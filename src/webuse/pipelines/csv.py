import csv
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..exceptions import PipelineStateError
from .base import Pipeline
from .utils import ensure_pipeline_item, item_to_dict, resolve_path


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=True, default=str)
    return value


class CsvPipeline(Pipeline):
    def __init__(
        self,
        path: str | Path = "items.csv",
        *,
        fieldnames: list[str] | None = None,
        append: bool = True,
        base_dir: str | Path | None = None,
    ) -> None:
        self.path = resolve_path(path, base_dir)
        self.fieldnames = fieldnames
        self.append = append
        self._file: Any = None
        self._writer: csv.DictWriter | None = None
        self._write_header = False

    def open_spider(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if self.append else "w"
        self._write_header = (
            not self.append or not self.path.exists() or self.path.stat().st_size == 0
        )
        self._file = self.path.open(mode, encoding="utf-8", newline="")

    def process_item(self, item: BaseModel) -> BaseModel:
        item = ensure_pipeline_item(item)
        row = {key: _csv_value(value) for key, value in item_to_dict(item).items()}
        if self._writer is None:
            self.fieldnames = self.fieldnames or list(row)
            if self._file is None:
                raise PipelineStateError("CsvPipeline is not open")
            self._writer = csv.DictWriter(
                self._file, fieldnames=self.fieldnames, extrasaction="ignore"
            )
            if self._write_header:
                self._writer.writeheader()
        self._writer.writerow(row)
        self._file.flush()
        return item

    def close_spider(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self._writer = None


__all__ = ["CsvPipeline"]
