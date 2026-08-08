import json
import time
from typing import Any

from .db import Database
from .schedule import next_run_at_ms, now_ms


BOOKS_TO_SCRAPE_CONFIG = {
    "name": "Books to Scrape",
    "spiders": {
        "books": {
            "start_urls": ["https://books.toscrape.com/"],
            "allowed_domains": ["books.toscrape.com"],
            "max_depth": 1,
            "pages": {
                "default": {
                    "follow": [{"css": ".next a", "same_domain": True}],
                    "extract": {
                        "books": {
                            "item_css": ".product_pod",
                            "fields": {
                                "title": {"css": "h3 a", "attr": "title"},
                                "price": ".price_color",
                                "availability": ".availability",
                            },
                        },
                    },
                },
            },
        },
    },
}

BOOKS_TO_SCRAPE_FILES = [
    {
        "path": "webuse.yaml",
        "content": """name: Books to Scrape
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
          - css: .next a
            same_domain: true
        extract:
          books:
            item_css: .product_pod
            fields:
              title:
                css: h3 a
                attr: title
              price: .price_color
              availability: .availability
""",
    },
    {
        "path": "spiders/books.py",
        "content": """import webuse


class BooksSpider(webuse.Spider):
    name = "books"
""",
    },
]


def now() -> int:
    return now_ms()


def _json_loads(value: Any, fallback: Any = None) -> Any:
    if value in (None, ""):
        return fallback
    return json.loads(value)


def _serialize_date(value: int | None) -> str:
    if not value:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(value / 1000))


def _duration(started_at: int | None, finished_at: int | None) -> str:
    if not started_at:
        return ""
    end = finished_at or now()
    seconds = max(0, round((end - started_at) / 1000))
    if seconds < 60:
        return f"{seconds}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}m {remainder:02d}s"


def _normalize_project_files(
    files: Any, fallback_config: Any = None
) -> list[dict[str, str]]:
    if isinstance(files, list) and files:
        return [{"path": file["path"], "content": file["content"]} for file in files]
    if fallback_config is not None:
        return [
            {"path": "webuse.yaml", "content": json.dumps(fallback_config, indent=2)}
        ]
    return []


class Store:
    def __init__(self, db: Database):
        self.db = db

    def _project_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "target": row["git_url"] or "https://books.toscrape.com/",
            "cron": row["cron"] or "",
            "nextRunAt": _serialize_date(row["next_run_at"])
            if "next_run_at" in row.keys()
            else "",
            "status": row["status"] if "status" in row.keys() else "Ready",
            "updatedAt": _serialize_date(row["updated_at"]),
        }

    def _project_detail(self, row: Any) -> dict[str, Any]:
        config = _json_loads(row["config"])
        return {
            **self._project_row(row),
            "config": config,
            "files": []
            if row["type"] == "git"
            else _normalize_project_files(self._list_project_files(row["id"]), config),
        }

    def _job_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "project": row["project"],
            "status": row["status"],
            "command": row["command"],
            "startedAt": _serialize_date(row["started_at"] or row["created_at"]),
            "finishedAt": _serialize_date(row["finished_at"]),
            "duration": _duration(row["started_at"], row["finished_at"]),
            "items": row["items"] or 0,
            "metadata": _json_loads(row["metadata"], {}),
        }

    def _log_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "jobId": row["job_id"],
            "stream": row["stream"],
            "message": row["message"],
            "time": time.strftime("%H:%M:%S", time.localtime(row["created_at"] / 1000)),
        }

    def _data_item_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "jobId": row["job_id"],
            "url": row["url"] or "",
            "item": _json_loads(row["item"], {}),
            "createdAt": _serialize_date(row["created_at"]),
        }

    def _assistant_session_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "projectId": row["project_id"],
            "title": row["title"] or "",
            "createdAt": _serialize_date(row["created_at"]),
            "updatedAt": _serialize_date(row["updated_at"]),
        }

    def _assistant_message_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "sessionId": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "metadata": _json_loads(row["metadata"], {}),
            "createdAt": _serialize_date(row["created_at"]),
        }

    def _list_project_files(self, project_id: int) -> list[dict[str, str]]:
        rows = self.db.all(
            "SELECT path, content FROM project_files WHERE project_id = ? ORDER BY path",
            (project_id,),
        )
        return [{"path": row["path"], "content": row["content"]} for row in rows]

    def _replace_project_files(
        self, project_id: int, files: list[dict[str, str]]
    ) -> None:
        timestamp = now()
        self.db.execute("DELETE FROM project_files WHERE project_id = ?", (project_id,))
        for file in files:
            self.db.execute(
                """
                INSERT INTO project_files (project_id, path, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, file["path"], file["content"], timestamp, timestamp),
            )

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.db.all(
            """
            SELECT p.*,
              COALESCE((
                SELECT status FROM jobs
                WHERE project_id = p.id
                ORDER BY created_at DESC
                LIMIT 1
              ), 'Ready') AS status
            FROM projects p
            ORDER BY p.updated_at DESC
            """
        )
        return [self._project_row(row) for row in rows]

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM projects WHERE id = ?", (project_id,))
        return self._project_detail(row) if row else None

    def create_project(self, input: dict[str, Any]) -> dict[str, Any]:
        timestamp = now()
        cron = input.get("cron") or None
        next_run_at = next_run_at_ms(cron, timestamp)
        with self.db.transaction():
            cursor = self.db.execute(
                """
                INSERT INTO projects (name, type, git_url, config, cron, next_run_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    input["name"],
                    input["type"],
                    input["target"],
                    json.dumps(input["config"])
                    if input.get("config") is not None
                    else None,
                    cron,
                    next_run_at,
                    timestamp,
                    timestamp,
                ),
            )
            project_id = int(cursor.lastrowid)
            self._replace_project_files(
                project_id,
                []
                if input["type"] == "git"
                else _normalize_project_files(input.get("files"), input.get("config")),
            )
        return self.get_project(project_id) or {}

    def create_books_to_scrape_project(self) -> dict[str, Any]:
        return self.create_project(
            {
                "name": "Books to Scrape",
                "type": "source",
                "target": "https://books.toscrape.com/",
                "cron": "",
                "config": BOOKS_TO_SCRAPE_CONFIG,
                "files": BOOKS_TO_SCRAPE_FILES,
            }
        )

    def update_project(
        self, project_id: int, input: dict[str, Any]
    ) -> dict[str, Any] | None:
        timestamp = now()
        cron = input.get("cron") or None
        next_run_at = next_run_at_ms(cron, timestamp)
        with self.db.transaction():
            cursor = self.db.execute(
                """
                UPDATE projects
                SET name = ?, type = ?, git_url = ?, config = ?, cron = ?, next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    input["name"],
                    input["type"],
                    input["target"],
                    json.dumps(input["config"])
                    if input.get("config") is not None
                    else None,
                    cron,
                    next_run_at,
                    timestamp,
                    project_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            self._replace_project_files(
                project_id,
                []
                if input["type"] == "git"
                else _normalize_project_files(input.get("files"), input.get("config")),
            )
        return self.get_project(project_id)

    def delete_project(self, project_id: int) -> bool:
        with self.db.transaction():
            job_ids = self.db.all(
                "SELECT id FROM jobs WHERE project_id = ?", (project_id,)
            )
            for job in job_ids:
                self.db.execute("DELETE FROM data_items WHERE job_id = ?", (job["id"],))
                self.db.execute("DELETE FROM logs WHERE job_id = ?", (job["id"],))
            self.db.execute("DELETE FROM jobs WHERE project_id = ?", (project_id,))
            cursor = self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cursor.rowcount > 0

    def list_jobs(self, project_id: int | None = None) -> list[dict[str, Any]]:
        where = "WHERE j.project_id = ?" if project_id is not None else ""
        params = (project_id,) if project_id is not None else ()
        rows = self.db.all(
            f"""
            SELECT j.*, p.name AS project, COUNT(d.id) AS items
            FROM jobs j
            JOIN projects p ON p.id = j.project_id
            LEFT JOIN data_items d ON d.job_id = j.id
            {where}
            GROUP BY j.id
            ORDER BY j.created_at DESC
            """,
            params,
        )
        return [self._job_row(row) for row in rows]

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        row = self.db.one(
            """
            SELECT j.*, p.name AS project, COUNT(d.id) AS items
            FROM jobs j
            JOIN projects p ON p.id = j.project_id
            LEFT JOIN data_items d ON d.job_id = j.id
            WHERE j.id = ?
            GROUP BY j.id
            """,
            (job_id,),
        )
        return self._job_row(row) if row else None

    def create_job(self, project_id: int) -> dict[str, Any] | None:
        if not self.get_project(project_id):
            return None
        timestamp = now()
        cursor = self.db.execute(
            """
            INSERT INTO jobs (project_id, status, command, created_at, updated_at)
            VALUES (?, 'queued', ?, ?, ?)
            """,
            (project_id, f"webuse crawl project:{project_id}", timestamp, timestamp),
        )
        return self.get_job(int(cursor.lastrowid))

    def ensure_cron_schedules(self, timestamp: int | None = None) -> None:
        scheduled_from = timestamp if timestamp is not None else now()
        rows = self.db.all(
            """
            SELECT id, cron
            FROM projects
            WHERE cron IS NOT NULL
              AND cron != ''
              AND next_run_at IS NULL
            """,
        )
        for row in rows:
            self.db.execute(
                "UPDATE projects SET next_run_at = ?, updated_at = ? WHERE id = ?",
                (
                    next_run_at_ms(row["cron"], scheduled_from),
                    scheduled_from,
                    row["id"],
                ),
            )

    def enqueue_due_cron_jobs(
        self, timestamp: int | None = None
    ) -> list[dict[str, Any]]:
        due_at = timestamp if timestamp is not None else now()
        self.ensure_cron_schedules(due_at)
        rows = self.db.all(
            """
            SELECT id, cron
            FROM projects
            WHERE cron IS NOT NULL
              AND cron != ''
              AND next_run_at IS NOT NULL
              AND next_run_at <= ?
            ORDER BY next_run_at, id
            """,
            (due_at,),
        )
        queued = []
        for row in rows:
            next_run_at = next_run_at_ms(row["cron"], due_at)
            active = self.db.one(
                """
                SELECT id FROM jobs
                WHERE project_id = ? AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (row["id"],),
            )
            with self.db.transaction():
                self.db.execute(
                    "UPDATE projects SET next_run_at = ?, updated_at = ? WHERE id = ?",
                    (next_run_at, due_at, row["id"]),
                )
                if active:
                    continue
                cursor = self.db.execute(
                    """
                    INSERT INTO jobs (project_id, status, command, metadata, created_at, updated_at)
                    VALUES (?, 'queued', ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        f"webuse crawl project:{row['id']}",
                        json.dumps(
                            {
                                "scheduled": True,
                                "cron": row["cron"],
                                "scheduledAt": due_at,
                            }
                        ),
                        due_at,
                        due_at,
                    ),
                )
            job = self.get_job(int(cursor.lastrowid))
            if job:
                queued.append(job)
        return queued

    def claim_job(self) -> dict[str, Any] | None:
        with self.db.transaction():
            row = self.db.one(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            )
            if not row:
                return None
            timestamp = now()
            cursor = self.db.execute(
                """
                UPDATE jobs
                SET status = 'running', started_at = ?, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (timestamp, timestamp, row["id"]),
            )
            return self.get_job(row["id"]) if cursor.rowcount > 0 else None

    def reconcile_running_jobs(self) -> None:
        timestamp = now()
        rows = self.db.all("SELECT id FROM jobs WHERE status = 'running'")
        for row in rows:
            self.append_log(
                row["id"], "stderr", "worker restarted while this job was running"
            )
        self.db.execute(
            """
            UPDATE jobs
            SET status = 'failed', finished_at = ?, updated_at = ?
            WHERE status = 'running'
            """,
            (timestamp, timestamp),
        )

    def update_job_command(self, job_id: int, command: str) -> None:
        self.db.execute(
            "UPDATE jobs SET command = ?, updated_at = ? WHERE id = ?",
            (command, now(), job_id),
        )

    def finish_job(
        self, job_id: int, status: str, metadata: dict[str, Any] | None = None
    ) -> None:
        timestamp = now()
        self.db.execute(
            """
            UPDATE jobs
            SET status = ?, finished_at = ?, metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, timestamp, json.dumps(metadata or {}), timestamp, job_id),
        )

    def cancel_queued_job(self, job_id: int) -> bool:
        timestamp = now()
        cursor = self.db.execute(
            """
            UPDATE jobs
            SET status = 'cancelled', finished_at = ?, updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (timestamp, timestamp, job_id),
        )
        return cursor.rowcount > 0

    def append_log(self, job_id: int, stream: str, message: str) -> None:
        self.db.execute(
            "INSERT INTO logs (job_id, stream, message, created_at) VALUES (?, ?, ?, ?)",
            (job_id, stream, message, now()),
        )

    def list_logs(
        self, job_id: int | None, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        rows = (
            self.db.all(
                "SELECT * FROM logs WHERE job_id = ? ORDER BY created_at, id LIMIT ? OFFSET ?",
                (job_id, limit, offset),
            )
            if job_id
            else self.db.all(
                "SELECT * FROM logs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        )
        return [self._log_row(row) for row in rows]

    def count_logs(self, job_id: int | None) -> int:
        row = (
            self.db.one(
                "SELECT COUNT(*) AS total FROM logs WHERE job_id = ?", (job_id,)
            )
            if job_id
            else self.db.one("SELECT COUNT(*) AS total FROM logs")
        )
        return int(row["total"]) if row else 0

    def insert_data_item(self, job_id: int, item: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO data_items (job_id, url, item, created_at) VALUES (?, ?, ?, ?)",
            (
                job_id,
                item.get("url") if isinstance(item.get("url"), str) else None,
                json.dumps(item),
                now(),
            ),
        )

    def clear_data_items(self, job_id: int) -> None:
        self.db.execute("DELETE FROM data_items WHERE job_id = ?", (job_id,))

    def list_data_items(self, job_id: int | None) -> list[dict[str, Any]]:
        rows = (
            self.db.all(
                "SELECT * FROM data_items WHERE job_id = ? ORDER BY id", (job_id,)
            )
            if job_id
            else self.db.all(
                "SELECT * FROM data_items ORDER BY created_at DESC, id DESC LIMIT 500"
            )
        )
        return [self._data_item_row(row) for row in rows]

    def get_or_create_assistant_session(self, project_id: int) -> dict[str, Any] | None:
        project = self.get_project(project_id)
        if not project:
            return None
        row = self.db.one(
            """
            SELECT * FROM assistant_sessions
            WHERE project_id = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (project_id,),
        )
        if row:
            return self._assistant_session_row(row)
        timestamp = now()
        cursor = self.db.execute(
            """
            INSERT INTO assistant_sessions (project_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (project_id, project["name"], timestamp, timestamp),
        )
        return self.get_assistant_session(int(cursor.lastrowid))

    def get_assistant_session(self, session_id: int) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT * FROM assistant_sessions WHERE id = ?", (session_id,)
        )
        return self._assistant_session_row(row) if row else None

    def list_assistant_messages(self, session_id: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM assistant_messages WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        )
        return [self._assistant_message_row(row) for row in rows]

    def append_assistant_message(
        self,
        session_id: int,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.get_assistant_session(session_id):
            return None
        timestamp = now()
        cursor = self.db.execute(
            """
            INSERT INTO assistant_messages (session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, json.dumps(metadata or {}), timestamp),
        )
        self.db.execute(
            "UPDATE assistant_sessions SET updated_at = ? WHERE id = ?",
            (timestamp, session_id),
        )
        row = self.db.one(
            "SELECT * FROM assistant_messages WHERE id = ?", (int(cursor.lastrowid),)
        )
        return self._assistant_message_row(row) if row else None
