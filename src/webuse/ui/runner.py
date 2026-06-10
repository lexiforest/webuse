import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import yaml

from .store import Store


class Runner:
    def __init__(
        self,
        store: Store,
        *,
        work_dir: Path,
        concurrency: int | None = None,
        poll_ms: int | None = None,
    ):
        self.store = store
        self.work_dir = work_dir
        self.concurrency = max(1, concurrency or int(os.environ.get("WEBUSE_WORKER_CONCURRENCY", "1")))
        self.poll_seconds = max(0.25, (poll_ms or int(os.environ.get("WEBUSE_WORKER_POLL_MS", "1000"))) / 1000)
        self._active: dict[int, subprocess.Popen[str]] = {}
        self._running = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.store.reconcile_running_jobs()
        self._thread = threading.Thread(target=self._loop, name="webuse-ui-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            children = list(self._active.values())
        for child in children:
            child.terminate()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def cancel_running_job(self, job_id: int) -> bool:
        with self._lock:
            child = self._active.get(job_id)
        if child is None:
            return False
        child.terminate()
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(self.poll_seconds)

    def _tick(self) -> None:
        while True:
            with self._lock:
                if self._running >= self.concurrency:
                    return
                self._running += 1
            job = self.store.claim_job()
            if not job:
                with self._lock:
                    self._running -= 1
                return
            threading.Thread(
                target=self._run_job_safe,
                args=(job,),
                name=f"webuse-job-{job['id']}",
                daemon=True,
            ).start()

    def _run_job_safe(self, job: dict[str, Any]) -> None:
        try:
            self._run_job(job)
        except Exception as exc:
            self.store.append_log(job["id"], "stderr", str(exc))
            self.store.finish_job(job["id"], "failed", {"reason": "worker_error"})
        finally:
            with self._lock:
                self._running -= 1

    def _run_job(self, job: dict[str, Any]) -> None:
        project = self.store.get_project(job["projectId"])
        if not project:
            self.store.append_log(job["id"], "stderr", f"project not found: {job['projectId']}")
            self.store.finish_job(job["id"], "failed", {"reason": "project_not_found"})
            return

        job_dir = self.work_dir / str(job["id"])
        job_dir.mkdir(parents=True, exist_ok=True)
        config_path = job_dir / "spider.yaml"
        output_path = job_dir / "items.jsonl"
        config_path.write_text(yaml.safe_dump(_normalize_config(project), sort_keys=False), encoding="utf-8")

        command = _crawl_command(["crawl", str(config_path), "-o", str(output_path)])
        command_text = " ".join(command)
        self.store.update_job_command(job["id"], command_text)
        self.store.append_log(job["id"], "stdout", command_text)

        child = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        with self._lock:
            self._active[job["id"]] = child
        try:
            stdout_thread = threading.Thread(
                target=_pipe_lines,
                args=(child.stdout, lambda line: self.store.append_log(job["id"], "stdout", line)),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_pipe_lines,
                args=(child.stderr, lambda line: self.store.append_log(job["id"], "stderr", line)),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            code = child.wait()
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
        finally:
            with self._lock:
                self._active.pop(job["id"], None)

        if code < 0:
            self.store.append_log(job["id"], "stderr", f"crawl terminated by signal {-code}")
            self.store.finish_job(job["id"], "cancelled", {"reason": "signal", "signal": -code, "outputPath": str(output_path)})
            return
        if code != 0:
            self.store.append_log(job["id"], "stderr", f"crawl exited with code {code}")
            self.store.finish_job(job["id"], "failed", {"reason": "exit_code", "code": code, "outputPath": str(output_path)})
            return

        item_count = _import_jsonl(self.store, job["id"], output_path) if output_path.exists() else 0
        self.store.append_log(job["id"], "stdout", f"imported {item_count} item{'s' if item_count != 1 else ''}")
        self.store.finish_job(job["id"], "succeeded", {"outputPath": str(output_path), "itemCount": item_count})


def _crawl_command(args: list[str]) -> list[str]:
    command = os.environ.get("WEBUSE_WORKER_COMMAND")
    if command:
        prefix = json.loads(os.environ.get("WEBUSE_WORKER_COMMAND_ARGS", "[]"))
        return [command, *prefix, *args]
    return [sys.executable, "-m", "webuse.cli", *args]


def _normalize_config(project: dict[str, Any]) -> dict[str, Any]:
    config = dict(project.get("config") or {})
    if isinstance(config.get("start_urls"), list):
        return config
    crawl = config.get("crawl")
    if isinstance(crawl, dict):
        normalized = dict(crawl)
        if isinstance(crawl.get("seeds"), list) and not isinstance(crawl.get("start_urls"), list):
            normalized["start_urls"] = crawl["seeds"]
            normalized.pop("seeds", None)
        return normalized
    return {
        "start_urls": [project["target"]],
        "extract": {"fields": {"title": "title"}},
    }


def _pipe_lines(stream: Any, callback: Any) -> None:
    if stream is None:
        return
    for line in stream:
        line = line.rstrip("\r\n")
        if line:
            callback(line)


def _import_jsonl(store: Store, job_id: int, output_path: Path) -> int:
    store.clear_data_items(job_id)
    count = 0
    with output_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            store.insert_data_item(job_id, json.loads(line))
            count += 1
    return count
