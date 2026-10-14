from functools import partial
from pathlib import Path
from typing import Any

from ..engine.sync import crawl
from ..extract import ParseResult, extract_response
from ..llm import use_openai_settings
from ..models import CrawlResult
from ..pipelines.utils import _pipeline_lifecycle, _process_items
from .base import BaseSpider, SpiderRun
from .config import ProjectConfig


class Spider(BaseSpider):
    def _extract_callback(self, response: Any, state: SpiderRun) -> ParseResult:
        parsed = extract_response(
            response, self._response_handler(response, state.settings)
        )
        parsed.items = _process_items(
            parsed.items,
            state.pipelines,
            coerce_item=self._coerce_pipeline_item,
            emit=partial(state.signals.send, spider=self, response=response),
        )
        return parsed

    def run(self, **overrides: Any) -> CrawlResult:
        project_config, project_base_dir = self._project_config()
        with use_openai_settings(project_config.llm if project_config else None):
            return self._run(project_config, project_base_dir, overrides)

    def _run(
        self,
        project_config: ProjectConfig | None,
        project_base_dir: Path | None,
        overrides: dict[str, Any],
    ) -> CrawlResult:
        state, engine_overrides = self._prepare_run(
            overrides, project_config, project_base_dir
        )
        options = self._crawl_options(
            state.settings,
            engine_overrides,
            extract=lambda response: self._extract_callback(response, state),
        )
        options["signals"] = state.signals
        with self._activate_run(state):
            reason = "error"
            try:
                state.signals.send("spider_open", spider=self)
                with _pipeline_lifecycle(state.pipelines):
                    state.result = crawl(state.settings.start_urls, **options)
                reason = state.result.close_reason or "finished"
                return state.result
            finally:
                state.signals.send(
                    "spider_closed", spider=self, result=state.result, reason=reason
                )
