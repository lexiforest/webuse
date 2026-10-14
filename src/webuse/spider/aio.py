import asyncio
from contextlib import aclosing
from functools import partial
from pathlib import Path
from typing import Any

from ..engine.aio import acrawl
from ..extract import aextract_items, aextract_response
from ..extract.rules import AsyncParseResult
from ..llm import use_openai_settings
from ..models import CrawlResult
from ..pipelines.utils import _apipeline_lifecycle, _aprocess_items
from .base import BaseSpider, SpiderRun
from .config import ProjectConfig


class AsyncSpider(BaseSpider):
    _async_pipelines = True

    def parse(self, response: Any) -> Any:
        settings = self._run_state.settings if self._run_state is not None else None
        return aextract_items(response, settings.extract if settings else self.extract)

    async def _aextract_callback(
        self, response: Any, state: SpiderRun, pipeline_lock: asyncio.Lock
    ) -> AsyncParseResult:
        parsed = await aextract_response(
            response, self._response_handler(response, state.settings)
        )

        async def processed_items():
            async with aclosing(parsed.items):
                async with pipeline_lock:
                    async with aclosing(
                        _aprocess_items(
                            parsed.items,
                            state.pipelines,
                            coerce_item=self._coerce_pipeline_item,
                            emit=partial(
                                state.signals.asend, spider=self, response=response
                            ),
                        )
                    ) as items:
                        async for item in items:
                            yield item

        return AsyncParseResult(processed_items(), parsed.requests)

    async def run(self, **overrides: Any) -> CrawlResult:
        project_config, project_base_dir = self._project_config()
        with use_openai_settings(project_config.llm if project_config else None):
            return await self._arun(project_config, project_base_dir, overrides)

    async def _arun(
        self,
        project_config: ProjectConfig | None,
        project_base_dir: Path | None,
        overrides: dict[str, Any],
    ) -> CrawlResult:
        state, engine_overrides = self._prepare_run(
            overrides, project_config, project_base_dir
        )
        pipeline_lock = asyncio.Lock()
        options = self._crawl_options(
            state.settings,
            engine_overrides,
            extract=lambda response: self._aextract_callback(
                response, state, pipeline_lock
            ),
        )
        options["signals"] = state.signals
        with self._activate_run(state):
            reason = "error"
            try:
                await state.signals.asend("spider_open", spider=self)
                async with _apipeline_lifecycle(state.pipelines):
                    state.result = await acrawl(state.settings.start_urls, **options)
                reason = state.result.close_reason or "finished"
                return state.result
            except asyncio.CancelledError:
                reason = "cancelled"
                raise
            finally:
                await state.signals.asend(
                    "spider_closed", spider=self, result=state.result, reason=reason
                )
