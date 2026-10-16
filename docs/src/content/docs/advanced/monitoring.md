---
title: "Monitoring Architecture"
description: "Current signals, metrics, and logs, with the planned dashboard monitoring boundary."
---

Monitoring connects crawler execution evidence to the project and run shown in
the dashboard. The current implementation includes Python signals and a metrics
emitter, stored run logs, and record inspection. Dashboard time-series metrics
and automatic LLM monitoring/advice remain planned.

## Source Map

| File | Responsibility |
| --- | --- |
| `src/webuse/signals.py` | Sync/async event dispatch for crawl, request, parse, and pipeline lifecycle. |
| `src/webuse/metrics/adapter.py` | `Metrics` and `attach_metrics()` translate signals into metrics. |
| `src/webuse/metrics/client.py` | UDP emission of counters, gauges, timers, and sets in a StatsD-like format. |
| `ui/src/lib/server/orchestrator.ts` | Crawler subprocess lifecycle and collection of run output. |
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
configured receiver. Attaching the emitter alone does not populate the dashboard.
See [Signals](../../references/signals/) for setup, event payloads, and metric names.

The Node control plane collects run logs and output records. Dashboard views and
the harness's run-inspection tool read this stored evidence for the same job.
Chat's streamed tool activity is separate from crawler log streaming.

