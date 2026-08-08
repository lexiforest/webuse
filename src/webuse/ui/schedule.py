import time
from datetime import datetime, timezone

from croniter import croniter


def now_ms() -> int:
    return int(time.time() * 1000)


def valid_cron(expression: str) -> bool:
    value = expression.strip()
    return not value or croniter.is_valid(value, strict=True)


def next_run_at_ms(expression: str | None, base_ms: int | None = None) -> int | None:
    value = (expression or "").strip()
    if not value:
        return None
    base = datetime.fromtimestamp(
        (base_ms if base_ms is not None else now_ms()) / 1000, timezone.utc
    )
    next_run = croniter(value, base).get_next(datetime)
    return int(next_run.timestamp() * 1000)
