from __future__ import annotations

import unittest

from leave_calendar.login_launcher import (
    destination_login_sequence,
    parse_login_sequence,
)


class LoginLauncherTests(unittest.TestCase):
    def test_monitoring_destination_keys(self) -> None:
        steps = parse_login_sequence(destination_login_sequence("monitoring", 1500))
        self.assertEqual(
            [(step.action, step.value) for step in steps[-6:]],
            [
                ("wait", 1500),
                ("key", "alt"),
                ("key", "a"),
                ("key", "h"),
                ("key", "l"),
                ("key", "enter"),
            ],
        )

    def test_credits_destination_has_second_l(self) -> None:
        steps = parse_login_sequence(destination_login_sequence("credits", 700))
        keys = [step.value for step in steps if step.action == "key"]
        self.assertEqual(keys[-6:], ["alt", "a", "h", "l", "l", "enter"])

    def test_default_sequence(self) -> None:
        steps = parse_login_sequence(
            "{USERNAME} | TAB | {PASSWORD} | ENTER"
        )
        self.assertEqual(
            [(step.action, step.value) for step in steps],
            [
                ("username", ""),
                ("key", "tab"),
                ("password", ""),
                ("key", "enter"),
            ],
        )

    def test_sequence_accepts_lines_and_wait(self) -> None:
        steps = parse_login_sequence(
            "USERNAME\nTAB\nWAIT 700\nPASSWORD\nENTER"
        )
        self.assertEqual(steps[2].action, "wait")
        self.assertEqual(steps[2].value, 700)

    def test_sequence_requires_credentials(self) -> None:
        with self.assertRaisesRegex(ValueError, "USERNAME"):
            parse_login_sequence("TAB | PASSWORD | ENTER")
        with self.assertRaisesRegex(ValueError, "PASSWORD"):
            parse_login_sequence("USERNAME | TAB | ENTER")

    def test_unknown_command_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            parse_login_sequence("USERNAME | CLICK | PASSWORD")


if __name__ == "__main__":
    unittest.main()
