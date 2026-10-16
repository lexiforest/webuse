---
title: "The Engine"
description: "Crawl execution, policy, and request state in src/webuse/engine."
---

`src/webuse/engine/` runs crawls: it schedules requests, downloads responses,
invokes extraction, discovers follow-ups, and collects results. Spiders supply
configuration and callbacks; HTTP transport belongs to `curl_cffi`.

## Architecture

<figure>
  <a href="../../diagrams/engine-architecture.svg">
    <img src="../../diagrams/engine-architecture.svg" width="960" height="860" alt="Seeds enter a queue. Requests are checked and downloaded, then responses are parsed and items processed or saved. Follow-ups loop back. The crawl finishes when the queue is empty and no work is active." />
  </a>
  <figcaption>The normal crawl workflow. Arrows show control flow.</figcaption>
</figure>

Blue shapes belong to the engine, purple shapes supply seeds or response
handling, and the green step delegates transport to `curl_cffi`. Pipelines run
inside spider callbacks; direct `crawl()` and `acrawl()` calls can use extraction
rules or callbacks without a spider. Follow rules inspect the current response
and combine their matches with callback requests before applying crawl policy.
Configured pipelines and CLI output save items as they are processed during the
crawl. The engine also collects items in memory for the returned `CrawlResult`;
returning that object is separate from saving output. Lifecycle signals let
listeners observe each stage.

Both ordinary engines use this flow, with different concurrency models described
below. [Agentic crawl control](../agentic/) uses a separate model/tool
loop and reuses the queue, seen set, and request hasher.

## Source

| File | Responsibility |
| --- | --- |
| `__init__.py` | Export `crawl()`, `acrawl()`, and request-state interfaces and implementations. |
| `sync.py` | Blocking `crawl()`: concurrent downloads in a thread pool, sequential parsing on the calling thread. |
| `aio.py` | Async `acrawl()`: fixed workers consume the selected async frontier directly; a condition coordinates idle workers and exhaustion. |
| `pages.py` | Compile page patterns, follow rules, and extraction before a run. |
| `policy.py` | Prepare requests and URLs, check robots.txt, discover links, and enforce depth, domain, page type, and follow rules. |
| `state.py` | Queue, seen-set, and fingerprint contracts; memory and Redis implementations. |
| `async_state.py` | Async queue/seen protocols, memory and Redis backends, and awaited state counts. |

## Request lifecycle

Before starting a crawl, the engine compiles page patterns and validates declarative
extraction. Invalid rules fail before client creation or downloads; Python
callbacks pass through unchanged.

1. Convert seeds to `CrawlRequest` objects, normalize URLs, assign or validate
   `page_type`, and reject seen fingerprints before enqueueing.
2. On dequeue, recheck page patterns and claim the fingerprint. Skip duplicates,
   then check robots.txt and the request budget before downloading.
3. Fetch through the HTTP client, then attach metadata as `response.crawl_request`.
4. Use `extract/rules.py` to obtain items and follow-up requests from the response.
5. Combine callback requests with follow-rule matches, apply scope and depth
   filters, then use the same page-pattern and seen checks before enqueueing.
6. Return `CrawlResult` with items, responses, errors, visited URLs, and counters.

The engine emits lifecycle signals for monitoring. Ordinary download errors are
recorded and crawling continues; unexpected parsing and follow-processing errors
propagate. `IgnoreRequest` skips processing, while `CloseSpider` clears pending
work and sets a close reason. Clients created by the engine are closed on cleanup.

Pipelines run inside the callback supplied by the spider, so the engine collects
items after pipeline processing. The engine does not import spiders or pipelines.

## State and limits

`RequestQueue` stores pending requests, `RequestSeen` tracks fingerprints, and
`RequestHasher` defines request identity. The default fingerprint includes the
method and canonical URL, with optional selected headers; bodies and
`options.params` are excluded. Canonicalization sorts query parameters and
removes common tracking parameters and fragments.

Both engines accept replaceable queue and seen backends; `acrawl()` requires
the async protocols. Both accept a custom hasher. Redis uses a list and set,
without acknowledgements or recovery of in-flight requests.

`max_requests` counts admitted download attempts, including failures.
`max_depth=0` processes seeds only. Results accumulate in memory.

See [Spider Internals](../spider/), [Async Crawling](../../user-guide/async/),
and [Crawl State](../state/) for integration and limitations.
