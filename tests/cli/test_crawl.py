import csv
import json
import sqlite3

import pytest

from webuse import cli
from webuse.models import CrawlResult, CrawlStats
from webuse.http import Response


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("extension", ["jsonl", "csv", "sqlite"])
def test_output_streams_processed_items_across_spiders(
    tmp_path, monkeypatch, asynchronous, extension
):
    import importlib
    from pydantic import BaseModel
    from webuse import AsyncSpider, Spider
    from webuse.exceptions import DropItem
    from webuse.pipelines import ItemPipeline
    from webuse.spider import aio, sync

    command = importlib.import_module("webuse.cli.crawl")
    (tmp_path / "webuse.yaml").write_text(
        "spiders:\n  first: first.py\n  second: second.py\n"
    )
    monkeypatch.chdir(tmp_path)
    output = tmp_path / f"items.{extension}"

    class Item(BaseModel):
        title: str

    class Clean(ItemPipeline):
        def process_item(self, item):
            if item.title == "drop":
                raise DropItem("excluded")
            return item.model_copy(update={"title": item.title.upper()})

    class Example(AsyncSpider if asynchronous else Spider):
        item_model = Item
        pipelines = [Clean()]

        def parse(self, response):
            return [{"title": response.text}, {"title": "drop"}]

    monkeypatch.setattr(command, "_load_spider", lambda *args, **kwargs: Example())
    processed_count = 0

    def read_records():
        if extension == "jsonl":
            return [json.loads(line) for line in output.read_text().splitlines()]
        if extension == "csv":
            with output.open() as file:
                return list(csv.DictReader(file))
        with sqlite3.connect(output) as connection:
            return [
                json.loads(row[0])
                for row in connection.execute("SELECT data FROM items ORDER BY id")
            ]

    def check_output(parsed):
        nonlocal processed_count
        processed_count += 1
        assert read_records() == [{"title": "KEPT"}] * processed_count
        return CrawlResult(items=parsed.items)

    def fake_crawl(seeds, **options):
        return check_output(options["extract"](Response(content=b"kept")))

    async def fake_acrawl(seeds, **options):
        from webuse.extract import ParseResult

        parsed = await options["extract"](Response(content=b"kept"))
        return check_output(ParseResult([item async for item in parsed.items]))

    monkeypatch.setattr(sync, "crawl", fake_crawl)
    monkeypatch.setattr(aio, "acrawl", fake_acrawl)
    args = ["crawl", "-o", str(output)]
    if asynchronous:
        args.append("--async")
    assert cli.main(args) == 0
    assert read_records() == [{"title": "KEPT"}, {"title": "KEPT"}]


@pytest.mark.parametrize("base", ["Spider", "AsyncSpider"])
@pytest.mark.parametrize("explicit_class", [False, True])
@pytest.mark.parametrize("command", [[], ["--async"]])
def test_crawl_loads_both_spider_types(tmp_path, capsys, base, explicit_class, command):
    path = tmp_path / "example.py"
    run_prefix = "async " if base == "AsyncSpider" else ""
    path.write_text(
        "from webuse.spider import Spider, AsyncSpider\n"
        "from webuse.spider.base import BaseSpider\n"
        "from webuse.models import CrawlResult, CrawlStats\n\n"
        f"class ExampleSpider({base}):\n"
        f"    {run_prefix}def run(self, **overrides):\n"
        "        return CrawlResult(items=[{'title': 'Loaded'}], stats=CrawlStats())\n"
    )
    target = f"{path}:ExampleSpider" if explicit_class else str(path)
    (tmp_path / "webuse.yaml").write_text(f"spiders:\n  example: '{target}'\n")
    output = tmp_path / "items.jsonl"

    assert (
        cli.main(
            ["crawl", str(tmp_path), "--spider", "example", "-o", str(output), *command]
        )
        == 0
    )
    assert capsys.readouterr().out == ""
    assert output.read_text() == '{"title": "Loaded"}\n'


@pytest.mark.parametrize("explicit_class", [False, True])
def test_crawl_rejects_base_spider_as_execution_target(tmp_path, explicit_class):
    from webuse.cli.crawl import _load_spider

    path = tmp_path / "base_only.py"
    path.write_text("from webuse.spider.base import BaseSpider\n")
    target = f"{path}:BaseSpider" if explicit_class else str(path)

    with pytest.raises(SystemExit, match="webuse.Spider or webuse.AsyncSpider"):
        _load_spider(target, project_dir=tmp_path)


@pytest.mark.parametrize("command", [[], ["--async"]])
def test_project_request_limit_is_shared_across_spiders(tmp_path, monkeypatch, command):
    from webuse.spider import aio as aio_module, sync as sync_module

    config = tmp_path / "webuse.yaml"
    config.write_text(
        "spiders:\n  first:\n    start_urls: [https://example.com/first]\n"
        "  second:\n    start_urls: [https://example.com/second]\n"
        "  third:\n    start_urls: [https://example.com/third]\n"
    )
    observed = []

    def fake_crawl(start_urls, **options):
        observed.append((start_urls, options["max_requests"]))
        return CrawlResult(stats=CrawlStats(queued=1, fetched=1))

    async def fake_acrawl(start_urls, **options):
        return fake_crawl(start_urls, **options)

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)
    monkeypatch.setattr(aio_module, "acrawl", fake_acrawl)
    assert cli.main(["crawl", str(tmp_path), "--max-requests", "2", *command]) == 0
    assert observed == [
        (["https://example.com/first"], 2),
        (["https://example.com/second"], 1),
    ]


@pytest.mark.parametrize("command", [[], ["--async"]])
def test_request_limit_must_be_positive(command):
    with pytest.raises(SystemExit, match="must be positive"):
        cli.main(["crawl", "https://example.com", "--max-requests", "0", *command])


def test_crawl_command_runs_spider_name_from_project_to_output_file(
    cli_project, monkeypatch, capsys
):
    cli_project.write_default_spider()
    output = cli_project.root / "test.jsonl"
    monkeypatch.chdir(cli_project.root)

    code = cli.main(["crawl", "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "One"}\n'


def test_crawl_command_passes_attributes_to_spider(cli_project, monkeypatch, capsys):
    cli_project.write_default_spider(
        item_fields="genre: str\n    edition: str",
        run_body=(
            "return CrawlResult("
            "items=[Item(genre=self.genre, edition=self.edition)], "
            "stats=CrawlStats())"
        ),
    )
    output = cli_project.root / "test.jsonl"
    monkeypatch.chdir(cli_project.root)

    code = cli.main(
        [
            "crawl",
            "--spider",
            "books",
            "--attribute",
            "genre=history",
            "--attribute",
            "genre=fiction",
            "-a",
            "edition=first",
            "-o",
            str(output),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert (
        output.read_text(encoding="utf-8")
        == '{"genre": "fiction", "edition": "first"}\n'
    )


@pytest.mark.parametrize("command", [[], ["--async"]])
def test_crawl_command_uses_async_state(cli_project, monkeypatch, command):
    from webuse.cli import crawl as crawl_module
    from webuse.engine import AsyncMemoryRequestQueue, AsyncMemoryRequestSeen

    closed = []

    class Queue(AsyncMemoryRequestQueue):
        def __init__(self, key, *, redis_url):
            super().__init__()
            assert key.endswith(":requests:queue")

        async def aclose(self):
            closed.append("queue")

    class Seen(AsyncMemoryRequestSeen):
        def __init__(self, key, *, redis_url):
            super().__init__()

        async def aclose(self):
            closed.append("seen")

    monkeypatch.setattr(crawl_module, "AsyncRedisRequestQueue", Queue)
    monkeypatch.setattr(crawl_module, "AsyncRedisRequestSeen", Seen)
    cli_project.write_spider(
        """import webuse


class BooksSpider(webuse.AsyncSpider):
    pass
"""
    )
    monkeypatch.chdir(cli_project.root)

    assert (
        cli.main(
            [
                "crawl",
                "--spider",
                "books",
                *command,
                "--state",
                "redis://localhost:6379/0",
            ]
        )
        == 0
    )
    assert sorted(closed) == ["queue", "seen"]


def test_crawl_command_resolves_redis_state(monkeypatch):
    from webuse.cli import crawl as crawl_module

    class FakeRedisRequestQueue:
        def __init__(self, key, *, redis_url):
            self.key = key
            self.redis_url = redis_url

    class FakeRedisRequestSeen:
        def __init__(self, key, *, redis_url):
            self.key = key
            self.redis_url = redis_url

    monkeypatch.setattr(crawl_module, "RedisRequestQueue", FakeRedisRequestQueue)
    monkeypatch.setattr(crawl_module, "RedisRequestSeen", FakeRedisRequestSeen)

    options = crawl_module._state_options("redis://localhost:6379/0", target="books")

    assert options["request_queue"].__class__.__name__ == "FakeRedisRequestQueue"
    assert options["request_seen"].__class__.__name__ == "FakeRedisRequestSeen"
    assert options["request_queue"].key == "webuse:books:requests:queue"
    assert options["request_seen"].key == "webuse:books:requests:seen"
    assert options["request_queue"].redis_url == "redis://localhost:6379/0"


@pytest.mark.parametrize("command", [[], ["--async"]])
def test_request_budget_skips_loading_later_spiders(tmp_path, command):
    (tmp_path / "webuse.yaml").write_text(
        "spiders:\n  first: first.py\n  later: later.py\n"
    )
    (tmp_path / "first.py").write_text(
        "from webuse import Spider\n"
        "from webuse.models import CrawlResult, CrawlStats\n"
        "class First(Spider):\n"
        "    def run(self, **kwargs):\n"
        "        return CrawlResult(stats=CrawlStats(queued=1))\n"
    )
    (tmp_path / "later.py").write_text("raise AssertionError('must not load')\n")
    assert cli.main(["crawl", str(tmp_path), *command, "--max-requests", "1"]) == 0


def test_crawl_command_rejects_malformed_attribute(cli_project, monkeypatch):
    cli_project.write_spider(
        """import webuse


class BooksSpider(webuse.Spider):
    pass
"""
    )
    monkeypatch.chdir(cli_project.root)

    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", "--spider", "books", "--attribute", "missing-equals"])

    assert "KEY=VALUE" in str(exc.value)


def test_crawl_command_writes_csv_output_by_extension(cli_project, monkeypatch, capsys):
    cli_project.write_default_spider(
        item_fields="title: str\n    price: str",
        run_body='return CrawlResult(items=[Item(title="One", price="$1.00")], stats=CrawlStats())',
    )
    output = cli_project.root / "test.csv"
    monkeypatch.chdir(cli_project.root)

    code = cli.main(["crawl", "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8").splitlines() == [
        "title,price",
        "One,$1.00",
    ]


def test_crawl_command_writes_sqlite_output_by_extension(
    cli_project, monkeypatch, capsys
):
    cli_project.write_default_spider()
    output = cli_project.root / "test.sqlite"
    monkeypatch.chdir(cli_project.root)

    code = cli.main(["crawl", "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    with sqlite3.connect(output) as connection:
        rows = connection.execute("SELECT item_type, data FROM items").fetchall()
    assert rows == [("Item", '{"title": "One"}')]


def test_crawl_command_rejects_unknown_output_extension(cli_project, monkeypatch):
    cli_project.write_default_spider()
    monkeypatch.chdir(cli_project.root)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            ["crawl", "--spider", "books", "-o", str(cli_project.root / "test.json")]
        )

    assert "unsupported output extension" in str(exc.value)


def test_crawl_command_accepts_project_directory(tmp_path, cli_project, capsys):
    cli_project.write_default_spider(
        run_body='return CrawlResult(items=[Item(title="Directory One")], stats=CrawlStats())'
    )
    output = tmp_path / "test.jsonl"

    code = cli.main(
        ["crawl", str(cli_project.root), "--spider", "books", "-o", str(output)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Directory One"}\n'


def test_crawl_command_defaults_to_current_project(cli_project, monkeypatch, capsys):
    cli_project.write_default_spider(
        name="alpha.py",
        run_body='return CrawlResult(items=[Item(title="Alpha")], stats=CrawlStats())',
    )
    cli_project.write_default_spider(
        name="beta.py",
        run_body='return CrawlResult(items=[Item(title="Beta")], stats=CrawlStats())',
    )
    (cli_project.root / "webuse.toml").write_text(
        "\n".join(
            [
                'name = "project"',
                "",
                "[spiders.alpha]",
                'path = "spiders/alpha.py"',
                "",
                "[spiders.beta]",
                'path = "spiders/beta.py"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    output = cli_project.root / "test.jsonl"
    monkeypatch.chdir(cli_project.root)

    code = cli.main(["crawl", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8").splitlines() == [
        '{"title": "Alpha"}',
        '{"title": "Beta"}',
    ]


def test_crawl_command_does_not_search_upwards_for_project(cli_project, monkeypatch):
    nested = cli_project.root / "nested"
    nested.mkdir()
    cli_project.write_default_spider()
    monkeypatch.chdir(nested)

    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", "--spider", "books"])

    assert "cannot find webuse.yaml" in str(exc.value)


def test_crawl_command_runs_importable_spider_module(
    tmp_path, cli_project, monkeypatch, capsys
):
    cli_project.make_package()
    cli_project.write_default_spider(
        run_body='return CrawlResult(items=[Item(title="Module One")], stats=CrawlStats())'
    )
    output = tmp_path / "test.jsonl"
    monkeypatch.chdir(tmp_path)

    (cli_project.root / "webuse.toml").write_text(
        'spiders = {books = {module = "project.spiders.books"}}\n'
    )
    code = cli.main(
        ["crawl", str(cli_project.root), "--spider", "books", "-o", str(output)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Module One"}\n'


def test_crawl_command_runs_async_spider_target_to_output_file(
    cli_project, monkeypatch, capsys
):
    cli_project.write_default_spider(
        base="webuse.AsyncSpider",
        async_run=True,
        run_body='return CrawlResult(items=[Item(title="Async One")], stats=CrawlStats())',
    )
    output = cli_project.root / "test.jsonl"
    monkeypatch.chdir(cli_project.root)

    code = cli.main(["crawl", "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Async One"}\n'


def test_crawl_command_runs_registered_yaml_config_to_output_file(
    tmp_path, monkeypatch, capsys
):
    from webuse.spider import sync as sync_module

    config = tmp_path / "books.yaml"
    config.write_text(
        """
name: books
start_urls:
  - https://example.com/
pages:
  default:
    extract:
      page:
        fields:
          title: h1
""",
        encoding="utf-8",
    )
    output = tmp_path / "items.jsonl"

    def fake_crawl(start_urls, **options):
        assert start_urls == ["https://example.com/"]
        response = Response(
            url="https://example.com/",
            status_code=200,
            content=b"<html><body><h1>Home</h1></body></html>",
        )
        return CrawlResult(items=options["extract"](response).items, stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    (tmp_path / "webuse.yaml").write_text(
        "spiders:\n  books:\n    config: books.yaml\n"
    )
    code = cli.main(["crawl", str(tmp_path), "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Home", "_type": "page"}\n'


def test_crawl_command_runs_registered_config_from_directory_and_spider_name(
    tmp_path, monkeypatch, capsys
):
    from webuse.spider import sync as sync_module

    config = tmp_path / "books.yaml"
    config.write_text(
        """
name: books
start_urls:
  - https://example.com/
pages:
  default:
    extract:
      page:
        fields:
          title: h1
""",
        encoding="utf-8",
    )
    output = tmp_path / "items.jsonl"

    def fake_crawl(start_urls, **options):
        response = Response(
            url=start_urls[0],
            status_code=200,
            content=b"<html><body><h1>Home</h1></body></html>",
        )
        return CrawlResult(items=options["extract"](response).items, stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    (tmp_path / "webuse.yaml").write_text("spiders:\n  books: books.yaml\n")
    code = cli.main(["crawl", str(tmp_path), "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Home", "_type": "page"}\n'
