from __future__ import annotations


class ModifierPeekState:
    """Toggle visibility once per Ctrl+Shift chord activation."""

    def __init__(self) -> None:
        self._ctrl: set[str] = set()
        self._shift: set[str] = set()
        self.visible = False
        self._chord_active = False

    def update(self, key_name: str, event_type: str) -> bool | None:
        name = str(key_name or "").strip().casefold()
        target = self._key_group(name)
        if target is None:
            return None
        pressed = event_type.casefold() == "down"
        if pressed:
            target.add(name)
        else:
            target.discard(name)
            # Some keyboard drivers report a generic release after a side-specific press.
            if name in {"ctrl", "shift"}:
                target.clear()
        chord_active = bool(self._ctrl and self._shift)
        if chord_active and not self._chord_active:
            self.visible = not self.visible
            self._chord_active = True
            return self.visible
        if not chord_active:
            self._chord_active = False
        return None

    def reset(self) -> bool | None:
        self._ctrl.clear()
        self._shift.clear()
        self._chord_active = False
        if not self.visible:
            return None
        self.visible = False
        return False

    def _key_group(self, name: str) -> set[str] | None:
        if name in {"ctrl", "left ctrl", "right ctrl"}:
            return self._ctrl
        if name in {"shift", "left shift", "right shift"}:
            return self._shift
        return None
