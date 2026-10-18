from pathlib import Path

from webuse.config import LOCAL_CONFIG_NAME, local_config_path


def test_local_config_uses_nearest_ancestor(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = home / "project"
    work = project / "ui"
    work.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    for directory in (home, project):
        (directory / LOCAL_CONFIG_NAME).write_text("llm: {}\n")

    assert local_config_path(work) == project / LOCAL_CONFIG_NAME
    (work / LOCAL_CONFIG_NAME).write_text("llm: {}\n")
    assert local_config_path(work) == work / LOCAL_CONFIG_NAME


def test_local_config_includes_home_but_stops_there(monkeypatch, tmp_path):
    home = tmp_path / "home"
    work = home / "project" / "ui"
    work.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / LOCAL_CONFIG_NAME).write_text("llm: {}\n")
    config = home / LOCAL_CONFIG_NAME
    config.write_text("llm: {}\n")

    assert local_config_path(work) == config
    config.unlink()
    assert local_config_path(work) == work / LOCAL_CONFIG_NAME


def test_local_config_outside_home_searches_through_root(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    work = tmp_path / "outside"
    root_config = Path(work.anchor) / LOCAL_CONFIG_NAME
    monkeypatch.setattr(Path, "is_file", lambda path: path == root_config)

    assert local_config_path(work) == root_config
