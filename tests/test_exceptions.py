import pytest

import webuse
from webuse.crawl.utils import follow_rule_from_config, load_config_file
from webuse.pipelines import JsonlPipeline, resolve_pipeline
from webuse.spider import Spider


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
