import argparse
import asyncio
import importlib
import importlib.util
import inspect
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from ..engine import (
    RedisRequestQueue,
    RedisRequestSeen,
)
from ..models import CrawlResult
from ..pipelines import CsvPipeline, JsonlPipeline, ItemPipeline, SQLitePipeline
from ..pipelines.utils import _pipeline_lifecycle
from ..signals import SignalBus
from ..spider import AgenticSpider, AsyncSpider, Spider
from ..spider.config import SpiderConfig
from ..log import configure_logger
from .utils import _pair
from .project import load_project_config as _project_config, require_project_dir


_SPIDER_CONFIG_SUFFIXES = {".toml", ".yaml", ".yml"}
_OUTPUT_EXTENSIONS = {
    ".jsonl": JsonlPipeline,
    ".csv": CsvPipeline,
    ".sqlite": SQLitePipeline,
    ".sqlite3": SQLitePipeline,
    ".db": SQLitePipeline,
}


class _OutputItem(BaseModel):
    model_config = ConfigDict(extra="allow")


class _InlineSpiderTarget:
    def __init__(self, name: str, config: SpiderConfig):
        self.name = name
        self.config = config


def _state_name(target: str) -> str:
    return (
        target.replace("/", "_").replace("\\", "_").replace(":", "_").replace(".", "_")
    )


def _state_options(value: str | None, *, target: str) -> dict[str, Any]:
    if not value:
        return {}
    parsed = urlparse(value)
    if parsed.scheme != "redis":
        raise SystemExit("--state requires a redis:// URL")
    name = _state_name(target)
    return {
        "request_queue": RedisRequestQueue(
            f"webuse:{name}:requests:queue", redis_url=value
        ),
        "request_seen": RedisRequestSeen(
            f"webuse:{name}:requests:seen", redis_url=value
        ),
    }


def _module_from_path(path: Path) -> Any:
    path = path.resolve()
    module_name = f"_webuse_spider_{path.stem}_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import spider file: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _module_from_import_path(target: str, project_dir: Path) -> Any:
    search_paths = [str(project_dir), str(project_dir.parent)]
    inserted = [path for path in search_paths if path not in sys.path]
    sys.path[:0] = inserted
    try:
        return importlib.import_module(target)
    except ModuleNotFoundError as exc:
        raise SystemExit(f"cannot find spider: {target}") from exc
    finally:
        for path in inserted:
            sys.path.remove(path)


def _configure_project_logging(project_dir: Path) -> None:
    config = _project_config(project_dir).log
    if not config:
        return
    destination = config.get("file", "stderr")
    sink = {"stderr": sys.stderr, "stdout": sys.stdout}.get(destination)
    if sink is None:
        sink = project_dir / destination
        sink.parent.mkdir(parents=True, exist_ok=True)
    configure_logger(config.get("level"), sink=sink, append=config.get("append", True))


def _inline_spider_target(name: str, value: Any) -> _InlineSpiderTarget:
    if not isinstance(value, dict):
        raise SystemExit(
            f"spiders.{name} must be a mapping, config path, or module path"
        )
    payload = dict(value)
    payload.setdefault("name", name)
    try:
        config = SpiderConfig.model_validate(payload)
    except ValidationError as exc:
        raise SystemExit(
            f"invalid inline spider config: spiders.{name}: {exc}"
        ) from exc
    return _InlineSpiderTarget(name, config)


def _spider_target_from_project_entry(
    name: str, value: Any, *, project_dir: Path
) -> str | _InlineSpiderTarget:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        raise SystemExit(
            f"spiders.{name} must be a mapping, config path, or module path"
        )
    for key in ("config", "path"):
        target = value.get(key)
        if isinstance(target, str) and target:
            path = Path(target)
            return str(path if path.is_absolute() else project_dir / path)
    module = value.get("module")
    if isinstance(module, str) and module:
        return module
    return _inline_spider_target(name, value)


def _spider_targets_from_project_config(
    project_dir: Path, spider: str | None
) -> list[str | _InlineSpiderTarget]:
    config = _project_config(project_dir)
    if not config.spiders:
        raise SystemExit("project config must define a non-empty spiders section")
    if spider is not None:
        if spider not in config.spiders:
            raise SystemExit(f"spider not found in project config: {spider}")
        return [
            _spider_target_from_project_entry(
                spider, config.spiders[spider], project_dir=project_dir
            )
        ]
    return [
        _spider_target_from_project_entry(name, value, project_dir=project_dir)
        for name, value in config.spiders.items()
    ]


def _module_from_target(target: str, *, project_dir: Path) -> Any:
    path = Path(target)
    if not path.is_absolute():
        path = project_dir / path
    if path.is_file():
        search_path = str(project_dir)
        inserted = search_path not in sys.path
        if inserted:
            sys.path.insert(0, search_path)
        try:
            return _module_from_path(path)
        finally:
            if inserted:
                sys.path.remove(search_path)
    if path.suffix == ".py":
        raise SystemExit(f"cannot find spider file: {path}")
    return _module_from_import_path(target, project_dir)


def _configure_spider(
    spider: Spider | AsyncSpider, project_dir: Path
) -> Spider | AsyncSpider:
    spider.project_dir = project_dir
    if spider.spider_config_path is not None:
        config_path = Path(spider.spider_config_path)
        if not config_path.is_absolute():
            spider.spider_config_path = project_dir / config_path
    return spider


def _spider_from_module(module: Any, project_dir: Path) -> Spider | AsyncSpider:
    candidates = []
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, (Spider, AsyncSpider))
            and value not in (Spider, AsyncSpider, AgenticSpider)
        ):
            candidates.append(value)
    if not candidates:
        raise SystemExit(
            "no webuse.Spider or webuse.AsyncSpider subclass found in "
            f"{getattr(module, '__name__', module)!r}"
        )
    if len(candidates) > 1:
        names = ", ".join(candidate.__name__ for candidate in candidates)
        raise SystemExit(f"multiple spiders found; register module:Class: {names}")
    return _configure_spider(candidates[0](), project_dir)


def _load_spider(
    target: str | _InlineSpiderTarget,
    *,
    project_dir: Path,
    spider_class: type[Spider] | type[AsyncSpider] = Spider,
) -> Spider | AsyncSpider:
    if isinstance(target, _InlineSpiderTarget):
        return spider_class(spider_config=target.config, project_dir=project_dir)
    module_target, separator, class_name = target.rpartition(":")
    if separator:
        module = _module_from_target(module_target, project_dir=project_dir)
        spider_class = getattr(module, class_name, None)
        if spider_class is None:
            raise SystemExit(f"spider class not found: {target}")
        if not isinstance(spider_class, type) or not issubclass(
            spider_class, (Spider, AsyncSpider)
        ):
            raise SystemExit(
                f"not a webuse.Spider or webuse.AsyncSpider subclass: {target}"
            )
        return _configure_spider(spider_class(), project_dir)
    path = Path(target)
    if path.suffix in _SPIDER_CONFIG_SUFFIXES:
        if not path.is_absolute():
            path = project_dir / path
        if not path.is_file():
            raise SystemExit(f"cannot find spider config: {path}")
        return spider_class(spider_config_path=path, project_dir=project_dir)
    return _spider_from_module(
        _module_from_target(target, project_dir=project_dir), project_dir
    )


def _attribute_pair(value: str) -> tuple[str, str]:
    return _pair(value, "--attribute")


def _attributes(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        key, item = _attribute_pair(value)
        result[key] = item
    return result


def _apply_attributes(
    spider: Spider | AsyncSpider, attributes: dict[str, str]
) -> Spider | AsyncSpider:
    for key, value in attributes.items():
        setattr(spider, key, value)
    return spider


def _spider_targets_from_crawl_target(
    target: str, spider: str | None
) -> tuple[list[str | _InlineSpiderTarget], Path]:
    project_dir = require_project_dir(target)
    return _spider_targets_from_project_config(project_dir, spider), project_dir


def _output_pipeline(output: str) -> ItemPipeline:
    path = Path(output)
    extension = path.suffix.lower()
    pipeline_class = _OUTPUT_EXTENSIONS.get(extension)
    if pipeline_class is None:
        supported = ", ".join(sorted(_OUTPUT_EXTENSIONS))
        raise SystemExit(
            f"unsupported output extension: {extension or '<none>'}. Supported extensions: {supported}"
        )
    if pipeline_class is SQLitePipeline and path.exists():
        path.unlink()
    if pipeline_class in {JsonlPipeline, CsvPipeline}:
        return pipeline_class(path, append=False)
    return pipeline_class(path)


@contextmanager
def _stream_spider_output(spider: Spider | AsyncSpider, pipeline: ItemPipeline | None):
    """Write processed records immediately, preserving the spider's own hooks."""
    original_signals = spider.signals
    signals = original_signals or SignalBus()
    written = 0

    def write(item):
        nonlocal written
        if pipeline is not None:
            if isinstance(item, dict):
                item = _OutputItem.model_validate(item)
            pipeline.process_item(item)
            written += 1

    def write_remaining(result):
        # Custom run() implementations may return items without dispatching
        # item_processed. Normal spiders have already written all their items.
        if pipeline is not None:
            for item in result.items[written:]:
                write(item)

    if pipeline is not None:
        signals.connect("item_processed", write)
        spider.signals = signals
    try:
        yield write_remaining
    finally:
        if pipeline is not None:
            signals.disconnect("item_processed", write)
            spider.signals = original_signals


def _run_single_spider(
    target: str | _InlineSpiderTarget,
    *,
    project_dir: Path,
    attributes: dict[str, str] | None = None,
    state: str | None = None,
    max_requests: int | None = None,
    output: ItemPipeline | None = None,
) -> CrawlResult:
    spider = _apply_attributes(
        _load_spider(target, project_dir=project_dir), attributes or {}
    )
    with _stream_spider_output(spider, output) as write_remaining:
        result = spider.run(
            **({"max_requests": max_requests} if max_requests is not None else {}),
            **_state_options(
                state,
                target=target.name
                if isinstance(target, _InlineSpiderTarget)
                else target,
            ),
        )
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        write_remaining(result)
    return result


async def _arun_single_spider(
    target: str | _InlineSpiderTarget,
    *,
    project_dir: Path,
    attributes: dict[str, str] | None = None,
    state: str | None = None,
    max_requests: int | None = None,
    output: ItemPipeline | None = None,
) -> CrawlResult:
    if state:
        raise SystemExit("--state is currently supported only for sync crawl")
    spider = _apply_attributes(
        _load_spider(target, project_dir=project_dir, spider_class=AsyncSpider),
        attributes or {},
    )
    with _stream_spider_output(spider, output) as write_remaining:
        result = spider.run(
            **({"max_requests": max_requests} if max_requests is not None else {})
        )
        if inspect.isawaitable(result):
            result = await result
        write_remaining(result)
    return result


def crawl_command(args: argparse.Namespace) -> int:
    if args.max_requests is not None and args.max_requests < 1:
        raise SystemExit("--max-requests must be positive")
    targets, project_dir = _spider_targets_from_crawl_target(
        args.directory, args.spider
    )
    _configure_project_logging(project_dir)
    attributes = _attributes(args.attribute)
    results = []
    remaining = args.max_requests
    output = _output_pipeline(args.output) if args.output else None
    with _pipeline_lifecycle([output] if output is not None else []):
        for target in targets:
            if remaining is not None and remaining <= 0:
                break
            current = _run_single_spider(
                target,
                project_dir=project_dir,
                attributes=attributes,
                state=args.state,
                max_requests=remaining,
                output=output,
            )
            results.append(current)
            if remaining is not None:
                remaining -= current.stats.queued
    return (
        0
        if all(
            not current.errors
            and (current.agent is None or current.close_reason == "finished")
            for current in results
        )
        else 1
    )


async def acrawl_command(args: argparse.Namespace) -> int:
    if args.max_requests is not None and args.max_requests < 1:
        raise SystemExit("--max-requests must be positive")
    targets, project_dir = _spider_targets_from_crawl_target(
        args.directory, args.spider
    )
    _configure_project_logging(project_dir)
    attributes = _attributes(args.attribute)
    results = []
    remaining = args.max_requests
    output = _output_pipeline(args.output) if args.output else None
    with _pipeline_lifecycle([output] if output is not None else []):
        for target in targets:
            if remaining is not None and remaining <= 0:
                break
            current = await _arun_single_spider(
                target,
                project_dir=project_dir,
                attributes=attributes,
                state=args.state,
                max_requests=remaining,
                output=output,
            )
            results.append(current)
            if remaining is not None:
                remaining -= current.stats.queued
    return (
        0
        if all(
            not current.errors
            and (current.agent is None or current.close_reason == "finished")
            for current in results
        )
        else 1
    )


def register(subparsers: argparse._SubParsersAction) -> None:
    crawl_parser = subparsers.add_parser(
        "crawl", help="run registered spiders in a project"
    )
    crawl_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="project directory (default: current directory)",
    )
    crawl_parser.add_argument("--spider", help="registered spider name (default: all)")
    crawl_parser.add_argument("-a", "--attribute", action="append")
    crawl_parser.add_argument("-o", "--output")
    crawl_parser.add_argument(
        "--state", metavar="REDIS_URL", help="Redis scheduler state URL (sync only)"
    )
    crawl_parser.add_argument("--async", dest="use_async", action="store_true")
    crawl_parser.add_argument("--max-requests", type=int)
    crawl_parser.set_defaults(func=crawl_command, async_func=acrawl_command)
