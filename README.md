# GetKit

GetKit is a small scraping toolkit built around `curl_cffi`.


`getkit` is part of the impersonate suite:

- `curl_cffi`
- `curl-impersonate`
- `impers`
- `seekit`, 
- [`getkit`](https://github.com/riverside-ai/getkit), this one
- [impersonate.pro](https://impersonate.pro), commercial support and getkit cloud hosting.

## Features

Why yet another scraping library?

- We need to build tools for both human and agents.
- A comprehensive CLI is crucial for agents like OpenClaw, so we offer it.
- You can define most of your tasks with yaml, instead of code, which is another great thing for agents and non-technical users.
- Even better, there is an simple GUI for you to generate crawling tasks.
- Writing and maintaining XPath/CSS is fragile and frustrating, these tedious work should be handed over to AI.
- `getkit` is created by the author of `curl_cffi`, the integration and support is much better.
- Last but not least, Claude just offered 6 months of free Claude Code Max for me as an open source contributor, I thought I should make full use of it. Kudos to Claude.

Here is a comparison in tables:

||scrapy|aiohttp|httpx|pycurl|getkit|
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
pip install getkit
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
import getkit

response = getkit.get("https://example.com", impersonate="chrome")
print(response.status_code)
print(response.text)
```

### Parse HTML

```python
import getkit

response = getkit.get("https://example.com")

title = response.css_first("title")
print(title.text() if title else None)

for link in response.css("a"):
    print(link.attr("href"), link.text())
```

XPath is also available:

```python
product = response.xpath_first("//article[@class='product']")
```

### Smart selectors

Smart selectors store prompt-based matches in `.getkit/selectors.json`.

```python
import getkit

response = getkit.get("https://example.com/products")
match = response.smart("primary product link")

print(match.text())
print(match.attr("href"))
```

### Persistent clients

Use `Client` or `AsyncClient` when you want connection reuse and shared defaults.

```python
import getkit

with getkit.Client(impersonate="chrome", timeout=20) as client:
    page1 = client.get("https://example.com")
    page2 = client.get("https://example.com/about")
```

Async:

```python
import asyncio
import getkit


async def main():
    async with getkit.AsyncClient(impersonate="chrome") as client:
        response = await client.get("https://example.com")
        print(response.status_code)


asyncio.run(main())
```

### Crawl from seed URLs

`getkit.crawl` starts from one or more seed URLs, extracts new URLs, filters them, and pushes them through an internal queue.

```python
import getkit

result = getkit.crawl(
    ["https://example.com"],
    follow=getkit.FollowRule(css="a", same_domain=True),
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

Async crawling:

```python
import asyncio
import getkit


async def main():
    result = await getkit.acrawl(
        ["https://example.com"],
        follow=getkit.FollowRule(css="a", same_domain=True),
        extract={"title": "h1"},
        max_depth=2,
        concurrency=10,
    )
    print(result.items)


asyncio.run(main())
```

### WebSockets

Sync:

```python
import getkit

with getkit.ws_connect("wss://echo.websocket.events") as ws:
    ws.send_text("hello")
    print(ws.recv_text())
```

Async:

```python
import asyncio
import getkit


async def main():
    ws = await getkit.aws_connect("wss://echo.websocket.events")
    await ws.send_json({"hello": "world"})
    print(await ws.recv_text())
    await ws.close()


asyncio.run(main())
```

## CLI

Installing from PyPI also installs the `getkit` command.

### Fetch a page

```bash
getkit fetch https://example.com
```

Extract with CSS:

```bash
getkit fetch https://example.com --css "a"
```

Extract with XPath:

```bash
getkit fetch https://example.com --xpath "//title"
```

Use a smart selector:

```bash
getkit fetch https://example.com/products --smart "primary product link"
```

Print response metadata:

```bash
getkit fetch https://example.com --meta
```

### Crawl from the terminal

```bash
getkit crawl https://example.com \
  --follow-css "a" \
  --same-domain \
  --extract-css "title=h1" \
  --max-depth 1
```

Run the async crawl path:

```bash
getkit crawl https://example.com \
  --follow-css "a" \
  --same-domain \
  --extract-css "title=h1" \
  --async
```

### Config file

You can move fetch or crawl settings into a YAML or TOML config file.

Example YAML:

```yaml
crawl:
  seeds:
    - https://example.com
  follow_css:
    - a
  same_domain: true
  extract:
    title: h1
  max_depth: 1
  concurrency: 5
```

Run it with:

```bash
getkit crawl --config getkit.yaml
```
