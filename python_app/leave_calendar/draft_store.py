from __future__ import annotations

import json
from pathlib import Path

from .models import DraftEntry
from .settings import app_data_dir


class DraftStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "draft.json"

    def save(self, employee_id: str, entries: list[DraftEntry]) -> None:
        payload = {
            "employee_id": employee_id,
            "entries": [entry.to_dict() for entry in entries],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self) -> tuple[str, list[DraftEntry]]:
        if not self.path.exists():
            return "", []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            entries = [DraftEntry.from_dict(item) for item in payload.get("entries", [])]
            entries = [entry for entry in entries if entry.days]
            return str(payload.get("employee_id", "")), entries
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return "", []

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
