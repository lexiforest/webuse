import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from webuse.ui.db import Database
from webuse.ui.agent import (
    _preview_workflow,
    _project_context,
    _read_project_docs,
    _validate_webuse_yaml,
)
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


def test_project_assistant_skill_and_yaml_tools(tmp_path: Path):
    content = """name: books-project
spiders:
  books:
    start_urls:
      - https://books.toscrape.com/
    allowed_domains:
      - books.toscrape.com
    max_depth: 1
    pages:
      default:
        follow:
          - css: .product_pod h3 a
            category: detail
        extract:
          books:
            item_css: .product_pod
            fields:
              title:
                css: h3 a
                attr: title
              price: .price_color
      detail:
        extract:
          book_details:
            fields:
              title: h1
"""
    (tmp_path / "webuse.yaml").write_text(content, encoding="utf-8")

    docs = _read_project_docs("follow")
    assert docs["heading"] == "YAML Spider Config"
    assert "No `from` key is needed" in docs["content"]

    validation = _validate_webuse_yaml(tmp_path)
    assert validation["ok"] is True
    assert validation["summary"]["spiders"] == ["books"]
    assert validation["summary"]["startUrls"] == ["https://books.toscrape.com/"]
    assert validation["summary"]["pages"] == ["books.default", "books.detail"]

    preview = _preview_workflow(tmp_path)
    assert preview["ok"] is True
    assert "Page: detail" in preview["mermaid"]
    assert any(node["type"] == "database" for node in preview["graph"]["nodes"])

    context = _project_context(
        [{"path": "webuse.yaml", "content": content}],
        "webuse.yaml",
    )
    assert "- mode: yaml" in context
    assert "- spiders: books" in context
    assert "- follow_rules: 1" in context
    assert "- pages: books.default, books.detail" in context


def test_project_assistant_yaml_validation_reports_errors(tmp_path: Path):
    (tmp_path / "webuse.yaml").write_text(
        """start_urls:
  - https://example.com/
pages:
  default:
    follow:
      - attr: href
    extract: []
""",
        encoding="utf-8",
    )

    validation = _validate_webuse_yaml(tmp_path)

    assert validation["ok"] is False
    assert any("Extra inputs are not permitted" in item for item in validation["errors"])
    assert "webuse.yaml must define a non-empty spiders mapping" in validation["errors"]


def test_project_assistant_summarizes_inline_spider_extract_items(tmp_path: Path):
    (tmp_path / "webuse.yaml").write_text(
        """spiders:
  books:
    start_urls:
      - https://example.com/
    pages:
      default:
        extract:
          books:
            item_css: article.book
            fields:
              title: h1
          categories:
            item_css: nav a
            fields:
              name: .
""",
        encoding="utf-8",
    )

    validation = _validate_webuse_yaml(tmp_path)

    assert validation["ok"] is True
    assert validation["summary"]["pages"] == ["books.default"]
    assert validation["summary"]["itemTypes"] == {
        "books.default": ["books", "categories"]
    }


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
        assert detail["config"]["spiders"]["books"]["start_urls"] == ["https://books.toscrape.com/"]
        assert {file["path"] for file in detail["files"]} == {"spiders/books.py", "webuse.yaml"}

        job = _json_request(
            f"{base_url}/jobs", method="POST", body={"projectId": project["id"]}
        )["job"]
        assert job["projectId"] == project["id"]
        assert job["status"] in {"queued", "running"}

        other_project = _json_request(
            f"{base_url}/projects",
            method="POST",
            body={
                "name": "Example",
                "type": "source",
                "target": "https://example.com",
                "cron": "0 * * * *",
                "config": {
                    "spiders": {
                        "default": {
                            "start_urls": ["https://example.com"],
                        },
                    },
                },
                "files": [
                    {
                        "path": "webuse.yaml",
                        "content": "spiders:\n  default:\n    start_urls:\n      - https://example.com\n",
                    }
                ],
            },
        )["project"]
        assert other_project["cron"] == "0 * * * *"
        assert other_project["nextRunAt"]
        other_detail = _json_request(f"{base_url}/projects?id={other_project['id']}")["project"]
        assert other_detail["cron"] == "0 * * * *"
        assert other_detail["nextRunAt"]
        assert other_detail["files"] == [
            {
                "path": "webuse.yaml",
                "content": "spiders:\n  default:\n    start_urls:\n      - https://example.com\n",
            }
        ]
        other_job = _json_request(
            f"{base_url}/jobs", method="POST", body={"projectId": other_project["id"]}
        )["job"]

        jobs = _json_request(f"{base_url}/jobs")["jobs"]
        assert {item["id"] for item in jobs} == {job["id"], other_job["id"]}

        project_jobs = _json_request(
            f"{base_url}/jobs?project_id={project['id']}"
        )["jobs"]
        assert [item["projectId"] for item in project_jobs] == [project["id"]]

        store.append_log(job["id"], "stderr", "first project log")
        store.append_log(job["id"], "stdout", "second project log")
        store.append_log(job["id"], "stdout", "third project log")
        store.append_log(other_job["id"], "stdout", "other project log")
        run_logs_response = _json_request(f"{base_url}/logs?run_id={job['id']}&limit=2")
        assert run_logs_response["total"] == 3
        assert [item["message"] for item in run_logs_response["logs"]] == [
            "first project log",
            "second project log",
        ]
        next_run_logs = _json_request(
            f"{base_url}/logs?run_id={job['id']}&limit=2&offset=2"
        )["logs"]
        assert [item["message"] for item in next_run_logs] == ["third project log"]

        store.insert_data_item(job["id"], {"url": "https://example.com/one", "title": "One"})
        store.insert_data_item(other_job["id"], {"url": "https://example.com/two", "title": "Two"})
        run_data = _json_request(f"{base_url}/data?run_id={job['id']}")["dataItems"]
        assert [item["item"]["title"] for item in run_data] == ["One"]
    finally:
        server.shutdown()
        runner.stop()
        thread.join(timeout=2)


def test_python_ui_worker_supports_api_aliases(tmp_path: Path, monkeypatch):
    store = Store(Database(tmp_path / "webuse.sqlite"))
    runner = Runner(store, work_dir=tmp_path / "jobs")

    def fake_assistant(**kwargs):
        return {
            "content": "Updated webuse.yaml.",
            "files": [
                {
                    "path": "webuse.yaml",
                    "content": "spiders:\n  default:\n    start_urls:\n      - https://example.com/\n",
                }
            ],
            "changedFiles": ["webuse.yaml"],
            "selectedPath": "webuse.yaml",
            "toolResults": [],
        }

    monkeypatch.setattr("webuse.ui.server.run_project_assistant", fake_assistant)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _handler_class(store=store, runner=runner, static_dir=None),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        project = _json_request(f"{base_url}/api/projects", method="POST")["project"]
        assert project["name"] == "Books to Scrape"

        history = _json_request(
            f"{base_url}/api/assistant-project?project_id={project['id']}"
        )
        assert history["session"]["projectId"] == project["id"]
        assert history["messages"] == []

        response = _json_request(
            f"{base_url}/api/assistant-project",
            method="POST",
            body={
                "projectId": project["id"],
                "sessionId": history["session"]["id"],
                "message": "Change the start URL",
                "files": project["files"],
                "selectedPath": "webuse.yaml",
            },
        )
        assert response["message"]["content"] == "Updated webuse.yaml."
        assert response["changedFiles"] == ["webuse.yaml"]
        assert response["files"][0]["content"] == "spiders:\n  default:\n    start_urls:\n      - https://example.com/\n"
    finally:
        server.shutdown()
        runner.stop()
        thread.join(timeout=2)


def test_python_ui_worker_settings_save_and_apply(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
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
        payload = _json_request(f"{base_url}/settings")
        assert payload["settings"]["runtime"]["databasePath"] == ""
        assert payload["settings"]["runtime"]["workDirectory"] == ""
        assert payload["settings"]["runtime"]["concurrency"] == ""
        assert payload["settings"]["llm"]["baseUrl"] == ""
        assert payload["settings"]["llm"]["model"] == ""
        assert payload["settings"]["smart"]["selectorStore"] == ""
        assert payload["effectiveSettings"]["smart"]["selectorStore"] == "selectors.json"

        updated = _json_request(
            f"{base_url}/settings",
            method="PUT",
            body={
                "settings": {
                    "runtime": {
                        "databasePath": "./webuse.sqlite",
                        "workDirectory": str(tmp_path / "applied-jobs"),
                        "concurrency": "3",
                    },
                    "llm": {
                        "apiKey": "test-key",
                        "baseUrl": "https://llm.example.com/v1",
                        "model": "configured-model",
                    },
                    "smart": {"selectorStore": "selectors.json"},
                }
            },
        )

        assert updated["settings"]["llm"]["model"] == "configured-model"
        assert updated["effectiveSettings"]["llm"]["model"] == "configured-model"
        assert runner.concurrency == 3
        assert runner.work_dir == tmp_path / "applied-jobs"
        assert (tmp_path / ".webuserc.yaml").exists()
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

        try:
            _json_request(
                f"http://127.0.0.1:{server.server_port}/projects",
                method="POST",
                body={
                    "name": "Bad Schedule",
                    "type": "source",
                    "target": "https://example.com",
                    "cron": "not a cron",
                },
            )
        except HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode("utf-8"))
            assert payload["error"] == "Project cron must be a valid cron expression."
        else:
            raise AssertionError("expected HTTP 400")
    finally:
        server.shutdown()
        runner.stop()
        thread.join(timeout=2)


def test_python_ui_worker_enqueues_due_cron_project(tmp_path: Path):
    store = Store(Database(tmp_path / "webuse.sqlite"))
    project = store.create_project(
        {
            "name": "Scheduled",
            "type": "source",
            "target": "https://example.com",
            "cron": "* * * * *",
            "config": {
                "spiders": {
                    "default": {"start_urls": ["https://example.com"]},
                },
            },
            "files": [],
        }
    )
    due_at = 1_800_000_000_000
    store.db.execute(
        "UPDATE projects SET next_run_at = ? WHERE id = ?",
        (due_at - 1, project["id"]),
    )

    jobs = store.enqueue_due_cron_jobs(due_at)

    assert len(jobs) == 1
    assert jobs[0]["projectId"] == project["id"]
    assert jobs[0]["status"] == "queued"
    assert jobs[0]["metadata"]["scheduled"] is True
    assert jobs[0]["metadata"]["cron"] == "* * * * *"

    updated = store.db.one("SELECT next_run_at FROM projects WHERE id = ?", (project["id"],))
    assert updated["next_run_at"] > due_at
    assert store.enqueue_due_cron_jobs(due_at) == []


def test_python_ui_worker_backfills_missing_next_run_at(tmp_path: Path):
    store = Store(Database(tmp_path / "webuse.sqlite"))
    project = store.create_project(
        {
            "name": "Migrated",
            "type": "source",
            "target": "https://example.com",
            "cron": "0 * * * *",
            "config": {
                "spiders": {
                    "default": {"start_urls": ["https://example.com"]},
                },
            },
            "files": [],
        }
    )
    store.db.execute("UPDATE projects SET next_run_at = NULL WHERE id = ?", (project["id"],))

    store.ensure_cron_schedules(1_800_000_000_000)

    updated = store.db.one("SELECT next_run_at FROM projects WHERE id = ?", (project["id"],))
    assert updated["next_run_at"] is not None
