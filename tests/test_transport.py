import asyncio

import pytest
from curl_cffi import AsyncSession, Session
from curl_cffi.requests import Headers, Response as CurlResponse
from curl_cffi.requests.exceptions import HTTPError

import webuse
from webuse import AsyncClient, Client, Response


def test_transport_default_is_owned_by_client():
    with Client() as client:
        assert client.impersonate == "chrome"

    async def run():
        async with AsyncClient() as client:
            assert client.impersonate == "chrome"

    asyncio.run(run())
    request = webuse.CrawlRequest(url="https://example.com")
    restored = webuse.CrawlRequest.model_validate_json(request.model_dump_json())
    assert "impersonate" not in restored.options.to_request_kwargs()
    followed = Response(url=request.url).follow("/next", timeout=10)
    assert followed.options.to_request_kwargs() == {"timeout": 10}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_native_sessions_preserve_headers_and_add_lazy_parsing(tmp_path, asynchronous):
    path = tmp_path / "page.html"
    path.write_bytes(b'<h1>hello</h1><a href="next.html">next</a>')
    kwargs = {"headers": {"X-Default": "kept"}, "impersonate": "safari", "retry": 1}

    async def run():
        async with AsyncClient(**kwargs) as client:
            assert isinstance(client, AsyncSession)
            return await client.get(path.as_uri(), headers={"X-Request": "added"})

    if asynchronous:
        response = asyncio.run(run())
    else:
        with Client(**kwargs) as client:
            assert isinstance(client, Session)
            response = client.get(path.as_uri(), headers={"X-Request": "added"})
    assert isinstance(response, Response)
    assert isinstance(response, CurlResponse)
    assert response.request.headers["x-default"] == "kept"
    assert response.request.headers["x-request"] == "added"
    assert response._tree is None
    assert response.find(css="h1").text() == "hello"
    assert response.links() == [path.with_name("next.html").as_uri()]


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_native_streaming_uses_response_type_and_closes(tmp_path, asynchronous, fail):
    path = tmp_path / "payload.json"
    path.write_bytes(b'{"ok":true}')
    responses = []

    def consume(response, body):
        assert isinstance(response, Response)
        assert body == path.read_bytes()
        if fail:
            raise ValueError("consumer failed")

    async def arun():
        async with AsyncClient() as client:
            async with client.stream("GET", path.as_uri()) as response:
                responses.append(response)
                consume(
                    response,
                    b"".join([chunk async for chunk in response.aiter_content()]),
                )

    def run():
        if asynchronous:
            asyncio.run(arun())
        else:
            with Client() as client:
                with client.stream("GET", path.as_uri()) as response:
                    responses.append(response)
                    consume(response, b"".join(response.iter_content()))

    if fail:
        with pytest.raises(ValueError, match="consumer failed"):
            run()
    else:
        run()
    if asynchronous:
        assert responses[0].astream_task.done()
    else:
        assert responses[0]._stream_closed


def test_native_response_decoding_headers_json_and_http_errors():
    response = Response(content=b"<h1>caf\xe9</h1>", status_code=404)
    response.headers = Headers({"Content-Type": "text/html; charset=iso-8859-1"})
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == "<h1>caf\u00e9</h1>"
    assert response.find(css="h1").text() == "caf\u00e9"
    with pytest.raises(HTTPError):
        response.raise_for_status()
    assert Response(content=b'{"ok":true}').json() == {"ok": True}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_crawl_keeps_native_request_and_session_defaults(tmp_path, asynchronous):
    path = tmp_path / "page.html"
    path.write_bytes(b"<h1>hello</h1>")
    options = {
        "request_defaults": {"headers": {"X-Default": "kept"}},
        "extract": {"default": {"page": {"fields": {"title": "h1"}}}},
    }
    if asynchronous:
        result = asyncio.run(webuse.acrawl(path.as_uri(), **options))
    else:
        result = webuse.crawl(path.as_uri(), **options)
    assert result.items == [{"title": "hello", "_type": "page"}]
    response = result.pages[0]
    assert response.request.headers["X-Default"] == "kept"
    assert response.crawl_request.url == path.as_uri()
    assert response.crawl_request is not response.request


@pytest.mark.parametrize("asynchronous", [False, True])
def test_top_level_helpers_use_parsing_response(tmp_path, asynchronous):
    path = tmp_path / "page.html"
    path.write_bytes(b"<h1>hello</h1>")
    response = (
        asyncio.run(webuse.aget(path.as_uri()))
        if asynchronous
        else webuse.get(path.as_uri())
    )
    assert response.find(css="h1").text() == "hello"


@pytest.mark.parametrize(
    "concurrency,defaults,expected",
    [(1, {}, 1), (25, {}, 25), (0, {}, 1), (25, {"max_clients": 3}, 3)],
)
def test_acrawl_transport_capacity_matches_workers(
    monkeypatch, concurrency, defaults, expected
):
    async def run():
        active = 0
        peak = 0
        full = asyncio.Event()

        async def request(client, method, url, **kwargs):
            nonlocal active, peak
            # Exercise curl_cffi's real handle pool without network traffic.
            handle = await client.pop_curl()
            try:
                active += 1
                peak = max(peak, active)
                if active == expected:
                    full.set()
                await full.wait()
                await asyncio.sleep(0)
                return Response(url=url, status_code=200, content=b"<h1>hello</h1>")
            finally:
                active -= 1
                client.push_curl(handle)

        monkeypatch.setattr(AsyncClient, "request", request)
        original_defaults = defaults.copy()
        result = await asyncio.wait_for(
            webuse.acrawl(
                [f"https://example.com/{index}" for index in range(30)],
                concurrency=concurrency,
                request_defaults=defaults,
            ),
            timeout=2,
        )
        assert peak == expected
        assert result.stats.fetched == 30
        assert defaults == original_defaults

    asyncio.run(run())
