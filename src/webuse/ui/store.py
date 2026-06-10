import json
import time
from typing import Any

from .db import Database


BOOKS_TO_SCRAPE_CONFIG = {
    "start_urls": ["https://books.toscrape.com/"],
    "allowed_domains": ["books.toscrape.com"],
    "max_depth": 1,
    "follow": [{"css": ".next a", "same_domain": True}],
    "extract": {
        "item_css": ".product_pod",
        "fields": {
            "title": {"css": "h3 a", "attr": "title"},
            "price": ".price_color",
            "availability": ".availability",
        },
    },
}


def now() -> int:
    return int(time.time() * 1000)


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


class Store:
    def __init__(self, db: Database):
        self.db = db

    def _project_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "target": row["git_url"] or "https://books.toscrape.com/",
            "status": row["status"] if "status" in row.keys() else "Ready",
            "updatedAt": _serialize_date(row["updated_at"]),
        }

    def _project_detail(self, row: Any) -> dict[str, Any]:
        return {**self._project_row(row), "config": _json_loads(row["config"])}

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
        cursor = self.db.execute(
            """
            INSERT INTO projects (name, type, git_url, config, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                input["name"],
                input["type"],
                input["target"],
                json.dumps(input["config"]) if input.get("config") is not None else None,
                timestamp,
                timestamp,
            ),
        )
        return self.get_project(int(cursor.lastrowid)) or {}

    def create_books_to_scrape_project(self) -> dict[str, Any]:
        return self.create_project(
            {
                "name": "Books to Scrape",
                "type": "source",
                "target": "https://books.toscrape.com/",
                "config": BOOKS_TO_SCRAPE_CONFIG,
            }
        )

    def update_project(self, project_id: int, input: dict[str, Any]) -> dict[str, Any] | None:
        self.db.execute(
            """
            UPDATE projects
            SET name = ?, type = ?, git_url = ?, config = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                input["name"],
                input["type"],
                input["target"],
                json.dumps(input["config"]) if input.get("config") is not None else None,
                now(),
                project_id,
            ),
        )
        return self.get_project(project_id)

    def delete_project(self, project_id: int) -> bool:
        with self.db.transaction():
            job_ids = self.db.all("SELECT id FROM jobs WHERE project_id = ?", (project_id,))
            for job in job_ids:
                self.db.execute("DELETE FROM data_items WHERE job_id = ?", (job["id"],))
                self.db.execute("DELETE FROM logs WHERE job_id = ?", (job["id"],))
            self.db.execute("DELETE FROM jobs WHERE project_id = ?", (project_id,))
            cursor = self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cursor.rowcount > 0

    def list_jobs(self) -> list[dict[str, Any]]:
        rows = self.db.all(
            """
            SELECT j.*, p.name AS project, COUNT(d.id) AS items
            FROM jobs j
            JOIN projects p ON p.id = j.project_id
            LEFT JOIN data_items d ON d.job_id = j.id
            GROUP BY j.id
            ORDER BY j.created_at DESC
            """
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
            self.append_log(row["id"], "stderr", "worker restarted while this job was running")
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

    def finish_job(self, job_id: int, status: str, metadata: dict[str, Any] | None = None) -> None:
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

    def list_logs(self, job_id: int | None) -> list[dict[str, Any]]:
        rows = (
            self.db.all(
                "SELECT * FROM logs WHERE job_id = ? ORDER BY created_at, id", (job_id,)
            )
            if job_id
            else self.db.all("SELECT * FROM logs ORDER BY created_at DESC, id DESC LIMIT 500")
        )
        return [self._log_row(row) for row in rows]

    def insert_data_item(self, job_id: int, item: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO data_items (job_id, url, item, created_at) VALUES (?, ?, ?, ?)",
            (job_id, item.get("url") if isinstance(item.get("url"), str) else None, json.dumps(item), now()),
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
