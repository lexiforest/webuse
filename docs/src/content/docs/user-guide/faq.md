---
title: "FAQ"
---

## Why do I need webuse? Isn't curl_cffi enough?

Downloading is only one part of scraping. Real crawls also need parsing,
deduplication, item validation, item storage, scheduler state, and deployment
conventions.

All of the extra stuff are not hard, but you will reinvent them for each of your
crawler projects, that's why a framework is needed.

And yes, Codex/Claude can write that for you, but isn't that your own home-grown
framework? So nowadays, framework is no longer the code you could've write, it's the
coding convention that you will follow.

## How does webuse compare to Scrapy?

See [Scrapy vs Webuse](../vs-scrapy/) for details. Shortly put:

* webuse borrows useful Scrapy conventions, such as spiders and item pipelines.
* webuse is built from the ground up around `curl_cffi` and Pydantic.
* webuse supports Python spiders and YAML spider configs.

Existing Scrapy projects are also an intended input to the orchestration/cloud
product without a framework migration.

## Can I use BeautifulSoup or another parser?

Yes, but webuse's built-in `Document` and `Element` helpers are the default
path. They keep CSS, element selection, and lazy parsing behavior aligned.

## Why not provide every Scrapy middleware?

Most Scrapy middlewares are downloader-focused. Since webuse builds around
`curl_cffi`, common transport behavior such as proxies, cookies, TLS
fingerprints, impersonation, and redirects already maps directly to request
options.

And actually we don't think middleware is a good mental model, lifecycle customization
is handled through signals and pipelines.

## Is webuse breadth-first or depth-first?

The default in-memory queue is FIFO, so crawls are breadth-first by default.
The queue abstraction is explicit, so other queue implementations can choose a
different policy.

## How do I deploy webuse?

Recommended deployment paths:

* `webuse serve` for local development
* Docker Compose for simple server jobs
* Kubernetes `CronJob` for scheduled production crawls
* Webuse Cloud deployment when you do not want to operate infrastructure

See [Deployment](../deployment/) for details.

## Why curl_cffi instead of requests, or httpx?

The main reason is impersonation. Many targets care about TLS and HTTP
fingerprints, not just headers. `curl_cffi` exposes those features while
still giving webuse sync and async HTTP surfaces.

In the future, we will also integrate [brimp](https://github.com/lexiforest/brimp),
for a seamless JavaScript rendering pipeline.

## How can I export JSON?

Use JSON Lines through `-o output.jsonl` or the `JsonlPipeline`. JSONL is
one JSON object per line, which is easier to stream than a single JSON array.

The cloud product commits to no vendor lock-in and downloading all user data at
any time. Complete cloud export remains to be implemented; existing local
pipelines produce portable JSONL, CSV, and SQLite outputs.

## Can I use a local model?

Yes, in fact we try to detect local services like ollama and lm studio automatically.
You can also use the `llm.*` config to use any OpenAI-compatible API.

## Will the LLM monitor my crawlers?

That is part of the product plan: use logs, metrics, failed responses, and data
checks to advise users. But in the initial releases, we will focus on the framework
itself.

## What is an agentic crawler?

[`AgenticSpider`](../../advanced/agentic/) uses an LLM during an execution to choose links,
inspect pages, and assemble validated records. The engine stops when the request
queue is empty and no request is active. You declare the goal, output model,
and total token budget; tools are Python calls inside the
crawler. AI-generated code alone is not this runtime mode.

## When should I use YAML config and when should I use Python?

Start with the smallest surface that fits:

1. command line options
2. YAML config
3. Python spider code

Use Python when extraction, routing, item cleanup, or start URL loading needs
custom control flow. YAML spiders can already cover common multi-page
cases with page-local follow rules, follow `page_type` values, and named item
extractors under `pages.<page_type>.extract`.

## How do I reduce bans?

Be polite and scrape only the information you need at the minimum practical
request volume. The main technical factors are usually proxy quality and client
fingerprinting, including TLS, HTTP/2, JavaScript, and behavior signals.

For solving client chanllenges, see [Signing & Captchas](../../advanced/request-hooks/).
