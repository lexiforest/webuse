import pytest

from webuse import cli
from webuse.config import load_config_file


def test_create_command_scaffolds_project(tmp_path, capsys):
    project = tmp_path / "books"

    code = cli.main(["create", str(project)])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert '"project": "books"' in out
    assert (project / "webuse.yaml").exists()
    assert (project / "README.md").exists()
    assert (project / ".gitignore").exists()
    assert not (project / "items.py").exists()
    assert not (project / "pipelines.py").exists()
    assert (project / "__init__.py").exists()
    assert (project / "spiders" / "__init__.py").exists()
    assert (project / ".webuse").is_dir()
    assert (project / "spiders").is_dir()
    config = load_config_file(project / "webuse.yaml")
    assert config["name"] == "books"
    assert "books.toscrape.com" not in str(config)
    assert "crawl" not in config
    assert config["llm"] == {}
    assert config["concurrency"] == 5
    assert config["per_domain"] == 1


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
    (project / "items.py").write_text("# custom item models\n")
    (project / "pipelines.py").write_text("# custom processing\n")

    code = cli.main(["create", str(project), "--force", "--name", "Custom"])
    _ = capsys.readouterr()

    assert code == 0
    assert (project / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert (project / "items.py").read_text() == "# custom item models\n"
    assert (project / "pipelines.py").read_text() == "# custom processing\n"
    assert "# Custom" in (project / "README.md").read_text(encoding="utf-8")
