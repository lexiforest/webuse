---
title: "Crawl State"
---

`webuse crawl` uses in-memory scheduler state by default. For sync and async crawls,
`--state` accepts a Redis URL to store pending requests and seen hashes.

```bash
cd books_project
webuse crawl --spider books --state redis://localhost:6379/0 -o books.jsonl
```

Running the command again reuses the same queue and seen hashes.

## What Is Stored

webuse stores two scheduler structures:

* request queue: pending `CrawlRequest` values
* request seen: request hashes that have already been scheduled

Request hashes are computed from the HTTP method and a canonical URL by
default. The canonical URL sorts query params and removes common tracking params
such as `utm_source`, `utm_medium`, `utm_campaign`, `gclid`, and
`fbclid`.

## Redis State

Passing a Redis URL stores state in Redis:

```bash
cd books_project
webuse crawl --spider books --state redis://localhost:6379/0 --async
```

webuse uses:

* Redis list for the queue
* Redis set for seen request hashes

Keys are scoped by spider target, for example:

```text
webuse:books:requests:queue
webuse:books:requests:seen
```

## Persistence Limits

<figure>
  <a href="../../diagrams/state-persistence.png">
    <img src="../../diagrams/state-persistence.png" width="1536" height="1024" loading="lazy" decoding="async" alt="A pending request is popped from Redis, marked seen, and downloaded. Interruption after marking seen can leave unfinished work absent from the queue and its fingerprint retained, preventing automatic retry." />
  </a>
  <figcaption>A request leaves the queue before its download completes. Reusing Redis state cannot guarantee recovery of in-flight work.</figcaption>
</figure>

Redis stores scheduler state, not a full process checkpoint. Popping a request
removes it from the queue before its download completes, and requests are marked
seen before downloading. In-flight work can be lost on interruption, and failed
requests remain seen. Reusing state does not guarantee recovery of unfinished
work. Reaching `max_requests` or raising `CloseSpider` clears pending requests.

## Async Python state

`acrawl()` and `AsyncSpider.run()` accept `request_queue` and `request_seen`
implementing `AsyncRequestQueue` and `AsyncRequestSeen`. Queue methods are
awaitable `put`, `pop`, `empty`, `clear`, and `size`; `pop` returns `None` when
empty. Seen methods are awaitable `add`, `contains`, and `size`; `add` atomically
returns whether a hash is new. Request hashing remains synchronous.

Defaults are `AsyncMemoryRequestQueue` and `AsyncMemoryRequestSeen`. Redis
implementations use redis-py's asyncio client and the same key/serialization
format as their synchronous counterparts:

```python
from contextlib import aclosing
from webuse import AsyncRedisRequestQueue, AsyncRedisRequestSeen, acrawl


async def crawl_with_state():
    async with (
        aclosing(AsyncRedisRequestQueue("books:queue")) as queue,
        aclosing(AsyncRedisRequestSeen("books:seen")) as seen,
    ):
        return await acrawl(
            "https://example.com", request_queue=queue, request_seen=seen
        )
```

Callers own supplied state backends. `aclose()` closes a backend's own Redis
client, but leaves an injected `client=` open. The CLI closes the state clients
it creates. Workers consume the selected frontier directly, and exhaustion
requires an empty frontier with no active workers. This coordinates one crawl
invocation, not multiple distributed crawlers or external queue producers.
