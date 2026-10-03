from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
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
from .mone import MONE_AUTO_LEVELS, MONE_MINIMUM_SL, MONE_MINIMUM_VL, suggest_mone_credits

if TYPE_CHECKING:
    from .local_repository import LocalRepository


_INVALID_REQUEST = object()


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
    sync_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repository: LocalRepository | None = None
        self._entries: list[MoneBalanceEntry] = []
        self._current_index = 0
        self._build_ui()
        self._install_preview_shortcuts()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        back_button = QPushButton("← Leave History")
        back_button.clicked.connect(self.back_requested)
        title = QLabel("MONE Credit Balance Entry")
        title.setStyleSheet("font-size:22px;font-weight:900;color:#f8fafc")
        self.sync_button = QPushButton("Sync MONE → Google Sheet")
        self.sync_button.setToolTip(
            "Upload all saved MONE-ready balances to the MONE BALANCES tab. "
            "Rows are updated by Employee ID."
        )
        self.sync_button.setStyleSheet(
            "QPushButton{background:#047857;color:#ecfdf5;border-color:#34d399;"
            "font-weight:900;padding:8px 12px;}QPushButton:hover{background:#059669}"
        )
        self.sync_button.clicked.connect(self._request_sync)
        title_row.addWidget(back_button)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.sync_button)
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

        request_row = QHBoxLayout()
        request_caption = QLabel("REQUESTED MONE · OPTIONAL")
        request_caption.setStyleSheet("color:#fbbf24;font-size:12px;font-weight:900")
        self.requested_mone_input = QLineEdit()
        self.requested_mone_input.setPlaceholderText("Example: 30")
        self.requested_mone_input.setMaximumWidth(150)
        self.requested_mone_input.setToolTip(
            "Optional applicant request. It replaces the automatic MONE ladder, "
            "but the protected 5 VL and 5 SL credits are always retained."
        )
        self.requested_mone_input.editingFinished.connect(self._refresh_mone_suggestion)
        request_row.addWidget(request_caption)
        request_row.addWidget(self.requested_mone_input)
        request_row.addStretch(1)
        form.addLayout(request_row)

        suggestion_caption = QLabel("SUGGESTED MONE · SL FIRST · KEEPS 5 VL / 5 SL")
        suggestion_caption.setStyleSheet("color:#fbbf24;font-size:12px;font-weight:900")
        suggestion_row = QHBoxLayout()
        self.target_mone_balance = self._balance_box("MONE target")
        self.mvl_balance = self._balance_box("MVL · suggested")
        self.msl_balance = self._balance_box("MSL · suggested")
        suggestion_row.addWidget(self.target_mone_balance)
        suggestion_row.addWidget(self.mvl_balance)
        suggestion_row.addWidget(self.msl_balance)
        self.suggestion_help = QLabel("")
        self.suggestion_help.setWordWrap(True)
        self.suggestion_help.setStyleSheet("color:#fef3c7;font-size:12px;font-weight:800")
        form.addWidget(suggestion_caption)
        form.addLayout(suggestion_row)
        form.addWidget(self.suggestion_help)

        input_caption = QLabel("FAST MONE BALANCE · VL SL [MONTH YEAR] · OR VLSL MONTH YEAR")
        input_caption.setStyleSheet("color:#67e8f9;font-size:12px;font-weight:900")
        self.balance_input = QLineEdit()
        self.balance_input.setPlaceholderText("10 15   ·   10 15 11 25   ·   10 10 25")
        self.balance_input.setToolTip(
            "Enter VL and SL directly, add the last credited month and year, or use one amount for both VL and SL."
        )
        self.balance_input.setMinimumHeight(56)
        self.balance_input.setStyleSheet(
            "QLineEdit{font-size:24px;font-weight:900;color:#f8fafc;background:#172554;"
            "border:2px solid #3b82f6;border-radius:9px;padding:8px 12px;}"
            "QLineEdit:read-only{color:#cbd5e1;background:#1e293b;border-color:#475569;}"
        )
        self.balance_input.returnPressed.connect(self.save_and_next)
        self.input_help = QLabel(
            "10 15 saves directly. 10.167 12 copies .167 to SL. "
            "10 15 11 25 catches up. 10 10 25 uses 10 for both VL and SL."
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

        self.previous_entry_box = QFrame()
        self.previous_entry_box.setObjectName("previousEntryBox")
        self.previous_entry_box.setStyleSheet(
            "#previousEntryBox{background:#0f2635;border:1px solid #155e75;border-radius:8px;"
            "padding:8px;}"
        )
        previous_layout = QVBoxLayout(self.previous_entry_box)
        previous_layout.setContentsMargins(10, 8, 10, 8)
        self.previous_entry_title = QLabel("PREVIOUS ENTRY")
        self.previous_entry_title.setStyleSheet(
            "color:#67e8f9;font-size:12px;font-weight:900"
        )
        self.previous_entry_id = QLabel("")
        self.previous_entry_id.setStyleSheet(
            "color:#bae6fd;font-size:12px;font-weight:800"
        )
        previous_balance_row = QHBoxLayout()
        self.previous_vl_balance = self._balance_box("VL balance")
        self.previous_sl_balance = self._balance_box("SL balance")
        previous_balance_row.addWidget(self.previous_vl_balance)
        previous_balance_row.addWidget(self.previous_sl_balance)
        self.previous_entry_summary = QLabel("")
        self.previous_entry_summary.setWordWrap(True)
        self.previous_entry_summary.setStyleSheet("color:#bae6fd;font-size:12px;font-weight:800")
        previous_layout.addWidget(self.previous_entry_title)
        previous_layout.addWidget(self.previous_entry_id)
        previous_layout.addLayout(previous_balance_row)
        previous_layout.addWidget(self.previous_entry_summary)
        form.addWidget(self.previous_entry_box)

        preview_splitter = QSplitter(Qt.Orientation.Vertical)
        preview_splitter.setChildrenCollapsible(False)
        preview_splitter.setHandleWidth(5)
        self.first_page_preview = LeaveCardPreviewPage(embedded=True)
        self.first_page_preview.set_reference_mode("LEAVE CARD · FIRST PAGE · NAME CHECK")
        self.last_page_preview = LeaveCardPreviewPage(embedded=True)
        self.last_page_preview.set_reference_mode("LEAVE CARD · CONTINUOUS PAGES · BALANCE CHECK")
        preview_splitter.addWidget(self.first_page_preview)
        preview_splitter.addWidget(self.last_page_preview)
        preview_splitter.setStretchFactor(0, 1)
        preview_splitter.setStretchFactor(1, 1)
        preview_splitter.setSizes([430, 430])
        splitter.addWidget(form_panel)
        splitter.addWidget(preview_splitter)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([450, 820])
        root.addWidget(splitter, 1)

    def _install_preview_shortcuts(self) -> None:
        self.preview_page_up_shortcut = QShortcut(QKeySequence("PgUp"), self)
        self.preview_page_down_shortcut = QShortcut(QKeySequence("PgDown"), self)
        for shortcut in (self.preview_page_up_shortcut, self.preview_page_down_shortcut):
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.preview_page_up_shortcut.activated.connect(
            lambda: self._scroll_continuous_preview(-1)
        )
        self.preview_page_down_shortcut.activated.connect(
            lambda: self._scroll_continuous_preview(1)
        )

    def _scroll_continuous_preview(self, direction: int) -> None:
        """Scroll the lower, continuous leave-card preview by one visible page."""
        bar = self.last_page_preview.scroll.verticalScrollBar()
        step = max(80, bar.pageStep())
        bar.setValue(bar.value() + (step if direction > 0 else -step))

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
            self.requested_mone_input.clear()
            self.requested_mone_input.setEnabled(False)
            self._set_suggestion_boxes(None)
            self.start_employee_combo.setCurrentIndex(-1)
            self.previous_entry_box.setVisible(False)
            self.previous_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.skip_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self.sync_button.setEnabled(False)
            return

        self.progress_label.setText(
            f"Employee {self._current_index + 1} of {len(self._entries)}"
        )
        self.start_employee_combo.blockSignals(True)
        self.start_employee_combo.setCurrentIndex(self._current_index)
        self.start_employee_combo.blockSignals(False)
        self._update_previous_entry()
        self.name_label.setText(entry.name)
        self.employee_id_label.setText(f"Employee ID · {entry.employee_id}")
        self.first_page_preview.set_employee_context(entry.employee_id, entry.name)
        self.first_page_preview.show_first_page_top()
        self.last_page_preview.set_employee_context(entry.employee_id, entry.name)
        self.last_page_preview.show_continuous_pages()
        self.previous_button.setEnabled(self._current_index > 0)
        self.skip_button.setEnabled(True)
        self.next_button.setEnabled(True)
        self.sync_button.setEnabled(bool(self.mone_sync_rows()))
        requested = (
            self._repository.mone_requested(entry.employee_id)
            if self._repository is not None
            else None
        )
        self.requested_mone_input.blockSignals(True)
        self.requested_mone_input.setText(f"{requested:g}" if requested is not None else "")
        self.requested_mone_input.setEnabled(True)
        self.requested_mone_input.blockSignals(False)

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
            self._refresh_mone_suggestion(entry.computed_vl, entry.computed_sl)
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
                "Enter VL SL, VL SL month year, or VLSL month year: 10 10 25."
            )
        self.balance_input.setFocus()
        self._refresh_mone_suggestion(
            override[0] if override else None,
            override[1] if override else None,
        )
        self.save_button.setEnabled(True)
        self.next_button.setText("Save + Next →")

    def _requested_mone_value(self, *, show_error: bool = False) -> float | None | object:
        text = self.requested_mone_input.text().strip().replace(",", "")
        if not text:
            return None
        try:
            value = round(float(text), 3)
        except ValueError:
            if show_error:
                self.suggestion_help.setText("Requested MONE must be a number, for example 30.")
            return _INVALID_REQUEST
        if value < 0:
            if show_error:
                self.suggestion_help.setText("Requested MONE cannot be negative.")
            return _INVALID_REQUEST
        return value

    def _set_suggestion_boxes(self, suggestion) -> None:
        if suggestion is None:
            self._set_balance_box(self.target_mone_balance, None)
            self._set_balance_box(self.mvl_balance, None)
            self._set_balance_box(self.msl_balance, None)
            self.suggestion_help.setText("Save or load a final VL/SL balance to calculate MONE.")
            return
        self._set_balance_box(self.target_mone_balance, suggestion.target)
        self._set_balance_box(self.mvl_balance, suggestion.mvl)
        self._set_balance_box(self.msl_balance, suggestion.msl)
        if suggestion.requested is None:
            level_text = " / ".join(f"{level:g}" for level in MONE_AUTO_LEVELS)
            self.suggestion_help.setText(
                f"Automatic level {suggestion.target:g} from {level_text}. "
                f"Available after maintaining credits: VL {suggestion.available_vl:g}, "
                f"SL {suggestion.available_sl:g}."
            )
        elif suggestion.is_requested_limited:
            self.suggestion_help.setText(
                f"Requested {suggestion.requested:g}; safely limited to {suggestion.target:g}. "
                f"SL is used first while keeping {MONE_MINIMUM_VL:g} VL / {MONE_MINIMUM_SL:g} SL."
            )
        else:
            self.suggestion_help.setText(
                f"Requested MONE {suggestion.target:g}; SL is used first while keeping "
                f"{MONE_MINIMUM_VL:g} VL / {MONE_MINIMUM_SL:g} SL."
            )

    def _refresh_mone_suggestion(
        self,
        vl: float | None = None,
        sl: float | None = None,
    ) -> None:
        if vl is None or sl is None:
            entry = self._current_entry()
            if entry is not None and entry.history_completed:
                vl, sl = entry.computed_vl, entry.computed_sl
            elif entry is not None and self._repository is not None:
                override = self._repository.mone_balance_override(entry.employee_id)
                if override is not None:
                    vl, sl = override
        if vl is None or sl is None:
            self._set_suggestion_boxes(None)
            return
        requested = self._requested_mone_value(show_error=False)
        if requested is _INVALID_REQUEST:
            self._set_balance_box(self.target_mone_balance, None)
            self._set_balance_box(self.mvl_balance, None)
            self._set_balance_box(self.msl_balance, None)
            self.suggestion_help.setText("Requested MONE must be a non-negative number.")
            return
        self._set_suggestion_boxes(suggest_mone_credits(vl, sl, requested))

    def _update_previous_entry(self) -> None:
        if self._current_index <= 0 or self._repository is None:
            self.previous_entry_box.setVisible(False)
            return
        previous = self._entries[self._current_index - 1]
        override = self._repository.mone_balance_override(previous.employee_id)
        catchup = self._repository.mone_balance_catchup(previous.employee_id)
        self.previous_entry_box.setVisible(True)
        self.previous_entry_title.setText(f"PREVIOUS ENTRY · {previous.name}")
        self.previous_entry_id.setText(f"Employee ID · {previous.employee_id}")
        if override is None:
            self._set_balance_box(self.previous_vl_balance, None)
            self._set_balance_box(self.previous_sl_balance, None)
            self.previous_entry_summary.setText(
                "No MONE balance saved · skipped."
            )
            return
        self._set_balance_box(self.previous_vl_balance, override[0])
        self._set_balance_box(self.previous_sl_balance, override[1])
        source = (
            f"catch-up through {catchup[4]:02d}/{catchup[5]}"
            if catchup is not None
            else "direct MONE balance"
        )
        self.previous_entry_summary.setText(
            source
        )

    def mone_sync_rows(self) -> list[dict[str, object]]:
        """Collect all complete MONE balance rows, ready for a safe sheet upsert."""
        if self._repository is None:
            return []
        rows: list[dict[str, object]] = []
        for entry in self._entries:
            if entry.history_completed:
                final_vl, final_sl = entry.computed_vl, entry.computed_sl
                source = "Leave History"
            else:
                override = self._repository.mone_balance_override(entry.employee_id)
                if override is None:
                    continue
                final_vl, final_sl = override
                source = "Manual MONE Balance"
            requested = self._repository.mone_requested(entry.employee_id)
            suggestion = suggest_mone_credits(final_vl, final_sl, requested)
            rows.append(
                {
                    "employee_id": entry.employee_id,
                    "name": entry.name,
                    "final_vl": final_vl,
                    "final_sl": final_sl,
                    "requested_mone": requested,
                    "target": suggestion.target,
                    "mvl": suggestion.mvl,
                    "msl": suggestion.msl,
                    "source": source,
                }
            )
        return rows

    def _request_sync(self) -> None:
        rows = self.mone_sync_rows()
        if not rows:
            self.suggestion_help.setText(
                "There are no saved MONE balances ready to sync yet."
            )
            return
        self.sync_requested.emit(rows)

    def set_sync_in_progress(self, active: bool) -> None:
        self.sync_button.setEnabled(not active and bool(self.mone_sync_rows()))
        self.sync_button.setText(
            "Syncing MONE…" if active else "Sync MONE → Google Sheet"
        )

    def _manual_values(self) -> tuple[float, float, int | None, int | None] | None:
        pieces = self.balance_input.text().replace(",", " ").split()
        if len(pieces) not in {2, 3, 4}:
            self.input_help.setText(
                "Enter VL SL, VL SL month year, or VLSL month year. Examples: 10 15 · 10 15 11 25 · 10 10 25"
            )
            return None
        try:
            if len(pieces) == 3:
                vl = sl = round(float(pieces[0]), 3)
            else:
                vl, sl = (round(float(piece), 3) for piece in pieces[:2])
                # A whole-number SL value may omit the same fractional credit
                # already entered for VL: "10.167 12" means "10.167 12.167".
                if "." in pieces[0] and "." not in pieces[1]:
                    sl = round(sl + (vl - int(vl)), 3)
        except ValueError:
            self.input_help.setText("VL and SL must be numbers. Example: 10 15 11 25 or 10 10 25")
            return None
        if vl < 0 or sl < 0:
            self.input_help.setText("VL and SL cannot be negative.")
            return None
        if len(pieces) == 2:
            return vl, sl, None, None
        try:
            month = int(pieces[-2])
            year = int(pieces[-1])
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
        self._refresh_mone_suggestion(vl, sl)
        self.input_help.setText(message)
        return True

    def save_current(self) -> None:
        self._save_current()

    def save_and_next(self) -> None:
        entry = self._current_entry()
        if entry is not None and not entry.history_completed and not self.balance_input.text().strip():
            self.skip_current()
            return
        if not self._save_current():
            return
        self._show_next()

    def _save_current(self) -> bool:
        entry = self._current_entry()
        if entry is None:
            return False
        requested = self._requested_mone_value(show_error=True)
        if requested is _INVALID_REQUEST:
            return False
        if not self._save_manual_current():
            return False
        if self._repository is None:
            self.input_help.setText("The local database is unavailable.")
            return False
        try:
            self._repository.save_mone_requested(entry.employee_id, entry.name, requested)
        except LocalRepositoryError as error:
            self.input_help.setText(str(error))
            return False
        self._refresh_mone_suggestion()
        return True

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
