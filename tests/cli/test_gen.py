import asyncio
import json
import sys

import pytest

from webuse import AsyncSpider, Response, cli
from webuse.config import load_config_file
from webuse.cli.crawl import _load_spider
from crawl_helpers import FakeClient


@pytest.fixture(autouse=True)
def isolated_spider_imports():
    # Each generated project owns its own top-level spiders package.
    def modules():
        return [
            name for name in sys.modules
            if name == "spiders" or name.startswith("spiders.")
        ]

    saved = {name: sys.modules.pop(name) for name in modules()}
    try:
        yield
    finally:
        for name in modules():
            sys.modules.pop(name)
        sys.modules.update(saved)


@pytest.mark.parametrize(
    "format_args,suffix",
    [([], ".yaml"), (["--yaml"], ".yaml"), (["--toml"], ".toml"), (["--python-only"], None)],
)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_gen_creates_registered_project_spider(
    tmp_path, capsys, format_args, suffix, asynchronous, monkeypatch
):
    project = tmp_path / "project"
    assert cli.main(["create", str(project)]) == 0
    capsys.readouterr()
    assert (
        cli.main(
            [
                "gen",
                "pages",
                "https://example.com",
                "--directory",
                str(project),
                *format_args,
                *(["--async"] if asynchronous else []),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    spider_path = project / "spiders/pages.py"
    assert payload["path"] == str(spider_path)
    assert "item_model = Item" in spider_path.read_text()
    assert "class Item(BaseModel):" in spider_path.read_text()
    assert "class CleanPipeline(webuse.ItemPipeline):" in spider_path.read_text()
    assert "def main" not in spider_path.read_text()
    config = load_config_file(project / "webuse.yaml")
    assert config["spiders"]["pages"] == {"path": "spiders/pages.py"}
    if suffix:
        config_path = project / f"spiders/pages{suffix}"
        assert payload["config"] == str(config_path)
        assert load_config_file(config_path)["start_urls"] == ["https://example.com"]
        assert load_config_file(config_path)["pipelines"] == [
            {"class": "spiders.pages.CleanPipeline"},
            {"type": "jsonl", "path": "output.jsonl"},
        ]
    else:
        assert "config" not in payload
    spider = _load_spider(str(spider_path), project_dir=project)
    assert isinstance(spider, AsyncSpider) is asynchronous

    class GeneratedPageClient(FakeClient):
        def request(self, method, url, **kwargs):
            response = super().request(method, url, **kwargs)
            response.content = b"<title>Home</title><h1>Home</h1>"
            return response

    class AsyncGeneratedPageClient:
        def __init__(self, **kwargs):
            pass

        async def request(self, method, url, **kwargs):
            return GeneratedPageClient().request(method, url, **kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    result = (
        asyncio.run(spider.run(client=AsyncGeneratedPageClient(), max_requests=1))
        if asynchronous
        else spider.run(client=GeneratedPageClient(), max_requests=1)
    )
    assert len(result.items) == 1
    assert result.items[0].model_dump() == {"title": "Home"}
    assert json.loads((project / "output.jsonl").read_text()) == {"title": "Home"}
    if asynchronous:
        from webuse.engine import aio

        monkeypatch.setattr(aio, "AsyncClient", AsyncGeneratedPageClient)
        # The generated AsyncSpider runs through the ordinary crawl command.
        assert cli.main(
            ["crawl", str(project), "--spider", "pages", "--max-requests", "1"]
        ) == 0
        records = (project / "output.jsonl").read_text().splitlines()
        assert len(records) == 2
        assert all(json.loads(record) == {"title": "Home"} for record in records)


@pytest.mark.parametrize("args", [[], ["--python-only"], ["--toml"]])
@pytest.mark.parametrize("exists", [False, True])
def test_gen_requires_existing_project(tmp_path, args, exists):
    target = tmp_path / "missing"
    if exists:
        target.mkdir()
    with pytest.raises(SystemExit, match="project|webuse.yaml"):
        cli.main(
            ["gen", "books", "https://example.com", "--directory", str(target), *args]
        )
    assert not (target / "books.yaml").exists()
    assert not (target / "spiders").exists()


@pytest.mark.parametrize("args", [["--toml", "--yaml"], ["--python-only", "--yaml"]])
def test_gen_refuses_multiple_formats(tmp_path, args):
    with pytest.raises(SystemExit, match="Use only one"):
        cli.main(
            ["gen", "books", "https://example.com", "--directory", str(tmp_path), *args]
        )


@pytest.mark.parametrize("project_suffix", ["yaml", "toml"])
@pytest.mark.parametrize("format_args", [[], ["--toml"], ["--python-only"]])
def test_gen_supports_minimal_project_and_sanitizes_names(
    tmp_path, project_suffix, format_args, capsys
):
    config = tmp_path / f"webuse.{project_suffix}"
    config.write_text(
        'name = "project"\n' if project_suffix == "toml" else "name: project\n"
    )
    assert (
        cli.main(
            [
                "gen",
                "Product Pages",
                "https://example.com",
                "--directory",
                str(tmp_path),
                *format_args,
            ]
        )
        == 0
    )
    spider_path = tmp_path / "spiders/product_pages.py"
    # Prove the pipeline loaded from this generated module actually processes items.
    spider_path.write_text(
        spider_path.read_text().replace(
            "return item", 'return item.model_copy(update={"title": "processed"})'
        )
    )
    assert load_config_file(config)["spiders"]["product_pages"] == {
        "path": "spiders/product_pages.py"
    }
    spider = _load_spider(str(spider_path), project_dir=tmp_path)
    response = Response(content=b"<title>Home</title>")

    class Client:
        def request(self, method, url, **kwargs):
            return response

    result = spider.run(client=Client(), max_requests=1)
    assert result.items[0].title == "processed"
    records = (tmp_path / "output.jsonl").read_text().splitlines()
    assert json.loads(records[0])["title"] == "processed"


@pytest.mark.parametrize(
    "suffix,args", [("yaml", []), ("toml", ["--toml"]), ("py", ["--python-only"])]
)
def test_gen_preserves_files_unless_forced(tmp_path, capsys, suffix, args):
    (tmp_path / "webuse.yaml").write_text("name: project\n")
    path = tmp_path / f"spiders/books.{suffix}"
    path.parent.mkdir()
    path.write_text("mine")
    command = [
        "gen",
        "books",
        "https://example.com",
        "--directory",
        str(tmp_path),
        *args,
    ]
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        cli.main(command)
    assert path.read_text() == "mine"
    assert cli.main([*command, "--force"]) == 0
    assert path.read_text() != "mine"


def test_gen_force_replaces_toml_registration(tmp_path, capsys):
    config = tmp_path / "webuse.toml"
    config.write_text('[spiders.books]\npath = "old.py"\n\n[log]\nlevel = "debug"\n')
    command = ["gen", "books", "https://example.com", "--directory", str(tmp_path)]
    with pytest.raises(SystemExit, match="already registered"):
        cli.main(command)
    assert not (tmp_path / "spiders").exists()
    assert cli.main([*command, "--force"]) == 0
    assert load_config_file(config) == {
        "spiders": {"books": {"path": "spiders/books.py"}},
        "log": {"level": "debug"},
    }


def test_gen_rejects_uneditable_toml_before_writing_files(tmp_path):
    config = tmp_path / "webuse.toml"
    content = 'spiders = {books = {path = "books.py"}}\n'
    config.write_text(content)
    with pytest.raises(SystemExit, match="inline TOML"):
        cli.main(["gen", "quotes", "https://example.com", "--directory", str(tmp_path)])
    assert config.read_text() == content
    assert not (tmp_path / "spiders").exists()
