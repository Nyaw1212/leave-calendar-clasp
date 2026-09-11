from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LOGIN_SEQUENCE = "{USERNAME} | TAB | {PASSWORD} | ENTER"
LEAVE_MONITORING_KEYS = ("ALT", "A", "H", "L", "ENTER")
LEAVE_CREDITS_KEYS = ("ALT", "A", "H", "L", "L", "ENTER")
SUPPORTED_KEYS = {
    "TAB": "tab",
    "ENTER": "enter",
    "ESC": "esc",
    "SPACE": "space",
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
    "ALT": "alt",
    "A": "a",
    "H": "h",
    "L": "l",
}


@dataclass(frozen=True, slots=True)
class LoginStep:
    action: str
    value: str | int = ""


def parse_login_sequence(value: str) -> tuple[LoginStep, ...]:
    """Parse a deliberately small login macro language.

    Commands are separated by pipes or new lines. Supported commands are the
    USERNAME/PASSWORD placeholders, common navigation keys, and WAIT <ms>.
    """
    text = str(value or "").replace("\r", "\n").replace("\n", "|")
    commands = [part.strip() for part in text.split("|") if part.strip()]
    if not commands:
        raise ValueError("Enter a login sequence.")

    steps: list[LoginStep] = []
    for command in commands:
        upper = command.upper()
        if upper in {"{USERNAME}", "USERNAME"}:
            steps.append(LoginStep("username"))
        elif upper in {"{PASSWORD}", "PASSWORD"}:
            steps.append(LoginStep("password"))
        elif upper in SUPPORTED_KEYS:
            steps.append(LoginStep("key", SUPPORTED_KEYS[upper]))
        elif upper.startswith("WAIT "):
            try:
                milliseconds = int(upper[5:].strip())
            except ValueError as error:
                raise ValueError(f"Invalid delay command: {command}") from error
            if not 0 <= milliseconds <= 30_000:
                raise ValueError("WAIT must be between 0 and 30000 milliseconds.")
            steps.append(LoginStep("wait", milliseconds))
        else:
            raise ValueError(f"Unsupported login command: {command}")

    if not any(step.action == "username" for step in steps):
        raise ValueError("The sequence must include {USERNAME}.")
    if not any(step.action == "password" for step in steps):
        raise ValueError("The sequence must include {PASSWORD}.")
    return tuple(steps)


def validate_executable(value: str) -> Path:
    path = Path(str(value or "").strip().strip('"')).expanduser()
    if not path.is_file():
        raise ValueError("Select a valid application .exe file.")
    if path.suffix.casefold() != ".exe":
        raise ValueError("The selected login application must be an .exe file.")
    return path


def destination_login_sequence(
    destination: str,
    navigation_delay_ms: int,
) -> str:
    destination_key = str(destination or "").strip().casefold()
    if destination_key == "monitoring":
        keys = LEAVE_MONITORING_KEYS
    elif destination_key == "credits":
        keys = LEAVE_CREDITS_KEYS
    else:
        raise ValueError(f"Unknown login destination: {destination}")
    delay = max(0, min(30_000, int(navigation_delay_ms)))
    commands = [DEFAULT_LOGIN_SEQUENCE, f"WAIT {delay}", *keys]
    return " | ".join(commands)


def launch_and_login(
    exe_path: str,
    username: str,
    password: str,
    startup_delay_ms: int,
    sequence: str,
) -> None:
    path = validate_executable(exe_path)
    if not username:
        raise ValueError("Enter the login username.")
    if not password:
        raise ValueError("Enter the login password.")
    steps = parse_login_sequence(sequence)

    subprocess.Popen([str(path)], cwd=str(path.parent))
    time.sleep(max(0, min(30_000, int(startup_delay_ms))) / 1000)

    import keyboard

    for step in steps:
        if step.action == "username":
            keyboard.write(username, delay=0.02)
        elif step.action == "password":
            keyboard.write(password, delay=0.02)
        elif step.action == "key":
            keyboard.send(str(step.value))
        elif step.action == "wait":
            time.sleep(int(step.value) / 1000)
        time.sleep(0.08)
