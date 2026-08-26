from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from .rules import LEAVE_TYPES, normalize_leave_type


_DEFAULT_CODES = {
    "Vacation Leave": "VL",
    "Sick Leave": "SL",
    "Forced Leave": "FL",
    "Special Privilege Leave": "SPL",
    "Compensatory Time Off": "CTO",
    "Maternity Leave": "ML",
    "Paternity Leave": "PL",
    "Other": "Other",
}

_NAME_HEADERS = {
    "label",
    "leave_type",
    "leave_type_name",
    "leave_types",
    "leave_name",
    "name",
    "text",
    "type",
    "type_of_leave",
    "description",
}
_CODE_HEADERS = {
    "abbreviation",
    "abbr",
    "code",
    "leave_code",
    "leave_type_code",
    "short_name",
}
_SHORTCUT_HEADERS = {
    "hotkey",
    "key",
    "keyboard_shortcut",
    "keyboard_shortcut_key",
    "short_cut",
    "short_cut_key",
    "short_cut_keys",
    "shortcut",
    "shortcut_key",
    "shortcut_keys",
}


@dataclass(frozen=True, slots=True)
class LeaveTypeOption:
    name: str
    code: str = ""
    shortcut: str = ""

    @property
    def display_name(self) -> str:
        if self.code and self.code.casefold() != self.name.casefold():
            return f"{self.code} — {self.name}"
        return self.name

    @property
    def legend_name(self) -> str:
        return self.code or self.name


def default_leave_type_options() -> list[LeaveTypeOption]:
    return [
        LeaveTypeOption(name=name, code=_DEFAULT_CODES.get(name, ""))
        for name in LEAVE_TYPES
    ]


def parse_leave_type_rows(rows: Sequence[Sequence[str]]) -> list[LeaveTypeOption]:
    """Parse the existing LEAVE_TYPE tab without requiring one rigid layout."""
    meaningful = [list(row) for row in rows if any(str(cell).strip() for cell in row)]
    if not meaningful:
        return default_leave_type_options()

    headers = [_header_key(cell) for cell in meaningful[0]]
    name_index = _first_index(headers, _NAME_HEADERS)
    code_index = _first_index(headers, _CODE_HEADERS)
    shortcut_index = _first_index(headers, _SHORTCUT_HEADERS)
    has_header = any(index is not None for index in (name_index, code_index, shortcut_index))

    if name_index is None:
        name_index = 0
    if not has_header:
        code_index = 1 if _max_width(meaningful) > 1 else None
        shortcut_index = 2 if _max_width(meaningful) > 2 else None

    options: list[LeaveTypeOption] = []
    seen: set[str] = set()
    data_rows = meaningful[1:] if has_header else meaningful
    for row in data_rows:
        name = _cell(row, name_index)
        code = _cell(row, code_index)
        shortcut = normalize_shortcut(_cell(row, shortcut_index))

        if not name and code:
            name = normalize_leave_type(code)
        if not name:
            continue

        name = normalize_leave_type(name)
        if not code:
            code = _DEFAULT_CODES.get(name, "")
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        options.append(LeaveTypeOption(name=name, code=code, shortcut=shortcut))

    return options or default_leave_type_options()


def normalize_shortcut(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""

    parts = [part.strip() for part in re.split(r"\s*\+\s*", text) if part.strip()]
    aliases = {
        "control": "Ctrl",
        "ctrl": "Ctrl",
        "option": "Alt",
        "alt": "Alt",
        "shift": "Shift",
        "command": "Meta",
        "cmd": "Meta",
        "meta": "Meta",
        "windows": "Meta",
        "win": "Meta",
    }
    normalized = []
    for part in parts:
        fallback = part
        if len(part) == 1 or re.fullmatch(r"f\d{1,2}", part, re.IGNORECASE):
            fallback = part.upper()
        normalized.append(aliases.get(part.casefold(), fallback))
    return "+".join(normalized)


def _header_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _first_index(values: Sequence[str], candidates: set[str]) -> int | None:
    return next((index for index, value in enumerate(values) if value in candidates), None)


def _max_width(rows: Sequence[Sequence[str]]) -> int:
    return max((len(row) for row in rows), default=0)


def _cell(row: Sequence[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()
