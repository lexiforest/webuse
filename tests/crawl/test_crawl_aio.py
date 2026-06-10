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


def test_acrawl_obeys_robots_txt():
    client = AsyncRobotsClient()

    async def run_crawl():
        return await acrawl(
            "https://example.com",
            client=client,
            follow=FollowRule(css="a.next", same_domain=True),
            extract={"title": "h1"},
            max_depth=1,
            robots_txt=True,
            user_agent="webuse-test",
        )

    result = asyncio.run(run_crawl())

    assert result.items == [{"title": "Home"}, {"title": "Allowed"}]
    assert result.stats.skipped_robots == 1
    assert "https://example.com/private" not in result.visited
    assert client.requests.count("https://example.com/robots.txt") == 1
