from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .card_attachment_store import CardAttachmentError, CardAttachmentStore
from .card_preview import LeaveCardPreviewPage
from .local_repository import LocalRepositoryError
from .mone import (
    MONE_AUTO_LEVELS,
    MONE_MINIMUM_SL,
    MONE_MINIMUM_VL,
    parse_mone_balance_fast_entry,
    suggest_mone_credits,
)

if TYPE_CHECKING:
    from .local_repository import LocalRepository
    from .settings import AppSettings


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

    MAX_HOTKEY_PRESETS = 12

    back_requested = Signal()
    sync_requested = Signal(object)
    card_removed = Signal(str)

    def __init__(
        self,
        settings: AppSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._repository: LocalRepository | None = None
        self._entries: list[MoneBalanceEntry] = []
        self._current_index = 0
        self._card_window_first_zoom = 80
        self._card_window_balance_zoom = 80
        self._card_preview_dialogs: dict[
            QDialog, tuple[LeaveCardPreviewPage, LeaveCardPreviewPage, QLineEdit]
        ] = {}
        self._mone_hotkey_values = self._load_mone_hotkey_presets()
        self._mone_hotkey_dialog: QDialog | None = None
        self._mone_hotkey_shortcuts: list[QShortcut] = []
        self._build_ui()
        self._install_preview_shortcuts()
        self._install_mone_hotkey_shortcuts()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        back_button = QPushButton("← Leave History")
        back_button.clicked.connect(self.back_requested)
        title = QLabel("MONE Credit Balance Entry")
        title.setStyleSheet("font-size:22px;font-weight:900;color:#f8fafc")
        self.fullscreen_preview_button = QPushButton("⧉ Open Card Window")
        self.fullscreen_preview_button.setToolTip(
            "Open the current leave card in a movable two-panel window for another monitor."
        )
        self.fullscreen_preview_button.clicked.connect(self._open_fullscreen_card)
        self.remove_card_button = QPushButton("Remove Attached Card")
        self.remove_card_button.setToolTip(
            "Remove this employee's active leave-card attachment. The compiled scan archive is kept."
        )
        self.remove_card_button.setStyleSheet(
            "QPushButton{background:#991b1b;color:#fef2f2;border-color:#f87171;"
            "font-weight:900;padding:8px 12px;}QPushButton:hover{background:#b91c1c}"
        )
        # A destructive action must never become the page's Enter/default
        # button while the user is saving and moving through fast-entry rows.
        self.remove_card_button.setAutoDefault(False)
        self.remove_card_button.setDefault(False)
        self.remove_card_button.clicked.connect(self._remove_attached_card)
        self.remove_card_button.setEnabled(False)
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
        title_row.addWidget(self.fullscreen_preview_button)
        title_row.addWidget(self.remove_card_button)
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

        input_caption = QLabel("FAST MONE BALANCE · VL SL [MONTH [YEAR]]")
        input_caption.setStyleSheet("color:#67e8f9;font-size:12px;font-weight:900")
        self.balance_input = QLineEdit()
        self.balance_input.setPlaceholderText("10 15   ·   4 6 7   ·   4 6 7 25")
        self.balance_input.setToolTip(
            "Enter VL and SL directly, add a last credited month for this year, or add month and year."
        )
        self.balance_input.setMinimumHeight(56)
        self.balance_input.setStyleSheet(
            "QLineEdit{font-size:24px;font-weight:900;color:#f8fafc;background:#172554;"
            "border:2px solid #3b82f6;border-radius:9px;padding:8px 12px;}"
            "QLineEdit:read-only{color:#cbd5e1;background:#1e293b;border-color:#475569;}"
        )
        self.balance_input.returnPressed.connect(self.save_and_next)
        # In MONE entry, +/− are preview-scroll keys, not balance characters.
        self.balance_input.installEventFilter(self)
        self.balance_input.textChanged.connect(self._sync_card_window_fast_entry)
        self.input_help = QLabel(
            "10 15 saves directly. 4 6 7 uses July this year. "
            "4 6 7 25 uses July 2025. 10.167 12 copies .167 to SL."
        )
        self.input_help.setWordWrap(True)
        self.input_help.setStyleSheet("color:#cbd5e1;font-size:13px")
        form.addWidget(input_caption)
        form.addWidget(self.balance_input)
        self.mone_hotkeys_button = QPushButton("⚡ MONE Hotkeys · F1–F12")
        self.mone_hotkeys_button.setToolTip(
            "Open the editable F1–F12 text presets for Fast MONE Balance."
        )
        self.mone_hotkeys_button.setStyleSheet(
            "QPushButton{background:#164e63;color:#cffafe;border-color:#22d3ee;"
            "font-weight:900;padding:8px 12px;}QPushButton:hover{background:#155e75}"
        )
        self.mone_hotkeys_button.clicked.connect(self._open_mone_hotkey_dialog)
        form.addWidget(self.mone_hotkeys_button)
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

    def _load_mone_hotkey_presets(self) -> list[str]:
        values = list(getattr(self._settings, "mone_hotkey_presets", ["", "", ""]))
        return [str(value) for value in values[: self.MAX_HOTKEY_PRESETS]] or [""]

    def _open_mone_hotkey_dialog(self) -> None:
        if self._mone_hotkey_dialog is not None and self._mone_hotkey_dialog.isVisible():
            self._mone_hotkey_dialog.showNormal()
            self._mone_hotkey_dialog.raise_()
            self._mone_hotkey_dialog.activateWindow()
            return

        dialog = QDialog(self.window())
        dialog.setWindowTitle("MONE Hotkey Presets")
        dialog.setModal(True)
        dialog.setMinimumWidth(620)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        title = QLabel("MONE HOTKEY PRESETS")
        title.setStyleSheet("font-size:20px;font-weight:900;color:#f8fafc")
        note = QLabel(
            "Assign text to F1–F12. Pressing a key in MONE Balance replaces the Fast MONE Balance input."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#bae6fd;font-size:13px;font-weight:800")
        layout.addWidget(title)
        layout.addWidget(note)

        dialog._mone_hotkey_values = self._mone_hotkey_values.copy()
        dialog._mone_hotkey_rows = QVBoxLayout()
        dialog._mone_hotkey_rows.setSpacing(6)
        layout.addLayout(dialog._mone_hotkey_rows)

        footer = QHBoxLayout()
        dialog._mone_hotkey_add_button = QPushButton()
        dialog._mone_hotkey_add_button.clicked.connect(
            lambda: self._add_mone_hotkey_dialog_row(dialog)
        )
        save_button = QPushButton("Save & Close")
        save_button.setStyleSheet(
            "QPushButton{background:#2563eb;color:white;border-color:#3b82f6;"
            "font-weight:900;padding:8px 12px;}QPushButton:hover{background:#1d4ed8}"
        )
        save_button.clicked.connect(lambda: self._save_and_close_mone_hotkeys(dialog))
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        footer.addWidget(dialog._mone_hotkey_add_button)
        footer.addStretch(1)
        footer.addWidget(save_button)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self._render_mone_hotkey_dialog_rows(dialog)
        dialog.finished.connect(self._forget_mone_hotkey_dialog)
        self._mone_hotkey_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _forget_mone_hotkey_dialog(self, _result: int) -> None:
        self._mone_hotkey_dialog = None

    def _clear_mone_hotkey_dialog_rows(self, dialog: QDialog) -> None:
        while dialog._mone_hotkey_rows.count():
            item = dialog._mone_hotkey_rows.takeAt(0)
            nested = item.layout()
            if nested is None:
                continue
            while nested.count():
                child = nested.takeAt(0).widget()
                if child is not None:
                    child.deleteLater()

    def _render_mone_hotkey_dialog_rows(self, dialog: QDialog) -> None:
        self._clear_mone_hotkey_dialog_rows(dialog)
        for index, value in enumerate(dialog._mone_hotkey_values):
            row = QHBoxLayout()
            key_label = QLabel(f"F{index + 1}")
            key_label.setMinimumWidth(38)
            key_label.setStyleSheet("color:#fbbf24;font-size:16px;font-weight:900")
            edit = QLineEdit(value)
            edit.setPlaceholderText("Example: 4 6 7")
            edit.setMinimumHeight(34)
            edit.setStyleSheet("font-size:16px;font-weight:800")
            edit.textChanged.connect(
                lambda text, row_index=index: self._set_mone_hotkey_dialog_value(
                    dialog, row_index, text
                )
            )
            remove_button = QPushButton("×")
            remove_button.setFixedWidth(34)
            remove_button.setToolTip("Remove this hotkey and renumber the following rows.")
            remove_button.setAutoDefault(False)
            remove_button.setDefault(False)
            remove_button.clicked.connect(
                lambda _checked=False, row_index=index: self._remove_mone_hotkey_dialog_row(
                    dialog, row_index
                )
            )
            row.addWidget(key_label)
            row.addWidget(edit, 1)
            row.addWidget(remove_button)
            dialog._mone_hotkey_rows.addLayout(row)
        next_key = len(dialog._mone_hotkey_values) + 1
        dialog._mone_hotkey_add_button.setEnabled(next_key <= self.MAX_HOTKEY_PRESETS)
        dialog._mone_hotkey_add_button.setText(
            f"+ Add F{next_key}" if next_key <= self.MAX_HOTKEY_PRESETS else "F1–F12 Added"
        )

    @staticmethod
    def _set_mone_hotkey_dialog_value(
        dialog: QDialog, index: int, value: str
    ) -> None:
        if 0 <= index < len(dialog._mone_hotkey_values):
            dialog._mone_hotkey_values[index] = value

    def _add_mone_hotkey_dialog_row(self, dialog: QDialog) -> None:
        if len(dialog._mone_hotkey_values) >= self.MAX_HOTKEY_PRESETS:
            return
        dialog._mone_hotkey_values.append("")
        self._render_mone_hotkey_dialog_rows(dialog)

    def _remove_mone_hotkey_dialog_row(self, dialog: QDialog, index: int) -> None:
        if not 0 <= index < len(dialog._mone_hotkey_values):
            return
        dialog._mone_hotkey_values.pop(index)
        if not dialog._mone_hotkey_values:
            dialog._mone_hotkey_values = [""]
        self._render_mone_hotkey_dialog_rows(dialog)

    def _save_and_close_mone_hotkeys(self, dialog: QDialog) -> None:
        self._mone_hotkey_values = [
            str(value).strip() for value in dialog._mone_hotkey_values
        ]
        if self._settings is not None:
            self._settings.mone_hotkey_presets = self._mone_hotkey_values.copy()
            try:
                self._settings.save()
            except OSError as error:
                QMessageBox.warning(dialog, "MONE Hotkeys", f"Could not save MONE hotkeys: {error}")
                return
        self.input_help.setText("MONE hotkeys saved. Press F1–F12 to load a preset.")
        dialog.accept()

    def _install_mone_hotkey_shortcuts(self) -> None:
        for index in range(self.MAX_HOTKEY_PRESETS):
            shortcut = QShortcut(QKeySequence(f"F{index + 1}"), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(
                lambda preset_index=index: self._apply_mone_hotkey(preset_index)
            )
            self._mone_hotkey_shortcuts.append(shortcut)

    def _apply_mone_hotkey(self, index: int) -> None:
        if not self.isVisible() or not 0 <= index < len(self._mone_hotkey_values):
            return
        preset = self._mone_hotkey_values[index].strip()
        if not preset:
            self.input_help.setText(f"F{index + 1} has no saved MONE preset yet.")
            return
        if self.balance_input.isReadOnly():
            self.input_help.setText("Automatic computed balance cannot be replaced.")
            return
        self.balance_input.setText(preset)
        self.balance_input.setFocus()
        self.balance_input.selectAll()
        self.input_help.setText(f"F{index + 1} preset loaded · press Enter to save and move next.")

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # type: ignore[override]
        if (
            watched is self.balance_input
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Minus, Qt.Key.Key_Plus)
        ):
            self._scroll_continuous_preview(
                -1 if event.key() == Qt.Key.Key_Minus else 1,
                gentle=True,
            )
            return True
        return super().eventFilter(watched, event)

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

    def _scroll_continuous_preview(
        self, direction: int, *, gentle: bool = False
    ) -> None:
        """Scroll the lower continuous preview by a page or a small key step."""
        self._scroll_preview_widget(
            self.last_page_preview,
            direction,
            gentle=gentle,
        )

    @staticmethod
    def _scroll_preview_widget(
        preview: LeaveCardPreviewPage, direction: int, *, gentle: bool = False
    ) -> None:
        """Scroll a displayed preview by either a page or a small key step."""
        bar = preview.scroll.verticalScrollBar()
        step = max(48, bar.singleStep() * 4) if gentle else max(80, bar.pageStep())
        bar.setValue(bar.value() + (step if direction > 0 else -step))

    def _open_fullscreen_card(self) -> None:
        entry = self._current_entry()
        if entry is None or not self.last_page_preview._source_path:
            self.input_help.setText(
                "No leave card is attached for this employee yet."
            )
            return
        dialog = QDialog(self.window())
        dialog.setWindowTitle(f"MONE Leave Card · {entry.name}")
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog._mone_fullscreen_locked = False
        dialog.setMinimumSize(900, 700)
        dialog.resize(1400, 920)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        title = QLabel("MONE LEAVE CARD · NAME AND BALANCE CHECK")
        title.setStyleSheet("font-size:18px;font-weight:900;color:#f8fafc")
        fast_entry_caption = QLabel("FAST MONE BALANCE")
        fast_entry_caption.setStyleSheet(
            "color:#67e8f9;font-size:11px;font-weight:900"
        )
        fast_entry_input = QLineEdit(self.balance_input.text())
        fast_entry_input.setPlaceholderText("VL SL [MONTH [YEAR]]")
        fast_entry_input.setMinimumWidth(300)
        fast_entry_input.setMinimumHeight(36)
        fast_entry_input.setStyleSheet(
            "QLineEdit{font-size:18px;font-weight:900;color:#f8fafc;background:#172554;"
            "border:2px solid #3b82f6;border-radius:7px;padding:4px 9px;}"
            "QLineEdit:read-only{color:#cbd5e1;background:#1e293b;border-color:#475569;}"
        )
        fast_entry_input.setReadOnly(self.balance_input.isReadOnly())
        fast_entry_input.textChanged.connect(self.balance_input.setText)
        fast_entry_input.returnPressed.connect(self.save_and_next)
        remove_card_button = QPushButton("Remove Attached Card")
        remove_card_button.setToolTip(
            "Remove the active leave-card attachment. The compiled scan archive is kept."
        )
        remove_card_button.setStyleSheet(
            "QPushButton{background:#991b1b;color:#fef2f2;border-color:#f87171;"
            "font-weight:900;padding:7px 10px;}QPushButton:hover{background:#b91c1c}"
        )
        # QDialog promotes a focused button to its default Enter action unless
        # this is explicitly disabled. Removal should require a mouse click.
        remove_card_button.setAutoDefault(False)
        remove_card_button.setDefault(False)
        remove_card_button.clicked.connect(self._remove_attached_card)
        fullscreen_button = QPushButton("⛶ Full Screen")
        close_button = QPushButton("Close Window")
        close_button.clicked.connect(dialog.close)

        def toggle_fullscreen() -> None:
            if dialog._mone_fullscreen_locked:
                dialog._mone_fullscreen_locked = False
                dialog.showNormal()
                fullscreen_button.setText("⛶ Full Screen")
            else:
                dialog._mone_fullscreen_locked = True
                dialog.showFullScreen()
                fullscreen_button.setText("Exit Full Screen")

        fullscreen_button.clicked.connect(toggle_fullscreen)
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(fast_entry_caption)
        heading.addWidget(fast_entry_input)
        heading.addWidget(remove_card_button)
        heading.addWidget(fullscreen_button)
        heading.addWidget(close_button)
        layout.addLayout(heading)

        preview_splitter = QSplitter(Qt.Orientation.Vertical)
        preview_splitter.setChildrenCollapsible(False)
        preview_splitter.setHandleWidth(6)
        first_preview = LeaveCardPreviewPage(embedded=True)
        first_preview.set_reference_mode("LEAVE CARD · FIRST PAGE · NAME CHECK")
        first_preview.set_employee_context(entry.employee_id, entry.name)
        first_preview.show_first_page_top()
        first_preview.zoom_slider.setValue(self._card_window_first_zoom)
        balance_preview = LeaveCardPreviewPage(embedded=True)
        balance_preview.set_reference_mode(
            "LEAVE CARD · CONTINUOUS PAGES · BALANCE CHECK"
        )
        balance_preview.set_employee_context(entry.employee_id, entry.name)
        balance_preview.show_continuous_pages()
        balance_preview.zoom_slider.setValue(self._card_window_balance_zoom)
        first_preview.zoom_slider.valueChanged.connect(self._remember_card_window_first_zoom)
        balance_preview.zoom_slider.valueChanged.connect(
            self._remember_card_window_balance_zoom
        )
        preview_splitter.addWidget(first_preview)
        preview_splitter.addWidget(balance_preview)
        preview_splitter.setStretchFactor(0, 1)
        preview_splitter.setStretchFactor(1, 1)
        preview_splitter.setSizes([440, 440])
        layout.addWidget(preview_splitter, 1)

        preview_page_up = QShortcut(QKeySequence("PgUp"), dialog)
        preview_page_down = QShortcut(QKeySequence("PgDown"), dialog)
        for shortcut in (preview_page_up, preview_page_down):
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        preview_page_up.activated.connect(
            lambda: self._scroll_preview_widget(balance_preview, -1)
        )
        preview_page_down.activated.connect(
            lambda: self._scroll_preview_widget(balance_preview, 1)
        )
        dialog._mone_preview_shortcuts = (preview_page_up, preview_page_down)

        self._card_preview_dialogs[dialog] = (
            first_preview,
            balance_preview,
            fast_entry_input,
        )

        def forget_dialog(_result: int) -> None:
            self._card_preview_dialogs.pop(dialog, None)

        dialog.finished.connect(forget_dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _update_open_card_preview_windows(self, entry: MoneBalanceEntry) -> None:
        """Keep each movable card window on the active MONE employee."""
        for dialog, (first_preview, balance_preview, fast_entry_input) in tuple(
            self._card_preview_dialogs.items()
        ):
            if not dialog.isVisible():
                continue
            first_zoom = first_preview.zoom_slider.value()
            balance_zoom = balance_preview.zoom_slider.value()
            dialog.setWindowTitle(f"MONE Leave Card · {entry.name}")
            first_preview.set_employee_context(entry.employee_id, entry.name)
            first_preview.show_first_page_top()
            balance_preview.set_employee_context(entry.employee_id, entry.name)
            balance_preview.show_continuous_pages()
            first_preview.zoom_slider.setValue(first_zoom)
            balance_preview.zoom_slider.setValue(balance_zoom)
            fast_entry_input.blockSignals(True)
            fast_entry_input.setText(self.balance_input.text())
            fast_entry_input.setReadOnly(self.balance_input.isReadOnly())
            fast_entry_input.blockSignals(False)
            if getattr(dialog, "_mone_fullscreen_locked", False):
                # Let the refreshed card layout finish, then force the window
                # back to the user's selected full-screen state.
                QTimer.singleShot(
                    0,
                    lambda: dialog.showFullScreen() if dialog.isVisible() else None,
                )

    def _remember_card_window_first_zoom(self, value: int) -> None:
        self._card_window_first_zoom = value

    def _remember_card_window_balance_zoom(self, value: int) -> None:
        self._card_window_balance_zoom = value

    def _sync_card_window_fast_entry(self, text: str) -> None:
        """Mirror the main Fast MONE Balance text into open card windows."""
        for dialog, (_first, _balance, fast_entry_input) in tuple(
            self._card_preview_dialogs.items()
        ):
            if not dialog.isVisible() or fast_entry_input.text() == text:
                continue
            fast_entry_input.blockSignals(True)
            fast_entry_input.setText(text)
            fast_entry_input.blockSignals(False)

    def _set_remove_card_button_state(self, entry: MoneBalanceEntry | None) -> None:
        has_card = bool(
            entry
            and self.first_page_preview._attached_employee_id == entry.employee_id
            and self.first_page_preview._source_path
        )
        self.remove_card_button.setEnabled(has_card)
        self.fullscreen_preview_button.setEnabled(has_card)

    def _remove_attached_card(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        has_card = (
            self.first_page_preview._attached_employee_id == entry.employee_id
            and bool(self.first_page_preview._source_path)
        )
        if not has_card:
            self.input_help.setText("No leave card is attached for this employee yet.")
            self._set_remove_card_button_state(entry)
            return

        answer = QMessageBox.question(
            self.window(),
            "Remove attached leave card?",
            f"Remove the active leave-card attachment for {entry.name}?\n\n"
            "The employee-folder Leave Card file and its app link will be removed. "
            "The compiled scanned-card archive and scanner Processed file will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = CardAttachmentStore().remove(entry.employee_id)
        except CardAttachmentError as error:
            QMessageBox.warning(self.window(), "Could not remove leave card", str(error))
            return
        if not removed:
            self.input_help.setText("There is no active attached leave card to remove.")
            self._set_remove_card_button_state(entry)
            return

        self.first_page_preview.reload_attached_card()
        self.first_page_preview.show_first_page_top()
        self.last_page_preview.reload_attached_card()
        self.last_page_preview.show_continuous_pages()
        for dialog, (first_preview, balance_preview, _fast_entry) in tuple(
            self._card_preview_dialogs.items()
        ):
            if not dialog.isVisible():
                continue
            first_preview.reload_attached_card()
            first_preview.show_first_page_top()
            balance_preview.reload_attached_card()
            balance_preview.show_continuous_pages()
        self._set_remove_card_button_state(entry)
        self.card_removed.emit(entry.employee_id)
        self.input_help.setText(
            "Attached leave card removed. The compiled scan archive was kept."
        )

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
        last_employee_id = repository.mone_balance_last_employee_id()
        if last_employee_id:
            self._current_index = next(
                (
                    index
                    for index, entry in enumerate(self._entries)
                    if entry.employee_id == last_employee_id
                ),
                0,
            )
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
            self._set_remove_card_button_state(None)
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
        if self._repository is not None:
            try:
                self._repository.save_mone_balance_last_employee(entry.employee_id)
            except LocalRepositoryError:
                # Progress should never block a normal MONE balance entry.
                pass
        self.first_page_preview.set_employee_context(entry.employee_id, entry.name)
        self.first_page_preview.show_first_page_top()
        self.last_page_preview.set_employee_context(entry.employee_id, entry.name)
        self.last_page_preview.show_continuous_pages()
        self._set_remove_card_button_state(entry)
        self._update_open_card_preview_windows(entry)
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
        try:
            return parse_mone_balance_fast_entry(self.balance_input.text())
        except ValueError as error:
            self.input_help.setText(str(error))
            return None

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
