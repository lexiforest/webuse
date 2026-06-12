from types import SimpleNamespace

from webuse import cli
from webuse import llm


def _reset(monkeypatch):
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

        def smart(self, prompt, **kwargs):
            captured["prompt"] = prompt
            captured["kwargs"] = kwargs
            return ["Local answer"]

    monkeypatch.setattr(llm.requests, "get", fake_get)
    monkeypatch.setattr(cli, "request", lambda *args, **kwargs: FakeResponse())

    code = cli.main(["fetch", "https://example.com", "--smart", "Extract title"])
    out = capsys.readouterr().out.strip()

    assert code == 0
    assert out == (
        "{\n"
        '  "url": "https://example.com",\n'
        '  "matches": [\n'
        '    "Local answer"\n'
        "  ],\n"
        '  "selector": "Extract title"\n'
        "}"
    )
    assert captured["prompt"] == "Extract title"
    assert captured["kwargs"]["translate_xpath"] is False
    assert captured["kwargs"]["model"] == "local-model"
    assert captured["kwargs"]["api_key"] == "lm-studio"
    assert captured["kwargs"]["base_url"] == "http://127.0.0.1:1234/v1"
