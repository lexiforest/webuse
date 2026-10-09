import asyncio
import importlib
import threading
import time
from collections import defaultdict

import pytest

from webuse import AsyncSpider, ConfigError, Response, SignalBus, Spider, acrawl, crawl
from webuse import llm
from webuse.cli.crawl import _configure_project_logging, _load_spider
from webuse.config import load_config_file
from webuse.crawl import FileRequestQueue, FileRequestSeen
from webuse.log import configure_logger, logger
from webuse.smart import SmartSelectorStore
from webuse.spider.config import ProjectConfig, SpiderConfig


class Client:
    def request(self, method, url, **kwargs):
        return Response(url=url, status_code=200, content=b"<h1>page</h1>")


class AsyncClient:
    async def request(self, *args, **kwargs):
        return Client().request(*args, **kwargs)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_parse_failure_propagates_and_emits_error_signals(asynchronous):
    events = []
    bus = SignalBus()
    for name in ("parse_error", "crawl_error", "crawl_finished"):
        bus.connect(name, lambda event=name, **kwargs: events.append((event, kwargs)))

    def fail(response):
        raise ValueError("bad parser")

    with pytest.raises(ValueError, match="bad parser"):
        if asynchronous:
            asyncio.run(
                asyncio.wait_for(
                    acrawl(
                        "https://example.com",
                        client=AsyncClient(),
                        extract=fail,
                        signals=bus,
                    ),
                    1,
                )
            )
        else:
            crawl("https://example.com", client=Client(), extract=fail, signals=bus)
    assert [event for event, _ in events] == [
        "parse_error",
        "crawl_error",
        "crawl_finished",
    ]
    assert events[-1][1]["reason"] == "error"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_download_errors_are_recorded_and_state_signals_are_emitted(
    asynchronous, tmp_path
):
    events = defaultdict(list)
    bus = SignalBus()
    for name in ("request_error", "state_loaded", "state_updated"):
        bus.connect(name, lambda event=name, **kwargs: events[event].append(kwargs))

    class Failing(Client):
        def request(self, *args, **kwargs):
            raise RuntimeError("download failed")

    class AsyncFailing:
        async def request(self, *args, **kwargs):
            return Failing().request(*args, **kwargs)

    if asynchronous:
        result = asyncio.run(
            acrawl("https://example.com", client=AsyncFailing(), signals=bus)
        )
    else:
        result = crawl(
            "https://example.com",
            client=Failing(),
            signals=bus,
            request_queue=FileRequestQueue(tmp_path / "queue.jsonl"),
            request_seen=FileRequestSeen(tmp_path / "seen.jsonl"),
        )
        assert FileRequestQueue(tmp_path / "queue.jsonl").empty()
    assert result.stats.errors == 1
    assert len(events["request_error"]) == 1
    assert events["state_loaded"][0]["queue_size"] == 0
    assert events["state_updated"][-1]["queue_size"] == 0
    assert events["state_updated"][-1]["seen_size"] == 1


@pytest.mark.parametrize("asynchronous", [False, True])
def test_per_domain_limit_is_enforced(asynchronous):
    active = defaultdict(int)
    peaks = defaultdict(int)
    lock = threading.Lock()
    urls = [
        f"https://{host}.example/{index}" for index in range(4) for host in ("a", "b")
    ]

    def enter(url):
        host = url.split("/")[2]
        with lock:
            active[host] += 1
            peaks[host] = max(peaks[host], active[host])
        return host

    class Limited(Client):
        def request(self, method, url, **kwargs):
            host = enter(url)
            time.sleep(0.005)
            with lock:
                active[host] -= 1
            return super().request(method, url, **kwargs)

    class AsyncLimited:
        async def request(self, method, url, **kwargs):
            host = enter(url)
            await asyncio.sleep(0.005)
            active[host] -= 1
            return Client().request(method, url, **kwargs)

    if asynchronous:
        result = asyncio.run(
            acrawl(urls, client=AsyncLimited(), concurrency=4, per_domain=1)
        )
    else:
        result = crawl(urls, client=Limited(), concurrency=4, per_domain=1)
    assert result.stats.fetched == len(urls)
    assert dict(peaks) == {"a.example": 1, "b.example": 1}


def test_async_worker_failure_does_not_hang_join():
    class Hasher:
        def hash(self, request):
            raise ValueError("invalid request")

    async def run():
        with pytest.raises(ValueError, match="invalid request"):
            await asyncio.wait_for(
                acrawl(
                    "https://example.com", client=AsyncClient(), request_hasher=Hasher()
                ),
                1,
            )
        assert not [
            task for task in asyncio.all_tasks() if task is not asyncio.current_task()
        ]

    asyncio.run(run())


def test_async_follow_callback_can_return_one_relative_url():
    async def follow(response):
        return "/next"

    result = asyncio.run(
        acrawl("https://example.com", client=AsyncClient(), follow=follow, max_depth=1)
    )
    assert result.visited == {"https://example.com/", "https://example.com/next"}


def test_project_concurrency_precedence():
    project = ProjectConfig(concurrency={"limit": 2, "per_domain": 1})

    def settings(spider, **overrides):
        return spider._resolve_settings(overrides, project_config=project)[0]

    assert settings(Spider()).concurrency == 2
    assert settings(Spider()).per_domain == 1

    class Custom(Spider):
        concurrency = 3

    assert settings(Custom()).concurrency == 3
    spider = Custom(spider_config=SpiderConfig(concurrency=4))
    assert settings(spider).concurrency == 4
    assert settings(spider, concurrency=5).concurrency == 5
    with pytest.raises(ValueError):
        ProjectConfig(concurrency={"per_domain": 0})


@pytest.mark.parametrize("asynchronous", [False, True])
def test_project_llm_settings_are_scoped_to_run(asynchronous, tmp_path, monkeypatch):
    defaults = llm.OpenAISettings(
        model="global", api_key="test", base_url="https://global.invalid/v1"
    )
    monkeypatch.setattr(llm, "_DEFAULT_SETTINGS", defaults)
    (tmp_path / "webuse.yaml").write_text(
        "llm:\n  model: project\n  api_key: test\n  base_url: https://project.invalid/v1\n"
    )
    base = AsyncSpider if asynchronous else Spider

    class Example(base):
        start_urls = ["https://example.com"]

        def parse(self, response):
            return {"model": llm.openai_defaults().model}

    spider = Example(project_dir=tmp_path)
    if asynchronous:
        result = asyncio.run(spider.run(client=AsyncClient()))
    else:
        result = spider.run(client=Client())
    assert result.items == [{"model": "project"}]
    assert llm.openai_defaults() == defaults


def test_async_llm_contexts_do_not_leak(monkeypatch):
    monkeypatch.setattr(llm, "_DEFAULT_SETTINGS", llm.OpenAISettings())

    async def run(model):
        with llm.use_openai_settings(
            {"model": model, "api_key": "test", "base_url": "https://example.invalid"}
        ):
            await asyncio.sleep(0)
            return llm.openai_defaults().model

    async def both():
        return await asyncio.gather(run("a"), run("b"))

    assert asyncio.run(both()) == ["a", "b"]
    assert llm.openai_defaults().model is None


def test_project_logging_applies_path_level_and_append(tmp_path):
    path = tmp_path / "logs" / "crawl.log"
    (tmp_path / "webuse.yaml").write_text(
        "log:\n  file: logs/crawl.log\n  level: warning\n  append: false\n"
    )
    try:
        _configure_project_logging(tmp_path)
        logger.info("hidden")
        logger.warning("first")
        assert "first" in path.read_text()
        assert "hidden" not in path.read_text()
        _configure_project_logging(tmp_path)
        logger.warning("second")
        assert "first" not in path.read_text()
        assert "second" in path.read_text()
    finally:
        configure_logger()


@pytest.mark.parametrize("suffix", ["yaml", "toml"])
def test_async_config_file_loads_async_spider(tmp_path, suffix):
    path = tmp_path / f"spider.{suffix}"
    path.write_text(
        "start_urls: [https://example.com]"
        if suffix == "yaml"
        else 'start_urls = ["https://example.com"]'
    )
    spider = _load_spider(str(path), spider_class=AsyncSpider)
    assert isinstance(spider, AsyncSpider)
    assert asyncio.run(spider.run(client=AsyncClient())).stats.fetched == 1


def test_smart_store_configuration_precedence(tmp_path, monkeypatch):
    monkeypatch.setattr(
        importlib.import_module("webuse.config"),
        "USER_CONFIG_PATH",
        tmp_path / "absent.yaml",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEBUSE_SELECTOR_STORE", raising=False)
    assert SmartSelectorStore().path.as_posix() == ".webuse/selectors.json"
    (tmp_path / ".webuserc.yaml").write_text(
        "smart:\n  selector_store: configured.json\n"
    )
    assert SmartSelectorStore().path.name == "configured.json"
    monkeypatch.setenv("WEBUSE_SELECTOR_STORE", "environment.json")
    assert SmartSelectorStore().path.name == "environment.json"
    assert SmartSelectorStore("explicit.json").path.name == "explicit.json"


def test_config_loaders_share_mapping_validation(tmp_path):
    from webuse.cli.common import load_config
    from webuse.crawl.utils import load_config_file as crawl_load_config

    path = tmp_path / "config.yaml"
    path.write_text("- not a mapping")
    for loader in (load_config, load_config_file, crawl_load_config):
        with pytest.raises(ConfigError, match="must contain a mapping"):
            loader(str(path))
