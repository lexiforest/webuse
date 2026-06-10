import asyncio
import inspect
from typing import Any
from urllib.robotparser import RobotFileParser

from ..client import AsyncClient
from ..exceptions import CloseSpider, IgnoreRequest
from ..log import logger
from ..models import CrawlRequest, CrawlResult, CrawlStats, FollowRule
from ..signals import SignalBus
from .state import DefaultRequestHasher, RequestHasher
from .utils import (
    arobots_allowed,
    coerce_requests,
    extract_items,
    follow_allowed,
    follow_candidates,
    handle_callback_result,
    normalize_url,
)


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
    robots_txt: bool = False,
    user_agent: str = "webuse",
    client: AsyncClient | None = None,
    on_error: Any = None,
    request_defaults: dict[str, Any] | None = None,
    request_hasher: RequestHasher | None = None,
    signals: SignalBus | None = None,
) -> CrawlResult:
    signal_bus = signals or SignalBus()
    result = CrawlResult(stats=CrawlStats())
    await signal_bus.asend("crawl_started", result=result)
    queue: asyncio.Queue[CrawlRequest | None] = asyncio.Queue()
    for seed in coerce_requests(seeds):
        await queue.put(seed)
        await signal_bus.asend("request_queued", request=seed, source="start")
    seen: set[str] = set()
    hasher = request_hasher or DefaultRequestHasher()
    owned_client = client is None
    client = client or AsyncClient(**(request_defaults or {}))
    follow_rules = follow if isinstance(follow, list) else [follow] if follow else []
    robots_cache: dict[str, RobotFileParser] = {}
    robots_locks: dict[str, asyncio.Lock] = {}

    def close_spider(reason: str) -> None:
        result.close_reason = reason
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def maybe_await(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    async def worker():
        while True:
            request = await queue.get()
            if request is None:
                queue.task_done()
                break
            if result.close_reason is not None:
                queue.task_done()
                continue
            request_hash = hasher.hash(request)
            if dedupe and request_hash in seen:
                result.stats.skipped_duplicates += 1
                logger.info(
                    "crawl request skipped method={} url={} reason=duplicate",
                    request.method,
                    request.url,
                )
                await signal_bus.asend(
                    "request_skipped", request=request, reason="duplicate"
                )
                queue.task_done()
                continue
            seen.add(request_hash)
            normalized = normalize_url(request.url)
            request.url = normalized
            if not await arobots_allowed(
                normalized,
                enabled=robots_txt,
                user_agent=user_agent,
                client=client,
                cache=robots_cache,
                locks=robots_locks,
            ):
                result.stats.skipped_robots += 1
                logger.info(
                    "crawl request skipped method={} url={} reason=robots",
                    request.method,
                    request.url,
                )
                await signal_bus.asend(
                    "request_skipped", request=request, reason="robots"
                )
                queue.task_done()
                continue
            result.visited.add(normalized)
            result.stats.queued += 1
            request_after_downloader = False
            try:
                logger.info(
                    "crawl request started method={} url={} depth={}",
                    request.method,
                    request.url,
                    request.depth,
                )
                await signal_bus.asend("request_before_downloader", request=request)
                response = await client.request(
                    request.method, request.url, **request.options.to_request_kwargs()
                )
                logger.info(
                    "crawl request finished method={} url={} status={}",
                    request.method,
                    request.url,
                    getattr(response, "status_code", None),
                )
                await signal_bus.asend(
                    "request_after_downloader", request=request, success=True
                )
                request_after_downloader = True
                result.stats.fetched += 1
                response.request = request
                result.pages.append(response)
                await signal_bus.asend(
                    "response_received", response=response, request=request
                )
                try:
                    await signal_bus.asend(
                        "parse_started", response=response, request=request
                    )
                    extracted = extract_items(response, extract)
                    result.items.extend(extracted)
                    result.stats.extracted_items += len(extracted)
                    callback_followups: list[Any] = []
                    extra_items: list[Any] = []
                    if callable(extract):
                        callback_result = await maybe_await(extract(response))
                        extra_items, callback_followups = handle_callback_result(
                            callback_result
                        )
                        result.items.extend(extra_items)
                        result.stats.extracted_items += len(extra_items)
                    await signal_bus.asend(
                        "parse_finished",
                        response=response,
                        request=request,
                        items=[*extracted, *extra_items],
                        followups=callback_followups,
                    )
                except IgnoreRequest:
                    result.stats.skipped_ignored += 1
                    logger.info(
                        "crawl request skipped method={} url={} reason=ignored",
                        request.method,
                        request.url,
                    )
                    await signal_bus.asend(
                        "request_skipped", request=request, reason="ignored"
                    )
                    continue
                except CloseSpider as exc:
                    close_spider(exc.reason)
                    continue
                except Exception as exc:
                    await signal_bus.asend(
                        "parse_error", response=response, request=request, error=exc
                    )
                    raise
                discovered: list[tuple[Any, FollowRule | None]] = [
                    (item, None) for item in callback_followups
                ]
                for rule in follow_rules:
                    found = follow_candidates(response, rule)
                    if len(found) == 1 and inspect.isawaitable(found[0]):
                        found = await maybe_await(found[0])
                    discovered.extend(
                        (candidate, rule if isinstance(rule, FollowRule) else None)
                        for candidate in found
                    )
                for candidate, matched_rule in discovered:
                    next_request = (
                        candidate
                        if isinstance(candidate, CrawlRequest)
                        else CrawlRequest(url=str(candidate))
                    )
                    next_request.depth = (
                        request.depth + 1
                        if next_request.depth == 0
                        else next_request.depth
                    )
                    next_request.parent_url = request.url
                    if not follow_allowed(
                        next_request.url,
                        request,
                        matched_rule,
                        allowed_domains,
                        max_depth,
                    ):
                        result.stats.skipped_rules += 1
                        logger.info(
                            "crawl request skipped method={} url={} reason=rules",
                            next_request.method,
                            next_request.url,
                        )
                        await signal_bus.asend(
                            "request_skipped", request=next_request, reason="rules"
                        )
                        continue
                    if max_requests is not None and result.stats.queued >= max_requests:
                        break
                    if result.close_reason is not None:
                        break
                    await queue.put(next_request)
                    await signal_bus.asend(
                        "request_queued", request=next_request, source="follow"
                    )
                    result.stats.followed_links += 1
            except IgnoreRequest:
                result.stats.skipped_ignored += 1
                logger.info(
                    "crawl request skipped method={} url={} reason=ignored",
                    request.method,
                    request.url,
                )
                await signal_bus.asend(
                    "request_skipped", request=request, reason="ignored"
                )
                if not request_after_downloader:
                    await signal_bus.asend(
                        "request_after_downloader", request=request, success=False
                    )
            except CloseSpider as exc:
                logger.info(
                    "crawl request stopped method={} url={} reason={}",
                    request.method,
                    request.url,
                    exc.reason,
                )
                if not request_after_downloader:
                    await signal_bus.asend(
                        "request_after_downloader", request=request, success=False
                    )
                close_spider(exc.reason)
            except Exception as exc:
                result.stats.errors += 1
                result.errors.append({"url": request.url, "error": str(exc)})
                logger.warning(
                    "crawl request failed method={} url={} error={}",
                    request.method,
                    request.url,
                    exc,
                )
                if not request_after_downloader:
                    await signal_bus.asend(
                        "request_after_downloader",
                        request=request,
                        success=False,
                        error=exc,
                    )
                if on_error:
                    await maybe_await(on_error(exc, request))
            finally:
                queue.task_done()

    try:
        workers = [asyncio.create_task(worker()) for _ in range(max(1, concurrency))]
        await queue.join()
        await signal_bus.asend("scheduler_empty", result=result)
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
    finally:
        if owned_client:
            await client.__aexit__(None, None, None)
        await signal_bus.asend(
            "crawl_finished", result=result, reason=result.close_reason or "finished"
        )
    return result
