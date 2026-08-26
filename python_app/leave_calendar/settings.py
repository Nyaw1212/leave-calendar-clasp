from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


APP_FOLDER_NAME = "LeaveCalendar"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    path = Path(base) / APP_FOLDER_NAME if base else Path.home() / f".{APP_FOLDER_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(slots=True)
class AppSettings:
    spreadsheet_id: str = ""
    credentials_path: str = ""

    @classmethod
    def load(cls) -> "AppSettings":
        path = app_data_dir() / "config.json"
        if not path.exists():
            return cls()
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls(
            spreadsheet_id=extract_spreadsheet_id(str(values.get("spreadsheet_id", ""))),
            credentials_path=str(values.get("credentials_path", "")),
        )

    def save(self) -> None:
        path = app_data_dir() / "config.json"
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def validate(self) -> None:
        self.spreadsheet_id = extract_spreadsheet_id(self.spreadsheet_id)
        if not self.spreadsheet_id:
            raise ValueError("Enter the Google Spreadsheet ID or full Sheet URL.")
        credentials = Path(self.credentials_path).expanduser()
        if not credentials.is_file():
            raise ValueError("Select a valid Google service-account JSON file.")


def extract_spreadsheet_id(value: str) -> str:
    text = str(value or "").strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", text)
    return match.group(1) if match else text
