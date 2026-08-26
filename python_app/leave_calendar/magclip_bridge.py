from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


SCHEMA = "magclip.magazine/v1"
WORKFLOW = "leave_entry"


def magclip_inbox_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".magclip"
    path = root / "MAGCLIP" / "inbox" if base else root / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def send_to_magclip(
    rows: Sequence[Sequence[str]],
    *,
    employee_id: str,
    employee_name: str,
    inbox: Path | None = None,
) -> Path:
    clean_rows = [[str(value) for value in row] for row in rows]
    if not clean_rows:
        raise ValueError("There are no new MAGCLIP rows to send.")
    if any(len(row) != 7 for row in clean_rows):
        raise ValueError("Every Leave Entry magazine row must contain exactly 7 fields.")

    target_dir = inbox or magclip_inbox_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "workflow": WORKFLOW,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "Leave Calendar",
        "employee": {"id": employee_id, "name": employee_name},
        "rows": clean_rows,
    }
    filename = (
        datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        + "-"
        + uuid.uuid4().hex[:8]
        + ".json"
    )
    destination = target_dir / filename

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".magclip-",
        suffix=".tmp",
        dir=target_dir,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def rows_to_tsv(rows: Iterable[Iterable[str]]) -> str:
    return "\n".join("\t".join(str(value) for value in row) for row in rows)
