import csv
import asyncio
import hashlib
import json
import sqlite3

import pytest
import webuse
from pydantic import BaseModel
from webuse.crawl import (
    DefaultRequestHasher,
    FileRequestQueue,
    FileRequestSeen,
    MemoryRequestQueue,
    MemoryRequestSeen,
    RedisRequestQueue,
    RedisRequestSeen,
    canonical_request_url,
    acrawl,
    crawl,
)
from webuse.spider import AsyncSpider, Spider
from webuse.models import CrawlRequest, FollowRule
from webuse.pipelines import (
    AssetDownloadPipeline,
    DropItem,
    Pipeline,
    WebhookPipeline,
    resolve_pipeline,
)
from webuse.response import Response


PAGES = {
    "https://example.com/": b"""
    <html><body>
      <a class="next" href="/page-1">Page 1</a>
      <h1>Home</h1>
    </body></html>
    """,
    "https://example.com/page-1": b"""
    <html><body>
      <a class="next" href="/page-2">Page 2</a>
      <h1>Page One</h1>
    </body></html>
    """,
    "https://example.com/page-2": b"""
    <html><body><h1>Page Two</h1></body></html>
    """,
}


class FakeClient:
    def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        return Response(url=url, status_code=200, content=PAGES[url])

    def close(self):
        return None


class AsyncFakeClient:
    async def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        return Response(url=url, status_code=200, content=PAGES[url])


class SampleItem(BaseModel):
    title: str
    source: str = ""


class AssetItem(BaseModel):
    title: str = ""
    asset_urls: list[str] = []
    assets: list[dict[str, object]] = []


class FakeAssetResponse:
    def __init__(self, status_code=200, content=b"asset-bytes"):
        self.status_code = status_code
        self.content = content


class FakeAssetSession:
    def __init__(self, response=None):
        self.response = response or FakeAssetResponse()
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.response

    def close(self):
        self.closed = True


class FakeWebhookResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class FakeWebhookSession:
    def __init__(self, response=None):
        self.response = response or FakeWebhookResponse()
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.response

    def close(self):
        self.closed = True


ROBOTS_PAGES = {
    "https://example.com/": b"""
    <html><body>
      <a class="next" href="/allowed">Allowed</a>
      <a class="next" href="/private">Private</a>
      <h1>Home</h1>
    </body></html>
    """,
    "https://example.com/allowed": b"""
    <html><body><h1>Allowed</h1></body></html>
    """,
    "https://example.com/private": b"""
    <html><body><h1>Private</h1></body></html>
    """,
    "https://example.com/robots.txt": b"""
    User-agent: *
    Disallow: /private
    """,
}


class RobotsClient:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        self.requests.append(url)
        return Response(url=url, status_code=200, content=ROBOTS_PAGES[url])

    def close(self):
        return None


class AsyncRobotsClient:
    def __init__(self):
        self.requests = []

    async def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        self.requests.append(url)
        return Response(url=url, status_code=200, content=ROBOTS_PAGES[url])


class FakeRedis:
    def __init__(self):
        self.lists = {}
        self.sets = {}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def lpop(self, key):
        values = self.lists.setdefault(key, [])
        return values.pop(0) if values else None

    def llen(self, key):
        return len(self.lists.get(key, []))

    def delete(self, key):
        self.lists.pop(key, None)
        self.sets.pop(key, None)

    def sadd(self, key, value):
        values = self.sets.setdefault(key, set())
        if value in values:
            return 0
        values.add(value)
        return 1

    def sismember(self, key, value):
        return value in self.sets.get(key, set())


class QueryClient:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        _ = (method, kwargs)
        self.requests.append(url)
        return Response(
            url=url, status_code=200, content=b"<html><body><h1>Home</h1></body></html>"
        )

    def close(self):
        return None
