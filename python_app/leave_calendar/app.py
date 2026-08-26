from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .settings import app_data_dir
from .ui import LeaveCalendarWindow


APP_STYLESHEET = """
QWidget {
    font-family: "Segoe UI";
    font-size: 12px;
}
QMainWindow, QDialog {
    background: #101318;
}
QLabel {
    color: #cbd5e1;
}
QGroupBox {
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 10px;
    margin-top: 9px;
    padding-top: 7px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
QPushButton {
    background: #202733;
    color: #f8fafc;
    border: 1px solid #384454;
    border-radius: 7px;
    padding: 6px 11px;
    font-weight: 600;
}
QPushButton:hover {
    background: #2a3442;
    border-color: #64748b;
}
QPushButton:pressed {
    background: #161c25;
}
QPushButton:disabled {
    color: #64748b;
    background: #171c24;
    border-color: #293241;
}
QPushButton#primarySmallButton {
    background: #2563eb;
    border-color: #3b82f6;
}
QPushButton#primarySmallButton:hover {
    background: #1d4ed8;
}
QLineEdit, QComboBox {
    background: #1b222d;
    color: #f8fafc;
    border: 1px solid #3b4656;
    border-radius: 7px;
    min-height: 27px;
    padding: 2px 8px;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QComboBox:focus {
    border-color: #38bdf8;
}
QComboBox::drop-down {
    border: 0;
    width: 24px;
}
QComboBox QAbstractItemView {
    color: #f8fafc;
    background: #1b222d;
    border: 1px solid #475569;
    selection-background-color: #2563eb;
    padding: 4px;
}
QTreeWidget {
    color: #e2e8f0;
    background: #171c24;
    alternate-background-color: #1b222d;
    border: 1px solid #334155;
    border-radius: 8px;
}
QHeaderView::section {
    color: #cbd5e1;
    background: #252d39;
    border: 0;
    border-right: 1px solid #374151;
    padding: 7px;
    font-weight: 700;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QScrollBar:vertical {
    background: #141922;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #475569;
    min-height: 32px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QStatusBar {
    color: #94a3b8;
    background: #0c0f14;
    border-top: 1px solid #242c37;
}
QSplitter::handle {
    background: #252d39;
    width: 2px;
}
"""


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
    application.setStyle("Fusion")
    application.setStyleSheet(APP_STYLESHEET)
    application.setApplicationName("Leave Calendar")
    application.setOrganizationName("MAGCLIP")
    window = LeaveCalendarWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
