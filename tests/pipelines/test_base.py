
import asyncio

import pytest
import webuse
from webuse.models import FollowRule
from webuse.pipelines import (
    DropItem,
    ItemPipeline,
)
from webuse.spider import Spider

from crawl_helpers import (
    AsyncFakeClient,
    FakeClient,
    SampleItem,
)


def test_spider_pipelines_process_and_drop_items():
    events = []

    class CleanPipeline(ItemPipeline):
        def open_spider(self):
            events.append("open")

        def process_item(self, item):
            return item.model_copy(update={"title": item.title.upper()})

        def close_spider(self):
            events.append("close")

    class DropPageOnePipeline(ItemPipeline):
        def process_item(self, item):
            if item.title == "PAGE ONE":
                raise DropItem("duplicate")
            return item

    class PipelineSpider(Spider):
        start_urls = ["https://example.com"]
        follow = [FollowRule(css="a.next", same_domain=True)]
        extract = {"default": {"page": {"fields": {"title": "h1"}}}}
        item_model = SampleItem
        max_depth = 1
        pipelines = [CleanPipeline(), DropPageOnePipeline()]

    result = PipelineSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="HOME")]
    assert events == ["open", "close"]


def test_spider_pipelines_require_pydantic_items():
    class PipelineSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"default": {"page": {"fields": {"title": "h1"}}}}
        pipelines = [ItemPipeline()]

    with pytest.raises(webuse.PipelineError, match="BaseModel"):
        PipelineSpider().run(client=FakeClient())


@pytest.mark.parametrize("with_project", [False, True])
def test_spider_config_jsonl_pipeline_from_toml(tmp_path, with_project):
    if with_project:
        (tmp_path / "webuse.toml").write_text('name = "test"\n')
    (tmp_path / "spiders").mkdir()
    (tmp_path / "spiders/books.toml").write_text(
        """
[items.pipelines]
default = [
  { type = "jsonl", path = "items.jsonl" },
]
""",
        encoding="utf-8",
    )

    class ProjectSpider(Spider):
        project_dir = tmp_path if with_project else None
        spider_config_path = tmp_path / "spiders/books.toml"
        start_urls = ["https://example.com"]
        extract = {"default": {"page": {"fields": {"title": "h1"}}}}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())
    base_dir = tmp_path if with_project else tmp_path / "spiders"
    lines = (base_dir / "items.jsonl").read_text(encoding="utf-8").splitlines()

    assert result.items == [SampleItem(title="Home")]
    assert lines == ['{"title": "Home", "source": ""}']


def test_spider_does_not_search_upwards_for_project_config(tmp_path, monkeypatch):
    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    (project / "webuse.toml").write_text(
        """
[concurrency]
limit = 1
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(nested)

    class ProjectSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"default": {"page": {"fields": {"title": "h1"}}}}
        item_model = SampleItem

    spider = ProjectSpider()
    assert spider._project_config() == (None, None)
    result = spider.run(client=FakeClient())

    assert result.items == [{"title": "Home", "_type": "page"}]


def test_spider_pipelines_take_precedence_over_spider_config(tmp_path):
    (tmp_path / "books.toml").write_text(
        """
[items.pipelines]
default = [
  { type = "jsonl", path = "configured.jsonl" },
]
""",
        encoding="utf-8",
    )

    class OverridePipeline(ItemPipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "spider"})

    class OverrideSpider(Spider):
        spider_config_path = tmp_path / "books.toml"
        start_urls = ["https://example.com"]
        extract = {"default": {"page": {"fields": {"title": "h1"}}}}
        item_model = SampleItem
        pipelines = [OverridePipeline()]

    result = OverrideSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home", source="spider")]
    assert not (tmp_path / "configured.jsonl").exists()


def test_spider_config_custom_pipeline_imports_from_project_dir(tmp_path):
    (tmp_path / "project_pipelines.py").write_text(
        """
class MarkPipeline:
    def process_item(self, item):
        return item.model_copy(update={"source": "project"})
""",
        encoding="utf-8",
    )
    (tmp_path / "webuse.toml").write_text('name = "test"\n')
    (tmp_path / "spiders").mkdir()
    (tmp_path / "spiders/books.toml").write_text(
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
        spider_config_path = tmp_path / "spiders/books.toml"
        start_urls = ["https://example.com"]
        extract = {"default": {"page": {"fields": {"title": "h1"}}}}
        item_model = SampleItem

    result = ProjectSpider().run(client=FakeClient())

    assert result.items == [SampleItem(title="Home", source="project")]


def test_run_pipeline_override_takes_precedence(tmp_path):
    class ClassPipeline(ItemPipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "class"})

    class RunPipeline(ItemPipeline):
        def process_item(self, item):
            return item.model_copy(update={"source": "run"})

    class OverrideSpider(Spider):
        start_urls = ["https://example.com"]
        extract = {"default": {"page": {"fields": {"title": "h1"}}}}
        item_model = SampleItem
        pipelines = [ClassPipeline()]

    result = OverrideSpider().run(client=FakeClient(), pipelines=[RunPipeline()])

    assert result.items == [SampleItem(title="Home", source="run")]


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("override", ["class", "run"])
def test_empty_pipeline_override_disables_spider_config(tmp_path, asynchronous, override):
    config_path = tmp_path / "books.yaml"
    config_path.write_text(
        "items:\n  pipelines:\n    default:\n      - type: jsonl\n        path: items.jsonl\n"
    )

    class Books(webuse.AsyncSpider if asynchronous else Spider):
        spider_config_path = config_path
        start_urls = ["https://example.com/"]
        extract = {"default": {"page": {"fields": {"title": "h1"}}}}
        item_model = SampleItem

    spider = Books()
    if override == "class":
        spider.pipelines = []
    options = {"pipelines": []} if override == "run" else {}
    result = (
        asyncio.run(spider.run(client=AsyncFakeClient(), **options))
        if asynchronous
        else spider.run(client=FakeClient(), **options)
    )
    assert result.items == [{"title": "Home", "_type": "page"}]
    assert not (tmp_path / "items.jsonl").exists()
