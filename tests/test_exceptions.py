import pytest

import webuse
from webuse.crawl.utils import follow_rule_from_config, load_config_file
from webuse.pipelines import JsonlPipeline, resolve_pipeline
from webuse.spider import Spider


def test_public_exception_hierarchy():
    assert issubclass(webuse.SmartSelectorError, webuse.WebuseError)
    assert issubclass(webuse.ConfigError, webuse.WebuseError)
    assert issubclass(webuse.SpiderError, webuse.WebuseError)
    assert issubclass(webuse.PipelineError, webuse.WebuseError)
    assert issubclass(webuse.PipelineStateError, webuse.PipelineError)
    assert issubclass(webuse.SignalError, webuse.WebuseError)
    assert issubclass(webuse.DropItem, webuse.PipelineError)
    assert issubclass(webuse.IgnoreRequest, webuse.WebuseError)
    assert issubclass(webuse.CloseSpider, webuse.WebuseError)
    assert issubclass(webuse.NotConfigured, webuse.ConfigError)
    assert issubclass(webuse.NotSupported, webuse.WebuseError)


def test_close_spider_carries_reason():
    exc = webuse.CloseSpider("quota")

    assert exc.reason == "quota"


def test_config_errors_use_webuse_error(tmp_path):
    with pytest.raises(webuse.ConfigError):
        load_config_file(tmp_path / "missing.toml")
    with pytest.raises(webuse.ConfigError):
        follow_rule_from_config(123)


def test_spider_errors_use_webuse_error():
    with pytest.raises(webuse.SpiderError):
        Spider(unknown=True)


def test_pipeline_errors_use_webuse_error():
    with pytest.raises(webuse.PipelineError):
        resolve_pipeline({"type": "missing"})
    with pytest.raises(webuse.PipelineError):
        resolve_pipeline("missing.module.Pipeline")
    with pytest.raises(webuse.PipelineStateError):
        JsonlPipeline().process_item({"title": "x"})
