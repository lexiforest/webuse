"""Request discovery and execution policy shared by both engines."""

import asyncio
import inspect
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from ..models import CrawlRequest, FollowRule


@dataclass(frozen=True)
class PagePattern:
    page_type: str
    include: tuple[re.Pattern, ...]
    exclude: tuple[re.Pattern, ...]

    def matches(self, url: str) -> bool:
        return bool(self.include) and self.allows(url)

    def allows(self, url: str) -> bool:
        return (
            not self.include or any(pattern.search(url) for pattern in self.include)
        ) and not any(pattern.search(url) for pattern in self.exclude)


def classify_request(request: CrawlRequest, patterns: list[PagePattern]) -> bool:
    """Assign an unset page type, or validate the explicitly assigned type."""
    if request.page_type:
        return all(
            pattern.allows(request.url)
            for pattern in patterns
            if pattern.page_type == request.page_type
        )
    for pattern in patterns:
        if pattern.matches(request.url):
            request.page_type = pattern.page_type
            break
    return True


def coerce_domains(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {value}
    return set(value) or None


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


def request_page_type(request: Any) -> str:
    page_type = getattr(request, "page_type", None)
    return str(page_type) if page_type else "default"


def page_type_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def follow_rule_applies(response: Any, rule: FollowRule) -> bool:
    allowed = page_type_values(rule.source_page_type)
    if not allowed or "*" in allowed:
        return True
    return request_page_type(getattr(response, "crawl_request", None)) in allowed


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
            for element in rule.select(response):
                value = element.attr(rule.attr)
                if value:
                    candidates.append(value)
    return candidates


async def afollow_candidates(response: Any, follow: Any) -> list[Any]:
    if isinstance(follow, FollowRule):
        if not follow_rule_applies(response, follow):
            return []
        elements = await follow.aselect(response)
        return [value for element in elements if (value := element.attr(follow.attr))]
    found = follow_candidates(response, follow)
    if len(found) == 1 and inspect.isawaitable(found[0]):
        return coerce_follow_result(await found[0])
    return found


def prepare_followup(
    candidate: Any, request: CrawlRequest, rule: FollowRule | None
) -> CrawlRequest:
    followup = (
        candidate
        if isinstance(candidate, CrawlRequest)
        else CrawlRequest(url=str(candidate))
    )
    followup.url = urljoin(request.url, followup.url)
    if rule and rule.page_type and not followup.page_type:
        followup.page_type = rule.page_type
    if followup.depth == 0:
        followup.depth = request.depth + 1
    followup.parent_url = request.url
    return followup


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
