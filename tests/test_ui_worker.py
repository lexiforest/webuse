import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from webuse.ui.db import Database
from webuse.ui.runner import Runner
from webuse.ui.server import _handler_class
from webuse.ui.store import Store


def _json_request(url: str, *, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={"content-type": "application/json"} if data is not None else {},
    )
    with urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def test_python_ui_worker_project_and_job_api(tmp_path: Path):
    store = Store(Database(tmp_path / "webuse.sqlite"))
    runner = Runner(store, work_dir=tmp_path / "jobs")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _handler_class(store=store, runner=runner, static_dir=None),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        assert _json_request(f"{base_url}/health") == {"ok": True}

        project = _json_request(f"{base_url}/projects", method="POST")["project"]
        assert project["name"] == "Books to Scrape"

        projects = _json_request(f"{base_url}/projects")["projects"]
        assert [item["id"] for item in projects] == [project["id"]]

        detail = _json_request(f"{base_url}/projects?id={project['id']}")["project"]
        assert detail["config"]["start_urls"] == ["https://books.toscrape.com/"]

        job = _json_request(
            f"{base_url}/jobs", method="POST", body={"projectId": project["id"]}
        )["job"]
        assert job["projectId"] == project["id"]
        assert job["status"] in {"queued", "running"}

        jobs = _json_request(f"{base_url}/jobs")["jobs"]
        assert jobs[0]["id"] == job["id"]

        assert "logs" in _json_request(f"{base_url}/logs")
        assert "dataItems" in _json_request(f"{base_url}/data")
    finally:
        server.shutdown()
        runner.stop()
        thread.join(timeout=2)


def test_python_ui_worker_validates_project_input(tmp_path: Path):
    store = Store(Database(tmp_path / "webuse.sqlite"))
    runner = Runner(store, work_dir=tmp_path / "jobs")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _handler_class(store=store, runner=runner, static_dir=None),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        try:
            _json_request(
                f"http://127.0.0.1:{server.server_port}/projects",
                method="POST",
                body={"name": "", "type": "source", "target": "https://example.com"},
            )
        except HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
            assert payload["error"] == "Project name is required."
        else:
            raise AssertionError("expected HTTP 400")
    finally:
        server.shutdown()
        runner.stop()
        thread.join(timeout=2)
