---
title: "Architecture Overview"
description: "Architecture and ownership boundaries of the Python runtime and local control plane."
---

Webuse has two main components: a Python crawler runtime and a Node control
plane. The runtime fetches pages and produces records. The control plane connects
Harness, project files, schedules, and the dashboard.

<figure>
  <a href="../../diagrams/architecture-overview.png">
    <img src="../../diagrams/architecture-overview.png" width="1536" height="1024" loading="lazy" decoding="async" alt="The UI communicates with the Node control plane, which launches Python crawlers and receives logs and records. Project files hold code; SQLite stores metadata and execution records." />
  </a>
  <figcaption>The local control plane and crawler runtime share project files on disk.</figcaption>
</figure>

## Python Runtime

| Layer | Responsibility | Details |
| --- | --- | --- |
| HTTP clients | Thin curl_cffi session subclasses; curl_cffi owns transport, cookies, retries, and streaming. | [Request hooks](../request-hooks/) |
| Responses and extraction | Add lazy Lexbor parsing to native responses, select existing elements, and extract validated values. | [Selection and Extraction](../../user-guide/extraction/) |
| Engines | Schedule requests, enforce crawl policy, download pages, and aggregate results. | [Engine Internals](../engine/) |
| Spiders | Resolve configuration, dispatch responses, and connect item pipelines to the engine. | [Spider Internals](../spider/) |
| Pipelines | Validate, transform, and deliver items through sync or async hooks. | [Item Pipeline](../../references/pipelines/) |
| State | Store pending requests and seen hashes with replaceable memory or Redis backends. | [Crawl State](../state/) |
| Signals and metrics | Dispatch lifecycle events and emit StatsD-style measurements. | [Signals](../../references/signals/) |
| CLI | Translate commands into Python API calls and project files. | [CLI Internals](../cli-internals/) |

Spiders supply configuration and response handlers to the function-based
`crawl()` and `acrawl()` engines. Pipelines run inside the spider's response
handler; engines do not import spiders or pipelines. Direct Python calls work
without a project directory. See the [engine diagram](../engine/#architecture)
for the request lifecycle.

`Response` extends curl_cffi's response through `response_class`, preserving
native transport fields. `response.request` is the native HTTP request;
`response.crawl_request` holds crawl metadata. HTML parsing happens only when
document operations need it.

Both sync and async crawls support Redis scheduler state through `--state`.
Persistent queue and seen data do not provide a full checkpoint or guarantee
recovery of in-flight work.

## Local Control Plane

The Node server serves the UI and APIs and runs the orchestrator in the same
process. The orchestrator owns fixed cron schedules and the job queue, launching
a Python subprocess through `webuse crawl` for each execution.

Harness, the editor, and crawler jobs share project files on disk. Manual, scheduled,
and sample jobs execute those working files directly; users manage code history
with Git. SQLite stores project metadata, execution records, and Pi conversation
entries. Pi owns the coding-agent loop; Webuse supplies project tools and the UI.

See [Harness Internals](../harness-internals/) for development, process management,
and the agent integration, and [Monitoring Architecture](../monitoring/) for log
and metric data flow. Released Python packages bundle the Node server and browser
assets; [Package Release](../package-release/) explains building and verification.

## Agentic Crawl Control

`AgenticSpider` shares the async spider's project settings and pipeline lifecycle
but runs `agentic_crawl()` instead of `acrawl()`. Its model selects follow-up
requests and assembles records through Python tools. The engine reuses the queue,
seen set, and request hasher, and stops when the queue is empty with no active
request.

This controls work within a crawl. LLM scheduling of future executions is a separate,
unimplemented capability. Start with the [agentic spider tutorial](../agentic/);
see [Agentic Runtime](../../references/agentic/) for tools, memory, and limits.

