from dataclasses import dataclass
from typing import Any

from curl_cffi import requests

from .config import load_webuse_config


@dataclass(frozen=True)
class OpenAISettings:
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    provider: str | None = None


_LOCAL_OPENAI_ENDPOINTS = (
    ("lmstudio", "http://127.0.0.1:1234/v1", "lm-studio"),
    ("ollama", "http://127.0.0.1:11434/v1", "ollama"),
)
_DEFAULT_SETTINGS: OpenAISettings | None = None


def openai_configured() -> bool:
    return bool(load_webuse_config().get("llm"))


def configured_openai_settings() -> OpenAISettings:
    config = load_webuse_config().get("llm", {})
    return OpenAISettings(
        model=config.get("model"),
        api_key=config.get("api_key"),
        base_url=config.get("base_url"),
        provider=config.get("provider") or ("openai" if config else None),
    )


def openai_settings_from_config(config: dict[str, Any] | None) -> OpenAISettings:
    config = config or {}
    defaults: OpenAISettings | None = None

    def default_value(name: str) -> Any:
        nonlocal defaults
        if defaults is None:
            defaults = openai_defaults()
        return getattr(defaults, name)

    settings = OpenAISettings(
        model=config.get("model") or default_value("model"),
        api_key=config.get("api_key") or default_value("api_key"),
        base_url=config.get("base_url") or default_value("base_url"),
        provider=config.get("provider")
        or (defaults.provider if defaults is not None else "config"),
    )
    return settings


def create_openai_client(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    settings: OpenAISettings | None = None,
) -> Any:
    settings = settings or openai_defaults()
    api_key = api_key or settings.api_key
    base_url = base_url or settings.base_url
    from openai import OpenAI

    kwargs = {
        key: value
        for key, value in {"api_key": api_key, "base_url": base_url}.items()
        if value
    }
    return OpenAI(**kwargs)


def _model_id(payload: Any) -> str | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            return str(item["id"])
    return None


def detect_local_openai_settings(*, timeout: float = 0.2) -> OpenAISettings | None:
    for provider, base_url, api_key in _LOCAL_OPENAI_ENDPOINTS:
        try:
            response = requests.get(f"{base_url}/models", timeout=timeout)
        except Exception:
            continue
        if getattr(response, "status_code", 0) >= 400:
            continue
        try:
            model = _model_id(response.json())
        except Exception:
            model = None
        if model is None:
            continue
        return OpenAISettings(
            model=model,
            api_key=api_key,
            base_url=base_url,
            provider=provider,
        )
    return None


def configure_openai_defaults(*, force: bool = False) -> OpenAISettings:
    global _DEFAULT_SETTINGS
    if _DEFAULT_SETTINGS is not None and not force:
        return _DEFAULT_SETTINGS
    if openai_configured():
        _DEFAULT_SETTINGS = configured_openai_settings()
        return _DEFAULT_SETTINGS
    _DEFAULT_SETTINGS = detect_local_openai_settings() or OpenAISettings()
    return _DEFAULT_SETTINGS


def openai_defaults() -> OpenAISettings:
    return configure_openai_defaults()
