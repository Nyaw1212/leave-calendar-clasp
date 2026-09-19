from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from .settings import app_data_dir


class CardAttachmentError(RuntimeError):
    """Raised when a local leave-card attachment cannot be stored."""


class CardAttachmentStore:
    """Local, read-only source copies associated with employee IDs.

    This store is deliberately separate from leave history and the SQLite
    repository. It never changes the source document or sends it anywhere.
    """

    ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_data_dir() / "leave_card_attachments"
        self.index_path = self.root / "attachments.json"
        self.files_path = self.root / "files"

    def attach(self, employee_id: str, source: str | Path) -> Path:
        clean_id = str(employee_id).strip()
        source_path = Path(source)
        if not clean_id:
            raise CardAttachmentError("Select an employee before attaching a card.")
        if source_path.suffix.lower() not in self.ALLOWED_SUFFIXES:
            raise CardAttachmentError("Choose a PDF or supported image file.")
        if not source_path.is_file():
            raise CardAttachmentError("The selected card file is no longer available.")

        try:
            self.files_path.mkdir(parents=True, exist_ok=True)
            target = self.files_path / f"{uuid4().hex}{source_path.suffix.lower()}"
            shutil.copy2(source_path, target)
            index = self._load_index()
            index[clean_id] = {
                "file": target.name,
                "source_name": source_path.name,
            }
            self._write_index(index)
            return target
        except OSError as error:
            raise CardAttachmentError(f"Could not attach the card: {error}") from error

    def path_for(self, employee_id: str) -> Path | None:
        entry = self._load_index().get(str(employee_id).strip())
        if not isinstance(entry, dict):
            return None
        filename = str(entry.get("file", "")).strip()
        if not filename or Path(filename).name != filename:
            return None
        path = self.files_path / filename
        return path if path.is_file() else None

    def _load_index(self) -> dict[str, dict[str, str]]:
        if not self.index_path.is_file():
            return {}
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(employee_id): value
            for employee_id, value in raw.items()
            if isinstance(value, dict)
        }

    def _write_index(self, index: dict[str, dict[str, str]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, indent=2), encoding="utf-8")
        temporary.replace(self.index_path)
