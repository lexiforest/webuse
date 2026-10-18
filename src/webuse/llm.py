from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
import os

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
_RUN_SETTINGS: ContextVar[OpenAISettings | None] = ContextVar(
    "webuse_llm_settings", default=None
)


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


def _model_ids(payload: Any) -> list[str]:
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(data, list):
        return []
    return list(
        dict.fromkeys(
            item["id"]
            for item in data
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
        )
    )


async def acompletion_content(
    *,
    settings: OpenAISettings,
    client: Any = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **payload: Any,
) -> str:
    """Await an injected model client or use curl_cffi for the default transport."""
    if client is not None:
        response = await client.chat.completions.create(**payload)
        return response.choices[0].message.content or ""
    api_key = api_key or settings.api_key
    base_url = base_url or settings.base_url or "https://api.openai.com/v1"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with requests.AsyncSession() as session:
        response = await session.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            allow_redirects=False,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"].get("content") or ""


def openai_model_ids(
    base_url: str, api_key: str = "", *, timeout: float = 2
) -> list[str]:
    """List models without making an inference request."""
    response = requests.get(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        timeout=timeout,
        allow_redirects=False,
    )
    response.raise_for_status()
    return _model_ids(response.json())


def _local_openai_settings(*, timeout: float):
    for provider, base_url, api_key in _LOCAL_OPENAI_ENDPOINTS:
        host = os.environ.get("WEBUSE_LOCAL_MODEL_HOST", "127.0.0.1")
        base_url = base_url.replace("127.0.0.1", host)
        try:
            response = requests.get(
                f"{base_url}/models", timeout=timeout, allow_redirects=False
            )
        except Exception:
            continue
        if getattr(response, "status_code", 0) >= 400:
            continue
        try:
            models = _model_ids(response.json())
        except Exception:
            models = []
        for model in models:
            yield OpenAISettings(
                model=model, api_key=api_key, base_url=base_url, provider=provider
            )


def discover_local_openai_settings(*, timeout: float = 0.2) -> list[OpenAISettings]:
    """Discover models in LM Studio, then Ollama, for local model selectors."""
    return list(_local_openai_settings(timeout=timeout))


def detect_local_openai_settings(*, timeout: float = 0.2) -> OpenAISettings | None:
    return next(_local_openai_settings(timeout=timeout), None)


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
    return _RUN_SETTINGS.get() or configure_openai_defaults()


@contextmanager
def use_openai_settings(config: dict[str, Any] | None):
    """Apply project settings to this execution without changing other executions."""
    if not config:
        yield
        return
    settings = openai_settings_from_config(config)
    token = _RUN_SETTINGS.set(settings)
    try:
        yield
    finally:
        _RUN_SETTINGS.reset(token)
