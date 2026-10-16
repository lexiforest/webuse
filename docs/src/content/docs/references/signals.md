---
title: "Signals"
---

`webuse` exposes signals so you can hook into its internals.

For a practical request-handling walkthrough, see
[Signing Requests and Solving CAPTCHAs](../../advanced/request-hooks/).

Some default behavior is a no-op, while other signals feed the bundled
`webuse.metrics` metrics emitter. A receiving service is needed to retain or
visualize those metrics; attaching the emitter alone does not populate the UI.

Signals are emitted through `SignalBus`, a small dependency-free event
dispatcher:

```python
import webuse

signals = webuse.SignalBus()
signals.connect("item_processed", lambda item: print(item))

webuse.crawl("https://example.com", signals=signals)
```

## Signal Reference

Handlers only need to accept the keyword arguments they use. If a signal sends
`item`, `response`, and `spider`, a handler that only accepts `item`
still works.

Metrics are emitted by attaching `Metrics`:

```python
from webuse.metrics import init as metrics_init
import webuse

metrics_init(prefix="webuse")

signals = webuse.SignalBus()
webuse.attach_metrics(signals, tags={"spider": "books"})
webuse.crawl("https://example.com", signals=signals)
```

For asynchronous code, use `await webuse.metrics.ainit(...)`. Initialization is
asynchronous; emitting counters, gauges, and timers uses regular methods backed
by an asyncio datagram transport. Call `webuse.metrics.close()` in a `finally`
block before the event loop exits. Explicit `Client` and `AsyncClient` instances
also provide `close()`. Closing repeatedly is safe, and reinitialization closes
the previous socket or transport after the replacement initializes successfully.

Here is a list of signals and their default behavior.

## Engines

* `spider_open` - hook only
* `spider_closed` - hook only
* `crawl_started` - metric
* `crawl_finished` - metric
* `crawl_error` - metric; fatal crawl failures before the exception propagates
* `crawl_idle` - hook, not implemented
* `scheduler_empty` - hook

## Agentic Progress

Agentic crawls also emit `agent_progress` with `turn` and `summary` when the model
provides a progress sentence. The summary is normalized to one line and at most
500 characters, matching the INFO log. It describes progress and intended next
actions; tool outcomes remain available through `agent_observation`.

## State

* `state_loaded` - metric
* `state_updated` - metric

The engines emit state snapshots at startup and during scheduling. Snapshots
include the backend name and queue/seen sizes. Custom sync adapters may implement
`__len__` to report sizes; otherwise those sizes are omitted. Async snapshots
describe its in-memory queue, not persistent state.

## Request Handling

* `request_queued` - metric
* `request_skipped` - metric
* `request_before_downloader` - metric
* `request_after_downloader` - metric
* `request_error` - metric; a failed download recorded in `CrawlResult.errors`
* `response_received` - metric

## Parsing and Items

Both engines propagate parsing, pipeline, and follow-callback exceptions.
Parsing failures emit `parse_error` and then `crawl_error`. Download failures
emit `request_error` and are recorded while remaining requests continue.
`IgnoreRequest` and `CloseSpider` retain their skip/stop behavior.

* `parse_started` - metric
* `parse_finished` - metric
* `parse_error` - metric
* `pipeline_started` - metric
* `pipeline_finished` - metric
* `pipeline_error` - metric
* `item_extracted` - metric
* `item_processed` - metric
* `item_dropped` - metric
* `item_error` - metric

## Metric Names

`Metrics` emits these metric buckets:

* `crawl_started`
* `crawl_finished`
* `crawl_duration`
* `crawl_in_flight`
* `crawl_error`
* `state_loaded`
* `state_updated`
* `state_queue_size`
* `state_seen_size`
* `request_queued`
* `request_skipped`
* `request_in_flight`
* `request_finished`
* `request_duration`
* `request_error`
* `response_received`
* `response_bytes`
* `parse_in_flight`
* `parse_finished`
* `parse_duration`
* `parse_items`
* `parse_followups`
* `parse_error`
* `pipeline_in_flight`
* `pipeline_finished`
* `pipeline_duration`
* `pipeline_error`
* `item_extracted`
* `item_processed`
* `item_dropped`
* `item_error`

## Async Handlers

Use `asend()` when dispatching async handlers. Sync crawl uses `send()`, so
sync signal handlers must not return awaitables. Async crawl and
`AsyncSpider.run()` use `asend()`.

## Dashboard & Monitoring

`webuse` sends some metrics with these signals, so you can know what the crawler is
doing, if the data are being collected correctly, if you are being banned, etc.

`webuse.metrics` is a simple emitter, with StatsD-like wire format, it
sends counters, gauges, timers, and sets over UDP. A message has the form
`prefix.bucket:value|type` with optional `|#key:value` tags. Timers passed in
seconds are converted to milliseconds on the wire.

For example, with the `webuse` prefix and `spider:books` tag configured above,
a successful download taking 250 ms emits these messages among others:

```text
webuse.request_finished:1|c|#spider:books,success:true
webuse.request_duration:250.0|ms|#spider:books,success:true
```

You can see the dashboard in the webuse UI.


TODO: add a screenshot.
