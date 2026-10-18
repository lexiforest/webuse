import json
import subprocess
import sys
from pathlib import Path

from webuse import resources


def test_checkout_docs_are_independent_of_working_directory(tmp_path, monkeypatch):
    expected = Path(__file__).resolve().parents[1] / "docs/src/content/docs"
    monkeypatch.chdir(tmp_path)
    info = resources.framework_info()
    assert info["docs"]["root"] == str(expected)
    pages = {page["path"] for page in info["docs"]["pages"]}
    assert pages == {
        path.relative_to(expected).as_posix() for path in expected.rglob("*.md")
    }
    assert "user-guide/quick-start.md" in pages
    assert info["python"] == sys.executable
    assert (Path(info["source"]) / "spider/config.py").is_file()


def test_packaged_docs_do_not_fall_back_to_current_checkout(tmp_path, monkeypatch):
    package = tmp_path / "site-packages/webuse"
    docs = package / "_docs"
    docs.mkdir(parents=True)
    (docs / "index.md").write_text(
        '---\ntitle: "Installed version"\n---\n', encoding="utf-8"
    )
    monkeypatch.setattr(resources, "__file__", str(package / "resources.py"))
    info = resources.framework_info()
    assert info["source"] == str(package)
    assert info["docs"] == {
        "root": str(docs),
        "pages": [{"path": "index.md", "title": "Installed version"}],
    }
    (docs / "index.md").unlink()
    assert resources.framework_info()["docs"] is None
    assert resources.framework_info()["docs_error"]


def test_editable_install_prefers_live_docs_over_old_build(tmp_path, monkeypatch):
    package = tmp_path / "src/webuse"
    (package / "_docs").mkdir(parents=True)
    (package / "_docs/index.md").write_text("old release", encoding="utf-8")
    (tmp_path / "pyproject.toml").touch()
    docs = tmp_path / "docs/src/content/docs"
    docs.mkdir(parents=True)
    (docs / "index.md").write_text("live docs", encoding="utf-8")
    monkeypatch.setattr(resources, "__file__", str(package / "resources.py"))
    assert resources.documentation_root() == docs


def test_discovery_command_emits_json_from_an_unrelated_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "webuse.resources"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == resources.framework_info()
