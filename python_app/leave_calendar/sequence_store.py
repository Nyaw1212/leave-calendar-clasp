from __future__ import annotations

import json
from pathlib import Path

from .settings import app_data_dir


class SequenceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "magclip_sequences.json"
        self.default_path = self.path.with_name("magclip_sequence_default.json")
        self.transition_path = self.path.with_name("magclip_stage_transitions.json")
        self.stage_delay_path = self.path.with_name("magclip_stage_delays.json")

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

    def load_default(self) -> str:
        if not self.default_path.exists():
            return ""
        try:
            raw = json.loads(self.default_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(raw, dict):
            return ""
        return " ".join(str(raw.get("default_sequence", "")).split())

    def save_default(self, name: str) -> None:
        clean_name = " ".join(str(name).split())
        self.default_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_path.write_text(
            json.dumps({"default_sequence": clean_name}, indent=2),
            encoding="utf-8",
        )

    def load_stage_delays(self) -> dict[str, int]:
        if not self.stage_delay_path.exists():
            return {}
        try:
            raw = json.loads(self.stage_delay_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            " ".join(str(stage).split()).casefold(): int(delay)
            for stage, delay in raw.items()
            if isinstance(delay, int) and 25 <= delay <= 2000
        }

    def save_stage_delay(self, stage: str, delay_ms: int) -> int:
        clean_stage = " ".join(str(stage).split()).casefold()
        clean_delay = int(delay_ms)
        if not clean_stage:
            raise ValueError("Choose a guided-flow stage.")
        if not 25 <= clean_delay <= 2000:
            raise ValueError("Stage delay must be from 25 through 2000 ms.")
        delays = self.load_stage_delays()
        delays[clean_stage] = clean_delay
        self.stage_delay_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.stage_delay_path.with_suffix(self.stage_delay_path.suffix + ".tmp")
        temporary.write_text(json.dumps(delays, indent=2), encoding="utf-8")
        temporary.replace(self.stage_delay_path)
        return clean_delay

    def load_stage_transitions(self) -> dict[str, tuple[str, ...]]:
        """Load the six-slot keyboard macros used between guided-flow stages."""
        if not self.transition_path.exists():
            return {}
        try:
            raw = json.loads(self.transition_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        transitions: dict[str, tuple[str, ...]] = {}
        for stage, actions in raw.items():
            clean_stage = " ".join(str(stage).split()).casefold()
            if (
                clean_stage
                and isinstance(actions, list)
                and len(actions) <= 6
                and all(isinstance(action, str) and action.strip() for action in actions)
            ):
                transitions[clean_stage] = tuple(
                    action.strip().upper() for action in actions
                )
        return transitions

    def save_stage_transition(
        self,
        stage: str,
        actions: list[str] | tuple[str, ...],
    ) -> tuple[str, ...]:
        clean_stage = " ".join(str(stage).split()).casefold()
        clean_actions = [
            str(action).strip().upper()
            for action in actions
            if str(action).strip() and str(action).strip().upper() != "NONE"
        ]
        if not clean_stage:
            raise ValueError("Choose a guided-flow transition.")
        if len(clean_actions) > 6:
            raise ValueError("A stage transition can contain up to 6 actions.")
        transitions = self.load_stage_transitions()
        transitions[clean_stage] = tuple(clean_actions)
        self.transition_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.transition_path.with_suffix(self.transition_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {name: list(commands) for name, commands in transitions.items()},
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.transition_path)
        return transitions[clean_stage]

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
