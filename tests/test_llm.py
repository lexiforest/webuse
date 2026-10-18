from types import SimpleNamespace

import pytest

from webuse import cli
from webuse import llm


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)


def _reset(monkeypatch):
    monkeypatch.delenv("WEBUSE_LOCAL_MODEL_HOST", raising=False)
    monkeypatch.setattr(llm, "_DEFAULT_SETTINGS", None)
    monkeypatch.delenv("WEBUSE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("WEBUSE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("WEBUSE_LLM_MODEL", raising=False)
    monkeypatch.delenv("WEBUSE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_PROVIDER", raising=False)


def test_openai_defaults_use_configured_environment_without_local_probe(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    def fail_get(*args, **kwargs):
        raise AssertionError("local endpoints should not be probed")

    monkeypatch.setattr(llm.requests, "get", fail_get)

    settings = llm.configure_openai_defaults()

    assert settings.provider == "openai"
    assert settings.api_key == "test-key"
    assert settings.base_url == "https://api.example.com/v1"
    assert settings.model == "test-model"


def test_openai_defaults_use_config_file_precedence(monkeypatch, tmp_path):
    _reset(monkeypatch)
    home = tmp_path / "home"
    work = tmp_path / "work"
    config_dir = home / ".config" / "webuse"
    config_dir.mkdir(parents=True)
    work.mkdir()
    (config_dir / "config.yaml").write_text(
        """
llm:
  api_key: user-key
  base_url: https://user.example.com/v1
  model: user-model
""",
        encoding="utf-8",
    )
    (work / ".webuserc.yaml").write_text(
        """
llm:
  base_url: https://local.example.com/v1
  model: local-model
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    def fail_get(*args, **kwargs):
        raise AssertionError("local endpoints should not be probed")

    monkeypatch.setattr(llm.requests, "get", fail_get)

    settings = llm.configure_openai_defaults()

    assert settings.provider == "openai"
    assert settings.api_key == "user-key"
    assert settings.base_url == "https://local.example.com/v1"
    assert settings.model == "env-model"


def test_openai_defaults_detect_local_lmstudio(monkeypatch):
    _reset(monkeypatch)
    seen_urls = []

    def fake_get(url, **kwargs):
        seen_urls.append(url)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"data": [{"id": "local-model"}]},
        )

    monkeypatch.setattr(llm.requests, "get", fake_get)

    settings = llm.configure_openai_defaults()

    assert seen_urls == ["http://127.0.0.1:1234/v1/models"]
    assert settings.provider == "lmstudio"
    assert settings.api_key == "lm-studio"
    assert settings.base_url == "http://127.0.0.1:1234/v1"
    assert settings.model == "local-model"


def test_openai_settings_from_config_does_not_probe_when_complete(monkeypatch):
    _reset(monkeypatch)

    def fail_get(*args, **kwargs):
        raise AssertionError("local endpoints should not be probed")

    monkeypatch.setattr(llm.requests, "get", fail_get)

    settings = llm.openai_settings_from_config(
        {
            "model": "configured-model",
            "api_key": "configured-key",
            "base_url": "https://llm.example.com/v1",
        }
    )

    assert settings.provider == "config"
    assert settings.api_key == "configured-key"
    assert settings.base_url == "https://llm.example.com/v1"
    assert settings.model == "configured-model"


def test_cli_startup_detects_local_openai_defaults_for_llm(monkeypatch, capsys):
    _reset(monkeypatch)
    captured = {}

    def fake_get(url, **kwargs):
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"data": [{"id": "local-model"}]},
        )

    class FakeResponse:
        url = "https://example.com"

        def llm_extract(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return ["Local answer"]

    monkeypatch.setattr(llm.requests, "get", fake_get)
    monkeypatch.setattr(
        "webuse.cli.fetch.request", lambda *args, **kwargs: FakeResponse()
    )

    code = cli.main(
        [
            "fetch",
            "https://example.com",
            "--llm-extract",
            "Extract title",
            "--schema",
            '{"type":"array","items":{"type":"string"}}',
        ]
    )
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == '[\n  "Local answer"\n]'
    assert captured["prompt"] == "Extract title"
    assert captured["kwargs"]["model"] == "local-model"
    assert captured["kwargs"]["api_key"] == "lm-studio"
    assert captured["kwargs"]["base_url"] == "http://127.0.0.1:1234/v1"


def test_discover_all_local_models_and_docker_host(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("WEBUSE_LOCAL_MODEL_HOST", "host.docker.internal")
    seen = []

    def get(url, **kwargs):
        seen.append(url)
        assert kwargs["allow_redirects"] is False
        models = (
            ["studio-a", "studio-b", "studio-a"] if ":1234/" in url else ["ollama-a"]
        )
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "data": [{"id": model} for model in models] + [None, {}, {"id": ""}]
            },
        )

    monkeypatch.setattr(llm.requests, "get", get)
    models = llm.discover_local_openai_settings()
    assert [model.model for model in models] == ["studio-a", "studio-b", "ollama-a"]
    assert seen == [
        "http://host.docker.internal:1234/v1/models",
        "http://host.docker.internal:11434/v1/models",
    ]


def test_discovery_skips_unavailable_or_malformed_servers(monkeypatch):
    _reset(monkeypatch)

    def get(url, **kwargs):
        if ":1234/" in url:
            raise OSError("offline")
        return SimpleNamespace(status_code=200, json=lambda: {"data": "invalid"})

    monkeypatch.setattr(llm.requests, "get", get)
    assert llm.discover_local_openai_settings() == []
    assert llm.detect_local_openai_settings() is None


def test_model_listing_passes_credentials_without_redirects(monkeypatch):
    def get(url, **kwargs):
        assert url == "https://model.example/v1/models"
        assert kwargs["headers"] == {"Authorization": "Bearer test-key"}
        assert kwargs["allow_redirects"] is False
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"data": [{"id": "a"}, {"id": "a"}, {"id": "b"}]},
        )

    monkeypatch.setattr(llm.requests, "get", get)
    assert llm.openai_model_ids("https://model.example/v1/", "test-key") == ["a", "b"]
