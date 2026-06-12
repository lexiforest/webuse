import json
import os
import shutil
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

    def apply_settings(self, settings: dict[str, Any]) -> None:
        runtime = settings.get("runtime") if isinstance(settings.get("runtime"), dict) else {}
        concurrency = _positive_int(runtime.get("concurrency"))
        if concurrency is not None:
            self.concurrency = concurrency
        work_directory = runtime.get("workDirectory")
        if isinstance(work_directory, str) and work_directory:
            self.work_dir = Path(work_directory)
            self.work_dir.mkdir(parents=True, exist_ok=True)

    def project_checkout_dir(self, project_id: int) -> Path:
        return self.work_dir / "projects" / str(project_id) / "repo"

    def sync_git_project(self, project: dict[str, Any]) -> Path:
        if project.get("type") != "git":
            raise ValueError("Project is not a git project.")
        git_url = project.get("target")
        if not isinstance(git_url, str) or not git_url:
            raise ValueError("Git project is missing a repository URL.")

        checkout_dir = self.project_checkout_dir(int(project["id"]))
        if (checkout_dir / ".git").is_dir():
            _run_git(["remote", "set-url", "origin", git_url], cwd=checkout_dir)
            _run_git(["pull", "--ff-only"], cwd=checkout_dir)
            return checkout_dir

        if checkout_dir.exists():
            shutil.rmtree(checkout_dir)
        checkout_dir.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["clone", git_url, str(checkout_dir)], cwd=self.work_dir)
        return checkout_dir

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(self.poll_seconds)

    def _tick(self) -> None:
        self.store.enqueue_due_cron_jobs()
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
        project_dir = job_dir / "project"
        job_dir.mkdir(parents=True, exist_ok=True)
        project_dir.mkdir(parents=True, exist_ok=True)

        if project.get("type") == "git":
            project_dir = self.sync_git_project(project)
        else:
            _materialize_project_files(project, project_dir)

        stored_config_path = next(
            (project_dir / name for name in ("webuse.yaml", "webuse.yml") if (project_dir / name).exists()),
            None,
        )
        crawl_target = project_dir if project.get("type") == "git" and stored_config_path is None else (stored_config_path or job_dir / "spider.yaml")
        output_path = job_dir / "items.jsonl"
        if project.get("type") != "git" and stored_config_path is None:
            crawl_target.write_text(yaml.safe_dump(_normalize_config(project), sort_keys=False), encoding="utf-8")

        command = _crawl_command(["crawl", str(crawl_target), "-o", str(output_path)])
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


def _run_git(args: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalize_config(project: dict[str, Any]) -> dict[str, Any]:
    webuse_file = next(
        (
            file
            for file in project.get("files", [])
            if file.get("path") in {"webuse.yaml", "webuse.yml"}
        ),
        None,
    )
    if webuse_file is not None:
        config = yaml.safe_load(webuse_file["content"])
        return config if isinstance(config, dict) else {}

    config = dict(project.get("config") or {})
    if isinstance(config.get("spiders"), dict):
        return config
    return {
        "spiders": {
            "default": {
                "start_urls": [project["target"]],
                "pages": {
                    "default": {
                        "extract": {
                            "page": {
                                "fields": {"title": "title"},
                            },
                        },
                    },
                },
            },
        },
    }


def _materialize_project_files(project: dict[str, Any], project_dir: Path) -> None:
    root = project_dir.resolve()
    for file in project.get("files", []):
        file_path = (root / file["path"]).resolve()
        if root not in file_path.parents:
            raise ValueError(f"invalid project file path: {file['path']}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file["content"], encoding="utf-8")


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
