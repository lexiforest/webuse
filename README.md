# Webuse

`webuse` is a combination of 3 layers:

- A Python crawler framework.
- A harness for writing crawlers on top of the framework.
- A orchestrator and UI for running the crawlers.

For hosted version with integrated proxies and browser rendering, visit
[impersonate.pro/webuse](https://impersonate.pro/webuse).

## Why

`curl_cffi` can be a good starting point for writing a crawler or scraper, it's fairly
easy to use AI to generate a decent script. But keeping it running means
handling blocked requests, sessions, dynamic pages, broken extraction, and changes
to the target site.

If you're writing a lot crawlers, soon you or your assistant will create a home-made
framework across different projects for these common tasks.
`webuse` is here to be the framework you has been or will be building, along with
a harness on how to write crawlers on top of the framework, and finally
the process manager and metrics dashboard.

Besides, you can also bring your existing scripts to the orchestrator, and it can
also manage the process for you.


> [!WARNING]
> `webuse` is intended for programmers, not non-technical users. At least you should
> know what the http protocol is.
>
> Even the harness part requires you understand what the model generates. Unlike other
> AI projects, we don't promise magic. Code is still code, not plain English.


## Install

Requires Python 3.11 or newer. Add the Python package to your project:

```bash
pip install webuse
```

## Quick start

Inspect a page from the command line:

```bash
webuse fetch https://example.com --css "title"
```

Create a project and generate a starter spider:

```bash
webuse create my_project
cd my_project
webuse gen books https://books.toscrape.com/
```

This generates three main files. `webuse.yaml` holds project defaults and
registers the spider:

```yaml
name: my_project
user_agent: chrome
robots_txt: true
llm: {}
concurrency:
  limit: 5
  per_domain: 1
log:
  level: info
  file: stderr
  append: true
spiders:
  books:
    path: spiders/books.py
```

`spiders/books.yaml` defines the starting URL, follow rules, extraction, and
pipelines. The starter follows links on the same domain and extracts page titles:

```yaml
name: books
start_urls:
  - https://books.toscrape.com/
allowed_domains:
  - books.toscrape.com
max_depth: 1
pages:
  default:
    follow:
      - css: a
        same_domain: true
    extract:
      books:
        fields:
          title: title
items:
  pipelines:
    default:
    - class: spiders.books.CleanBookPipeline
    - type: jsonl
      path: output.jsonl
```

`spiders/books.py` provides the item model, a cleanup pipeline you can customize,
and the spider class that loads the YAML:

```python
import webuse
from pydantic import BaseModel, Field


class BookItem(BaseModel):
    title: str
    price: str = ""
    availability: str = Field(
        default="", description="Raw availability text from the listing page."
    )


class CleanBookPipeline(webuse.ItemPipeline):
    def process_item(self, item: BookItem):
        return item


class BooksSpider(webuse.Spider):
    spider_config_path = "spiders/books.yaml"
    item_model = BookItem
```

Run a small crawl from `my_project/`:

```bash
webuse crawl --spider books --max-requests 3 -o books.jsonl
```

Edit the generated files in `spiders/` to define what to follow and extract.
You can write them yourself or use a coding agent with the
[Webuse crawler skill](ui/skills/webuse-crawlers/SKILL.md). See the
[quick-start guide](docs/src/content/docs/user-guide/quick-start.md) for examples.

To use the local Chat, code editor, and dashboard:

```bash
webuse serve
```

The packaged UI opens at `http://127.0.0.1:2951/` and requires Node.js 22.19+.
Configure a streaming, tool-capable OpenAI-compatible model in Settings to use
Chat. Project files and run data stay on your machine; no Webuse Cloud account
is required. The CLI examples above require neither Node.js nor an LLM.

## Webuse Cloud

Webuse Cloud is the planned managed environment for running crawlers in
production, with isolated workspaces, proxies, hosted browsers, CAPTCHA solving,
Defuddle-based HTML-to-Markdown extraction, and an integrated LLM API. Monitoring,
streaming logs, failure diagnosis, and data checks are also planned.

The goal is to bring existing Scrapy projects or other crawler code with minimal
changes, or deploy a crawler built locally. The Webuse framework will be optional,
with portable projects, downloadable data, and support for your own providers.
Cloud deployment and these managed services are not implemented in this checkout.

Learn more at [impersonate.pro/webuse](https://impersonate.pro/webuse).

## Development and contributing

Use Python 3.11+, uv, and Node.js 22.19+ with npm. From the repository root:

```bash
uv sync --extra dev
cd ui
npm ci
npm run dev
```

Run Python checks from the repository root:

```bash
uv run python3 -m compileall src tests
uv run pytest -q
```

Run UI checks from `ui/`:

```bash
npm run typecheck
npm test
npm run build
```

Bug reports, documentation improvements, examples, and focused pull requests are
welcome. Include reproduction steps for bugs, update relevant docs, and run the
checks affected by your change. See [local UI setup](ui/README.md),
[docs development](docs/README.md), and
[release packaging](docs/src/content/docs/advanced/package-release.md) for details.



## Documentation and development

- [Documentation index](docs/src/content/docs/index.md)
- [Build and preview docs](docs/README.md)
- [Local dashboard setup](ui/README.md)
- [Comprehensive examples](examples/)

## One more thing

We have a rust prototype of webuse, feel free to try it out.

## License

MIT.
