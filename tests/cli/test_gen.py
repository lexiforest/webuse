import sqlite3

import pytest

from webuse import cli
from webuse.exceptions import SmartSelectorError
from webuse.models import CrawlResult, CrawlStats
from webuse.response import Response


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
