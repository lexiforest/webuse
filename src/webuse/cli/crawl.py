import argparse
import asyncio
import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError

from ..crawl import (
    FileRequestQueue,
    FileRequestSeen,
    RedisRequestQueue,
    RedisRequestSeen,
)
from ..models import CrawlResult, CrawlStats, FollowRule
from ..pipelines import CsvPipeline, JsonlPipeline, Pipeline, SQLitePipeline
from ..spider import AsyncSpider, Spider
from ..spider.config import ProjectConfig, SpiderConfig
from ..crawl.utils import load_config_file
from .common import add_request_args, cli_request_options


_CONFIG_NAMES = ("webuse.toml", "webuse.yaml", "webuse.yml")
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
    name = _state_name(target)
    if parsed.scheme == "redis":
        return {
            "request_queue": RedisRequestQueue(
                f"webuse:{name}:requests:queue", redis_url=value
            ),
            "request_seen": RedisRequestSeen(
                f"webuse:{name}:requests:seen", redis_url=value
            ),
        }
    path = Path(value)
    return {
        "request_queue": FileRequestQueue(path / name / "queue.jsonl"),
        "request_seen": FileRequestSeen(path / name / "seen.jsonl"),
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


def _project_dir_from_module(module: Any) -> Path | None:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return None
    path = Path(module_file).resolve()
    if path.parent.name == "spiders":
        return path.parent.parent
    return None


def _module_from_import_path(target: str) -> Any:
    search_path = str(Path.cwd())
    inserted = False
    if search_path not in sys.path:
        sys.path.insert(0, search_path)
        inserted = True
    try:
        return importlib.import_module(target)
    except ModuleNotFoundError as exc:
        raise SystemExit(f"cannot find spider: {target}") from exc
    finally:
        if inserted:
            sys.path.remove(search_path)


def _project_root_from(path: Path) -> Path | None:
    path = path.resolve()
    candidate = path if path.is_dir() else path.parent
    if any((candidate / name).exists() for name in _CONFIG_NAMES):
        return candidate
    return None


def _project_root_for_config(path: Path) -> Path | None:
    root = _project_root_from(path)
    if root is not None:
        return root
    resolved = path.resolve()
    if resolved.parent.name == "spiders":
        candidate = resolved.parent.parent
        if any((candidate / name).exists() for name in _CONFIG_NAMES):
            return candidate
    return None


def _spider_from_config_path(path: Path) -> Spider:
    spider = Spider(spider_config_path=path.resolve())
    project_dir = _project_root_for_config(path)
    if project_dir is not None:
        spider.project_dir = project_dir
    return spider


def _spider_files_from_project(project_dir: Path) -> list[Path]:
    spiders_dir = project_dir / "spiders"
    if not spiders_dir.is_dir():
        raise SystemExit(f"project has no spiders directory: {project_dir}")
    return sorted(
        path for path in spiders_dir.glob("*.py") if path.name != "__init__.py"
    )


def _project_config_path(project_dir: Path) -> Path:
    for name in _CONFIG_NAMES:
        path = project_dir / name
        if path.exists():
            return path
    raise SystemExit(f"cannot find webuse.toml or webuse.yaml in {project_dir}")


def _has_project_config(project_dir: Path) -> bool:
    return any((project_dir / name).exists() for name in _CONFIG_NAMES)


def _project_config(project_dir: Path) -> ProjectConfig:
    path = _project_config_path(project_dir)
    try:
        return ProjectConfig.model_validate(load_config_file(path))
    except ValidationError as exc:
        raise SystemExit(f"invalid project config: {path}: {exc}") from exc


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


def _module_from_target(target: str, *, project_dir: Path | None = None) -> Any:
    path = Path(target)
    if path.exists():
        if path.is_dir():
            raise SystemExit(
                f"target is a project directory, not a single spider: {target}"
            )
        return _module_from_path(path)
    if path.suffix == ".py":
        raise SystemExit(f"cannot find spider file: {target}")
    project_root = project_dir or _project_root_from(Path.cwd())
    if project_root is not None:
        spider_path = project_root / "spiders" / f"{target}.py"
        if spider_path.exists():
            return _module_from_path(spider_path)
    return _module_from_import_path(target)


def _configure_spider(spider: Spider, module: Any) -> Spider:
    module_file = getattr(module, "__file__", None)
    module_dir = Path(module_file).resolve().parent if module_file else None
    project_dir = _project_dir_from_module(module)
    if spider.project_dir is None and project_dir is not None:
        spider.project_dir = project_dir
    if spider.spider_config_path is not None:
        config_path = Path(spider.spider_config_path)
        if not config_path.is_absolute():
            candidates = []
            if project_dir is not None:
                candidates.append(project_dir / config_path)
            if module_dir is not None:
                candidates.append(module_dir / config_path)
            for candidate in candidates:
                if candidate.exists():
                    spider.spider_config_path = candidate
                    break
    return spider


def _spider_from_module(module: Any) -> Spider:
    candidates = []
    for value in vars(module).values():
        if (
            isinstance(value, type)
            and issubclass(value, Spider)
            and value is not Spider
        ):
            candidates.append(value)
    if not candidates:
        raise SystemExit(
            f"no webuse.Spider subclass found in {getattr(module, '__name__', module)!r}"
        )
    if len(candidates) > 1:
        names = ", ".join(candidate.__name__ for candidate in candidates)
        raise SystemExit(f"multiple spiders found; use module.Class: {names}")
    return _configure_spider(candidates[0](), module)


def _load_spider(
    target: str | _InlineSpiderTarget,
    *,
    project_dir: Path | None = None,
    spider_class: type[Spider] | type[AsyncSpider] = Spider,
) -> Spider:
    if isinstance(target, _InlineSpiderTarget):
        return spider_class(spider_config=target.config, project_dir=project_dir)
    module_target, separator, class_name = target.rpartition(":")
    if separator:
        module = _module_from_target(module_target, project_dir=project_dir)
        spider_class = getattr(module, class_name, None)
        if spider_class is None:
            raise SystemExit(f"spider class not found: {target}")
        if not isinstance(spider_class, type) or not issubclass(spider_class, Spider):
            raise SystemExit(f"not a webuse.Spider subclass: {target}")
        return _configure_spider(spider_class(), module)
    path = Path(target)
    if project_dir is not None and path.suffix in _SPIDER_CONFIG_SUFFIXES:
        candidates = (
            (project_dir / path.name, project_dir / "spiders" / path.name)
            if not path.is_absolute()
            else (path,)
        )
        for candidate in candidates:
            if candidate.exists():
                return _spider_from_config_path(candidate)
    if path.exists() and path.suffix in _SPIDER_CONFIG_SUFFIXES:
        return _spider_from_config_path(path)
    return _spider_from_module(_module_from_target(target, project_dir=project_dir))


def _attribute_pair(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit(f"--attribute argument must be KEY=VALUE: {value!r}")
    key, item = value.split("=", 1)
    key = key.strip()
    if not key:
        raise SystemExit(f"--attribute argument has an empty key: {value!r}")
    return key, item


def _attributes(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        key, item = _attribute_pair(value)
        result[key] = item
    return result


def _apply_attributes(spider: Spider, attributes: dict[str, str]) -> Spider:
    for key, value in attributes.items():
        setattr(spider, key, value)
    return spider


def _field_pair(value: str, label: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit(f"{label} argument must be KEY=VALUE: {value!r}")
    key, item = value.split("=", 1)
    key = key.strip()
    if not key:
        raise SystemExit(f"{label} argument has an empty key: {value!r}")
    if not item:
        raise SystemExit(f"{label} argument has an empty value: {value!r}")
    return key, item


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _standalone_option_used(args: argparse.Namespace) -> bool:
    return any(
        (
            args.css,
            args.xpath,
            args.smart,
            args.item_css,
            args.attr,
            args.all_fields,
            args.follow_css,
            args.follow_xpath,
            args.follow_attr,
            args.same_domain,
            args.allowed_domain,
            args.max_depth is not None,
            args.max_requests is not None,
            args.concurrency is not None,
            args.dedupe is not None,
            args.robots_txt is not None,
            args.user_agent,
            args.header,
            args.cookie,
            args.param,
            args.auth,
            args.proxy,
            args.proxy_auth,
            args.impersonate,
            args.timeout is not None,
            args.verify is not None,
            args.follow_redirects is not None,
            args.max_redirects is not None,
            args.ja3,
            args.akamai,
            args.extra_fp,
            args.default_headers is not None,
            args.http_version,
            args.interface,
            args.cert,
            args.referer,
        )
    )


def _extract_rules(args: argparse.Namespace) -> dict[str, Any] | None:
    fields: dict[str, dict[str, Any]] = {}
    for option_name, selector_type in (
        ("css", "css"),
        ("xpath", "xpath"),
        ("smart", "smart"),
    ):
        for value in getattr(args, option_name) or []:
            field, selector = _field_pair(value, f"--{option_name}")
            if field in fields:
                raise SystemExit(f"duplicate extract field: {field}")
            fields[field] = {selector_type: selector}
    attrs = _attributes(args.attr)
    for field, attr in attrs.items():
        if field not in fields:
            raise SystemExit(f"--attr references unknown extract field: {field}")
        fields[field]["attr"] = attr
    for field in args.all_fields or []:
        if field not in fields:
            raise SystemExit(f"--all references unknown extract field: {field}")
        fields[field]["all"] = True
    if not fields:
        return None
    rules: dict[str, Any] = {}
    if args.item_css:
        rules["item_css"] = args.item_css
        rules["fields"] = {}
        output_fields = rules["fields"]
    else:
        output_fields = rules
    for field, rule in fields.items():
        if set(rule) == {"css"}:
            output_fields[field] = rule["css"]
        else:
            output_fields[field] = rule
    return rules


def _follow_rules(args: argparse.Namespace) -> list[FollowRule] | None:
    attr = args.follow_attr or "href"
    rules = [
        FollowRule(css=selector, attr=attr, same_domain=bool(args.same_domain))
        for selector in args.follow_css or []
    ]
    rules.extend(
        FollowRule(xpath=selector, attr=attr, same_domain=bool(args.same_domain))
        for selector in args.follow_xpath or []
    )
    return rules or None


def _standalone_spider(
    args: argparse.Namespace, spider_class: type[Spider] | type[AsyncSpider]
) -> Spider:
    spider = spider_class(
        start_urls=[args.directory],
        extract=_extract_rules(args),
        follow=_follow_rules(args),
    )
    if args.max_depth is not None:
        spider.max_depth = args.max_depth
    if args.max_requests is not None:
        spider.max_requests = args.max_requests
    if args.concurrency is not None:
        spider.concurrency = args.concurrency
    if args.dedupe is not None:
        spider.dedupe = args.dedupe
    if args.robots_txt is not None:
        spider.robots_txt = args.robots_txt
    if args.user_agent:
        spider.user_agent = args.user_agent
    if args.allowed_domain:
        spider.allowed_domains = args.allowed_domain
    request_defaults = cli_request_options(args, {})
    if request_defaults:
        spider.request_defaults = request_defaults
    return spider


def _project_dir_from_target(target: str) -> Path:
    path = Path(target)
    if path.exists() and path.is_file():
        root = _project_root_from(path)
        return root if root is not None else path.resolve().parent
    if path.exists() and path.is_dir():
        return _project_root_from(path) or path.resolve()
    root = _project_root_from(Path.cwd())
    if root is None:
        raise SystemExit("cannot find webuse.toml or webuse.yaml")
    return root


def _spider_targets_from_crawl_target(
    target: str, spider: str | None
) -> tuple[list[str | _InlineSpiderTarget], Path | None]:
    if spider is None:
        target_path = Path(target)
        if target_path.exists() and target_path.is_file():
            if target_path.name in _CONFIG_NAMES:
                project_dir = target_path.resolve().parent
                return _spider_targets_from_project_config(
                    project_dir, None
                ), project_dir
            if target_path.suffix in _SPIDER_CONFIG_SUFFIXES:
                return [str(target_path)], _project_root_for_config(target_path)
        project_dir = _project_dir_from_target(target)
        return _spider_targets_from_project_config(project_dir, None), project_dir
    project_dir = (
        _project_dir_from_target(target)
        if Path(target).exists() or target == "."
        else _project_root_from(Path.cwd())
    )
    if project_dir is not None and _has_project_config(project_dir):
        return _spider_targets_from_project_config(project_dir, spider), project_dir
    return [spider], project_dir


def _merge_results(results: list[CrawlResult]) -> CrawlResult:
    merged = CrawlResult(stats=CrawlStats())
    for result in results:
        merged.items.extend(result.items)
        merged.pages.extend(result.pages)
        merged.errors.extend(result.errors)
        merged.visited.update(result.visited)
        for name in CrawlStats.model_fields:
            setattr(
                merged.stats,
                name,
                getattr(merged.stats, name) + getattr(result.stats, name),
            )
        if result.close_reason and merged.close_reason is None:
            merged.close_reason = result.close_reason
    return merged


def _output_pipeline(output: str) -> Pipeline:
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


def _write_output(result: CrawlResult, output: str | None) -> None:
    if output is None:
        return
    pipeline = _output_pipeline(output)
    pipeline.open_spider()
    try:
        for item in result.items:
            if isinstance(item, dict):
                item = _OutputItem.model_validate(item)
            pipeline.process_item(item)
    finally:
        pipeline.close_spider()


def _run_single_spider(
    target: str | _InlineSpiderTarget,
    *,
    project_dir: Path | None = None,
    attributes: dict[str, str] | None = None,
    state: str | None = None,
) -> CrawlResult:
    result = _apply_attributes(
        _load_spider(target, project_dir=project_dir), attributes or {}
    ).run(
        **_state_options(
            state,
            target=target.name if isinstance(target, _InlineSpiderTarget) else target,
        )
    )
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result


async def _arun_single_spider(
    target: str | _InlineSpiderTarget,
    *,
    project_dir: Path | None = None,
    attributes: dict[str, str] | None = None,
    state: str | None = None,
) -> CrawlResult:
    if state:
        raise SystemExit("--state is currently supported only for sync crawl")
    result = _apply_attributes(
        _load_spider(target, project_dir=project_dir, spider_class=AsyncSpider),
        attributes or {},
    ).run()
    if inspect.isawaitable(result):
        result = await result
    return result


def _run_standalone(args: argparse.Namespace) -> CrawlResult:
    result = _standalone_spider(args, Spider).run(
        **_state_options(args.state, target=args.directory)
    )
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result


async def _arun_standalone(args: argparse.Namespace) -> CrawlResult:
    if args.state:
        raise SystemExit("--state is currently supported only for sync crawl")
    result = _standalone_spider(args, AsyncSpider).run()
    if inspect.isawaitable(result):
        result = await result
    return result


def crawl_command(args: argparse.Namespace) -> int:
    if _is_url(args.directory):
        if args.spider:
            raise SystemExit("--spider cannot be used with a URL crawl target")
        result = _run_standalone(args)
        _write_output(result, args.output)
        return 0 if not result.errors else 1
    if _standalone_option_used(args):
        raise SystemExit("standalone crawl options require a URL crawl target")
    targets, project_dir = _spider_targets_from_crawl_target(
        args.directory, args.spider
    )
    attributes = _attributes(args.attribute)
    result = _merge_results(
        [
            _run_single_spider(
                target, project_dir=project_dir, attributes=attributes, state=args.state
            )
            for target in targets
        ]
    )
    _write_output(result, args.output)
    return 0 if not result.errors else 1


async def acrawl_command(args: argparse.Namespace) -> int:
    if _is_url(args.directory):
        if args.spider:
            raise SystemExit("--spider cannot be used with a URL crawl target")
        result = await _arun_standalone(args)
        _write_output(result, args.output)
        return 0 if not result.errors else 1
    if _standalone_option_used(args):
        raise SystemExit("standalone crawl options require a URL crawl target")
    targets, project_dir = _spider_targets_from_crawl_target(
        args.directory, args.spider
    )
    attributes = _attributes(args.attribute)
    result = _merge_results(
        [
            await _arun_single_spider(
                target, project_dir=project_dir, attributes=attributes, state=args.state
            )
            for target in targets
        ]
    )
    _write_output(result, args.output)
    return 0 if not result.errors else 1


def register(subparsers: argparse._SubParsersAction) -> None:
    crawl_parser = subparsers.add_parser("crawl")
    crawl_parser.add_argument("directory", nargs="?", default=".")
    crawl_parser.add_argument("--spider")
    crawl_parser.add_argument("-a", "--attribute", action="append")
    crawl_parser.add_argument("-o", "--output")
    crawl_parser.add_argument("--state")
    crawl_parser.add_argument("--async", dest="use_async", action="store_true")
    crawl_parser.add_argument("--css", action="append")
    crawl_parser.add_argument("--xpath", action="append")
    crawl_parser.add_argument("--smart", action="append")
    crawl_parser.add_argument("--item-css")
    crawl_parser.add_argument("--attr", action="append")
    crawl_parser.add_argument("--all", dest="all_fields", action="append")
    crawl_parser.add_argument("--follow-css", action="append")
    crawl_parser.add_argument("--follow-xpath", action="append")
    crawl_parser.add_argument("--follow-attr")
    crawl_parser.add_argument("--same-domain", action="store_true")
    crawl_parser.add_argument("--allowed-domain", action="append")
    crawl_parser.add_argument("--max-depth", type=int)
    crawl_parser.add_argument("--max-requests", type=int)
    crawl_parser.add_argument("--concurrency", type=int)
    crawl_parser.add_argument(
        "--dedupe", dest="dedupe", action="store_true", default=None
    )
    crawl_parser.add_argument("--no-dedupe", dest="dedupe", action="store_false")
    crawl_parser.add_argument(
        "--robots-txt", dest="robots_txt", action="store_true", default=None
    )
    crawl_parser.add_argument(
        "--no-robots-txt", dest="robots_txt", action="store_false"
    )
    crawl_parser.add_argument("--user-agent")
    add_request_args(crawl_parser)
    crawl_parser.set_defaults(func=crawl_command, async_func=acrawl_command)
