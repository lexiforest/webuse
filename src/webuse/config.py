import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .exceptions import ConfigError


LOCAL_CONFIG_NAME = ".webuserc.yaml"
USER_CONFIG_PATH = Path("~/.config/webuse/config.yaml")
DEFAULT_SETTINGS = {
    "runtime": {
        "databasePath": "./webuse.sqlite",
        "workDirectory": "/tmp/webuse",
        "concurrency": "1",
    },
    "llm": {
        "apiKey": "",
        "baseUrl": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
    },
    "smart": {
        "selectorStore": "selectors.json",
    },
}
EMPTY_SETTINGS = {
    "runtime": {
        "databasePath": "",
        "workDirectory": "",
        "concurrency": "",
    },
    "llm": {
        "apiKey": "",
        "baseUrl": "",
        "model": "",
    },
    "smart": {
        "selectorStore": "",
    },
}


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
        if (
            isinstance(value, Mapping)
            and isinstance(merged.get(key), Mapping)
        ):
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
    runtime = {
        key: value
        for key, value in {
            "database_path": _env_first("WEBUSE_DB_PATH"),
            "work_directory": _env_first("WEBUSE_WORK_DIR"),
            "concurrency": _env_first("WEBUSE_CONCURRENCY", "WEBUSE_WORKER_CONCURRENCY"),
        }.items()
        if value is not None
    }
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
    if runtime:
        config["runtime"] = runtime
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


def _string_value(value: Any, fallback: str) -> str:
    return fallback if value is None else str(value)


def webuse_settings_from_config(
    config: dict[str, Any] | None = None,
    *,
    defaults: dict[str, dict[str, str]] = DEFAULT_SETTINGS,
) -> dict[str, Any]:
    config = config if config is not None else load_webuse_config()
    runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    smart = config.get("smart") if isinstance(config.get("smart"), dict) else {}
    return {
        "runtime": {
            "databasePath": _string_value(
                runtime.get("database_path"), defaults["runtime"]["databasePath"]
            ),
            "workDirectory": _string_value(
                runtime.get("work_directory"), defaults["runtime"]["workDirectory"]
            ),
            "concurrency": _string_value(
                runtime.get("concurrency"), defaults["runtime"]["concurrency"]
            ),
        },
        "llm": {
            "apiKey": _string_value(llm.get("api_key"), defaults["llm"]["apiKey"]),
            "baseUrl": _string_value(llm.get("base_url"), defaults["llm"]["baseUrl"]),
            "model": _string_value(llm.get("model"), defaults["llm"]["model"]),
        },
        "smart": {
            "selectorStore": _string_value(
                smart.get("selector_store"), defaults["smart"]["selectorStore"]
            ),
        },
    }


def webuse_local_settings() -> dict[str, Any]:
    return webuse_settings_from_config(_read_yaml(local_config_path()), defaults=EMPTY_SETTINGS)


def save_local_webuse_settings(settings: dict[str, Any]) -> dict[str, Any]:
    import yaml

    runtime = settings.get("runtime") if isinstance(settings.get("runtime"), dict) else {}
    llm = settings.get("llm") if isinstance(settings.get("llm"), dict) else {}
    smart = settings.get("smart") if isinstance(settings.get("smart"), dict) else {}
    config = _drop_empty(
        {
            "runtime": {
                "database_path": runtime.get("databasePath"),
                "work_directory": runtime.get("workDirectory"),
                "concurrency": runtime.get("concurrency"),
            },
            "llm": {
                "api_key": llm.get("apiKey"),
                "base_url": llm.get("baseUrl"),
                "model": llm.get("model"),
            },
            "smart": {
                "selector_store": smart.get("selectorStore"),
            },
        }
    )
    path = local_config_path()
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return {
        "settings": webuse_local_settings(),
        "effectiveSettings": webuse_settings_from_config(),
        "paths": {"local": str(local_config_path()), "user": str(user_config_path())},
    }


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, item in value.items()
            if (cleaned := _drop_empty(item)) not in ("", None, {})
        }
    return value


__all__ = [
    "LOCAL_CONFIG_NAME",
    "USER_CONFIG_PATH",
    "env_config",
    "load_webuse_config",
    "local_config_path",
    "save_local_webuse_settings",
    "user_config_path",
    "webuse_local_settings",
    "webuse_settings_from_config",
]
