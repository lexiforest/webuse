from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .client import request
from .crawl import acrawl, crawl
from .models import FollowRule
from .smart import SmartSelectorStore


def _load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(path)
    if config_path.suffix == ".toml":
        import tomllib

        return tomllib.loads(config_path.read_text(encoding="utf-8"))
    if config_path.suffix in {".yaml", ".yml"}:
        import yaml

        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raise ValueError(f"Unsupported config format: {config_path.suffix}")


def _pairs(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        key, item = value.split("=", 1)
        result[key] = item
    return result


def _extract_rules(values: list[str] | None) -> dict[str, Any]:
    rules: dict[str, Any] = {}
    for value in values or []:
        key, selector = value.split("=", 1)
        rules[key] = selector
    return rules


def _print_jsonl(items: list[Any]) -> None:
    for item in items:
        if is_dataclass(item):
            item = asdict(item)
        print(json.dumps(item, ensure_ascii=True, default=str))


def _fetch_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config).get("fetch", {})
    url = args.url or config.get("url")
    if not url:
        raise SystemExit("fetch requires a URL")
    response = request(
        args.method or config.get("method", "GET"),
        url,
        headers={**config.get("headers", {}), **_pairs(args.header)},
        params={**config.get("params", {}), **_pairs(args.param)},
        proxy=args.proxy or config.get("proxy"),
        impersonate=args.impersonate or config.get("impersonate"),
        timeout=args.timeout or config.get("timeout"),
    )
    if args.json_output or config.get("json_output"):
        payload = response.json()
        if isinstance(payload, list):
            _print_jsonl(payload)
        else:
            _print_jsonl([payload])
        return 0
    if args.css:
        matches = [element.text() for element in response.css(args.css)]
        _print_jsonl([{"url": response.url, "matches": matches}])
        return 0
    if args.xpath:
        matches = [element.text() for element in response.xpath(args.xpath)]
        _print_jsonl([{"url": response.url, "matches": matches}])
        return 0
    if args.smart:
        smart_store = args.smart_store or config.get("smart_store")
        smart_key = args.smart_key or config.get("smart_key")
        store = SmartSelectorStore(smart_store) if smart_store else None
        match = response.smart(args.smart, key=smart_key, store=store)
        _print_jsonl([{"url": response.url, "match": match.text(), "selector": args.smart}])
        return 0
    if args.meta:
        _print_jsonl(
            [
                {
                    "url": response.url,
                    "status_code": response.status_code,
                    "headers": response.headers,
                }
            ]
        )
        return 0
    sys.stdout.write(response.text)
    if not response.text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _crawl_options(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    follow_rules = []
    for selector in config.get("follow_css", []):
        follow_rules.append(FollowRule(css=selector, same_domain=config.get("same_domain", False)))
    for selector in args.follow_css or []:
        follow_rules.append(FollowRule(css=selector, same_domain=args.same_domain))
    for selector in config.get("follow_xpath", []):
        follow_rules.append(FollowRule(xpath=selector, same_domain=config.get("same_domain", False)))
    for selector in args.follow_xpath or []:
        follow_rules.append(FollowRule(xpath=selector, same_domain=args.same_domain))
    return {
        "extract": {**config.get("extract", {}), **_extract_rules(args.extract_css)},
        "follow": follow_rules,
        "max_depth": args.max_depth if args.max_depth is not None else config.get("max_depth", 0),
        "max_requests": args.max_requests if args.max_requests is not None else config.get("max_requests"),
        "concurrency": args.concurrency if args.concurrency is not None else config.get("concurrency", 10),
        "allowed_domains": set(args.allowed_domain or config.get("allowed_domains", [])) or None,
    }


def _crawl_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config).get("crawl", {})
    seeds = args.urls or config.get("seeds")
    if not seeds:
        raise SystemExit("crawl requires at least one seed URL")
    options = _crawl_options(args, config)
    result = crawl(seeds, **options)
    if result.items:
        _print_jsonl(result.items)
    else:
        _print_jsonl(
            [
                {
                    "visited": sorted(result.visited),
                    "stats": asdict(result.stats),
                }
            ]
        )
    return 0 if not result.errors else 1


async def _acrawl_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config).get("crawl", {})
    seeds = args.urls or config.get("seeds")
    if not seeds:
        raise SystemExit("crawl requires at least one seed URL")
    options = _crawl_options(args, config)
    result = await acrawl(seeds, **options)
    if result.items:
        _print_jsonl(result.items)
    else:
        _print_jsonl(
            [
                {
                    "visited": sorted(result.visited),
                    "stats": asdict(result.stats),
                }
            ]
        )
    return 0 if not result.errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webuse")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("url", nargs="?")
    fetch.add_argument("--config")
    fetch.add_argument("--method")
    fetch.add_argument("--header", action="append")
    fetch.add_argument("--param", action="append")
    fetch.add_argument("--proxy")
    fetch.add_argument("--impersonate")
    fetch.add_argument("--timeout", type=float)
    fetch.add_argument("--css")
    fetch.add_argument("--xpath")
    fetch.add_argument("--smart")
    fetch.add_argument("--smart-store")
    fetch.add_argument("--smart-key")
    fetch.add_argument("--meta", action="store_true")
    fetch.add_argument("--json-output", action="store_true")
    fetch.set_defaults(func=_fetch_command)

    crawl_parser = subparsers.add_parser("crawl")
    crawl_parser.add_argument("urls", nargs="*")
    crawl_parser.add_argument("--config")
    crawl_parser.add_argument("--follow-css", action="append")
    crawl_parser.add_argument("--follow-xpath", action="append")
    crawl_parser.add_argument("--extract-css", action="append")
    crawl_parser.add_argument("--allowed-domain", action="append")
    crawl_parser.add_argument("--same-domain", action="store_true")
    crawl_parser.add_argument("--max-depth", type=int)
    crawl_parser.add_argument("--max-requests", type=int)
    crawl_parser.add_argument("--concurrency", type=int)
    crawl_parser.add_argument("--async", dest="use_async", action="store_true")
    crawl_parser.set_defaults(func=_crawl_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "crawl" and getattr(args, "use_async", False):
        return asyncio.run(_acrawl_command(args))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
