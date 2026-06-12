import sqlite3

import pytest

from webuse import cli
from webuse.models import CrawlResult, CrawlStats
from webuse.response import Response


def test_crawl_command_runs_standalone_url_with_multiple_fields(
    tmp_path, monkeypatch, capsys
):
    from webuse.spider import sync as sync_module

    output = tmp_path / "items.jsonl"

    def fake_crawl(start_urls, **options):
        response = Response(
            url=start_urls[0],
            status_code=200,
            content=b"<html><body><h1>Home</h1><p>$1.00</p></body></html>",
        )
        return CrawlResult(items=options["extract"](response), stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    code = cli.main(
        [
            "crawl",
            "https://example.com/",
            "--css",
            "title=h1",
            "--xpath",
            "price=//p",
            "-o",
            str(output),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Home", "price": "$1.00"}\n'


def test_crawl_command_runs_standalone_url_with_item_css(tmp_path, monkeypatch, capsys):
    from webuse.spider import sync as sync_module

    output = tmp_path / "items.jsonl"

    def fake_crawl(start_urls, **options):
        response = Response(
            url=start_urls[0],
            status_code=200,
            content=b"""
<html><body>
  <article class="product">
    <h3><a title="One">One</a></h3>
    <p class="price">$1.00</p>
  </article>
  <article class="product">
    <h3><a title="Two">Two</a></h3>
  </article>
</body></html>
""",
        )
        return CrawlResult(items=options["extract"](response), stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    code = cli.main(
        [
            "crawl",
            "https://example.com/",
            "--item-css",
            ".product",
            "--css",
            "title=h3 a",
            "--attr",
            "title=title",
            "--css",
            "price=.price",
            "-o",
            str(output),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8").splitlines() == [
        '{"title": "One", "price": "$1.00"}',
        '{"title": "Two", "price": null}',
    ]


def test_crawl_command_runs_standalone_url_with_attr_and_all(
    tmp_path, monkeypatch, capsys
):
    from webuse.spider import sync as sync_module

    output = tmp_path / "items.jsonl"

    def fake_crawl(start_urls, **options):
        response = Response(
            url=start_urls[0],
            status_code=200,
            content=b"""
<html><body>
  <a href="/one">One</a>
  <a href="/two">Two</a>
</body></html>
""",
        )
        return CrawlResult(items=options["extract"](response), stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    code = cli.main(
        [
            "crawl",
            "https://example.com/",
            "--css",
            "links=a",
            "--attr",
            "links=href",
            "--all",
            "links",
            "-o",
            str(output),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert (
        output.read_text(encoding="utf-8")
        == '{"links": ["https://example.com/one", "https://example.com/two"]}\n'
    )


def test_crawl_command_maps_standalone_request_options(monkeypatch, capsys):
    from webuse.spider import sync as sync_module

    captured = {}

    def fake_crawl(start_urls, **options):
        captured["start_urls"] = start_urls
        captured["options"] = options
        return CrawlResult(stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    code = cli.main(
        [
            "crawl",
            "https://example.com/",
            "--css",
            "title=h1",
            "--header",
            "X-Test=yes",
            "--param",
            "page=1",
            "--timeout",
            "3.5",
        ]
    )
    _ = capsys.readouterr()

    assert code == 0
    assert captured["start_urls"] == ["https://example.com/"]
    request_defaults = captured["options"]["request_defaults"]
    assert request_defaults["impersonate"] == "chrome"
    assert request_defaults["headers"] == {"X-Test": "yes"}
    assert request_defaults["params"] == {"page": "1"}
    assert request_defaults["timeout"] == 3.5


def test_crawl_command_maps_standalone_follow_options(monkeypatch, capsys):
    from webuse.spider import sync as sync_module

    captured = {}

    def fake_crawl(start_urls, **options):
        captured["options"] = options
        return CrawlResult(stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    code = cli.main(
        [
            "crawl",
            "https://example.com/",
            "--follow-css",
            "a.next",
            "--follow-xpath",
            "//a",
            "--follow-attr",
            "data-href",
            "--same-domain",
            "--allowed-domain",
            "example.com",
            "--robots-txt",
            "--max-depth",
            "1",
        ]
    )
    _ = capsys.readouterr()

    assert code == 0
    options = captured["options"]
    assert options["max_depth"] == 1
    assert options["robots_txt"] is True
    assert options["allowed_domains"] == {"example.com"}
    assert len(options["follow"]) == 2
    assert options["follow"][0].css == "a.next"
    assert options["follow"][1].xpath == "//a"
    assert all(rule.attr == "data-href" for rule in options["follow"])
    assert all(rule.same_domain for rule in options["follow"])


def test_crawl_command_rejects_spider_with_url_target():
    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", "https://example.com/", "--spider", "books"])

    assert "--spider" in str(exc.value)


def test_crawl_command_rejects_standalone_options_without_url_target(cli_project):
    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", str(cli_project.root), "--css", "title=h1"])

    assert "URL crawl target" in str(exc.value)


def test_crawl_command_rejects_malformed_css_field():
    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", "https://example.com/", "--css", "missing-equals"])

    assert "KEY=VALUE" in str(exc.value)


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


def test_crawl_command_passes_file_state_to_spider(
    tmp_path, cli_project, monkeypatch, capsys
):
    cli_project.write_default_spider(
        item_fields="queue: str\n    seen: str",
        run_body=(
            'queue = kwargs["request_queue"]\n'
            '        seen = kwargs["request_seen"]\n'
            "        return CrawlResult("
            "items=[Item(queue=queue.__class__.__name__, seen=seen.__class__.__name__)], "
            "stats=CrawlStats())"
        ),
    )
    output = cli_project.root / "test.jsonl"
    state = tmp_path / "state"
    monkeypatch.chdir(cli_project.root)

    code = cli.main(
        ["crawl", "--spider", "books", "--state", str(state), "-o", str(output)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert (
        output.read_text(encoding="utf-8")
        == '{"queue": "FileRequestQueue", "seen": "FileRequestSeen"}\n'
    )


def test_crawl_command_rejects_state_with_async(tmp_path, cli_project, monkeypatch):
    cli_project.write_spider(
        """import webuse


class BooksSpider(webuse.AsyncSpider):
    pass
"""
    )
    monkeypatch.chdir(cli_project.root)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "crawl",
                "--spider",
                "books",
                "--async",
                "--state",
                str(tmp_path / "state"),
            ]
        )

    assert "--state" in str(exc.value)


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
        '\n'.join(
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

    assert "cannot find spider" in str(exc.value)


def test_crawl_command_runs_importable_spider_module(
    tmp_path, cli_project, monkeypatch, capsys
):
    cli_project.make_package()
    cli_project.write_default_spider(
        run_body='return CrawlResult(items=[Item(title="Module One")], stats=CrawlStats())'
    )
    output = tmp_path / "test.jsonl"
    monkeypatch.chdir(tmp_path)

    code = cli.main(["crawl", "--spider", "project.spiders.books", "-o", str(output)])
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


def test_crawl_command_runs_standalone_yaml_config_to_output_file(
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
        return CrawlResult(items=options["extract"](response), stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    code = cli.main(["crawl", str(config), "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Home", "_type": "page"}\n'


def test_crawl_command_runs_standalone_config_from_directory_and_spider_name(
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
        return CrawlResult(items=options["extract"](response), stats=CrawlStats())

    monkeypatch.setattr(sync_module, "crawl", fake_crawl)

    code = cli.main(
        ["crawl", str(tmp_path), "--spider", "books.yaml", "-o", str(output)]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Home", "_type": "page"}\n'
