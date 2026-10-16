---
title: Signing & CAPTCHAs
description: Use existing signals to add request signatures, proxy settings, and CAPTCHA solutions.
---

Some sites require a signed header or a CAPTCHA solution before they return data.
Use Webuse's existing [signals](../../references/signals/) to prepare these requests:

- `request_before_downloader` receives the mutable `request` before downloading.
- `response_received` receives `response` and `request` before parsing.

These signals are available in ordinary sync/async crawls and agentic crawls.
Standalone `Client` calls do not emit crawl signals; prepare their request
arguments directly.

## Add a signing header

Create a project and a Python spider:

```bash
webuse create signed_project
cd signed_project
webuse gen protected https://api.example.com/items --python-only
```

Replace `spiders/protected.py` with the following example. The URL, header names,
and signing algorithm are illustrative: use the target API's actual contract.
This example signs a GET request without a body or separate `params` options.

```python
import hashlib
import hmac
import os
import time
from urllib.parse import urlsplit

from webuse import SignalBus, Spider


def sign_request(request):
    url = urlsplit(request.url)
    if url.scheme != "https" or url.netloc != "api.example.com":
        return

    timestamp = str(int(time.time()))
    target = url.path or "/"
    if url.query:
        target += "?" + url.query
    message = f"{request.method.upper()}\n{target}\n{timestamp}"
    signature = hmac.new(
        os.environ["TARGET_SIGNING_KEY"].encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    headers = dict(request.options.headers or {})
    headers.update({"X-Timestamp": timestamp, "X-Signature": signature})
    request.options.headers = headers
    request.options.allow_redirects = False


class ProtectedSpider(Spider):
    name = "protected"
    start_urls = ["https://api.example.com/items"]
    allowed_domains = {"api.example.com"}

    def __init__(self, **overrides):
        super().__init__(**overrides)
        if self.signals is None:
            self.signals = SignalBus()
        self.signals.connect("request_before_downloader", sign_request)

    def parse(self, response):
        response.raise_for_status()
        return response.json()
```

Supply `TARGET_SIGNING_KEY` in the crawler process's environment, then run from
the project directory:

```bash
webuse crawl --spider protected -o protected.jsonl
```

The hook preserves other request headers and reads the secret at runtime. Do not
put the key in source files, YAML, prompts, or logs. The request sends the signature,
not the signing key. Each spider instance creates its own bus unless one is supplied.

For body signatures, serialize the body once, sign those bytes, and send the same
bytes through `request.options.data`. Include query parameters in the signature
exactly as required by the target.

The signal runs before downloading, but a request can still wait for a worker or
per-domain slot afterward. It does not run again for curl_cffi's internal
redirects or transport retries. Avoid enabling automatic retries for signatures
that must be regenerated per transmission; handle redirects explicitly when a new
URL needs a new signature. Very short-lived signatures may require a custom
client that signs immediately before sending.

## Attach a CAPTCHA solution before downloading

If you already know the challenge parameters, an async pre-download handler can
await a solver and attach its result. Use `AsyncSpider` or `acrawl()` for an async
handler; sync crawls reject awaitables.

The following snippet assumes a project-owned `captcha_service.py` module with
an async `solve_token(page_url, site_key, proxy, user_agent)` function returning
a token string. This is an adapter you supply for your chosen solver, not a
built-in Webuse API. Implement its HTTP calls with curl_cffi, read credentials
from runtime configuration, and bound polling time and paid attempts.

```python
import os
from urllib.parse import urlsplit

from webuse import AsyncSpider, SignalBus

from captcha_service import solve_token


async def attach_captcha(request):
    url = urlsplit(request.url)
    if url.scheme != "https" or url.netloc != "protected.example.com":
        return

    proxy = os.environ.get("TARGET_PROXY_URL")
    user_agent = "ExampleCrawler/1.0"
    token = await solve_token(
        page_url=request.url,
        site_key=os.environ["TARGET_CAPTCHA_SITE_KEY"],
        proxy=proxy,
        user_agent=user_agent,
    )
    if not token:
        raise RuntimeError("CAPTCHA solver returned no token")

    headers = dict(request.options.headers or {})
    headers.update({"User-Agent": user_agent, "X-Captcha-Token": token})
    request.options.headers = headers
    request.options.proxy = proxy
    request.options.allow_redirects = False


class ProtectedSpider(AsyncSpider):
    name = "protected"
    start_urls = ["https://protected.example.com/items"]
    allowed_domains = {"protected.example.com"}

    def __init__(self, **overrides):
        super().__init__(**overrides)
        if self.signals is None:
            self.signals = SignalBus()
        self.signals.connect("request_before_downloader", attach_captcha)

    def parse(self, response):
        response.raise_for_status()
        return response.json()
```

Use this as an alternative `spiders/protected.py` in the project above. The same
`webuse crawl --spider protected` command detects and awaits the async spider.
For the function API, connect the handler to a `SignalBus` and pass it as
`signals=signals` to `await acrawl(...)`.

`X-Captcha-Token` is an illustrative target-site header. Many sites instead require
a form submission, JSON field, cookie, or browser interaction. Match the target's
actual flow; obtaining a solver token alone does not establish an accepted session.
This example solves once per matching request, so keep its scope narrow.

When a challenge is bound to a proxy IP, cookies, or user agent, preserve that
identity from challenge acquisition through submission and resource access.
Keep the solver API's credentials on its own connection. Async handlers may run
concurrently; coordinate any shared session refresh rather than solving the same
challenge repeatedly.

## When the response contains the challenge

`response_received` lets you inspect the response, including challenge HTML served
with HTTP 200. However, engines ignore signal handler return values: returning
a new request or response does not replace the download or schedule a retry.

There is currently no built-in "solve and retry this request" signal operation.
Returning the same request from a parse callback can also encounter normal queue
deduplication. For a multi-step flow, write explicit project code using a shared
`Client` or `AsyncClient` to acquire the challenge, submit its solution, and fetch
the resource, with a bounded attempt count. Only extract records after verifying
that the resource was actually returned.

