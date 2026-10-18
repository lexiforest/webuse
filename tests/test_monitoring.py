import json
from types import SimpleNamespace

import pytest

from webuse import SignalBus
from webuse import monitoring
from webuse.metrics.execution import ExecutionClient, execution_metrics


def test_monitoring_connection_precedence(monkeypatch):
    monkeypatch.setenv("WEBUSE_PROMETHEUS_URL", "http://environment:9090")
    monkeypatch.setattr(
        monitoring,
        "load_webuse_config",
        lambda **kw: {"monitoring": {"prometheus_url": "http://file:9090"}},
    )
    assert monitoring.connection() == {
        "prometheusUrl": "http://environment:9090",
        "source": "environment",
    }
    monkeypatch.delenv("WEBUSE_PROMETHEUS_URL")
    assert monitoring.connection()["prometheusUrl"] == "http://file:9090"
    monkeypatch.setattr(
        monitoring, "load_webuse_config", lambda **kw: {"monitoring": []}
    )
    assert monitoring.connection()["prometheusUrl"] == ""
    monkeypatch.setattr(
        monitoring, "load_webuse_config", lambda **kw: {"monitoring": 5}
    )
    assert "error" in monitoring.connection()


def test_prometheus_transport(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "status": "success",
                "data": {"resultType": "matrix", "result": []},
                "warnings": ["partial data"],
            },
        )

    monkeypatch.setattr(monitoring.requests, "get", get)
    result = monitoring.query(
        "http://localhost:9090/prometheus/",
        {"query": "up", "start": 10, "end": 20, "step": 5, "ignored": True},
    )
    assert result["warnings"] == ["partial data"]
    assert calls[0][0] == "http://localhost:9090/prometheus/api/v1/query_range"
    assert calls[0][1] == {
        "params": {
            "query": "up",
            "start": 10,
            "end": 20,
            "step": 5,
            "timeout": "5s",
            "limit": 50,
        },
        "timeout": 7,
        "allow_redirects": False,
    }
    assert "error" in monitoring.query("file:///secret", {"query": "up"})
    assert "error" in monitoring.query("http://user:secret@localhost", {"query": "up"})
    assert len(calls) == 1


def test_execution_metrics_final_counts_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBUSE_METRICS_ENABLED", "1")
    monkeypatch.setenv("WEBUSE_PROJECT_ID", "17")
    monkeypatch.setenv("WEBUSE_EXECUTION_ID", "29")
    monkeypatch.setenv("WEBUSE_METRICS_INSTANCE", "database-a")
    destination = tmp_path / "metrics.json"
    monkeypatch.setenv("WEBUSE_METRICS_SUMMARY_PATH", str(destination))
    lines = []
    monkeypatch.setattr(ExecutionClient, "_send", lambda self, line: lines.append(line))
    signals = SignalBus()
    calls = []
    signals.connect("item_processed", lambda **kw: calls.append(kw))
    spider = SimpleNamespace(signals=signals)
    with execution_metrics(spider, "books"):
        request = object()
        signals.send("request_before_downloader", request=request)
        signals.send("request_after_downloader", request=request, success=True)
        signals.send(
            "response_received",
            response=SimpleNamespace(status_code=200, content=b"abc"),
        )
        signals.send("item_processed", item={"title": "Book"})
    result = json.loads(destination.read_text())
    assert result["totals"]["request_finished"] == 1
    assert result["totals"]["downloaded_bytes"] == 3
    assert result["totals"]["item_processed"] == 1
    assert result["spiders"] == ["books"]
    assert all(
        "project_id:17" in line
        and "execution_id:29" in line
        and "webuse_instance:database-a" in line
        for line in lines
    )
    assert any("request_duration:" in line and "|ms" in line for line in lines)
    count = len(lines)
    signals.send("item_processed", item={})
    assert len(lines) == count
    assert len(calls) == 2
    with pytest.raises(RuntimeError), execution_metrics(spider, "second"):
        raise RuntimeError("crawler failed")
    assert json.loads(destination.read_text())["spiders"] == ["books", "second"]
    assert spider.signals is signals


def test_execution_metrics_disabled(monkeypatch):
    monkeypatch.delenv("WEBUSE_METRICS_ENABLED", raising=False)
    spider = SimpleNamespace(signals=None)
    with execution_metrics(spider, "books"):
        assert spider.signals is None


def test_missing_udp_receiver_does_not_fail_crawl(monkeypatch):
    from webuse.metrics.client import Client

    def unavailable(self, line):
        raise OSError("unreachable")

    monkeypatch.setattr(Client, "_send", unavailable)
    client = ExecutionClient()
    client.counter("request_finished", 1)
    assert client.totals["request_finished"] == 1
