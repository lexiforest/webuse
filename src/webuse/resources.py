"""Discover local docs and source with ``python -m webuse.resources``.

Uses the crawler's Python installation; no model discovery or network access.
"""

import json
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def documentation_root() -> Path | None:
    package = Path(__file__).resolve().parent
    # Editable installs use live website sources, even after a release build.
    checkout = package.parent.parent
    source_docs = checkout / "docs" / "src" / "content" / "docs"
    if (
        package.parent.name == "src"
        and (checkout / "pyproject.toml").is_file()
        and (source_docs / "index.md").is_file()
    ):
        return source_docs
    bundled = package / "_docs"
    return bundled if (bundled / "index.md").is_file() else None


def framework_info() -> dict:
    """Return an index of version-matched resources, without dumping their text."""
    package = Path(__file__).resolve().parent
    root = documentation_root()
    try:
        installed_version = version("webuse")
    except PackageNotFoundError:
        installed_version = "unknown"
    pages = []
    if root:
        for path in sorted(root.rglob("*.md")):
            title = re.search(
                r"^title:\s*(.+)$", path.read_text(encoding="utf-8"), re.M
            )
            pages.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "title": title[1].strip("\"'") if title else path.stem,
                }
            )
    return {
        "version": installed_version,
        "python": sys.executable,
        "source": str(package),
        "docs": {"root": str(root), "pages": pages} if root else None,
        "docs_error": None
        if root
        else "Webuse documentation is missing; reinstall a release containing bundled docs.",
        "capabilities": [
            "project creation and spider generation",
            "YAML and Python spiders",
            "synchronous and asynchronous crawling",
            "CSS and LLM extraction",
            "item pipelines",
            "agentic crawling",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(framework_info(), indent=2 if sys.stdout.isatty() else None))
