import inspect
import importlib
import sys
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..crawl.sync import crawl
from ..crawl.utils import (
    UNSET,
    coerce_domains,
    extract_items,
    follow_rule_from_config,
    handle_callback_result,
    load_config_file,
)
from ..exceptions import ConfigError, PipelineError, SpiderError
from ..models import CrawlRequest, CrawlResult
from ..pipelines import DropItem, Pipeline, resolve_pipelines
from ..signals import SignalBus
from .config import EffectiveSpiderSettings, ProjectConfig, SpiderConfig


_SETTING_FIELDS = set(EffectiveSpiderSettings.model_fields)
_SPIDER_CONFIG_FIELDS = set(SpiderConfig.model_fields)


class Spider:
    name: str | None = None
    start_urls: Any = ()
    routes: dict[str, Any] = {}
    follow: Any = None
    extract: Any = None
    item_model: type[BaseModel] | str | None = None
    pipelines: Any = None
    project_dir: str | Path | None = None
    config_path: str | Path | None = None
    spider_config_path: str | Path | None = None
    max_depth: int = 0
    max_requests: int | None = None
    concurrency: int = 10
    dedupe: bool = True
    robots_txt: bool | None = None
    user_agent: str | None = None
    allowed_domains: set[str] | list[str] | tuple[str, ...] | None = None
    request_defaults: dict[str, Any] | None = None
    signals: SignalBus | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "seeds" in cls.__dict__:
            raise SpiderError("Spider.seeds is not supported; use Spider.start_urls")
        if "start_requests" in cls.__dict__:
            raise SpiderError(
                "Spider.start_requests is not supported; use Spider.start"
            )

    def __init__(self, **overrides: Any) -> None:
        for key, value in overrides.items():
            if not hasattr(self, key):
                raise SpiderError(f"Unknown spider option: {key}")
            setattr(self, key, value)

    def start(self) -> str | list[str] | list[CrawlRequest]:
        return self.start_urls

    def parse(self, response: Any) -> Any:
        settings = getattr(self, "_active_settings", None)
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

    def _pipeline_lock(self) -> threading.Lock:
        if not hasattr(self, "_pipeline_lock_obj"):
            self._pipeline_lock_obj = threading.Lock()
        return self._pipeline_lock_obj

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
        project_config: ProjectConfig | None = None,
        project_base_dir: Path | None = None,
    ) -> list[Pipeline]:
        if override is not UNSET:
            return resolve_pipelines(override)
        if self.pipelines is not None:
            return resolve_pipelines(self.pipelines)
        specs = project_config.pipeline_specs() if project_config is not None else None
        return resolve_pipelines(specs, base_dir=project_base_dir)

    def _resolve_settings(
        self,
        overrides: dict[str, Any],
        *,
        project_config: ProjectConfig | None = None,
    ) -> tuple[EffectiveSpiderSettings, dict[str, Any]]:
        values = {
            "name": self.name,
            "start_urls": self.start(),
            "follow": self.follow,
            "extract": self.extract,
            "max_depth": self.max_depth,
            "max_requests": self.max_requests,
            "concurrency": self.concurrency,
            "dedupe": self.dedupe,
            "robots_txt": self.robots_txt,
            "user_agent": self.user_agent,
            "allowed_domains": self.allowed_domains,
            "request_defaults": self.request_defaults,
        }

        spider_config = self._spider_config()
        if spider_config is not None:
            for key in spider_config.model_fields_set & _SPIDER_CONFIG_FIELDS:
                if key == "same_domain":
                    continue
                value = getattr(spider_config, key)
                if key == "follow" and value is not None:
                    rules = value if isinstance(value, list) else [value]
                    value = [
                        follow_rule_from_config(
                            rule, same_domain=spider_config.same_domain
                        )
                        for rule in rules
                    ]
                values[key] = value

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
            if key in _SETTING_FIELDS:
                values[key] = crawl_overrides.pop(key)

        settings = EffectiveSpiderSettings.model_validate(values)
        settings.allowed_domains = coerce_domains(settings.allowed_domains)
        settings.robots_txt = bool(settings.robots_txt)
        settings.user_agent = settings.user_agent or "webuse"
        return settings, crawl_overrides

    def _open_pipelines(self, pipelines: list[Pipeline]) -> None:
        opened: list[Pipeline] = []
        try:
            for pipeline in pipelines:
                open_spider = getattr(pipeline, "open_spider", None)
                if open_spider:
                    open_spider()
                opened.append(pipeline)
        except Exception:
            for pipeline in reversed(opened):
                close_spider = getattr(pipeline, "close_spider", None)
                if close_spider:
                    close_spider()
            raise

    def _close_pipelines(self, pipelines: list[Pipeline]) -> None:
        for pipeline in reversed(pipelines):
            close_spider = getattr(pipeline, "close_spider", None)
            if close_spider:
                close_spider()

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
        item_model = self._pipeline_item_model()
        if item_model is None:
            raise PipelineError(
                "Pipelines require pydantic BaseModel items; set Spider.item_model or return BaseModel items from parse()"
            )
        try:
            return item_model.model_validate(item)
        except Exception as exc:
            raise PipelineError(
                f"Cannot convert item to {item_model.__name__}: {item!r}"
            ) from exc

    def _ensure_pipeline_result(self, item: Any) -> BaseModel:
        if not isinstance(item, BaseModel):
            raise PipelineError(
                f"Pipelines must return pydantic BaseModel items or None, got {type(item).__name__}"
            )
        return item

    def _process_pipeline_items(
        self, items: list[Any], response: Any | None = None
    ) -> list[Any]:
        pipelines = getattr(self, "_active_pipelines", [])
        signal_bus = getattr(self, "_active_signals", None)
        if not pipelines:
            if signal_bus is not None:
                for item in items:
                    signal_bus.send(
                        "item_extracted", item=item, response=response, spider=self
                    )
                    signal_bus.send(
                        "item_processed", item=item, response=response, spider=self
                    )
            return items
        processed: list[Any] = []
        with self._pipeline_lock():
            for item in items:
                if signal_bus is not None:
                    signal_bus.send(
                        "item_extracted", item=item, response=response, spider=self
                    )
                current: BaseModel | None = self._coerce_pipeline_item(item)
                try:
                    for pipeline in pipelines:
                        if signal_bus is not None:
                            signal_bus.send(
                                "pipeline_started",
                                pipeline=pipeline,
                                item=current,
                                response=response,
                                spider=self,
                            )
                        current = pipeline.process_item(current)
                        if signal_bus is not None:
                            signal_bus.send(
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
                        signal_bus.send(
                            "item_dropped",
                            item=item,
                            response=response,
                            spider=self,
                            error=exc,
                        )
                    current = None
                except Exception as exc:
                    if signal_bus is not None:
                        signal_bus.send(
                            "pipeline_error",
                            item=item,
                            response=response,
                            spider=self,
                            error=exc,
                        )
                        signal_bus.send(
                            "item_error",
                            item=item,
                            response=response,
                            spider=self,
                            error=exc,
                        )
                    raise
                if current is not None:
                    if signal_bus is not None:
                        signal_bus.send(
                            "item_processed",
                            item=current,
                            response=response,
                            spider=self,
                        )
                    processed.append(current)
        return processed

    def _extract_callback(
        self, response: Any, settings: EffectiveSpiderSettings
    ) -> Any:
        request = getattr(response, "request", None)
        handler = self._route_handler(getattr(request, "category", None))
        parse_result = handler(response)
        if inspect.isawaitable(parse_result):
            raise SpiderError("async parse() requires AsyncSpider.run()")
        items, followups = handle_callback_result(parse_result)
        items = self._process_pipeline_items(items, response=response)
        if followups:
            return items, followups
        return items

    def _crawl_options(
        self, settings: EffectiveSpiderSettings, overrides: dict[str, Any]
    ) -> dict[str, Any]:
        options = {
            "extract": lambda response: self._extract_callback(response, settings),
            "follow": settings.follow,
            "max_depth": settings.max_depth,
            "max_requests": settings.max_requests,
            "concurrency": settings.concurrency,
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

    def run(self, **overrides: Any) -> CrawlResult:
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
        self._active_pipelines = pipelines
        self._active_settings = settings
        self._active_signals = signal_bus
        signal_bus.send("spider_open", spider=self)
        result: CrawlResult | None = None
        self._open_pipelines(pipelines)
        try:
            crawl_options = self._crawl_options(settings, crawl_overrides)
            crawl_options["signals"] = signal_bus
            result = crawl(settings.start_urls, **crawl_options)
            return result
        finally:
            self._close_pipelines(pipelines)
            signal_bus.send(
                "spider_closed",
                spider=self,
                result=result,
                reason=(result.close_reason if result else "error") or "finished",
            )
            self._active_pipelines = []
            self._active_settings = None
            self._active_signals = None
