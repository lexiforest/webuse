---
title: "Item Pipeline"
description: "How spiders create item pipelines, process records, and manage resources."
---

The item pipeline owns item validation, transformation, and delivery. Spiders connect
pipelines to response parsing.

The typical usage patter for item pipeline is content cleaning and storage.

Source code: `src/webuse/pipelines/`

## Source

| File | Responsibility |
| --- | --- |
| `factory.py` | `create_pipeline()`: create instances from item pipelines. |
| `utils.py` | Utilities for pipelines. |

Built-in pipelines live in `builtin/` and implement the shared `ItemPipeline`
contract from `base.py`.

| File | Pipeline | Responsibility |
| --- | --- | --- |
| `base.py` | `ItemPipeline`, `AsyncItemPipeline` | Sync and async base classes for item processing. |
| `builtin/jsonl.py` | `JsonlPipeline` | Deliver items to a JSONL file. |
| `builtin/csv.py` | `CsvPipeline` | Deliver items to a CSV file. |
| `builtin/sqlite.py` | `SQLitePipeline` | Deliver items to a SQLite database. |
| `builtin/webhook.py` | `WebhookPipeline` | Deliver each item as JSON to an HTTP endpoint. |
| `builtin/assets.py` | `AssetDownloadPipeline` | Download item-linked assets and add download metadata to the item. |
| `builtin/aio.py` | `AsyncJsonlPipeline`, `AsyncCsvPipeline`, `AsyncSQLitePipeline`, `AsyncWebhookPipeline`, `AsyncAssetDownloadPipeline` | Async equivalents with the same configuration options. |

## Usage

<figure>
  <a href="../../diagrams/item-pipeline.png">
    <img src="../../diagrams/item-pipeline.png" width="1536" height="1024" loading="lazy" decoding="async" alt="With pipelines configured, an extracted item is converted to a validated model and passed through each process_item hook. Returning None or raising DropItem stops the chain for that item; otherwise processing continues to the next pipeline. Transformation and saving happen during the crawl." />
  </a>
  <figcaption>Each item passes through the configured chain. Pipelines can transform or save it at each step.</figcaption>
</figure>

For crawler projects, configure the chain in `spiders/<name>.yaml` and keep
custom pipeline implementations in Python. For example:

```yaml
pipelines:
  - class: spiders.books.CleanPipeline
  - type: jsonl
    path: output.jsonl
```

This references the `CleanPipeline` generated in `spiders/books.py`. Project-level
defaults do not supply pipelines. For direct library use or explicitly Python-only
projects, set `Spider.pipelines`; `run(pipelines=...)` overrides the chain for that
execution without changing the stored attribute. The factory recognizes built-in
names such as `jsonl`, mappings with `type` or `class`, and Python pipeline objects.

The following examples demonstrate direct library use without a project:

```python
from pydantic import BaseModel
from webuse import JsonlPipeline, Spider


class Page(BaseModel):
    title: str


spider = Spider(
    start_urls=["https://example.com"],
    item_model=Page,
    extract={"default": {"page": {"fields": {"title": "h1"}}}},
    pipelines=[JsonlPipeline("pages.jsonl")],
)
spider.run()

# Run again with a different pipeline, overriding the spider's default chain.
spider.run(pipelines=[{"type": "csv", "path": "pages.csv"}])
```

With the pipeline chain, spiders convert each extracted item to a Pydantic
`BaseModel` through `item_model` or per-item `_item_model` when needed.
Each `process_item(item)` receives the previous pipeline's result and must return
a `BaseModel` or `None`. Returning `None` or raising `DropItem` stops that item's
chain. Surviving items are returned to the engine for aggregation in `CrawlResult`.

## Events

The processing helpers emit `item_extracted`, `pipeline_started`, `pipeline_finished`, and
`item_processed` events. Returning `None` and raising `DropItem` both emit
`pipeline_finished` followed by `item_dropped`, with a `DropItem` error in the
event context. Both stop the item's chain and count as a drop in metrics.
Other processing errors emit `pipeline_error` and
`item_error` before propagating. Initial item-conversion failures occur before
the pipeline error handlers. See [Signals](../signals/) for the event reference.

## Lifecycle

**Opening and Closing.** Spiders open pipelines in order with `open_spider()` and
close successfully opened pipelines in reverse order with `close_spider()`. Both hooks
take no arguments. If opening fails, previously opened pipelines are closed; the failing opener
must release its own partially allocated resources.

## Adding a Custom Pipeline

```python
from pydantic import BaseModel
from webuse import ItemPipeline, Spider


class Item(BaseModel):
    title: str


class CleanTitlePipeline(ItemPipeline):
    def process_item(self, item: Item) -> Item:
        return item.model_copy(update={"title": item.title.strip()})


class ExampleSpider(Spider):
    start_urls = ["https://example.com"]
    pipelines = [CleanTitlePipeline()]

    def parse(self, response):
        return Item(title=response.find(css="h1").text())
```

Calling `ExampleSpider().run()` applies `CleanTitlePipeline` to each parsed item.

## Async Pipelines

Subclass `AsyncItemPipeline` for async `open_spider()`, `process_item(item)`,
and `close_spider()` hooks. `AsyncSpider` accepts both sync and async pipelines;
`Spider` requires sync hooks.

```python
from webuse import AsyncItemPipeline


class SaveItemPipeline(AsyncItemPipeline):
    def __init__(self, store):
        self.store = store

    async def process_item(self, item):
        await self.store.save(item.model_dump())
        return item
```

Pass an instance to `AsyncSpider(pipelines=[SaveItemPipeline(store)], ...)`,
where `store.save()` is your async storage API.

`AsyncSpider` selects async versions of configured built-in names/types. For
explicit Python classes or instances, use the `Async*Pipeline` classes listed
above; these are not converted automatically.

Items are processed in order within each response, while responses run
concurrently up to crawl `concurrency`. Custom async pipelines may receive
overlapping calls; protect shared state across awaits with `asyncio.Lock` where
needed. Sync hooks run on the event-loop thread. Lifecycle hooks run before
workers start and after they stop.

See [Spider Internals](../../advanced/spider/) for how spiders connect pipelines to the
crawl engines and [Configuration Reference](../config/) for YAML fields and examples.
