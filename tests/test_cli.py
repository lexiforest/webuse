import sqlite3

import pytest

from webuse import cli
from webuse.exceptions import SmartSelectorError
from webuse.models import CrawlResult, CrawlStats, RequestOptions
from webuse.response import Response


def test_fetch_command_with_selector(monkeypatch, capsys):
    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"

            class FakeElement:
                def text(self):
                    return "Hello"

            return [FakeElement()]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "https://example.com", "--css", ".title"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Hello"' in out


def test_fetch_command_with_llm_selector(monkeypatch, capsys):
    captured = {}

    class FakeResponse:
        url = "https://example.com"

        def llm(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return "Alpha Gadget"

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--llm",
            "Which product is first?",
            "--llm-model",
            "test-model",
            "--llm-max-chars",
            "100",
            "--llm-temperature",
            "0.2",
            "--output-shape",
            "item",
            "--field",
            "product",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == '{\n  "product": "Alpha Gadget"\n}'
    assert captured["prompt"] == "Which product is first?"
    assert captured["kwargs"]["model"] == "test-model"
    assert captured["kwargs"]["max_chars"] == 100
    assert captured["kwargs"]["temperature"] == 0.2


def test_fetch_command_with_configured_llm_selector(monkeypatch, capsys, tmp_path):
    captured = {}
    config = tmp_path / "webuse.yaml"
    config.write_text(
        """
fetch:
  url: https://example.com
  llm: Extract the primary title
  llm_model: configured-model
  llm_system_prompt: Return only the title.
  llm_base_url: https://llm.example.com/v1
  llm_api_key: test-key
  output_shape: item
  field: title
""",
        encoding="utf-8",
    )

    class FakeResponse:
        url = "https://example.com"

        def llm(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return "Configured Title"

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "--config", str(config)])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == '{\n  "title": "Configured Title"\n}'
    assert captured["prompt"] == "Extract the primary title"
    assert captured["kwargs"]["model"] == "configured-model"
    assert captured["kwargs"]["system_prompt"] == "Return only the title."
    assert captured["kwargs"]["base_url"] == "https://llm.example.com/v1"
    assert captured["kwargs"]["api_key"] == "test-key"


def test_fetch_command_parses_llm_json_array(monkeypatch, capsys):
    class FakeResponse:
        url = "https://example.com"

        def llm(self, prompt, **kwargs):
            assert "JSON value" in kwargs["system_prompt"]
            return '["Alpha", "Beta"]'

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "https://example.com", "--llm", "All titles"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == (
        "{\n"
        '  "url": "https://example.com",\n'
        '  "match": [\n'
        '    "Alpha",\n'
        '    "Beta"\n'
        "  ],\n"
        '  "selector": "All titles"\n'
        "}"
    )


def test_fetch_command_coerces_multiline_llm_output_to_list(monkeypatch, capsys):
    class FakeResponse:
        url = "https://example.com"

        def llm(self, prompt, **kwargs):
            return "Alpha\nBeta\nGamma"

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "https://example.com", "--llm", "All titles"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"match": [\n    "Alpha",\n    "Beta",\n    "Gamma"\n  ]' in out


def test_crawl_command_runs_standalone_url_with_css_to_output_file(
    tmp_path, monkeypatch, capsys
):
    from webuse.spider import sync as sync_module

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

    code = cli.main(
        [
            "crawl",
            "https://example.com/",
            "--css",
            "title=h1",
            "-o",
            str(output),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Home"}\n'


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


def test_crawl_command_rejects_standalone_options_without_url_target(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", str(project), "--css", "title=h1"])

    assert "URL crawl target" in str(exc.value)


def test_crawl_command_rejects_malformed_css_field():
    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", "https://example.com/", "--css", "missing-equals"])

    assert "KEY=VALUE" in str(exc.value)


def test_crawl_command_runs_spider_name_from_project_to_output_file(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    spider = spiders / "books.py"
    spider.write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class BooksSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="One")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = project / "test.jsonl"
    monkeypatch.chdir(project)

    code = cli.main(["crawl", "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "One"}\n'


def test_crawl_command_passes_attributes_to_spider(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    genre: str
    edition: str


class BooksSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(genre=self.genre, edition=self.edition)], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = project / "test.jsonl"
    monkeypatch.chdir(project)

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


def test_crawl_command_passes_file_state_to_spider(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    queue: str
    seen: str


class BooksSpider(webuse.Spider):
    def run(self, **kwargs):
        queue = kwargs["request_queue"]
        seen = kwargs["request_seen"]
        return CrawlResult(items=[Item(queue=queue.__class__.__name__, seen=seen.__class__.__name__)], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = project / "test.jsonl"
    state = tmp_path / "state"
    monkeypatch.chdir(project)

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


def test_crawl_command_rejects_state_with_async(tmp_path, monkeypatch):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse


class BooksSpider(webuse.AsyncSpider):
    pass
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

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


def test_crawl_command_rejects_malformed_attribute(tmp_path, monkeypatch):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse


class BooksSpider(webuse.Spider):
    pass
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", "--spider", "books", "--attribute", "missing-equals"])

    assert "KEY=VALUE" in str(exc.value)


def test_crawl_command_writes_csv_output_by_extension(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str
    price: str


class BooksSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="One", price="$1.00")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = project / "test.csv"
    monkeypatch.chdir(project)

    code = cli.main(["crawl", "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8").splitlines() == [
        "title,price",
        "One,$1.00",
    ]


def test_crawl_command_writes_sqlite_output_by_extension(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class BooksSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="One")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = project / "test.sqlite"
    monkeypatch.chdir(project)

    code = cli.main(["crawl", "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    with sqlite3.connect(output) as connection:
        rows = connection.execute("SELECT item_type, data FROM items").fetchall()
    assert rows == [("Item", '{"title": "One"}')]


def test_crawl_command_rejects_unknown_output_extension(tmp_path, monkeypatch):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class BooksSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="One")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", "--spider", "books", "-o", str(project / "test.json")])

    assert "unsupported output extension" in str(exc.value)


def test_crawl_command_accepts_project_directory(tmp_path, capsys):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class BooksSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="Directory One")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = tmp_path / "test.jsonl"

    code = cli.main(["crawl", str(project), "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Directory One"}\n'


def test_crawl_command_defaults_to_current_project(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "alpha.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class AlphaSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="Alpha")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    (spiders / "beta.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class BetaSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="Beta")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = project / "test.jsonl"
    monkeypatch.chdir(project)

    code = cli.main(["crawl", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8").splitlines() == [
        '{"title": "Alpha"}',
        '{"title": "Beta"}',
    ]


def test_crawl_command_does_not_search_upwards_for_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    nested = project / "nested"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    nested.mkdir()
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class BooksSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="One")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(nested)

    with pytest.raises(SystemExit) as exc:
        cli.main(["crawl", "--spider", "books"])

    assert "cannot find spider" in str(exc.value)


def test_crawl_command_runs_importable_spider_module(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "__init__.py").write_text("", encoding="utf-8")
    (spiders / "__init__.py").write_text("", encoding="utf-8")
    (spiders / "books.py").write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class BooksSpider(webuse.Spider):
    def run(self):
        return CrawlResult(items=[Item(title="Module One")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = tmp_path / "test.jsonl"
    monkeypatch.chdir(tmp_path)

    code = cli.main(["crawl", "--spider", "project.spiders.books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Module One"}\n'


def test_crawl_command_runs_async_spider_target_to_output_file(
    tmp_path, monkeypatch, capsys
):
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    spider = spiders / "books.py"
    spider.write_text(
        """import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    title: str


class BooksSpider(webuse.AsyncSpider):
    async def run(self):
        return CrawlResult(items=[Item(title="Async One")], stats=CrawlStats())
""",
        encoding="utf-8",
    )
    output = project / "test.jsonl"
    monkeypatch.chdir(project)

    code = cli.main(["crawl", "--spider", "books", "-o", str(output)])
    out = capsys.readouterr().out

    assert code == 0
    assert out == ""
    assert output.read_text(encoding="utf-8") == '{"title": "Async One"}\n'


def test_fetch_command_with_smart_store_and_key(monkeypatch, capsys, tmp_path):
    store_path = tmp_path / "selectors.json"

    class FakeResponse:
        url = "https://example.com"

        def smart(self, prompt, *, key=None, store=None, use_llm=False, resolver=None):
            assert prompt == "product link"
            assert key == "product"
            assert store is not None
            assert store.path == store_path
            assert use_llm is False
            assert resolver is None

            class FakeElement:
                def text(self):
                    return "Open"

            return FakeElement()

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--smart",
            "product link",
            "--smart-store",
            str(store_path),
            "--smart-key",
            "product",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Open"' in out


def test_fetch_command_uses_configured_smart_store_and_key(
    monkeypatch, capsys, tmp_path
):
    store_path = tmp_path / "configured-selectors.json"
    config_path = tmp_path / "webuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[fetch]",
                'url = "https://example.com"',
                f'smart_store = "{store_path}"',
                'smart_key = "configured"',
            ]
        ),
        encoding="utf-8",
    )

    class FakeResponse:
        url = "https://example.com"

        def smart(self, prompt, *, key=None, store=None, use_llm=False, resolver=None):
            assert prompt == "configured prompt"
            assert key == "configured"
            assert store is not None
            assert store.path == store_path
            assert use_llm is False
            assert resolver is None

            class FakeElement:
                def text(self):
                    return "Configured"

            return FakeElement()

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        ["fetch", "--config", str(config_path), "--smart", "configured prompt"]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"Configured"' in out


def test_config_request_option_names_match_request_options():
    expected = {name for name in RequestOptions.model_fields if name != "extra_kwargs"}
    config = {name: name for name in expected}
    config["extra_kwargs"] = {"custom_option": "custom"}

    options = cli._request_options_from_config(config)

    assert set(options) == expected | {"custom_option"}


def test_fetch_config_passes_request_options(monkeypatch, capsys, tmp_path):
    config_path = tmp_path / "webuse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[fetch]",
                'url = "https://example.com"',
                'method = "POST"',
                "timeout = 5",
                "follow_redirects = true",
                'impersonate = "chrome"',
                "[fetch.headers]",
                'User-Agent = "webuse"',
                "[fetch.json]",
                'query = "alpha"',
            ]
        ),
        encoding="utf-8",
    )
    captured = {}

    class FakeResponse:
        text = "ok\n"

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr(cli, "request", fake_request)

    code = cli.main(["fetch", "--config", str(config_path)])
    _ = capsys.readouterr()

    assert code == 0
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com"
    assert captured["kwargs"]["headers"] == {"User-Agent": "webuse"}
    assert captured["kwargs"]["json"] == {"query": "alpha"}
    assert captured["kwargs"]["timeout"] == 5
    assert captured["kwargs"]["follow_redirects"] is True
    assert captured["kwargs"]["impersonate"] == "chrome"


def test_fetch_command_defaults_to_chrome_impersonation(monkeypatch, capsys):
    captured = {}

    class FakeResponse:
        text = "ok\n"

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr(cli, "request", fake_request)

    code = cli.main(["fetch", "https://example.com"])
    _ = capsys.readouterr()

    assert code == 0
    assert captured["kwargs"]["impersonate"] == "chrome"


def test_fetch_command_supports_body_files_and_request_options(
    monkeypatch, capsys, tmp_path
):
    upload = tmp_path / "upload.txt"
    upload.write_text("payload", encoding="utf-8")
    captured = {}

    class FakeResponse:
        text = "ok\n"

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, "kwargs": kwargs})
        assert kwargs["files"]["upload"].read() == b"payload"
        return FakeResponse()

    monkeypatch.setattr(cli, "request", fake_request)

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--method",
            "POST",
            "--form",
            "name=alpha",
            "--file",
            f"upload={upload}",
            "--cookie",
            "session=abc",
            "--auth",
            "user:pass",
            "--no-verify",
            "--follow-redirects",
            "--max-redirects",
            "3",
            "--http-version",
            "v2",
            "--ja3",
            "ja3-value",
            "--akamai",
            "akamai-value",
            "--extra-fp",
            'tls="abc"',
        ]
    )
    _ = capsys.readouterr()

    assert code == 0
    assert captured["method"] == "POST"
    assert captured["kwargs"]["data"] == {"name": "alpha"}
    assert captured["kwargs"]["cookies"] == {"session": "abc"}
    assert captured["kwargs"]["auth"] == ("user", "pass")
    assert captured["kwargs"]["verify"] is False
    assert captured["kwargs"]["follow_redirects"] is True
    assert captured["kwargs"]["max_redirects"] == 3
    assert captured["kwargs"]["http_version"] == "v2"
    assert captured["kwargs"]["ja3"] == "ja3-value"
    assert captured["kwargs"]["akamai"] == "akamai-value"
    assert captured["kwargs"]["extra_fp"] == {"tls": "abc"}


def test_fetch_command_outputs_first_attr_as_item(monkeypatch, capsys):
    class FakeElement:
        def __init__(self, href):
            self.href = href

        def attr(self, name):
            assert name == "href"
            return self.href

    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == "a.product"
            return [FakeElement("/alpha"), FakeElement("/beta")]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--css",
            "a.product",
            "--attr",
            "href",
            "--first",
            "--output-shape",
            "item",
            "--field",
            "link",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == '{\n  "link": "/alpha"\n}'


def test_fetch_command_can_output_jsonl(monkeypatch, capsys):
    class FakeElement:
        def text(self):
            return "Hello"

    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"
            return [FakeElement()]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        ["fetch", "https://example.com", "--css", ".title", "--first", "--jsonl"]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert (
        out == '{"url": "https://example.com", "match": "Hello", "selector": ".title"}'
    )


def test_fetch_command_outputs_all_matches_as_jsonl(monkeypatch, capsys):
    class FakeElement:
        def __init__(self, title):
            self.title = title

        def attr(self, name):
            assert name == "title"
            return self.title

    class FakeResponse:
        url = "https://books.toscrape.com/"

        def css(self, selector):
            assert selector == ".product_pod h3 a"
            return [FakeElement("Alpha"), FakeElement("Beta")]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://books.toscrape.com/",
            "--css",
            ".product_pod h3 a",
            "--attr",
            "title",
            "--all",
            "--jsonl",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert out == [
        '{"url": "https://books.toscrape.com/", "match": "Alpha", "selector": ".product_pod h3 a"}',
        '{"url": "https://books.toscrape.com/", "match": "Beta", "selector": ".product_pod h3 a"}',
    ]


def test_fetch_command_outputs_all_items_as_jsonl(monkeypatch, capsys):
    class FakeElement:
        def text(self):
            return "Hello"

    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"
            return [FakeElement(), FakeElement()]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--css",
            ".title",
            "--all",
            "--jsonl",
            "--output-shape",
            "item",
            "--field",
            "title",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert out == ['{"title": "Hello"}', '{"title": "Hello"}']


def test_fetch_command_outputs_all_matches_as_csv(monkeypatch, capsys):
    class FakeElement:
        def __init__(self, title):
            self.title = title

        def attr(self, name):
            assert name == "title"
            return self.title

    class FakeResponse:
        url = "https://books.toscrape.com/"

        def css(self, selector):
            assert selector == ".product_pod h3 a"
            return [FakeElement("Alpha"), FakeElement("Beta")]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://books.toscrape.com/",
            "--css",
            ".product_pod h3 a",
            "--attr",
            "title",
            "--all",
            "--csv",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert out == [
        "url,match,selector",
        "https://books.toscrape.com/,Alpha,.product_pod h3 a",
        "https://books.toscrape.com/,Beta,.product_pod h3 a",
    ]


def test_fetch_command_outputs_item_csv(monkeypatch, capsys):
    class FakeElement:
        def text(self):
            return "Hello"

    class FakeResponse:
        url = "https://example.com"

        def css(self, selector):
            assert selector == ".title"
            return [FakeElement(), FakeElement()]

    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--css",
            ".title",
            "--all",
            "--csv",
            "--output-shape",
            "item",
            "--field",
            "title",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert out == ["title", "Hello", "Hello"]


def test_fetch_command_rejects_csv_with_jsonl():
    with pytest.raises(SystemExit):
        cli.main(["fetch", "https://example.com", "--csv", "--jsonl"])


def test_fetch_smart_llm_failure_can_emit_empty(monkeypatch, capsys):
    class FakeResolver:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeResponse:
        url = "https://example.com"

        def smart(self, prompt, *, key=None, store=None, use_llm=False, resolver=None):
            assert prompt == "missing cta"
            assert use_llm is True
            assert isinstance(resolver, FakeResolver)
            assert resolver.kwargs["model"] == "test-model"
            raise SmartSelectorError("missing")

    monkeypatch.setattr(cli, "LlmSmartResolver", FakeResolver)
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--smart",
            "missing cta",
            "--smart-use-llm",
            "--smart-model",
            "test-model",
            "--smart-failure",
            "empty",
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"match": null' in out


def test_websocket_command_sends_and_receives(monkeypatch, capsys):
    captured = {}

    class FakeWebSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def send_json(self, payload):
            captured["payload"] = payload

        def recv(self):
            return "pong"

    def fake_ws_connect(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeWebSocket()

    monkeypatch.setattr(cli, "ws_connect", fake_ws_connect)

    code = cli.main(
        [
            "websocket",
            "wss://example.com/socket",
            "--send-json",
            '{"ping": true}',
            "--recv",
            "2",
            "--header",
            "X-Test=yes",
        ]
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert captured["url"] == "wss://example.com/socket"
    assert captured["kwargs"]["headers"] == {"X-Test": "yes"}
    assert captured["payload"] == {"ping": True}
    assert out == [
        '{"url": "wss://example.com/socket", "message": "pong"}',
        '{"url": "wss://example.com/socket", "message": "pong"}',
    ]


def test_malformed_key_value_arguments_have_clear_errors(monkeypatch):
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["fetch", "https://example.com", "--header", "missing-equals"])

    assert "KEY=VALUE" in str(exc.value)


def test_create_command_scaffolds_project(tmp_path, capsys):
    project = tmp_path / "books"

    code = cli.main(["create", str(project)])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"project": "books"' in out
    assert (project / "webuse.toml").exists()
    assert (project / "README.md").exists()
    assert (project / ".gitignore").exists()
    assert (project / "items.py").exists()
    assert (project / "pipelines.py").exists()
    assert (project / "__init__.py").exists()
    assert (project / "spiders" / "__init__.py").exists()
    assert (project / ".webuse").is_dir()
    assert (project / "spiders").is_dir()
    config_text = (project / "webuse.toml").read_text(encoding="utf-8")
    items_text = (project / "items.py").read_text(encoding="utf-8")
    pipelines_text = (project / "pipelines.py").read_text(encoding="utf-8")
    assert 'name = "books"' in config_text
    assert "books.toscrape.com" not in config_text
    assert "[crawl]" not in config_text
    assert "[concurrency]" in config_text
    assert "[items.pipelines]" in config_text
    assert '{ class = "pipelines.CleanBookPipeline" }' in config_text
    assert '{ type = "jsonl", path = "output.jsonl" }' in config_text
    assert "from pydantic import BaseModel" in items_text
    assert "class BookItem(BaseModel)" in items_text
    assert "class CleanBookPipeline(webuse.Pipeline)" in pipelines_text


def test_create_command_refuses_non_empty_folder_without_force(tmp_path):
    project = tmp_path / "existing"
    project.mkdir()
    (project / "keep.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(["create", str(project)])

    assert "not empty" in str(exc.value)


def test_create_command_force_writes_scaffold_into_existing_folder(tmp_path, capsys):
    project = tmp_path / "existing"
    project.mkdir()
    (project / "keep.txt").write_text("mine", encoding="utf-8")

    code = cli.main(["create", str(project), "--force", "--name", "Custom"])
    _ = capsys.readouterr()

    assert code == 0
    assert (project / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert "# Custom" in (project / "README.md").read_text(encoding="utf-8")
    assert "class BookItem(BaseModel)" in (project / "items.py").read_text(
        encoding="utf-8"
    )
    assert "class CleanBookPipeline(webuse.Pipeline)" in (
        project / "pipelines.py"
    ).read_text(encoding="utf-8")


def test_gen_command_creates_yaml_config_by_default(tmp_path, capsys):
    target = tmp_path / "standalone"

    code = cli.main(
        ["gen", "books", "https://books.toscrape.com/", "--directory", str(target)]
    )
    out = capsys.readouterr().out.strip()

    config = target / "books.yaml"
    assert code == 0
    assert str(config) in out
    assert config.exists()
    assert not (target / "books.py").exists()
    assert not (target / "spiders").exists()
    text = config.read_text(encoding="utf-8")
    assert "name: books" in text
    assert "start_urls:" in text
    assert "- https://books.toscrape.com/" in text
    assert "extract:" in text


def test_gen_command_creates_python_spider_file(tmp_path, capsys):
    target = tmp_path / "standalone"

    code = cli.main(
        [
            "gen",
            "books",
            "https://books.toscrape.com/",
            "--directory",
            str(target),
            "--python",
        ]
    )
    out = capsys.readouterr().out.strip()

    spider = target / "books.py"
    assert code == 0
    assert str(spider) in out
    assert spider.exists()
    text = spider.read_text(encoding="utf-8")
    assert "class BooksSpider(webuse.Spider)" in text
    assert 'name = "books"' in text
    assert "Path(" not in text
    assert "sys.path" not in text
    assert "from items import" not in text
    assert 'item_model = "items.BookItem"' not in text
    assert 'start_urls = ["https://books.toscrape.com/"]' in text
    assert 'allowed_domains = {"books.toscrape.com"}' in text
    assert '"fields": {' in text
    assert '"title": "title"' in text
    assert "def main():" in text
    assert "BooksSpider().run()" in text
    assert "def run(" not in text
    assert "_json_default" not in text
    assert "import json" not in text
    assert not (target / "spiders").exists()
    assert not (target / "books.toml").exists()
    assert not (target / "books.yaml").exists()


def test_gen_command_creates_project_yaml_config_by_default(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")

    code = cli.main(
        ["gen", "books", "https://books.toscrape.com/", "--directory", str(project)]
    )
    out = capsys.readouterr().out.strip()

    config = project / "spiders" / "books.yaml"
    spider = project / "spiders" / "books.py"
    assert code == 0
    assert str(config) in out
    assert config.exists()
    assert spider.exists()
    spider_text = spider.read_text(encoding="utf-8")
    assert 'spider_config_path = "spiders/books.yaml"' in spider_text
    assert 'item_model = "items.BookItem"' in spider_text
    config_text = config.read_text(encoding="utf-8")
    assert "start_urls:" in config_text
    assert "fields:" in config_text


def test_gen_command_creates_project_python_spider_file(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")

    code = cli.main(
        [
            "gen",
            "books",
            "https://books.toscrape.com/",
            "--directory",
            str(project),
            "--python",
        ]
    )
    out = capsys.readouterr().out.strip()

    spider = project / "spiders" / "books.py"
    assert code == 0
    assert str(spider) in out
    assert spider.exists()
    text = spider.read_text(encoding="utf-8")
    assert 'item_model = "items.BookItem"' in text
    assert 'start_urls = ["https://books.toscrape.com/"]' in text


def test_gen_command_can_create_toml_config(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")

    code = cli.main(
        [
            "gen",
            "books",
            "https://books.toscrape.com/",
            "--directory",
            str(project),
            "--toml",
        ]
    )
    out = capsys.readouterr().out.strip()

    config = project / "spiders" / "books.toml"
    spider = project / "spiders" / "books.py"
    assert code == 0
    assert str(config) in out
    assert spider.exists()
    spider_text = spider.read_text(encoding="utf-8")
    assert 'spider_config_path = "spiders/books.toml"' in spider_text
    assert "Path(" not in spider_text
    assert "sys.path" not in spider_text
    assert 'item_model = "items.BookItem"' in spider_text
    assert "def main():" in spider_text
    assert "BooksSpider().run()" in spider_text
    assert "def run(" not in spider_text
    assert "_json_default" not in spider_text
    assert "import json" not in spider_text
    assert 'start_urls = ["https://books.toscrape.com/"]' not in spider_text
    assert "allowed_domains" not in spider_text
    assert "webuse.FollowRule" not in spider_text
    assert '"fields": {' not in spider_text
    text = config.read_text(encoding="utf-8")
    assert 'name = "books"' in text
    assert 'start_urls = ["https://books.toscrape.com/"]' in text
    assert 'allowed_domains = ["books.toscrape.com"]' in text
    assert "[[follow]]" in text
    assert "[extract.fields]" in text
    assert "[crawl]" not in text
    assert "[items.pipelines]" not in text


def test_gen_command_can_create_yaml_config(tmp_path, capsys):
    project = tmp_path / "project"
    project.mkdir()
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")

    code = cli.main(
        [
            "gen",
            "books",
            "https://books.toscrape.com/",
            "--directory",
            str(project),
            "--yaml",
        ]
    )
    out = capsys.readouterr().out.strip()

    config = project / "spiders" / "books.yaml"
    spider = project / "spiders" / "books.py"
    assert code == 0
    assert str(config) in out
    assert spider.exists()
    spider_text = spider.read_text(encoding="utf-8")
    assert 'spider_config_path = "spiders/books.yaml"' in spider_text
    assert "Path(" not in spider_text
    assert "sys.path" not in spider_text
    assert 'item_model = "items.BookItem"' in spider_text
    assert "def main():" in spider_text
    assert "BooksSpider().run()" in spider_text
    assert "def run(" not in spider_text
    assert "_json_default" not in spider_text
    assert "import json" not in spider_text
    assert 'start_urls = ["https://books.toscrape.com/"]' not in spider_text
    assert "allowed_domains" not in spider_text
    assert "webuse.FollowRule" not in spider_text
    assert '"fields": {' not in spider_text
    text = config.read_text(encoding="utf-8")
    assert "name: books" in text
    assert "start_urls:" in text
    assert "- https://books.toscrape.com/" in text
    assert "allowed_domains:" in text
    assert "follow:" in text
    assert "extract:" in text
    assert "fields:" in text
    assert "crawl:" not in text
    assert "pipelines:" not in text


def test_gen_command_can_create_standalone_toml_config_only(tmp_path, capsys):
    target = tmp_path / "standalone"

    code = cli.main(
        [
            "gen",
            "books",
            "https://books.toscrape.com/",
            "--directory",
            str(target),
            "--toml",
        ]
    )
    out = capsys.readouterr().out.strip()

    config = target / "books.toml"
    assert code == 0
    assert str(config) in out
    assert config.exists()
    assert not (target / "books.py").exists()
    assert not (target / "spiders").exists()
    text = config.read_text(encoding="utf-8")
    assert 'name = "books"' in text
    assert 'start_urls = ["https://books.toscrape.com/"]' in text
    assert "[extract.fields]" in text


def test_gen_command_can_create_standalone_yaml_config_only(tmp_path, capsys):
    target = tmp_path / "standalone"

    code = cli.main(
        [
            "gen",
            "books",
            "https://books.toscrape.com/",
            "--directory",
            str(target),
            "--yaml",
        ]
    )
    out = capsys.readouterr().out.strip()

    config = target / "books.yaml"
    assert code == 0
    assert str(config) in out
    assert config.exists()
    assert not (target / "books.py").exists()
    assert not (target / "spiders").exists()
    text = config.read_text(encoding="utf-8")
    assert "name: books" in text
    assert "start_urls:" in text
    assert "extract:" in text
    assert "fields:" in text


def test_gen_command_refuses_both_config_formats(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "gen",
                "books",
                "https://books.toscrape.com/",
                "--directory",
                str(tmp_path),
                "--toml",
                "--yaml",
            ]
        )

    assert "Use only one" in str(exc.value)


def test_gen_command_refuses_python_with_config_format(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "gen",
                "books",
                "https://books.toscrape.com/",
                "--directory",
                str(tmp_path),
                "--python",
                "--yaml",
            ]
        )

    assert "Use only one" in str(exc.value)


def test_gen_command_refuses_config_overwrite_without_force(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    config = project / "spiders" / "books.toml"
    config.parent.mkdir(parents=True)
    config.write_text("mine", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "gen",
                "books",
                "https://books.toscrape.com/",
                "--directory",
                str(project),
                "--toml",
            ]
        )

    assert "refusing to overwrite" in str(exc.value)
    assert config.read_text(encoding="utf-8") == "mine"


def test_gen_command_sanitizes_module_name(tmp_path, capsys):
    target = tmp_path / "standalone"

    code = cli.main(
        ["gen", "Product Pages", "https://example.com", "--directory", str(target)]
    )
    _ = capsys.readouterr()

    assert code == 0
    assert (target / "product_pages.yaml").exists()


def test_gen_command_refuses_default_yaml_overwrite_without_force(tmp_path):
    target = tmp_path / "standalone"
    config = target / "books.yaml"
    target.mkdir(parents=True)
    config.write_text("mine", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(
            ["gen", "books", "https://books.toscrape.com/", "--directory", str(target)]
        )

    assert "refusing to overwrite" in str(exc.value)
    assert config.read_text(encoding="utf-8") == "mine"


def test_gen_command_force_overwrites_default_yaml_config(tmp_path, capsys):
    target = tmp_path / "standalone"
    config = target / "books.yaml"
    target.mkdir(parents=True)
    config.write_text("mine", encoding="utf-8")

    code = cli.main(
        [
            "gen",
            "books",
            "https://books.toscrape.com/",
            "--directory",
            str(target),
            "--force",
        ]
    )
    _ = capsys.readouterr()

    assert code == 0
    assert "start_urls:" in config.read_text(encoding="utf-8")


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
extract:
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
    assert output.read_text(encoding="utf-8") == '{"title": "Home"}\n'


def test_crawl_command_runs_standalone_toml_config_to_output_file(
    tmp_path, monkeypatch, capsys
):
    from webuse.spider import sync as sync_module

    config = tmp_path / "books.toml"
    config.write_text(
        """
name = "books"
start_urls = ["https://example.com/"]

[extract.fields]
title = "h1"
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
    assert output.read_text(encoding="utf-8") == '{"title": "Home"}\n'


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
extract:
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
    assert output.read_text(encoding="utf-8") == '{"title": "Home"}\n'
