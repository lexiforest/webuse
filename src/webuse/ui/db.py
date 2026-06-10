import os
import sqlite3
import threading
from pathlib import Path


def default_data_dir() -> Path:
    if os.name == "nt":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "webuse"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "webuse"


def default_db_path() -> Path:
    return Path(os.environ.get("WEBUSE_DB_PATH", default_data_dir() / "webuse.sqlite"))


def default_work_dir(db_path: Path) -> Path:
    return Path(os.environ.get("WEBUSE_WORK_DIR", db_path.parent / "jobs"))


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def execute(self, sql: str, values: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self.conn.execute(sql, values)
            self.conn.commit()
            return cursor

    def executescript(self, sql: str) -> None:
        with self._lock:
            self.conn.executescript(sql)
            self.conn.commit()

    def one(self, sql: str, values: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, values).fetchone()

    def all(self, sql: str, values: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, values).fetchall())

    def transaction(self):
        return self._lock


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  name text NOT NULL,
  type text NOT NULL,
  git_url text,
  source_tarball blob,
  config text,
  created_at integer NOT NULL,
  updated_at integer NOT NULL
);
CREATE INDEX IF NOT EXISTS projects_type_idx ON projects (type);
CREATE INDEX IF NOT EXISTS projects_created_at_idx ON projects (created_at);

CREATE TABLE IF NOT EXISTS jobs (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  project_id integer NOT NULL,
  status text NOT NULL,
  command text NOT NULL,
  started_at integer,
  finished_at integer,
  metadata text,
  created_at integer NOT NULL,
  updated_at integer NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON UPDATE no action ON DELETE no action
);
CREATE INDEX IF NOT EXISTS jobs_project_id_idx ON jobs (project_id);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs (created_at);

CREATE TABLE IF NOT EXISTS logs (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  job_id integer NOT NULL,
  stream text NOT NULL,
  message text NOT NULL,
  created_at integer NOT NULL,
  FOREIGN KEY (job_id) REFERENCES jobs(id) ON UPDATE no action ON DELETE no action
);
CREATE INDEX IF NOT EXISTS logs_job_id_idx ON logs (job_id);
CREATE INDEX IF NOT EXISTS logs_created_at_idx ON logs (created_at);

CREATE TABLE IF NOT EXISTS data_items (
  id integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  job_id integer NOT NULL,
  url text,
  item text NOT NULL,
  created_at integer NOT NULL,
  FOREIGN KEY (job_id) REFERENCES jobs(id) ON UPDATE no action ON DELETE no action
);
CREATE INDEX IF NOT EXISTS data_items_job_id_idx ON data_items (job_id);
CREATE INDEX IF NOT EXISTS data_items_created_at_idx ON data_items (created_at);
"""
