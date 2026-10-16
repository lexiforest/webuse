---
title: "Spider Internals"
description: "How the spider classes resolve configuration, dispatch responses, and run pipelines."
---

`src/webuse/spider/` adapts spider classes and declarative configuration to the
function-based engines in `src/webuse/engine/`. The engines own fetching,
queueing, deduplication, scope, concurrency, and result aggregation.

| File | Responsibility |
| --- | --- |
| `base.py` | `BaseSpider`: configuration, route lookup, item conversion, and common crawl options; `SpiderRun`: state for one invocation. |
| `sync.py` / `aio.py` | `Spider` / `AsyncSpider`: run pipelines and connect response handlers to `crawl()` / `acrawl()`. |
| `config.py` | Project, spider, and effective run configuration models. |
| `../engine/pages.py` | Shared compilation of `pages` into URL patterns, follow rules, and extraction rules. |
| `../extract/rules.py` | Declarative extraction and normalization into `ParseResult(items, requests)`. |
| `../extract/schema.py` | Validate page type/item/field structure and normalize selector strings before opening pipelines. |
| `../engine/policy.py` | URL normalization, robots rules, follow-up preparation, depth, and scope filtering. |
| `../pipelines/utils.py` | Internal helpers for pipeline lifecycle, item processing, signals, and serialization. |

`Spider` and `AsyncSpider` are sibling subclasses of `BaseSpider`. Users subclass
one of the concrete classes; `AsyncSpider` is not a subtype of `Spider`.

## From configuration to a run

1. `run()` loads project configuration and scopes the project's LLM settings
   with `use_openai_settings()`.
2. `_resolve_settings()` starts with instance attributes and `start()`, overlays
   explicitly supplied spider-config fields, fills project defaults, then applies
   run overrides. It compiles declarative `pages` into follow/extract rules and
   validates the result as `EffectiveSpiderSettings`.
3. `_prepare_run()` resolves pipelines and a signal bus into a `SpiderRun`.
   `_activate_run()` exposes it as `_run_state` for the duration of execution.
   The concrete spider emits `spider_open` and opens pipelines in order.
4. `_crawl_options()` combines resolved settings, the concrete class's extraction
   callback, and remaining engine options such as `client`. The spider calls
   `crawl()` or awaits `acrawl()` and returns its `CrawlResult`.
5. Pipeline lifecycle helpers close successfully opened pipelines in reverse order, even
   when a later opening or processing step fails. They attempt every close and
   preserve combined execution/cleanup failures in an exception group. An opener
   that fails must release its own partially allocated resources.
6. The spider emits `spider_closed` and clears `_run_state` even if cleanup or a
   lifecycle signal fails. Async cancellation also follows this cleanup path.

Project configuration comes from `config_path`, or a config file directly inside
`project_dir`; spiders do not search parent directories. Constructor overrides
set instance attributes. Pipeline precedence is separate: `run(pipelines=...)`,
then `self.pipelines`, then the spider config's `items.pipelines`. Project config
does not supply pipelines. Passing `pipelines=[]` disables them.
An instance rejects overlapping runs; use separate spiders for concurrent runs.
Sequential runs get fresh state, including after a failure.

## Responses, routes, and pipelines

The extraction callback reads `response.crawl_request.page_type`. Without a
page type it calls `parse()`. Otherwise it looks in `routes`, then for
`parse_<page_type>`. Route values may be method names or callables. If route lookup
fails but declarative extraction handles the page type, it falls back to `parse()`.
The default `parse()` extracts using the active settings; overriding it replaces
that behavior.

The adapters in `src/webuse/extract/rules.py` separate items from follow-up requests
into internal `ParseResult` (sync) or `AsyncParseResult` (async) values.
A parser can return an item, yield items and
`CrawlRequest` objects, or return `(items, followups)`. Strings represent follow-up
URLs. `acrawl()` and `AsyncSpider` also accept awaitable parse results and async
iterables. Async items flow through pipelines as yielded; generators are closed
on errors and cancellation. `start()` remains synchronous for both spider classes. Public parse
methods do not need to construct `ParseResult` themselves.

With pipelines enabled, items must be Pydantic models or convertible through
`item_model` / per-item `_item_model`. Each pipeline receives the previous one's
result; returning `None` or raising `DropItem` drops the item. Without pipelines,
items pass through unchanged. Processing emits item/pipeline signals. Async
workers process responses concurrently while preserving item order within each
response and pipeline order for each item. Other pipeline errors propagate.

Spiders call the internal `_process_items()` / `_aprocess_items()` helpers in
`pipelines/utils.py`. The sync engine invokes response handlers sequentially;
`AsyncSpider` processes items inside its fixed crawl workers, with no run-wide
pipeline lock or separate item task queue. Pipelines protect their own shared
resources when needed. Lifecycle
context managers in the same module handle opening and cleanup. `AsyncSpider`
accepts sync and async hooks; `Spider` rejects awaitables.
The pipeline interfaces are `ItemPipeline` and `AsyncItemPipeline`; hooks are `open_spider()`,
`process_item(item)`, and `close_spider()`.

Keep configuration in the spider layer, extraction in `extract/rules.py`, crawl
policy in the engines, and pipeline execution under the spiders. The engines do not
import spider classes. Changes usually need coverage in `tests/spider/`,
`tests/engine/`, and `tests/pipelines/`.
Inheritance or discovery changes also affect `src/webuse/cli/crawl.py`.

See [Async Crawling](../../user-guide/async/) for async usage and limitations,
[Item Pipeline Internals](../../references/pipelines/) for processing and cleanup behavior,
[Configuration Reference](../../references/config/) for configuration fields and examples, and
[Signals](../../references/signals/) for lifecycle events.
