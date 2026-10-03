from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .card_preview import LeaveCardPreviewPage
from .local_repository import LocalRepositoryError

if TYPE_CHECKING:
    from .local_repository import LocalRepository


@dataclass(frozen=True, slots=True)
class MoneBalanceEntry:
    employee_id: str
    name: str
    history_completed: bool
    computed_vl: float = 0.0
    computed_sl: float = 0.0


class MoneBalancePage(QWidget):
    """One-at-a-time MONE credit-balance entry with a leave-card reference."""

    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repository: LocalRepository | None = None
        self._entries: list[MoneBalanceEntry] = []
        self._current_index = 0
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        back_button = QPushButton("← Leave History")
        back_button.clicked.connect(self.back_requested)
        title = QLabel("MONE Credit Balance Entry")
        title.setStyleSheet("font-size:22px;font-weight:900;color:#f8fafc")
        title_row.addWidget(back_button)
        title_row.addWidget(title)
        title_row.addStretch(1)
        root.addLayout(title_row)

        note = QLabel(
            "Employees with saved Leave History (or marked Done) use their calculated VL/SL balance. For unfinished "
            "leave history, enter a MONE-only balance: <b>10 15</b> means VL 10 and SL 15. "
            "These entries do not change Leave History or normal leave credits."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "background:#102a33;color:#bae6fd;border:1px solid #155e75;"
            "border-radius:8px;padding:10px 12px;font-size:13px"
        )
        root.addWidget(note)

        start_row = QHBoxLayout()
        start_caption = QLabel("START FROM")
        start_caption.setStyleSheet("color:#67e8f9;font-size:12px;font-weight:900")
        self.start_employee_combo = QComboBox()
        self.start_employee_combo.setEditable(True)
        self.start_employee_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.start_employee_combo.setPlaceholderText("Choose or type an employee name…")
        self.start_employee_combo.setToolTip(
            "Choose the employee whose leave card is ready. Entry begins there, then continues to the following names."
        )
        self.start_employee_combo.activated.connect(self._select_start_employee)
        start_row.addWidget(start_caption)
        start_row.addWidget(self.start_employee_combo, 1)
        root.addLayout(start_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        form_panel = QWidget()
        form_panel.setMinimumWidth(350)
        form_panel.setMaximumWidth(510)
        form = QVBoxLayout(form_panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self.progress_label = QLabel("No employees available")
        self.progress_label.setStyleSheet("color:#67e8f9;font-size:14px;font-weight:800")
        self.name_label = QLabel("Load an NBP BIS list or local employee records.")
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("font-size:22px;font-weight:900;color:#f8fafc")
        self.employee_id_label = QLabel("")
        self.employee_id_label.setStyleSheet("color:#94a3b8;font-size:13px;font-weight:800")
        self.source_label = QLabel("")
        self.source_label.setWordWrap(True)
        self.source_label.setStyleSheet(
            "background:#1e293b;color:#cbd5e1;border-radius:8px;padding:10px;"
            "font-size:14px;font-weight:800"
        )
        form.addWidget(self.progress_label)
        form.addWidget(self.name_label)
        form.addWidget(self.employee_id_label)
        form.addWidget(self.source_label)

        balance_row = QHBoxLayout()
        self.vl_balance = self._balance_box("VL balance")
        self.sl_balance = self._balance_box("SL balance")
        balance_row.addWidget(self.vl_balance)
        balance_row.addWidget(self.sl_balance)
        form.addLayout(balance_row)

        input_caption = QLabel("FAST MONE BALANCE · VL SL [LAST CREDIT MONTH YEAR]")
        input_caption.setStyleSheet("color:#67e8f9;font-size:12px;font-weight:900")
        self.balance_input = QLineEdit()
        self.balance_input.setPlaceholderText("10 15   or   10 15 11 25")
        self.balance_input.setToolTip(
            "Enter VL and SL directly, or add the last credited month and year to catch up through the last completed month."
        )
        self.balance_input.setMinimumHeight(56)
        self.balance_input.setStyleSheet(
            "QLineEdit{font-size:24px;font-weight:900;color:#f8fafc;background:#172554;"
            "border:2px solid #3b82f6;border-radius:9px;padding:8px 12px;}"
            "QLineEdit:read-only{color:#cbd5e1;background:#1e293b;border-color:#475569;}"
        )
        self.balance_input.returnPressed.connect(self.save_and_next)
        self.input_help = QLabel(
            "10 15 saves a direct balance. 10 15 11 25 adds credits from Dec 2025 through the latest completed month."
        )
        self.input_help.setWordWrap(True)
        self.input_help.setStyleSheet("color:#cbd5e1;font-size:13px")
        form.addWidget(input_caption)
        form.addWidget(self.balance_input)
        form.addWidget(self.input_help)

        form.addStretch(1)
        buttons = QHBoxLayout()
        self.previous_button = QPushButton("← Back")
        self.previous_button.clicked.connect(self.show_previous)
        self.save_button = QPushButton("Save Balance")
        self.save_button.clicked.connect(self.save_current)
        self.skip_button = QPushButton("Skip →")
        self.skip_button.setToolTip("Move to the next employee without saving a MONE balance.")
        self.skip_button.clicked.connect(self.skip_current)
        self.next_button = QPushButton("Save + Next →")
        self.next_button.setStyleSheet(
            "QPushButton{background:#2563eb;color:white;border-color:#3b82f6;"
            "font-weight:900;padding:10px 14px;}QPushButton:hover{background:#1d4ed8}"
        )
        self.next_button.clicked.connect(self.save_and_next)
        buttons.addWidget(self.previous_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.skip_button)
        buttons.addWidget(self.next_button)
        form.addLayout(buttons)

        self.preview = LeaveCardPreviewPage(embedded=True)
        splitter.addWidget(form_panel)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([450, 820])
        root.addWidget(splitter, 1)

    @staticmethod
    def _balance_box(title: str) -> QFrame:
        box = QFrame()
        box.setStyleSheet(
            "QFrame{background:#ecfeff;border:1px solid #67e8f9;border-radius:9px;}"
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 8, 12, 9)
        caption = QLabel(title)
        caption.setStyleSheet("color:#0e7490;font-size:12px;font-weight:900")
        value = QLabel("—")
        value.setObjectName("moneBalanceValue")
        value.setStyleSheet("color:#0f172a;font-size:25px;font-weight:900")
        layout.addWidget(caption)
        layout.addWidget(value)
        return box

    @staticmethod
    def _set_balance_box(box: QFrame, value: float | None) -> None:
        label = box.findChild(QLabel, "moneBalanceValue")
        if label is not None:
            label.setText(f"{value:.3f}" if value is not None else "—")

    def set_context(
        self,
        repository: LocalRepository,
        entries: Iterable[MoneBalanceEntry],
    ) -> None:
        self._repository = repository
        self._entries = list(entries)
        self._current_index = 0
        self.start_employee_combo.blockSignals(True)
        self.start_employee_combo.clear()
        for index, entry in enumerate(self._entries):
            self.start_employee_combo.addItem(
                f"{entry.name} · {entry.employee_id}", index
            )
        self.start_employee_combo.setEnabled(bool(self._entries))
        self.start_employee_combo.blockSignals(False)
        self._show_current()

    def _select_start_employee(self, combo_index: int) -> None:
        entry_index = self.start_employee_combo.itemData(combo_index)
        if not isinstance(entry_index, int) or not 0 <= entry_index < len(self._entries):
            return
        self._current_index = entry_index
        self._show_current()

    def _current_entry(self) -> MoneBalanceEntry | None:
        if 0 <= self._current_index < len(self._entries):
            return self._entries[self._current_index]
        return None

    def _show_current(self) -> None:
        entry = self._current_entry()
        if entry is None:
            self.progress_label.setText("No employees available")
            self.name_label.setText("Load an NBP BIS list or local employee records.")
            self.employee_id_label.setText("")
            self.source_label.setText("There is no MONE balance entry to show yet.")
            self.balance_input.clear()
            self.balance_input.setReadOnly(True)
            self.start_employee_combo.setCurrentIndex(-1)
            self.previous_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.skip_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return

        self.progress_label.setText(
            f"Employee {self._current_index + 1} of {len(self._entries)}"
        )
        self.start_employee_combo.blockSignals(True)
        self.start_employee_combo.setCurrentIndex(self._current_index)
        self.start_employee_combo.blockSignals(False)
        self.name_label.setText(entry.name)
        self.employee_id_label.setText(f"Employee ID · {entry.employee_id}")
        self.preview.set_employee_context(entry.employee_id, entry.name)
        self.preview.show_last_page_bottom()
        self.previous_button.setEnabled(self._current_index > 0)
        self.skip_button.setEnabled(True)
        self.next_button.setEnabled(True)

        if entry.history_completed:
            self.source_label.setText(
                "✓ SAVED LEAVE HISTORY / DONE RECORD · calculated balance is used automatically for MONE."
            )
            self.source_label.setStyleSheet(
                "background:#14532d;color:#dcfce7;border-radius:8px;padding:10px;"
                "font-size:14px;font-weight:900"
            )
            self._set_balance_box(self.vl_balance, entry.computed_vl)
            self._set_balance_box(self.sl_balance, entry.computed_sl)
            self.balance_input.setReadOnly(True)
            self.balance_input.setText(f"{entry.computed_vl:g} {entry.computed_sl:g}")
            self.input_help.setText("Automatic computed balance. Use Next to continue.")
            self.save_button.setEnabled(False)
            self.next_button.setText("Next →")
            return

        override = (
            self._repository.mone_balance_override(entry.employee_id)
            if self._repository is not None
            else None
        )
        catchup = (
            self._repository.mone_balance_catchup(entry.employee_id)
            if self._repository is not None
            else None
        )
        self.source_label.setText(
            "MANUAL MONE BALANCE REQUIRED · this saved value is used only for MONE."
        )
        self.source_label.setStyleSheet(
            "background:#78350f;color:#fef3c7;border-radius:8px;padding:10px;"
            "font-size:14px;font-weight:900"
        )
        self._set_balance_box(self.vl_balance, override[0] if override else None)
        self._set_balance_box(self.sl_balance, override[1] if override else None)
        self.balance_input.setReadOnly(False)
        if catchup:
            base_vl, base_sl, month, year, through_month, through_year = catchup
            self.balance_input.setText(f"{base_vl:g} {base_sl:g} {month} {year % 100:02d}")
            self.input_help.setText(
                f"Saved catch-up through {through_month:02d}/{through_year} · "
                f"final MONE balance {override[0]:.3f} VL / {override[1]:.3f} SL."
                if override
                else "Enter VL SL or VL SL month year."
            )
        else:
            self.balance_input.setText(
                f"{override[0]:g} {override[1]:g}" if override else ""
            )
            self.input_help.setText(
                "Enter VL SL, or add last-credit month and year: 10 15 11 25."
            )
        self.balance_input.setFocus()
        self.save_button.setEnabled(True)
        self.next_button.setText("Save + Next →")

    def _manual_values(self) -> tuple[float, float, int | None, int | None] | None:
        pieces = self.balance_input.text().replace(",", " ").split()
        if len(pieces) not in {2, 4}:
            self.input_help.setText(
                "Enter VL SL, or VL SL last-credit-month last-credit-year. Example: 10 15 11 25"
            )
            return None
        try:
            vl, sl = (round(float(piece), 3) for piece in pieces[:2])
        except ValueError:
            self.input_help.setText("VL and SL must be numbers. Example: 10 15 11 25")
            return None
        if vl < 0 or sl < 0:
            self.input_help.setText("VL and SL cannot be negative.")
            return None
        if len(pieces) == 2:
            return vl, sl, None, None
        try:
            month = int(pieces[2])
            year = int(pieces[3])
        except ValueError:
            self.input_help.setText("The last credited month and year must be whole numbers. Example: 11 25")
            return None
        if year < 100:
            year += 2000 if year < 70 else 1900
        if not 1 <= month <= 12 or year < 1900:
            self.input_help.setText("Use a valid last credited month and year. Example: 11 25")
            return None
        return vl, sl, month, year

    def _save_manual_current(self) -> bool:
        entry = self._current_entry()
        if entry is None or entry.history_completed:
            return True
        values = self._manual_values()
        if values is None:
            return False
        if self._repository is None:
            self.input_help.setText("The local database is unavailable.")
            return False
        try:
            base_vl, base_sl, last_month, last_year = values
            if last_month is None or last_year is None:
                vl, sl = self._repository.save_mone_balance_override(
                    entry.employee_id, entry.name, base_vl, base_sl
                )
                message = "Saved for MONE only. Leave History was not changed."
            else:
                vl, sl, month_count, through_month, through_year = (
                    self._repository.save_mone_balance_catchup(
                        entry.employee_id,
                        entry.name,
                        base_vl,
                        base_sl,
                        last_month,
                        last_year,
                    )
                )
                first_month = last_month % 12 + 1
                first_year = last_year + (1 if last_month == 12 else 0)
                message = (
                    f"Saved catch-up · {month_count} month(s), {first_month:02d}/{first_year} "
                    f"through {through_month:02d}/{through_year} · +{month_count * 1.25:.3f} VL / SL."
                )
        except LocalRepositoryError as error:
            self.input_help.setText(str(error))
            return False
        self._set_balance_box(self.vl_balance, vl)
        self._set_balance_box(self.sl_balance, sl)
        self.input_help.setText(message)
        return True

    def save_current(self) -> None:
        self._save_manual_current()

    def save_and_next(self) -> None:
        if not self._save_manual_current():
            return
        self._show_next()

    def skip_current(self) -> None:
        """Move on without changing the current employee's manual balance."""
        self._show_next()

    def _show_next(self) -> None:
        if self._current_index + 1 < len(self._entries):
            self._current_index += 1
            self._show_current()
        else:
            self.input_help.setText("All employees have been reviewed. Use Back to correct a value.")
            self.skip_button.setEnabled(False)
            self.next_button.setEnabled(False)

    def show_previous(self) -> None:
        if self._current_index <= 0:
            return
        self._current_index -= 1
        self._show_current()
