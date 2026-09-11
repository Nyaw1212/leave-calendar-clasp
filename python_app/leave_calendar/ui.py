from __future__ import annotations

import logging
import traceback
import uuid
from datetime import date
from typing import Any, Callable

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QObject,
    QPoint,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QCursor,
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
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
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
from .credits_page import CreditsPage
from .date_input import DateInputError, parse_assumption_date
from .draft_store import DraftStore
from .fast_entry import FastDateError, parse_fast_range
from .history_import import HistoryImportError, parse_history_text
from .leave_types import LeaveTypeOption, default_leave_type_options
from .local_repository import LocalRepository
from .lookup_hotkey import ModifierPeekState
from .login_launcher import (
    DEFAULT_LOGIN_SEQUENCE,
    destination_login_sequence,
    launch_and_login,
    validate_executable,
)
from .magclip_bridge import rows_to_tsv
from .magclip_page import MagclipModePage
from .models import (
    DraftEntry,
    Employee,
    EmployeeProfile,
    Holiday,
    LeaveDay,
    LeaveRecord,
    SaveResult,
)
from .philippine_holidays import (
    holidays_for_year,
    local_holidays,
    timeanddate_calendar_url,
)
from .rules import (
    credit_for_day,
    group_consecutive_dates,
    inclusive_dates,
    is_sl_charge,
    is_mone_charge,
    is_vl_charge,
    normalize_leave_type,
)
from .settings import AppSettings, app_data_dir


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


class LookupHotkeyBridge(QObject):
    visibility_requested = Signal(bool)


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


class MoneAllocationDialog(QDialog):
    def __init__(self, total: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.total = round(max(0.0, total), 3)
        self._syncing = False
        self.setWindowTitle("Allocate MONE Credits")
        self.setMinimumWidth(460)

        title = QLabel("Allocate MONE between VL and SL")
        title.setStyleSheet("font-size:18px;font-weight:800;color:#f8fafc")
        total_label = QLabel(f"MONE total: {self.total:.3f} days")
        total_label.setStyleSheet("color:#93c5fd;font-size:13px;font-weight:700")

        self.vl_input = self._allocation_input(self.total)
        self.sl_input = self._allocation_input(0.0)
        self.vl_input.valueChanged.connect(self._vl_changed)
        self.sl_input.valueChanged.connect(self._sl_changed)

        grid = QGridLayout()
        grid.addWidget(QLabel("Vacation Leave (VL)"), 0, 0)
        grid.addWidget(self.vl_input, 0, 1)
        grid.addWidget(QLabel("Sick Leave (SL)"), 1, 0)
        grid.addWidget(self.sl_input, 1, 1)

        hint = QLabel(
            "Enter either amount. The other amount is computed automatically "
            "so VL + SL always equals the total. Weekends and holidays count."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            "background:#10243a;color:#bae6fd;border:1px solid #1d4f73;"
            "border-radius:8px;padding:9px"
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(total_label)
        layout.addLayout(grid)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.vl_input.selectAll()
        self.vl_input.setFocus()

    def _allocation_input(self, value: float) -> QDoubleSpinBox:
        field = QDoubleSpinBox()
        field.setDecimals(3)
        field.setRange(0.0, self.total)
        field.setSingleStep(0.5)
        field.setValue(value)
        field.setSuffix(" days")
        field.setMinimumHeight(38)
        field.setStyleSheet("font-size:15px;font-weight:700")
        return field

    def _vl_changed(self, value: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.sl_input.setValue(round(self.total - value, 3))
        self._syncing = False

    def _sl_changed(self, value: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.vl_input.setValue(round(self.total - value, 3))
        self._syncing = False

    @property
    def allocation(self) -> tuple[float, float]:
        return round(self.vl_input.value(), 3), round(self.sl_input.value(), 3)


class EditLeaveDialog(QDialog):
    def __init__(
        self,
        options: list[LeaveTypeOption],
        leave_type: str,
        start: date,
        end: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Leave Entry")
        self.setMinimumWidth(440)
        self.start_date = start
        self.end_date = end

        title = QLabel("Edit leave type and dates")
        title.setStyleSheet("font-size:18px;font-weight:800;color:#f8fafc")
        self.leave_type_combo = QComboBox()
        current_index = -1
        current_normalized = normalize_leave_type(leave_type)
        for option in options:
            self.leave_type_combo.addItem(option.display_name, option.name)
            if normalize_leave_type(option.name) == current_normalized:
                current_index = self.leave_type_combo.count() - 1
        if current_index < 0:
            self.leave_type_combo.addItem(leave_type, leave_type)
            current_index = self.leave_type_combo.count() - 1
        self.leave_type_combo.setCurrentIndex(current_index)

        self.start_edit = QLineEdit(start.strftime("%m/%d/%Y"))
        self.end_edit = QLineEdit(end.strftime("%m/%d/%Y"))
        self.start_edit.setPlaceholderText("MM/DD/YYYY")
        self.end_edit.setPlaceholderText("MM/DD/YYYY")
        self.start_edit.selectAll()

        grid = QGridLayout()
        grid.addWidget(QLabel("Leave Type"), 0, 0)
        grid.addWidget(self.leave_type_combo, 0, 1)
        grid.addWidget(QLabel("Start Date"), 1, 0)
        grid.addWidget(self.start_edit, 1, 1)
        grid.addWidget(QLabel("End Date"), 2, 0)
        grid.addWidget(self.end_edit, 2, 1)

        note = QLabel(
            "Saving recalculates the Days and Credit values using weekends and "
            "Philippine regular holidays."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "background:#10243a;color:#bae6fd;border:1px solid #1d4f73;"
            "border-radius:8px;padding:8px"
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(11)
        layout.addWidget(title)
        layout.addLayout(grid)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.start_edit.setFocus()

    @property
    def leave_type(self) -> str:
        return str(
            self.leave_type_combo.currentData()
            or self.leave_type_combo.currentText()
        )

    def accept(self) -> None:  # type: ignore[override]
        try:
            start = parse_assumption_date(self.start_edit.text())
            end = parse_assumption_date(self.end_edit.text())
        except DateInputError:
            QMessageBox.warning(
                self,
                "Invalid leave date",
                "Enter both dates as MM/DD/YYYY, for example 11/24/2023.",
            )
            return
        if end < start:
            QMessageBox.warning(
                self,
                "Invalid date range",
                "End Date cannot be earlier than Start Date.",
            )
            return
        self.start_date = start
        self.end_date = end
        super().accept()


class LoginLauncherDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Login Launcher Setup")
        self.setMinimumWidth(650)

        title = QLabel("Login Launcher Setup")
        title.setStyleSheet("font-size:18px;font-weight:800;color:#f8fafc")

        self.exe_edit = QLineEdit(settings.login_exe_path)
        self.exe_edit.setPlaceholderText(r"C:\Path\To\Application.exe")
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_executable)
        exe_row = QHBoxLayout()
        exe_row.setContentsMargins(0, 0, 0, 0)
        exe_row.addWidget(self.exe_edit, 1)
        exe_row.addWidget(browse_button)

        self.username_edit = QLineEdit(settings.login_username)
        self.username_edit.setPlaceholderText("Username")
        self.password_edit = QLineEdit(settings.login_password)
        self.password_edit.setPlaceholderText("Password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        show_password = QPushButton("Show")
        show_password.setCheckable(True)
        show_password.toggled.connect(
            lambda checked: self.password_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        password_row = QHBoxLayout()
        password_row.setContentsMargins(0, 0, 0, 0)
        password_row.addWidget(self.password_edit, 1)
        password_row.addWidget(show_password)

        self.delay_input = QSpinBox()
        self.delay_input.setRange(0, 30_000)
        self.delay_input.setSingleStep(500)
        self.delay_input.setSuffix(" ms")
        self.delay_input.setValue(settings.login_startup_delay_ms)
        self.delay_input.setToolTip(
            "Time allowed for the login window to open before typing begins."
        )

        self.navigation_delay_input = QSpinBox()
        self.navigation_delay_input.setRange(0, 30_000)
        self.navigation_delay_input.setSingleStep(500)
        self.navigation_delay_input.setSuffix(" ms")
        self.navigation_delay_input.setValue(settings.login_navigation_delay_ms)
        self.navigation_delay_input.setToolTip(
            "Time allowed for login to finish before opening Monitoring or Credits."
        )

        grid = QGridLayout()
        grid.addWidget(QLabel("Application .exe"), 0, 0)
        grid.addLayout(exe_row, 0, 1)
        grid.addWidget(QLabel("Username"), 1, 0)
        grid.addWidget(self.username_edit, 1, 1)
        grid.addWidget(QLabel("Password"), 2, 0)
        grid.addLayout(password_row, 2, 1)
        grid.addWidget(QLabel("Startup delay"), 3, 0)
        grid.addWidget(self.delay_input, 3, 1)
        grid.addWidget(QLabel("After-login delay"), 4, 0)
        grid.addWidget(self.navigation_delay_input, 4, 1)

        note = QLabel(
            "Save these settings once, then use the Leave Monitoring or Leave Credits "
            "buttons in the main header. Login uses USERNAME → Tab → PASSWORD → Enter. "
            "Credentials are stored locally and are never added to MAGCLIP or the clipboard."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "background:#10243a;color:#bae6fd;border:1px solid #1d4f73;"
            "border-radius:8px;padding:9px"
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setObjectName("primarySmallButton")
        buttons.accepted.connect(self._save_settings)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(11)
        layout.addWidget(title)
        layout.addLayout(grid)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _browse_executable(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Choose Login Application",
            self.exe_edit.text(),
            "Windows applications (*.exe)",
        )
        if selected:
            self.exe_edit.setText(selected)

    def _update_settings(self) -> bool:
        try:
            validate_executable(self.exe_edit.text())
            if not self.username_edit.text().strip():
                raise ValueError("Enter the login username.")
            if not self.password_edit.text():
                raise ValueError("Enter the login password.")
        except ValueError as error:
            QMessageBox.warning(self, "Login launcher", str(error))
            return False
        if not self.username_edit.text():
            QMessageBox.warning(self, "Login launcher", "Enter the login username.")
            return False
        if not self.password_edit.text():
            QMessageBox.warning(self, "Login launcher", "Enter the login password.")
            return False

        self.settings.login_exe_path = self.exe_edit.text().strip().strip('"')
        self.settings.login_username = self.username_edit.text()
        self.settings.login_password = self.password_edit.text()
        self.settings.login_startup_delay_ms = self.delay_input.value()
        self.settings.login_navigation_delay_ms = self.navigation_delay_input.value()
        self.settings.login_sequence = DEFAULT_LOGIN_SEQUENCE
        try:
            self.settings.save()
        except OSError as error:
            QMessageBox.critical(
                self,
                "Login launcher",
                f"Could not save the login settings: {error}",
            )
            return False
        return True

    def _save_settings(self) -> None:
        if self._update_settings():
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
        self.special_non_working_holidays: set[date] = set()
        self.special_working_holidays: set[date] = set()
        self.holiday_details: dict[date, tuple[str, ...]] = {}
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
        special_non_working_holidays: set[date],
        special_working_holidays: set[date],
        holiday_details: dict[date, tuple[str, ...]],
        draft_dates: set[date],
    ) -> None:
        self.existing = set(existing)
        self.holidays = set(holidays)
        self.special_non_working_holidays = set(special_non_working_holidays)
        self.special_working_holidays = set(special_working_holidays)
        self.holiday_details = dict(holiday_details)
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
                background, color, border = "#111111", "#ffffff", "#000000"
            elif day in self.draft_dates:
                background, color, border = "#dcfce7", "#166534", "#86efac"
            elif day in self.holidays:
                background, color, border = "#fce8e6", "#b3261e", "#d93025"
            elif day in self.special_non_working_holidays:
                background, color, border = "#fef3c7", "#92400e", "#f59e0b"
            elif day in self.special_working_holidays:
                background, color, border = "#cffafe", "#155e75", "#06b6d4"
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
            button.setToolTip("\n".join(self.holiday_details.get(day, ())))
            button.setStyleSheet(
                "QToolButton{"
                f"background:{background};color:{color};"
                f"border:{border_width} solid {border};"
                f"border-radius:{radius};font-size:{font_size};font-weight:600}}"
                "QToolButton:hover{border:2px solid #06b6d4}"
            )


class LookupMonthCard(QFrame):
    day_clicked = Signal(object)

    def __init__(
        self,
        month: date,
        *,
        holidays: set[date],
        special_non_working: set[date],
        special_working: set[date],
        holiday_details: dict[date, tuple[str, ...]],
        saved_dates: set[date],
        draft_dates: set[date],
        selected_dates: set[date],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("lookupMonthCard")
        self.setStyleSheet(
            "QFrame#lookupMonthCard{background:#ffffff;border:1px solid #cbd5e1;"
            "border-radius:9px}"
        )
        self.day_buttons: dict[date, QToolButton] = {}
        self.base_day_styles: dict[date, str] = {}
        layout = QGridLayout(self)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setHorizontalSpacing(3)
        layout.setVerticalSpacing(3)

        title = QLabel(month.strftime("%B %Y"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "color:#08254b;font-size:15px;font-weight:900;padding:3px"
        )
        layout.addWidget(title, 0, 0, 1, 7)
        for column, weekday in enumerate(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")):
            label = QLabel(weekday)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color:#64748b;font-size:10px;font-weight:800")
            layout.addWidget(label, 1, column)

        first_weekday = (month.weekday() + 1) % 7
        days = (add_months(month, 1) - month).days
        today = date.today()
        for number in range(1, days + 1):
            day = date(month.year, month.month, number)
            position = first_weekday + number - 1
            button = QToolButton()
            button.setText(str(number))
            button.setFixedHeight(25)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip("\n".join(holiday_details.get(day, ())))
            background = "#ffffff"
            color = "#0f172a"
            border = "#e2e8f0"
            font_weight = 700
            if day.weekday() >= 5:
                background = "#f1f5f9"
                color = "#64748b"
            if day in draft_dates:
                background = "#dcfce7"
                color = "#166534"
                border = "#22c55e"
            if day in saved_dates:
                background = "#111827"
                color = "#ffffff"
                border = "#000000"
            if day in special_working:
                background = "#ccfbf1"
                color = "#115e59"
                border = "#14b8a6"
            if day in special_non_working:
                background = "#fef3c7"
                color = "#92400e"
                border = "#f59e0b"
            if day in holidays:
                background = "#fee2e2"
                color = "#b91c1c"
                border = "#ef4444"
            if day == today:
                border = "#2563eb"
                font_weight = 900
            base_style = (
                f"background:{background};color:{color};border:1px solid {border};"
                f"border-radius:5px;font-size:11px;font-weight:{font_weight}"
            )
            self.base_day_styles[day] = base_style
            self.day_buttons[day] = button
            button.clicked.connect(
                lambda _checked=False, selected_day=day: self.day_clicked.emit(
                    selected_day
                )
            )
            layout.addWidget(button, 2 + position // 7, position % 7)
        self.set_selection(selected_dates)

    def set_selection(self, selected_dates: set[date]) -> None:
        for day, button in self.day_buttons.items():
            if day in selected_dates:
                button.setStyleSheet(
                    "background:#fde047;color:#111827;border:2px solid #eab308;"
                    "border-radius:5px;font-size:11px;font-weight:900"
                )
            else:
                button.setStyleSheet(self.base_day_styles[day])


class LookupScrollArea(QScrollArea):
    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if delta:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)


class CalendarLookupPanel(QWidget):
    def __init__(self) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("calendarLookupPanel")
        self.setStyleSheet(
            "QWidget#calendarLookupPanel{background:#0f141b;border-right:2px solid #2563eb}"
        )
        self._loading_months = False
        self._data_revision = 0
        self._rendered_revision = -1
        self._months: list[date] = []
        self._month_widgets: dict[tuple[int, int], LookupMonthCard] = {}
        self.holidays: set[date] = set()
        self.special_non_working: set[date] = set()
        self.special_working: set[date] = set()
        self.holiday_details: dict[date, tuple[str, ...]] = {}
        self.saved_dates: set[date] = set()
        self.draft_dates: set[date] = set()
        self.selection_anchor: date | None = None
        self.selection_end: date | None = None
        self.leave_type = "Vacation Leave"
        self.requested_credit = 1.0

        title = QLabel("CALENDAR LOOKUP")
        title.setStyleSheet("color:#f8fafc;font-size:17px;font-weight:900")
        instruction = QLabel("Ctrl + Shift toggles · click a YEAR tab to jump")
        instruction.setStyleSheet("color:#93c5fd;font-size:11px;font-weight:700")
        self.selection_summary = QLabel("Click a start date, then an end date")
        self.selection_summary.setWordWrap(True)
        self.selection_summary.setStyleSheet(
            "background:#172334;color:#f8fafc;border:1px solid #334155;"
            "border-radius:7px;padding:6px;font-size:11px;font-weight:800"
        )
        clear_selection = QPushButton("Clear")
        clear_selection.setFixedSize(52, 28)
        clear_selection.clicked.connect(self.clear_selection)
        selection_row = QHBoxLayout()
        selection_row.setContentsMargins(0, 0, 0, 0)
        selection_row.setSpacing(4)
        selection_row.addWidget(self.selection_summary, 1)
        selection_row.addWidget(clear_selection)
        legend = QLabel(
            "Red regular · Amber special non-working · Teal special working · "
            "Black saved leave · Green draft"
        )
        legend.setWordWrap(True)
        legend.setStyleSheet("color:#94a3b8;font-size:10px")

        self.content = QWidget()
        self.month_layout = QVBoxLayout(self.content)
        self.month_layout.setContentsMargins(5, 5, 7, 7)
        self.month_layout.setSpacing(7)
        self.month_layout.addStretch(1)
        self.scroll = LookupScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.content)
        self.scroll.verticalScrollBar().valueChanged.connect(self._load_near_edge)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_year_from_scroll)

        year_title = QLabel("YEAR")
        year_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        year_title.setStyleSheet("color:#93c5fd;font-size:10px;font-weight:900")
        self.year_buttons: dict[int, QPushButton] = {}
        year_content = QWidget()
        year_list = QVBoxLayout(year_content)
        year_list.setContentsMargins(2, 2, 2, 2)
        year_list.setSpacing(2)
        for year in range(CALENDAR_MIN_YEAR, CALENDAR_MAX_YEAR + 1):
            button = QPushButton(str(year))
            button.setCheckable(True)
            button.setFixedHeight(27)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{background:#172334;color:#cbd5e1;border:1px solid #334155;"
                "border-radius:6px;padding:0;font-size:10px;font-weight:800}"
                "QPushButton:hover{background:#24344b;border-color:#38bdf8;color:white}"
                "QPushButton:checked{background:#2563eb;border-color:#7dd3fc;color:white}"
            )
            button.clicked.connect(
                lambda _checked=False, selected_year=year: self._jump_to_year(
                    selected_year
                )
            )
            year_list.addWidget(button)
            self.year_buttons[year] = button
        self.year_scroll = LookupScrollArea()
        self.year_scroll.setWidgetResizable(True)
        self.year_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.year_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.year_scroll.setFixedSize(58, 352)
        self.year_scroll.setWidget(year_content)
        year_rail = QVBoxLayout()
        year_rail.setContentsMargins(2, 0, 0, 0)
        year_rail.setSpacing(4)
        year_rail.addWidget(year_title)
        year_rail.addWidget(self.year_scroll)
        year_rail.addStretch(1)
        calendar_row = QHBoxLayout()
        calendar_row.setContentsMargins(0, 0, 0, 0)
        calendar_row.setSpacing(3)
        calendar_row.addWidget(self.scroll, 1)
        calendar_row.addLayout(year_rail)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 9, 7, 8)
        layout.setSpacing(5)
        layout.addWidget(title)
        layout.addWidget(instruction)
        layout.addLayout(selection_row)
        layout.addWidget(legend)
        layout.addLayout(calendar_row, 1)

    def set_calendar_data(
        self,
        *,
        holidays: set[date],
        special_non_working: set[date],
        special_working: set[date],
        holiday_details: dict[date, tuple[str, ...]],
        saved_dates: set[date],
        draft_dates: set[date],
    ) -> None:
        new_holidays = set(holidays)
        new_special_non_working = set(special_non_working)
        new_special_working = set(special_working)
        new_holiday_details = dict(holiday_details)
        new_saved_dates = set(saved_dates)
        new_draft_dates = set(draft_dates)
        if (
            new_holidays == self.holidays
            and new_special_non_working == self.special_non_working
            and new_special_working == self.special_working
            and new_holiday_details == self.holiday_details
            and new_saved_dates == self.saved_dates
            and new_draft_dates == self.draft_dates
        ):
            return
        self.holidays = new_holidays
        self.special_non_working = new_special_non_working
        self.special_working = new_special_working
        self.holiday_details = new_holiday_details
        self.saved_dates = new_saved_dates
        self.draft_dates = new_draft_dates
        self._data_revision += 1
        self._update_selection_summary()

    def set_credit_context(self, leave_type: str, requested_credit: float) -> None:
        self.leave_type = leave_type
        self.requested_credit = requested_credit
        self._update_selection_summary()

    def selected_dates(self) -> set[date]:
        if self.selection_anchor is None:
            return set()
        end = self.selection_end or self.selection_anchor
        return set(inclusive_dates(self.selection_anchor, end))

    def select_day(self, day: date) -> None:
        if self.selection_anchor is None or self.selection_end is not None:
            self.selection_anchor = day
            self.selection_end = None
        else:
            start = min(self.selection_anchor, day)
            self.selection_end = max(self.selection_anchor, day)
            self.selection_anchor = start
        self._refresh_selection_highlight()
        self._update_selection_summary()

    def clear_selection(self) -> None:
        self.selection_anchor = None
        self.selection_end = None
        self._refresh_selection_highlight()
        self._update_selection_summary()

    def _refresh_selection_highlight(self) -> None:
        selected = self.selected_dates()
        for card in self._month_widgets.values():
            card.set_selection(selected)

    def _update_selection_summary(self) -> None:
        selected = self.selected_dates()
        if not selected:
            self.selection_summary.setText("Click a start date, then an end date")
            return
        credits = sum(
            credit_for_day(
                day,
                self.leave_type,
                self.requested_credit,
                self.holidays,
            )
            for day in selected
        )
        start = min(selected)
        end = max(selected)
        range_text = f"{start:%m/%d/%Y}"
        if end != start:
            range_text += f" → {end:%m/%d/%Y}"
        suffix = " · click End" if self.selection_end is None else ""
        self.selection_summary.setText(
            f"{normalize_leave_type(self.leave_type)} · {range_text} · "
            f"{len(selected)} day(s) · {credits:.3f} credit{suffix}"
        )

    def prepare_to_show(self, initial_anchor: date) -> None:
        """Initialize once, or refresh changed data without resetting navigation."""
        if not self._months:
            self.center_on(initial_anchor)
            return
        if self._rendered_revision != self._data_revision:
            anchor = self._visible_month() or initial_anchor.replace(day=1)
            self._rebuild(anchor)
            self.center_on(anchor)

    def center_on(self, anchor: date) -> None:
        anchor = anchor.replace(day=1)
        self._select_year_tab(anchor.year)
        key = (anchor.year, anchor.month)
        if (
            key not in self._month_widgets
            or self._rendered_revision != self._data_revision
        ):
            self._rebuild(anchor)
        widget = self._month_widgets.get(key)
        if widget is not None:
            QTimer.singleShot(
                0,
                lambda target=widget: self.scroll.ensureWidgetVisible(
                    target,
                    0,
                    18,
                ),
            )

    def _select_year_tab(self, year: int) -> None:
        for button_year, button in self.year_buttons.items():
            button.setChecked(button_year == year)
        button = self.year_buttons.get(year)
        if button is not None:
            QTimer.singleShot(
                0,
                lambda target=button: self.year_scroll.ensureWidgetVisible(
                    target,
                    0,
                    8,
                ),
            )

    def _jump_to_year(self, year: int) -> None:
        visible = self._visible_month()
        month = visible.month if visible is not None else 1
        self.center_on(date(year, month, 1))

    def _visible_month(self) -> date | None:
        if not self._months:
            return None
        viewport_top = self.scroll.verticalScrollBar().value()
        for month in self._months:
            widget = self._month_widgets.get((month.year, month.month))
            if widget is not None and widget.geometry().bottom() >= viewport_top:
                return month
        return self._months[-1]

    def _sync_year_from_scroll(self, _value: int) -> None:
        visible = self._visible_month()
        if visible is not None:
            selected = self.year_buttons.get(visible.year)
            if selected is not None and not selected.isChecked():
                self._select_year_tab(visible.year)

    def _rebuild(self, anchor: date) -> None:
        while self.month_layout.count() > 1:
            item = self.month_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._months.clear()
        self._month_widgets.clear()
        self._rendered_revision = self._data_revision
        first = add_months(anchor, -8)
        for offset in range(21):
            self._append_month(add_months(first, offset))

    def _month_card(self, month: date) -> LookupMonthCard:
        card = LookupMonthCard(
            month,
            holidays=self.holidays,
            special_non_working=self.special_non_working,
            special_working=self.special_working,
            holiday_details=self.holiday_details,
            saved_dates=self.saved_dates,
            draft_dates=self.draft_dates,
            selected_dates=self.selected_dates(),
        )
        card.day_clicked.connect(self.select_day)
        return card

    def _append_month(self, month: date) -> None:
        if not CALENDAR_MIN_YEAR <= month.year <= CALENDAR_MAX_YEAR:
            return
        card = self._month_card(month)
        self.month_layout.insertWidget(self.month_layout.count() - 1, card)
        self._months.append(month)
        self._month_widgets[(month.year, month.month)] = card

    def _prepend_months(self, count: int) -> None:
        if not self._months:
            return
        old_maximum = self.scroll.verticalScrollBar().maximum()
        values = [add_months(self._months[0], -offset) for offset in range(count, 0, -1)]
        inserted: list[date] = []
        for month in values:
            if not CALENDAR_MIN_YEAR <= month.year <= CALENDAR_MAX_YEAR:
                continue
            card = self._month_card(month)
            self.month_layout.insertWidget(len(inserted), card)
            inserted.append(month)
            self._month_widgets[(month.year, month.month)] = card
        if not inserted:
            return
        self._months[0:0] = inserted

        def preserve_position() -> None:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.value() + bar.maximum() - old_maximum)

        QTimer.singleShot(0, preserve_position)

    def _load_near_edge(self, value: int) -> None:
        if self._loading_months or not self._months:
            return
        bar = self.scroll.verticalScrollBar()
        self._loading_months = True
        try:
            if value <= 80:
                self._prepend_months(8)
            elif value >= max(0, bar.maximum() - 160):
                first_new = add_months(self._months[-1], 1)
                for offset in range(8):
                    self._append_month(add_months(first_new, offset))
        finally:
            self._loading_months = False


class LeaveCalendarWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Leave Calendar · Python Desktop")
        self.resize(1450, 900)
        self.setMinimumSize(1080, 720)

        self.thread_pool = QThreadPool.globalInstance()
        self.repository: LocalRepository | None = None
        self.employees: list[Employee] = []
        self.employee_by_display: dict[str, Employee] = {}
        self.active_employee: Employee | None = None
        self.profile: EmployeeProfile | None = None
        self.holiday_records: tuple[Holiday, ...] = ()
        self.holidays: set[date] = set()
        self.special_non_working_holidays: set[date] = set()
        self.special_working_holidays: set[date] = set()
        self.holiday_details: dict[date, tuple[str, ...]] = {}
        self.existing: set[date] = set()
        self.existing_records: tuple[LeaveRecord, ...] = ()
        self.draft_entries: list[DraftEntry] = []
        self.draft_employee_id = ""
        self.draft_store = DraftStore()
        self.app_settings = AppSettings.load()
        self._save_in_progress = False
        self.leave_type_options = default_leave_type_options()
        self.shortcut_leave_types: dict[str, LeaveTypeOption] = {}
        self.draft_item_by_id: dict[str, QTreeWidgetItem] = {}
        self.history_dates_by_id: dict[str, set[date]] = {}
        self.history_label_by_id: dict[str, str] = {}
        self.saved_record_id_by_history_id: dict[str, str] = {}
        self._audit_draft_ids: set[str] = set()
        self._audit_calendar_day: date | None = None
        self._audit_draft_entry_id: str | None = None
        self._calendar_geometry: QByteArray | None = None
        self._calendar_was_maximized = False
        self._magclip_window_docked = False
        self._magclip_return_mode = "calendar"
        self.fast_last_start: date | None = None
        self.fast_edit_history_id: str | None = None
        self.locked_leave_code: str | None = None
        self.lookup_modifier_state = ModifierPeekState()
        self.lookup_hotkey_handle: object | None = None

        self._build_ui()
        self.lookup_panel = CalendarLookupPanel()
        self.lookup_hotkey_bridge = LookupHotkeyBridge()
        self.lookup_hotkey_bridge.visibility_requested.connect(
            self.set_calendar_lookup_visible
        )
        self.apply_holiday_records(local_holidays())
        self.update_calendar_data()
        application = QApplication.instance()
        if application:
            application.installEventFilter(self)
        self.install_calendar_lookup_hotkey()
        self._set_connected(False)
        QTimer.singleShot(0, self._start)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)

        self.app_header = QWidget()
        heading = QHBoxLayout(self.app_header)
        heading.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Leave History Recorder")
        title.setStyleSheet("font-size:21px;font-weight:800;color:#f8fafc")
        self.connection_label = QLabel("Not connected")
        self.connection_label.setStyleSheet("padding:6px 10px;border-radius:10px")
        configure_button = QPushButton("Open Local Data")
        configure_button.clicked.connect(self.open_local_data_folder)
        import_button = QPushButton("Paste History Data")
        import_button.clicked.connect(self.import_pasted_history)
        self.mode_button = QPushButton("MAGCLIP Mode")
        self.mode_button.setStyleSheet(
            "QPushButton{background:#1d4ed8;color:white;border-color:#3b82f6;"
            "font-weight:800}QPushButton:hover{background:#2563eb}"
        )
        self.mode_button.clicked.connect(self.toggle_magclip_mode)
        self.credits_button = QPushButton("Credits Mode")
        self.credits_button.setStyleSheet(
            "QPushButton{background:#0e7490;color:white;border-color:#22d3ee;"
            "font-weight:800}QPushButton:hover{background:#0891b2}"
        )
        self.credits_button.clicked.connect(self.toggle_credits_mode)
        logs_button = QPushButton("Open Logs")
        logs_button.clicked.connect(self.open_logs)
        monitoring_button = QPushButton("Leave Monitoring")
        monitoring_button.setToolTip(
            "Open the saved application, log in, and open Leave Monitoring."
        )
        monitoring_button.clicked.connect(
            lambda: self.open_login_destination("monitoring")
        )
        credits_login_button = QPushButton("Leave Credits")
        credits_login_button.setToolTip(
            "Open the saved application, log in, and open Leave Credits."
        )
        credits_login_button.clicked.connect(
            lambda: self.open_login_destination("credits")
        )
        login_setup_button = QPushButton("Login Setup")
        login_setup_button.clicked.connect(self.configure_login_launcher)
        self.holiday_button = QPushButton("PH Holidays · Local ✓")
        self.holiday_button.clicked.connect(self.load_philippine_holidays)
        self.holiday_button.setToolTip(
            "Philippine holidays for 1975–2026 are bundled locally. "
            "No Google Sheets request is needed."
        )
        source_button = QToolButton()
        source_button.setText("Source ↗")
        source_button.setToolTip("Open the matching Timeanddate Philippines calendar.")
        source_button.clicked.connect(self.open_holiday_source)
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.mode_button)
        heading.addWidget(self.credits_button)
        heading.addWidget(self.connection_label)
        heading.addWidget(self.holiday_button)
        heading.addWidget(source_button)
        heading.addWidget(monitoring_button)
        heading.addWidget(credits_login_button)
        heading.addWidget(login_setup_button)
        heading.addWidget(logs_button)
        heading.addWidget(import_button)
        heading.addWidget(configure_button)
        root.addWidget(self.app_header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_calendar_side())
        splitter.addWidget(self._build_draft_side())
        splitter.setSizes([1050, 380])
        self.magclip_page = MagclipModePage()
        self.magclip_page.back_requested.connect(self._return_from_magclip)
        self.credits_page = CreditsPage()
        self.credits_page.back_requested.connect(self.show_calendar_mode)
        self.credits_page.credits_changed.connect(self._refresh_active_employee_locally)
        self.credits_page.magclip_requested.connect(self.show_credits_magclip_mode)
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(splitter)
        self.mode_stack.addWidget(self.magclip_page)
        self.mode_stack.addWidget(self.credits_page)
        root.addWidget(self.mode_stack, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Opening local database…")

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
        self.assumption_edit.setPlaceholderText("10 1 19")
        self.assumption_edit.setToolTip(
            "Enter MONTH DAY YEAR, such as 10 1 19. YYYY-MM-DD also works."
        )
        self.assumption_edit.returnPressed.connect(self.save_assumption_date)
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

        self.fast_group = QGroupBox(
            "Fast Encode · use / between month, start day, and optional end day"
        )
        fast_layout = QHBoxLayout(self.fast_group)
        self.fast_year_spin = QSpinBox()
        self.fast_year_spin.setRange(CALENDAR_MIN_YEAR, CALENDAR_MAX_YEAR)
        self.fast_year_spin.setValue(date.today().year)
        self.fast_year_spin.setKeyboardTracking(False)
        self.fast_year_spin.setMinimumWidth(92)
        self.fast_year_spin.setToolTip(
            "Select the starting year. A backward month automatically advances the year."
        )
        self.fast_year_spin.valueChanged.connect(self.fast_year_changed)
        self.fast_range_edit = QLineEdit()
        self.fast_range_edit.setPlaceholderText("9/1 or 9/1/3")
        self.fast_range_edit.setMaximumWidth(190)
        self.fast_range_edit.setToolTip(
            "Use 9/1 for one day or 9/1/3 for September 1 through 3."
        )
        self.fast_range_edit.returnPressed.connect(self.commit_fast_entry)
        self.fast_cancel_shortcut = QShortcut(
            QKeySequence("Escape"),
            self.fast_range_edit,
        )
        self.fast_cancel_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.fast_cancel_shortcut.activated.connect(self.cancel_fast_date_edit)
        lock_label = QLabel("LOCK")
        lock_label.setStyleSheet("color:#94a3b8;font-weight:900")
        self.leave_lock_buttons: dict[str, QPushButton] = {}
        for code in ("VL", "SL", "WL", "FL", "SPL"):
            lock_button = QPushButton(code)
            lock_button.setCheckable(True)
            lock_button.setMinimumWidth(42 if len(code) <= 2 else 50)
            lock_button.setToolTip(
                f"Lock Fast Encode and calendar selections to {code}. "
                "Click the active button again to unlock."
            )
            lock_button.toggled.connect(
                lambda enabled, leave_code=code: self.update_leave_lock(
                    leave_code,
                    enabled,
                )
            )
            self.leave_lock_buttons[code] = lock_button
        self.fast_add_button = QPushButton("Add Fast Entry")
        self.fast_add_button.clicked.connect(self.commit_fast_entry)
        self.fast_help = QLabel("9/1 · one day    9/1/3 · range")
        self.fast_help.setStyleSheet("color:#94a3b8;font-weight:700")
        fast_layout.addWidget(QLabel("WORKING YEAR"))
        fast_layout.addWidget(self.fast_year_spin)
        fast_layout.addWidget(self.fast_range_edit)
        fast_layout.addWidget(lock_label)
        for lock_button in self.leave_lock_buttons.values():
            fast_layout.addWidget(lock_button)
        fast_layout.addWidget(self.fast_add_button)
        fast_layout.addStretch(1)
        fast_layout.addWidget(self.fast_help)
        layout.addWidget(self.fast_group)

        self.entry_warning_label = QLabel()
        self.entry_warning_label.setWordWrap(True)
        self.entry_warning_label.setStyleSheet(
            "background:#422006;color:#fde68a;border:1px solid #f59e0b;"
            "border-radius:7px;padding:6px 10px;font-weight:700"
        )
        self.entry_warning_label.hide()
        self.entry_warning_timer = QTimer(self)
        self.entry_warning_timer.setSingleShot(True)
        self.entry_warning_timer.timeout.connect(self.entry_warning_label.hide)
        layout.addWidget(self.entry_warning_label)

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
            "Black: saved leave   ·   Gold outline: audit match   ·   "
            "Red: regular holiday   ·   Amber: special non-working   ·   "
            "Teal: special working   ·   Gray: weekend"
        )
        legend.setStyleSheet("color:#667085;font-size:11px")
        legend.setWordWrap(True)
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
        title = QLabel("Leave History")
        title.setStyleSheet("font-size:17px;font-weight:800;color:#f8fafc")
        self.draft_meta = QLabel("0 saved · 0 draft · 0.000 credits")
        self.draft_meta.setStyleSheet("color:#667085")
        self.audit_hint = QLabel(
            "AUDIT · Click Type for dropdown · Click Dates for fast edit"
        )
        self.audit_hint.setStyleSheet(
            "background:#102a33;color:#67e8f9;border:1px solid #155e75;"
            "border-radius:7px;padding:5px 8px;font-size:10px;font-weight:700"
        )
        layout.addWidget(title)
        layout.addWidget(self.draft_meta)
        layout.addWidget(self.audit_hint)

        self.draft_tree = QTreeWidget()
        self.draft_tree.setHeaderLabels(
            ["Status", "Type", "Dates", "Days", "Credit", ""]
        )
        draft_header = self.draft_tree.header()
        draft_header.setStretchLastSection(False)
        draft_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        draft_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        draft_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        draft_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        draft_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        draft_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        draft_header.resizeSection(0, 48)
        draft_header.resizeSection(1, 48)
        draft_header.resizeSection(3, 38)
        draft_header.resizeSection(4, 52)
        draft_header.resizeSection(5, 28)
        self.draft_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.draft_tree.setIndentation(0)
        self.draft_tree.setMouseTracking(True)
        self.draft_tree.itemEntered.connect(self.audit_draft_item)
        self.draft_tree.itemClicked.connect(self.quick_edit_leave_history_item)
        self.draft_tree.itemDoubleClicked.connect(self.edit_leave_history_item)
        self.draft_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.draft_tree.customContextMenuRequested.connect(
            self.open_leave_history_menu
        )
        layout.addWidget(self.draft_tree, 1)

        actions = QHBoxLayout()
        remove_button = QPushButton("Remove Draft")
        remove_button.clicked.connect(self.remove_draft_entry)
        clear_button = QPushButton("Clear Draft")
        clear_button.clicked.connect(self.clear_draft)
        copy_button = QPushButton("Copy Draft TSV")
        copy_button.clicked.connect(self.copy_draft_tsv)
        actions.addWidget(remove_button)
        actions.addWidget(clear_button)
        actions.addWidget(copy_button)
        layout.addLayout(actions)

        self.save_local_button = QPushButton("Save Locally")
        self.save_local_button.clicked.connect(
            lambda: self.save_draft(open_magclip=False)
        )
        self.save_send_button = QPushButton("Save + Open MAGCLIP Mode")
        self.save_send_button.setStyleSheet(
            "QPushButton{background:#159455;color:white;padding:12px;border:0;"
            "border-radius:7px;font-weight:800}QPushButton:hover{background:#117a45}"
        )
        self.save_send_button.clicked.connect(
            lambda: self.save_draft(open_magclip=True)
        )
        layout.addWidget(self.save_local_button)
        layout.addWidget(self.save_send_button)

        integration_note = QLabel(
            "MAGCLIP is built into this app. Every saved leave-history row is one "
            "clip with eight rounds: editable NAME, TYPE, START, END, VL, SL, "
            "LWOP, and STATUS."
        )
        integration_note.setWordWrap(True)
        integration_note.setStyleSheet(
            "background:#ecfdf3;color:#067647;padding:10px;border-radius:7px;font-size:11px"
        )
        layout.addWidget(integration_note)
        return panel

    def _start(self) -> None:
        self.connect_repository()

    def open_local_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_data_dir())))

    def import_pasted_history(self) -> None:
        if self.repository is None:
            self.show_error("The local database is unavailable.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Paste Leave History Data")
        dialog.resize(850, 500)
        layout = QVBoxLayout(dialog)
        instructions = QLabel(
            "Paste rows copied from Excel or Google Sheets. Header is optional.\n"
            "Order: NAME | TYPE | START | END | VL | SL | LWOP | STATUS\n"
            "For seven-column rows without NAME, the currently selected employee is used."
        )
        instructions.setWordWrap(True)
        editor = QPlainTextEdit()
        editor.setPlaceholderText(
            "Chiao\tVacation Leave\t7/14/2026\t7/16/2026\t3\t0\t0\tA"
        )
        clipboard_text = QApplication.clipboard().text()
        if "\t" in clipboard_text or "\n" in clipboard_text:
            editor.setPlainText(clipboard_text)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setText("Import Rows")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(instructions)
        layout.addWidget(editor, 1)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            records = parse_history_text(
                editor.toPlainText(),
                self.active_employee.name if self.active_employee else "",
            )
            imported, skipped = self.repository.import_leave_records(records)
        except (HistoryImportError, ValueError, RuntimeError) as error:
            self.show_error(str(error))
            return

        selected_id = self.active_employee.employee_id if self.active_employee else ""
        self.employees = self.repository.employees(force=True)
        imported_employee = next(
            (
                employee
                for employee in self.employees
                if employee.name.casefold() == records[0].name.casefold()
            ),
            None,
        )
        employee = (
            next(
                (item for item in self.employees if item.employee_id == selected_id),
                None,
            )
            or imported_employee
        )
        self.populate_employees(employee.employee_id if employee else "")
        if employee:
            self.activate_employee(employee)
        QMessageBox.information(
            self,
            "History import complete",
            f"Imported {imported} row(s). Skipped {skipped} exact duplicate(s).",
        )

    def connect_repository(self) -> None:
        self.statusBar().showMessage("Opening local SQLite database…")
        self._set_connected(False, "Opening local data…")

        def job() -> tuple[
            LocalRepository,
            list[Employee],
            list[LeaveTypeOption],
        ]:
            repository = LocalRepository()
            repository.connect()
            return (
                repository,
                repository.employees(force=True),
                repository.leave_types(force=True),
            )

        self.run_job(job, self._connected)

    def _connected(self, result: object) -> None:
        repository, employees, leave_types = result  # type: ignore[misc]
        self.repository = repository
        self.employees = employees
        self.apply_leave_type_options(leave_types)
        self.populate_employees()
        self._set_connected(True, repository.spreadsheet_title)
        shortcut_count = len(self.shortcut_leave_types)
        self.statusBar().showMessage(
            f"{repository.spreadsheet_title} · "
            f"{shortcut_count} local shortcut(s) · PH holidays local",
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
            self.shortcut_legend.setText("SHORTCUTS  No local shortcuts configured")
            self.shortcut_legend.setToolTip(
                "Local shortcut configuration is unavailable."
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
            self.show_error("The local database is unavailable.")
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
        self.existing = set()
        self.existing_records = ()
        self.render_draft()
        self.populate_employees(employee.employee_id)
        self.assumption_edit.setText(
            employee.assumption_date.isoformat() if employee.assumption_date else ""
        )
        self.calendar.clear_selection()
        self.statusBar().showMessage(f"Loading {employee.name}…")

        def job() -> tuple[
            Employee,
            EmployeeProfile,
            set[date],
            tuple[LeaveRecord, ...],
        ]:
            assert self.repository is not None
            refreshed = self.repository.employee_by_id(employee.employee_id, force=True) or employee
            records = tuple(self.repository.leave_records(refreshed.employee_id))
            profile = self.repository.employee_profile(
                refreshed,
                force=True,
                records=records,
            )
            return (
                refreshed,
                profile,
                {
                    day
                    for record in records
                    for day in record.calendar_dates
                },
                records,
            )

        self.run_job(job, self._employee_loaded)

    def _employee_loaded(self, result: object) -> None:
        employee, profile, existing, records = result  # type: ignore[misc]
        self.active_employee = employee
        self.profile = profile
        self.existing = existing
        self.existing_records = records
        self.assumption_edit.setText(
            employee.assumption_date.isoformat() if employee.assumption_date else ""
        )
        self.update_profile_metrics()
        self.render_draft()
        self.magclip_page.set_history(employee, records)
        self.credits_page.set_context(self.repository, employee)
        self.statusBar().showMessage(f"Ready: {employee.name}", 5000)

    def save_assumption_date(self) -> None:
        if not self.active_employee or not self.repository:
            self.show_error("Select or manually enter an employee first.")
            return
        try:
            assumption_date = parse_assumption_date(self.assumption_edit.text())
        except DateInputError as error:
            self.show_error(str(error))
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
        self.assumption_edit.setText(
            employee.assumption_date.isoformat() if employee.assumption_date else ""
        )
        self.credits_page.set_context(self.repository, employee)
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
            special_non_working_holidays=self.special_non_working_holidays,
            special_working_holidays=self.special_working_holidays,
            holiday_details=self.holiday_details,
            draft_dates=draft_dates,
        )
        if hasattr(self, "lookup_panel"):
            self.lookup_panel.set_calendar_data(
                holidays=self.holidays,
                special_non_working=self.special_non_working_holidays,
                special_working=self.special_working_holidays,
                holiday_details=self.holiday_details,
                saved_dates=self.existing,
                draft_dates=draft_dates,
            )
        self.update_selected_summary()

    def apply_holiday_records(self, holidays: tuple[Holiday, ...]) -> None:
        self.holiday_records = tuple(holidays)
        self.holidays = {item.day for item in holidays if item.is_regular}
        self.special_non_working_holidays = {
            item.day for item in holidays if item.is_special_non_working
        }
        self.special_working_holidays = {
            item.day for item in holidays if item.is_special_working
        }
        details: dict[date, list[str]] = {}
        for item in holidays:
            details.setdefault(item.day, []).append(
                f"{item.name} · {item.holiday_type}"
            )
        self.holiday_details = {
            day: tuple(sorted(labels)) for day, labels in details.items()
        }

    def displayed_year(self) -> int:
        try:
            year = int(self.jump_year_edit.text())
        except ValueError:
            year = self.calendar.start_month.year
        return min(max(year, CALENDAR_MIN_YEAR), CALENDAR_MAX_YEAR)

    def open_holiday_source(self) -> None:
        QDesktopServices.openUrl(QUrl(timeanddate_calendar_url(self.displayed_year())))

    def load_philippine_holidays(self) -> None:
        year = self.displayed_year()
        rows = holidays_for_year(year)
        if not rows:
            QMessageBox.information(
                self,
                "Philippine holidays",
                "Reviewed Philippine nationwide holidays are "
                f"available locally from 1975 through 2026. No data exists for {year}.",
            )
            self.open_holiday_source()
            return
        self.update_calendar_data()
        message = f"{len(rows)} Philippine holidays for {year} are active locally."
        self.statusBar().showMessage(message, 8000)
        QMessageBox.information(self, "Philippine holidays", message)

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
        leave_type = self.current_leave_type()
        requested_credit = float(self.credit_combo.currentData() or 1)
        if hasattr(self, "lookup_panel"):
            self.lookup_panel.set_credit_context(leave_type, requested_credit)
        if self.calendar.range_anchor is not None:
            self.selected_label.setText(
                f"Start: {self.calendar.range_anchor:%b %d, %Y} · click the end date"
            )
            return
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

        if self.locked_leave_code:
            if self.select_leave_type_by_code(self.locked_leave_code):
                self.add_to_draft()
                return
            self.statusBar().showMessage(
                f"{self.locked_leave_code} is not available; choose a leave type.",
                6000,
            )

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
        mone_allocation: tuple[float, float] | None = None
        if is_mone_charge(dialog.selected_option.name):
            requested_credit = float(self.credit_combo.currentData() or 1)
            chargeable_total = sum(
                credit_for_day(
                    day,
                    dialog.selected_option.name,
                    requested_credit,
                    self.holidays,
                )
                for day in self.calendar.selected
            )
            allocation_dialog = MoneAllocationDialog(chargeable_total, self)
            if allocation_dialog.exec() != QDialog.DialogCode.Accepted:
                self.statusBar().showMessage(
                    "MONE allocation canceled; the dates remain selected.",
                    5000,
                )
                return
            mone_allocation = allocation_dialog.allocation
        self.add_to_draft(mone_allocation=mone_allocation)

    def fast_year_changed(self, year: int) -> None:
        self.fast_last_start = None
        self.fast_range_edit.clear()
        self.jump_year_edit.setText(str(year))
        self.jump_to_month()
        self.statusBar().showMessage(
            f"Fast Encode working year set to {year}.",
            4000,
        )

    def _set_fast_year_automatically(self, year: int) -> None:
        self.fast_year_spin.blockSignals(True)
        self.fast_year_spin.setValue(year)
        self.fast_year_spin.blockSignals(False)

    def show_fast_date(self, target: date) -> None:
        self.jump_year_edit.setText(str(target.year))
        month_index = self.jump_month_combo.findData(target.month)
        if month_index >= 0:
            self.jump_month_combo.setCurrentIndex(month_index)
        self.calendar.set_view(target.replace(day=1), self.calendar.month_count)
        self.sync_calendar_jump_controls()
        self.update_calendar_data()

    def commit_fast_entry(self) -> None:
        editing_history_id = self.fast_edit_history_id
        try:
            start, end = parse_fast_range(
                self.fast_range_edit.text(),
                self.fast_year_spin.value(),
                None if editing_history_id else self.fast_last_start,
            )
        except FastDateError as error:
            self.show_error(str(error))
            self.fast_range_edit.setFocus()
            return
        if not CALENDAR_MIN_YEAR <= start.year <= CALENDAR_MAX_YEAR:
            self.show_error(
                f"The date must be from {CALENDAR_MIN_YEAR} through {CALENDAR_MAX_YEAR}."
            )
            return
        if editing_history_id:
            if self._apply_fast_date_edit(editing_history_id, start, end):
                self.fast_last_start = start
                self._set_fast_year_automatically(start.year)
                self._reset_fast_entry_mode()
                self.fast_range_edit.setFocus()
            return
        selected = set(inclusive_dates(start, end))
        self.show_fast_date(start)
        self.calendar.selected = selected
        self.calendar.apply_styles()
        self.calendar.selected_changed.emit()
        draft_count = len(self.draft_entries)
        self.open_leave_type_picker()
        if len(self.draft_entries) == draft_count:
            return
        self.fast_last_start = start
        self._set_fast_year_automatically(start.year)
        self.fast_range_edit.clear()
        self.fast_range_edit.setFocus()
        self.statusBar().showMessage(
            f"Added {start:%m-%d-%Y} → {end:%m-%d-%Y}.",
            5000,
        )

    def _apply_fast_date_edit(
        self,
        history_id: str,
        start: date,
        end: date,
    ) -> bool:
        draft_entry = next(
            (entry for entry in self.draft_entries if entry.entry_id == history_id),
            None,
        )
        if draft_entry is not None:
            self._replace_draft_leave(
                draft_entry,
                draft_entry.leave_type,
                start,
                end,
            )
            self.show_fast_date(start)
            self.statusBar().showMessage(
                f"Draft dates updated to {start:%m/%d/%Y} → {end:%m/%d/%Y}.",
                6000,
            )
            return True

        record_id = self.saved_record_id_by_history_id.get(history_id)
        saved_record = next(
            (
                record
                for record in self.existing_records
                if record.record_id == record_id
            ),
            None,
        )
        if saved_record is None:
            self.show_error("That leave-history entry could not be found.")
            return False
        if not self._save_leave_edit(
            saved_record,
            saved_record.leave_type,
            start,
            end,
        ):
            return False
        self.show_fast_date(start)
        return True

    def _reset_fast_entry_mode(self) -> None:
        self.fast_edit_history_id = None
        self.fast_group.setTitle(
            "Fast Encode · use / between month, start day, and optional end day"
        )
        self.fast_range_edit.clear()
        self.fast_range_edit.setPlaceholderText("9/1 or 9/1/3")
        self.fast_add_button.setText("Add Fast Entry")
        self.fast_help.setText("9/1 · one day    9/1/3 · range")

    def cancel_fast_date_edit(self) -> None:
        was_editing = self.fast_edit_history_id is not None
        self._reset_fast_entry_mode()
        if was_editing:
            self.statusBar().showMessage("Date edit canceled.", 4000)

    def select_leave_type_by_code(self, code: str) -> bool:
        for index in range(self.leave_type_combo.count()):
            item_leave_type = str(self.leave_type_combo.itemData(index))
            if self.leave_code(item_leave_type).casefold() == code.casefold():
                self.leave_type_combo.setCurrentIndex(index)
                return True
        return False

    def update_leave_lock(self, code: str, enabled: bool) -> None:
        if enabled:
            self.locked_leave_code = code
            for other_code, button in self.leave_lock_buttons.items():
                if other_code != code and button.isChecked():
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
            self.select_leave_type_by_code(code)
            self.statusBar().showMessage(
                f"{code} Lock active · completed ranges are added as {code}.",
                5000,
            )
        elif self.locked_leave_code == code:
            self.locked_leave_code = None
            self.statusBar().showMessage(
                "Leave-type lock off · completed ranges will ask for a leave type.",
                5000,
            )
        for button_code, button in self.leave_lock_buttons.items():
            if self.locked_leave_code == button_code:
                button.setStyleSheet(
                    "QPushButton{background:#16a34a;color:white;"
                    "border:2px solid #86efac;font-weight:900}"
                    "QPushButton:hover{background:#15803d}"
                )
            else:
                button.setStyleSheet("")

    def add_to_draft(
        self,
        mone_allocation: tuple[float, float] | None = None,
    ) -> None:
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

        if is_vl_charge(leave_type) or is_sl_charge(leave_type) or is_mone_charge(leave_type):
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
                vl_allocation=(mone_allocation[0] if mone_allocation else None),
                sl_allocation=(mone_allocation[1] if mone_allocation else None),
            )
        )
        self.draft_employee_id = self.active_employee.employee_id
        self.remarks_edit.clear()
        self.calendar.clear_selection()
        self.render_draft()
        if warnings:
            warning_text = " · ".join(warnings)
            LOGGER.warning("Historical entry warning: %s", warning_text)
            self.entry_warning_label.setText("⚠ " + warning_text)
            self.entry_warning_label.show()
            self.entry_warning_timer.start(12000)
            self.statusBar().showMessage(
                "Leave added to draft with a warning.",
                12000,
            )
        else:
            self.statusBar().showMessage("Leave added to draft.", 4000)

    def render_draft(self) -> None:
        self.clear_audit_link()
        self.draft_tree.clear()
        self.draft_item_by_id = {}
        self.history_dates_by_id = {}
        self.history_label_by_id = {}
        self.saved_record_id_by_history_id = {}
        draft_total = 0.0
        for entry in self.draft_entries:
            draft_total += entry.total_credits
            dates = entry.first_day.strftime("%m/%d/%Y")
            if entry.last_day != entry.first_day:
                dates += " → " + entry.last_day.strftime("%m/%d/%Y")
            item = QTreeWidgetItem(
                [
                    "Draft",
                    self.leave_code(entry.leave_type),
                    dates,
                    str(len(entry.days)),
                    f"{entry.total_credits:.3f}",
                    "",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, entry.entry_id)
            item.setToolTip(1, entry.remarks)
            self.draft_tree.addTopLevelItem(item)
            self.draft_item_by_id[entry.entry_id] = item
            self.history_dates_by_id[entry.entry_id] = {
                leave_day.day for leave_day in entry.days
            }
            self.history_label_by_id[entry.entry_id] = (
                f"Draft · {self.leave_code(entry.leave_type)}"
            )
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
            self.draft_tree.setItemWidget(item, 5, remove_button)

        saved_total = 0.0
        for index, record in enumerate(
            sorted(
                self.existing_records,
                key=lambda value: (value.start, value.end, value.record_id),
                reverse=True,
            )
        ):
            saved_total += record.total_credits
            dates = record.start.strftime("%m/%d/%Y")
            if record.end != record.start:
                dates += " → " + record.end.strftime("%m/%d/%Y")
            history_id = f"saved:{record.record_id or index}:{index}"
            item = QTreeWidgetItem(
                [
                    "Saved",
                    self.leave_code(record.leave_type),
                    dates,
                    str(record.day_count),
                    f"{record.total_credits:.3f}",
                    "",
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, history_id)
            item.setToolTip(1, record.remarks)
            self.draft_tree.addTopLevelItem(item)
            self.draft_item_by_id[history_id] = item
            self.history_dates_by_id[history_id] = set(record.calendar_dates)
            self.history_label_by_id[history_id] = (
                f"Saved · {self.leave_code(record.leave_type)}"
            )
            self.saved_record_id_by_history_id[history_id] = record.record_id

        total = saved_total + draft_total
        saved_count = len(self.existing_records)
        draft_count = len(self.draft_entries)
        self.draft_meta.setText(
            f"{saved_count} saved · {draft_count} draft · "
            f"{total:.3f} credits"
        )
        if self.draft_entries and self.draft_employee_id:
            self.draft_store.save(self.draft_employee_id, self.draft_entries)
        elif not self.draft_entries:
            self.draft_store.clear()
        if hasattr(self, "calendar"):
            self.update_calendar_data()
        self._update_magclip_action_button()

    def _update_magclip_action_button(self) -> None:
        if not hasattr(self, "save_send_button") or self._save_in_progress:
            return
        if not self.draft_entries and self.existing_records:
            self.save_send_button.setText("Open MAGCLIP Mode")
        else:
            self.save_send_button.setText("Save + Open MAGCLIP Mode")

    def audit_draft_item(self, item: QTreeWidgetItem, _column: int) -> None:
        entry_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        dates = self.history_dates_by_id.get(entry_id)
        if not dates:
            self.clear_draft_hover_audit()
            return

        self._clear_draft_row_highlights()
        self._audit_calendar_day = None
        self._audit_draft_entry_id = entry_id
        if dates and not self.calendar.dates_are_visible(dates):
            self.calendar.set_view(min(dates).replace(day=1), self.calendar.month_count)
            self.sync_calendar_jump_controls()
            self.update_calendar_data()
        self.calendar.set_audit_dates(dates)
        self.audit_hint.setText(
            f"AUDIT · {self.history_label_by_id.get(entry_id, 'Leave')} · "
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
            entry_id
            for entry_id, dates in self.history_dates_by_id.items()
            if day in dates
        ]
        self._set_draft_row_highlights(set(matches))
        if matches:
            first_item = self.draft_item_by_id.get(matches[0])
            if first_item is not None:
                self.draft_tree.scrollToItem(first_item)
            count = len(matches)
            self.audit_hint.setText(
                f"AUDIT · {day:%b %d, %Y} · {count} matching leave "
                f"entr{'y' if count == 1 else 'ies'}"
            )
        else:
            self.audit_hint.setText(
                f"AUDIT · {day:%b %d, %Y} · no matching leave entry"
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
            self.audit_hint.setText(
                "AUDIT · Click Type for dropdown · Click Dates for fast edit"
            )

    def remove_draft_entry(self) -> None:
        selected = self.draft_tree.currentItem()
        if not selected:
            return
        entry_id = str(selected.data(0, Qt.ItemDataRole.UserRole))
        if not any(entry.entry_id == entry_id for entry in self.draft_entries):
            self.statusBar().showMessage(
                "Saved leave records are read-only; only drafts can be removed.",
                5000,
            )
            return
        self.remove_draft_entry_by_id(entry_id)

    def open_leave_history_menu(self, position: QPoint) -> None:
        item = self.draft_tree.itemAt(position)
        if item is None:
            return
        history_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        menu = QMenu(self)
        if any(entry.entry_id == history_id for entry in self.draft_entries):
            edit_action = menu.addAction("Edit Leave Entry…")
            remove_action = menu.addAction("Remove Draft Entry")
            chosen = menu.exec(self.draft_tree.viewport().mapToGlobal(position))
            if chosen is edit_action:
                self.edit_draft_leave(history_id)
            elif chosen is remove_action:
                self.remove_draft_entry_by_id(history_id)
            return

        record_id = self.saved_record_id_by_history_id.get(history_id)
        if not record_id:
            return
        edit_action = menu.addAction("Edit Leave Entry…")
        delete_action = menu.addAction("Delete Saved Leave…")
        chosen = menu.exec(self.draft_tree.viewport().mapToGlobal(position))
        if chosen is edit_action:
            self.edit_saved_leave(record_id)
        elif chosen is delete_action:
            self.delete_saved_leave(record_id)

    def edit_leave_history_item(
        self,
        item: QTreeWidgetItem,
        column: int,
    ) -> None:
        if column in (1, 2):
            return
        history_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        if any(entry.entry_id == history_id for entry in self.draft_entries):
            self.edit_draft_leave(history_id)
            return
        record_id = self.saved_record_id_by_history_id.get(history_id)
        if record_id:
            self.edit_saved_leave(record_id)

    def quick_edit_leave_date(
        self,
        item: QTreeWidgetItem,
        column: int,
    ) -> None:
        if column != 2:
            return
        history_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        draft_entry = next(
            (entry for entry in self.draft_entries if entry.entry_id == history_id),
            None,
        )
        record_id = self.saved_record_id_by_history_id.get(history_id)
        saved_record = next(
            (
                record
                for record in self.existing_records
                if record.record_id == record_id
            ),
            None,
        )
        leave_type = (
            draft_entry.leave_type
            if draft_entry is not None
            else saved_record.leave_type if saved_record is not None else ""
        )
        start = (
            draft_entry.first_day
            if draft_entry is not None
            else saved_record.start if saved_record is not None else None
        )
        end = (
            draft_entry.last_day
            if draft_entry is not None
            else saved_record.end if saved_record is not None else None
        )
        if not leave_type or start is None or end is None:
            return

        self.fast_edit_history_id = history_id
        self._set_fast_year_automatically(start.year)
        self.fast_group.setTitle(
            f"Fast Edit Dates · {self.leave_code(leave_type)} · "
            f"{start:%m/%d/%Y} → {end:%m/%d/%Y}"
        )
        self.fast_range_edit.clear()
        self.fast_range_edit.setPlaceholderText("Replacement: 9/1 or 9/1/3")
        self.fast_add_button.setText("Update Dates")
        self.fast_help.setText("Enter to update · Esc to cancel")
        self.fast_range_edit.setFocus()
        self.statusBar().showMessage(
            "Fast date edit active. Enter the replacement using / and press Enter.",
            7000,
        )

    def quick_edit_leave_history_item(
        self,
        item: QTreeWidgetItem,
        column: int,
    ) -> None:
        """Dispatch one history click without reusing an item after a row rebuild."""
        if column == 1:
            self.quick_edit_leave_type(item, column)
        elif column == 2:
            self.quick_edit_leave_date(item, column)

    def quick_edit_leave_type(
        self,
        item: QTreeWidgetItem,
        column: int,
    ) -> None:
        if column != 1:
            return
        history_id = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        draft_entry = next(
            (entry for entry in self.draft_entries if entry.entry_id == history_id),
            None,
        )
        record_id = self.saved_record_id_by_history_id.get(history_id)
        saved_record = next(
            (
                record
                for record in self.existing_records
                if record.record_id == record_id
            ),
            None,
        )
        current_type = (
            draft_entry.leave_type
            if draft_entry is not None
            else saved_record.leave_type if saved_record is not None else ""
        )
        if not current_type:
            return

        menu = QMenu(self)
        action_types: dict[object, str] = {}
        current_normalized = normalize_leave_type(current_type)
        for option in self.leave_type_options:
            label = f"{option.code}  ·  {option.display_name}"
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(normalize_leave_type(option.name) == current_normalized)
            action_types[action] = option.name
        row_rect = self.draft_tree.visualItemRect(item)
        type_left = self.draft_tree.columnViewportPosition(1)
        menu_position = self.draft_tree.viewport().mapToGlobal(
            QPoint(type_left, row_rect.bottom() + 1)
        )
        chosen = menu.exec(menu_position)
        selected_type = action_types.get(chosen)
        if not selected_type or normalize_leave_type(selected_type) == current_normalized:
            return
        if draft_entry is not None:
            self._replace_draft_leave(
                draft_entry,
                selected_type,
                draft_entry.first_day,
                draft_entry.last_day,
            )
            self.statusBar().showMessage(
                "Draft leave type updated and credit recalculated.",
                5000,
            )
        elif saved_record is not None:
            self._save_leave_edit(
                saved_record,
                selected_type,
                saved_record.start,
                saved_record.end,
            )

    def edit_draft_leave(self, entry_id: str) -> None:
        entry = next(
            (item for item in self.draft_entries if item.entry_id == entry_id),
            None,
        )
        if entry is None:
            self.show_error("That draft leave entry could not be found.")
            return
        dialog = EditLeaveDialog(
            self.leave_type_options,
            entry.leave_type,
            entry.first_day,
            entry.last_day,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._replace_draft_leave(
            entry,
            dialog.leave_type,
            dialog.start_date,
            dialog.end_date,
        )
        self.statusBar().showMessage(
            "Draft leave updated; Days and Credit were recalculated.",
            6000,
        )

    def _replace_draft_leave(
        self,
        entry: DraftEntry,
        leave_type: str,
        start: date,
        end: date,
    ) -> None:
        positive_credits = [item.credits for item in entry.days if item.credits > 0]
        requested_credit = (
            max(positive_credits)
            if positive_credits
            else float(self.credit_combo.currentData() or 1.0)
        )
        days = tuple(
            LeaveDay(
                day,
                credit_for_day(
                    day,
                    leave_type,
                    requested_credit,
                    self.holidays,
                ),
            )
            for day in inclusive_dates(start, end)
        )
        vl_allocation: float | None = None
        sl_allocation: float | None = None
        if is_mone_charge(leave_type):
            total = round(sum(item.credits for item in days), 3)
            old_vl = (
                entry.vl_allocation
                if is_mone_charge(entry.leave_type) and entry.vl_allocation is not None
                else total
            )
            vl_allocation = min(total, max(0.0, float(old_vl)))
            sl_allocation = round(total - vl_allocation, 3)
        replacement = DraftEntry(
            entry_id=entry.entry_id,
            leave_type=leave_type,
            days=days,
            remarks=entry.remarks,
            vl_allocation=vl_allocation,
            sl_allocation=sl_allocation,
        )
        self.draft_entries = [
            replacement if item.entry_id == entry.entry_id else item
            for item in self.draft_entries
        ]
        self.render_draft()

    def edit_saved_leave(self, record_id: str) -> None:
        if not self.repository or not self.active_employee:
            self.show_error("The local database is unavailable.")
            return
        record = next(
            (item for item in self.existing_records if item.record_id == record_id),
            None,
        )
        if record is None:
            self.show_error("That saved leave record could not be found.")
            return
        dialog = EditLeaveDialog(
            self.leave_type_options,
            record.leave_type,
            record.start,
            record.end,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_leave_edit(
            record,
            dialog.leave_type,
            dialog.start_date,
            dialog.end_date,
        )

    def _save_leave_edit(
        self,
        record: LeaveRecord,
        leave_type: str,
        start: date,
        end: date,
    ) -> bool:
        if not self.repository or not self.active_employee:
            self.show_error("The local database is unavailable.")
            return False
        try:
            updated = self.repository.update_leave_record(
                record.record_id,
                self.active_employee.employee_id,
                leave_type,
                start,
                end,
            )
            if not updated:
                raise RuntimeError("The saved leave record no longer exists.")
            self._refresh_active_employee_locally()
        except Exception as error:
            LOGGER.exception("Could not edit saved leave")
            self.show_error(str(error))
            return False
        self.statusBar().showMessage(
            "Saved leave updated; calendar markers and credits were recalculated.",
            7000,
        )
        return True

    def delete_saved_leave(self, record_id: str) -> None:
        if not self.repository or not self.active_employee:
            self.show_error("The local database is unavailable.")
            return
        record = next(
            (item for item in self.existing_records if item.record_id == record_id),
            None,
        )
        if record is None:
            self.show_error("That saved leave record could not be found.")
            return
        dates = record.start.strftime("%m/%d/%Y")
        if record.end != record.start:
            dates += " → " + record.end.strftime("%m/%d/%Y")
        answer = QMessageBox.question(
            self,
            "Delete saved leave",
            f"Delete {self.leave_code(record.leave_type)} for {dates}?\n\n"
            "This removes only this exact saved row from the local database.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = self.repository.delete_leave_record(
                record_id,
                self.active_employee.employee_id,
            )
            if not deleted:
                raise RuntimeError("The saved leave record no longer exists.")
            self._refresh_active_employee_locally()
        except Exception as error:
            LOGGER.exception("Could not delete saved leave")
            self.show_error(str(error))
            return
        self.statusBar().showMessage("Saved leave deleted from the local database.", 6000)

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

    def save_draft(self, open_magclip: bool) -> None:
        if self._save_in_progress:
            self.statusBar().showMessage("The current draft is already being saved.", 3000)
            return
        if not self.repository or not self.active_employee:
            self.show_error("Select an employee and open the local database first.")
            return
        if not self.draft_entries:
            if open_magclip and self.existing_records:
                self.show_magclip_mode()
                return
            if open_magclip:
                self.show_error(
                    "There is no draft or saved leave history for this employee."
                )
                return
            self.show_error("Add at least one leave entry to the draft.")
            return
        employee = self.active_employee
        entries = list(self.draft_entries)
        self._set_save_busy(True, open_magclip)
        self.statusBar().showMessage(
            "Saving locally and opening MAGCLIP Mode…"
            if open_magclip
            else "Saving locally…"
        )

        try:
            result = self.repository.save_draft(employee, entries)
        except Exception as error:
            LOGGER.exception("Could not save local leave history")
            self._draft_save_failed(str(error))
            return
        try:
            self._draft_saved(result, open_magclip)
        except Exception as error:
            LOGGER.exception("Leave was saved but the display refresh failed")
            self._set_save_busy(False)
            self.show_error(
                "The leave was saved, but the display could not refresh. "
                "Restart the app to reload it.\n\n" + str(error)
            )

    def _set_save_busy(self, busy: bool, opening: bool = False) -> None:
        self._save_in_progress = busy
        self.save_local_button.setEnabled(not busy)
        self.save_send_button.setEnabled(not busy)
        self.save_local_button.setText(
            "Saving…" if busy and not opening else "Save Locally"
        )
        self.save_send_button.setText(
            "Saving + Opening…" if busy and opening else "Save + Open MAGCLIP Mode"
        )
        if not busy:
            self._update_magclip_action_button()

    def _draft_save_failed(self, message: str) -> None:
        self._set_save_busy(False)
        self.show_error(message)

    def _draft_saved(self, result: SaveResult, open_magclip: bool) -> None:
        self._set_save_busy(False)
        if result.rows_written:
            self.draft_entries.clear()
            self.draft_employee_id = ""
        self._refresh_active_employee_locally()
        message = result.message
        QMessageBox.information(self, "Leave history saved", message)
        self.statusBar().showMessage(message, 9000)
        if open_magclip:
            self.show_magclip_mode()

    def _refresh_active_employee_locally(self) -> None:
        if not self.active_employee or not self.repository:
            self.render_draft()
            return
        employee = (
            self.repository.employee_by_id(self.active_employee.employee_id, force=True)
            or self.active_employee
        )
        records = tuple(self.repository.leave_records(employee.employee_id))
        profile = self.repository.employee_profile(
            employee,
            force=True,
            records=records,
        )
        self._employee_loaded(
            (
                employee,
                profile,
                {
                    day
                    for record in records
                    for day in record.calendar_dates
                },
                records,
            )
        )

    def toggle_magclip_mode(self) -> None:
        if self.mode_stack.currentWidget() is self.magclip_page:
            self.show_calendar_mode()
        else:
            self.show_magclip_mode()

    def toggle_credits_mode(self) -> None:
        if self.mode_stack.currentWidget() is self.credits_page:
            self.show_calendar_mode()
        else:
            self.show_credits_mode()

    def show_credits_mode(self) -> None:
        self.magclip_page.deactivate_hotkeys()
        self._restore_calendar_window()
        self.credits_page.set_context(self.repository, self.active_employee)
        self.mode_stack.setCurrentWidget(self.credits_page)
        self.credits_button.setText("Calendar Mode")
        self.mode_button.setText("MAGCLIP Mode")
        self.statusBar().showMessage("Credits Mode active · data saves locally.", 5000)

    def show_magclip_mode(self) -> None:
        self._magclip_return_mode = "calendar"
        self.magclip_page.set_history(self.active_employee, self.existing_records)
        self.mode_stack.setCurrentWidget(self.magclip_page)
        self.mode_button.setText("Calendar Mode")
        self.credits_button.setText("Credits Mode")
        self.magclip_page.activate_hotkeys()
        self._dock_magclip_window()
        self.statusBar().showMessage(
            "MAGCLIP Mode active · F1 Fire · R Reload Round · "
            "F4 Reload Clip · F3 Abort",
            8000,
        )

    def show_credits_magclip_mode(self) -> None:
        if not self.active_employee or not self.repository:
            self.statusBar().showMessage("Select an employee first.", 5000)
            return
        self._magclip_return_mode = "credits"
        entries = self.repository.credit_magclip_entries(
            self.active_employee.employee_id
        )
        self.magclip_page.set_credits(self.active_employee, entries)
        self.mode_stack.setCurrentWidget(self.magclip_page)
        self.mode_button.setText("Calendar Mode")
        self.credits_button.setText("Credits Mode")
        self.magclip_page.activate_hotkeys()
        self._dock_magclip_window()
        self.statusBar().showMessage(
            "Credits MAGCLIP active · F1 Fire/Repeat · F2 Stop · F3 Abort",
            8000,
        )

    def _return_from_magclip(self) -> None:
        if self._magclip_return_mode == "credits":
            self.show_credits_mode()
        else:
            self.show_calendar_mode()

    def show_calendar_mode(self) -> None:
        self.magclip_page.deactivate_hotkeys()
        self.mode_stack.setCurrentIndex(0)
        self.mode_button.setText("MAGCLIP Mode")
        self.credits_button.setText("Credits Mode")
        self._restore_calendar_window()
        self.statusBar().showMessage("Calendar Mode active.", 4000)

    def _dock_magclip_window(self) -> None:
        if self._magclip_window_docked:
            return
        self._calendar_was_maximized = self.isMaximized()
        self._calendar_geometry = self.saveGeometry()
        self._magclip_window_docked = True
        self.app_header.hide()
        self.setWindowTitle("Leave Calendar · MAGCLIP Side Panel")
        self.setMinimumSize(460, 640)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.showNormal()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(520, available.width())
            self.setGeometry(
                available.right() - width + 1,
                available.top(),
                width,
                available.height(),
            )
        else:
            self.resize(520, 900)
        self.show()
        self.raise_()

    def _restore_calendar_window(self) -> None:
        if not self._magclip_window_docked:
            return
        self._magclip_window_docked = False
        self.app_header.show()
        self.setWindowTitle("Leave Calendar · Python Desktop")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.setMinimumSize(1080, 720)
        self.showNormal()
        if self._calendar_geometry is not None:
            self.restoreGeometry(self._calendar_geometry)
        if self._calendar_was_maximized:
            self.showMaximized()
        else:
            self.show()

    def install_calendar_lookup_hotkey(self) -> None:
        if self.lookup_hotkey_handle is not None:
            return
        try:
            import keyboard

            self.lookup_hotkey_handle = keyboard.hook(
                self._calendar_lookup_key_event,
                suppress=False,
            )
        except Exception as error:
            LOGGER.warning("Could not enable Ctrl+Shift calendar lookup: %s", error)
            self.lookup_hotkey_handle = None

    def _calendar_lookup_key_event(self, event: object) -> None:
        requested = self.lookup_modifier_state.update(
            str(getattr(event, "name", "")),
            str(getattr(event, "event_type", "")),
        )
        if requested is not None:
            self.lookup_hotkey_bridge.visibility_requested.emit(requested)

    def set_calendar_lookup_visible(self, visible: bool) -> None:
        if not visible:
            self.lookup_panel.hide()
            return
        month = int(self.jump_month_combo.currentData() or date.today().month)
        try:
            year = int(self.jump_year_edit.text().strip())
        except ValueError:
            year = self.fast_year_spin.value()
        year = min(CALENDAR_MAX_YEAR, max(CALENDAR_MIN_YEAR, year))
        anchor = date(year, month, 1)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(340, max(280, available.width() // 4))
            self.lookup_panel.setGeometry(
                available.left(),
                available.top(),
                width,
                available.height(),
            )
        else:
            self.lookup_panel.resize(330, 850)
        self.lookup_panel.prepare_to_show(anchor)
        self.lookup_panel.show()

    def uninstall_calendar_lookup_hotkey(self) -> None:
        self.lookup_panel.hide()
        self.lookup_modifier_state.reset()
        if self.lookup_hotkey_handle is None:
            return
        try:
            import keyboard

            keyboard.unhook(self.lookup_hotkey_handle)
        except Exception:
            LOGGER.exception("Could not remove Ctrl+Shift calendar lookup hook")
        self.lookup_hotkey_handle = None

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        self.magclip_page.deactivate_hotkeys()
        self.uninstall_calendar_lookup_hotkey()
        self.lookup_panel.close()
        super().closeEvent(event)

    def run_job(
        self,
        function: Callable[[], Any],
        on_success: Callable[[object], None],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        worker = Worker(function)
        worker.signals.result.connect(on_success)
        worker.signals.error.connect(on_error or self.show_error)
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

    def configure_login_launcher(self) -> bool:
        dialog = LoginLauncherDialog(self.app_settings, self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def open_login_destination(self, destination: str) -> None:
        try:
            validate_executable(self.app_settings.login_exe_path)
            if not self.app_settings.login_username.strip():
                raise ValueError("Enter the login username in Login Setup.")
            if not self.app_settings.login_password:
                raise ValueError("Enter the login password in Login Setup.")
        except ValueError:
            if not self.configure_login_launcher():
                return

        self.statusBar().showMessage(
            f"Opening Leave {destination.title()}… keep the target application untouched.",
            self.app_settings.login_startup_delay_ms
            + self.app_settings.login_navigation_delay_ms
            + 5000,
        )
        sequence = destination_login_sequence(
            destination,
            self.app_settings.login_navigation_delay_ms,
        )
        self.run_job(
            lambda: launch_and_login(
                self.app_settings.login_exe_path,
                self.app_settings.login_username,
                self.app_settings.login_password,
                self.app_settings.login_startup_delay_ms,
                sequence,
            ),
            lambda _result: self.statusBar().showMessage(
                f"Leave {destination.title()} sequence completed.", 5000
            ),
        )


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
