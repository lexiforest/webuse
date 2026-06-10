import os
import sys
from typing import Any

from loguru import logger


DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}"


def configure_logger(
    level: str | None = None,
    *,
    sink: Any = None,
    colorize: bool | None = None,
) -> None:
    """Configure the process-wide webuse logger.

    CLI entrypoints call this at startup; library users can call it when they
    want webuse logs to use a different sink, level, or format.
    """
    logger.remove()
    logger.add(
        sys.stderr if sink is None else sink,
        level=level or os.environ.get("WEBUSE_LOG_LEVEL", DEFAULT_LOG_LEVEL),
        format=DEFAULT_LOG_FORMAT,
        colorize=colorize,
    )


__all__ = ["DEFAULT_LOG_FORMAT", "DEFAULT_LOG_LEVEL", "configure_logger", "logger"]
