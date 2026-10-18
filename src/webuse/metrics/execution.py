"""Opt-in execution telemetry for crawlers launched by the local control plane."""

import json
import os
import socket
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .adapter import Metrics
from .client import Client
from ..signals import SignalBus


class ExecutionClient(Client):
    def __init__(self):
        super().__init__()
        self.totals = {}
        self.last_activity = time.time()

    def _send(self, line):
        try:
            super()._send(line)
        except OSError:
            pass  # An unavailable metrics receiver must not fail a crawl.

    def counter(self, bucket, value=1, tags=None):
        self.totals[bucket] = self.totals.get(bucket, 0) + value
        self.last_activity = time.time()
        super().counter(bucket, value, tags)


@contextmanager
def execution_metrics(spider, name):
    if os.environ.get("WEBUSE_METRICS_ENABLED") != "1":
        yield
        return
    client = ExecutionClient()
    try:
        host = socket.gethostbyname(os.environ.get("WEBUSE_STATSD_HOST", "127.0.0.1"))
        port = int(os.environ.get("WEBUSE_STATSD_PORT", "8125"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid StatsD port")
        client.init(host, port, "webuse")
    except (OSError, ValueError):
        # Keep final counts available even when UDP setup fails.
        client.init("127.0.0.1", 8125, "webuse")
    tags = {
        "webuse_instance": os.environ.get("WEBUSE_METRICS_INSTANCE", "local"),
        "project_id": os.environ.get("WEBUSE_PROJECT_ID", ""),
        "execution_id": os.environ.get("WEBUSE_EXECUTION_ID", ""),
        "spider": name,
    }
    original = spider.signals
    signals = original or SignalBus()
    spider.signals = signals
    adapter = Metrics(client=client, tags=tags).bind(signals)
    stopped = threading.Event()

    def sample():
        client.gauge("heartbeat", time.time(), tags)
        client.gauge("last_activity", client.last_activity, tags)
        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_SELF)
            client.gauge("process_cpu_seconds", usage.ru_utime + usage.ru_stime, tags)
            client.gauge(
                "process_peak_rss_bytes",
                usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                tags,
            )
        except ImportError:
            pass

    def monitor():
        while not stopped.wait(2):
            sample()

    # Seed cumulative series so the first observations have a zero baseline.
    for metric in (
        "request_finished",
        "request_error",
        "item_extracted",
        "item_processed",
        "item_dropped",
        "item_error",
        "parse_error",
        "pipeline_error",
    ):
        client.counter(metric, 0, tags)
    sample()
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=3)
        sample()
        client.close()
        for key, handlers in list(signals._handlers.items()):
            for handler in list(handlers):
                if getattr(handler, "__self__", None) is adapter:
                    signals.disconnect(key, handler)
        spider.signals = original
        path = os.environ.get("WEBUSE_METRICS_SUMMARY_PATH")
        if path:
            try:
                destination = Path(path)
                saved = (
                    json.loads(destination.read_text())
                    if destination.exists()
                    else {"spiders": [], "totals": {}}
                )
                saved["spiders"].append(name)
                for metric, count in client.totals.items():
                    saved["totals"][metric] = saved["totals"].get(metric, 0) + count
                saved["lastActivity"] = client.last_activity * 1000
                destination.write_text(json.dumps(saved))
            except (OSError, ValueError, TypeError):
                pass
