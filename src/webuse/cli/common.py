import argparse
import json
from pathlib import Path
from typing import Any

from ..exceptions import ConfigError
from ..models import RequestOptions


_REQUEST_OPTION_NAMES = {
    name for name in RequestOptions.model_fields if name != "extra_kwargs"
}


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    if config_path.suffix == ".toml":
        import tomllib

        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    if config_path.suffix in {".yaml", ".yml"}:
        import yaml

        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raise ConfigError(f"Unsupported config format: {config_path.suffix}")


def _pair(value: str, label: str) -> tuple[str, str]:
    if "=" not in value:
        raise SystemExit(f"{label} argument must be KEY=VALUE: {value!r}")
    key, item = value.split("=", 1)
    key = key.strip()
    if not key:
        raise SystemExit(f"{label} argument has an empty key: {value!r}")
    return key, item


def _pairs(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        key, item = _pair(value, "KEY=VALUE")
        result[key] = item
    return result


def json_arg(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label} must be valid JSON: {exc.msg}") from exc


def _auth(value: str, label: str) -> tuple[str, str]:
    if ":" not in value:
        raise SystemExit(f"{label} must be USER:PASS")
    username, password = value.split(":", 1)
    if not username:
        raise SystemExit(f"{label} has an empty username")
    return username, password


def _request_options_from_config(config: dict[str, Any]) -> dict[str, Any]:
    options = {
        key: config[key]
        for key in _REQUEST_OPTION_NAMES
        if key in config and config[key] is not None
    }
    options.update(config.get("extra_kwargs", {}) or {})
    return options


def _merge_pairs(
    config_values: Any, cli_values: list[str] | None
) -> dict[str, Any] | None:
    merged = {**(config_values or {}), **_pairs(cli_values)}
    return merged or None


def _merge_json_pairs(
    config_values: Any, cli_values: list[str] | None, label: str
) -> dict[str, Any] | None:
    merged = dict(config_values or {})
    for value in cli_values or []:
        key, item = _pair(value, label)
        merged[key] = json_arg(item, label)
    return merged or None


def cli_request_options(
    args: argparse.Namespace, config: dict[str, Any]
) -> dict[str, Any]:
    request_kwargs = RequestOptions().to_request_kwargs()
    request_kwargs.update(_request_options_from_config(config))
    updates = {
        "headers": _merge_pairs(config.get("headers"), getattr(args, "header", None)),
        "cookies": _merge_pairs(config.get("cookies"), getattr(args, "cookie", None)),
        "params": _merge_pairs(config.get("params"), getattr(args, "param", None)),
        "proxy": getattr(args, "proxy", None) or config.get("proxy"),
        "proxy_auth": (
            _auth(args.proxy_auth, "--proxy-auth")
            if getattr(args, "proxy_auth", None)
            else config.get("proxy_auth")
        ),
        "impersonate": getattr(args, "impersonate", None) or config.get("impersonate"),
        "timeout": getattr(args, "timeout", None)
        if getattr(args, "timeout", None) is not None
        else config.get("timeout"),
        "auth": _auth(args.auth, "--auth")
        if getattr(args, "auth", None)
        else config.get("auth"),
        "verify": getattr(args, "verify", None)
        if getattr(args, "verify", None) is not None
        else config.get("verify"),
        "follow_redirects": (
            getattr(args, "follow_redirects", None)
            if getattr(args, "follow_redirects", None) is not None
            else config.get("follow_redirects")
        ),
        "max_redirects": (
            getattr(args, "max_redirects", None)
            if getattr(args, "max_redirects", None) is not None
            else config.get("max_redirects")
        ),
        "ja3": getattr(args, "ja3", None) or config.get("ja3"),
        "akamai": getattr(args, "akamai", None) or config.get("akamai"),
        "extra_fp": _merge_json_pairs(
            config.get("extra_fp"), getattr(args, "extra_fp", None), "--extra-fp"
        ),
        "default_headers": (
            getattr(args, "default_headers", None)
            if getattr(args, "default_headers", None) is not None
            else config.get("default_headers")
        ),
        "http_version": getattr(args, "http_version", None)
        or config.get("http_version"),
        "interface": getattr(args, "interface", None) or config.get("interface"),
        "cert": getattr(args, "cert", None) or config.get("cert"),
        "referer": getattr(args, "referer", None) or config.get("referer"),
    }
    request_kwargs.update(
        {key: value for key, value in updates.items() if value is not None}
    )
    request_kwargs.pop("method", None)
    return {key: value for key, value in request_kwargs.items() if value is not None}


def print_jsonl(items: list[Any]) -> None:
    for item in items:
        if hasattr(item, "model_dump"):
            item = item.model_dump(mode="json")
        print(json.dumps(item, ensure_ascii=True, default=str))


def add_request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--header", action="append")
    parser.add_argument("--cookie", action="append")
    parser.add_argument("--param", action="append")
    parser.add_argument("--auth")
    parser.add_argument("--proxy")
    parser.add_argument("--proxy-auth")
    parser.add_argument("--impersonate")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--verify", dest="verify", action="store_true", default=None)
    parser.add_argument("--no-verify", dest="verify", action="store_false")
    parser.add_argument(
        "--follow-redirects", dest="follow_redirects", action="store_true", default=None
    )
    parser.add_argument(
        "--no-follow-redirects", dest="follow_redirects", action="store_false"
    )
    parser.add_argument("--max-redirects", type=int)
    parser.add_argument("--ja3")
    parser.add_argument("--akamai")
    parser.add_argument("--extra-fp", action="append")
    parser.add_argument(
        "--default-headers", dest="default_headers", action="store_true", default=None
    )
    parser.add_argument(
        "--no-default-headers", dest="default_headers", action="store_false"
    )
    parser.add_argument("--http-version")
    parser.add_argument("--interface")
    parser.add_argument("--cert")
    parser.add_argument("--referer")
