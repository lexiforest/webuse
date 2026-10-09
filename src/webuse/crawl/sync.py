from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any
from threading import BoundedSemaphore
from contextlib import nullcontext
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
    state_info,
)
from .utils import (
    coerce_requests,
    domain,
    extract_items,
    follow_allowed,
    follow_candidates,
    handle_callback_result,
    normalize_url,
    robots_allowed,
    prepare_followup,
    record_extraction,
    record_error,
)


def crawl(
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
    client: Client | None = None,
    on_error: Any = None,
    request_defaults: dict[str, Any] | None = None,
    request_queue: RequestQueue | None = None,
    request_seen: RequestSeen | None = None,
    request_hasher: RequestHasher | None = None,
    signals: SignalBus | None = None,
) -> CrawlResult:
    signal_bus = signals or SignalBus()
    if per_domain is not None and per_domain < 1:
        raise ValueError("per_domain must be positive")
    scheduler_queue = (
        request_queue if request_queue is not None else MemoryRequestQueue()
    )
    result = CrawlResult(stats=CrawlStats())
    signal_bus.send("crawl_started", result=result)
    owned_client = client is None
    client = client or Client(**(request_defaults or {}))
    seen = request_seen if request_seen is not None else MemoryRequestSeen()
    hasher = request_hasher or DefaultRequestHasher()
    robots_cache: dict[str, RobotFileParser] = {}
    domain_limits: dict[str, BoundedSemaphore] = {}

    def state_updated() -> None:
        signal_bus.send("state_updated", **state_info(scheduler_queue, seen))

    def fetch(request: CrawlRequest):
        limit = (
            domain_limits.setdefault(domain(request.url), BoundedSemaphore(per_domain))
            if per_domain
            else nullcontext()
        )
        with limit:
            if result.close_reason is not None:
                raise IgnoreRequest()
            response = client.request(
                request.method,
                request.url,
                **request.options.to_request_kwargs(),
            )
        return request, response

    def close_spider(reason: str) -> None:
        result.close_reason = reason
        scheduler_queue.clear()
        state_updated()
        for future in pending:
            future.cancel()
        pending.clear()

    try:
        signal_bus.send("state_loaded", **state_info(scheduler_queue, seen))
        for seed in coerce_requests(seeds):
            scheduler_queue.put(seed)
            signal_bus.send("request_queued", request=seed, source="start")
            state_updated()
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            pending = {}
            while not scheduler_queue.empty() or pending:
                while not scheduler_queue.empty() and len(pending) < max(
                    1, concurrency
                ):
                    if max_requests is not None and result.stats.queued >= max_requests:
                        scheduler_queue.clear()
                        state_updated()
                        break
                    request = scheduler_queue.pop()
                    if request is None:
                        break
                    request_hash = hasher.hash(request)
                    is_new = seen.add(request_hash)
                    state_updated()
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
                        record_error(result, request, exc)
                        signal_bus.send("request_error", request=request, error=exc)
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
                    response.crawl_request = request
                    result.pages.append(response)
                    signal_bus.send(
                        "response_received", response=response, request=request
                    )
                    try:
                        signal_bus.send(
                            "parse_started", response=response, request=request
                        )
                        extracted = extract_items(response, extract)
                        record_extraction(result, extracted)
                        if callable(extract):
                            extra_items, callback_followups = handle_callback_result(
                                extract(response)
                            )
                            record_extraction(result, extra_items)
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
                        signal_bus.send(
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
                        signal_bus.send(
                            "request_skipped", request=request, reason="ignored"
                        )
                        continue
                    except CloseSpider as exc:
                        signal_bus.send(
                            "parse_finished",
                            response=response,
                            request=request,
                            items=[],
                            followups=[],
                        )
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
                        next_request = prepare_followup(
                            candidate, request, matched_rule
                        )
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
                        state_updated()
                        signal_bus.send(
                            "request_queued", request=next_request, source="follow"
                        )
                        result.stats.followed_links += 1
                        if (
                            max_requests is not None
                            and result.stats.queued >= max_requests
                        ):
                            scheduler_queue.clear()
                            state_updated()
                            break
            signal_bus.send("scheduler_empty", result=result)
    except Exception as exc:
        result.close_reason = "error"
        signal_bus.send("crawl_error", result=result, error=exc)
        raise
    finally:
        if owned_client:
            client.close()
        signal_bus.send(
            "crawl_finished", result=result, reason=result.close_reason or "finished"
        )
    return result
