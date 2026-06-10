from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class CliProject:
    root: Path

    @property
    def spiders(self) -> Path:
        return self.root / "spiders"

    def write_spider(self, source: str, name: str = "books.py") -> Path:
        path = self.spiders / name
        path.write_text(source, encoding="utf-8")
        return path

    def write_default_spider(self, name: str = "books.py", **kwargs) -> Path:
        return self.write_spider(spider_source(**kwargs), name=name)

    def make_package(self) -> None:
        (self.root / "__init__.py").write_text("", encoding="utf-8")
        (self.spiders / "__init__.py").write_text("", encoding="utf-8")


@pytest.fixture
def cli_project(tmp_path: Path) -> CliProject:
    project = tmp_path / "project"
    spiders = project / "spiders"
    spiders.mkdir(parents=True)
    (project / "webuse.toml").write_text('name = "project"\n', encoding="utf-8")
    return CliProject(project)


def spider_source(
    *,
    item_fields: str = "title: str",
    run_body: str = 'return CrawlResult(items=[Item(title="One")], stats=CrawlStats())',
    base: str = "webuse.Spider",
    async_run: bool = False,
) -> str:
    run_prefix = "async def" if async_run else "def"
    return f"""import webuse
from pydantic import BaseModel
from webuse.models import CrawlResult, CrawlStats


class Item(BaseModel):
    {item_fields}


class BooksSpider({base}):
    {run_prefix} run(self, **kwargs):
        {run_body}
"""
