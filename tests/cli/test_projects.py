import json
import sys

import pytest
import yaml

from webuse import cli
from webuse.engine import aio, sync
from crawl_helpers import AsyncFakeClient, FakeClient


@pytest.fixture
def fake_transport(monkeypatch):
    class AsyncClient(AsyncFakeClient):
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(sync, "Client", FakeClient)
    monkeypatch.setattr(aio, "AsyncClient", AsyncClient)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "target", ["https://example.com", "books.yaml", "books.py", "webuse.yaml"]
)
def test_crawl_rejects_non_project_targets(tmp_path, target, asynchronous):
    value = target if "://" in target else str(tmp_path / target)
    if "://" not in target:
        (tmp_path / target).write_text("spiders: {}\n")
    with pytest.raises(SystemExit, match="project directory"):
        cli.main(["crawl", value, *(["--async"] if asynchronous else [])])


@pytest.mark.parametrize("asynchronous", [False, True])
def test_crawl_requires_registration_even_for_existing_file(tmp_path, asynchronous):
    (tmp_path / "webuse.yaml").write_text("spiders:\n  pages:\n    start_urls: []\n")
    (tmp_path / "unregistered.py").write_text(
        "raise AssertionError('must not execute')"
    )
    with pytest.raises(SystemExit, match="spider not found in project config"):
        cli.main(
            [
                "crawl",
                str(tmp_path),
                "--spider",
                "unregistered.py",
                *(["--async"] if asynchronous else []),
            ]
        )


@pytest.mark.parametrize("kind", ["config", "path", "module"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_registered_spider_inherits_project_settings_outside_cwd(
    tmp_path, monkeypatch, kind, asynchronous, fake_transport, capsys
):
    monkeypatch.delitem(sys.modules, "nested", raising=False)
    monkeypatch.delitem(sys.modules, "nested.books", raising=False)
    root = tmp_path / "project"
    (root / "nested").mkdir(parents=True)
    if kind == "config":
        (root / "nested/books.yaml").write_text("start_urls: [https://example.com/]\n")
        entry = "config: nested/books.yaml"
    else:
        base = "AsyncSpider" if asynchronous else "Spider"
        (root / "nested/books.py").write_text(
            f"from webuse import {base}\nclass Books({base}):\n    start_urls = ['https://example.com/']\n"
        )
        entry = "module: nested.books" if kind == "module" else "path: nested/books.py"
    (root / "webuse.yaml").write_text(
        f"name: project\nconcurrency:\n  limit: 2\n  per_domain: 1\nspiders:\n  books:\n    {entry}\n"
    )
    observed = []
    # Inspect effective options without bypassing the real engine.
    from webuse.spider import aio as aspider, sync as sspider

    original = aspider.acrawl if asynchronous else sspider.crawl

    def capture(start_urls, **options):
        observed.append(options)
        return original(start_urls, **options)

    monkeypatch.setattr(
        aspider if asynchronous else sspider,
        "acrawl" if asynchronous else "crawl",
        capture,
    )
    assert cli.main(["crawl", str(root), *(["--async"] if asynchronous else [])]) == 0
    assert observed[0]["concurrency"] == 2
    assert observed[0]["per_domain"] == 1


def test_gen_registration_conflict_does_not_write_files(tmp_path):
    config = tmp_path / "webuse.yaml"
    content = "spiders:\n  books:\n    start_urls: [https://example.com/]\n"
    config.write_text(content)
    with pytest.raises(SystemExit, match="already registered"):
        cli.main(["gen", "books", "https://example.com/", "--directory", str(tmp_path)])
    assert config.read_text() == content
    assert not (tmp_path / "spiders").exists()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("inline", [False, True])
def test_registered_spiders_have_independent_pipelines(
    tmp_path, asynchronous, inline, fake_transport, monkeypatch
):
    project = tmp_path / "project"
    (project / "spiders").mkdir(parents=True)
    spiders = {}
    for name, url in [
        ("home", "https://example.com/"),
        ("page", "https://example.com/page-1"),
    ]:
        config = {
            "start_urls": [url],
            "items": {
                "pipelines": {
                    "default": [{"type": "jsonl", "path": f"{name}.jsonl"}]
                }
            },
            "pages": {
                "default": {
                    "extract": {
                        "page": {
                            "item_model": "crawl_helpers.SampleItem",
                            "fields": {"title": "h1"},
                        }
                    }
                }
            },
        }
        if inline:
            spiders[name] = config
        else:
            (project / f"spiders/{name}.yaml").write_text(yaml.safe_dump(config))
            spiders[name] = {"config": f"spiders/{name}.yaml"}
    (project / "webuse.yaml").write_text(yaml.safe_dump({"spiders": spiders}))
    monkeypatch.chdir(tmp_path)

    assert cli.main(["crawl", str(project), *(["--async"] if asynchronous else [])]) == 0

    for name, title in [("home", "Home"), ("page", "Page One")]:
        records = [
            json.loads(line)
            for line in (project / f"{name}.jsonl").read_text().splitlines()
        ]
        assert records == [{"title": title, "source": ""}]
        assert not (tmp_path / f"{name}.jsonl").exists()
