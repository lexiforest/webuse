import inspect
import json
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..exceptions import DropItem, PipelineError
from .base import AsyncItemPipeline, ItemPipeline


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


def _sync_result(value: Any) -> Any:
    if inspect.isawaitable(value):
        close = getattr(value, "close", None)
        if close is not None:
            close()
        raise PipelineError("Async pipeline hooks require AsyncSpider.run()")
    return value


def _raise_cleanup_errors(
    errors: list[BaseException], primary: BaseException | None
) -> None:
    if not errors:
        return
    if primary is not None:
        raise BaseExceptionGroup(
            "Pipeline execution and cleanup failed", [primary, *errors]
        )
    if len(errors) == 1:
        raise errors[0]
    raise BaseExceptionGroup("Pipeline cleanup failed", errors)


@contextmanager
def _pipeline_lifecycle(
    pipelines: list[ItemPipeline | AsyncItemPipeline],
) -> Iterator[None]:
    """Open a spider's pipelines and close every successfully opened pipeline."""
    opened = []
    primary = None
    try:
        for pipeline in pipelines:
            hook = getattr(pipeline, "open_spider", None)
            if hook is not None:
                _sync_result(hook())
            opened.append(pipeline)
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        errors = []
        for pipeline in reversed(opened):
            try:
                hook = getattr(pipeline, "close_spider", None)
                if hook is not None:
                    _sync_result(hook())
            except BaseException as error:
                errors.append(error)
        _raise_cleanup_errors(errors, primary)


@asynccontextmanager
async def _apipeline_lifecycle(
    pipelines: list[ItemPipeline | AsyncItemPipeline],
) -> AsyncIterator[None]:
    """Async lifecycle, including cleanup after failed opening or cancellation."""
    opened = []
    primary = None
    try:
        for pipeline in pipelines:
            hook = getattr(pipeline, "open_spider", None)
            if hook is not None:
                result = hook()
                if inspect.isawaitable(result):
                    await result
            opened.append(pipeline)
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        errors = []
        for pipeline in reversed(opened):
            try:
                hook = getattr(pipeline, "close_spider", None)
                if hook is not None:
                    result = hook()
                    if inspect.isawaitable(result):
                        await result
            except BaseException as error:
                errors.append(error)
        _raise_cleanup_errors(errors, primary)


def _process_items(
    items: list[Any],
    pipelines: list[ItemPipeline | AsyncItemPipeline],
    *,
    coerce_item: Callable[[Any], BaseModel],
    emit: Callable[..., Any],
) -> list[Any]:
    """Apply a spider's pipeline chain; the caller supplies signal context."""
    processed = []
    for item in items:
        emit("item_extracted", item=item)
        current = coerce_item(item) if pipelines else item
        for pipeline in pipelines:
            try:
                emit("pipeline_started", pipeline=pipeline, item=current)
                result = _sync_result(pipeline.process_item(current))
                if result is None:
                    raise DropItem("Pipeline returned None")
                current = result
                emit("pipeline_finished", pipeline=pipeline, item=current)
                current = ensure_pipeline_item(current)
            except DropItem as error:
                emit("pipeline_finished", pipeline=pipeline, item=current)
                emit("item_dropped", item=item, error=error)
                current = None
                break
            except Exception as error:
                emit("pipeline_error", pipeline=pipeline, item=current, error=error)
                emit("item_error", item=item, error=error)
                raise
        if current is not None or not pipelines:
            emit("item_processed", item=current)
            processed.append(current)
    return processed


async def _aprocess_items(
    items: list[Any],
    pipelines: list[ItemPipeline | AsyncItemPipeline],
    *,
    coerce_item: Callable[[Any], BaseModel],
    emit: Callable[..., Any],
) -> list[Any]:
    """Apply sync/async hooks; the spider serializes concurrent response batches."""
    processed = []
    for item in items:
        await emit("item_extracted", item=item)
        current = coerce_item(item) if pipelines else item
        for pipeline in pipelines:
            try:
                await emit("pipeline_started", pipeline=pipeline, item=current)
                result = pipeline.process_item(current)
                result = await result if inspect.isawaitable(result) else result
                if result is None:
                    raise DropItem("Pipeline returned None")
                current = result
                await emit("pipeline_finished", pipeline=pipeline, item=current)
                current = ensure_pipeline_item(current)
            except DropItem as error:
                await emit("pipeline_finished", pipeline=pipeline, item=current)
                await emit("item_dropped", item=item, error=error)
                current = None
                break
            except Exception as error:
                await emit(
                    "pipeline_error", pipeline=pipeline, item=current, error=error
                )
                await emit("item_error", item=item, error=error)
                raise
        if current is not None or not pipelines:
            await emit("item_processed", item=current)
            processed.append(current)
    return processed


__all__ = ["ensure_pipeline_item", "item_to_dict", "item_to_json", "resolve_path"]
