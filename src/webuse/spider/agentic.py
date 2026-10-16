"""Goal-driven async spider using the shared project and pipeline lifecycle."""

import asyncio
from functools import partial

from ..agent import AgentLimits
from ..engine.agentic import agentic_crawl
from ..exceptions import SpiderError
from ..models import CrawlResult
from ..extract.rules import _aiter_values
from ..pipelines.utils import _apipeline_lifecycle, _aprocess_items
from .aio import AsyncSpider
from .config import EffectiveAgenticSettings


class AgenticSpider(AsyncSpider):
    """Declare goal, item_model and limits; the LLM chooses crawler actions."""

    _settings_class = EffectiveAgenticSettings
    goal: str = ""
    limits: AgentLimits | None = None
    model = None
    llm = None
    tools = ()
    max_depth = None

    async def _arun(self, project_config, project_base_dir, overrides):
        model = overrides.pop("model", self.model)
        llm = overrides.pop("llm", self.llm)
        tools = overrides.pop("tools", self.tools)
        state, engine_overrides = self._prepare_run(
            overrides, project_config, project_base_dir
        )
        goal = state.settings.goal
        limits = state.settings.limits
        if state.settings.follow or state.settings.extract:
            raise SpiderError("AgenticSpider uses a goal, not follow/extract rules")
        if state.settings.pages is not None and state.settings.pages.patterns:
            raise SpiderError("AgenticSpider uses a goal, not URL page_type routing")
        if not state.settings.dedupe:
            raise SpiderError("AgenticSpider requires dedupe=True")
        if state.settings.max_requests is not None:
            limits = limits.model_copy(
                update={
                    "max_requests": min(
                        limits.max_requests, state.settings.max_requests
                    )
                    if limits.max_requests is not None
                    else state.settings.max_requests
                }
            )
            limits = AgentLimits.model_validate(limits.model_dump())
        item_model = self._pipeline_item_model()
        if item_model is None:
            raise SpiderError("AgenticSpider requires item_model")
        state.result = CrawlResult()

        async def process(item):
            return [
                processed
                async for processed in _aprocess_items(
                    _aiter_values(item),
                    state.pipelines,
                    coerce_item=self._coerce_pipeline_item,
                    emit=partial(state.signals.asend, spider=self),
                )
            ]

        with self._activate_run(state):
            reason = "error"
            try:
                await state.signals.asend("spider_open", spider=self)
                async with _apipeline_lifecycle(state.pipelines):
                    await agentic_crawl(
                        state.settings.start_urls,
                        goal=goal,
                        item_model=item_model,
                        limits=limits,
                        model=model,
                        llm=llm,
                        tools=list(tools),
                        allowed_domains=state.settings.allowed_domains,
                        max_depth=state.settings.max_depth,
                        robots_txt=state.settings.robots_txt,
                        user_agent=state.settings.user_agent,
                        request_defaults=state.settings.request_defaults,
                        signals=state.signals,
                        process_item=process,
                        result=state.result,
                        **engine_overrides,
                    )
                reason = state.result.close_reason or "finished"
                return state.result
            except asyncio.CancelledError:
                reason = "cancelled"
                raise
            finally:
                await state.signals.asend(
                    "spider_closed", spider=self, result=state.result, reason=reason
                )
