from __future__ import annotations

import json
import logging
import traceback
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QIntValidator,
    QKeySequence,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .calendar_navigation import (
    CALENDAR_MAX_YEAR,
    CALENDAR_MIN_YEAR,
    add_months,
    calendar_column_count,
    calendar_navigation_offset,
    calendar_view_start,
    clamp_calendar_month,
)
from .draft_store import DraftStore
from .leave_types import LeaveTypeOption, default_leave_type_options
from .magclip_bridge import rows_to_tsv, send_to_magclip
from .models import DraftEntry, Employee, EmployeeProfile, LeaveDay, SaveResult
from .repository import RepositoryError, SheetsRepository
from .rules import (
    credit_for_day,
    group_consecutive_dates,
    inclusive_dates,
    is_sl_charge,
    is_vl_charge,
    normalize_leave_type,
)
from .settings import AppSettings, app_data_dir, extract_spreadsheet_id


LOGGER = logging.getLogger(__name__)


def _wheel_direction(event: QWheelEvent) -> int:
    delta = event.angleDelta().y()
    if delta == 0:
        return 0
    return 1 if delta > 0 else -1


class WheelStepComboBox(QComboBox):
    wheel_step = Signal(int)

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        direction = _wheel_direction(event)
        if direction:
            self.wheel_step.emit(direction)
            event.accept()
            return
        super().wheelEvent(event)


class WheelStepLineEdit(QLineEdit):
    wheel_step = Signal(int)

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        direction = _wheel_direction(event)
        if direction:
            self.wheel_step.emit(direction)
            event.accept()
            return
        super().wheelEvent(event)


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as error:
            LOGGER.exception("Background operation failed")
            message = str(error).strip() or error.__class__.__name__
            self.signals.error.emit(message)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Google Sheets Connection")
        self.setMinimumWidth(620)

        self.sheet_edit = QLineEdit(settings.spreadsheet_id)
        self.sheet_edit.setPlaceholderText("Paste the full Google Sheet URL or Spreadsheet ID")
        self.credentials_edit = QLineEdit(settings.credentials_path)
        self.credentials_edit.setPlaceholderText("Select the service-account JSON file")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_credentials)

        credentials_row = QHBoxLayout()
        credentials_row.addWidget(self.credentials_edit, 1)
        credentials_row.addWidget(browse)
        credentials_widget = QWidget()
        credentials_widget.setLayout(credentials_row)

        self.account_label = QLabel()
        self.account_label.setWordWrap(True)
        self.account_label.setStyleSheet("color:#94a3b8")
        self.credentials_edit.textChanged.connect(self._show_account)

        form = QFormLayout()
        form.addRow("Google Sheet:", self.sheet_edit)
        form.addRow("Credentials JSON:", credentials_widget)
        form.addRow("Service account:", self.account_label)

        note = QLabel(
            "Share the Google Sheet with the service-account email as Editor. "
            "The JSON stays on this computer and is never stored in GitHub."
        )
        note.setWordWrap(True)
        note.setStyleSheet("background:#eef4ff;padding:10px;border-radius:6px;color:#174ea6")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self._show_account()

    def _browse_credentials(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Google service-account JSON",
            self.credentials_edit.text() or str(Path.home()),
            "JSON files (*.json)",
        )
        if filename:
            self.credentials_edit.setText(filename)

    def _show_account(self) -> None:
        path = Path(self.credentials_edit.text().strip()).expanduser()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            email = str(payload.get("client_email", ""))
        except (OSError, json.JSONDecodeError):
            email = ""
        self.account_label.setText(email or "Select a valid JSON file to see the sharing email.")

    def _validate_and_accept(self) -> None:
        settings = self.settings()
        try:
            settings.validate()
        except ValueError as error:
            QMessageBox.warning(self, "Connection settings", str(error))
            return
        self.accept()

    def settings(self) -> AppSettings:
        return AppSettings(
            spreadsheet_id=extract_spreadsheet_id(self.sheet_edit.text()),
            credentials_path=self.credentials_edit.text().strip(),
        )


class LeaveTypeDialog(QDialog):
    def __init__(
        self,
        options: list[LeaveTypeOption],
        selected_dates: list[date],
        current_leave_type: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose Leave Type")
        self.setMinimumWidth(620)
        self.selected_option: LeaveTypeOption | None = None
        self._shortcuts: list[QShortcut] = []

        title = QLabel("Choose the leave type")
        title.setStyleSheet("font-size:19px;font-weight:800;color:#f8fafc")
        subtitle = QLabel(_selected_date_caption(selected_dates))
        subtitle.setStyleSheet("color:#94a3b8;font-size:12px")

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        seen_shortcuts: set[str] = set()
        first_button: QPushButton | None = None
        for index, option in enumerate(options):
            prefix = f"[{option.shortcut}]  " if option.shortcut else ""
            button = QPushButton(prefix + option.display_name)
            button.setMinimumHeight(42)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{text-align:left;background:#1b2635;border:1px solid #3b4b61;"
                "border-radius:9px;padding:8px 12px;color:#f8fafc;font-weight:700}"
                "QPushButton:hover{background:#22344a;border-color:#38bdf8}"
                "QPushButton:default{border:2px solid #3b82f6;background:#1e3a5f}"
            )
            button.clicked.connect(
                lambda _checked=False, selected=option: self._choose(selected)
            )
            if option.name == current_leave_type:
                button.setDefault(True)
            if first_button is None:
                first_button = button
            grid.addWidget(button, index // 2, index % 2)

            sequence = QKeySequence(option.shortcut).toString(
                QKeySequence.SequenceFormat.PortableText
            )
            sequence_key = sequence.casefold()
            if sequence and sequence_key not in seen_shortcuts:
                shortcut = QShortcut(QKeySequence(sequence), self)
                shortcut.activated.connect(lambda selected=option: self._choose(selected))
                self._shortcuts.append(shortcut)
                seen_shortcuts.add(sequence_key)

        note = QLabel(
            "Choose a button or press its shortcut key. The selection will be added "
            "to Draft Leave History once."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "background:#10243a;color:#bae6fd;border:1px solid #1d4f73;"
            "border-radius:8px;padding:8px"
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(grid)
        layout.addWidget(note)
        layout.addWidget(buttons)
        if first_button:
            first_button.setFocus()

    def _choose(self, option: LeaveTypeOption) -> None:
        self.selected_option = option
        self.accept()


class DayButton(QToolButton):
    pressed_day = Signal(object)
    hovered_day = Signal(object)
    released_day = Signal(object)
    pointed_day = Signal(object)
    unpointed_day = Signal(object)

    def __init__(
        self,
        day: date,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.day = day
        self.compact = compact
        self.setText(str(day.day))
        width, height = (29, 21) if compact else (35, 31)
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed_day.emit(self.day)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # type: ignore[override]
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self.hovered_day.emit(self.day)
        else:
            self.pointed_day.emit(self.day)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self.unpointed_day.emit(self.day)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.buttons() & Qt.MouseButton.LeftButton:
            target = QApplication.widgetAt(event.globalPosition().toPoint())
            if isinstance(target, DayButton):
                self.hovered_day.emit(target.day)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.released_day.emit(self.day)
        super().mouseReleaseEvent(event)


class MultiMonthCalendar(QWidget):
    selected_changed = Signal()
    selection_completed = Signal()
    day_hovered = Signal(object)
    day_unhovered = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        today = date.today()
        self.month_count = 12
        self.start_month = calendar_view_start(today, self.month_count)
        self.selection_mode = "drag"
        self.selected: set[date] = set()
        self.existing: set[date] = set()
        self.holidays: set[date] = set()
        self.draft_dates: set[date] = set()
        self.audit_dates: set[date] = set()
        self._buttons: dict[date, DayButton] = {}
        self._drag_anchor: date | None = None
        self._drag_last: date | None = None
        self._drag_initial: set[date] = set()
        self._drag_moved = False
        self._range_anchor: date | None = None

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self.rebuild()

    def set_view(self, start_month: date, month_count: int) -> None:
        self.month_count = month_count
        self.start_month = calendar_view_start(start_month, month_count)
        self.rebuild()

    @property
    def range_anchor(self) -> date | None:
        return self._range_anchor

    def set_selection_mode(self, mode: str) -> None:
        self.selection_mode = "range" if mode == "range" else "drag"
        self._range_anchor = None
        self._drag_anchor = None
        self._drag_last = None
        self._drag_moved = False
        self.selected_changed.emit()

    def set_audit_dates(self, dates: set[date]) -> None:
        self.audit_dates = set(dates)
        self.apply_styles()

    def dates_are_visible(self, dates: set[date]) -> bool:
        return all(day in self._buttons for day in dates)

    def set_data(
        self,
        *,
        existing: set[date],
        holidays: set[date],
        draft_dates: set[date],
    ) -> None:
        self.existing = set(existing)
        self.holidays = set(holidays)
        self.draft_dates = set(draft_dates)
        self.apply_styles()

    def clear_selection(self) -> None:
        self.selected.clear()
        self._range_anchor = None
        self.apply_styles()
        self.selected_changed.emit()

    def rebuild(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._buttons.clear()

        compact = self.month_count >= 12
        self.grid.setSpacing(4 if compact else 10)
        columns = calendar_column_count(self.month_count)
        for index in range(self.month_count):
            month = add_months(self.start_month, index)
            self.grid.addWidget(self._build_month(month), index // columns, index % columns)
        self.apply_styles()

    def _build_month(self, month: date) -> QWidget:
        compact = self.month_count >= 12
        frame = QFrame()
        frame.setObjectName("monthCard")
        frame.setStyleSheet(
            "QFrame#monthCard{background:white;border:1px solid #dfe3e8;border-radius:8px}"
        )
        layout = QGridLayout(frame)
        layout.setContentsMargins(*(4, 3, 4, 3) if compact else (8, 8, 8, 8))
        layout.setHorizontalSpacing(3 if compact else 6)
        layout.setVerticalSpacing(1 if compact else 4)
        title = QLabel(month.strftime("%B %Y"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-weight:700;color:#08254b;"
            + ("font-size:10px;padding:0" if compact else "padding:3px")
        )
        layout.addWidget(title, 0, 0, 1, 7)

        for column, weekday in enumerate(("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")):
            label = QLabel(weekday)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "color:#667085;font-weight:700;"
                + ("font-size:8px" if compact else "font-size:10px")
            )
            layout.addWidget(label, 1, column)

        first_weekday = (month.weekday() + 1) % 7
        next_month = add_months(month, 1)
        days = (next_month - month).days
        for number in range(1, days + 1):
            day = date(month.year, month.month, number)
            position = first_weekday + number - 1
            button = DayButton(day, compact=compact)
            button.pressed_day.connect(self._begin_drag)
            button.hovered_day.connect(self._drag_over)
            button.released_day.connect(self._end_drag)
            button.pointed_day.connect(self.day_hovered.emit)
            button.unpointed_day.connect(self.day_unhovered.emit)
            layout.addWidget(button, 2 + position // 7, position % 7)
            self._buttons[day] = button
        return frame

    def _begin_drag(self, day: date) -> None:
        if self.selection_mode == "range":
            return
        self._drag_anchor = day
        self._drag_last = day
        self._drag_initial = set(self.selected)
        self._drag_moved = False

    def _drag_over(self, day: date) -> None:
        if self.selection_mode == "range":
            return
        if self._drag_anchor is None or day == self._drag_last:
            return
        self._drag_last = day
        self._drag_moved = day != self._drag_anchor
        selected_range = set(inclusive_dates(self._drag_anchor, day))
        self.selected = self._drag_initial | selected_range
        self.apply_styles()
        self.selected_changed.emit()

    def _end_drag(self, released_day: date) -> None:
        if self.selection_mode == "range":
            self._select_range_endpoint(released_day)
            return
        if self._drag_anchor is None:
            return
        if not self._drag_moved:
            if self._drag_anchor in self.selected:
                self.selected.remove(self._drag_anchor)
            else:
                self.selected.add(self._drag_anchor)
        self._drag_anchor = None
        self._drag_last = None
        self.apply_styles()
        self.selected_changed.emit()
        if self.selected:
            QTimer.singleShot(0, self.selection_completed.emit)

    def _select_range_endpoint(self, day: date) -> None:
        if self._range_anchor is None:
            self._range_anchor = day
            self.selected = {day}
            completed = False
        else:
            self.selected = set(inclusive_dates(self._range_anchor, day))
            self._range_anchor = None
            completed = True
        self.apply_styles()
        self.selected_changed.emit()
        if completed:
            QTimer.singleShot(0, self.selection_completed.emit)

    def apply_styles(self) -> None:
        for day, button in self._buttons.items():
            if day in self.selected and day in self.existing:
                background, color, border = "#fff4e5", "#9a3412", "#f97316"
            elif day in self.selected:
                background, color, border = "#dbeafe", "#174ea6", "#1a73e8"
            elif day in self.existing:
                background, color, border = "#ede9fe", "#5b21b6", "#c4b5fd"
            elif day in self.draft_dates:
                background, color, border = "#dcfce7", "#166534", "#86efac"
            elif day in self.holidays:
                background, color, border = "#fce8e6", "#b3261e", "#d93025"
            elif day.weekday() >= 5:
                background, color, border = "#f2f4f7", "#667085", "#dfe3e8"
            else:
                background, color, border = "#ffffff", "#182230", "#dfe3e8"
            button.setEnabled(True)
            font_size = "9px" if button.compact else "11px"
            radius = "4px" if button.compact else "5px"
            border_width = "3px" if day in self.audit_dates else "1px"
            if day in self.audit_dates:
                border = "#f59e0b"
            button.setStyleSheet(
                "QToolButton{"
                f"background:{background};color:{color};"
                f"border:{border_width} solid {border};"
                f"border-radius:{radius};font-size:{font_size};font-weight:600}}"
                "QToolButton:hover{border:2px solid #06b6d4}"
            )


class LeaveCalendarWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Leave Calendar · Python Desktop")
        self.resize(1450, 900)
        self.setMinimumSize(1080, 720)

        self.thread_pool = QThreadPool.globalInstance()
        self.settings = AppSettings.load()
        self.repository: SheetsRepository | None = None
        self.employees: list[Employee] = []
        self.employee_by_display: dict[str, Employee] = {}
        self.active_employee: Employee | None = None
        self.profile: EmployeeProfile | None = None
        self.holidays: set[date] = set()
        self.existing: set[date] = set()
        self.draft_entries: list[DraftEntry] = []
        self.draft_employee_id = ""
        self.draft_store = DraftStore()
        self.last_saved_rows: tuple[tuple[str, ...], ...] = ()
        self.leave_type_options = default_leave_type_options()
        self.shortcut_leave_types: dict[str, LeaveTypeOption] = {}
        self.draft_item_by_id: dict[str, QTreeWidgetItem] = {}
        self._audit_draft_ids: set[str] = set()
        self._audit_calendar_day: date | None = None
        self._audit_draft_entry_id: str | None = None

        self._build_ui()
        application = QApplication.instance()
        if application:
            application.installEventFilter(self)
        self._set_connected(False)
        QTimer.singleShot(0, self._start)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)

        heading = QHBoxLayout()
        title = QLabel("Leave History Recorder")
        title.setStyleSheet("font-size:21px;font-weight:800;color:#f8fafc")
        self.connection_label = QLabel("Not connected")
        self.connection_label.setStyleSheet("padding:6px 10px;border-radius:10px")
        configure_button = QPushButton("Google Sheets Settings")
        configure_button.clicked.connect(self.configure_connection)
        logs_button = QPushButton("Open Logs")
        logs_button.clicked.connect(self.open_logs)
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.connection_label)
        heading.addWidget(logs_button)
        heading.addWidget(configure_button)
        root.addLayout(heading)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_calendar_side())
        splitter.addWidget(self._build_draft_side())
        splitter.setSizes([1050, 380])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Configure Google Sheets to begin.")

    def _build_calendar_side(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)

        employee_group = QGroupBox("Employee and Leave Details")
        employee_layout = QGridLayout(employee_group)
        self.employee_combo = QComboBox()
        self.employee_combo.setEditable(True)
        self.employee_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.employee_combo.setPlaceholderText("Select an employee or type any name")
        self.employee_combo.activated.connect(self._employee_option_selected)
        if self.employee_combo.lineEdit():
            self.employee_combo.lineEdit().returnPressed.connect(self.use_employee_text)
        use_name = QPushButton("Use / Add Name")
        use_name.clicked.connect(self.use_employee_text)

        self.assumption_edit = QLineEdit()
        self.assumption_edit.setPlaceholderText("YYYY-MM-DD")
        save_date = QPushButton("Save Date")
        save_date.clicked.connect(self.save_assumption_date)

        self.leave_type_combo = QComboBox()
        for option in self.leave_type_options:
            self.leave_type_combo.addItem(option.display_name, option.name)
        self.credit_combo = QComboBox()
        self.credit_combo.addItem("1.000 — Whole Day", 1.0)
        self.credit_combo.addItem("0.500 — Half Day", 0.5)
        self.leave_type_combo.currentIndexChanged.connect(self.update_selected_summary)
        self.credit_combo.currentIndexChanged.connect(self.update_selected_summary)

        self.remarks_edit = QLineEdit()
        self.remarks_edit.setPlaceholderText("Optional historical note")

        employee_layout.addWidget(QLabel("Employee"), 0, 0)
        employee_layout.addWidget(QLabel("Date of Assumption / Entry"), 0, 2)
        employee_layout.addWidget(QLabel("Leave Type"), 0, 4)
        employee_layout.addWidget(QLabel("Credit"), 0, 5)
        employee_layout.addWidget(self.employee_combo, 1, 0)
        employee_layout.addWidget(use_name, 1, 1)
        employee_layout.addWidget(self.assumption_edit, 1, 2)
        employee_layout.addWidget(save_date, 1, 3)
        employee_layout.addWidget(self.leave_type_combo, 1, 4)
        employee_layout.addWidget(self.credit_combo, 1, 5)
        employee_layout.addWidget(QLabel("Remarks"), 2, 0)
        self.shortcut_legend = QLabel("SHORTCUTS  Loading LEAVE_TYPE…")
        self.shortcut_legend.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.shortcut_legend.setStyleSheet(
            "background:#172033;color:#cbd5e1;border:1px solid #334155;"
            "border-radius:7px;padding:3px 8px;font-size:10px;font-weight:700"
        )
        employee_layout.addWidget(self.shortcut_legend, 2, 1, 1, 5)
        employee_layout.addWidget(self.remarks_edit, 3, 0, 1, 6)
        layout.addWidget(employee_group)

        self.metric_labels: dict[str, QLabel] = {}
        metrics = QHBoxLayout()
        for key, label in (
            ("opening_vl", "Opening VL"),
            ("opening_sl", "Opening SL"),
            ("balance_vl", "Current VL"),
            ("balance_sl", "Current SL"),
        ):
            card = QFrame()
            card.setStyleSheet("background:#fff;border:1px solid #dfe3e8;border-radius:8px")
            card_layout = QVBoxLayout(card)
            caption = QLabel(label)
            caption.setStyleSheet("color:#667085;font-size:11px")
            value = QLabel("0.000")
            value.setStyleSheet("font-size:19px;font-weight:800;color:#08254b")
            card_layout.addWidget(caption)
            card_layout.addWidget(value)
            self.metric_labels[key] = value
            metrics.addWidget(card)
        layout.addLayout(metrics)

        navigation = QHBoxLayout()
        previous_button = QPushButton("‹ Previous")
        previous_button.clicked.connect(lambda: self.move_months(-1))
        next_button = QPushButton("Next ›")
        next_button.clicked.connect(lambda: self.move_months(1))
        self.month_count_combo = QComboBox()
        for count in (3, 6, 12):
            self.month_count_combo.addItem(f"{count} Months", count)
        self.month_count_combo.setCurrentIndex(self.month_count_combo.findData(12))
        self.month_count_combo.currentIndexChanged.connect(self.change_month_count)
        self.selection_mode_combo = QComboBox()
        self.selection_mode_combo.addItem("Drag / Click", "drag")
        self.selection_mode_combo.addItem("Start → End", "range")
        self.selection_mode_combo.setMinimumWidth(125)
        self.selection_mode_combo.setToolTip(
            "Drag / Click: drag across dates or toggle individual days.\n"
            "Start → End: click the first date, then click the last date."
        )
        self.selection_mode_combo.currentIndexChanged.connect(self.change_selection_mode)
        today = date.today()
        self.jump_month_combo = WheelStepComboBox()
        for month in range(1, 13):
            self.jump_month_combo.addItem(date(2000, month, 1).strftime("%B"), month)
        self.jump_month_combo.setCurrentIndex(0)
        self.jump_month_combo.setMinimumWidth(132)
        self.jump_month_combo.setFixedHeight(34)
        self.jump_month_combo.setStyleSheet(
            "QComboBox{background:#1f2937;color:#f8fafc;border:1px solid #475569;"
            "border-radius:7px;font-size:13px;font-weight:700;padding:4px 10px}"
        )
        self.jump_month_combo.wheel_step.connect(self.scroll_jump_month)
        self.jump_year_edit = WheelStepLineEdit(str(today.year))
        self.jump_year_edit.setValidator(QIntValidator(CALENDAR_MIN_YEAR, CALENDAR_MAX_YEAR, self))
        self.jump_year_edit.setMaximumWidth(92)
        self.jump_year_edit.setFixedHeight(34)
        self.jump_year_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.jump_year_edit.setMaxLength(4)
        self.jump_year_edit.setToolTip(
            "Enter a year from 1975 to 2100, or hover here and use the mouse wheel."
        )
        self.jump_year_edit.setStyleSheet(
            "QLineEdit{background:#0f172a;color:#f8fafc;border:2px solid #38bdf8;"
            "border-radius:7px;font-size:17px;font-weight:900;padding:2px 8px}"
            "QLineEdit:focus{border-color:#22c55e}"
        )
        self.jump_year_edit.returnPressed.connect(self.jump_to_month)
        self.jump_year_edit.wheel_step.connect(self.scroll_jump_year)
        jump_button = QPushButton("Go")
        jump_button.clicked.connect(self.jump_to_month)
        jump_button.setFixedHeight(34)
        jump_button.setMinimumWidth(54)
        jump_button.setObjectName("primarySmallButton")
        today_button = QPushButton("Today")
        today_button.clicked.connect(self.jump_to_today)
        today_button.setFixedHeight(34)
        today_button.setMinimumWidth(68)

        jump_panel = QFrame()
        jump_panel.setObjectName("calendarJumpPanel")
        jump_panel.setStyleSheet(
            "QFrame#calendarJumpPanel{background:#111827;border:1px solid #334155;"
            "border-radius:10px}"
        )
        jump_layout = QHBoxLayout(jump_panel)
        jump_layout.setContentsMargins(8, 3, 8, 3)
        jump_layout.setSpacing(6)
        month_label = QLabel("MONTH")
        month_label.setStyleSheet("color:#94a3b8;font-size:10px;font-weight:900")
        year_label = QLabel("YEAR")
        year_label.setStyleSheet("color:#94a3b8;font-size:10px;font-weight:900")
        jump_layout.addWidget(month_label)
        jump_layout.addWidget(self.jump_month_combo)
        jump_layout.addWidget(year_label)
        jump_layout.addWidget(self.jump_year_edit)
        jump_layout.addWidget(jump_button)
        jump_layout.addWidget(today_button)
        self.selected_label = QLabel("No dates selected")
        self.selected_label.setStyleSheet("font-weight:700;color:#60a5fa")
        navigation.addWidget(previous_button)
        navigation.addWidget(next_button)
        navigation.addWidget(self.month_count_combo)
        navigation.addWidget(self.selection_mode_combo)
        navigation.addSpacing(8)
        navigation.addWidget(jump_panel)
        navigation.addStretch(1)
        navigation.addWidget(self.selected_label)
        layout.addLayout(navigation)

        self.calendar = MultiMonthCalendar()
        self.calendar.selected_changed.connect(self.update_selected_summary)
        self.calendar.selection_completed.connect(self.open_leave_type_picker)
        self.calendar.day_hovered.connect(self.audit_calendar_day)
        self.calendar.day_unhovered.connect(self.clear_calendar_day_audit)
        self.sync_calendar_jump_controls()
        self.sync_calendar_mode_controls()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.calendar)
        layout.addWidget(scroll, 1)

        legend = QLabel(
            "Select with Drag / Click or Start → End   ·   Blue: selected   ·   "
            "Orange: selected duplicate   ·   Green: in draft   ·   "
            "Purple: already recorded   ·   Gold outline: audit match   ·   "
            "Red: regular holiday   ·   Gray: weekend"
        )
        legend.setStyleSheet("color:#667085;font-size:11px")
        layout.addWidget(legend)

        add_button = QPushButton("＋ Choose Leave Type for Selected Dates")
        add_button.setStyleSheet(
            "QPushButton{background:#1a73e8;color:white;padding:11px;border:0;"
            "border-radius:7px;font-weight:800}QPushButton:hover{background:#1557b0}"
        )
        add_button.clicked.connect(self.open_leave_type_picker)
        layout.addWidget(add_button)
        return container

    def _build_draft_side(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        title = QLabel("Draft Leave History")
        title.setStyleSheet("font-size:17px;font-weight:800;color:#f8fafc")
        self.draft_meta = QLabel("0 entries · 0.000 credits")
        self.draft_meta.setStyleSheet("color:#667085")
        self.audit_hint = QLabel("AUDIT · Hover a draft entry ↔ calendar date")
        self.audit_hint.setStyleSheet(
            "background:#102a33;color:#67e8f9;border:1px solid #155e75;"
            "border-radius:7px;padding:5px 8px;font-size:10px;font-weight:700"
        )
        layout.addWidget(title)
        layout.addWidget(self.draft_meta)
        layout.addWidget(self.audit_hint)

        self.draft_tree = QTreeWidget()
        self.draft_tree.setHeaderLabels(["Type", "Dates", "Days", "Credit", ""])
        draft_header = self.draft_tree.header()
        draft_header.setStretchLastSection(False)
        draft_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        draft_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        draft_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        draft_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        draft_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        draft_header.resizeSection(0, 58)
        draft_header.resizeSection(2, 44)
        draft_header.resizeSection(3, 58)
        draft_header.resizeSection(4, 34)
        self.draft_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.draft_tree.setIndentation(0)
        self.draft_tree.setMouseTracking(True)
        self.draft_tree.itemEntered.connect(self.audit_draft_item)
        layout.addWidget(self.draft_tree, 1)

        actions = QHBoxLayout()
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.remove_draft_entry)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_draft)
        copy_button = QPushButton("Copy TSV")
        copy_button.clicked.connect(self.copy_draft_tsv)
        actions.addWidget(remove_button)
        actions.addWidget(clear_button)
        actions.addWidget(copy_button)
        layout.addLayout(actions)

        save_button = QPushButton("Save to Google Sheets")
        save_button.clicked.connect(lambda: self.save_draft(send=False))
        send_button = QPushButton("Save + Send to MAGCLIP")
        send_button.setStyleSheet(
            "QPushButton{background:#159455;color:white;padding:12px;border:0;"
            "border-radius:7px;font-weight:800}QPushButton:hover{background:#117a45}"
        )
        send_button.clicked.connect(lambda: self.save_draft(send=True))
        retry_button = QPushButton("Send Last Saved Again")
        retry_button.clicked.connect(self.send_last_saved)
        layout.addWidget(save_button)
        layout.addWidget(send_button)
        layout.addWidget(retry_button)

        integration_note = QLabel(
            "MAGCLIP automatically receives the saved 7-field magazine. If MAGCLIP is "
            "busy, the magazine waits in its local queue."
        )
        integration_note.setWordWrap(True)
        integration_note.setStyleSheet(
            "background:#ecfdf3;color:#067647;padding:10px;border-radius:7px;font-size:11px"
        )
        layout.addWidget(integration_note)
        return panel

    def _start(self) -> None:
        if not self.settings.spreadsheet_id or not self.settings.credentials_path:
            self.configure_connection()
            return
        self.connect_repository()

    def configure_connection(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings = dialog.settings()
        self.settings.save()
        self.connect_repository()

    def connect_repository(self) -> None:
        self.statusBar().showMessage("Connecting to Google Sheets…")
        self._set_connected(False, "Connecting…")

        def job() -> tuple[
            SheetsRepository,
            list[Employee],
            set[date],
            list[LeaveTypeOption],
        ]:
            repository = SheetsRepository(self.settings)
            repository.connect()
            return (
                repository,
                repository.employees(force=True),
                repository.regular_holidays(True),
                repository.leave_types(force=True),
            )

        self.run_job(job, self._connected)

    def _connected(self, result: object) -> None:
        repository, employees, holidays, leave_types = result  # type: ignore[misc]
        self.repository = repository
        self.employees = employees
        self.holidays = holidays
        self.apply_leave_type_options(leave_types)
        self.populate_employees()
        self._set_connected(True, repository.spreadsheet_title)
        shortcut_count = len(self.shortcut_leave_types)
        self.statusBar().showMessage(
            f"Connected to {repository.spreadsheet_title} · "
            f"{shortcut_count} LEAVE_TYPE shortcut(s) loaded",
            7000,
        )

        draft_employee_id, entries = self.draft_store.load()
        self.draft_entries = entries
        self.draft_employee_id = draft_employee_id if entries else ""
        self.render_draft()
        if draft_employee_id:
            employee = next(
                (item for item in self.employees if item.employee_id == draft_employee_id),
                None,
            )
            if employee:
                self.activate_employee(employee)

    def _set_connected(self, connected: bool, text: str = "Not connected") -> None:
        color = "#067647" if connected else "#b42318"
        background = "#ecfdf3" if connected else "#fef3f2"
        self.connection_label.setText(text or ("Connected" if connected else "Not connected"))
        self.connection_label.setStyleSheet(
            f"color:{color};background:{background};padding:6px 10px;border-radius:10px;font-weight:700"
        )

    def apply_leave_type_options(self, options: list[LeaveTypeOption]) -> None:
        previous = self.current_leave_type()
        self.leave_type_options = list(options) or default_leave_type_options()
        self.leave_type_combo.blockSignals(True)
        self.leave_type_combo.clear()
        for option in self.leave_type_options:
            self.leave_type_combo.addItem(option.display_name, option.name)
        previous_index = self.leave_type_combo.findData(previous)
        self.leave_type_combo.setCurrentIndex(previous_index if previous_index >= 0 else 0)
        self.leave_type_combo.blockSignals(False)

        shortcuts: dict[str, LeaveTypeOption] = {}
        legend_items: list[str] = []
        legend_details: list[str] = []
        for option in self.leave_type_options:
            if not option.shortcut:
                continue
            sequence = QKeySequence(option.shortcut).toString(
                QKeySequence.SequenceFormat.PortableText
            )
            if not sequence:
                LOGGER.warning(
                    "Ignoring invalid LEAVE_TYPE shortcut %r for %s",
                    option.shortcut,
                    option.name,
                )
                continue
            key = sequence.casefold()
            if key in shortcuts:
                LOGGER.warning(
                    "Ignoring duplicate LEAVE_TYPE shortcut %s for %s",
                    sequence,
                    option.name,
                )
                continue
            shortcuts[key] = option
            legend_items.append(f"[{sequence}] {option.legend_name}")
            legend_details.append(f"{sequence}: {option.display_name}")
        self.shortcut_leave_types = shortcuts

        if legend_items:
            self.shortcut_legend.setText("SHORTCUTS  " + "   •   ".join(legend_items))
            self.shortcut_legend.setToolTip(
                "Press a shortcut to choose the leave type. Use Add Selected Dates "
                "to create one draft entry.\n"
                + "\n".join(legend_details)
            )
        else:
            self.shortcut_legend.setText("SHORTCUTS  Add keys in the LEAVE_TYPE sheet")
            self.shortcut_legend.setToolTip(
                "Add a Shortcut or Shortcut Key column to LEAVE_TYPE, then reconnect."
            )
        self.update_selected_summary()

    def current_leave_type(self) -> str:
        return str(self.leave_type_combo.currentData() or self.leave_type_combo.currentText())

    def leave_code(self, leave_type: str) -> str:
        normalized = normalize_leave_type(leave_type)
        option = next(
            (
                item
                for item in self.leave_type_options
                if normalize_leave_type(item.name) == normalized
            ),
            None,
        )
        return option.code if option and option.code else _leave_code(normalized)

    def populate_employees(self, selected_id: str = "") -> None:
        self.employee_combo.blockSignals(True)
        self.employee_combo.clear()
        self.employee_by_display = {item.display_name: item for item in self.employees}
        self.employee_combo.addItems(self.employee_by_display.keys())
        if selected_id:
            employee = next((x for x in self.employees if x.employee_id == selected_id), None)
            if employee:
                self.employee_combo.setCurrentText(employee.display_name)
        else:
            self.employee_combo.setCurrentIndex(-1)
        self.employee_combo.blockSignals(False)

    def _employee_option_selected(self, _index: int) -> None:
        employee = self.employee_by_display.get(self.employee_combo.currentText())
        if employee:
            self.activate_employee(employee)

    def use_employee_text(self) -> None:
        if self.repository is None:
            self.show_error("Connect to Google Sheets first.")
            return
        text = " ".join(self.employee_combo.currentText().split())
        if not text:
            self.show_error("Select an employee or type a name.")
            return
        if text in self.employee_by_display:
            self.activate_employee(self.employee_by_display[text])
            return

        name_matches = [item for item in self.employees if item.name.casefold() == text.casefold()]
        if name_matches:
            self.activate_employee(name_matches[0])
            return

        answer = QMessageBox.question(
            self,
            "Add manual employee",
            f'Add "{text}" as a reusable employee?\n\nA unique Employee ID will be created automatically.',
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.statusBar().showMessage(f"Adding {text}…")
        self.run_job(
            lambda: self.repository.get_or_create_employee(text),  # type: ignore[union-attr]
            self._manual_employee_ready,
        )

    def _manual_employee_ready(self, result: object) -> None:
        employee, created = result  # type: ignore[misc]
        if created:
            self.employees.append(employee)
            self.employees.sort(key=lambda item: item.name.casefold())
        self.populate_employees(employee.employee_id)
        self.activate_employee(employee)
        self.statusBar().showMessage(
            f"{employee.name} was added and is ready for leave entry.",
            5000,
        )

    def activate_employee(self, employee: Employee) -> None:
        if self.draft_entries and self.draft_employee_id not in ("", employee.employee_id):
            answer = QMessageBox.question(
                self,
                "Switch employee",
                "The current draft belongs to another employee. Clear that draft and switch?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.populate_employees(self.draft_employee_id)
                return
            self.draft_entries.clear()
            self.draft_employee_id = ""
            self.draft_store.clear()
            self.render_draft()

        self.active_employee = employee
        self.populate_employees(employee.employee_id)
        self.assumption_edit.setText(
            employee.assumption_date.isoformat() if employee.assumption_date else ""
        )
        self.calendar.clear_selection()
        self.statusBar().showMessage(f"Loading {employee.name}…")

        def job() -> tuple[Employee, EmployeeProfile, set[date], set[date]]:
            assert self.repository is not None
            refreshed = self.repository.employee_by_id(employee.employee_id, force=True) or employee
            return (
                refreshed,
                self.repository.employee_profile(refreshed, force=True),
                self.repository.existing_dates(refreshed.employee_id),
                self.repository.regular_holidays(),
            )

        self.run_job(job, self._employee_loaded)

    def _employee_loaded(self, result: object) -> None:
        employee, profile, existing, holidays = result  # type: ignore[misc]
        self.active_employee = employee
        self.profile = profile
        self.existing = existing
        self.holidays = holidays
        self.assumption_edit.setText(
            employee.assumption_date.isoformat() if employee.assumption_date else ""
        )
        self.update_profile_metrics()
        self.update_calendar_data()
        self.statusBar().showMessage(f"Ready: {employee.name}", 5000)

    def save_assumption_date(self) -> None:
        if not self.active_employee or not self.repository:
            self.show_error("Select or manually enter an employee first.")
            return
        try:
            assumption_date = date.fromisoformat(self.assumption_edit.text().strip())
        except ValueError:
            self.show_error("Enter the Date of Assumption as YYYY-MM-DD.")
            return
        if assumption_date > date.today() and not self.confirm_warning(
            "Future Date of Assumption",
            "The Date of Assumption is in the future. It will produce no earned leave "
            "credit as of today.\n\nSave it anyway?",
        ):
            return
        employee_id = self.active_employee.employee_id
        self.statusBar().showMessage("Saving Date of Assumption…")
        self.run_job(
            lambda: self.repository.save_employee_profile(employee_id, assumption_date),
            self._profile_saved,
        )

    def _profile_saved(self, result: object) -> None:
        employee = result  # type: ignore[assignment]
        self.active_employee = employee
        self.employees = [
            employee if item.employee_id == employee.employee_id else item for item in self.employees
        ]
        assert self.repository is not None
        self.profile = self.repository.employee_profile(employee)
        self.update_profile_metrics()
        self.statusBar().showMessage("Date of Assumption saved and credits recalculated.", 6000)

    def update_profile_metrics(self) -> None:
        profile = self.profile
        for key, label in self.metric_labels.items():
            label.setText(f"{float(getattr(profile, key, 0) if profile else 0):.3f}")

    def update_calendar_data(self) -> None:
        draft_dates = {item.day for entry in self.draft_entries for item in entry.days}
        self.calendar.set_data(
            existing=self.existing,
            holidays=self.holidays,
            draft_dates=draft_dates,
        )
        self.update_selected_summary()

    def move_months(self, offset: int) -> None:
        navigation_offset = calendar_navigation_offset(
            self.calendar.month_count,
            offset,
        )
        self.calendar.set_view(
            clamp_calendar_month(
                add_months(self.calendar.start_month, navigation_offset)
            ),
            self.calendar.month_count,
        )
        self.sync_calendar_jump_controls()
        self.update_calendar_data()

    def jump_to_month(self) -> None:
        month = int(self.jump_month_combo.currentData() or 1)
        try:
            year = int(self.jump_year_edit.text())
        except ValueError:
            year = self.calendar.start_month.year
        if not CALENDAR_MIN_YEAR <= year <= CALENDAR_MAX_YEAR:
            self.show_error(
                f"Enter a year from {CALENDAR_MIN_YEAR} to {CALENDAR_MAX_YEAR}."
            )
            self.sync_calendar_jump_controls()
            return
        self.calendar.set_view(date(year, month, 1), self.calendar.month_count)
        self.sync_calendar_jump_controls()
        self.update_calendar_data()

    def jump_to_today(self) -> None:
        today = date.today().replace(day=1)
        self.calendar.set_view(today, self.calendar.month_count)
        self.sync_calendar_jump_controls()
        self.update_calendar_data()

    def scroll_jump_month(self, direction: int) -> None:
        if not self.jump_month_combo.isEnabled():
            return
        month = int(self.jump_month_combo.currentData() or 1)
        try:
            year = int(self.jump_year_edit.text())
        except ValueError:
            year = self.calendar.start_month.year
        target = clamp_calendar_month(add_months(date(year, month, 1), direction))
        self.jump_month_combo.setCurrentIndex(target.month - 1)
        self.jump_year_edit.setText(str(target.year))
        self.jump_to_month()

    def scroll_jump_year(self, direction: int) -> None:
        try:
            year = int(self.jump_year_edit.text())
        except ValueError:
            year = self.calendar.start_month.year
        year = min(max(year + direction, CALENDAR_MIN_YEAR), CALENDAR_MAX_YEAR)
        self.jump_year_edit.setText(str(year))
        self.jump_to_month()

    def sync_calendar_jump_controls(self) -> None:
        self.jump_month_combo.setCurrentIndex(self.calendar.start_month.month - 1)
        self.jump_year_edit.setText(str(self.calendar.start_month.year))

    def sync_calendar_mode_controls(self) -> None:
        yearly_view = self.calendar.month_count >= 12
        self.jump_month_combo.setEnabled(not yearly_view)
        self.jump_month_combo.setToolTip(
            "The 12-month view always shows January through December. "
            "Hover over YEAR and use the mouse wheel to change years."
            if yearly_view
            else "Choose the first month, or hover here and use the mouse wheel."
        )

    def change_month_count(self) -> None:
        count = int(self.month_count_combo.currentData() or 3)
        self.calendar.set_view(self.calendar.start_month, count)
        self.sync_calendar_jump_controls()
        self.sync_calendar_mode_controls()
        self.update_calendar_data()

    def change_selection_mode(self) -> None:
        mode = str(self.selection_mode_combo.currentData() or "drag")
        self.calendar.set_selection_mode(mode)
        message = (
            "Start → End mode: click the first date, then click the last date."
            if mode == "range"
            else "Drag / Click mode: drag across dates or click individual days."
        )
        self.statusBar().showMessage(message, 6000)

    def update_selected_summary(self) -> None:
        selected = self.calendar.selected
        if self.calendar.range_anchor is not None:
            self.selected_label.setText(
                f"Start: {self.calendar.range_anchor:%b %d, %Y} · click the end date"
            )
            return
        leave_type = self.current_leave_type()
        requested_credit = float(self.credit_combo.currentData() or 1)
        credits = sum(
            credit_for_day(day, leave_type, requested_credit, self.holidays)
            for day in selected
        )
        self.selected_label.setText(
            f"{len(selected)} selected · {credits:.3f} credit" if selected else "No dates selected"
        )

    def open_leave_type_picker(self) -> None:
        if not self.active_employee:
            self.show_error("Select or manually enter an employee first.")
            return
        if self.calendar.range_anchor is not None:
            self.show_error("Click the end date to complete the selected range.")
            return
        if not self.calendar.selected:
            self.show_error("Select at least one date.")
            return

        dialog = LeaveTypeDialog(
            self.leave_type_options,
            sorted(self.calendar.selected),
            self.current_leave_type(),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.selected_option is None:
            self.statusBar().showMessage(
                "Leave type selection canceled; the dates remain selected.",
                5000,
            )
            return

        index = self.leave_type_combo.findData(dialog.selected_option.name)
        if index >= 0:
            self.leave_type_combo.setCurrentIndex(index)
        self.add_to_draft()

    def add_to_draft(self) -> None:
        if not self.active_employee:
            self.show_error("Select or manually enter an employee first.")
            return
        if self.calendar.range_anchor is not None:
            self.show_error("Click the end date to complete the selected range.")
            return
        if not self.calendar.selected:
            self.show_error("Select at least one date.")
            return

        leave_type = self.current_leave_type()
        requested_credit = float(self.credit_combo.currentData() or 1)
        warnings: list[str] = []
        assumption_date = self.profile.assumption_date if self.profile else None
        if assumption_date is None:
            warnings.append(
                "No Date of Assumption is saved. The leave entry can still be recorded, "
                "but the employee's credit balance will remain unavailable."
            )
        else:
            before_assumption = sum(
                1 for day in self.calendar.selected if day < assumption_date
            )
            if before_assumption:
                warnings.append(
                    f"{before_assumption} selected date(s) occur before the saved Date "
                    "of Assumption."
                )

        duplicate_dates = self.calendar.selected & self.existing
        if duplicate_dates:
            warnings.append(
                f"{len(duplicate_dates)} selected date(s) are already recorded. They will "
                "be saved again as additional historical entries."
            )

        draft_dates = {
            item.day
            for entry in self.draft_entries
            for item in entry.days
        }
        duplicate_draft_dates = self.calendar.selected & draft_dates
        if duplicate_draft_dates:
            warnings.append(
                f"{len(duplicate_draft_dates)} selected date(s) are already in this "
                "draft. Continuing will create another draft entry for those dates."
            )

        if is_vl_charge(leave_type) or is_sl_charge(leave_type):
            zero_credit_dates = sum(
                1
                for day in self.calendar.selected
                if credit_for_day(day, leave_type, requested_credit, self.holidays) == 0
            )
            if zero_credit_dates:
                warnings.append(
                    f"{zero_credit_dates} weekend or regular-holiday date(s) will be "
                    "saved with 0 credit."
                )

        if warnings and not self.confirm_warning(
            "Review Historical Entry",
            "\n\n".join(warnings) + "\n\nContinue and add these dates to the draft?",
        ):
            return

        days = tuple(
            LeaveDay(
                day,
                credit_for_day(day, leave_type, requested_credit, self.holidays),
            )
            for day in sorted(self.calendar.selected)
        )
        self.draft_entries.append(
            DraftEntry(
                entry_id=uuid.uuid4().hex,
                leave_type=leave_type,
                days=days,
                remarks=self.remarks_edit.text().strip(),
            )
        )
        self.draft_employee_id = self.active_employee.employee_id
        self.remarks_edit.clear()
        self.calendar.clear_selection()
        self.render_draft()
        self.statusBar().showMessage("Leave added to draft.", 4000)

    def render_draft(self) -> None:
        self.clear_audit_link()
        self.draft_tree.clear()
        self.draft_item_by_id = {}
        total = 0.0
        for entry in self.draft_entries:
            total += entry.total_credits
            dates = entry.first_day.strftime("%m/%d/%Y")
            if entry.last_day != entry.first_day:
                dates += " → " + entry.last_day.strftime("%m/%d/%Y")
            item = QTreeWidgetItem(
                [
                    self.leave_code(entry.leave_type),
                    dates,
                    str(len(entry.days)),
                    f"{entry.total_credits:.3f}",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, entry.entry_id)
            item.setToolTip(0, entry.remarks)
            self.draft_tree.addTopLevelItem(item)
            self.draft_item_by_id[entry.entry_id] = item
            remove_button = QPushButton("×")
            remove_button.setToolTip("Remove this draft entry")
            remove_button.setFixedSize(24, 22)
            remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_button.setStyleSheet(
                "QPushButton{background:transparent;color:#f87171;border:0;"
                "font-size:18px;font-weight:900;padding:0}"
                "QPushButton:hover{background:#3f1d24;color:#fecaca;border-radius:5px}"
            )
            remove_button.clicked.connect(
                lambda _checked=False, entry_id=entry.entry_id: self.remove_draft_entry_by_id(
                    entry_id
                )
            )
            self.draft_tree.setItemWidget(item, 4, remove_button)
        self.draft_meta.setText(
            f"{len(self.draft_entries)} entr{'y' if len(self.draft_entries) == 1 else 'ies'} · "
            f"{total:.3f} credits"
        )
        if self.draft_entries and self.draft_employee_id:
            self.draft_store.save(self.draft_employee_id, self.draft_entries)
        elif not self.draft_entries:
            self.draft_store.clear()
        if hasattr(self, "calendar"):
            self.update_calendar_data()

    def audit_draft_item(self, item: QTreeWidgetItem, _column: int) -> None:
        entry_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        entry = next(
            (candidate for candidate in self.draft_entries if candidate.entry_id == entry_id),
            None,
        )
        if entry is None:
            self.clear_draft_hover_audit()
            return

        self._clear_draft_row_highlights()
        self._audit_calendar_day = None
        self._audit_draft_entry_id = entry.entry_id
        dates = {leave_day.day for leave_day in entry.days}
        if dates and not self.calendar.dates_are_visible(dates):
            self.calendar.set_view(entry.first_day.replace(day=1), self.calendar.month_count)
            self.sync_calendar_jump_controls()
            self.update_calendar_data()
        self.calendar.set_audit_dates(dates)
        self.audit_hint.setText(
            f"AUDIT · {self.leave_code(entry.leave_type)} · "
            f"{_selected_date_caption(sorted(dates))}"
        )

    def clear_draft_hover_audit(self) -> None:
        if self._audit_draft_entry_id is None:
            return
        self._audit_draft_entry_id = None
        self.calendar.set_audit_dates(set())
        if self._audit_calendar_day is None:
            self._reset_audit_hint()

    def audit_calendar_day(self, day: date) -> None:
        if self._audit_draft_entry_id is not None:
            self._audit_draft_entry_id = None
            self.calendar.set_audit_dates(set())
        self._audit_calendar_day = day
        matches = [
            entry
            for entry in self.draft_entries
            if any(leave_day.day == day for leave_day in entry.days)
        ]
        self._set_draft_row_highlights({entry.entry_id for entry in matches})
        if matches:
            first_item = self.draft_item_by_id.get(matches[0].entry_id)
            if first_item is not None:
                self.draft_tree.scrollToItem(first_item)
            count = len(matches)
            self.audit_hint.setText(
                f"AUDIT · {day:%b %d, %Y} · {count} matching draft "
                f"entr{'y' if count == 1 else 'ies'}"
            )
        else:
            self.audit_hint.setText(
                f"AUDIT · {day:%b %d, %Y} · no matching draft entry"
            )

    def clear_calendar_day_audit(self, day: date) -> None:
        if self._audit_calendar_day != day:
            return
        self._audit_calendar_day = None
        self._clear_draft_row_highlights()
        if self._audit_draft_entry_id is None:
            self._reset_audit_hint()

    def _set_draft_row_highlights(self, entry_ids: set[str]) -> None:
        self._clear_draft_row_highlights()
        background = QBrush(QColor("#155e75"))
        foreground = QBrush(QColor("#ecfeff"))
        for entry_id in entry_ids:
            item = self.draft_item_by_id.get(entry_id)
            if item is None:
                continue
            for column in range(self.draft_tree.columnCount()):
                item.setBackground(column, background)
                item.setForeground(column, foreground)
        self._audit_draft_ids = set(entry_ids)

    def _clear_draft_row_highlights(self) -> None:
        if not self._audit_draft_ids:
            return
        empty_brush = QBrush()
        for entry_id in self._audit_draft_ids:
            item = self.draft_item_by_id.get(entry_id)
            if item is None:
                continue
            for column in range(self.draft_tree.columnCount()):
                item.setBackground(column, empty_brush)
                item.setForeground(column, empty_brush)
        self._audit_draft_ids.clear()

    def clear_audit_link(self) -> None:
        self._audit_calendar_day = None
        self._audit_draft_entry_id = None
        self._clear_draft_row_highlights()
        if hasattr(self, "calendar"):
            self.calendar.set_audit_dates(set())
        self._reset_audit_hint()

    def _reset_audit_hint(self) -> None:
        if hasattr(self, "audit_hint"):
            self.audit_hint.setText("AUDIT · Hover a draft entry ↔ calendar date")

    def remove_draft_entry(self) -> None:
        selected = self.draft_tree.currentItem()
        if not selected:
            return
        entry_id = str(selected.data(0, Qt.ItemDataRole.UserRole))
        self.remove_draft_entry_by_id(entry_id)

    def remove_draft_entry_by_id(self, entry_id: str) -> None:
        self.draft_entries = [entry for entry in self.draft_entries if entry.entry_id != entry_id]
        if not self.draft_entries:
            self.draft_employee_id = ""
        self.render_draft()

    def clear_draft(self) -> None:
        if not self.draft_entries:
            return
        if QMessageBox.question(self, "Clear draft", "Clear all draft leave entries?") != QMessageBox.StandardButton.Yes:
            return
        self.draft_entries.clear()
        self.draft_employee_id = ""
        self.render_draft()

    def draft_magclip_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for entry in self.draft_entries:
            for group in group_consecutive_dates(entry.days, date_getter=lambda item: item.day):
                total = sum(item.credits for item in group)
                rows.append(
                    [
                        entry.leave_type,
                        group[0].day.strftime("%m/%d/%Y"),
                        group[-1].day.strftime("%m/%d/%Y"),
                        "A",
                        f"{total if is_vl_charge(entry.leave_type) else 0:.3f}",
                        f"{total if is_sl_charge(entry.leave_type) else 0:.3f}",
                        "0.000",
                    ]
                )
        return rows

    def copy_draft_tsv(self) -> None:
        rows = self.draft_magclip_rows()
        if not rows:
            self.show_error("The draft is empty.")
            return
        QApplication.clipboard().setText(rows_to_tsv(rows))
        self.statusBar().showMessage("Draft MAGCLIP rows copied as TSV.", 5000)

    def save_draft(self, send: bool) -> None:
        if not self.repository or not self.active_employee:
            self.show_error("Select an employee and connect to Google Sheets first.")
            return
        if not self.draft_entries:
            self.show_error("Add at least one leave entry to the draft.")
            return
        employee = self.active_employee
        entries = list(self.draft_entries)
        self.statusBar().showMessage(
            "Saving and sending to MAGCLIP…" if send else "Saving to Google Sheets…"
        )

        def job() -> tuple[SaveResult, Path | None]:
            assert self.repository is not None
            result = self.repository.save_draft(employee, entries)
            inbox_file = None
            if send and result.magclip_rows:
                inbox_file = send_to_magclip(
                    result.magclip_rows,
                    employee_id=employee.employee_id,
                    employee_name=employee.name,
                )
            return result, inbox_file

        self.run_job(job, lambda result: self._draft_saved(result, send))

    def _draft_saved(self, payload: object, sent: bool) -> None:
        result, inbox_file = payload  # type: ignore[misc]
        self.last_saved_rows = result.magclip_rows
        if result.rows_written:
            self.draft_entries.clear()
            self.draft_employee_id = ""
            self.render_draft()
        message = result.message
        if sent and inbox_file:
            message += " MAGCLIP magazine queued automatically."
        QMessageBox.information(self, "Leave history saved", message)
        self.statusBar().showMessage(message, 9000)
        if self.active_employee:
            self.activate_employee(self.active_employee)

    def send_last_saved(self) -> None:
        if not self.last_saved_rows or not self.active_employee:
            self.show_error("There are no rows from the latest save to send again.")
            return
        try:
            send_to_magclip(
                self.last_saved_rows,
                employee_id=self.active_employee.employee_id,
                employee_name=self.active_employee.name,
            )
        except Exception as error:
            LOGGER.exception("Could not send last saved magazine")
            self.show_error(str(error))
            return
        self.statusBar().showMessage("Last saved magazine queued for MAGCLIP.", 6000)

    def run_job(self, function: Callable[[], Any], on_success: Callable[[object], None]) -> None:
        worker = Worker(function)
        worker.signals.result.connect(on_success)
        worker.signals.error.connect(self.show_error)
        self.thread_pool.start(worker)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if hasattr(self, "draft_tree") and watched is self.draft_tree.viewport():
            if event.type() == QEvent.Type.Leave:
                self.clear_draft_hover_audit()
            elif event.type() == QEvent.Type.MouseMove:
                position = event.position().toPoint()  # type: ignore[attr-defined]
                if self.draft_tree.itemAt(position) is None:
                    self.clear_draft_hover_audit()
        if (
            event.type() == QEvent.Type.KeyPress
            and QApplication.activeWindow() is self
            and not event.isAutoRepeat()  # type: ignore[attr-defined]
        ):
            focus = QApplication.focusWidget()
            if not isinstance(focus, (QLineEdit, QComboBox)):
                key_combination = event.keyCombination()  # type: ignore[attr-defined]
                sequence = QKeySequence(key_combination).toString(
                    QKeySequence.SequenceFormat.PortableText,
                )
                option = self.shortcut_leave_types.get(sequence.casefold())
                if option:
                    self.activate_leave_type_shortcut(option, sequence)
                    return True
        return super().eventFilter(watched, event)

    def activate_leave_type_shortcut(
        self,
        option: LeaveTypeOption,
        sequence: str,
    ) -> None:
        index = self.leave_type_combo.findData(option.name)
        if index >= 0:
            self.leave_type_combo.setCurrentIndex(index)
        self.statusBar().showMessage(
            f"{sequence}: {option.display_name} selected · click Add Selected Dates to Draft.",
            6000,
        )

    def show_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 10000)
        QMessageBox.critical(self, "Leave Calendar", message)

    def confirm_warning(self, title: str, message: str) -> bool:
        answer = QMessageBox.warning(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def open_logs(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_data_dir())))


def _leave_code(value: str) -> str:
    normalized = normalize_leave_type(value)
    return {
        "Vacation Leave": "VL",
        "Sick Leave": "SL",
        "Forced Leave": "FL",
        "Special Privilege Leave": "SPL",
        "Compensatory Time Off": "CTO",
        "Maternity Leave": "ML",
        "Paternity Leave": "PL",
    }.get(normalized, normalized)


def _selected_date_caption(selected_dates: list[date]) -> str:
    if not selected_dates:
        return "No dates selected"
    first = min(selected_dates)
    last = max(selected_dates)
    count = len(selected_dates)
    date_range = first.strftime("%b %d, %Y")
    if last != first:
        date_range += " → " + last.strftime("%b %d, %Y")
    return f"{count} selected date{'s' if count != 1 else ''} · {date_range}"
