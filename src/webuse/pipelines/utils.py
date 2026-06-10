import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..exceptions import PipelineError


def ensure_pipeline_item(item: Any) -> BaseModel:
    if not isinstance(item, BaseModel):
        raise PipelineError(
            f"Pipelines require pydantic BaseModel items, got {type(item).__name__}"
        )
    return item


def item_to_dict(item: BaseModel) -> dict[str, Any]:
    return ensure_pipeline_item(item).model_dump(mode="json")


def item_to_json(item: BaseModel) -> str:
    return json.dumps(item_to_dict(item), ensure_ascii=True, default=str)


def resolve_path(path: str | Path, base_dir: str | Path | None = None) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute() and base_dir is not None:
        resolved = Path(base_dir) / resolved
    return resolved


__all__ = ["ensure_pipeline_item", "item_to_dict", "item_to_json", "resolve_path"]
