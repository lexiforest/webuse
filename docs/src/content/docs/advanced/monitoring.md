---
title: "Monitoring Architecture"
description: "Execution dashboards, Prometheus metrics, logs, and stored crawl evidence."
---

Monitoring connects crawler execution evidence to the project and execution shown in
the dashboard. Each execution has a fixed monitoring dashboard with optional built-in
panels. Prometheus supplies time series; SQLite supplies execution metadata, final
counts, logs, and saved records. Automatic LLM monitoring/advice remains planned.

## Source Map

| File | Responsibility |
| --- | --- |
| `src/webuse/signals.py` | Sync/async event dispatch for crawl, request, parse, and pipeline lifecycle. |
| `src/webuse/metrics/adapter.py` | `Metrics` and `attach_metrics()` translate signals into metrics. |
| `src/webuse/metrics/client.py` | UDP emission of counters, gauges, timers, and sets in a StatsD-like format. |
| `src/webuse/metrics/execution.py` | Automatic CLI instrumentation for control-plane executions and final count summaries. |
| `src/webuse/monitoring.py` | Configuration discovery and Prometheus HTTP transport through curl_cffi. |
| `ui/src/lib/server/monitoring.ts` | Execution-scoped queries, time bounds, and panel data. |
| `ui/src/routes/monitoring.tsx` | Fixed dashboard, panel preferences, and TanStack Query polling. |
| `ui/src/components/MetricChart.tsx` | Lazy-loaded ECharts time series, linked cursors, and interval selection. |
| `ui/src/lib/server/orchestrator.ts` | Crawler subprocess lifecycle and collection of execution output. |
| `ui/src/routes/api/logs.ts` | Stored log access for the UI. |
| `ui/src/routes/logs.tsx` | Log view, currently using polling. |

## Current Data Flow

<figure>
  <a href="../../diagrams/monitoring-data-flow.png">
    <img src="../../diagrams/monitoring-data-flow.png" width="1536" height="1024" loading="lazy" decoding="async" alt="Metrics flow from crawl signals through the metrics adapter and UDP emitter to a configured receiver. Separately, the Node collector stores crawler logs in SQLite for the dashboard to poll through the API." />
  </a>
  <figcaption>Metrics use a configured receiver; dashboard log views read stored logs through polling.</figcaption>
</figure>

Engines and spider pipeline helpers emit through `SignalBus`. Attaching `Metrics`
converts these events into metrics and sends them through `webuse.metrics` to a
configured receiver. The control plane enables this instrumentation automatically
when launching `webuse crawl`. Prometheus must scrape a StatsD exporter to populate
time-series panels.
See [Signals](../../references/signals/) for setup, event payloads, and metric names.

The Node control plane collects execution logs and output records. Dashboard views and
the harness's execution-inspection tool read this stored evidence for the same job.
Harness's streamed tool activity is separate from crawler log streaming.


## Compose metrics storage

`ui/compose.yaml` includes Prometheus and a StatsD exporter, adapted from ustats.
Instrumented crawlers in the Compose network send metrics to `statsd-exporter:8125`.
Host crawlers use `127.0.0.1:8125`. Prometheus scrapes the exporter every five seconds
and stores data in a named volume. Open `http://127.0.0.1:9090` to query it.
The global Stats page shows SQLite execution summaries. Open **Executions → Monitor**
for charts scoped to one execution.

For a host-based development server or `webuse serve`, start just the metrics services:

```sh
docker compose -f ui/compose.yaml up -d prometheus statsd-exporter
```

Set `monitoring.prometheus_url: http://127.0.0.1:9090` in `.webuserc.yaml`, or save
the URL in **Settings → Monitoring**. The full Compose stack already supplies
`WEBUSE_PROMETHEUS_URL=http://prometheus:9090` and `WEBUSE_STATSD_HOST=statsd-exporter`.

## Connection and preferences

Connection precedence is a nonempty SQLite setting, then `WEBUSE_PROMETHEUS_URL`,
then `monitoring.prometheus_url` from the framework's configuration loader. That
loader reads user configuration and the nearest `.webuserc.yaml` found upward from
the launch directory (`WEBUSE_CONFIG_DIR` when set). Clearing the UI setting restores
fallback discovery. **Test saved connection** checks the effective saved connection.
Endpoints use HTTP(S); embedded credentials are not supported.

The browser requests Webuse's `/api/monitoring` endpoint. Node scopes queries and
invokes the Python curl_cffi transport; the browser never connects to Prometheus.
Queries have timeouts, bounded series counts, and resolution chosen from the selected
duration. Each series includes `webuse_instance` (a UUID stored in the database),
`project_id`, `execution_id`, and `spider`, preventing collisions between databases
that share one Prometheus instance. No URLs or item contents become metric labels.

The **Panels** menu saves enabled panel IDs per project in SQLite. Ordering is fixed;
hidden panels are unmounted and stop polling. **Restore defaults** enables progress,
throughput, HTTP health, extraction/pipelines, data quality, and errors/logs.
Resources, crawler LLM usage, and insights are optional. Refresh pauses in background
browser tabs. Selecting an interval in a chart filters the other charts and logs.

## Evidence and limitations

- **Progress:** live request, queue, and in-flight counts from Prometheus; saved item
  counts from SQLite. Finished instrumented crawls use their final count summary,
  so a short crawl can still show totals even if it finished between scrapes.
- **Throughput, HTTP, extraction:** rates, status codes, latency percentiles,
  item outcomes, and mean parse/pipeline durations. Counters map to `_total`;
  timers map to histograms in seconds.
- **Data quality:** field completeness and exact duplicate counts in the first 100
  saved items. This is an execution-wide sample, not schema validation or a time-series
  query. The Data view exposes the full collected records.
- **Errors/logs:** the latest 100 stored log lines in the selected interval. stderr
  alone does not identify an error. Use Logs for the full output.
- **Resources:** crawler-process CPU usage, peak RSS, and downloaded bytes. CPU/RSS
  use Python's `resource` module where available and exclude descendant processes.
  Peak RSS is a high-water mark, not current memory usage.
- **LLM usage:** explicitly unavailable until crawler model calls are instrumented.
  Harness conversation tokens are not attributed to crawler executions.
- **Insights:** simple rules based on saved execution evidence; no automatic model calls.

Old executions, uninstrumented custom commands, expired history, and intervals with
too few scrapes show unavailable telemetry rather than invented zeros. Custom commands
that invoke `webuse crawl` inherit instrumentation. Other runtimes need their own
metric adapter. `WEBUSE_METRICS_ENABLED=0` disables automatic instrumentation;
`WEBUSE_STATSD_HOST` and `WEBUSE_STATSD_PORT` select the UDP receiver (defaults:
`127.0.0.1:8125`). Receiver failure does not fail a crawl.

The exporter expires inactive series after one hour to bound its active series set;
Prometheus retains previously scraped history according to its own retention setting.
Final counts may be unavailable after abrupt process termination. UDP metrics are
best-effort operational evidence, not an accounting ledger.
