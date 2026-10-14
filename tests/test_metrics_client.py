import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

import webuse
from webuse import metrics
from webuse.metrics import client as metrics_client


def test_async_metrics_transport_emission_and_lifecycle(monkeypatch):
    async def run():
        first = Mock(spec=asyncio.DatagramTransport)
        second = Mock(spec=asyncio.DatagramTransport)
        first.is_closing.return_value = False
        second.is_closing.return_value = False
        endpoint = AsyncMock(side_effect=[(first, None), (second, None)])
        monkeypatch.setattr(asyncio.get_running_loop(), "create_datagram_endpoint", endpoint)
        client = metrics.AsyncClient()
        with pytest.raises(RuntimeError, match="ainit"):
            client.counter("pages", 1)

        await client.ainit("localhost", 8126, prefix="crawl")
        assert endpoint.call_args.kwargs == {"remote_addr": ("localhost", 8126)}
        signals = webuse.SignalBus()
        metrics.attach_metrics(signals, client=client)
        await signals.asend("request_queued", source="start")
        first.sendto.assert_called_once_with(b"crawl.request_queued:1|c|#source:start")
        client.timer("duration", 0.5)
        first.sendto.assert_called_with(b"crawl.duration:500.0|ms")

        await client.ainit(prefix="next")
        first.close.assert_called_once_with()
        client.gauge("active", 2)
        second.sendto.assert_called_once_with(b"next.active:2|g")
        client.close()
        client.close()
        second.close.assert_called_once_with()
        with pytest.raises(RuntimeError, match="ainit"):
            client.counter("pages", 1)

    asyncio.run(run())


def test_sync_metrics_socket_cleanup(monkeypatch):
    first, second = Mock(), Mock()
    monkeypatch.setattr(metrics_client.socket, "socket", Mock(side_effect=[first, second]))
    client = metrics.Client()
    client.init(prefix="crawl")
    client.counter("pages", 1)
    first.sendto.assert_called_once_with(b"crawl.pages:1|c", ("127.0.0.1", 8125))
    client.init()
    first.close.assert_called_once_with()
    client.close()
    client.close()
    second.close.assert_called_once_with()
    with pytest.raises(RuntimeError, match="init"):
        client.counter("pages", 1)


def test_global_metrics_reinitialization_and_failed_setup(monkeypatch):
    async def run():
        sock = Mock()
        transport = Mock(spec=asyncio.DatagramTransport)
        transport.is_closing.return_value = False
        endpoint = AsyncMock(side_effect=[OSError("setup failed"), (transport, None)])
        monkeypatch.setattr(asyncio.get_running_loop(), "create_datagram_endpoint", endpoint)
        monkeypatch.setattr(metrics_client.socket, "socket", Mock(return_value=sock))
        monkeypatch.setattr(metrics_client, "_client", None)
        metrics.init(prefix="sync")
        try:
            with pytest.warns(UserWarning, match="Reinitializing"):
                with pytest.raises(OSError, match="setup failed"):
                    await metrics.ainit()
            sock.close.assert_not_called()
            metrics.counter("pages", 1)
            sock.sendto.assert_called_once_with(b"sync.pages:1|c", ("127.0.0.1", 8125))

            with pytest.warns(UserWarning, match="Reinitializing"):
                await metrics.ainit(prefix="async")
            sock.close.assert_called_once_with()
            metrics.counter("pages", 2)
            transport.sendto.assert_called_once_with(b"async.pages:2|c")
        finally:
            metrics.close()
        metrics.close()
        transport.close.assert_called_once_with()
        assert metrics_client._client is None

    asyncio.run(run())
