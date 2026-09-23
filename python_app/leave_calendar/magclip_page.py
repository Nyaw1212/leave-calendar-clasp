from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .magclip_engine import (
    CREDIT_FIELDS,
    CREDIT_SEQUENCE,
    DEFAULT_SEQUENCE,
    MANUAL_LEAVE_FIELDS,
    MANUAL_LEAVE_SEQUENCE,
    MANDATORY_LEAVE_FIELDS,
    MONE_FIELDS,
    ClipboardEntryEngine,
    CreditEntryEngine,
    LeaveEntryEngine,
    Magazine,
    SEQUENCE_PRESETS,
    action_consumes_round,
    credit_entry_rounds,
    insert_sequence_slot,
    leave_record_rounds,
    mandatory_leave_rounds,
    mone_record_rounds,
    normalize_manual_leave_clipboard,
    parse_clipboard_rows,
    parse_sequence_commands,
)
from .models import CreditEntry, Employee, LeaveRecord, MandatoryLeaveRecord
from .sequence_store import SequenceStore


LOGGER = logging.getLogger(__name__)


class MagclipBridge(QObject):
    refresh = Signal()
    status = Signal(str)
    guided_transition_complete = Signal()
    guided_transition_finished = Signal()
    guided_stage_auto_requested = Signal()
    guided_transition_auto_complete = Signal()


class KeyboardContext:
    def __init__(self, abort_event: threading.Event) -> None:
        self.abort_event = abort_event

    @staticmethod
    def _modules() -> tuple[Any, Any]:
        import keyboard
        import pyperclip

        return keyboard, pyperclip

    def paste_text(self, value: str) -> None:
        keyboard, pyperclip = self._modules()
        pyperclip.copy(value)
        keyboard.send("ctrl+v")

    def type_text(self, value: str) -> None:
        keyboard, _pyperclip = self._modules()
        keyboard.write(value)

    def press_tab(self) -> None:
        keyboard, _pyperclip = self._modules()
        keyboard.send("tab")

    def press_enter(self) -> None:
        keyboard, _pyperclip = self._modules()
        keyboard.send("enter")

    def press_space(self) -> None:
        keyboard, _pyperclip = self._modules()
        keyboard.send("space")

    def press_escape(self) -> None:
        keyboard, _pyperclip = self._modules()
        keyboard.send("esc")

    def press_arrow_up(self) -> None:
        keyboard, _pyperclip = self._modules()
        keyboard.send("up")

    def press_arrow_down(self) -> None:
        keyboard, _pyperclip = self._modules()
        keyboard.send("down")

    def should_abort(self) -> bool:
        return self.abort_event.is_set()


class MagclipModePage(QWidget):
    back_requested = Signal()
    guided_flow_next_requested = Signal()
    guided_flow_auto_next_requested = Signal()
    hotkey_fire_requested = Signal()
    hotkey_stop_requested = Signal()
    hotkey_reload_round_requested = Signal()
    hotkey_abort_requested = Signal()
    hotkey_reload_clip_requested = Signal()
    SEQUENCE_SLOTS = 40
    SEQUENCE_COLUMNS = 4
    TRANSITION_SLOTS = 6
    TRANSITION_ACTIONS = (
        "NONE",
        "TAB",
        "ENTER",
        "ENTER 400MS",
        "ENTER 700MS",
        "SPACE",
        "ESC",
        "ARROW UP",
        "ARROW DOWN",
        "TYPE P",
        "TYPE A",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.magazine = Magazine()
        self.engine = LeaveEntryEngine(delay_ms=120)
        self.bridge = MagclipBridge()
        self.abort_event = threading.Event()
        self.context = KeyboardContext(self.abort_event)
        self.running = False
        self.repeat_enabled = False
        self.repeat_delay_ms = 700
        self.repeat_stop_event = threading.Event()
        self.content_mode = "leave"
        self.rounds_per_fire: int | None = None
        self.custom_sequence: list[str] = list(DEFAULT_SEQUENCE)
        self.hotkey_handles: list[Any] = []
        self.f1_hook_handle: Any | None = None
        self.history_rows: list[list[str]] = []
        self.history_record_ids: list[str] = []
        self.name_overrides: dict[str, str] = {}
        self.employee_id = ""
        self.sequence_store = SequenceStore()
        self.saved_sequences = self.sequence_store.load()
        self.stage_transitions = self.sequence_store.load_stage_transitions()
        self.stage_delays = self.sequence_store.load_stage_delays()
        self.guided_flow_stage: str | None = None
        self._last_round_highlight: tuple[int, int] | None = None
        self._build_ui()
        self.bridge.refresh.connect(self.refresh_view)
        self.bridge.status.connect(self.status_label.setText)
        self.bridge.guided_transition_complete.connect(
            self.guided_flow_next_requested.emit
        )
        self.bridge.guided_transition_auto_complete.connect(
            self.guided_flow_auto_next_requested.emit
        )
        self.bridge.guided_transition_finished.connect(
            lambda: self.flow_next_button.setEnabled(True)
        )
        self.bridge.guided_stage_auto_requested.connect(
            lambda: self.run_guided_flow_next(auto_fire=True)
        )
        self.hotkey_fire_requested.connect(self.fire_current_clip)
        self.hotkey_stop_requested.connect(self.stop_repeat)
        self.hotkey_reload_round_requested.connect(self.reload_last_round)
        self.hotkey_abort_requested.connect(self.abort)
        self.hotkey_reload_clip_requested.connect(self.reload_last_clip)
        self._install_local_hotkeys()
        self.refresh_view()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        back_button = QPushButton("← Calendar Mode")
        back_button.clicked.connect(lambda: self.back_requested.emit())
        title = QLabel("MAGCLIP Mode")
        title.setStyleSheet("font-size:21px;font-weight:800;color:#f8fafc")
        self.employee_label = QLabel("No employee selected")
        self.employee_label.setStyleSheet("color:#94a3b8;font-weight:700")
        self.hotkey_state = QLabel("HOTKEYS OFF")
        self.flow_next_button = QPushButton()
        self.flow_next_button.setStyleSheet(
            "QPushButton{background:#16a34a;color:white;border:0;border-radius:7px;"
            "padding:8px 12px;font-weight:900}"
            "QPushButton:hover{background:#15803d}"
        )
        self.flow_next_button.clicked.connect(
            lambda: self.run_guided_flow_next(auto_fire=True)
        )
        self.flow_next_button.hide()
        self.hotkey_state.setStyleSheet(
            "background:#3f1d24;color:#fecaca;border-radius:8px;padding:6px 10px;"
            "font-weight:800"
        )
        header.addWidget(back_button)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.flow_next_button)
        header.addWidget(self.hotkey_state)
        root.addLayout(header)
        self.employee_label.setWordWrap(True)
        root.addWidget(self.employee_label)

        # Keep MAGCLIP inside the visible display: controls scroll inside the
        # left pane instead of increasing the application's minimum window size.
        monitor_panel = self._build_monitor_panel()
        monitor_panel.setMinimumWidth(0)
        monitor_panel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        monitor_scroll = QScrollArea()
        monitor_scroll.setWidgetResizable(True)
        monitor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        monitor_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        monitor_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        monitor_scroll.setWidget(monitor_panel)
        monitor_scroll.setMinimumWidth(0)
        monitor_scroll.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )

        history_panel = self._build_history_panel()
        history_panel.setMinimumWidth(0)
        history_panel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        splitter.addWidget(monitor_scroll)
        splitter.addWidget(history_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 360])
        root.addWidget(splitter, 1)

    def set_guided_flow(self, stage: str | None) -> None:
        labels = {
            "credits": "Next · MONE →",
            "mone": "Next · Mandatory →",
            "mandatory": "Next · Leave →",
            "leave": "Finish Flow",
        }
        self.guided_flow_stage = stage
        label = labels.get(stage or "")
        self.flow_next_button.setVisible(bool(label))
        self.flow_next_button.setText(label)
        if hasattr(self, "stage_delay_panel"):
            self.stage_delay_panel.setVisible(bool(stage))
            self.stage_auto_fire_check.setVisible(bool(stage))
            if stage:
                self._load_stage_delay(stage)
        if hasattr(self, "stage_transition_editor"):
            editable_transition = stage in {"credits", "mone", "mandatory"}
            self.stage_transition_editor.setVisible(editable_transition)
            if editable_transition:
                self._load_stage_transition(stage)

    def _load_stage_delay(self, stage: str) -> None:
        delay = self.stage_delays.get(stage, 500)
        self.stage_delay_title.setText(
            f"STAGE START DELAY · {stage.title()} clips"
        )
        self.stage_delay_spin.blockSignals(True)
        self.stage_delay_spin.setValue(delay)
        self.stage_delay_spin.blockSignals(False)

    def set_stage_delay(self, delay: int) -> None:
        stage = self.guided_flow_stage
        if not stage:
            return
        try:
            saved_delay = self.sequence_store.save_stage_delay(stage, delay)
        except (OSError, ValueError) as error:
            self.bridge.status.emit(f"STAGE DELAY · {error}")
            return
        self.stage_delays[stage] = saved_delay
        self.bridge.status.emit(
            f"STAGE START DELAY SAVED · {stage.title()} · {saved_delay} ms"
        )

    def guided_stage_start_delay(self) -> int:
        """Return the saved wait before the current guided stage first fires."""
        stage = self.guided_flow_stage or ""
        return int(self.stage_delays.get(stage, 500))

    def guided_stage_auto_fire_enabled(self) -> bool:
        """Return whether Full MAGCLIP should fire F1 as a stage is shown."""
        return self.stage_auto_fire_check.isChecked()

    def _transition_label(self, stage: str) -> str:
        return {
            "credits": "Credits → MONE",
            "mone": "MONE → Mandatory",
            "mandatory": "Mandatory → Leave",
        }.get(stage, "Next Stage")

    def _load_stage_transition(self, stage: str) -> None:
        commands = self.stage_transitions.get(stage, ())
        for index, box in enumerate(self.stage_transition_boxes):
            box.blockSignals(True)
            box.setCurrentText(commands[index] if index < len(commands) else "NONE")
            box.blockSignals(False)
        self.stage_transition_title.setText(
            f"NEXT STAGE MACRO · {self._transition_label(stage)} · up to 6 keyboard actions"
        )

    def save_stage_transition(self) -> None:
        stage = self.guided_flow_stage
        if stage not in {"credits", "mone", "mandatory"}:
            return
        actions = [
            box.currentText()
            for box in self.stage_transition_boxes
            if box.currentText() != "NONE"
        ]
        try:
            saved = self.sequence_store.save_stage_transition(stage, actions)
        except (OSError, ValueError) as error:
            self.bridge.status.emit(f"NEXT STAGE MACRO · {error}")
            return
        self.stage_transitions[stage] = saved
        self.bridge.status.emit(
            f"NEXT STAGE MACRO SAVED · {self._transition_label(stage)} · "
            f"{len(saved)} ACTION(S)"
        )

    def run_guided_flow_next(self, auto_fire: bool = False) -> None:
        stage = self.guided_flow_stage
        if self.running:
            return
        if stage not in {"credits", "mone", "mandatory"}:
            (
                self.guided_flow_auto_next_requested
                if auto_fire
                else self.guided_flow_next_requested
            ).emit()
            return
        actions = [
            box.currentText()
            for box in self.stage_transition_boxes
            if box.currentText() != "NONE"
        ]
        if not actions:
            (
                self.guided_flow_auto_next_requested
                if auto_fire
                else self.guided_flow_next_requested
            ).emit()
            return
        self.running = True
        self.abort_event.clear()
        self.flow_next_button.setEnabled(False)
        self.bridge.status.emit(
            f"NEXT STAGE MACRO · {self._transition_label(stage)} · RUNNING"
        )

        def worker() -> None:
            try:
                result = self.engine.run_navigation_sequence(self.context, actions)
                if result.completed:
                    self.bridge.status.emit(
                        f"NEXT STAGE MACRO · {self._transition_label(stage)} · DONE"
                    )
                    if auto_fire:
                        self.bridge.guided_transition_auto_complete.emit()
                    else:
                        self.bridge.guided_transition_complete.emit()
                elif result.aborted:
                    self.bridge.status.emit("NEXT STAGE MACRO · ABORTED")
                else:
                    self.bridge.status.emit(
                        "NEXT STAGE MACRO ERROR · use keyboard-only actions"
                    )
            except Exception as error:
                LOGGER.exception("Guided MAGCLIP transition failed")
                self.bridge.status.emit(f"NEXT STAGE MACRO ERROR · {error}")
            finally:
                self.running = False
                self.bridge.guided_transition_finished.emit()
                self.bridge.refresh.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _build_history_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 4)
        self.history_caption = QLabel(
            "LEAVE HISTORY CLIPS · Double-click NAME to edit · STATUS: A / C / D"
        )
        self.history_caption.setStyleSheet("color:#67e8f9;font-weight:800")
        self.history_table = QTreeWidget()
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setHeaderLabels(
            ["NAME", "TYPE", "START", "END", "VL", "SL", "LWOP", "STATUS"]
        )
        table_header = self.history_table.header()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 8):
            table_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.setRootIsDecorated(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setMinimumWidth(0)
        self.history_table.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        self.history_table.setStyleSheet(
            "QTreeWidget{font-size:14px}"
            "QHeaderView::section{font-size:13px;font-weight:900;padding:7px 5px}"
            "QTreeWidget::item{padding:4px 3px}"
            "QTreeWidget::item:selected{"
            "background-color:rgba(250,204,21,204);"
            "color:#111827;"
            "border-top:1px solid #fde047;"
            "border-bottom:1px solid #fde047;"
            "font-weight:800}"
        )
        self.history_table.itemDoubleClicked.connect(self._history_item_double_clicked)
        self.history_table.itemChanged.connect(self._history_item_changed)
        layout.addWidget(self.history_caption)
        layout.addWidget(self.history_table, 1)
        return panel

    def _build_monitor_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 6, 0, 0)

        self.status_label = QLabel("READY")
        self.status_label.setStyleSheet(
            "background:#102a33;color:#67e8f9;border:1px solid #155e75;"
            "border-radius:8px;padding:7px 10px;font-weight:900"
        )
        self.progress_label = QLabel("No leave-history clips loaded")
        self.progress_label.setStyleSheet("color:#94a3b8;font-weight:700")
        self.load_selected_button = QPushButton("Load Selected Clip from Round 1")
        self.load_selected_button.clicked.connect(self.load_selected_clip)
        self.load_clipboard_button = QPushButton("Load Clipboard Data")
        self.load_clipboard_button.clicked.connect(self.load_clipboard_data)
        clip_actions = QHBoxLayout()
        clip_actions.addWidget(self.load_selected_button, 1)
        clip_actions.addWidget(self.load_clipboard_button)

        round_grid = QGridLayout()
        current_title = QLabel("CURRENT ROUND")
        next_title = QLabel("NEXT ROUND")
        current_title.setStyleSheet("color:#60a5fa;font-weight:800")
        next_title.setStyleSheet("color:#a78bfa;font-weight:800")
        self.current_label = QLabel("—")
        self.next_label = QLabel("—")
        for label in (self.current_label, self.next_label):
            label.setWordWrap(True)
            label.setMinimumHeight(56)
            label.setStyleSheet(
                "background:#1b222d;color:#f8fafc;border:1px solid #3b4656;"
                "border-radius:8px;padding:9px;font-size:15px;font-weight:800"
            )
        round_grid.addWidget(current_title, 0, 0)
        round_grid.addWidget(next_title, 0, 1)
        round_grid.addWidget(self.current_label, 1, 0)
        round_grid.addWidget(self.next_label, 1, 1)

        settings = QHBoxLayout()
        settings.addWidget(QLabel("Rounds per F1:"))
        self.fire_mode = QComboBox()
        self.fire_mode.addItems(["1", "2", "3", "ALL"])
        self.fire_mode.setCurrentText("ALL")
        self.fire_mode.currentTextChanged.connect(self.set_rounds_per_fire)
        settings.addWidget(self.fire_mode)
        settings.addSpacing(18)
        settings.addWidget(QLabel("Action Delay:"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(25, 2000)
        self.delay_spin.setSingleStep(25)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setValue(self.engine.delay_ms)
        self.delay_spin.valueChanged.connect(self.set_delay_ms)
        settings.addWidget(self.delay_spin)
        self.repeat_check = QCheckBox("Repeat clips")
        self.repeat_check.toggled.connect(self.set_repeat_enabled)
        settings.addSpacing(18)
        settings.addWidget(self.repeat_check)
        self.repeat_delay_spin = QSpinBox()
        self.repeat_delay_spin.setRange(100, 10000)
        self.repeat_delay_spin.setSingleStep(100)
        self.repeat_delay_spin.setSuffix(" ms")
        self.repeat_delay_spin.setValue(self.repeat_delay_ms)
        self.repeat_delay_spin.valueChanged.connect(self.set_repeat_delay_ms)
        settings.addWidget(self.repeat_delay_spin)
        settings.addStretch(1)

        sequence_caption = QLabel(
            "CUSTOM SEQUENCE · Up to 40 actions · Right-click a slot to insert"
        )
        sequence_caption.setStyleSheet("color:#cbd5e1;font-weight:800")
        sequence_header = QHBoxLayout()
        sequence_header.addWidget(sequence_caption)
        sequence_header.addStretch(1)
        self.sequence_toggle = QPushButton("Show More")
        self.sequence_toggle.setCheckable(True)
        self.sequence_toggle.setChecked(False)
        self.sequence_toggle.setMinimumWidth(100)
        self.sequence_toggle.clicked.connect(self.toggle_sequence_editor)
        self.default_preset_button = QPushButton("Set as Default")
        self.default_preset_button.setToolTip(
            "Choose and remember a named sequence preset for regular Leave MAGCLIP."
        )
        self.default_preset_button.clicked.connect(self.toggle_default_preset_picker)
        self.default_preset_picker = QComboBox()
        self.default_preset_picker.setMinimumWidth(180)
        self.default_preset_picker.setToolTip(
            "Choose a preset to save and apply as the default regular Leave MAGCLIP sequence."
        )
        self.default_preset_picker.activated.connect(self.set_default_preset_from_picker)
        self.default_preset_picker.hide()
        sequence_header.addWidget(self.default_preset_button)
        sequence_header.addWidget(self.default_preset_picker)
        sequence_header.addWidget(self.sequence_toggle)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Sequence preset:"))
        self.sequence_preset = QComboBox()
        self.sequence_preset.addItem("CUSTOM", None)
        for name, sequence in SEQUENCE_PRESETS.items():
            self.sequence_preset.addItem(name, sequence)
        for name, sequence in sorted(self.saved_sequences.items()):
            if name not in SEQUENCE_PRESETS and name != "CUSTOM":
                self.sequence_preset.addItem(name, sequence)
        self.sequence_preset.currentIndexChanged.connect(self._preset_changed)
        self._refresh_default_preset_picker()
        preset_row.addWidget(self.sequence_preset, 1)
        import_commands = QPushButton("Import Commands")
        import_commands.setToolTip(
            "Read commands from the clipboard and populate sequence slots 1–40"
        )
        import_commands.clicked.connect(self.import_clipboard_commands)
        preset_row.addWidget(import_commands)
        save_sequence = QPushButton("Save Sequence")
        save_sequence.clicked.connect(self.save_current_sequence)
        preset_row.addWidget(save_sequence)
        delete_sequence = QPushButton("Delete Saved")
        delete_sequence.clicked.connect(self.delete_saved_sequence)
        preset_row.addWidget(delete_sequence)
        sequence_grid = QGridLayout()
        self.sequence_boxes: list[QComboBox] = []
        for index in range(self.SEQUENCE_SLOTS):
            label = QLabel(f"{index + 1:02d}")
            box = QComboBox()
            box.addItems(
                [
                    "NONE",
                    "PASTE",
                    "PASTE 400MS",
                    "PASTE 700MS",
                    "TYPE",
                    "TYPE P",
                    "TYPE A",
                    "TYPE A 400MS",
                    "TYPE STATUS",
                    "TAB",
                    "ENTER",
                    "ENTER 400MS",
                    "ENTER 700MS",
                    "SPACE",
                    "ESC",
                    "ARROW UP",
                    "ARROW DOWN",
                ]
            )
            box.setCurrentText(
                DEFAULT_SEQUENCE[index] if index < len(DEFAULT_SEQUENCE) else "NONE"
            )
            box.currentTextChanged.connect(self._sequence_changed)
            box.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            box.customContextMenuRequested.connect(
                lambda position, slot=index, editor=box: self._open_slot_menu(
                    slot,
                    editor.mapToGlobal(position),
                )
            )
            self.sequence_boxes.append(box)
            row = index // self.SEQUENCE_COLUMNS
            column = (index % self.SEQUENCE_COLUMNS) * 2
            sequence_grid.addWidget(label, row, column)
            sequence_grid.addWidget(box, row, column + 1)

        # Apply the remembered preset only after every editable sequence slot
        # exists; selecting a preset fills those slots.
        default_sequence = self.sequence_store.load_default()
        if not default_sequence or not self.select_sequence(default_sequence):
            self.select_sequence("LEAVE ENTRY")

        self.sequence_editor = QWidget()
        sequence_editor_layout = QVBoxLayout(self.sequence_editor)
        sequence_editor_layout.setContentsMargins(0, 0, 0, 0)
        sequence_editor_layout.setSpacing(5)
        sequence_editor_layout.addLayout(preset_row)
        sequence_editor_layout.addLayout(sequence_grid)
        self.sequence_editor.hide()

        self.stage_delay_panel = QFrame()
        stage_delay_layout = QHBoxLayout(self.stage_delay_panel)
        stage_delay_layout.setContentsMargins(0, 0, 0, 0)
        self.stage_delay_title = QLabel("STAGE START DELAY")
        self.stage_delay_title.setStyleSheet("color:#a78bfa;font-weight:900")
        self.stage_delay_spin = QSpinBox()
        self.stage_delay_spin.setRange(25, 2000)
        self.stage_delay_spin.setSingleStep(25)
        self.stage_delay_spin.setSuffix(" ms")
        self.stage_delay_spin.setValue(self.engine.delay_ms)
        self.stage_delay_spin.valueChanged.connect(self.set_stage_delay)
        stage_delay_layout.addWidget(self.stage_delay_title)
        stage_delay_layout.addStretch(1)
        stage_delay_layout.addWidget(self.stage_delay_spin)
        self.stage_delay_panel.hide()

        self.stage_auto_fire_check = QCheckBox("Run F1 when stage loads")
        self.stage_auto_fire_check.setChecked(False)
        self.stage_auto_fire_check.setToolTip(
            "When checked, Full MAGCLIP waits for this stage's saved delay, "
            "then fires its first clip automatically."
        )
        self.stage_auto_fire_check.hide()

        self.stage_transition_editor = QGroupBox("Next Stage Macro")
        transition_layout = QGridLayout(self.stage_transition_editor)
        self.stage_transition_title = QLabel(
            "NEXT STAGE MACRO · up to 6 keyboard actions"
        )
        self.stage_transition_title.setStyleSheet("color:#facc15;font-weight:900")
        transition_layout.addWidget(
            self.stage_transition_title,
            0,
            0,
            1,
            self.TRANSITION_SLOTS,
        )
        self.stage_transition_boxes: list[QComboBox] = []
        for index in range(self.TRANSITION_SLOTS):
            box = QComboBox()
            box.addItems(self.TRANSITION_ACTIONS)
            box.setToolTip(f"Next Stage Macro action {index + 1}")
            self.stage_transition_boxes.append(box)
            transition_layout.addWidget(box, 1, index)
        save_transition = QPushButton("Save Next Stage Macro")
        save_transition.clicked.connect(self.save_stage_transition)
        transition_layout.addWidget(
            save_transition,
            2,
            0,
            1,
            self.TRANSITION_SLOTS,
        )
        self.stage_transition_editor.hide()

        actions = QGridLayout()
        fire_button = QPushButton("F1 · Fire")
        fire_button.clicked.connect(self.fire_current_clip)
        reload_round = QPushButton("R · Reload Round")
        reload_round.clicked.connect(self.reload_last_round)
        reload_clip = QPushButton("F4 · Reload Clip")
        reload_clip.clicked.connect(self.reload_last_clip)
        abort_button = QPushButton("F3 · Abort")
        abort_button.clicked.connect(self.abort)
        stop_repeat = QPushButton("F2 · Stop Repeat")
        stop_repeat.clicked.connect(self.stop_repeat)
        clear_sequence = QPushButton("Clear Sequence")
        clear_sequence.clicked.connect(self.clear_custom_sequence)
        actions.addWidget(fire_button, 0, 0)
        actions.addWidget(reload_round, 0, 1)
        actions.addWidget(reload_clip, 0, 2)
        actions.addWidget(abort_button, 1, 0)
        actions.addWidget(stop_repeat, 1, 1)
        actions.addWidget(clear_sequence, 1, 2)

        legend = QLabel(
            "F1 Fire / Start Repeat  ·  F2 Stop Repeat  ·  "
            "R Reload last round  ·  F4 Reload last clip  ·  "
            "F3 Abort  ·  Hotkeys work only in MAGCLIP Mode"
        )
        legend.setStyleSheet("color:#94a3b8;font-size:11px")

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_label)
        layout.addLayout(clip_actions)
        layout.addLayout(round_grid)
        layout.addLayout(settings)
        layout.addLayout(sequence_header)
        layout.addWidget(self.sequence_editor)
        layout.addWidget(self.stage_delay_panel)
        layout.addWidget(self.stage_auto_fire_check)
        layout.addWidget(self.stage_transition_editor)
        layout.addLayout(actions)
        layout.addWidget(legend)
        return panel

    def toggle_sequence_editor(self, expanded: bool) -> None:
        self.sequence_editor.setVisible(expanded)
        self.sequence_toggle.setText("Show Less" if expanded else "Show More")

    def set_history(
        self,
        employee: Employee | None,
        records: tuple[LeaveRecord, ...] | list[LeaveRecord],
    ) -> None:
        self._set_content_mode("leave")
        # Reapply the remembered default each time regular Leave MAGCLIP opens.
        self._apply_default_leave_sequence()
        employee_id = employee.employee_id if employee else ""
        self.employee_label.setText(employee.display_name if employee else "No employee selected")
        ordered = sorted(records, key=lambda item: (item.start, item.end, item.record_id))
        history_rows = []
        magclip_name = employee.magclip_name.strip() if employee else ""
        for record in ordered:
            row = leave_record_rounds(record)
            row[0] = magclip_name or self.name_overrides.get(record.record_id, record.name)
            history_rows.append(row)
        if employee_id == self.employee_id and history_rows == self.history_rows:
            return
        self.employee_id = employee_id
        self.history_rows = history_rows
        self.history_record_ids = [record.record_id for record in ordered]
        self.history_table.blockSignals(True)
        self.history_table.clear()
        for index, row in enumerate(self.history_rows):
            item = QTreeWidgetItem(row)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            self.history_table.addTopLevelItem(item)
            self._install_leave_status_dropdown(item, index)
        self.history_table.blockSignals(False)
        self.magazine.load(self.history_rows)
        if self.history_rows:
            self.history_table.setCurrentItem(self.history_table.topLevelItem(0))
            self.bridge.status.emit(f"READY · {len(self.history_rows)} HISTORY CLIP(S)")
        else:
            self.bridge.status.emit("EMPTY · NO SAVED LEAVE HISTORY")
        self.bridge.refresh.emit()

    def set_mone(
        self,
        employee: Employee | None,
        records: tuple[LeaveRecord, ...] | list[LeaveRecord],
    ) -> None:
        self.content_mode = "mone"
        self.engine = LeaveEntryEngine(delay_ms=self.delay_spin.value())
        self.employee_label.setText(
            employee.display_name if employee else "No employee selected"
        )
        self.history_caption.setText(
            "MONE CLIPS · Each row fires TYPE, START, VL, SL, END"
        )
        self.history_table.setColumnCount(len(MONE_FIELDS))
        self.history_table.setHeaderLabels(list(MONE_FIELDS))
        ordered = sorted(records, key=lambda item: (item.start, item.end, item.record_id))
        self.employee_id = employee.employee_id if employee else ""
        self.history_rows = [mone_record_rounds(record) for record in ordered]
        self.history_record_ids = [record.record_id for record in ordered]
        self.history_table.blockSignals(True)
        self.history_table.clear()
        for index, row in enumerate(self.history_rows):
            item = QTreeWidgetItem(row)
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            self.history_table.addTopLevelItem(item)
        self.history_table.blockSignals(False)
        self.magazine.load(self.history_rows, MONE_FIELDS)
        if self.history_rows:
            self.history_table.setCurrentItem(self.history_table.topLevelItem(0))
            self.bridge.status.emit(f"READY · {len(self.history_rows)} MONE CLIP(S)")
        else:
            self.bridge.status.emit("EMPTY · NO MONE CLIPS")
        self.bridge.refresh.emit()

    def set_mandatory_leave(
        self,
        employee: Employee | None,
        records: tuple[MandatoryLeaveRecord, ...] | list[MandatoryLeaveRecord],
    ) -> None:
        self.content_mode = "mandatory_leave"
        self.engine = LeaveEntryEngine(delay_ms=self.delay_spin.value())
        self.employee_label.setText(
            employee.display_name if employee else "No employee selected"
        )
        self.history_caption.setText(
            "MANDATORY LEAVE CLIPS · Each row fires YEAR, VL, SL"
        )
        self.history_table.setColumnCount(3)
        self.history_table.setHeaderLabels(["YEAR", "VL", "SL"])
        ordered = sorted(records, key=lambda item: item.year)
        self.employee_id = employee.employee_id if employee else ""
        self.history_rows = [mandatory_leave_rounds(record) for record in ordered]
        self.history_record_ids = [record.record_id for record in ordered]
        self.history_table.blockSignals(True)
        self.history_table.clear()
        for index, row in enumerate(self.history_rows):
            item = QTreeWidgetItem(row)
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            self.history_table.addTopLevelItem(item)
        self.history_table.blockSignals(False)
        self.magazine.load(self.history_rows, MANDATORY_LEAVE_FIELDS)
        if self.history_rows:
            self.history_table.setCurrentItem(self.history_table.topLevelItem(0))
            self.bridge.status.emit(
                f"READY · {len(self.history_rows)} MANDATORY LEAVE CLIP(S)"
            )
        else:
            self.bridge.status.emit("EMPTY · NO MANDATORY LEAVE CLIPS")
        self.bridge.refresh.emit()

    def select_sequence(self, name: str) -> bool:
        wanted = " ".join(name.split()).casefold()
        index = next(
            (
                position
                for position in range(self.sequence_preset.count())
                if " ".join(self.sequence_preset.itemText(position).split()).casefold()
                == wanted
            ),
            -1,
        )
        if index < 0:
            self.bridge.status.emit(f'SEQUENCE "{name}" NOT FOUND')
            return False
        self.sequence_preset.setCurrentIndex(index)
        self._preset_changed(index)
        return True

    def set_credits(
        self,
        employee: Employee | None,
        entries: list[CreditEntry] | tuple[CreditEntry, ...],
    ) -> None:
        self._set_content_mode("credits")
        employee_id = employee.employee_id if employee else ""
        self.employee_label.setText(
            employee.display_name if employee else "No employee selected"
        )
        ordered = list(entries)
        rows = [credit_entry_rounds(entry) for entry in ordered]
        if employee_id == self.employee_id and rows == self.history_rows:
            return
        self.employee_id = employee_id
        self.history_rows = rows
        self.history_record_ids = [entry.entry_id for entry in ordered]
        self.history_table.blockSignals(True)
        self.history_table.clear()
        for index, row in enumerate(rows):
            item = QTreeWidgetItem(row)
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            self.history_table.addTopLevelItem(item)
        self.history_table.blockSignals(False)
        self.magazine.load(rows, CREDIT_FIELDS)
        if rows:
            self.history_table.setCurrentItem(self.history_table.topLevelItem(0))
            self.bridge.status.emit(f"READY · {len(rows)} CREDIT CLIP(S)")
        else:
            self.bridge.status.emit("EMPTY · NO CREDIT ROWS")
        self.bridge.refresh.emit()

    def load_clipboard_data(self) -> None:
        try:
            rows = parse_clipboard_rows(QApplication.clipboard().text())
        except ValueError as error:
            self.bridge.status.emit(f"CLIPBOARD DATA · {error}")
            return
        manual_rows = normalize_manual_leave_clipboard(rows)
        manual_leave = manual_rows is not None
        if manual_rows is not None:
            rows = manual_rows
        self.content_mode = "manual_leave" if manual_leave else "clipboard"
        self.engine = ClipboardEntryEngine(delay_ms=self.delay_spin.value())
        self.employee_id = ""
        self.employee_label.setText("Clipboard data")
        self.history_rows = rows
        self.history_record_ids = []
        column_count = max(len(row) for row in rows)
        fields = (
            MANUAL_LEAVE_FIELDS
            if manual_leave
            else tuple(f"ROUND {index + 1}" for index in range(column_count))
        )
        self.history_caption.setText(
            (
                f"MANUAL LEAVE CLIPS · {len(rows)} row(s) · "
                "NAME, TYPE, START, END, STATUS, VL, SL"
            )
            if manual_leave
            else f"CLIPBOARD CLIPS · {len(rows)} row(s) · {column_count} round(s) maximum"
        )
        self.history_table.blockSignals(True)
        self.history_table.clear()
        self.history_table.setColumnCount(column_count)
        self.history_table.setHeaderLabels(list(fields))
        for column in range(column_count):
            self.history_table.header().setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch,
            )
        for index, row in enumerate(rows):
            item = QTreeWidgetItem(row)
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            self.history_table.addTopLevelItem(item)
        self.history_table.blockSignals(False)
        self.magazine.load(rows, fields)
        if manual_leave:
            self.sequence_preset.setCurrentText("MANUAL LEAVE")
            for position, box in enumerate(self.sequence_boxes):
                box.blockSignals(True)
                box.setCurrentText(
                    MANUAL_LEAVE_SEQUENCE[position]
                    if position < len(MANUAL_LEAVE_SEQUENCE)
                    else "NONE"
                )
                box.blockSignals(False)
            self.custom_sequence = list(MANUAL_LEAVE_SEQUENCE)
        self.history_table.setCurrentItem(self.history_table.topLevelItem(0))
        self.bridge.status.emit(
            f"READY · {len(rows)} "
            f"{'MANUAL LEAVE' if manual_leave else 'CLIPBOARD'} CLIP(S)"
        )
        self.bridge.refresh.emit()

    def _set_content_mode(self, mode: str) -> None:
        if mode == self.content_mode:
            return
        self.content_mode = mode
        if mode == "credits":
            self.engine = CreditEntryEngine(delay_ms=self.delay_spin.value())
            self.history_caption.setText(
                "CREDIT CLIPS · Each row fires MONTH, YEAR, VL EARNED, SL EARNED"
            )
            headers = list(CREDIT_FIELDS)
            preset_name = "CREDITS"
        else:
            self.engine = LeaveEntryEngine(delay_ms=self.delay_spin.value())
            self.history_caption.setText(
                "LEAVE HISTORY CLIPS · Double-click NAME to edit · STATUS: A / C / D"
            )
            headers = ["NAME", "TYPE", "START", "END", "VL", "SL", "LWOP", "STATUS"]
            preset_name = self.sequence_store.load_default() or "LEAVE ENTRY"
        self.history_table.setColumnCount(len(headers))
        self.history_table.setHeaderLabels(headers)
        table_header = self.history_table.header()
        for column in range(len(headers)):
            table_header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch
                if column < 2
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        if mode == "credits":
            if not self.select_sequence(preset_name):
                self.select_sequence("LEAVE ENTRY")
        else:
            self._apply_default_leave_sequence()

    def _install_leave_status_dropdown(
        self,
        item: QTreeWidgetItem,
        index: int,
    ) -> None:
        status = item.text(7).strip().upper() or "A"
        if status not in {"A", "C", "D"}:
            status = "A"
        combo = QComboBox()
        combo.addItems(["A", "C", "D"])
        combo.setCurrentText(status)
        combo.setToolTip("MAGCLIP status for this row")
        combo.currentTextChanged.connect(
            lambda value, row_index=index: self._set_leave_status(row_index, value)
        )
        self.history_table.setItemWidget(item, 7, combo)

    def _set_leave_status(self, index: int, value: str) -> None:
        if index < 0 or index >= len(self.history_rows):
            return
        status = value.strip().upper()
        self.history_rows[index][7] = status
        if index < len(self.magazine.clips) and len(self.magazine.clips[index].rounds) > 7:
            self.magazine.clips[index].rounds[7].value = status
        self.bridge.status.emit(f"CLIP {index + 1} STATUS · {status}")
        self.bridge.refresh.emit()

    def _history_item_double_clicked(
        self,
        item: QTreeWidgetItem,
        column: int,
    ) -> None:
        if self.content_mode == "leave" and column == 0:
            self.history_table.editItem(item, column)
            return
        self.load_selected_clip()

    def _history_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self.content_mode != "leave" or column != 0:
            return
        index = int(item.data(0, Qt.ItemDataRole.UserRole))
        if index < 0 or index >= len(self.history_rows):
            return
        name = item.text(0)
        self.history_rows[index][0] = name
        if index < len(self.history_record_ids):
            self.name_overrides[self.history_record_ids[index]] = name
        if index < len(self.magazine.clips) and self.magazine.clips[index].rounds:
            self.magazine.clips[index].rounds[0].value = name
        self.bridge.status.emit(f"CLIP {index + 1} NAME UPDATED")
        self.bridge.refresh.emit()

    def load_selected_clip(self, *_args: object) -> None:
        item = self.history_table.currentItem()
        if item is None:
            self.bridge.status.emit("SELECT A CLIP")
            return
        index = int(item.data(0, Qt.ItemDataRole.UserRole))
        if self.magazine.select_clip(index):
            self.bridge.status.emit(f"CLIP {index + 1} LOADED FROM ROUND 1")
            self.bridge.refresh.emit()

    def set_rounds_per_fire(self, value: str) -> None:
        self.rounds_per_fire = None if value == "ALL" else int(value)
        if not self.custom_sequence:
            self.bridge.status.emit(f"FIRE MODE · {value} ROUND(S)")

    def set_delay_ms(self, value: int) -> None:
        self.engine.delay_ms = value
        self.bridge.status.emit(f"DELAY · {value} ms")

    def set_repeat_enabled(self, enabled: bool) -> None:
        self.repeat_enabled = enabled
        self.bridge.status.emit("REPEAT CLIPS ON" if enabled else "REPEAT CLIPS OFF")

    def set_repeat_delay_ms(self, value: int) -> None:
        self.repeat_delay_ms = value
        self.bridge.status.emit(f"REPEAT DELAY · {value} ms")

    def _sequence_changed(self) -> None:
        self.sequence_preset.blockSignals(True)
        self.sequence_preset.setCurrentText("CUSTOM")
        self.sequence_preset.blockSignals(False)
        self.custom_sequence = [
            box.currentText()
            for box in self.sequence_boxes
            if box.currentText() != "NONE"
        ]
        if self.custom_sequence:
            self.bridge.status.emit("CUSTOM · " + " → ".join(self.custom_sequence))
        else:
            self.bridge.status.emit("CUSTOM SEQUENCE OFF")

    def import_clipboard_commands(self) -> None:
        try:
            commands = parse_sequence_commands(
                QApplication.clipboard().text(),
                self.SEQUENCE_SLOTS,
            )
        except ValueError as error:
            self.bridge.status.emit(f"IMPORT COMMANDS · {error}")
            return
        values = commands + ["NONE"] * (self.SEQUENCE_SLOTS - len(commands))
        for box, value in zip(self.sequence_boxes, values):
            box.blockSignals(True)
            if box.findText(value) < 0:
                box.addItem(value)
            box.setCurrentText(value)
            box.blockSignals(False)
        self._sequence_changed()
        self.sequence_toggle.setChecked(True)
        self.toggle_sequence_editor(True)
        self.bridge.status.emit(f"IMPORTED · {len(commands)} COMMAND(S)")

    def save_current_sequence(self) -> None:
        actions = [
            box.currentText()
            for box in self.sequence_boxes
            if box.currentText() != "NONE"
        ]
        if not actions:
            self.bridge.status.emit("SAVE SEQUENCE · ADD AT LEAST ONE ACTION")
            return
        current_name = self.sequence_preset.currentText()
        suggested = current_name if current_name in self.saved_sequences else ""
        name, accepted = QInputDialog.getText(
            self,
            "Save MAGCLIP Sequence",
            "Sequence name:",
            text=suggested,
        )
        if not accepted:
            return
        clean_name = " ".join(name.split())
        if clean_name in SEQUENCE_PRESETS or clean_name == "CUSTOM":
            QMessageBox.warning(
                self,
                "Save MAGCLIP Sequence",
                "Choose a different name; built-in preset names cannot be replaced.",
            )
            return
        if clean_name in self.saved_sequences:
            answer = QMessageBox.question(
                self,
                "Replace Saved Sequence",
                f'Replace the saved sequence "{clean_name}"?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            saved_name = self.sequence_store.save(clean_name, actions)
        except (OSError, ValueError) as error:
            self.bridge.status.emit(f"SAVE SEQUENCE · {error}")
            return

        sequence = tuple(actions)
        self.saved_sequences[saved_name] = sequence
        index = self.sequence_preset.findText(saved_name)
        self.sequence_preset.blockSignals(True)
        if index < 0:
            self.sequence_preset.addItem(saved_name, sequence)
            index = self.sequence_preset.count() - 1
        else:
            self.sequence_preset.setItemData(index, sequence)
        self.sequence_preset.setCurrentIndex(index)
        self.sequence_preset.blockSignals(False)
        self.custom_sequence = list(sequence)
        self._refresh_default_preset_picker()
        self.bridge.status.emit(
            f"SAVED SEQUENCE · {saved_name} · {len(sequence)} ACTIONS"
        )

    def delete_saved_sequence(self) -> None:
        name = self.sequence_preset.currentText()
        if name not in self.saved_sequences:
            self.bridge.status.emit("DELETE SEQUENCE · SELECT A SAVED SEQUENCE")
            return
        answer = QMessageBox.question(
            self,
            "Delete Saved Sequence",
            f'Delete the saved sequence "{name}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = self.sequence_store.delete(name)
        except OSError as error:
            self.bridge.status.emit(f"DELETE SEQUENCE · {error}")
            return
        if not deleted:
            self.bridge.status.emit("DELETE SEQUENCE · SAVED FILE CHANGED")
            return
        del self.saved_sequences[name]
        index = self.sequence_preset.findText(name)
        if index >= 0:
            self.sequence_preset.removeItem(index)
        self.sequence_preset.setCurrentText("CUSTOM")
        if self.sequence_store.load_default().casefold() == name.casefold():
            try:
                self.sequence_store.save_default("")
            except OSError as error:
                self.bridge.status.emit(f"DEFAULT PRESET · {error}")
        self._refresh_default_preset_picker()
        self.bridge.status.emit(f"DELETED SEQUENCE · {name}")

    def _open_slot_menu(self, index: int, global_position: QPoint) -> None:
        menu = QMenu(self)
        before_action = menu.addAction(f"Insert slot before {index + 1:02d}")
        after_action = menu.addAction(f"Insert slot after {index + 1:02d}")
        chosen = menu.exec(global_position)
        if chosen is before_action:
            self._insert_slot(index, after=False)
        elif chosen is after_action:
            self._insert_slot(index, after=True)

    def _insert_slot(self, index: int, *, after: bool) -> None:
        try:
            values = insert_sequence_slot(
                [box.currentText() for box in self.sequence_boxes],
                index,
                after=after,
            )
        except ValueError as error:
            self.bridge.status.emit(f"INSERT SLOT · {error}")
            return
        for box, value in zip(self.sequence_boxes, values):
            box.blockSignals(True)
            box.setCurrentText(value)
            box.blockSignals(False)
        self._sequence_changed()
        position = index + 2 if after else index + 1
        self.bridge.status.emit(f"INSERTED EMPTY SLOT {position:02d}")

    def _refresh_default_preset_picker(self) -> None:
        current_default = self.sequence_store.load_default()
        self.default_preset_picker.blockSignals(True)
        self.default_preset_picker.clear()
        self.default_preset_picker.addItem("Choose preset…", "")
        for index in range(self.sequence_preset.count()):
            name = self.sequence_preset.itemText(index)
            if name == "CUSTOM" or not self.sequence_preset.itemData(index):
                continue
            self.default_preset_picker.addItem(name, name)
        default_index = self.default_preset_picker.findData(current_default)
        self.default_preset_picker.setCurrentIndex(
            default_index if default_index >= 0 else 0
        )
        self.default_preset_picker.blockSignals(False)

    def toggle_default_preset_picker(self) -> None:
        visible = not self.default_preset_picker.isVisible()
        self.default_preset_picker.setVisible(visible)
        self.default_preset_button.setText(
            "Cancel Default" if visible else "Set as Default"
        )
        if visible:
            self._refresh_default_preset_picker()
            self.default_preset_picker.setFocus()
            self.default_preset_picker.showPopup()

    def set_default_preset_from_picker(self, _index: int) -> None:
        name = str(self.default_preset_picker.currentData() or "")
        if not name:
            return
        try:
            self.sequence_store.save_default(name)
        except OSError as error:
            self.bridge.status.emit(f"DEFAULT PRESET · {error}")
            return
        self.select_sequence(name)
        self.default_preset_picker.hide()
        self.default_preset_button.setText("Set as Default")
        self.bridge.status.emit(f'DEFAULT PRESET · "{name}" APPLIED')

    def _apply_default_leave_sequence(self) -> None:
        default_name = self.sequence_store.load_default()
        if not default_name or not self.select_sequence(default_name):
            self.select_sequence("LEAVE ENTRY")

    def _preset_changed(self, index: int) -> None:
        sequence = self.sequence_preset.itemData(index)
        if not sequence:
            return
        for position, box in enumerate(self.sequence_boxes):
            box.blockSignals(True)
            box.setCurrentText(
                sequence[position] if position < len(sequence) else "NONE"
            )
            box.blockSignals(False)
        self.custom_sequence = list(sequence)
        if self.sequence_preset.currentText() == "REPEAT PROCE APPROVE":
            self.repeat_check.setChecked(True)
            self.repeat_delay_spin.setValue(1500)
        self.bridge.status.emit(
            f"PRESET · {self.sequence_preset.currentText()} · "
            f"{len(sequence)} ACTIONS"
        )

    def clear_custom_sequence(self) -> None:
        for box in self.sequence_boxes:
            box.blockSignals(True)
            box.setCurrentText("NONE")
            box.blockSignals(False)
        self.custom_sequence = []
        self.sequence_preset.blockSignals(True)
        self.sequence_preset.setCurrentText("CUSTOM")
        self.sequence_preset.blockSignals(False)
        self.bridge.status.emit("CUSTOM SEQUENCE OFF")

    def fire_current_clip(self) -> None:
        if self.running:
            return
        if self.magazine.current_clip() is None:
            self.bridge.status.emit("DONE · NO CLIP CHAMBERED")
            return
        self._clear_last_round_highlight()
        self.running = True
        self.abort_event.clear()
        self.repeat_stop_event.clear()
        self.bridge.status.emit(
            "REPEATING · F2 STOP · F3 ABORT"
            if self.repeat_enabled
            else "RUNNING · F3 ABORT"
        )

        def worker() -> None:
            advance_guided_stage = False
            try:
                while True:
                    status = self._fire_once()
                    self.bridge.status.emit(status)
                    self.bridge.refresh.emit()
                    if (
                        status == "READY"
                        and self.magazine.current_clip() is None
                        and self.guided_flow_stage in {"credits", "mone", "mandatory"}
                    ):
                        advance_guided_stage = True
                        break
                    if status != "READY" or not self.repeat_enabled:
                        break
                    if self.repeat_stop_event.wait(self.repeat_delay_ms / 1000):
                        self.bridge.status.emit("REPEAT STOPPED")
                        break
            except Exception as error:
                LOGGER.exception("MAGCLIP firing failed")
                self.bridge.status.emit(f"MAGCLIP ERROR · {error}")
            finally:
                self.running = False
                self.bridge.refresh.emit()
                if advance_guided_stage:
                    self.bridge.status.emit("STAGE COMPLETE · RUNNING NEXT STAGE MACRO")
                    self.bridge.guided_stage_auto_requested.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _fire_once(self) -> str:
        clip = self.magazine.current_clip()
        if clip is None:
            return "DONE · NO CLIP CHAMBERED"
        remaining = clip.rounds[self.magazine.round_index :]
        if not remaining:
            return "CLIP ERROR"
        if self.custom_sequence:
            value_count = sum(
                action_consumes_round(action) for action in self.custom_sequence
            )
            if value_count == 0:
                return "CUSTOM ERROR · ADD AT LEAST ONE PASTE OR TYPE"
            if value_count > len(remaining):
                return "CUSTOM ERROR · NOT ENOUGH ROUNDS"
            values = [round_.value for round_ in remaining]
            result, consumed = self.engine.run_sequence(
                self.context,
                values,
                self.magazine.round_index,
                self.custom_sequence,
            )
            if result.completed:
                for _ in range(consumed):
                    self.magazine.advance_round()
                return "READY"
            return "ABORTED" if result.aborted else "SEQUENCE ERROR"

        fire_count = (
            len(remaining)
            if self.rounds_per_fire is None
            else min(self.rounds_per_fire, len(remaining))
        )
        values = [round_.value for round_ in remaining[:fire_count]]
        result = self.engine.run_rounds(
            self.context,
            values,
            self.magazine.round_index,
        )
        if result.completed:
            for _ in values:
                self.magazine.advance_round()
            return "READY"
        return "ABORTED" if result.aborted else "CLIP ERROR"

    def stop_repeat(self) -> None:
        self.repeat_stop_event.set()
        self.bridge.status.emit("STOPPING REPEAT…")

    def abort(self) -> None:
        self.abort_event.set()
        self.repeat_stop_event.set()
        self._highlight_last_fired_round()

    def _clear_last_round_highlight(self) -> None:
        if self._last_round_highlight is None:
            return
        clip_index, round_index = self._last_round_highlight
        item = self.history_table.topLevelItem(clip_index)
        if item is not None and round_index < self.history_table.columnCount():
            item.setBackground(round_index, QBrush())
            item.setForeground(round_index, QBrush())
            widget = self.history_table.itemWidget(item, round_index)
            if widget is not None:
                widget.setStyleSheet("")
        self._last_round_highlight = None

    def _highlight_last_fired_round(self) -> None:
        """Mark the completed round that F3 stopped after, ready for review."""
        self._clear_last_round_highlight()
        position = self.magazine.last_round_position
        if position is None:
            self.bridge.status.emit("ABORT · NO FIRED ROUND TO HIGHLIGHT")
            return
        clip_index, round_index = position
        item = self.history_table.topLevelItem(clip_index)
        if item is None or round_index >= self.history_table.columnCount():
            self.bridge.status.emit("ABORT · LAST FIRED ROUND IS UNAVAILABLE")
            return
        highlight = QBrush(QColor("#facc15"))
        item.setBackground(round_index, highlight)
        item.setForeground(round_index, QBrush(QColor("#111827")))
        widget = self.history_table.itemWidget(item, round_index)
        if widget is not None:
            widget.setStyleSheet(
                "QComboBox{background:#facc15;color:#111827;font-weight:900;}"
            )
        self.history_table.clearSelection()
        self.history_table.scrollToItem(item)
        self._last_round_highlight = position
        field = (
            self.magazine.fields[round_index]
            if round_index < len(self.magazine.fields)
            else f"ROUND {round_index + 1}"
        )
        self.bridge.status.emit(
            f"ABORT · LAST FIRED HIGHLIGHTED · CLIP {clip_index + 1} · {field}"
        )

    def reload_last_round(self) -> None:
        if self.running:
            return
        if self.magazine.reload_last_round():
            self.bridge.status.emit("LAST ROUND RELOADED")
            self.bridge.refresh.emit()
        else:
            self.bridge.status.emit("NO LAST ROUND")

    def reload_last_clip(self) -> None:
        if self.running:
            return
        if self.magazine.reload_last_clip():
            self.bridge.status.emit("LAST CLIP RELOADED")
            self.bridge.refresh.emit()
        else:
            self.bridge.status.emit("NO COMPLETED CLIP")

    def refresh_view(self) -> None:
        clip_no, total_clips, round_no, total_rounds = self.magazine.progress()
        if total_clips == 0:
            self.progress_label.setText("No leave-history clips loaded")
            self.current_label.setText("—")
            self.next_label.setText("—")
            return
        if self.magazine.current_clip() is None:
            self.progress_label.setText(f"Completed {total_clips}/{total_clips} clips")
            self.current_label.setText("DONE")
            self.next_label.setText("—")
            return
        self.progress_label.setText(
            f"Clip {clip_no}/{total_clips}  ·  Round {round_no}/{total_rounds}"
        )
        current = self.magazine.current_round()
        field_name = self.magazine.current_field() or "ROUND"
        self.current_label.setText(f"{field_name}\n{current.value if current else '—'}")
        next_details = self.magazine.next_round_details()
        self.next_label.setText(
            f"{next_details[0]}\n{next_details[1]}" if next_details else "—"
        )
        current_item = self.history_table.topLevelItem(self.magazine.clip_index)
        if current_item is not None and self._last_round_highlight is None:
            self.history_table.setCurrentItem(current_item)
            self.history_table.scrollToItem(current_item)

    def _install_local_hotkeys(self) -> None:
        """Keep MAGCLIP keyboard controls usable while this panel has focus."""
        bindings = (
            ("F1", self.hotkey_fire_requested),
            ("F2", self.hotkey_stop_requested),
            ("R", self.hotkey_reload_round_requested),
            ("F3", self.hotkey_abort_requested),
            ("F4", self.hotkey_reload_clip_requested),
        )
        self.local_hotkeys: list[QShortcut] = []
        for key, signal in bindings:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(signal.emit)
            self.local_hotkeys.append(shortcut)

    def _capture_f1(self, event: Any) -> bool:
        """Fire MAGCLIP once and always swallow F1 before Edge can see it."""
        if getattr(event, "event_type", "") == "down":
            self.hotkey_fire_requested.emit()
        return False

    def activate_hotkeys(self) -> None:
        # Re-register whenever MAGCLIP opens so a stale Windows hook cannot
        # leave the page showing active while the actual keys are detached.
        self.deactivate_hotkeys()
        handles: list[Any] = []
        keyboard_module: Any | None = None
        try:
            import keyboard

            keyboard_module = keyboard
            self.f1_hook_handle = keyboard.hook_key(
                "f1",
                self._capture_f1,
                suppress=True,
            )
            handles.append(
                keyboard.add_hotkey("f2", self.hotkey_stop_requested.emit, suppress=True)
            )
            handles.append(
                keyboard.add_hotkey(
                    "r",
                    self.hotkey_reload_round_requested.emit,
                    suppress=True,
                )
            )
            handles.append(
                keyboard.add_hotkey("f3", self.hotkey_abort_requested.emit, suppress=True)
            )
            handles.append(
                keyboard.add_hotkey(
                    "f4",
                    self.hotkey_reload_clip_requested.emit,
                    suppress=True,
                )
            )
        except Exception as error:
            LOGGER.exception("Could not enable MAGCLIP hotkeys")
            if keyboard_module is not None:
                for handle in handles:
                    try:
                        keyboard_module.remove_hotkey(handle)
                    except Exception:
                        pass
            if self.f1_hook_handle is not None and keyboard_module is not None:
                try:
                    keyboard_module.unhook(self.f1_hook_handle)
                except Exception:
                    pass
            self.f1_hook_handle = None
            self.hotkey_handles = []
            self.hotkey_state.setText("GLOBAL HOTKEY ERROR")
            self.hotkey_state.setStyleSheet(
                "background:#7c2d12;color:#ffedd5;border-radius:8px;padding:6px 10px;"
                "font-weight:800"
            )
            self.bridge.status.emit(
                "GLOBAL HOTKEY ERROR · Click the MAGCLIP panel and use F1/F2/R/F3/F4."
            )
            return
        self.hotkey_handles = handles
        self.hotkey_state.setText("GLOBAL HOTKEYS ACTIVE")
        self.hotkey_state.setStyleSheet(
            "background:#0f3d2e;color:#86efac;border-radius:8px;padding:6px 10px;"
            "font-weight:800"
        )

    def deactivate_hotkeys(self) -> None:
        self.abort()
        try:
            import keyboard

            if self.f1_hook_handle is not None:
                keyboard.unhook(self.f1_hook_handle)
        except Exception:
            LOGGER.exception("Could not disable MAGCLIP F1 hook")
        self.f1_hook_handle = None
        if self.hotkey_handles:
            try:
                import keyboard

                for handle in self.hotkey_handles:
                    keyboard.remove_hotkey(handle)
            except Exception:
                LOGGER.exception("Could not disable all MAGCLIP hotkeys")
        self.hotkey_handles = []
        self.hotkey_state.setText("HOTKEYS OFF")
        self.hotkey_state.setStyleSheet(
            "background:#3f1d24;color:#fecaca;border-radius:8px;padding:6px 10px;"
            "font-weight:800"
        )
