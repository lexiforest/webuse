import argparse
import asyncio
import importlib

from ..llm import configure_openai_defaults
from ..log import configure_logger


_COMMAND_MODULES = [
    "webuse.cli.create",
    "webuse.cli.gen",
    "webuse.cli.fetch",
    "webuse.cli.crawl",
    "webuse.cli.websocket",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="webuse")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module_name in _COMMAND_MODULES:
        importlib.import_module(module_name).register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logger()
    configure_openai_defaults()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "use_async", False):
        return asyncio.run(args.async_func(args))
    return args.func(args)
