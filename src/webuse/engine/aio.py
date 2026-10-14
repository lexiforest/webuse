import asyncio
import inspect
from contextlib import aclosing
from typing import Any
from urllib.robotparser import RobotFileParser

from ..extract import aextract_response
from ..extract.schema import compile_extraction
from ..http import AsyncClient
from ..exceptions import CloseSpider, IgnoreRequest
from ..log import logger
from ..models import CrawlRequest, CrawlResult, CrawlStats, FollowRule
from ..signals import SignalBus
from .state import DefaultRequestHasher, RequestHasher
from .async_state import (
    AsyncRequestQueue,
    AsyncRequestSeen,
    AsyncMemoryRequestQueue,
    AsyncMemoryRequestSeen,
    async_state_info,
)
from .policy import (
    arobots_allowed,
    coerce_requests,
    coerce_follow_result,
    domain,
    follow_allowed,
    follow_candidates,
    normalize_url,
    prepare_followup,
)


async def acrawl(
    seeds: str | list[str] | list[CrawlRequest],
    *,
    extract: Any = None,
    follow: Any = None,
    max_depth: int = 0,
    max_requests: int | None = None,
    concurrency: int = 10,
    per_domain: int | None = None,
    dedupe: bool = True,
    allowed_domains: set[str] | None = None,
    robots_txt: bool = False,
    user_agent: str = "webuse",
    client: AsyncClient | None = None,
    on_error: Any = None,
    request_defaults: dict[str, Any] | None = None,
    request_queue: AsyncRequestQueue | None = None,
    request_seen: AsyncRequestSeen | None = None,
    request_hasher: RequestHasher | None = None,
    signals: SignalBus | None = None,
) -> CrawlResult:
    extract = compile_extraction(extract)
    if per_domain is not None and per_domain < 1:
        raise ValueError("per_domain must be positive")
    concurrency = max(1, concurrency)
    signal_bus = signals or SignalBus()
    result = CrawlResult(stats=CrawlStats())
    await signal_bus.asend("crawl_started", result=result)
    queue = request_queue if request_queue is not None else AsyncMemoryRequestQueue()
    seen = request_seen if request_seen is not None else AsyncMemoryRequestSeen()
    condition = asyncio.Condition()
    active = 0
    hasher = request_hasher or DefaultRequestHasher()
    owned_client = client is None
    if owned_client:
        client_options = dict(request_defaults or {})
        client_options.setdefault("max_clients", concurrency)
        client = AsyncClient(**client_options)
    follow_rules = follow if isinstance(follow, list) else [follow] if follow else []
    robots_cache: dict[str, RobotFileParser] = {}
    robots_locks: dict[str, asyncio.Lock] = {}
    domain_limits: dict[str, asyncio.Semaphore] = {}

    async def state_signal(name="state_updated"):
        await signal_bus.asend(name, **await async_state_info(queue, seen))

    async def fetch(request):
        async def download():
            if result.close_reason is not None:
                raise IgnoreRequest()
            return await client.request(
                request.method,
                request.url,
                **request.options.to_request_kwargs(),
            )

        if per_domain is None:
            return await download()
        limit = domain_limits.setdefault(
            domain(request.url), asyncio.Semaphore(per_domain)
        )
        async with limit:
            return await download()

    async def close_spider(reason: str) -> None:
        result.close_reason = reason
        await queue.clear()
        async with condition:
            condition.notify_all()

    async def acquire_request():
        nonlocal active
        async with condition:
            while result.close_reason is None:
                request = await queue.pop()
                if request is not None:
                    active += 1
                    return request
                # Active workers can still discover requests while awaiting I/O.
                if active == 0:
                    return None
                await condition.wait()
        return None

    async def maybe_await(value: Any) -> Any:
        return await value if inspect.isawaitable(value) else value

    async def worker():
        nonlocal active
        while True:
            request = await acquire_request()
            if request is None:
                return
            request_after_downloader = True
            try:
                request_hash = hasher.hash(request)
                is_new = await seen.add(request_hash)
                if dedupe and not is_new:
                    result.stats.skipped_duplicates += 1
                    logger.info(
                        "crawl request skipped method={} url={} reason=duplicate",
                        request.method,
                        request.url,
                    )
                    await signal_bus.asend(
                        "request_skipped", request=request, reason="duplicate"
                    )
                    continue
                await state_signal()
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
                    continue
                # Check after robots awaits so concurrent workers share one budget.
                if max_requests is not None and result.stats.queued >= max_requests:
                    continue
                result.visited.add(normalized)
                result.stats.queued += 1
                request_after_downloader = False
                logger.info(
                    "crawl request started method={} url={} depth={}",
                    request.method,
                    request.url,
                    request.depth,
                )
                await signal_bus.asend("request_before_downloader", request=request)
                response = await fetch(request)
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
                response.crawl_request = request
                result.pages.append(response)
                await signal_bus.asend(
                    "response_received", response=response, request=request
                )
                try:
                    await signal_bus.asend(
                        "parse_started", response=response, request=request
                    )
                    parsed = await aextract_response(response, extract)
                    page_items = []
                    async with aclosing(parsed.items) as items:
                        async for item in items:
                            result.items.append(item)
                            page_items.append(item)
                    callback_followups = parsed.requests
                    await signal_bus.asend(
                        "parse_finished",
                        response=response,
                        request=request,
                        items=page_items,
                        followups=callback_followups,
                    )
                except IgnoreRequest:
                    await signal_bus.asend(
                        "parse_finished",
                        response=response,
                        request=request,
                        items=[],
                        followups=[],
                    )
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
                    await signal_bus.asend(
                        "parse_finished",
                        response=response,
                        request=request,
                        items=[],
                        followups=[],
                    )
                    await close_spider(exc.reason)
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
                        found = coerce_follow_result(await found[0])
                    discovered.extend(
                        (candidate, rule if isinstance(rule, FollowRule) else None)
                        for candidate in found
                    )
                for candidate, matched_rule in discovered:
                    next_request = prepare_followup(candidate, request, matched_rule)
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
                    async with condition:
                        condition.notify_all()
                    await state_signal()
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
                await close_spider(exc.reason)
            except Exception as exc:
                # Parsing, pipelines, follow callbacks and signal failures are
                # programming/configuration errors, just as in sync crawl.
                if request_after_downloader:
                    raise
                result.errors.append({"url": request.url, "error": str(exc)})
                await signal_bus.asend("request_error", request=request, error=exc)
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
                async with condition:
                    active -= 1
                    condition.notify_all()

    workers = []
    try:
        await state_signal("state_loaded")
        for seed in coerce_requests(seeds):
            await queue.put(seed)
            await signal_bus.asend("request_queued", request=seed, source="start")
            await state_signal()
        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await asyncio.gather(*workers)
        await state_signal()
        await signal_bus.asend("scheduler_empty", result=result)
    except Exception as exc:
        result.close_reason = "error"
        await signal_bus.asend("crawl_error", result=result, error=exc)
        raise
    except asyncio.CancelledError:
        result.close_reason = "cancelled"
        raise
    finally:
        tasks = workers
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if owned_client:
            await client.__aexit__(None, None, None)
        await signal_bus.asend(
            "crawl_finished", result=result, reason=result.close_reason or "finished"
        )
    return result
