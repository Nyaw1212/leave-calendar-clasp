from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .credits import CreditOrderError, MONTH_NAMES
from .local_repository import LocalRepository, LocalRepositoryError
from .models import CreditEntry, Employee


class CreditsPage(QWidget):
    back_requested = Signal()
    credits_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository: LocalRepository | None = None
        self.employee: Employee | None = None
        self.entries: list[CreditEntry] = []

        title = QLabel("Monthly Credit Ledger")
        title.setStyleSheet("font-size:22px;font-weight:900;color:#f8fafc")
        self.employee_label = QLabel("Select an employee in Calendar Mode")
        self.employee_label.setStyleSheet("color:#7dd3fc;font-size:13px;font-weight:700")
        back_button = QPushButton("Calendar Mode")
        back_button.clicked.connect(self.back_requested.emit)

        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addWidget(self.employee_label)
        heading.addStretch(1)
        heading.addWidget(back_button)

        rule = QLabel(
            "CREDITS Sheet1 logic · Opening credit comes from Date of Assumption. "
            "Click a month to add MONTHS ELAPSED × 1.250. Selecting an earlier "
            "month automatically starts the next year."
        )
        rule.setWordWrap(True)
        rule.setStyleSheet(
            "background:#10243a;color:#bae6fd;border:1px solid #1d4f73;"
            "border-radius:9px;padding:10px;font-weight:700"
        )

        self.opening_vl = QLabel("0.000")
        self.opening_sl = QLabel("0.000")
        for field in (self.opening_vl, self.opening_sl):
            field.setStyleSheet("font-size:20px;font-weight:900;color:#f8fafc")
        opening_note = QLabel("Calculated from Date of Assumption")
        opening_note.setStyleSheet("color:#94a3b8;font-weight:700")

        opening_controls = QGridLayout()
        opening_controls.addWidget(QLabel("OPENING VL"), 0, 0)
        opening_controls.addWidget(QLabel("OPENING SL"), 0, 1)
        opening_controls.addWidget(self.opening_vl, 1, 0)
        opening_controls.addWidget(self.opening_sl, 1, 1)
        opening_controls.addWidget(opening_note, 1, 2)
        opening_controls.setColumnStretch(3, 1)

        self.selected_month = 1
        self.month_buttons: dict[int, QPushButton] = {}
        month_grid = QGridLayout()
        month_grid.setHorizontalSpacing(7)
        month_grid.setVerticalSpacing(7)
        for number, name in enumerate(MONTH_NAMES, start=1):
            button = QPushButton(name[:3])
            button.setCheckable(True)
            button.setMinimumSize(76, 38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{background:#172334;color:#cbd5e1;border:1px solid #334155;"
                "border-radius:12px;font-weight:900;font-size:12px}"
                "QPushButton:hover{background:#24344b;border-color:#38bdf8;color:white}"
                "QPushButton:checked{background:#2563eb;border:2px solid #7dd3fc;color:white}"
                "QPushButton:disabled{background:#111827;color:#475569;border-color:#1e293b}"
            )
            button.clicked.connect(
                lambda _checked=False, month=number: self._month_clicked(month)
            )
            month_grid.addWidget(button, (number - 1) // 3, (number - 1) % 3)
            self.month_buttons[number] = button
        self.month_buttons[1].setChecked(True)
        controls = QGridLayout()
        controls.setHorizontalSpacing(10)
        controls.setVerticalSpacing(7)
        controls.addWidget(QLabel("CHOOSE MONTH"), 0, 0)
        controls.addLayout(month_grid, 1, 0, 4, 1)
        click_note = QLabel("CLICK A MONTH TO ADD IT")
        click_note.setStyleSheet("color:#86efac;font-weight:900")
        controls.addWidget(click_note, 1, 1)
        auto_note = QLabel("YEAR: AUTO  ·  RATE: 1.250")
        auto_note.setStyleSheet("color:#94a3b8;font-weight:700")
        controls.addWidget(auto_note, 2, 1)
        controls.setColumnStretch(0, 1)
        controls.setColumnStretch(2, 2)

        self.status = QLabel("Choose an employee, then add the first credit month.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "background:#172334;color:#cbd5e1;border-radius:7px;padding:8px"
        )

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            ["MONTH", "YEAR", "VL EARNED", "SL EARNED", "MONTH GAP", ""]
        )
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(5, 46)

        self.total_vl = QLabel("0.000")
        self.total_sl = QLabel("0.000")
        for total in (self.total_vl, self.total_sl):
            total.setStyleSheet("font-size:24px;font-weight:900;color:#f8fafc")

        totals = QGridLayout()
        totals.addWidget(QLabel("TOTAL VL EARNED"), 0, 0)
        totals.addWidget(QLabel("TOTAL SL EARNED"), 0, 1)
        totals.addWidget(self.total_vl, 1, 0)
        totals.addWidget(self.total_sl, 1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(heading)
        layout.addWidget(rule)
        layout.addLayout(opening_controls)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        layout.addWidget(self.tree, 1)
        layout.addLayout(totals)
        self._set_controls_enabled(False)

    def set_context(
        self,
        repository: LocalRepository | None,
        employee: Employee | None,
    ) -> None:
        self.repository = repository
        self.employee = employee
        self.employee_label.setText(
            employee.display_name if employee else "Select an employee in Calendar Mode"
        )
        self.reload()

    def reload(self) -> None:
        self.entries = []
        opening: tuple[float, float] | None = None
        if self.repository is not None and self.employee is not None:
            try:
                self.entries = self.repository.credit_entries(self.employee.employee_id)
                opening = self.repository.credit_opening(self.employee.employee_id)
            except LocalRepositoryError as error:
                self._show_warning(str(error))
        self.opening_vl.setText(f"{opening[0] if opening else 0.0:.3f}")
        self.opening_sl.setText(f"{opening[1] if opening else 0.0:.3f}")
        self._opening_is_saved = opening is not None
        self._render()

    def _render(self) -> None:
        self.tree.clear()
        previous: CreditEntry | None = None
        for entry in self.entries:
            month_gap = (
                1
                if previous is None
                else 12 * (entry.year - previous.year) + entry.month - previous.month
            )
            item = QTreeWidgetItem(
                [
                    MONTH_NAMES[entry.month - 1].title(),
                    str(entry.year),
                    f"{entry.vl_earned:.3f}",
                    f"{entry.sl_earned:.3f}",
                    str(month_gap),
                    "",
                ]
            )
            for column in range(1, 5):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
            self.tree.addTopLevelItem(item)
            remove_button = QPushButton("×")
            remove_button.setToolTip(
                f"Remove {MONTH_NAMES[entry.month - 1].title()} {entry.year}"
            )
            remove_button.setFixedSize(30, 24)
            remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_button.setStyleSheet(
                "QPushButton{background:#7f1d1d;color:#fecaca;border:1px solid #ef4444;"
                "border-radius:7px;font-size:16px;font-weight:900;padding:0}"
                "QPushButton:hover{background:#dc2626;color:white}"
            )
            remove_button.clicked.connect(
                lambda _checked=False, selected_id=entry.entry_id: self.remove_entry(
                    selected_id
                )
            )
            self.tree.setItemWidget(item, 5, remove_button)
            previous = entry

        opening = (
            self.repository.credit_opening(self.employee.employee_id)
            if self.repository is not None and self.employee is not None
            else None
        )
        self.total_vl.setText(
            f"{(opening[0] if opening else 0) + sum(row.vl_earned for row in self.entries):.3f}"
        )
        self.total_sl.setText(
            f"{(opening[1] if opening else 0) + sum(row.sl_earned for row in self.entries):.3f}"
        )
        available = self.repository is not None and self.employee is not None
        self._set_controls_enabled(available)
        for button in self.month_buttons.values():
            button.setEnabled(available and self._opening_is_saved)
        if self.entries:
            last = self.entries[-1]
            self._select_month(last.month % 12 + 1)
            self.status.setText(
                f"Last row: {MONTH_NAMES[last.month - 1].title()} {last.year}. "
                "The next year will be inferred automatically."
            )
            self.status.setStyleSheet(
                "background:#0f3328;color:#bbf7d0;border-radius:7px;padding:8px"
            )
        elif available:
            if self.employee and self.employee.assumption_date:
                assumption = self.employee.assumption_date
                self._select_month(assumption.month % 12 + 1)
            self.status.setText(
                "The opening credit comes from Date of Assumption. "
                "Choose the next credit month."
            )
            self.status.setStyleSheet(
                "background:#172334;color:#cbd5e1;border-radius:7px;padding:8px"
            )

    def _set_controls_enabled(self, enabled: bool) -> None:
        for button in self.month_buttons.values():
            button.setEnabled(enabled)

    def _select_month(self, month: int) -> None:
        self.selected_month = int(month)
        for number, button in self.month_buttons.items():
            button.setChecked(number == self.selected_month)

    def _month_clicked(self, month: int) -> None:
        self._select_month(month)
        self.add_month()

    def _show_warning(self, message: str) -> None:
        self.status.setText(f"WARNING · {message}")
        self.status.setStyleSheet(
            "background:#422006;color:#fde68a;border:1px solid #d97706;"
            "border-radius:7px;padding:8px;font-weight:700"
        )

    def add_month(self) -> None:
        if self.repository is None or self.employee is None:
            self._show_warning("Select an employee in Calendar Mode first.")
            return
        if not self.employee.assumption_date:
            self._show_warning("Save the employee's Date of Assumption first.")
            return
        try:
            self.repository.add_credit_entry(
                self.employee.employee_id,
                self.selected_month,
                self.employee.assumption_date.year,
                self.entries[-1].rate if self.entries else 1.25,
            )
        except (CreditOrderError, LocalRepositoryError, ValueError) as error:
            self._show_warning(str(error))
            return
        self.reload()
        self.credits_changed.emit()

    def remove_entry(self, entry_id: str) -> None:
        if self.repository is None or self.employee is None:
            self._show_warning("Select an employee in Calendar Mode first.")
            return
        try:
            removed = self.repository.delete_credit_entry(
                self.employee.employee_id,
                entry_id,
            )
        except LocalRepositoryError as error:
            self._show_warning(str(error))
            return
        if not removed:
            self._show_warning("The credit row could not be found.")
            return
        self.reload()
        self.credits_changed.emit()

    def remove_last(self) -> None:
        if self.repository is None or self.employee is None or not self.entries:
            self._show_warning("There is no credit row to remove.")
            return
        try:
            removed = self.repository.delete_last_credit_entry(self.employee.employee_id)
        except LocalRepositoryError as error:
            self._show_warning(str(error))
            return
        if not removed:
            self._show_warning("The last credit row could not be found.")
            return
        self.reload()
        self.credits_changed.emit()
