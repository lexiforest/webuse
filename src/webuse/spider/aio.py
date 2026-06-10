import asyncio
import inspect
from collections.abc import AsyncIterable
from typing import Any

from pydantic import BaseModel

from ..crawl.aio import acrawl
from ..crawl.utils import UNSET, handle_callback_result
from ..models import CrawlResult
from ..pipelines import DropItem, Pipeline
from ..signals import SignalBus
from .config import EffectiveSpiderSettings
from .sync import Spider


class AsyncSpider(Spider):
    def _pipeline_async_lock(self) -> asyncio.Lock:
        if not hasattr(self, "_pipeline_async_lock_obj"):
            self._pipeline_async_lock_obj = asyncio.Lock()
        return self._pipeline_async_lock_obj

    async def _aopen_pipelines(self, pipelines: list[Pipeline]) -> None:
        opened: list[Pipeline] = []
        try:
            for pipeline in pipelines:
                open_spider = getattr(pipeline, "open_spider", None)
                if open_spider:
                    result = open_spider()
                    if inspect.isawaitable(result):
                        await result
                opened.append(pipeline)
        except Exception:
            for pipeline in reversed(opened):
                close_spider = getattr(pipeline, "close_spider", None)
                if close_spider:
                    result = close_spider()
                    if inspect.isawaitable(result):
                        await result
            raise

    async def _aclose_pipelines(self, pipelines: list[Pipeline]) -> None:
        for pipeline in reversed(pipelines):
            close_spider = getattr(pipeline, "close_spider", None)
            if close_spider:
                result = close_spider()
                if inspect.isawaitable(result):
                    await result

    async def _aprocess_pipeline_items(
        self, items: list[Any], response: Any | None = None
    ) -> list[Any]:
        pipelines = getattr(self, "_active_pipelines", [])
        signal_bus = getattr(self, "_active_signals", None)
        if not pipelines:
            if signal_bus is not None:
                for item in items:
                    await signal_bus.asend(
                        "item_extracted", item=item, response=response, spider=self
                    )
                    await signal_bus.asend(
                        "item_processed", item=item, response=response, spider=self
                    )
            return items
        processed: list[Any] = []
        async with self._pipeline_async_lock():
            for item in items:
                if signal_bus is not None:
                    await signal_bus.asend(
                        "item_extracted", item=item, response=response, spider=self
                    )
                current: BaseModel | None = self._coerce_pipeline_item(item)
                try:
                    for pipeline in pipelines:
                        if signal_bus is not None:
                            await signal_bus.asend(
                                "pipeline_started",
                                pipeline=pipeline,
                                item=current,
                                response=response,
                                spider=self,
                            )
                        result = pipeline.process_item(current)
                        current = (
                            await result if inspect.isawaitable(result) else result
                        )
                        if signal_bus is not None:
                            await signal_bus.asend(
                                "pipeline_finished",
                                pipeline=pipeline,
                                item=current,
                                response=response,
                                spider=self,
                            )
                        if current is None:
                            break
                        current = self._ensure_pipeline_result(current)
                except DropItem as exc:
                    if signal_bus is not None:
                        await signal_bus.asend(
                            "item_dropped",
                            item=item,
                            response=response,
                            spider=self,
                            error=exc,
                        )
                    current = None
                except Exception as exc:
                    if signal_bus is not None:
                        await signal_bus.asend(
                            "pipeline_error",
                            item=item,
                            response=response,
                            spider=self,
                            error=exc,
                        )
                        await signal_bus.asend(
                            "item_error",
                            item=item,
                            response=response,
                            spider=self,
                            error=exc,
                        )
                    raise
                if current is not None:
                    if signal_bus is not None:
                        await signal_bus.asend(
                            "item_processed",
                            item=current,
                            response=response,
                            spider=self,
                        )
                    processed.append(current)
        return processed

    async def _aextract_callback(
        self, response: Any, settings: EffectiveSpiderSettings
    ) -> Any:
        request = getattr(response, "request", None)
        handler = self._route_handler(getattr(request, "category", None))
        parse_result = handler(response)
        if inspect.isawaitable(parse_result):
            parse_result = await parse_result
        elif isinstance(parse_result, AsyncIterable):
            parse_result = [entry async for entry in parse_result]
        items, followups = handle_callback_result(parse_result)
        items = await self._aprocess_pipeline_items(items, response=response)
        if followups:
            return items, followups
        return items

    async def run(self, **overrides: Any) -> CrawlResult:  # type: ignore[override]
        pipeline_override = overrides.pop("pipelines", UNSET)
        signal_bus = overrides.pop("signals", None) or self.signals or SignalBus()
        project_config, project_base_dir = self._project_config()
        settings, crawl_overrides = self._resolve_settings(
            overrides, project_config=project_config
        )
        pipelines = self._resolve_pipeline_chain(
            pipeline_override,
            project_config=project_config,
            project_base_dir=project_base_dir,
        )
        options = self._crawl_options(settings, crawl_overrides)
        options["extract"] = lambda response: self._aextract_callback(
            response, settings
        )
        options["signals"] = signal_bus
        self._active_pipelines = pipelines
        self._active_settings = settings
        self._active_signals = signal_bus
        await signal_bus.asend("spider_open", spider=self)
        result: CrawlResult | None = None
        await self._aopen_pipelines(pipelines)
        try:
            result = await acrawl(settings.start_urls, **options)
            return result
        finally:
            await self._aclose_pipelines(pipelines)
            await signal_bus.asend(
                "spider_closed",
                spider=self,
                result=result,
                reason=(result.close_reason if result else "error") or "finished",
            )
            self._active_pipelines = []
            self._active_settings = None
            self._active_signals = None
