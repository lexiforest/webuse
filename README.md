# Webuse

Webuse is a small scraping toolkit built around `curl_cffi`.

`webuse` is part of the impersonate suite:

- [`curl-impersonate`](https://github.com/lexiforest/curl-impersonate), make curl impersonate browsers' tls/ja3 fingerprints.
- [`curl_cffi`](https://github.com/lexiforest/curl_cffi), Python binding for curl-impersonate.
- [`impers`](https://github.com/lexiforest/impers), Nodejs binding to curl-impersonate.
- [`webuse`](https://github.com/riverside-ai/webuse), this one
- [impersonate.pro](https://impersonate.pro), commercial support and webuse cloud hosting.

## Why

Why yet another scraping library?

- We need to build tools for both human and agents.
- A comprehensive CLI is crucial for agents like OpenClaw, so we offer it.
- You can define most of your tasks with yaml, instead of code, which is another great thing for agents and non-technical users.
- Even better, there is an simple GUI for you to generate scraping tasks.
- Writing and maintaining XPath/CSS is fragile and frustrating, these tedious work should be handed over to AI.
- `webuse` is created by the author of `curl_cffi`, the integration and support is much better.
- Last but not least, I have some extra Codex tokens, why not utilizing it?

Here is a comparison in tables:

||scrapy|aiohttp|httpx|pycurl|webuse|
|---|---|---|---|---|---|
|http/2|❌|❌|✅|✅|✅|
|http/3|❌|❌|❌|☑️<sup>1</sup>|✅<sup>2</sup>|
|sync|✅|❌|✅|✅|✅|
|async|❌|✅|✅|❌|✅|
|LLM selectors|❌|✅|❌|❌|✅|
|native cli|❌|❌|❌|❌|✅|
|tls/h2/h3 fingerprints|❌|❌|❌|❌|✅|
|speed|🐇|🐇🐇|🐇|🐇🐇|🐇🐇|

What about dynamic websites?

Well, that's what we are building next. Playwright and puppeteer is real solution, and
headless real browsers are just too heavy to be agents. We are building a new lightweight
browser-ish executor, stay tuned.

## Install

Install from PyPI:

```bash
pip install webuse
```

Install from source:

```bash
pip install .
```

For development:

```bash
python -m pip install -e .[dev]
```

## Usage

### Quick HTTP request

```python
import webuse

response = webuse.get("https://example.com", impersonate="chrome")
print(response.status_code)
print(response.text)
```

### Parse HTML

```python
import webuse

response = webuse.get("https://example.com")

title = response.css_first("title")
print(title.text() if title else None)

for link in response.css("a"):
    print(link.attr("href"), link.text())
```

XPath is also available:

```python
product = response.xpath_first("//article[@class='product']")
```

Regex extraction follows the same list/first pattern:

```python
slugs = response.re(r"/products/([a-z-]+)")
first_slug = response.re_first(r"/products/([a-z-]+)")
```

### Smart extraction

Smart extraction asks the model for all matches:

```python
import webuse

response = webuse.get("https://example.com/products")
titles = response.smart("All product titles")
print(titles)
```

Use `smart_first()` when you only want the first match:

```python
title = response.smart_first("First product title")
```

If you want a prompt translated into a cached selector, enable XPath
translation:

```python
import webuse

response = webuse.get("https://example.com/products")
match = response.smart_first("primary product link", translate_xpath=True)

print(match.text())
print(match.attr("href"))
```

### Persistent clients

Use `Client` or `AsyncClient` when you want connection reuse and shared defaults.

```python
import webuse

with webuse.Client(impersonate="chrome", timeout=20) as client:
    page1 = client.get("https://example.com")
    page2 = client.get("https://example.com/about")
```

Async:

```python
import asyncio
import webuse


async def main():
    async with webuse.AsyncClient(impersonate="chrome") as client:
        response = await client.get("https://example.com")
        print(response.status_code)


asyncio.run(main())
```

### Crawl from seed URLs

`webuse.crawl` starts from one or more seed URLs, extracts new URLs, filters them, and pushes them through an internal queue.

```python
import webuse

result = webuse.crawl(
    ["https://example.com"],
    follow=webuse.FollowRule(css="a", same_domain=True),
    extract={
        "title": "h1",
        "next_link": {"css": "a.next", "attr": "href"},
    },
    max_depth=1,
    concurrency=5,
)

print(result.items)
print(result.stats)
```

Class-based spiders are a thin wrapper around the same crawl API:

```python
import webuse


class BooksSpider(webuse.Spider):
    start_urls = ["https://books.toscrape.com/"]
    allowed_domains = {"books.toscrape.com"}
    max_depth = 1

    follow = [
        webuse.FollowRule(css=".next a", same_domain=True),
    ]

    extract = {
        "item_css": ".product_pod",
        "fields": {
            "title": {"css": "h3 a", "attr": "title"},
            "price": ".price_color",
        },
    }


result = BooksSpider().run()
print(result.items)
```

The default `Spider.parse()` extracts items from `extract`. If you define your own
`parse()` method, it replaces that default extraction behavior. Custom `parse()`
methods may yield item dictionaries or follow-up requests:

```python
def parse(self, response):
    yield {"title": response.css_first("h1").text()}
    yield response.follow("/next", options=webuse.RequestOptions(timeout=5))
```

For multi-step crawls, use serializable request categories instead of callback
functions:

```python
class BooksSpider(webuse.Spider):
    start_urls = ["https://example.com/books"]
    routes = {"detail": "parse_detail"}

    def parse(self, response):
        for link in response.links("a.book"):
            yield response.follow(link, category="detail")

    def parse_detail(self, response):
        yield {"title": response.css_first("h1").text()}
```

Spiders can also run item pipelines. Pipeline items are Pydantic `BaseModel` instances; set `Spider.item_model` to convert extracted dictionaries before they enter the pipeline chain. `Spider.pipelines` overrides project defaults from `[items.pipelines]` in `webuse.toml`.

```python
from pydantic import BaseModel


class BookItem(BaseModel):
    title: str


class BooksSpider(webuse.Spider):
    start_urls = ["https://books.toscrape.com/"]
    extract = {"title": "h1"}
    item_model = BookItem
    pipelines = [
        webuse.JsonlPipeline("books.jsonl"),
        webuse.SQLitePipeline("books.sqlite"),
    ]
```

Async crawling:

```python
import asyncio
import webuse


async def main():
    result = await webuse.acrawl(
        ["https://example.com"],
        follow=webuse.FollowRule(css="a", same_domain=True),
        extract={"title": "h1"},
        max_depth=2,
        concurrency=10,
    )
    print(result.items)


asyncio.run(main())
```

Async spiders use `AsyncSpider` and keep the same `run()` entrypoint:

```python
import asyncio
import webuse


class BooksSpider(webuse.AsyncSpider):
    start_urls = ["https://books.toscrape.com/"]
    extract = {"title": "h1"}


async def main():
    result = await BooksSpider().run()
    print(result.items)


asyncio.run(main())
```

### WebSockets

Sync:

```python
import webuse

with webuse.ws_connect("wss://echo.websocket.events") as ws:
    ws.send_text("hello")
    print(ws.recv_text())
```

Async:

```python
import asyncio
import webuse


async def main():
    ws = await webuse.aws_connect("wss://echo.websocket.events")
    await ws.send_json({"hello": "world"})
    print(await ws.recv_text())
    await ws.close()


asyncio.run(main())
```

## CLI

Installing from PyPI also installs the `webuse` command.

### Fetch a page

```bash
webuse fetch https://example.com
```

Extract with CSS:

```bash
webuse fetch https://example.com --css "a"
```

Extract with XPath:

```bash
webuse fetch https://example.com --xpath "//title"
```

Use smart extraction:

```bash
webuse fetch https://example.com/products --smart "primary product link"
```

Add `--first` when you want one value instead of all matches.

Print response metadata:

```bash
webuse fetch https://example.com --meta
```

### Run a spider project

```bash
webuse crawl books_project --spider books -o books.jsonl
```

### Run an ad hoc crawl

Use `--item-css` to select each repeated record container, then extract fields
relative to that container. When `--item-css` is omitted, fields are extracted
from the whole document.

```bash
webuse crawl https://books.toscrape.com/ \
  --item-css ".product_pod" \
  --css title="h3 a" \
  --attr title=title \
  --css price=".price_color" \
  --follow-css ".next a" \
  --same-domain \
  --max-depth 49 \
  -o books.jsonl
```

### Config file

You can move fetch settings into a TOML or YAML config file.

Example TOML:

```toml
[fetch]
url = "https://example.com"
css = "h1"
```

Run it with:

```bash
webuse fetch --config webuse.toml
```

For crawl tasks, YAML spider configs use the same item-scoped extraction model
as the CLI:

```yaml
name: books
start_urls:
  - https://books.toscrape.com/
allowed_domains:
  - books.toscrape.com
max_depth: 1
follow:
  - css: .next a
    same_domain: true
extract:
  item_css: .product_pod
  fields:
    title:
      css: h3 a
      attr: title
    price: .price_color
```

Run it with:

```bash
webuse crawl books.yaml -o books.jsonl
```
