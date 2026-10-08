import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .exceptions import ConfigError


LOCAL_CONFIG_NAME = ".webuserc.yaml"
USER_CONFIG_PATH = Path("~/.config/webuse/config.yaml")
def user_config_path() -> Path:
    return USER_CONFIG_PATH.expanduser()


def local_config_path(directory: Path | None = None) -> Path:
    return (directory or Path.cwd()) / LOCAL_CONFIG_NAME


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    import yaml

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"Config file must contain a mapping: {path}")
    return value


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def env_config() -> dict[str, Any]:
    llm = {
        key: value
        for key, value in {
            "api_key": _env_first("WEBUSE_LLM_API_KEY", "OPENAI_API_KEY"),
            "base_url": _env_first("WEBUSE_LLM_BASE_URL", "OPENAI_BASE_URL"),
            "model": _env_first("WEBUSE_LLM_MODEL", "OPENAI_MODEL"),
            "provider": _env_first("WEBUSE_LLM_PROVIDER", "OPENAI_PROVIDER"),
        }.items()
        if value is not None
    }
    smart = {
        key: value
        for key, value in {
            "selector_store": _env_first("WEBUSE_SELECTOR_STORE"),
        }.items()
        if value is not None
    }
    config: dict[str, Any] = {}
    if llm:
        config["llm"] = llm
    if smart:
        config["smart"] = smart
    return config


def load_webuse_config(
    *,
    directory: Path | None = None,
    user_path: Path | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {}
    config = _deep_merge(config, _read_yaml(user_path or user_config_path()))
    config = _deep_merge(config, _read_yaml(local_config_path(directory)))
    config = _deep_merge(config, env_config())
    return config

__all__ = [
    "LOCAL_CONFIG_NAME",
    "USER_CONFIG_PATH",
    "env_config",
    "load_webuse_config",
    "local_config_path",
    "user_config_path",
]
