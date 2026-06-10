import asyncio
import inspect
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from pydantic import BaseModel

from ..exceptions import ConfigError
from ..models import CrawlRequest, FollowRule


UNSET = object()


def load_config_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    if config_path.suffix == ".toml":
        import tomllib

        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    if config_path.suffix in {".yaml", ".yml"}:
        import yaml

        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raise ConfigError(f"Unsupported config format: {config_path.suffix}")


def allowed_domains(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return set(value) or None


def follow_rule_from_config(value: Any, *, same_domain: bool = False) -> FollowRule:
    if isinstance(value, FollowRule):
        return value
    if isinstance(value, str):
        return FollowRule(css=value, same_domain=same_domain)
    if not isinstance(value, dict):
        raise ConfigError(f"Unsupported follow rule: {value!r}")
    return FollowRule(
        css=value.get("css"),
        xpath=value.get("xpath"),
        attr=value.get("attr", "href"),
        include=value.get("include"),
        exclude=value.get("exclude"),
        same_domain=value.get("same_domain", same_domain),
        allowed_domains=allowed_domains(value.get("allowed_domains")),
        max_depth=value.get("max_depth"),
    )


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    normalized = parsed._replace(fragment="", path=path)
    return normalized.geturl()


def domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def origin(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def robots_url(url: str) -> str | None:
    url_origin = origin(url)
    return f"{url_origin}/robots.txt" if url_origin else None


def robots_parser_from_response(
    robots_url_value: str, response: Any | None
) -> RobotFileParser:
    parser = RobotFileParser(robots_url_value)
    if response is None:
        parser.parse([])
        return parser
    status_code = getattr(response, "status_code", 0)
    if status_code in {401, 403}:
        parser.disallow_all = True
    elif 400 <= status_code < 500:
        parser.allow_all = True
    else:
        parser.parse(response.text.splitlines())
    return parser


def robots_allowed(
    url: str,
    *,
    enabled: bool,
    user_agent: str,
    client: Any,
    cache: dict[str, RobotFileParser],
) -> bool:
    robots_url_value = robots_url(url)
    if not enabled or robots_url_value is None:
        return True
    parser = cache.get(robots_url_value)
    if parser is None:
        try:
            response = client.request("GET", robots_url_value)
        except Exception:
            response = None
        parser = robots_parser_from_response(robots_url_value, response)
        cache[robots_url_value] = parser
    return parser.can_fetch(user_agent, url)


async def arobots_allowed(
    url: str,
    *,
    enabled: bool,
    user_agent: str,
    client: Any,
    cache: dict[str, RobotFileParser],
    locks: dict[str, asyncio.Lock],
) -> bool:
    robots_url_value = robots_url(url)
    if not enabled or robots_url_value is None:
        return True
    parser = cache.get(robots_url_value)
    if parser is None:
        lock = locks.setdefault(robots_url_value, asyncio.Lock())
        async with lock:
            parser = cache.get(robots_url_value)
            if parser is None:
                try:
                    response = await client.request("GET", robots_url_value)
                except Exception:
                    response = None
                parser = robots_parser_from_response(robots_url_value, response)
                cache[robots_url_value] = parser
    return parser.can_fetch(user_agent, url)


def same_domain(url: str, origin_url: str) -> bool:
    return domain(url) == domain(origin_url)


def follow_candidates(response: Any, follow: Any) -> list[str]:
    if follow is None:
        return []
    if callable(follow):
        value = follow(response)
        if inspect.isawaitable(value):
            return [value]
        if value is None:
            return []
        if isinstance(value, (str, CrawlRequest)):
            return [value]
        return list(value)
    rules = follow if isinstance(follow, list) else [follow]
    candidates: list[str] = []
    for rule in rules:
        if isinstance(rule, str):
            candidates.extend(response.links(rule))
        elif isinstance(rule, FollowRule):
            if rule.css:
                for element in response.css(rule.css):
                    value = element.attr(rule.attr)
                    if value:
                        candidates.append(value)
            elif rule.xpath:
                for element in response.xpath(rule.xpath):
                    value = element.attr(rule.attr)
                    if value:
                        candidates.append(value)
    return candidates


def follow_allowed(
    url: str,
    request: CrawlRequest,
    rule: FollowRule | None,
    allowed_domains: set[str] | None,
    max_depth: int,
) -> bool:
    if request.depth + 1 > max_depth:
        return False
    if allowed_domains and domain(url) not in allowed_domains:
        return False
    if rule:
        if rule.max_depth is not None and request.depth + 1 > rule.max_depth:
            return False
        if rule.same_domain and not same_domain(url, request.url):
            return False
        if rule.allowed_domains and domain(url) not in rule.allowed_domains:
            return False
        if rule.include and re.search(rule.include, url) is None:
            return False
        if rule.exclude and re.search(rule.exclude, url):
            return False
        if rule.predicate and not rule.predicate(url, request):
            return False
    return True


def coerce_requests(seeds: str | list[str] | list[CrawlRequest]) -> list[CrawlRequest]:
    if isinstance(seeds, str):
        return [CrawlRequest(url=seeds)]
    items: list[CrawlRequest] = []
    for seed in seeds:
        if isinstance(seed, CrawlRequest):
            items.append(seed)
        else:
            items.append(CrawlRequest(url=str(seed)))
    return items


def coerce_domains(domains: Any) -> set[str] | None:
    if domains is None:
        return None
    if isinstance(domains, str):
        return {domains}
    return set(domains) or None


def element_value(element: Any, attr: str | None) -> Any:
    if attr:
        return element.attr(attr)
    return element.text()


def extract_by_selector(scope: Any, rule: dict[str, Any], selector_type: str) -> Any:
    selector = rule[selector_type]
    attr = rule.get("attr")
    if rule.get("all"):
        matches = (
            scope.css(selector) if selector_type == "css" else scope.xpath(selector)
        )
        return [element_value(match, attr) for match in matches]
    match = (
        scope.css_first(selector)
        if selector_type == "css"
        else scope.xpath_first(selector)
    )
    return element_value(match, attr) if match else None


def extract_by_smart(scope: Any, rule: dict[str, Any]) -> Any:
    smart_first = getattr(scope, "smart_first", None)
    if smart_first is None:
        return None
    match = smart_first(rule["smart"], key=rule.get("key"), translate_xpath=True)
    if not match:
        return None
    return element_value(match, rule.get("attr"))


def extract_item(scope: Any, fields: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key, rule in fields.items():
        if isinstance(rule, str):
            match = scope.css_first(rule)
            item[key] = match.text() if match else None
        elif isinstance(rule, dict):
            if "css" in rule:
                item[key] = extract_by_selector(scope, rule, "css")
            elif "xpath" in rule:
                item[key] = extract_by_selector(scope, rule, "xpath")
            elif "smart" in rule:
                item[key] = extract_by_smart(scope, rule)
    return item


def extraction_scopes(response: Any, extract: dict[str, Any]) -> list[Any]:
    item_css = extract.get("item_css")
    item_xpath = extract.get("item_xpath")
    if item_css and item_xpath:
        raise ConfigError("extract cannot define both item_css and item_xpath")
    if item_css:
        return response.css(item_css)
    if item_xpath:
        return response.xpath(item_xpath)
    return [response]


def extraction_fields(extract: dict[str, Any]) -> dict[str, Any]:
    if "fields" in extract:
        fields = extract["fields"]
        if not isinstance(fields, dict):
            raise ConfigError("extract.fields must be a mapping")
        return fields
    return {
        key: value
        for key, value in extract.items()
        if key not in {"item_css", "item_xpath"}
    }


def extract_items(response: Any, extract: Any) -> list[Any]:
    if extract is None:
        return []
    if isinstance(extract, dict):
        fields = extraction_fields(extract)
        if not fields:
            return []
        return [
            extract_item(scope, fields)
            for scope in extraction_scopes(response, extract)
        ]
    return []


def handle_callback_result(result: Any) -> tuple[list[Any], list[Any]]:
    items: list[Any] = []
    followups: list[Any] = []
    if result is None:
        return items, followups
    if isinstance(result, tuple) and len(result) == 2:
        raw_items, raw_followups = result
        items.extend(raw_items if isinstance(raw_items, list) else [raw_items])
        followups.extend(
            raw_followups if isinstance(raw_followups, list) else [raw_followups]
        )
        return items, followups
    if not isinstance(
        result, (str, bytes, dict, BaseModel, CrawlRequest)
    ) and isinstance(result, Iterable):
        for entry in result:
            if isinstance(entry, CrawlRequest) or isinstance(entry, str):
                followups.append(entry)
            else:
                items.append(entry)
        return items, followups
    if isinstance(result, list):
        for entry in result:
            if isinstance(entry, CrawlRequest) or isinstance(entry, str):
                followups.append(entry)
            else:
                items.append(entry)
        return items, followups
    if isinstance(result, CrawlRequest) or isinstance(result, str):
        followups.append(result)
    else:
        items.append(result)
    return items, followups
