"""Exercise an installed release, including assets, SQLite, and a real crawl.

Run with the Python interpreter of a fresh environment containing the wheel.
All HTTP traffic stays on loopback; no model or external website is needed.
"""

import argparse
import difflib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from curl_cffi import requests
from webuse.resources import framework_info


class Page(BaseHTTPRequestHandler):
    model_requests = []

    def do_GET(self):
        content = b"<html><body><h1>Packaged UI smoke</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        assert self.path == "/v1/chat/completions", self.path
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if request.get("tools"):
            self.model_requests.append(request)
        assert request["model"] == "smoke-model"
        assert request["stream"] is True
        workspace = next(
            (
                json.loads(message["content"])
                for message in request["messages"]
                if message.get("role") == "tool"
                and message.get("tool_call_id") == "call-0"
            ),
            {},
        )
        docs_root = workspace.get("framework", {}).get("docs", {}).get("root", "")
        calls = [
            ("workspace_info", {}),
            ("read", {"path": workspace.get("skill", "")}),
            ("read", {"path": str(Path(docs_root) / "user-guide/quick-start.md")}),
            ("read", {"path": "webuse.yaml"}),
            ("fetch_page", {"url": f"http://127.0.0.1:{self.server.server_port}/"}),
            ("write", {"path": "note.txt", "content": "Pi edited this workspace."}),
            (
                "run_python",
                {
                    "code": "from pathlib import Path; print(Path('note.txt').read_text())"
                },
            ),
            ("run_crawl", {"maxRequests": 1}),
        ]
        index = len(self.model_requests) - 1
        if index < len(calls):
            name, arguments = calls[index]
            delta = {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": f"call-{index}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ]
            }
            finish = "tool_calls"
        else:
            delta = {"content": "The sample crawl succeeded."}
            finish = "stop"
        chunks = [
            {
                "id": "smoke",
                "object": "chat.completion.chunk",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", **delta},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "smoke",
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            },
        ]
        content = (
            "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_args):
        pass


def context_snapshot(model_requests: list[dict], workspace: dict) -> dict:
    """Capture actual model inputs; normalize only the two per-run fixture paths."""
    replacements = {
        workspace["directory"]: "<PROJECT_WORKSPACE>",
        workspace["skill"]: "<WEBUSE_SKILL>",
    }

    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, str):
            for path, label in replacements.items():
                # Tool results and arguments also contain JSON-encoded paths.
                value = value.replace(json.dumps(path)[1:-1], label).replace(
                    path, label
                )
        return value

    return normalize({"initial": model_requests[0], "after_docs": model_requests[3]})


def assert_context_parity(packaged: dict, development: dict):
    if packaged != development:
        difference = difflib.unified_diff(
            json.dumps(packaged, indent=2, sort_keys=True).splitlines(),
            json.dumps(development, indent=2, sort_keys=True).splitlines(),
            fromfile="packaged Harness context",
            tofile="development Harness context",
            lineterm="",
        )
        raise AssertionError("Harness context differs:\n" + "\n".join(difference))


def assert_packaged_docs(dev_ui: Path):
    """Catch missing or stale pages in the installed distribution, not just paths."""
    info = framework_info()
    installed = Path(info["docs"]["root"])
    assert installed == Path(info["source"]) / "_docs", (
        "Run parity checks with an installed wheel's Python, not an editable install"
    )
    source = dev_ui.parent / "docs/src/content/docs"
    assert source.is_dir(), source

    def pages(root):
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*.md")
        }

    assert pages(installed) == pages(source), (
        "Packaged Markdown differs from the checkout; rebuild the wheel"
    )


def check_ui(directory: Path, target: str, dev_ui: Path | None = None):
    Page.model_requests = []
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("WEBUSE_", "OPENAI_", "NITRO_"))
        and key not in {"PYTHONPATH", "PYTHONHOME", "HOST", "PORT"}
    }
    # Prevent crawler CLI provider discovery; this crawl only uses CSS selectors.
    env.update(OPENAI_API_KEY="local-smoke-unused", NO_PROXY="127.0.0.1,localhost")
    log = directory / "server.log"
    with log.open("w") as output:
        command = [
            sys.executable,
            "-m",
            "webuse.cli",
            "serve",
            "--no-open",
            "--port",
            str(port),
            "--data-dir",
            str(directory / "state"),
        ]
        if dev_ui:
            command = [
                "npm",
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
            env.update(
                WEBUSE_PYTHON_COMMAND=sys.executable,
                WEBUSE_DB_PATH=str(directory / "state/webuse.db"),
                WEBUSE_WORK_DIR=str(directory / "executions"),
                WEBUSE_WORKSPACE_DIR=str(directory / "workspaces"),
                WEBUSE_CONFIG_DIR=str(directory),
                PORT=str(port),
            )
        process = subprocess.Popen(
            command,
            cwd=dev_ui or directory,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        try:
            with requests.Session(trust_env=False) as client:
                deadline = time.monotonic() + 90
                while True:
                    if process.poll() is not None:
                        raise AssertionError("Packaged UI exited during startup")
                    try:
                        response = client.get(base + "/", timeout=1)
                        response.raise_for_status()
                        break
                    except requests.RequestsError:
                        if time.monotonic() > deadline:
                            raise AssertionError("Packaged UI did not start")
                        time.sleep(0.1)
                assert "<html" in response.text.lower()
                assets = re.findall(
                    r'(?:src|href)="(/[^"?#]+\.(?:js|css))', response.text
                )
                if dev_ui:
                    assets = ["/@vite/client"]
                assert assets, "Rendered HTML must reference frontend assets"
                for asset in assets:
                    response = client.get(base + asset, timeout=5)
                    response.raise_for_status()
                    assert "text/html" not in response.headers.get("content-type", "")
                    assert response.content

                def api(method, path, **kwargs):
                    result = client.request(
                        method, base + path, timeout=30 if dev_ui else 5, **kwargs
                    )
                    result.raise_for_status()
                    return result.json()

                config = (
                    f"name: smoke\nspiders:\n  smoke:\n    start_urls:\n      - {target}\n"
                    "    pages:\n      default:\n        extract:\n          page:\n"
                    "            fields:\n              title: h1\n"
                )
                project = api(
                    "POST",
                    "/api/projects",
                    json={
                        "name": "Release smoke",
                        "target": target,
                        "files": [{"path": "webuse.yaml", "content": config}],
                    },
                )["project"]
                execution = api(
                    "POST", "/api/executions", json={"projectId": project["id"]}
                )["execution"]
                deadline = time.monotonic() + 90
                while execution["status"] in {"queued", "running"}:
                    assert time.monotonic() < deadline, "Packaged crawler timed out"
                    time.sleep(0.1)
                    execution = api("GET", f"/api/executions?id={execution['id']}")[
                        "execution"
                    ]
                assert execution["status"] == "succeeded", api(
                    "GET", f"/api/logs?execution_id={execution['id']}"
                )
                items = api("GET", f"/api/data?execution_id={execution['id']}")[
                    "dataItems"
                ]
                assert len(items) == 1, items
                assert items[0]["item"]["title"] == "Packaged UI smoke", items
                api(
                    "PUT",
                    "/api/settings",
                    json={
                        "settings": {
                            "llm": {
                                "baseUrl": target.rstrip("/") + "/v1",
                                "model": "smoke-model",
                                "contextWindow": "131072",
                                "maxOutputTokens": "8192",
                                "apiKey": "local-smoke-unused",
                            }
                        }
                    },
                )
                result = client.post(
                    base + "/api/assistant-project",
                    json={
                        "projectId": project["id"],
                        "message": "Inspect, edit, and test this crawler.",
                        "files": project["files"],
                        "revision": project["revision"],
                        "selectedPath": "webuse.yaml",
                    },
                    timeout=60,
                )
                result.raise_for_status()
                events = [json.loads(line) for line in result.text.splitlines() if line]
                final = events[-1]
                assert final["type"] == "result", events
                assert not final.get("error"), final
                assert final["changedFiles"] == ["note.txt"], final
                assert all(
                    tool["status"] == "succeeded" for tool in final["toolResults"]
                ), final
                assert any(event["type"] == "text" for event in events), events
                assert len(Page.model_requests) == 9, Page.model_requests
                tool_messages = [
                    message
                    for message in Page.model_requests[-1]["messages"]
                    if message["role"] == "tool"
                ]
                workspace = json.loads(tool_messages[0]["content"])
                discovered = workspace["framework"]
                expected = framework_info()
                assert discovered == expected, (discovered, expected)
                skill = Path(workspace["skill"]).read_text(encoding="utf-8")
                assert skill in tool_messages[1]["content"], (
                    "The model must receive the complete installed skill"
                )
                assert "webuse gen books" in tool_messages[2]["content"], tool_messages[
                    2
                ]
                snapshot = context_snapshot(Page.model_requests, workspace)
                page_result = json.loads(tool_messages[4]["content"])
                assert page_result["status"] == 200, page_result
                assert "Packaged UI smoke" in page_result["html"], page_result
                python_result = json.loads(tool_messages[6]["content"])
                assert python_result["exitCode"] == 0, python_result
                assert "Pi edited this workspace" in python_result["output"], (
                    python_result
                )
                refreshed = api("GET", f"/api/projects?id={project['id']}")["project"]
                assert (
                    Path(refreshed["workspacePath"]) / "note.txt"
                ).read_text() == "Pi edited this workspace."
                crawl_result = json.loads(tool_messages[7]["content"])
                assert crawl_result["status"] == "succeeded", crawl_result
                assert crawl_result["records"][0]["title"] == "Packaged UI smoke", (
                    crawl_result
                )
                history = api(
                    "GET", f"/api/assistant-project?project_id={project['id']}"
                )
                assert history["messages"][-1]["metadata"]["toolResults"], history
                # Exercise the public workspace API, including conflict detection.
                stale = client.patch(
                    base + f"/api/projects?id={project['id']}",
                    json={
                        "files": project["files"],
                        "revision": project["revision"],
                    },
                    timeout=5,
                )
                assert stale.status_code == 409, stale.text
                workspace_file = Path(refreshed["workspacePath"]) / "note.txt"
                assert workspace_file.exists()
                saved = api(
                    "PATCH",
                    f"/api/projects?id={project['id']}",
                    json={
                        "files": refreshed["files"]
                        + [{"path": "editor.txt", "content": "saved on disk"}],
                        "revision": refreshed["revision"],
                    },
                )["project"]
                assert (
                    Path(saved["workspacePath"]) / "editor.txt"
                ).read_text() == "saved on disk"
                updated = api("PUT", f"/api/projects?id={project['id']}", json=saved)[
                    "project"
                ]
                assert updated["workspacePath"] == project["workspacePath"]
                workspace_file.write_text("external editor")
                changed = api("GET", f"/api/projects?id={project['id']}")["project"]
                assert changed["revision"] != updated["revision"]
                assert workspace_file.read_text() == "external editor"
                assert (directory / "state" / "webuse.db").is_file()
        except BaseException:
            print(log.read_text(), file=sys.stderr)
            raise
        finally:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dev-ui",
        type=Path,
        help="Run npm dev from this UI directory using this Python installation",
    )
    modes.add_argument(
        "--compare-dev",
        type=Path,
        metavar="UI_DIRECTORY",
        help="Run the packaged and dev servers and compare the actual Harness model context",
    )
    args = parser.parse_args()
    info = framework_info()
    assert info["docs"], info
    assert (Path(info["docs"]["root"]) / "user-guide/quick-start.md").is_file()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="webuse-release-smoke-") as temporary:
            target = f"http://127.0.0.1:{server.server_port}/"
            root = Path(temporary)
            if args.compare_dev:
                dev_ui = args.compare_dev.resolve()
                assert_packaged_docs(dev_ui)
                packaged = check_ui(root / "packaged", target)
                development = check_ui(root / "development", target, dev_ui)
                assert_context_parity(packaged, development)
                print(
                    "Harness context parity passed: initial request, system prompt, tool schemas, skill, documentation, and discovery results."
                )
            else:
                check_ui(root, target, args.dev_ui.resolve() if args.dev_ui else None)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print(
        "UI passed: assets, SQLite, crawler records, installed framework docs, and Pi Harness tools/streaming."
    )


if __name__ == "__main__":
    main()
