---
title: "webuse"
---

`webuse` is a crawler toolkit built around `curl_cffi` and Pydantic,
with a crawler harness based on pi, and orchestrator + crawler dashboard.

There are many ways to work with webuse:

- Write a simple yaml config file
- Write a regular python code based spider
- Let your Claude/Codex generate a project for you
- Run and monitor your spiders with the webuse ui and process manager
- Import your existing project with other framework, such as Scrapy.

With the [hosted harness and deploying service](https://impersonate.pro/webuse), you get even more:

- Integrated proxy services
- Integrated captcha servcies
- An isoldated deploying environment

Start with [Quick Start](./user-guide/quick-start/) if you are new to the project. Use
[Command Line](./references/cli/) for command-line workflows, [Configuration Reference](./references/config/) for project and spider
configuration, and [Scrapy vs Webuse](./user-guide/vs-scrapy/) if you are coming from Scrapy or any other framework.

## User Guide

- [Quick Start](./user-guide/quick-start/)
- [Harness](./user-guide/harness/)
- [Dashboard](./user-guide/dashboard/)
- [Async Crawling](./user-guide/async/)
- [Selection and Extraction](./user-guide/extraction/)
- [Deployment](./user-guide/deployment/)
- [Webuse Cloud](./user-guide/cloud/)
- [Scrapy and Webuse](./user-guide/vs-scrapy/)
- [Frequently Asked Questions](./user-guide/faq/)

## References

- [Command Line](./references/cli/)
- [Configuration Reference](./references/config/)
- [Item Pipeline](./references/pipelines/)
- [Signals](./references/signals/)
- [Agentic Runtime](./references/agentic/)

## Advanced Usage

- [Agentic Spiders](./advanced/agentic/)
- [Signing & CAPTCHAs](./advanced/request-hooks/)
- [Crawl State](./advanced/state/)

## Contributing

- [Architecture Overview](./advanced/overview/)
- [Engine Internals](./advanced/engine/)
- [Spider Internals](./advanced/spider/)
- [CLI Internals](./advanced/cli-internals/)
- [Harness Internals](./advanced/harness-internals/)
- [Monitoring Architecture](./advanced/monitoring/)
- [Package Release](./advanced/package-release/)
