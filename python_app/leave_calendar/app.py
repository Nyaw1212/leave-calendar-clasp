from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .settings import app_data_dir
from .ui import LeaveCalendarWindow


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        handlers=[
            logging.FileHandler(app_data_dir() / "leave_calendar.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    configure_logging()
    application = QApplication(sys.argv)
    application.setApplicationName("Leave Calendar")
    application.setOrganizationName("MAGCLIP")
    window = LeaveCalendarWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
