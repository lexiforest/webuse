from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any
from urllib.robotparser import RobotFileParser

from ..client import Client
from ..exceptions import CloseSpider, IgnoreRequest
from ..log import logger
from ..models import CrawlRequest, CrawlResult, CrawlStats, FollowRule
from ..signals import SignalBus
from .state import (
    DefaultRequestHasher,
    MemoryRequestQueue,
    MemoryRequestSeen,
    RequestHasher,
    RequestQueue,
    RequestSeen,
)
from .utils import (
    coerce_requests,
    extract_items,
    follow_allowed,
    follow_candidates,
    handle_callback_result,
    normalize_url,
    robots_allowed,
)


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
    robots_txt: bool = False,
    user_agent: str = "webuse",
    client: Client | None = None,
    on_error: Any = None,
    request_defaults: dict[str, Any] | None = None,
    request_queue: RequestQueue | None = None,
    request_seen: RequestSeen | None = None,
    request_hasher: RequestHasher | None = None,
    signals: SignalBus | None = None,
) -> CrawlResult:
    signal_bus = signals or SignalBus()
    scheduler_queue = request_queue or MemoryRequestQueue()
    result = CrawlResult(stats=CrawlStats())
    signal_bus.send("crawl_started", result=result)
    for seed in coerce_requests(seeds):
        scheduler_queue.put(seed)
        signal_bus.send("request_queued", request=seed, source="start")
    owned_client = client is None
    client = client or Client(**(request_defaults or {}))
    seen = request_seen or MemoryRequestSeen()
    hasher = request_hasher or DefaultRequestHasher()
    robots_cache: dict[str, RobotFileParser] = {}

    def fetch(request: CrawlRequest):
        response = client.request(
            request.method, request.url, **request.options.to_request_kwargs()
        )
        return request, response

    def close_spider(reason: str) -> None:
        result.close_reason = reason
        scheduler_queue.clear()
        for future in pending:
            future.cancel()
        pending.clear()

    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            pending = {}
            while not scheduler_queue.empty() or pending:
                while not scheduler_queue.empty() and len(pending) < max(
                    1, concurrency
                ):
                    request = scheduler_queue.pop()
                    if request is None:
                        break
                    request_hash = hasher.hash(request)
                    is_new = seen.add(request_hash)
                    if dedupe and not is_new:
                        result.stats.skipped_duplicates += 1
                        logger.info(
                            "crawl request skipped method={} url={} reason=duplicate",
                            request.method,
                            request.url,
                        )
                        signal_bus.send(
                            "request_skipped", request=request, reason="duplicate"
                        )
                        continue
                    normalized = normalize_url(request.url)
                    request.url = normalized
                    if not robots_allowed(
                        normalized,
                        enabled=robots_txt,
                        user_agent=user_agent,
                        client=client,
                        cache=robots_cache,
                    ):
                        result.stats.skipped_robots += 1
                        logger.info(
                            "crawl request skipped method={} url={} reason=robots",
                            request.method,
                            request.url,
                        )
                        signal_bus.send(
                            "request_skipped", request=request, reason="robots"
                        )
                        continue
                    result.visited.add(normalized)
                    result.stats.queued += 1
                    logger.info(
                        "crawl request started method={} url={} depth={}",
                        request.method,
                        request.url,
                        request.depth,
                    )
                    signal_bus.send("request_before_downloader", request=request)
                    pending[executor.submit(fetch, request)] = request
                if not pending:
                    continue
                done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    request = pending.pop(future)
                    try:
                        request, response = future.result()
                    except IgnoreRequest:
                        result.stats.skipped_ignored += 1
                        logger.info(
                            "crawl request skipped method={} url={} reason=ignored",
                            request.method,
                            request.url,
                        )
                        signal_bus.send(
                            "request_skipped", request=request, reason="ignored"
                        )
                        signal_bus.send(
                            "request_after_downloader", request=request, success=False
                        )
                        continue
                    except CloseSpider as exc:
                        logger.info(
                            "crawl request stopped method={} url={} reason={}",
                            request.method,
                            request.url,
                            exc.reason,
                        )
                        signal_bus.send(
                            "request_after_downloader", request=request, success=False
                        )
                        close_spider(exc.reason)
                        break
                    except Exception as exc:
                        result.stats.errors += 1
                        result.errors.append({"url": request.url, "error": str(exc)})
                        logger.warning(
                            "crawl request failed method={} url={} error={}",
                            request.method,
                            request.url,
                            exc,
                        )
                        signal_bus.send(
                            "request_after_downloader",
                            request=request,
                            success=False,
                            error=exc,
                        )
                        if on_error:
                            on_error(exc, request)
                        continue
                    result.stats.fetched += 1
                    logger.info(
                        "crawl request finished method={} url={} status={}",
                        request.method,
                        request.url,
                        getattr(response, "status_code", None),
                    )
                    signal_bus.send(
                        "request_after_downloader", request=request, success=True
                    )
                    response.request = request
                    result.pages.append(response)
                    signal_bus.send(
                        "response_received", response=response, request=request
                    )
                    try:
                        signal_bus.send(
                            "parse_started", response=response, request=request
                        )
                        extracted = extract_items(response, extract)
                        result.items.extend(extracted)
                        result.stats.extracted_items += len(extracted)
                        if callable(extract):
                            extra_items, callback_followups = handle_callback_result(
                                extract(response)
                            )
                            result.items.extend(extra_items)
                            result.stats.extracted_items += len(extra_items)
                        else:
                            extra_items = []
                            callback_followups = []
                        signal_bus.send(
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
                        signal_bus.send(
                            "request_skipped", request=request, reason="ignored"
                        )
                        continue
                    except CloseSpider as exc:
                        close_spider(exc.reason)
                        break
                    except Exception as exc:
                        signal_bus.send(
                            "parse_error", response=response, request=request, error=exc
                        )
                        raise
                    rules = (
                        follow
                        if isinstance(follow, list)
                        else [follow]
                        if follow
                        else []
                    )
                    discovered: list[tuple[Any, FollowRule | None]] = [
                        (item, None) for item in callback_followups
                    ]
                    for rule in rules:
                        discovered.extend(
                            (candidate, rule if isinstance(rule, FollowRule) else None)
                            for candidate in follow_candidates(response, rule)
                        )
                    for candidate, matched_rule in discovered:
                        next_request = (
                            candidate
                            if isinstance(candidate, CrawlRequest)
                            else CrawlRequest(url=str(candidate))
                        )
                        if (
                            matched_rule
                            and matched_rule.category
                            and not next_request.category
                        ):
                            next_request.category = matched_rule.category
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
                            signal_bus.send(
                                "request_skipped", request=next_request, reason="rules"
                            )
                            continue
                        scheduler_queue.put(next_request)
                        signal_bus.send(
                            "request_queued", request=next_request, source="follow"
                        )
                        result.stats.followed_links += 1
                        if (
                            max_requests is not None
                            and result.stats.queued >= max_requests
                        ):
                            scheduler_queue.clear()
                            break
            signal_bus.send("scheduler_empty", result=result)
    finally:
        if owned_client:
            client.close()
        signal_bus.send(
            "crawl_finished", result=result, reason=result.close_reason or "finished"
        )
    return result
