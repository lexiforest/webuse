import sqlite3

import pytest

from webuse import cli
from webuse.exceptions import SmartSelectorError
from webuse.models import CrawlResult, CrawlStats
from webuse.response import Response


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
    assert "[llm]" in config_text
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
