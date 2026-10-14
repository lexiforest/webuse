import importlib
import inspect
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..config import load_config_file
from ..engine.policy import coerce_domains
from ..extract import extract_handles_category, extract_items
from ..extract.schema import compile_extraction
from ..exceptions import ConfigError, PipelineError, SpiderError
from ..models import CrawlRequest, CrawlResult
from ..pipelines import AsyncItemPipeline, ItemPipeline, create_pipelines
from ..signals import SignalBus
from .config import (
    EffectiveSpiderSettings,
    ProjectConfig,
    SpiderConfig,
    compile_pages_config,
)


UNSET = object()


_SPIDER_CONFIG_FIELDS = set(SpiderConfig.model_fields)


@dataclass
class SpiderRun:
    """State owned by one invocation of a spider."""

    settings: EffectiveSpiderSettings
    pipelines: list[ItemPipeline | AsyncItemPipeline]
    signals: SignalBus
    result: CrawlResult | None = None


class BaseSpider:
    """Shared configuration and helpers for synchronous and asynchronous spiders."""

    _run_state: SpiderRun | None = None
    _settings_class = EffectiveSpiderSettings

    name: str | None = None
    start_urls: Any = ()
    routes: dict[str, Any] = {}
    follow: Any = None
    extract: Any = None
    item_model: type[BaseModel] | str | None = None
    pipelines: Any = None
    project_dir: str | Path | None = None
    config_path: str | Path | None = None
    spider_config: SpiderConfig | None = None
    spider_config_path: str | Path | None = None
    max_depth: int = 0
    max_requests: int | None = None
    concurrency: int | None = None
    per_domain: int | None = None
    dedupe: bool = True
    robots_txt: bool | None = None
    user_agent: str | None = None
    allowed_domains: set[str] | list[str] | tuple[str, ...] | None = None
    request_defaults: dict[str, Any] | None = None
    signals: SignalBus | None = None

    def __init__(self, **overrides: Any) -> None:
        for key, value in overrides.items():
            if not hasattr(self, key):
                raise SpiderError(f"Unknown spider option: {key}")
            setattr(self, key, value)

    def start(self) -> str | list[str] | list[CrawlRequest]:
        return self.start_urls

    def parse(self, response: Any) -> Any:
        settings = self._run_state.settings if self._run_state is not None else None
        extract = settings.extract if settings is not None else self.extract
        return extract_items(response, extract)

    def on_error(self, exc: Exception, request: CrawlRequest) -> None:
        return None

    def _route_handler(self, category: str | None) -> Any:
        if not category:
            return self.parse
        handler = self.routes.get(category)
        if handler is None:
            method_name = f"parse_{category}"
            handler = getattr(self, method_name, None)
        if handler is None:
            raise SpiderError(f"No parse route for request category: {category!r}")
        if isinstance(handler, str):
            handler = getattr(self, handler, None)
            if handler is None:
                raise SpiderError(f"No parse route for request category: {category!r}")
        if inspect.isfunction(handler):
            return lambda response: handler(self, response)
        if not callable(handler):
            raise SpiderError(f"Parse route for category {category!r} is not callable")
        return handler

    def _config_path(self) -> Path | None:
        if self.config_path is not None:
            return Path(self.config_path)
        config_names = ("webuse.toml", "webuse.yaml", "webuse.yml")
        if self.project_dir is not None:
            for name in config_names:
                path = Path(self.project_dir) / name
                if path.exists():
                    return path
        return None

    def _project_config(self) -> tuple[ProjectConfig | None, Path | None]:
        config_path = self._config_path()
        if config_path is None:
            return None, None
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
        try:
            return ProjectConfig.model_validate(
                load_config_file(config_path)
            ), config_path.parent
        except ValidationError as exc:
            raise ConfigError(f"Invalid project config: {config_path}: {exc}") from exc

    def _spider_config(self) -> SpiderConfig | None:
        if self.spider_config is not None:
            return self.spider_config
        if self.spider_config_path is None:
            return None
        try:
            return SpiderConfig.model_validate(
                load_config_file(self.spider_config_path)
            )
        except ValidationError as exc:
            raise ConfigError(
                f"Invalid spider config: {self.spider_config_path}: {exc}"
            ) from exc

    def _resolve_pipeline_chain(
        self,
        override: Any = UNSET,
        *,
        spider_config: SpiderConfig | None = None,
        project_base_dir: Path | None = None,
    ) -> list[ItemPipeline | AsyncItemPipeline]:
        if override is not UNSET:
            return create_pipelines(override)
        if self.pipelines is not None:
            return create_pipelines(self.pipelines, base_dir=project_base_dir)
        specs = spider_config.pipeline_specs() if spider_config is not None else None
        base_dir = project_base_dir
        if base_dir is None and self.spider_config_path is not None:
            base_dir = Path(self.spider_config_path).parent
        return create_pipelines(specs, base_dir=base_dir)

    def _resolve_settings(
        self,
        overrides: dict[str, Any],
        *,
        project_config: ProjectConfig | None = None,
        spider_config: SpiderConfig | None = None,
    ) -> tuple[EffectiveSpiderSettings, dict[str, Any]]:
        setting_fields = self._settings_class.model_fields
        values = {key: getattr(self, key) for key in setting_fields}
        values["start_urls"] = self.start()

        spider_config = spider_config or self._spider_config()
        if spider_config is not None:
            for key in spider_config.model_fields_set & _SPIDER_CONFIG_FIELDS:
                if key in {"same_domain", "items"}:
                    continue
                if key == "pages":
                    follow, extract = compile_pages_config(
                        spider_config.pages, same_domain=spider_config.same_domain
                    )
                    values["follow"] = follow
                    values["extract"] = extract
                    continue
                if key not in setting_fields:
                    raise ConfigError(f"Spider config {key!r} requires AgenticSpider")
                value = getattr(spider_config, key)
                values[key] = value

        concurrency_defaults = project_config.concurrency if project_config else {}
        if values["concurrency"] is None:
            values["concurrency"] = concurrency_defaults.get("limit", 10)
        if values["per_domain"] is None:
            values["per_domain"] = concurrency_defaults.get("per_domain")
        if values["robots_txt"] is None:
            values["robots_txt"] = (
                project_config.robots_txt
                if project_config and project_config.robots_txt is not None
                else False
            )
        if not values["user_agent"]:
            values["user_agent"] = (
                project_config.user_agent
                if project_config and project_config.user_agent
                else "webuse"
            )

        crawl_overrides = dict(overrides)
        for key in list(crawl_overrides):
            if key in setting_fields:
                values[key] = crawl_overrides.pop(key)

        values["extract"] = compile_extraction(values["extract"])
        settings = self._settings_class.model_validate(values)
        settings.allowed_domains = coerce_domains(settings.allowed_domains)
        settings.robots_txt = bool(settings.robots_txt)
        settings.user_agent = settings.user_agent or "webuse"
        return settings, crawl_overrides

    def _import_item_model(self, path: str) -> type[BaseModel]:
        module_name, _, object_name = path.rpartition(".")
        if not module_name or not object_name:
            raise SpiderError(
                f"Spider.item_model import path must be module.Object: {path!r}"
            )
        inserted = False
        if self.project_dir is not None:
            search_path = str(Path(self.project_dir))
            if search_path not in sys.path:
                sys.path.insert(0, search_path)
                inserted = True
        try:
            try:
                module = importlib.import_module(module_name)
                item_model = getattr(module, object_name)
            except (AttributeError, ModuleNotFoundError) as exc:
                raise SpiderError(f"Cannot import Spider.item_model: {path!r}") from exc
        finally:
            if inserted:
                sys.path.remove(search_path)
        if not isinstance(item_model, type) or not issubclass(item_model, BaseModel):
            raise SpiderError("Spider.item_model must be a pydantic BaseModel subclass")
        return item_model

    def _pipeline_item_model(self) -> type[BaseModel] | None:
        if self.item_model is None:
            return None
        if isinstance(self.item_model, str):
            return self._import_item_model(self.item_model)
        if not isinstance(self.item_model, type) or not issubclass(
            self.item_model, BaseModel
        ):
            raise SpiderError("Spider.item_model must be a pydantic BaseModel subclass")
        return self.item_model

    def _coerce_pipeline_item(self, item: Any) -> BaseModel:
        if isinstance(item, BaseModel):
            return item
        item_payload = item
        item_model_spec = None
        if isinstance(item, dict):
            item_model_spec = item.get("_item_model")
            if item_model_spec is not None:
                item_payload = {
                    key: value
                    for key, value in item.items()
                    if key not in {"_item_model", "_type"}
                }
        if isinstance(item_model_spec, str):
            item_model = self._import_item_model(item_model_spec)
            try:
                return item_model.model_validate(item_payload)
            except Exception as exc:
                raise PipelineError(
                    f"Cannot convert item to {item_model.__name__}: {item!r}"
                ) from exc
        if isinstance(item_model_spec, type) and issubclass(item_model_spec, BaseModel):
            try:
                return item_model_spec.model_validate(item_payload)
            except Exception as exc:
                raise PipelineError(
                    f"Cannot convert item to {item_model_spec.__name__}: {item!r}"
                ) from exc
        item_model = self._pipeline_item_model()
        if item_model is None:
            raise PipelineError(
                "Pipelines require pydantic BaseModel items; set Spider.item_model or return BaseModel items from parse()"
            )
        try:
            return item_model.model_validate(item_payload)
        except Exception as exc:
            raise PipelineError(
                f"Cannot convert item to {item_model.__name__}: {item!r}"
            ) from exc

    def _response_handler(
        self, response: Any, settings: EffectiveSpiderSettings
    ) -> Any:
        category = getattr(getattr(response, "crawl_request", None), "category", None)
        try:
            return self._route_handler(category)
        except SpiderError:
            if not extract_handles_category(settings.extract, category):
                raise
            return self.parse

    def _prepare_run(
        self,
        overrides: dict[str, Any],
        project_config: ProjectConfig | None,
        project_base_dir: Path | None,
    ) -> tuple[SpiderRun, dict[str, Any]]:
        if self._run_state is not None:
            raise SpiderError("A spider instance can only run one crawl at a time")
        pipeline_override = overrides.pop("pipelines", UNSET)
        signals = overrides.pop("signals", None) or self.signals or SignalBus()
        spider_config = self._spider_config()
        settings, engine_overrides = self._resolve_settings(
            overrides, project_config=project_config, spider_config=spider_config
        )
        pipelines = self._resolve_pipeline_chain(
            pipeline_override,
            spider_config=spider_config,
            project_base_dir=project_base_dir,
        )
        return SpiderRun(settings, pipelines, signals), engine_overrides

    @contextmanager
    def _activate_run(self, state: SpiderRun) -> Iterator[None]:
        if self._run_state is not None:
            raise SpiderError("A spider instance can only run one crawl at a time")
        self._run_state = state
        try:
            yield
        finally:
            self._run_state = None

    def _crawl_options(
        self,
        settings: EffectiveSpiderSettings,
        overrides: dict[str, Any],
        *,
        extract: Callable[[Any], Any],
    ) -> dict[str, Any]:
        options = {
            "extract": extract,
            "follow": settings.follow,
            "max_depth": settings.max_depth,
            "max_requests": settings.max_requests,
            "concurrency": settings.concurrency,
            "per_domain": settings.per_domain,
            "dedupe": settings.dedupe,
            "robots_txt": settings.robots_txt,
            "user_agent": settings.user_agent,
            "allowed_domains": settings.allowed_domains,
            "on_error": self.on_error,
            "request_defaults": settings.request_defaults,
        }
        options.update(overrides)
        options["allowed_domains"] = coerce_domains(options.get("allowed_domains"))
        options["robots_txt"] = bool(options.get("robots_txt"))
        options["user_agent"] = options.get("user_agent") or "webuse"
        return options
