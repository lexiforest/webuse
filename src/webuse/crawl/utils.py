import asyncio
import inspect
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from pydantic import BaseModel

from ..exceptions import ConfigError
from ..config import load_config_file as load_config_file
from ..models import CrawlRequest, CrawlResult, FollowRule
from ..parser import Document, Element


UNSET = object()


def coerce_domains(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return set(value) or None


allowed_domains = coerce_domains


def follow_rule_from_config(value: Any, *, same_domain: bool = False) -> FollowRule:
    if isinstance(value, FollowRule):
        return value
    if isinstance(value, str):
        return FollowRule(css=value, same_domain=same_domain)
    if not isinstance(value, dict):
        raise ConfigError(f"Unsupported follow rule: {value!r}")
    if "xpath" in value:
        raise ConfigError("XPath is no longer supported; use a CSS follow rule")
    return FollowRule(
        css=value.get("css"),
        attr=value.get("attr", "href"),
        category=value.get("category"),
        include=value.get("include"),
        exclude=value.get("exclude"),
        same_domain=value.get("same_domain", same_domain),
        allowed_domains=allowed_domains(value.get("allowed_domains")),
        max_depth=value.get("max_depth"),
    )


def compile_pages_config(
    pages: Any, *, same_domain: bool = False
) -> tuple[list[FollowRule] | None, dict[str, Any] | None]:
    if pages is None:
        return None, None
    if not isinstance(pages, dict):
        raise ConfigError("pages must be a mapping")
    follow: list[FollowRule] = []
    extract: dict[str, Any] = {}
    for category, page in pages.items():
        category_name = str(category)
        if not isinstance(page, dict):
            raise ConfigError(f"pages.{category_name} must be a mapping")
        page_follow = page.get("follow")
        if page_follow is not None:
            rules = page_follow if isinstance(page_follow, list) else [page_follow]
            for rule in rules:
                if isinstance(rule, dict) and (
                    {"source_category", "from_category", "from", "on"} & set(rule)
                ):
                    raise ConfigError(
                        f"pages.{category_name}.follow source category is implied by the page key"
                    )
                parsed = follow_rule_from_config(rule, same_domain=same_domain)
                parsed.source_category = category_name
                follow.append(parsed)
        if "extract" in page:
            page_extract = page["extract"]
            if not isinstance(page_extract, dict):
                raise ConfigError(f"pages.{category_name}.extract must be a mapping")
            extract[category_name] = page_extract
    return follow or None, extract or None


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


def request_category(request: Any) -> str:
    category = getattr(request, "category", None)
    return str(category) if category else "default"


def category_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def follow_rule_applies(response: Any, rule: FollowRule) -> bool:
    allowed = category_values(rule.source_category)
    if not allowed or "*" in allowed:
        return True
    return request_category(getattr(response, "crawl_request", None)) in allowed


def coerce_follow_result(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, CrawlRequest)) or inspect.isawaitable(value):
        return [value]
    return list(value)


def follow_candidates(response: Any, follow: Any) -> list[Any]:
    if follow is None:
        return []
    if callable(follow):
        return coerce_follow_result(follow(response))
    rules = follow if isinstance(follow, list) else [follow]
    candidates: list[str] = []
    for rule in rules:
        if isinstance(rule, str):
            candidates.extend(response.links(rule))
        elif isinstance(rule, FollowRule):
            if not follow_rule_applies(response, rule):
                continue
            if rule.css:
                for element in response.css(rule.css):
                    value = element.attr(rule.attr)
                    if value:
                        candidates.append(value)
    return candidates


def prepare_followup(
    candidate: Any, request: CrawlRequest, rule: FollowRule | None
) -> CrawlRequest:
    followup = (
        candidate
        if isinstance(candidate, CrawlRequest)
        else CrawlRequest(url=str(candidate))
    )
    followup.url = urljoin(request.url, followup.url)
    if rule and rule.category and not followup.category:
        followup.category = rule.category
    if followup.depth == 0:
        followup.depth = request.depth + 1
    followup.parent_url = request.url
    return followup


def record_extraction(result: CrawlResult, items: list[Any]) -> None:
    result.items.extend(items)
    result.stats.extracted_items += len(items)


def record_error(result: CrawlResult, request: CrawlRequest, error: Exception) -> None:
    result.stats.errors += 1
    result.errors.append({"url": request.url, "error": str(error)})


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


def element_value(element: Any, attr: str | None) -> Any:
    if attr:
        return element.attr(attr)
    return element.text()


def extract_by_selector(scope: Any, rule: dict[str, Any]) -> Any:
    selector = rule["css"]
    attr = rule.get("attr")
    if selector in {".", "&"}:
        if rule.get("all"):
            return [element_value(scope, attr)]
        return element_value(scope, attr)
    if rule.get("all"):
        matches = scope.css(selector)
        return [element_value(match, attr) for match in matches]
    match = scope.css_first(selector)
    return element_value(match, attr) if match else None


def extraction_document(scope: Any) -> Document:
    if isinstance(scope, Element):
        return Document(scope.html(), url=scope.base_url)
    return scope


def extract_by_find_element(scope: Any, rule: dict[str, Any]) -> Any:
    match = extraction_document(scope).find_element(
        rule["find_element"], key=rule.get("key")
    )
    return element_value(match, rule.get("attr"))


def extract_by_smart(scope: Any, rule: dict[str, Any]) -> Any:
    if "attr" in rule or "key" in rule:
        raise ConfigError(
            "smart extracts values; use find_element for attr or selector keys"
        )
    document = extraction_document(scope)
    extractor = document.smart if rule.get("all") else document.smart_first
    return extractor(rule["smart"])


def extract_item(scope: Any, fields: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for key, rule in fields.items():
        if isinstance(rule, str):
            match = scope if rule in {".", "&"} else scope.css_first(rule)
            item[key] = match.text() if match else None
        elif isinstance(rule, dict):
            if "xpath" in rule:
                raise ConfigError("XPath is no longer supported; use CSS extraction")
            if "css" in rule:
                item[key] = extract_by_selector(scope, rule)
            elif "smart" in rule:
                item[key] = extract_by_smart(scope, rule)
            elif "find_element" in rule:
                item[key] = extract_by_find_element(scope, rule)
    return item


def extraction_scopes(response: Any, extract: dict[str, Any]) -> list[Any]:
    item_css = extract.get("item_css")
    if "item_xpath" in extract:
        raise ConfigError("item_xpath is no longer supported; use item_css")
    if item_css:
        return response.css(item_css)
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
        if key not in {"item_css", "item_xpath", "type", "item_type", "item_model"}
    }


def looks_like_field_rule(value: Any) -> bool:
    if isinstance(value, str):
        return True
    if not isinstance(value, dict):
        return False
    if "xpath" in value:
        raise ConfigError("XPath is no longer supported; use CSS extraction")
    return any(key in value for key in ("css", "smart", "find_element"))


def looks_like_field_mapping(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(looks_like_field_rule(rule) for rule in value.values())
    )


def looks_like_extract_spec(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if "item_xpath" in value:
        raise ConfigError("item_xpath is no longer supported; use item_css")
    return any(
        key in value for key in ("fields", "item_css")
    ) or looks_like_field_mapping(value)


def extract_spec_items(
    response: Any, name: str | None, spec: dict[str, Any]
) -> list[Any]:
    fields = extraction_fields(spec)
    if not fields:
        return []
    items = [extract_item(scope, fields) for scope in extraction_scopes(response, spec)]
    if name is None:
        return items
    item_type = spec.get("type") or spec.get("item_type") or name
    item_model = spec.get("item_model")
    for item in items:
        item.setdefault("_type", item_type)
        if item_model is not None:
            item.setdefault("_item_model", item_model)
    return items


def extract_specs_for_response(
    response: Any, extract: dict[str, Any]
) -> list[tuple[str | None, dict[str, Any]]]:
    if looks_like_extract_spec(extract):
        return [(None, extract)]

    request = getattr(response, "crawl_request", None)
    category = getattr(request, "category", None)
    category_key = str(category) if category else "default"
    selected = extract.get(category_key)
    if selected is None:
        selected = extract.get("*")
    if selected is None:
        return []

    if not isinstance(selected, dict):
        raise ConfigError(f"extract rule for category {category!r} must be a mapping")
    reserved = {"fields", "item_css", "item_xpath", "type", "item_type", "item_model"}
    used_reserved = reserved & set(selected)
    if used_reserved:
        keys = ", ".join(sorted(used_reserved))
        raise ConfigError(
            f"extract rule for category {category!r} must be keyed by item type; "
            f"move {keys} under an item name"
        )

    specs: list[tuple[str | None, dict[str, Any]]] = []
    for name, spec in selected.items():
        if not looks_like_extract_spec(spec):
            raise ConfigError(f"extract item rule {name!r} must be a mapping")
        specs.append((str(name), spec))
    return specs


def extract_handles_category(extract: Any, category: str | None) -> bool:
    if extract is None or not isinstance(extract, dict):
        return False
    if looks_like_extract_spec(extract):
        return True
    category_key = str(category) if category else "default"
    return category_key in extract or "*" in extract


def extract_items(response: Any, extract: Any) -> list[Any]:
    if extract is None:
        return []
    if isinstance(extract, dict):
        items: list[Any] = []
        for name, spec in extract_specs_for_response(response, extract):
            items.extend(extract_spec_items(response, name, spec))
        return items
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
    if isinstance(result, CrawlRequest) or isinstance(result, str):
        followups.append(result)
    else:
        items.append(result)
    return items, followups
