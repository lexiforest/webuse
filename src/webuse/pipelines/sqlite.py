import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..exceptions import PipelineError, PipelineStateError
from .base import Pipeline
from .utils import ensure_pipeline_item, item_to_json, resolve_path


def _table_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise PipelineError(f"Invalid SQLite table name: {value!r}")
    return value


class SQLitePipeline(Pipeline):
    def __init__(
        self,
        path: str | Path = "items.sqlite",
        *,
        table: str = "items",
        base_dir: str | Path | None = None,
    ) -> None:
        self.path = resolve_path(path, base_dir)
        self.table = _table_name(table)
        self._connection: sqlite3.Connection | None = None

    def open_spider(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def process_item(self, item: BaseModel) -> BaseModel:
        if self._connection is None:
            raise PipelineStateError("SQLitePipeline is not open")
        item = ensure_pipeline_item(item)
        self._connection.execute(
            f"INSERT INTO {self.table} (item_type, data, created_at) VALUES (?, ?, ?)",
            (
                item.__class__.__name__,
                item_to_json(item),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._connection.commit()
        return item

    def close_spider(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


__all__ = ["SQLitePipeline"]
