"""Run the same declarative fixture as the Rust prototype against Python."""

import asyncio
import json
from pathlib import Path

from webuse import AsyncSpider, Response


def test_shared_rust_python_crawl_contract():
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "crates/webuse/tests/fixtures/core.json"
        ).read_text()
    )

    class Client:
        async def request(self, method, url, **kwargs):
            return Response(
                url=url, status_code=200, content=fixture["pages"][url].encode()
            )

    options = dict(fixture["config"])
    result = asyncio.run(
        AsyncSpider(**options).run(client=Client())
    )
    assert result.items == fixture["items"]
    assert result.stats.model_dump() == fixture["stats"]
    assert sorted(result.visited) == fixture["visited"]
