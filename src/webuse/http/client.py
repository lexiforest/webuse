"""curl_cffi sessions with Webuse's parsing-enabled response type."""

from functools import partial
from typing import Any

from curl_cffi import AsyncSession, Session

from .response import Response


class Client(Session[Response]):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("impersonate", "chrome")
        kwargs.setdefault("response_class", Response)
        super().__init__(**kwargs)


class AsyncClient(AsyncSession[Response]):
    def __init__(self, **kwargs: Any):
        kwargs.setdefault("impersonate", "chrome")
        kwargs.setdefault("response_class", Response)
        super().__init__(**kwargs)


def request(method: str, url: str, **kwargs: Any) -> Response:
    with Client() as client:
        return client.request(method, url, **kwargs)


async def arequest(method: str, url: str, **kwargs: Any) -> Response:
    async with AsyncClient() as client:
        return await client.request(method, url, **kwargs)


get = partial(request, "GET")
post = partial(request, "POST")
put = partial(request, "PUT")
delete = partial(request, "DELETE")
aget = partial(arequest, "GET")
apost = partial(arequest, "POST")
aput = partial(arequest, "PUT")
adelete = partial(arequest, "DELETE")
