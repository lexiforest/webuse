"""Exercise an installed release, including assets, SQLite, and a real crawl.

Run with the Python interpreter of a fresh environment containing the wheel.
All HTTP traffic stays on loopback; no model or external website is needed.
"""

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
    def do_GET(self):
        content = b"<html><body><h1>Packaged UI smoke</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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
    print("Installed UI passed: HTML, compiled assets, SQLite, crawler, and extracted records.")


if __name__ == "__main__":
    main()
