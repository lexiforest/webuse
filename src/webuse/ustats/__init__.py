# Vendored from the `ustats` statsd client (MIT, Copyright (c) lexiforest) to
# keep webuse self-contained. `aio_udp.py` is adapted from a gist by vxgmichel
# (https://gist.github.com/vxgmichel/e47bff34b68adb3cf6bd4845c4bed448).

__all__ = [
    "ainit",
    "init",
    "counter",
    "gauge",
    "timer",
    "sets",
    "send",
    "StopWatch",
    "timing",
]


import socket
import warnings
from abc import abstractmethod
from contextlib import contextmanager
from functools import partial, partialmethod
from time import perf_counter
from typing import Literal, Optional, Union

from .aio_udp import connect

MetricType = Literal["c", "ms", "g", "s"]


def _format(prefix, bucket, value, tags, metric_type) -> str:
    # It's typical for python to use seconds, not ms
    if metric_type == "ms":
        value *= 1000
    line = f"{prefix}.{bucket}:{value}|{metric_type}"
    if tags:
        line += "|#" + ",".join([f"{k}:{v}" for k, v in tags.items()])
    return line


class BaseClient:
    def __init__(self):
        self._sock = None
        self._prefix = ""

    @abstractmethod
    def _send(self, line: str):
        raise NotImplementedError()

    def send(
        self,
        bucket: str,
        value: Union[int, float, str],
        tags: Optional[dict] = None,
        metric_type: MetricType = "c",
    ):
        line = _format(self._prefix, bucket, value, tags, metric_type)
        self._send(line)

    def gauge(
        self,
        bucket: str,
        value: Union[int, float],
        tags: Optional[dict] = None,
    ):
        """statsd protocol is too stupid, which uses signed value as delta values.
        For negative values, we need to set it to 0 first.
        """
        line_value = _format(self._prefix, bucket, value, tags, metric_type="g")
        if value < 0:
            line_0 = _format(self._prefix, bucket, 0, tags, metric_type="g")
            line = line_0 + "\n" + line_value
        else:
            line = line_value
        self._send(line)

    def incr(
        self,
        bucket: str,
        value: Union[int, float],
        tags: Optional[dict] = None,
    ):
        signed_value = f"{value:+}"
        self.send(bucket, signed_value, tags, metric_type="g")

    def decr(
        self,
        bucket: str,
        value: Union[int, float],
        tags: Optional[dict] = None,
    ):
        self.incr(bucket, -value, tags)

    counter = partialmethod(send, metric_type="c")
    timer = partialmethod(send, metric_type="ms")
    sets = partialmethod(send, metric_type="s")


class AsyncClient(BaseClient):
    async def ainit(self, host: str = "127.0.0.1", port: int = 8125, prefix: str = ""):
        self._sock = await connect(host, port)
        self._prefix = prefix

    def _send(self, line: str):
        if self._sock is None:
            raise RuntimeError("Metric sock is not initialized. call ainit() first.")
        self._sock.send(line.encode())

    async def _recv(self) -> bytes:
        assert self._sock
        data, _ = await self._sock.recv()
        return data


class Client(BaseClient):
    def __init__(self):
        self._sock = None
        self._prefix = ""

    def init(self, host: str = "127.0.0.1", port: int = 8125, prefix: str = ""):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._host = host
        self._port = port
        self._prefix = prefix

    def _send(self, line: str):
        if self._sock is None:
            raise RuntimeError("Metric sock is not initialized. call init() first.")
        self._sock.sendto(line.encode(), (self._host, self._port))

    def _recv(self) -> bytes:
        assert self._sock
        data, _ = self._sock.recvfrom(2048)
        return data


_client: Optional[BaseClient] = None


def init(host: str = "127.0.0.1", port: int = 8125, prefix: str = ""):
    global _client
    if _client is not None:
        warnings.warn("Reinitializing global client.", stacklevel=2)
    _client = Client()
    _client.init(host, port, prefix)


async def ainit(host: str = "127.0.0.1", port: int = 8125, prefix: str = ""):
    global _client
    if _client is not None:
        warnings.warn("Reinitializing global client.", stacklevel=2)
    _client = AsyncClient()
    await _client.ainit(host, port, prefix)


def send(
    bucket: str,
    value: Union[int, float],
    tags: Optional[dict] = None,
    metric_type: MetricType = "c",
):
    assert _client, "Client not initialized"
    _client.send(bucket, value, tags, metric_type)


counter = partial(send, metric_type="c")
timer = partial(send, metric_type="ms")
sets = partial(send, metric_type="s")


def gauge(
    bucket: str,
    value: Union[int, float],
    tags: Optional[dict] = None,
):
    assert _client, "Client not initialized"
    _client.gauge(bucket, value, tags)


def incr(
    bucket: str,
    value: Union[int, float],
    tags: Optional[dict] = None,
):
    assert _client, "Client not initialized"
    _client.incr(bucket, value, tags)


def decr(
    bucket: str,
    value: Union[int, float],
    tags: Optional[dict] = None,
):
    assert _client, "Client not initialized"
    _client.decr(bucket, value, tags)


class StopWatch:
    def __init__(self, name: str):
        self._name = name
        self._time = perf_counter()

    def time(self, tags: Optional[dict] = None):
        duration = perf_counter() - self._time
        timer(self._name, duration, tags)


@contextmanager
def timing(bucket: str, tags: Optional[dict] = None):
    start = perf_counter()
    try:
        yield None
    finally:
        timer(bucket, perf_counter() - start, tags)
