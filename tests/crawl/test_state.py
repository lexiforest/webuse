import asyncio
import csv
import hashlib
import json
import sqlite3

import pytest
import webuse
from webuse.crawl import (
    DefaultRequestHasher,
    FileRequestQueue,
    FileRequestSeen,
    RedisRequestQueue,
    RedisRequestSeen,
    canonical_request_url,
    acrawl,
    crawl,
)
from webuse.models import CrawlRequest, FollowRule
from webuse.pipelines import (
    AssetDownloadPipeline,
    DropItem,
    Pipeline,
    WebhookPipeline,
    resolve_pipeline,
)
from webuse.response import Response
from webuse.spider import AsyncSpider, Spider

from crawl_helpers import (
    AsyncFakeClient,
    AsyncRobotsClient,
    AssetItem,
    FakeAssetResponse,
    FakeAssetSession,
    FakeClient,
    FakeRedis,
    FakeWebhookResponse,
    FakeWebhookSession,
    QueryClient,
    RobotsClient,
    SampleItem,
)


def test_canonical_request_url_sorts_params_and_removes_tracking_params():
    assert (
        canonical_request_url("HTTPS://Example.COM/path?b=2&utm_source=x&a=1#frag")
        == "https://example.com/path?a=1&b=2"
    )

def test_default_request_hasher_uses_method_and_canonical_url_by_default():
    hasher = DefaultRequestHasher()
    first = CrawlRequest(
        url="https://example.com/path?b=2&utm_source=x&a=1", method="GET"
    )
    second = CrawlRequest(url="https://example.com/path?a=1&b=2", method="GET")
    third = CrawlRequest(url="https://example.com/path?a=1&b=2", method="POST")

    assert hasher.hash(first) == hasher.hash(second)
    assert hasher.hash(first) != hasher.hash(third)

def test_default_request_hasher_can_include_headers():
    plain = DefaultRequestHasher()
    with_headers = DefaultRequestHasher(include_headers=["Accept-Language"])
    first = CrawlRequest(
        url="https://example.com",
        options=webuse.RequestOptions(headers={"Accept-Language": "en"}),
    )
    second = CrawlRequest(
        url="https://example.com",
        options=webuse.RequestOptions(headers={"Accept-Language": "fr"}),
    )

    assert plain.hash(first) == plain.hash(second)
    assert with_headers.hash(first) != with_headers.hash(second)

def test_file_request_queue_persists_jsonl(tmp_path):
    path = tmp_path / "queue.jsonl"
    queue = FileRequestQueue(path)
    request = CrawlRequest(url="https://example.com", category="detail")

    queue.put(request)
    loaded = FileRequestQueue(path)

    assert loaded.pop() == request
    assert path.read_text(encoding="utf-8").count("\n") == 1

def test_file_request_seen_persists_jsonl(tmp_path):
    path = tmp_path / "seen.jsonl"
    seen = FileRequestSeen(path)

    assert seen.add("hash-1")
    assert not seen.add("hash-1")
    assert FileRequestSeen(path).contains("hash-1")
    assert path.read_text(encoding="utf-8").splitlines() == ['{"hash": "hash-1"}']

def test_redis_request_queue_and_seen_use_list_and_set():
    client = FakeRedis()
    queue = RedisRequestQueue("queue", client=client)
    seen = RedisRequestSeen("seen", client=client)
    request = CrawlRequest(url="https://example.com")

    queue.put(request)

    assert not queue.empty()
    assert queue.pop() == request
    assert queue.empty()
    assert seen.add("hash-1")
    assert not seen.add("hash-1")
    assert seen.contains("hash-1")
