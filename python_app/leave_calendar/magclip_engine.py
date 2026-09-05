from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from .credits import month_name
from .models import CreditEntry, LeaveRecord


MAGCLIP_FIELDS = ("NAME", "TYPE", "START", "END", "VL", "SL", "LWOP", "STATUS")
CREDIT_FIELDS = ("MONTH", "YEAR", "VL EARNED", "SL EARNED")
DEFAULT_SEQUENCE = (
    "ENTER",
    "PASTE",
    "ENTER",
    "TAB",
    "PASTE",
    "TAB",
    "PASTE",
    "TAB",
    "PASTE",
    "TAB",
    "TAB",
    "PASTE",
    "TAB",
    "PASTE",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TYPE",
    "TAB",
)
POCES_APPOVE_SEQUENCE = (
    "ENTER 700MS",
    "PASTE 700MS",
    "ENTER 700MS",
    "TAB",
    "PASTE",
    "TAB",
    "PASTE",
    "TAB",
    "PASTE",
    "TAB",
    "TYPE P",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
    "ARROW DOWN",
    "ARROW DOWN",
    "TYPE A",
    "TAB",
    "PASTE",
    "TAB",
    "PASTE",
    "TAB",
    "TAB",
    "TAB",
    "TAB",
)
CREDIT_SEQUENCE = (
    "ENTER",
    "TAB",
    "TYPE",
    "TAB",
    "PASTE",
    "TAB",
    "PASTE",
    "TAB",
    "PASTE",
    "TAB",
    "ENTER",
)
SEQUENCE_PRESETS = {
    "LEAVE ENTRY": DEFAULT_SEQUENCE,
    "POCES APPOVE": POCES_APPOVE_SEQUENCE,
    "CREDITS": CREDIT_SEQUENCE,
}


def leave_record_rounds(record: LeaveRecord) -> list[str]:
    return [
        record.name,
        record.leave_type,
        record.start.strftime("%m/%d/%Y"),
        record.end.strftime("%m/%d/%Y"),
        f"{record.vl:.3f}",
        f"{record.sl:.3f}",
        f"{record.lwop:.3f}",
        record.status or "A",
    ]


def credit_entry_rounds(entry: CreditEntry) -> list[str]:
    return [
        month_name(entry.month).title(),
        str(entry.year),
        f"{entry.vl_earned:.3f}",
        f"{entry.sl_earned:.3f}",
    ]


@dataclass(slots=True)
class Round:
    value: str


@dataclass(slots=True)
class Clip:
    rounds: list[Round] = field(default_factory=list)


class Magazine:
    def __init__(self) -> None:
        self.clips: list[Clip] = []
        self.clip_index = 0
        self.round_index = 0
        self.last_fired_clip_index: int | None = None
        self.last_round_position: tuple[int, int] | None = None
        self.fields: tuple[str, ...] = MAGCLIP_FIELDS

    def load(
        self,
        rows: list[list[str]],
        fields: tuple[str, ...] = MAGCLIP_FIELDS,
    ) -> None:
        self.clips = [
            Clip([Round(str(value)) for value in row])
            for row in rows
            if any(str(value) != "" for value in row)
        ]
        self.clip_index = 0
        self.round_index = 0
        self.last_fired_clip_index = None
        self.last_round_position = None
        self.fields = fields

    def select_clip(self, index: int) -> bool:
        if index < 0 or index >= len(self.clips):
            return False
        self.clip_index = index
        self.round_index = 0
        self.last_round_position = None
        return True

    def current_clip(self) -> Clip | None:
        if self.clip_index >= len(self.clips):
            return None
        return self.clips[self.clip_index]

    def current_round(self) -> Round | None:
        clip = self.current_clip()
        if clip is None or self.round_index >= len(clip.rounds):
            return None
        return clip.rounds[self.round_index]

    def current_field(self) -> str | None:
        if self.current_round() is None or self.round_index >= len(self.fields):
            return None
        return self.fields[self.round_index]

    def next_round_details(self) -> tuple[str, str] | None:
        clip = self.current_clip()
        if clip is None:
            return None
        next_round = self.round_index + 1
        if next_round < len(clip.rounds):
            field_name = (
                self.fields[next_round]
                if next_round < len(self.fields)
                else f"ROUND {next_round + 1}"
            )
            return field_name, clip.rounds[next_round].value
        next_clip = self.clip_index + 1
        if next_clip < len(self.clips) and self.clips[next_clip].rounds:
            return self.fields[0], self.clips[next_clip].rounds[0].value
        return None

    def advance_round(self) -> None:
        clip = self.current_clip()
        if clip is None:
            return
        self.last_round_position = (self.clip_index, self.round_index)
        self.round_index += 1
        if self.round_index >= len(clip.rounds):
            self.last_fired_clip_index = self.clip_index
            self.clip_index += 1
            self.round_index = 0

    def reload_last_round(self) -> bool:
        if self.last_round_position is None:
            return False
        clip_index, round_index = self.last_round_position
        if clip_index >= len(self.clips):
            return False
        if round_index >= len(self.clips[clip_index].rounds):
            return False
        self.clip_index = clip_index
        self.round_index = round_index
        return True

    def reload_last_clip(self) -> bool:
        if self.last_fired_clip_index is None:
            return False
        self.clip_index = self.last_fired_clip_index
        self.round_index = 0
        return True

    def progress(self) -> tuple[int, int, int, int]:
        total_clips = len(self.clips)
        clip_number = min(self.clip_index + 1, total_clips) if total_clips else 0
        clip = self.current_clip()
        total_rounds = len(clip.rounds) if clip else 0
        round_number = min(self.round_index + 1, total_rounds) if total_rounds else 0
        return clip_number, total_clips, round_number, total_rounds


class EngineContext(Protocol):
    def paste_text(self, value: str) -> None: ...
    def type_text(self, value: str) -> None: ...
    def press_tab(self) -> None: ...
    def press_enter(self) -> None: ...
    def press_space(self) -> None: ...
    def press_escape(self) -> None: ...
    def press_arrow_up(self) -> None: ...
    def press_arrow_down(self) -> None: ...
    def should_abort(self) -> bool: ...


@dataclass(slots=True)
class EngineResult:
    completed: bool
    aborted: bool = False


def action_details(action: str) -> tuple[str, int | None]:
    match = re.fullmatch(r"(.+?)\s+(\d+)MS", action.strip().upper())
    if match:
        return match.group(1), int(match.group(2))
    return action.strip().upper(), None


def action_consumes_round(action: str) -> bool:
    return action_details(action)[0] in {"PASTE", "TYPE"}


class LeaveEntryEngine:
    valid_actions = {
        "PASTE",
        "TYPE",
        "TYPE P",
        "TYPE A",
        "TAB",
        "ENTER",
        "SPACE",
        "ESC",
        "ARROW UP",
        "ARROW DOWN",
    }

    def __init__(self, delay_ms: int = 120) -> None:
        self.delay_ms = delay_ms

    @staticmethod
    def _lwop_enabled(value: str) -> bool:
        normalized = value.strip().casefold()
        return normalized not in {"", "0", "0.0", "0.00", "0.000", "false", "no", "off"}

    def _wait(self, delay_ms: int | None = None) -> None:
        time.sleep((self.delay_ms if delay_ms is None else delay_ms) / 1000)

    def run_rounds(
        self,
        context: EngineContext,
        values: list[str],
        start_round: int,
    ) -> EngineResult:
        for offset, value in enumerate(values):
            if context.should_abort():
                return EngineResult(completed=False, aborted=True)
            field_index = start_round + offset
            if field_index >= len(MAGCLIP_FIELDS):
                return EngineResult(completed=False)
            field_name = MAGCLIP_FIELDS[field_index]
            is_last_in_fire = offset == len(values) - 1
            if field_name == "LWOP":
                if self._lwop_enabled(value):
                    context.press_space()
                    self._wait()
                if not is_last_in_fire:
                    context.press_tab()
                    self._wait()
                continue
            context.paste_text(value)
            self._wait()
            if not is_last_in_fire:
                context.press_tab()
                self._wait()
        return EngineResult(completed=True)

    def run_sequence(
        self,
        context: EngineContext,
        values: list[str],
        start_round: int,
        actions: list[str],
    ) -> tuple[EngineResult, int]:
        consumed = 0
        for action in actions:
            if context.should_abort():
                return EngineResult(completed=False, aborted=True), consumed
            base_action, action_delay = action_details(action)
            if base_action not in self.valid_actions:
                return EngineResult(completed=False), consumed
            if base_action in {"TYPE P", "TYPE A"}:
                context.type_text(base_action[-1])
                self._wait(action_delay)
                continue
            if base_action in {"PASTE", "TYPE"}:
                if consumed >= len(values):
                    return EngineResult(completed=False), consumed
                field_index = start_round + consumed
                if field_index >= len(MAGCLIP_FIELDS):
                    return EngineResult(completed=False), consumed
                value = values[consumed]
                if MAGCLIP_FIELDS[field_index] == "LWOP":
                    if self._lwop_enabled(value):
                        context.press_space()
                elif base_action == "TYPE":
                    context.type_text(value)
                else:
                    context.paste_text(value)
                consumed += 1
                self._wait(action_delay)
                continue
            if base_action == "TAB":
                context.press_tab()
            elif base_action == "ENTER":
                context.press_enter()
            elif base_action == "SPACE":
                context.press_space()
            elif base_action == "ESC":
                context.press_escape()
            elif base_action == "ARROW UP":
                context.press_arrow_up()
            elif base_action == "ARROW DOWN":
                context.press_arrow_down()
            self._wait(action_delay)

        # This form-specific preset intentionally uses navigation and literal
        # P/A values instead of writing every remaining leave-history field.
        # Once its full sequence succeeds, advance to the next history clip.
        normalized_actions = tuple(action.strip().upper() for action in actions)
        if normalized_actions == POCES_APPOVE_SEQUENCE:
            return EngineResult(completed=True), len(values)

        # POCES APPOVE enters STATUS as a literal A before pasting VL and SL.
        # Its final TAB lands on LWOP, so finish that checkbox round here and
        # mark the already-entered STATUS round complete.
        field_index = start_round + consumed
        if (
            consumed + 2 == len(values)
            and field_index == MAGCLIP_FIELDS.index("LWOP")
            and any(action_details(action)[0] == "TYPE A" for action in actions)
        ):
            if self._lwop_enabled(values[consumed]):
                context.press_space()
                self._wait()
            consumed += 2

        # The requested sequence has seven value actions for an eight-round
        # clip. After its final TAB reaches STATUS, type that trailing value and
        # TAB once more so the destination form is ready for the next record.
        field_index = start_round + consumed
        if (
            consumed < len(values)
            and consumed + 1 == len(values)
            and field_index == len(MAGCLIP_FIELDS) - 1
            and MAGCLIP_FIELDS[field_index] == "STATUS"
        ):
            context.type_text(values[consumed])
            self._wait()
            context.press_tab()
            self._wait()
            consumed += 1

        return EngineResult(completed=True), consumed


class CreditEntryEngine(LeaveEntryEngine):
    """MONTH TYPER engine: TYPE sends a three-letter uppercase month code."""

    @staticmethod
    def _month_code(value: str) -> str:
        return "".join(character for character in value if character.isalpha())[:3].upper()

    def run_sequence(
        self,
        context: EngineContext,
        values: list[str],
        start_round: int,
        actions: list[str],
    ) -> tuple[EngineResult, int]:
        consumed = 0
        for action in actions:
            if context.should_abort():
                return EngineResult(completed=False, aborted=True), consumed
            base_action, action_delay = action_details(action)
            if base_action not in self.valid_actions:
                return EngineResult(completed=False), consumed
            if base_action in {"TYPE P", "TYPE A"}:
                context.type_text(base_action[-1])
                self._wait(action_delay)
                continue
            if base_action in {"PASTE", "TYPE"}:
                if consumed >= len(values):
                    return EngineResult(completed=False), consumed
                value = values[consumed]
                if base_action == "TYPE":
                    value = self._month_code(value)
                    if not value:
                        return EngineResult(completed=False), consumed
                    context.type_text(value)
                else:
                    context.paste_text(value)
                consumed += 1
                self._wait(action_delay)
                continue
            if base_action == "TAB":
                context.press_tab()
            elif base_action == "ENTER":
                context.press_enter()
            elif base_action == "SPACE":
                context.press_space()
            elif base_action == "ESC":
                context.press_escape()
            elif base_action == "ARROW UP":
                context.press_arrow_up()
            elif base_action == "ARROW DOWN":
                context.press_arrow_down()
            self._wait(action_delay)
        return EngineResult(completed=True), consumed

    def run_rounds(
        self,
        context: EngineContext,
        values: list[str],
        start_round: int,
    ) -> EngineResult:
        del start_round
        result, consumed = self.run_sequence(
            context,
            values,
            0,
            list(CREDIT_SEQUENCE),
        )
        if result.completed and consumed != len(values):
            return EngineResult(completed=False)
        return result
