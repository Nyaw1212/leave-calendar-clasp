from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .settings import app_data_dir


class CardAttachmentError(RuntimeError):
    """Raised when a local leave-card attachment cannot be stored."""


class CardAttachmentStore:
    """Employee-ID-linked local filing for leave cards and exported history."""

    ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}

    def __init__(self, root: Path | None = None) -> None:
        using_default_root = root is None
        self.root = root or app_data_dir() / "NBP Leave Records"
        self.index_path = self.root / "attachments.json"
        self.legacy_root = (
            app_data_dir() / "leave_card_attachments"
            if using_default_root
            else self.root.parent / "leave_card_attachments"
        )

    @staticmethod
    def _safe_folder_part(value: str) -> str:
        clean = re.sub(r'[<>:"/\\|?*]+', " ", str(value or ""))
        return " ".join(clean.split()).strip(". ") or "Employee"

    def folder_for(
        self, employee_id: str, employee_name: str = "", *, create: bool = True
    ) -> Path:
        folder = self.root / (
            f"{self._safe_folder_part(employee_id)} - "
            f"{self._safe_folder_part(employee_name)}"
        )
        if create:
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise CardAttachmentError(
                    f"Could not create the employee folder: {error}"
                ) from error
        return folder

    def attach(self, employee_id: str, employee_name: str, source: str | Path) -> Path:
        clean_id = str(employee_id).strip()
        source_path = Path(source)
        if not clean_id:
            raise CardAttachmentError("Select an employee before attaching a card.")
        if source_path.suffix.lower() not in self.ALLOWED_SUFFIXES:
            raise CardAttachmentError("Choose a PDF or supported image file.")
        if not source_path.is_file():
            raise CardAttachmentError("The selected card file is no longer available.")

        try:
            folder = self.folder_for(clean_id, employee_name)
            target = folder / f"Leave Card{source_path.suffix.lower()}"
            shutil.copy2(source_path, target)
            index = self._load_index()
            index[clean_id] = {
                "file": str(target.relative_to(self.root)),
                "source_name": source_path.name,
            }
            self._write_index(index)
            return target
        except OSError as error:
            raise CardAttachmentError(f"Could not attach the card: {error}") from error

    def path_for(self, employee_id: str, employee_name: str = "") -> Path | None:
        clean_id = str(employee_id).strip()
        entry = self._load_index().get(clean_id)
        if isinstance(entry, dict):
            relative_file = str(entry.get("file", "")).strip()
            path = self.root / relative_file
            if relative_file and path.is_file() and self.root in path.parents:
                return path
        return self._migrate_legacy_attachment(clean_id, employee_name)

    def _migrate_legacy_attachment(self, employee_id: str, employee_name: str) -> Path | None:
        """Copy a pre-folder attachment into the new employee folder on first use."""
        legacy_index = self.legacy_root / "attachments.json"
        try:
            raw = json.loads(legacy_index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        entry = raw.get(employee_id) if isinstance(raw, dict) else None
        filename = str(entry.get("file", "")).strip() if isinstance(entry, dict) else ""
        source = self.legacy_root / "files" / filename
        if not filename or Path(filename).name != filename or not source.is_file():
            return None
        return self.attach(employee_id, employee_name, source)

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
