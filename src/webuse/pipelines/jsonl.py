from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..exceptions import PipelineStateError
from .base import Pipeline
from .utils import ensure_pipeline_item, item_to_json, resolve_path


class JsonlPipeline(Pipeline):
    def __init__(
        self,
        path: str | Path = "items.jsonl",
        *,
        append: bool = True,
        base_dir: str | Path | None = None,
    ) -> None:
        self.path = resolve_path(path, base_dir)
        self.append = append
        self._file: Any = None

    def open_spider(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a" if self.append else "w", encoding="utf-8")

    def process_item(self, item: BaseModel) -> BaseModel:
        if self._file is None:
            raise PipelineStateError("JsonlPipeline is not open")
        item = ensure_pipeline_item(item)
        self._file.write(item_to_json(item))
        self._file.write("\n")
        self._file.flush()
        return item

    def close_spider(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


__all__ = ["JsonlPipeline"]
