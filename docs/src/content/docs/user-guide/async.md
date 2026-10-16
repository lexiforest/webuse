---
title: "Async Crawling"
description: "The async counterparts to Webuse's crawl, spider, client, and pipeline APIs."
---

Webuse provides sync and async APIs for the same crawling workflow. Selectors,
follow rules, item models, and project configuration are shared. This guide shows
the async counterpart of each API and where `await` is needed.

For production usage, we recommend the async API for better performance.

| Sync | Async |
| --- | --- |
| `crawl(...)` | `await acrawl(...)` |
| `Spider` and `spider.run()` | `AsyncSpider` and `await spider.run()` |
| `with Client() as client:` | `async with AsyncClient() as client:` |
| `client.get(...)` | `await client.get(...)` |
| `response.find(css=...)` | `response.find(css=...)`; no `await` needed |
| `response.find(llm=...)` / `response.find_all(llm=...)` | `await response.afind(llm=...)` / `await response.afind_all(llm=...)` |
| `response.llm_extract(...)` | `await response.allm_extract(...)` |
| `ItemPipeline` | `AsyncItemPipeline` for awaitable I/O; sync pipelines also work |

## Crawl Functions

`acrawl()` is the async counterpart of `crawl()`. It accepts the same crawling
options and returns a `CrawlResult` when awaited. Given your `start_urls`,
`extract`, and `follow` configuration:

```python
from webuse import acrawl

result = await acrawl(start_urls, extract=extract, follow=follow, concurrency=5)
print(result.items)
```

Put this code inside an `async def` function and call it with
`asyncio.run(main())` at your script's entry point. In an existing async function
or a notebook that supports top-level await, await it directly. Both APIs return
items, errors, responses, and stats in the result.

## Spiders and Parsing

`AsyncSpider` provides the same spider configuration and parsing conventions as
`Spider`, with an awaitable `run()`. A parser that only reads downloaded HTML
can be a regular function:

```python
from pydantic import BaseModel
from webuse import AsyncSpider


class Page(BaseModel):
    title: str


class PagesSpider(AsyncSpider):
    start_urls = ["https://example.com/"]

    def parse(self, response):
        title = response.find(css="h1")
        if title is not None:
            yield Page(title=title.text())


# Inside your async entry point:
result = await PagesSpider().run()
```

CSS selection, `.text()`, `.attr()`, and `response.follow(...)` are synchronous
in both APIs. A parser that awaits I/O uses `async def`. For example, a parser
using [LLM extraction](../extraction/) can await `allm_extract()`:

```python
async def parse(self, response):
    yield await response.allm_extract("Extract the page title.", schema=Page)
```

Async parsers can return results or yield them as an async generator.
`start()` and `FollowRule.predicate` are synchronous in both APIs. Follow callbacks can be
coroutines returning links or requests, but cannot be async generators.

## HTTP Clients

`AsyncClient` corresponds to `Client`, with `async with` for its lifetime and
awaitable request methods. Reading the downloaded response uses the same API:

```python
from webuse import AsyncClient


async def fetch_title(url):
    async with AsyncClient() as client:
        response = await client.get(url)
        title = response.find(css="h1")
        return title.text() if title is not None else None
```

`acrawl()` manages its own client by default. If you pass `client=client`, keep
that client open until the crawl completes and close it yourself afterward.

Calling a synchronous HTTP or storage client inside `async def` still blocks
other work on the event loop. Use awaitable clients for I/O in async callbacks.

## Item Pipelines

`AsyncItemPipeline` has the same `open_spider()`, `process_item()`, and
`close_spider()` hooks as `ItemPipeline`, declared with `async def` so they can
await storage or HTTP calls. For example:

```python
from webuse import AsyncClient, AsyncItemPipeline


class SendRecords(AsyncItemPipeline):
    def __init__(self, url):
        self.url = url

    async def open_spider(self):
        self.client = AsyncClient()

    async def process_item(self, item):
        response = await self.client.post(self.url, json=item.model_dump(mode="json"))
        response.raise_for_status()
        return item

    async def close_spider(self):
        await self.client.close()
```

Both pipeline types are configured through the spider's `pipelines`.
`AsyncSpider` also accepts synchronous `ItemPipeline` instances, which are useful
for work such as cleaning strings that needs no I/O.
Calls to `process_item()` can overlap across responses, so protect shared mutable
state when updating it across awaits.

Configured built-in pipelines such as `jsonl`, `csv`, `sqlite`, `webhook`, and
`assets` automatically use async implementations with `AsyncSpider`. If you
construct pipeline objects yourself, choose their async classes, such as
`AsyncJsonlPipeline` or `AsyncWebhookPipeline`; explicit sync objects are not
converted. See [Item Pipelines](../../references/pipelines/) for their options.

## Project Commands

Sync and async Python spiders use the same registration in `webuse.yaml` and
the same crawl command:

```bash
cd my_project
webuse crawl --spider pages
```

The CLI detects `AsyncSpider` and awaits it automatically. You do not need to add
`--async` for a Python async spider.

For a declarative YAML spider, select async execution with:

```bash
webuse crawl --spider pages --async
```

To generate a new async spider in the current project, use:

```bash
webuse gen pages https://example.com/ --async
```

For Python spiders, the base class determines execution: `Spider` is synchronous
and `AsyncSpider` is asynchronous, regardless of the `crawl --async` flag.

## Concurrency and State

<figure>
  <a href="../../diagrams/async-concurrency.png">
    <img src="../../diagrams/async-concurrency.png" width="1536" height="1024" loading="lazy" decoding="async" alt="Three workers download different responses concurrently. Within each worker, each item's pipeline chain finishes before the next item's begins; processing overlaps between workers." />
  </a>
  <figcaption>Example timing with three workers. A1 and A2 are items from response A; each bar covers one item's pipeline chain.</figcaption>
</figure>

Both APIs use `concurrency` and `per_domain` to control parallel work. Within one
response, items pass through the pipeline chain in order, but different responses
can be processed concurrently. Do not rely on a fixed overall item order.

`AsyncRequestQueue` and `AsyncRequestSeen` are the async counterparts of
`RequestQueue` and `RequestSeen` for custom backends passed to `acrawl()`.
Async memory and Redis backends are available; CLI `--state` also works with async
execution. See [Crawl State](../../advanced/state/) for configuration.

Use a separate spider instance for each concurrent run. Async execution still
accumulates items and responses in the final result, and cancellation does not
save a checkpoint for resuming later.
