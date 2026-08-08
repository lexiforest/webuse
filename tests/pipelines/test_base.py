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


def test_spider_pipelines_process_and_drop_items():
    events = []

    class CleanPipeline(Pipeline):
        def open_spider(self):
            events.append("open")

        def process_item(self, item):
            return item.model_copy(update={"title": item.title.upper()})

        def close_spider(self):
            events.append("close")

    class DropPageOnePipeline(Pipeline):
        def process_item(self, item):
            if item.title == "PAGE ONE":
                raise DropItem("duplicate")
            return item

    class PipelineSpider(Spider):
        start_urls = ["https://example.com"]
        follow = [FollowRule(css="a.next", same_domain=True)]
        extract = {"title": "h1"}
        item_model = SampleItem
        max_depth = 1
        pipelines = [CleanPipeline(), DropPageOnePipeline()]

    result = PipelineSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="HOME")]
    assert events == ["open", "close"]


def test_spider_pipelines_require_pydantic_items():
    class PipelineSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        pipelines = [Pipeline()]

    with pytest.raises(webuse.PipelineError, match="BaseModel"):
        PipelineSpider().run(client=FakeClient())


def test_project_level_jsonl_pipeline_from_webuse_toml(tmp_path):
    (tmp_path / "webuse.toml").write_text(
        """
[items.pipelines]
default = [
  { type = "jsonl", path = "items.jsonl" },
]
""",
        encoding="utf-8",
    )

    class ProjectSpider(Spider):
        project_dir = tmp_path
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())
    lines = (tmp_path / "items.jsonl").read_text(encoding="utf-8").splitlines()

    assert result.items == [SampleItem(title="Home")]
    assert lines == ['{"title": "Home", "source": ""}']


def test_spider_does_not_search_upwards_for_project_config(tmp_path, monkeypatch):
    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    (project / "webuse.toml").write_text(
        """
[items.pipelines]
default = [
  { type = "jsonl", path = "items.jsonl" },
]
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(nested)

    class ProjectSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())

    assert result.items == [{"title": "Home"}]
    assert not (project / "items.jsonl").exists()


def test_spider_pipelines_take_precedence_over_project_config(tmp_path):
    (tmp_path / "webuse.toml").write_text(
        """
[items.pipelines]
default = [
  { type = "jsonl", path = "project.jsonl" },
]
""",
        encoding="utf-8",
    )

    class OverridePipeline(Pipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "spider"})

    class OverrideSpider(Spider):
        project_dir = tmp_path
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem
        pipelines = [OverridePipeline()]

    result = OverrideSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home", source="spider")]
    assert not (tmp_path / "project.jsonl").exists()


def test_project_level_custom_pipeline_imports_from_project_dir(tmp_path):
    (tmp_path / "project_pipelines.py").write_text(
        """
class MarkPipeline:
    def process_item(self, item):
        return item.model_copy(update={"source": "project"})
""",
        encoding="utf-8",
    )
    (tmp_path / "webuse.toml").write_text(
        """
[items.pipelines]
default = [
  { class = "project_pipelines.MarkPipeline" },
]
""",
        encoding="utf-8",
    )

    class ProjectSpider(Spider):
        project_dir = tmp_path
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home", source="project")]


def test_run_pipeline_override_takes_precedence(tmp_path):
    class ClassPipeline(Pipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "class"})

    class RunPipeline(Pipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "run"})

    class OverrideSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"title": "h1"}
        item_model = SampleItem
        pipelines = [ClassPipeline()]

    result = OverrideSpider().run(client=FakeClient(), pipelines=[RunPipeline()])

    assert result.items == [SampleItem(title="Home", source="run")]
