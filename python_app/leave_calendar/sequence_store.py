from __future__ import annotations

import json
from pathlib import Path

from .settings import app_data_dir


class SequenceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "magclip_sequences.json"

    def load(self) -> dict[str, tuple[str, ...]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}

        sequences: dict[str, tuple[str, ...]] = {}
        for name, actions in raw.items():
            clean_name = " ".join(str(name).split())
            if (
                not clean_name
                or not isinstance(actions, list)
                or not actions
                or len(actions) > 40
                or not all(isinstance(action, str) and action.strip() for action in actions)
            ):
                continue
            sequences[clean_name] = tuple(action.strip().upper() for action in actions)
        return sequences

    def save(self, name: str, actions: list[str] | tuple[str, ...]) -> str:
        clean_name = " ".join(str(name).split())
        clean_actions = [str(action).strip().upper() for action in actions if str(action).strip()]
        if not clean_name:
            raise ValueError("Enter a sequence name.")
        if not clean_actions:
            raise ValueError("Add at least one sequence action before saving.")
        if len(clean_actions) > 40:
            raise ValueError("A saved sequence can contain up to 40 actions.")

        sequences = self.load()
        sequences[clean_name] = tuple(clean_actions)
        self._write(sequences)
        return clean_name

    def delete(self, name: str) -> bool:
        sequences = self.load()
        if name not in sequences:
            return False
        del sequences[name]
        self._write(sequences)
        return True

    def _write(self, sequences: dict[str, tuple[str, ...]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {name: list(actions) for name, actions in sequences.items()},
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)
