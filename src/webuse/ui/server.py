import json
import mimetypes
import os
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..config import (
    local_config_path,
    save_local_webuse_settings,
    user_config_path,
    webuse_local_settings,
    webuse_settings_from_config,
)
from .agent import run_project_assistant
from .db import Database, default_db_path, default_work_dir
from .runner import Runner
from .schedule import valid_cron
from .store import Store


def serve_ui(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    db_path: Path | None = None,
    work_dir: Path | None = None,
    static_dir: Path | None = None,
    open_browser: bool = False,
) -> None:
    db_path = db_path or default_db_path()
    work_dir = work_dir or default_work_dir(db_path)
    static_dir = static_dir or _default_static_dir()

    store = Store(Database(db_path))
    runner = Runner(store, work_dir=work_dir)
    runner.apply_settings(webuse_settings_from_config())
    runner.start()

    handler = _handler_class(store=store, runner=runner, static_dir=static_dir)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"webuse ui listening on {url}")
    print(f"database: {db_path}")
    print(f"work dir: {work_dir}")
    if static_dir and static_dir.exists():
        print(f"static: {static_dir}")
    else:
        print("static: not found; serving API and a minimal status page")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()
        server.server_close()


def _default_static_dir() -> Path | None:
    env = os.environ.get("WEBUSE_UI_STATIC_DIR")
    if env:
        return Path(env)
    candidate = Path(__file__).with_name("static")
    return candidate if candidate.exists() else None


def _handler_class(*, store: Store, runner: Runner, static_dir: Path | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "webuse-ui/0.1"

        def do_GET(self) -> None:
            if self.path_only == "/health":
                return self._json({"ok": True})
            if self.path_only == "/settings":
                return self._json(_settings_payload())
            if self.path_only == "/projects":
                project_id = self._id_param()
                if project_id is not None:
                    project = store.get_project(project_id)
                    return self._json({"project": project} if project else {"error": "Project not found."}, HTTPStatus.OK if project else HTTPStatus.NOT_FOUND)
                return self._json({"projects": store.list_projects()})
            if self.path_only == "/jobs":
                job_id = self._id_param()
                if job_id is not None:
                    job = store.get_job(job_id)
                    return self._json({"job": job} if job else {"error": "Job not found."}, HTTPStatus.OK if job else HTTPStatus.NOT_FOUND)
                return self._json({"jobs": store.list_jobs(self._query_int("project_id"))})
            if self.path_only == "/logs":
                run_id = self._run_id_param()
                limit = self._query_int("limit") or 100
                offset = self._query_int("offset") or 0
                return self._json(
                    {
                        "logs": store.list_logs(run_id, limit=limit, offset=offset),
                        "total": store.count_logs(run_id),
                    }
                )
            if self.path_only == "/data":
                return self._json({"dataItems": store.list_data_items(self._run_id_param())})
            if self.path_only == "/assistant/project":
                project_id = self._query_int("project_id")
                if project_id is None:
                    return self._json({"error": "A valid project_id is required."}, HTTPStatus.BAD_REQUEST)
                session = store.get_or_create_assistant_session(project_id)
                if not session:
                    return self._json({"error": "Project not found."}, HTTPStatus.NOT_FOUND)
                return self._json({"session": session, "messages": store.list_assistant_messages(session["id"])})
            return self._static()

        def do_POST(self) -> None:
            if self.path_only == "/projects":
                body = self._read_json(required=False)
                if body is None:
                    return self._json({"project": store.create_books_to_scrape_project()}, HTTPStatus.CREATED)
                result = _validate_project_input(body)
                if "error" in result:
                    return self._json({"error": result["error"]}, HTTPStatus.BAD_REQUEST)
                project = store.create_project(result["input"])
                if project.get("type") == "git":
                    try:
                        runner.sync_git_project(project)
                    except Exception as exc:
                        store.delete_project(project["id"])
                        return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return self._json({"project": project}, HTTPStatus.CREATED)
            if self.path_only == "/jobs":
                body = self._read_json(required=True)
                project_id = _positive_int((body or {}).get("projectId"))
                if project_id is None:
                    return self._json({"error": "A valid projectId is required."}, HTTPStatus.BAD_REQUEST)
                job = store.create_job(project_id)
                return self._json({"job": job} if job else {"error": "Project not found."}, HTTPStatus.CREATED if job else HTTPStatus.NOT_FOUND)
            if self.path_only == "/assistant/project":
                body = self._read_json(required=True)
                project_id = _positive_int((body or {}).get("projectId"))
                if project_id is None:
                    return self._json({"error": "A valid projectId is required."}, HTTPStatus.BAD_REQUEST)
                if not store.get_project(project_id):
                    return self._json({"error": "Project not found."}, HTTPStatus.NOT_FOUND)
                message = (body or {}).get("message")
                if not isinstance(message, str) or not message.strip():
                    return self._json({"error": "Assistant message is required."}, HTTPStatus.BAD_REQUEST)
                files_result = _validate_assistant_files((body or {}).get("files"))
                if "error" in files_result:
                    return self._json({"error": files_result["error"]}, HTTPStatus.BAD_REQUEST)
                requested_session = store.get_assistant_session(_positive_int((body or {}).get("sessionId")) or 0)
                session = (
                    requested_session
                    if requested_session and requested_session["projectId"] == project_id
                    else store.get_or_create_assistant_session(project_id)
                )
                if not session:
                    return self._json({"error": "Project not found."}, HTTPStatus.NOT_FOUND)
                history = store.list_assistant_messages(session["id"])
                user_content = message.strip()
                store.append_assistant_message(session["id"], "user", user_content)
                try:
                    result = run_project_assistant(
                        project_id=project_id,
                        session_id=session["id"],
                        files=files_result["files"],
                        selected_path=(body or {}).get("selectedPath") if isinstance((body or {}).get("selectedPath"), str) else None,
                        history=history,
                        user_message=user_content,
                        work_dir=runner.work_dir,
                    )
                except Exception as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                store.append_assistant_message(
                    session["id"],
                    "assistant",
                    result["content"],
                    {"changedFiles": result["changedFiles"], "toolResults": result["toolResults"]},
                )
                return self._json(
                    {
                        "session": session,
                        "message": {
                            "role": "assistant",
                            "content": result["content"],
                            "metadata": {
                                "changedFiles": result["changedFiles"],
                                "toolResults": result["toolResults"],
                            },
                        },
                        "messages": store.list_assistant_messages(session["id"]),
                        "files": result["files"],
                        "changedFiles": result["changedFiles"],
                        "selectedPath": result["selectedPath"],
                        "toolResults": result["toolResults"],
                    }
                )
            return self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

        def do_PUT(self) -> None:
            if self.path_only == "/settings":
                body = self._read_json(required=True)
                settings = body.get("settings") if isinstance(body, dict) else None
                if not isinstance(settings, dict):
                    return self._json({"error": "Settings body is required."}, HTTPStatus.BAD_REQUEST)
                payload = save_local_webuse_settings(settings)
                runner.apply_settings(payload["effectiveSettings"])
                return self._json(payload)
            if self.path_only != "/projects":
                return self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            project_id = self._id_param()
            if project_id is None:
                return self._json({"error": "A valid project id is required."}, HTTPStatus.BAD_REQUEST)
            result = _validate_project_input(self._read_json(required=True))
            if "error" in result:
                return self._json({"error": result["error"]}, HTTPStatus.BAD_REQUEST)
            project = store.update_project(project_id, result["input"])
            if project and project.get("type") == "git":
                try:
                    runner.sync_git_project(project)
                except Exception as exc:
                    return self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return self._json({"project": project} if project else {"error": "Project not found."}, HTTPStatus.OK if project else HTTPStatus.NOT_FOUND)

        def do_DELETE(self) -> None:
            if self.path_only == "/projects":
                project_id = self._id_param()
                if project_id is None:
                    return self._json({"error": "A valid project id is required."}, HTTPStatus.BAD_REQUEST)
                store.delete_project(project_id)
                return self._json({"ok": True})
            if self.path_only == "/jobs":
                job_id = self._id_param()
                if job_id is None:
                    return self._json({"error": "A valid job id is required."}, HTTPStatus.BAD_REQUEST)
                cancelled = store.cancel_queued_job(job_id) or runner.cancel_running_job(job_id)
                return self._json({"ok": cancelled})
            return self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

        @property
        def parsed_url(self):
            return urlparse(self.path)

        @property
        def path_only(self) -> str:
            path = self.parsed_url.path.rstrip("/") or "/"
            if path == "/api/assistant-project":
                return "/assistant/project"
            if path.startswith("/api/"):
                return path[4:]
            return path

        def _id_param(self) -> int | None:
            return self._query_int("id")

        def _run_id_param(self) -> int | None:
            return self._query_int("run_id") or self._query_int("id")

        def _query_int(self, name: str) -> int | None:
            values = parse_qs(self.parsed_url.query).get(name)
            return _positive_int(values[0]) if values else None

        def _read_json(self, *, required: bool) -> dict | None:
            length = int(self.headers.get("content-length", "0") or "0")
            if length <= 0:
                return {} if required else None
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _json(self, body: dict, status: int = HTTPStatus.OK) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _static(self) -> None:
            if static_dir is None or not static_dir.exists():
                return self._minimal_page()
            relative = self.path_only.lstrip("/") or "index.html"
            path = (static_dir / relative).resolve()
            root = static_dir.resolve()
            if not str(path).startswith(str(root)) or not path.exists() or path.is_dir():
                path = root / "index.html"
            if not path.exists():
                return self._minimal_page()
            payload = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _minimal_page(self) -> None:
            payload = (
                "<!doctype html><title>webuse</title>"
                "<h1>webuse ui</h1>"
                "<p>Python worker is running. Build UI assets or run the SolidStart dev server to use the full interface.</p>"
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def _positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _settings_payload() -> dict:
    return {
        "settings": webuse_local_settings(),
        "effectiveSettings": webuse_settings_from_config(),
        "paths": {"local": str(local_config_path()), "user": str(user_config_path())},
    }


def _validate_project_input(body: dict | None) -> dict:
    if not isinstance(body, dict):
        return {"error": "Project body is required."}
    name = body.get("name")
    project_type = body.get("type")
    target = body.get("target")
    config = body.get("config")
    cron = body.get("cron", "")
    if not isinstance(name, str) or not name.strip():
        return {"error": "Project name is required."}
    if project_type not in {"source", "yaml", "python", "git"}:
        return {"error": "Project type must be yaml, python, or git."}
    if not isinstance(target, str) or not target.strip():
        return {"error": "Project source is required."}
    if config is not None and (not isinstance(config, dict)):
        return {"error": "Project config must be an object."}
    if cron is not None and not isinstance(cron, str):
        return {"error": "Project cron must be a string."}
    if isinstance(cron, str) and cron.strip() and not valid_cron(cron):
        return {"error": "Project cron must be a valid cron expression."}
    files = []
    if project_type != "git" and "files" in body:
        raw_files = body["files"]
        if not isinstance(raw_files, list):
            return {"error": "Project files must be an array."}
        seen = set()
        for file in raw_files:
            if not isinstance(file, dict):
                return {"error": "Project file entries must be objects."}
            raw_path = file.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                return {"error": "Project file path is required."}
            file_path = raw_path.strip().replace("\\", "/")
            parts = file_path.split("/")
            if file_path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                return {"error": f"Invalid project file path: {raw_path}"}
            if file_path in seen:
                return {"error": f"Duplicate project file path: {file_path}"}
            content = file.get("content")
            if not isinstance(content, str):
                return {"error": f"Project file content must be text: {file_path}"}
            seen.add(file_path)
            files.append({"path": file_path, "content": content})
    return {
        "input": {
            "name": name.strip(),
            "type": project_type,
            "target": target.strip(),
            "cron": cron.strip() if isinstance(cron, str) else "",
            "config": None if project_type == "git" else config,
            "files": files,
        }
    }


def _validate_assistant_files(raw_files: Any) -> dict:
    if not isinstance(raw_files, list):
        return {"error": "Assistant files must be an array."}
    seen = set()
    files = []
    for file in raw_files:
        if not isinstance(file, dict):
            return {"error": "Assistant file entries must be objects."}
        raw_path = file.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return {"error": "Assistant file path is required."}
        file_path = raw_path.strip().replace("\\", "/")
        parts = file_path.split("/")
        if file_path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            return {"error": f"Invalid assistant file path: {raw_path}"}
        if file_path in seen:
            return {"error": f"Duplicate assistant file path: {file_path}"}
        content = file.get("content")
        if not isinstance(content, str):
            return {"error": f"Assistant file content must be text: {file_path}"}
        seen.add(file_path)
        files.append({"path": file_path, "content": content})
    return {"files": files}
