import json
import re
from pathlib import Path
from typing import Any

from ..models import SmartSelectorRecord


class SmartSelectorStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or "selectors.json")
        self._records: dict[str, SmartSelectorRecord] | None = None

    def _load(self) -> dict[str, SmartSelectorRecord]:
        if self._records is not None:
            return self._records
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = {
                key: _record_from_payload(key, value) for key, value in payload.items()
            }
        else:
            self._records = {}
        return self._records

    def get(self, key: str) -> SmartSelectorRecord | None:
        return self._load().get(key)

    def save(self, record: SmartSelectorRecord) -> None:
        records = self._load()
        records[record.key] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {key: value.model_dump(mode="json") for key, value in records.items()},
                indent=2,
            ),
            encoding="utf-8",
        )


def _record_from_payload(key: str, payload: dict[str, Any]) -> SmartSelectorRecord:
    valid_fields = set(SmartSelectorRecord.model_fields)
    values = {name: value for name, value in payload.items() if name in valid_fields}
    values.setdefault("key", key)
    values.setdefault("prompt", "")
    return SmartSelectorRecord(**values)


def prompt_key(prompt: str, key: str | None = None) -> str:
    if key:
        return key
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
    return slug or "selector"
