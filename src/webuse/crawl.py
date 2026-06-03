from __future__ import annotations

import asyncio
import inspect
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any
from urllib.parse import urlparse

from .client import AsyncClient, Client
from .models import CrawlRequest, CrawlResult, CrawlStats, FollowRule


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    normalized = parsed._replace(fragment="", path=path)
    return normalized.geturl()


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _same_domain(url: str, origin: str) -> bool:
    return _domain(url) == _domain(origin)


def _follow_candidates(response: Any, follow: Any) -> list[str]:
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


def _follow_allowed(url: str, request: CrawlRequest, rule: FollowRule | None, allowed_domains: set[str] | None, max_depth: int) -> bool:
    if request.depth + 1 > max_depth:
        return False
    if allowed_domains and _domain(url) not in allowed_domains:
        return False
    if rule:
        if rule.max_depth is not None and request.depth + 1 > rule.max_depth:
            return False
        if rule.same_domain and not _same_domain(url, request.url):
            return False
        if rule.allowed_domains and _domain(url) not in rule.allowed_domains:
            return False
        if rule.include and re.search(rule.include, url) is None:
            return False
        if rule.exclude and re.search(rule.exclude, url):
            return False
        if rule.predicate and not rule.predicate(url, request):
            return False
    return True


def _coerce_requests(seeds: str | list[str] | list[CrawlRequest]) -> list[CrawlRequest]:
    if isinstance(seeds, str):
        return [CrawlRequest(url=seeds)]
    items: list[CrawlRequest] = []
    for seed in seeds:
        if isinstance(seed, CrawlRequest):
            items.append(seed)
        else:
            items.append(CrawlRequest(url=str(seed)))
    return items


def _element_value(element: Any, attr: str | None) -> Any:
    if attr:
        return element.attr(attr)
    return element.text()


def _extract_by_selector(response: Any, rule: dict[str, Any], selector_type: str) -> Any:
    selector = rule[selector_type]
    attr = rule.get("attr")
    if rule.get("all"):
        matches = response.css(selector) if selector_type == "css" else response.xpath(selector)
        return [_element_value(match, attr) for match in matches]
    match = response.css_first(selector) if selector_type == "css" else response.xpath_first(selector)
    return _element_value(match, attr) if match else None


def _extract_by_smart(response: Any, rule: dict[str, Any]) -> Any:
    match = response.smart(rule["smart"], key=rule.get("key"))
    if not match:
        return None
    return _element_value(match, rule.get("attr"))


def _extract_items(response: Any, extract: Any) -> list[Any]:
    if extract is None:
        return []
    if isinstance(extract, dict):
        item: dict[str, Any] = {}
        for key, rule in extract.items():
            if isinstance(rule, str):
                match = response.css_first(rule)
                item[key] = match.text() if match else None
            elif isinstance(rule, dict):
                if "css" in rule:
                    item[key] = _extract_by_selector(response, rule, "css")
                elif "xpath" in rule:
                    item[key] = _extract_by_selector(response, rule, "xpath")
                elif "smart" in rule:
                    item[key] = _extract_by_smart(response, rule)
        return [item]
    return []


def _handle_callback_result(result: Any) -> tuple[list[Any], list[Any]]:
    items: list[Any] = []
    followups: list[Any] = []
    if result is None:
        return items, followups
    if isinstance(result, tuple) and len(result) == 2:
        raw_items, raw_followups = result
        items.extend(raw_items if isinstance(raw_items, list) else [raw_items])
        followups.extend(raw_followups if isinstance(raw_followups, list) else [raw_followups])
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


def crawl(
    seeds: str | list[str] | list[CrawlRequest],
    *,
    extract: Any = None,
    follow: Any = None,
    max_depth: int = 0,
    max_requests: int | None = None,
    concurrency: int = 10,
    dedupe: bool = True,
    allowed_domains: set[str] | None = None,
    client: Client | None = None,
    on_error: Any = None,
    request_defaults: dict[str, Any] | None = None,
) -> CrawlResult:
    queue = _coerce_requests(seeds)
    result = CrawlResult(stats=CrawlStats())
    owned_client = client is None
    client = client or Client(**(request_defaults or {}))
    seen: set[str] = set()

    def fetch(request: CrawlRequest):
        response = client.request(request.method, request.url, **request.options.to_request_kwargs())
        return request, response

    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            pending = {}
            while queue or pending:
                while queue and len(pending) < max(1, concurrency):
                    request = queue.pop(0)
                    normalized = _normalize_url(request.url)
                    if dedupe and normalized in seen:
                        result.stats.skipped_duplicates += 1
                        continue
                    seen.add(normalized)
                    request.url = normalized
                    result.visited.add(normalized)
                    result.stats.queued += 1
                    pending[executor.submit(fetch, request)] = request
                if not pending:
                    continue
                done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    request = pending.pop(future)
                    try:
                        request, response = future.result()
                    except Exception as exc:
                        result.stats.errors += 1
                        result.errors.append({"url": request.url, "error": str(exc)})
                        if on_error:
                            on_error(exc, request)
                        continue
                    result.stats.fetched += 1
                    result.pages.append(response)
                    extracted = _extract_items(response, extract)
                    result.items.extend(extracted)
                    result.stats.extracted_items += len(extracted)
                    if callable(extract):
                        extra_items, callback_followups = _handle_callback_result(extract(response))
                        result.items.extend(extra_items)
                        result.stats.extracted_items += len(extra_items)
                    else:
                        callback_followups = []
                    rules = follow if isinstance(follow, list) else [follow] if follow else []
                    discovered: list[tuple[Any, FollowRule | None]] = [(item, None) for item in callback_followups]
                    for rule in rules:
                        discovered.extend((candidate, rule if isinstance(rule, FollowRule) else None) for candidate in _follow_candidates(response, rule))
                    for candidate, matched_rule in discovered:
                        next_request = candidate if isinstance(candidate, CrawlRequest) else CrawlRequest(url=str(candidate))
                        next_request.depth = request.depth + 1 if next_request.depth == 0 else next_request.depth
                        next_request.parent_url = request.url
                        if not _follow_allowed(next_request.url, request, matched_rule, allowed_domains, max_depth):
                            result.stats.skipped_rules += 1
                            continue
                        queue.append(next_request)
                        result.stats.followed_links += 1
                        if max_requests is not None and result.stats.queued >= max_requests:
                            queue.clear()
                            break
    finally:
        if owned_client:
            client.close()
    return result


async def acrawl(
    seeds: str | list[str] | list[CrawlRequest],
    *,
    extract: Any = None,
    follow: Any = None,
    max_depth: int = 0,
    max_requests: int | None = None,
    concurrency: int = 10,
    dedupe: bool = True,
    allowed_domains: set[str] | None = None,
    client: AsyncClient | None = None,
    on_error: Any = None,
    request_defaults: dict[str, Any] | None = None,
) -> CrawlResult:
    result = CrawlResult(stats=CrawlStats())
    queue: asyncio.Queue[CrawlRequest | None] = asyncio.Queue()
    for seed in _coerce_requests(seeds):
        await queue.put(seed)
    seen: set[str] = set()
    owned_client = client is None
    client = client or AsyncClient(**(request_defaults or {}))
    follow_rules = follow if isinstance(follow, list) else [follow] if follow else []

    async def maybe_await(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    async def worker():
        while True:
            request = await queue.get()
            if request is None:
                queue.task_done()
                break
            normalized = _normalize_url(request.url)
            if dedupe and normalized in seen:
                result.stats.skipped_duplicates += 1
                queue.task_done()
                continue
            seen.add(normalized)
            request.url = normalized
            result.visited.add(normalized)
            result.stats.queued += 1
            try:
                response = await client.request(request.method, request.url, **request.options.to_request_kwargs())
                result.stats.fetched += 1
                result.pages.append(response)
                extracted = _extract_items(response, extract)
                result.items.extend(extracted)
                result.stats.extracted_items += len(extracted)
                callback_followups: list[Any] = []
                if callable(extract):
                    callback_result = await maybe_await(extract(response))
                    extra_items, callback_followups = _handle_callback_result(callback_result)
                    result.items.extend(extra_items)
                    result.stats.extracted_items += len(extra_items)
                discovered: list[tuple[Any, FollowRule | None]] = [(item, None) for item in callback_followups]
                for rule in follow_rules:
                    found = _follow_candidates(response, rule)
                    if len(found) == 1 and inspect.isawaitable(found[0]):
                        found = await maybe_await(found[0])
                    discovered.extend((candidate, rule if isinstance(rule, FollowRule) else None) for candidate in found)
                for candidate, matched_rule in discovered:
                    next_request = candidate if isinstance(candidate, CrawlRequest) else CrawlRequest(url=str(candidate))
                    next_request.depth = request.depth + 1 if next_request.depth == 0 else next_request.depth
                    next_request.parent_url = request.url
                    if not _follow_allowed(next_request.url, request, matched_rule, allowed_domains, max_depth):
                        result.stats.skipped_rules += 1
                        continue
                    if max_requests is not None and result.stats.queued >= max_requests:
                        break
                    await queue.put(next_request)
                    result.stats.followed_links += 1
            except Exception as exc:
                result.stats.errors += 1
                result.errors.append({"url": request.url, "error": str(exc)})
                if on_error:
                    await maybe_await(on_error(exc, request))
            finally:
                queue.task_done()

    try:
        workers = [asyncio.create_task(worker()) for _ in range(max(1, concurrency))]
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
    finally:
        if owned_client:
            await client.__aexit__(None, None, None)
    return result
