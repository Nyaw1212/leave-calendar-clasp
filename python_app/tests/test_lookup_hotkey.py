import unittest

from leave_calendar.lookup_hotkey import ModifierPeekState


class ModifierPeekStateTests(unittest.TestCase):
    def test_ctrl_shift_toggles_and_release_does_not_hide(self) -> None:
        state = ModifierPeekState()

        self.assertIsNone(state.update("ctrl", "down"))
        self.assertTrue(state.update("shift", "down"))
        self.assertIsNone(state.update("a", "down"))
        self.assertIsNone(state.update("ctrl", "up"))
        self.assertIsNone(state.update("shift", "up"))
        self.assertTrue(state.visible)

        self.assertIsNone(state.update("ctrl", "down"))
        self.assertFalse(state.update("shift", "down"))
        self.assertFalse(state.visible)

    def test_repeated_keydown_does_not_reopen_or_rehide(self) -> None:
        state = ModifierPeekState()

        state.update("left ctrl", "down")
        self.assertTrue(state.update("left shift", "down"))
        self.assertIsNone(state.update("left shift", "down"))
        self.assertIsNone(state.update("left shift", "up"))
        self.assertTrue(state.visible)


if __name__ == "__main__":
    unittest.main()
