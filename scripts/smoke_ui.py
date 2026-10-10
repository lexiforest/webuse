"""Exercise an installed release, including assets, SQLite, and a real crawl.

Run with the Python interpreter of a fresh environment containing the wheel.
All HTTP traffic stays on loopback; no model or external website is needed.
"""

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from curl_cffi import requests


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
        self.model_requests.append(request)
        assert request["model"] == "smoke-model"
        assert request["stream"] is True
        calls = [
            ("read", {"path": "webuse.yaml"}),
            ("fetch_page", {"url": f"http://127.0.0.1:{self.server.server_port}/"}),
            ("write", {"path": "note.txt", "content": "Pi edited this workspace."}),
            ("run_python", {"code": "from pathlib import Path; print(Path('note.txt').read_text())"}),
            ("run_crawl", {"maxRequests": 1}),
        ]
        index = len(self.model_requests) - 1
        if index < len(calls):
            name, arguments = calls[index]
            delta = {"tool_calls": [{"index": 0, "id": f"call-{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
            finish = "tool_calls"
        else:
            delta = {"content": "The sample crawl succeeded."}
            finish = "stop"
        chunks = [
            {"id": "smoke", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", **delta}, "finish_reason": None}]},
            {"id": "smoke", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
        ]
        content = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_args):
        pass


def check_ui(directory: Path, target: str):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("WEBUSE_", "OPENAI_", "NITRO_"))
        and key not in {"PYTHONPATH", "PYTHONHOME", "HOST", "PORT"}
    }
    # Prevent crawler CLI provider discovery; this crawl only uses CSS selectors.
    env.update(OPENAI_API_KEY="local-smoke-unused", NO_PROXY="127.0.0.1,localhost")
    log = directory / "server.log"
    with log.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "webuse.cli", "ui", "--no-open",
             "--port", str(port), "--data-dir", str(directory / "state")],
            cwd=directory, env=env, stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            with requests.Session(trust_env=False) as client:
                deadline = time.monotonic() + 30
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
                assets = re.findall(r'(?:src|href)="(/[^"?#]+\.(?:js|css))', response.text)
                assert assets, "Rendered HTML must reference compiled frontend assets"
                for asset in assets:
                    response = client.get(base + asset, timeout=5)
                    response.raise_for_status()
                    assert "text/html" not in response.headers.get("content-type", "")
                    assert response.content

                def api(method, path, **kwargs):
                    result = client.request(method, base + path, timeout=5, **kwargs)
                    result.raise_for_status()
                    return result.json()

                config = (
                    f"name: smoke\nspiders:\n  smoke:\n    start_urls:\n      - {target}\n"
                    "    pages:\n      default:\n        extract:\n          page:\n"
                    "            fields:\n              title: h1\n"
                )
                project = api("POST", "/api/projects", json={
                    "name": "Release smoke", "type": "yaml", "target": target,
                    "files": [{"path": "webuse.yaml", "content": config}],
                })["project"]
                run = api("POST", "/api/runs", json={"projectId": project["id"]})["run"]
                deadline = time.monotonic() + 30
                while run["status"] in {"queued", "running"}:
                    assert time.monotonic() < deadline, "Packaged crawler timed out"
                    time.sleep(0.1)
                    run = api("GET", f"/api/runs?id={run['id']}")["run"]
                assert run["status"] == "succeeded", api("GET", f"/api/logs?run_id={run['id']}")
                items = api("GET", f"/api/data?run_id={run['id']}")["dataItems"]
                assert len(items) == 1, items
                assert items[0]["item"]["title"] == "Packaged UI smoke", items
                api("PUT", "/api/settings", json={"settings": {"llm": {
                    "baseUrl": target.rstrip("/") + "/v1", "model": "smoke-model", "apiKey": "local-smoke-unused",
                }}})
                result = client.post(base + "/api/assistant-project", json={
                    "projectId": project["id"], "message": "Inspect, edit, and test this crawler.",
                    "files": project["files"], "revision": project["revision"], "selectedPath": "webuse.yaml",
                }, timeout=60)
                result.raise_for_status()
                events = [json.loads(line) for line in result.text.splitlines() if line]
                final = events[-1]
                assert final["type"] == "result", events
                assert not final.get("error"), final
                assert final["changedFiles"] == ["note.txt"], final
                assert all(tool["status"] == "succeeded" for tool in final["toolResults"]), final
                assert any(event["type"] == "text" for event in events), events
                assert len(Page.model_requests) == 6, Page.model_requests
                tool_messages = [message for message in Page.model_requests[-1]["messages"] if message["role"] == "tool"]
                page_result = json.loads(tool_messages[1]["content"])
                assert page_result["status"] == 200, page_result
                assert "Packaged UI smoke" in page_result["html"], page_result
                python_result = json.loads(tool_messages[3]["content"])
                assert python_result["exitCode"] == 0, python_result
                assert "Pi edited this workspace" in python_result["output"], python_result
                refreshed = api("GET", f"/api/projects?id={project['id']}")["project"]
                assert refreshed["savedVersion"] == project["savedVersion"]
                assert (Path(refreshed["workspacePath"]) / "note.txt").read_text() == "Pi edited this workspace."
                crawl_result = json.loads(tool_messages[4]["content"])
                assert crawl_result["status"] == "succeeded", crawl_result
                assert crawl_result["records"][0]["title"] == "Packaged UI smoke", crawl_result
                history = api("GET", f"/api/assistant-project?project_id={project['id']}")
                assert history["messages"][-1]["metadata"]["toolResults"], history
                # Exercise the public workspace API, including conflicts and publication.
                stale = client.patch(base + f"/api/projects?id={project['id']}", json={
                    "files": project["files"], "revision": project["revision"],
                }, timeout=5)
                assert stale.status_code == 409, stale.text
                workspace_file = Path(refreshed["workspacePath"]) / "note.txt"
                assert workspace_file.exists()
                saved = api("PATCH", f"/api/projects?id={project['id']}", json={
                    "files": refreshed["files"] + [{"path": "editor.txt", "content": "saved on disk"}],
                    "revision": refreshed["revision"],
                })["project"]
                assert saved["savedVersion"] == project["savedVersion"]
                assert (Path(saved["workspacePath"]) / "editor.txt").read_text() == "saved on disk"
                published = api("PUT", f"/api/projects?id={project['id']}", json=saved)["project"]
                assert published["savedVersion"] != project["savedVersion"]
                workspace_file.write_text("external editor")
                changed = api("GET", f"/api/projects?id={project['id']}")["project"]
                assert changed["revision"] != published["revision"]
                reverted = api("PATCH", f"/api/projects?id={project['id']}", json={
                    "action": "revert", "revision": changed["revision"],
                })["project"]
                assert not reverted["changes"]
                assert workspace_file.read_text() == "Pi edited this workspace."
                assert (directory / "state" / "webuse-ui.sqlite").is_file()
        except BaseException:
            print(log.read_text(), file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="webuse-release-smoke-") as temporary:
            check_ui(Path(temporary), f"http://127.0.0.1:{server.server_port}/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print("Installed UI passed: assets, SQLite, crawler records, and Pi Chat tools/streaming.")


if __name__ == "__main__":
    main()
