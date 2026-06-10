import importlib
import sys
from pathlib import Path
from typing import Any

from ..exceptions import PipelineError
from .assets import AssetDownloadPipeline
from .base import Pipeline
from .csv import CsvPipeline
from .jsonl import JsonlPipeline
from .sqlite import SQLitePipeline
from .webhook import WebhookPipeline


_BUILTIN_PIPELINES = {
    "assets": AssetDownloadPipeline,
    "asset_download": AssetDownloadPipeline,
    "jsonl": JsonlPipeline,
    "csv": CsvPipeline,
    "sqlite": SQLitePipeline,
    "webhook": WebhookPipeline,
}


def _import_object(path: str, *, base_dir: str | Path | None = None) -> Any:
    module_name, _, object_name = path.rpartition(".")
    if not module_name or not object_name:
        raise PipelineError(f"Pipeline import path must be module.Object: {path!r}")
    inserted = False
    if base_dir is not None:
        search_path = str(Path(base_dir))
        if search_path not in sys.path:
            sys.path.insert(0, search_path)
            inserted = True
    try:
        try:
            module = importlib.import_module(module_name)
            return getattr(module, object_name)
        except (AttributeError, ModuleNotFoundError) as exc:
            raise PipelineError(f"Cannot import pipeline object: {path!r}") from exc
    finally:
        if inserted:
            sys.path.remove(search_path)


def resolve_pipeline(spec: Any, *, base_dir: str | Path | None = None) -> Pipeline:
    if isinstance(spec, Pipeline):
        return spec
    if isinstance(spec, str):
        key = spec.lower()
        if key in _BUILTIN_PIPELINES:
            return _BUILTIN_PIPELINES[key](base_dir=base_dir)
        target = _import_object(spec, base_dir=base_dir)
        return target() if isinstance(target, type) else target
    if isinstance(spec, type):
        return spec()
    if isinstance(spec, dict):
        options = dict(spec)
        pipeline_type = options.pop("type", None)
        pipeline_class = options.pop("class", None)
        if pipeline_type:
            if base_dir is not None and "base_dir" not in options:
                options["base_dir"] = base_dir
            key = str(pipeline_type).lower()
            if key not in _BUILTIN_PIPELINES:
                raise PipelineError(f"Unknown builtin pipeline type: {pipeline_type!r}")
            return _BUILTIN_PIPELINES[key](**options)
        if pipeline_class:
            target = _import_object(str(pipeline_class), base_dir=base_dir)
            return target(**options) if isinstance(target, type) else target
    if hasattr(spec, "process_item"):
        return spec
    raise PipelineError(f"Unsupported pipeline spec: {spec!r}")


def resolve_pipelines(
    specs: Any, *, base_dir: str | Path | None = None
) -> list[Pipeline]:
    if specs is None:
        return []
    if isinstance(specs, (str, dict, Pipeline)) or hasattr(specs, "process_item"):
        specs = [specs]
    return [resolve_pipeline(spec, base_dir=base_dir) for spec in specs]


__all__ = ["resolve_pipeline", "resolve_pipelines"]
