---
title: "Webuse vs Scrapy"
---

## Comparing webuse and scrapy

`webuse` borrows the sprites of Scrapy that make larger scraping projects pleasant:
spiders, generated spider files, item pipelines, feed-like output, and lifecycle
signals. It does not try to clone Scrapy's full downloader middleware stack.

With webuse, you don't need to battle with twisted anymore, it's only the standard lib.

### Configuration

webuse uses `webuse.yaml` for project settings, and an explicit `spiders` section.
Crawl-specific settings live inline under `spiders.<name>`, on the spider class,
or in a per-spider YAML file referenced from the root config.

The CLI reads the root project config (`webuse.yaml`, or
`webuse.toml`) from the supplied directory. It does not accept a config file
as the crawl target or search upward through parent directories.

### settings.py

In webuse, `webuse.yaml` covers the role of Scrapy's project settings.

| Scrapy setting | webuse equivalent |
| --- | --- |
| `BOT_NAME` | `name` |
| `USER_AGENT` | `user_agent` |
| `SPIDER_MODULES` / `NEWSPIDER_MODULE` | explicit `spiders` entries in `webuse.yaml` |
| `ROBOTSTXT_OBEY` | `robots_txt: true` |
| `CONCURRENT_REQUESTS` | `concurrency.limit` |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | `concurrency.per_domain` |
| `ITEM_PIPELINES` | `items.pipelines.default` in each spider config |
| `FEEDS` | `crawl -o` or an explicit item pipeline |
| `DOWNLOAD_MIDDLEWARES` | signals, request options, and project code |
| retry, proxies, TLS, cookies, redirects | `curl_cffi` request options |

Example project config:

```yaml
name: my_project
user_agent: Mozilla/5.0 MyProject/1.0
robots_txt: true
concurrency:
  limit: 16
  per_domain: 1
log:
  level: info
  file: stderr
  append: true
```

Item pipelines belong in each spider's YAML config:

```yaml
items:
  pipelines:
    default:
      - class: spiders.books.CleanBookPipeline
      - type: jsonl
        path: output.jsonl
```

### Commands

#### startproject

Scrapy:

```bash
scrapy startproject books_project
```

webuse:

```bash
webuse create books_project
```


#### genspider

Scrapy:

```bash
scrapy genspider books books.toscrape.com
```

webuse:

```bash
webuse create books_project
cd books_project
webuse gen books https://books.toscrape.com/
```

Generation requires an existing project and registers the new spider there.
YAML config with a Python module is the default output. Use `--python-only`
for a Python-only spider:

```bash
webuse gen quotes https://quotes.toscrape.com/ --python-only
webuse crawl --spider quotes -o quotes.jsonl
```

#### crawl and runspider

Scrapy:

```bash
scrapy crawl quotes
scrapy runspider quotes.py
```

webuse:

```bash
webuse crawl --spider quotes
```

If no directory is given, `webuse crawl` assumes the current directory. If
`--spider` is omitted, it runs all entries registered in the project's
`spiders` configuration.

### Spiders

Scrapy spiders use callback functions stored on request objects. webuse keeps
`RequestOptions` pure data and serializable. A follow-up request can carry a
`page_type`, and the spider maps that page type to a route:

```python
import webuse


class BooksSpider(webuse.Spider):
    start_urls = ["https://books.toscrape.com/"]
    routes = {"detail": "parse_detail"}

    def parse(self, response):
        for link in response.find_all(css="article.product_pod h3 a"):
            yield response.follow(link.attr("href"), page_type="detail")

    def parse_detail(self, response):
        yield {"title": response.find(css="h1").text()}
```

`Spider.parse` also has a default behavior: if the spider has an `extract`
mapping, the base method extracts items from it. Override `parse` for custom
logic.

For no-code spiders, the same page type is serializable in YAML. `pages` is
keyed by source page type, and follow rules set `page_type` for discovered
requests:

```yaml
pages:
  default:
    follow:
      - css: .product_pod h3 a
        page_type: detail
    extract:
      summaries:
        item_css: .product_pod
        fields:
          title:
            css: h3 a
            attr: title
  detail:
    extract:
      details:
        fields:
          title: h1
```

Unlike Scrapy item loaders, a single page type may run multiple named
extractors under `extract.<page_type>.items`. This lets one page emit, for
example, product summaries and category records without custom Python code.

## Items and Pipelines

webuse item pipelines process Pydantic `BaseModel` items. The project-level
pipeline config is the default for all spiders, unless `Spider.pipelines` is
set.

```python
import webuse
from pydantic import BaseModel


class CleanBookPipeline(webuse.ItemPipeline):
    def process_item(self, item: BaseModel):
        return item
```

Built-in pipelines include JSONL, CSV, SQLite, webhook delivery, and asset
download. `crawl -o` selects JSONL, CSV, or SQLite by file extension.

## State

Scrapy persists scheduler state in `requests.queue`, `requests.seen`, and
`spider.state` when jobs are paused. webuse exposes the queue and seen set as
interfaces and lets the CLI store them in Redis through `--state`:

```bash
webuse crawl books_project --spider books --state redis://localhost:6379/0
```

## Signals and Metrics

webuse uses a small `SignalBus` instead of a dependency-heavy dispatcher.
Signals are lifecycle hooks. Metrics are attached through `Metrics` and
the bundled `webuse.metrics` client. See [Signals](../../references/signals/).

## Scrapy project in webuse dashboard


