# Load start URLs dynamically from common external sources.
#
# Run one of these examples with:
#
#   webuse crawl examples/start_urls.py:FileStartUrlsSpider -a start_urls_file=./start_urls.txt -o pages.jsonl
#   webuse crawl examples/start_urls.py:RedisStartUrlsSpider -a redis_url=redis://localhost:6379/0 -a redis_key=webuse:start_urls -o pages.jsonl
#   webuse crawl examples/start_urls.py:SQLiteStartUrlsSpider -a sqlite_database=./start_urls.sqlite -o pages.jsonl

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

import webuse


class PageItem(BaseModel):
    url: str
    title: str = ""


def clean_urls(values: Iterable[Any]) -> list[str]:
    urls: list[str] = []
    for value in values:
        if isinstance(value, bytes):
            value = value.decode()
        url = str(value).strip()
        if url and not url.startswith("#"):
            urls.append(url)
    return urls


def sql_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value


class PageTitleMixin:
    item_model = PageItem
    max_depth = 0

    def parse(self, response: webuse.Response):
        title = response.css_first("title")
        yield PageItem(
            url=response.url,
            title=title.text().strip() if title is not None else "",
        )


class FileStartUrlsSpider(PageTitleMixin, webuse.Spider):
    name = "file_start_urls"
    start_urls_file = "start_urls.txt"

    def start(self) -> list[str]:
        path = Path(self.start_urls_file)
        return clean_urls(path.read_text(encoding="utf-8").splitlines())


class RedisStartUrlsSpider(PageTitleMixin, webuse.Spider):
    name = "redis_start_urls"
    redis_url = "redis://localhost:6379/0"
    redis_key = "webuse:start_urls"
    redis_source = "list"

    def start(self) -> list[str]:
        try:
            from redis import Redis
        except ImportError as exc:
            raise RuntimeError(
                "Install redis with `uv add redis` to run RedisStartUrlsSpider"
            ) from exc

        client = Redis.from_url(self.redis_url, decode_responses=True)
        if self.redis_source == "set":
            values = client.smembers(self.redis_key)
        elif self.redis_source == "list":
            values = client.lrange(self.redis_key, 0, -1)
        else:
            raise ValueError("redis_source must be 'list' or 'set'")
        return clean_urls(values)


class SQLiteStartUrlsSpider(PageTitleMixin, webuse.Spider):
    name = "sqlite_start_urls"
    sqlite_database = "start_urls.sqlite"
    sqlite_table = "start_urls"
    sqlite_column = "url"

    def start(self) -> list[str]:
        table = sql_identifier(self.sqlite_table)
        column = sql_identifier(self.sqlite_column)
        query = (
            f"select {column} from {table} where {column} is not null order by rowid"
        )

        with sqlite3.connect(self.sqlite_database) as connection:
            rows = connection.execute(query).fetchall()
        return clean_urls(row[0] for row in rows)
