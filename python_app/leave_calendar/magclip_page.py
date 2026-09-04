from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .magclip_engine import (
    DEFAULT_SEQUENCE,
    LeaveEntryEngine,
    Magazine,
    SEQUENCE_PRESETS,
    action_consumes_round,
    leave_record_rounds,
)
from .models import Employee, LeaveRecord


LOGGER = logging.getLogger(__name__)


class MagclipBridge(QObject):
    refresh = Signal()
    status = Signal(str)


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
    SEQUENCE_SLOTS = 30
    SEQUENCE_COLUMNS = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.magazine = Magazine()
        self.engine = LeaveEntryEngine(delay_ms=120)
        self.bridge = MagclipBridge()
        self.abort_event = threading.Event()
        self.context = KeyboardContext(self.abort_event)
        self.running = False
        self.rounds_per_fire: int | None = None
        self.custom_sequence: list[str] = list(DEFAULT_SEQUENCE)
        self.hotkey_handles: list[Any] = []
        self.history_rows: list[list[str]] = []
        self.history_record_ids: list[str] = []
        self.name_overrides: dict[str, str] = {}
        self.employee_id = ""
        self._build_ui()
        self.bridge.refresh.connect(self.refresh_view)
        self.bridge.status.connect(self.status_label.setText)
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
        self.hotkey_state.setStyleSheet(
            "background:#3f1d24;color:#fecaca;border-radius:8px;padding:6px 10px;"
            "font-weight:800"
        )
        header.addWidget(back_button)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.hotkey_state)
        root.addLayout(header)
        self.employee_label.setWordWrap(True)
        root.addWidget(self.employee_label)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_history_panel())
        splitter.addWidget(self._build_monitor_panel())
        splitter.setSizes([310, 590])
        root.addWidget(splitter, 1)

    def _build_history_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 4)
        caption = QLabel(
            "LEAVE HISTORY CLIPS · Double-click NAME to edit; all eight cells are rounds"
        )
        caption.setStyleSheet("color:#67e8f9;font-weight:800")
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
        self.history_table.setStyleSheet(
            "QTreeWidget::item:selected{"
            "background-color:rgba(250,204,21,204);"
            "color:#111827;"
            "border-top:1px solid #fde047;"
            "border-bottom:1px solid #fde047;"
            "font-weight:800}"
        )
        self.history_table.itemDoubleClicked.connect(self._history_item_double_clicked)
        self.history_table.itemChanged.connect(self._history_item_changed)
        self.load_selected_button = QPushButton("Load Selected Clip from Round 1")
        self.load_selected_button.clicked.connect(self.load_selected_clip)
        layout.addWidget(caption)
        layout.addWidget(self.history_table, 1)
        layout.addWidget(self.load_selected_button)
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
        settings.addWidget(QLabel("Delay:"))
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(25, 2000)
        self.delay_spin.setSingleStep(25)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.setValue(self.engine.delay_ms)
        self.delay_spin.valueChanged.connect(self.set_delay_ms)
        settings.addWidget(self.delay_spin)
        settings.addStretch(1)

        sequence_caption = QLabel(
            "CUSTOM SEQUENCE · Up to 30 actions; selected actions override Rounds per F1"
        )
        sequence_caption.setStyleSheet("color:#cbd5e1;font-weight:800")
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Sequence preset:"))
        self.sequence_preset = QComboBox()
        self.sequence_preset.addItem("CUSTOM", None)
        for name, sequence in SEQUENCE_PRESETS.items():
            self.sequence_preset.addItem(name, sequence)
        self.sequence_preset.setCurrentText("LEAVE ENTRY")
        self.sequence_preset.currentIndexChanged.connect(self._preset_changed)
        preset_row.addWidget(self.sequence_preset, 1)
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
                    "TYPE",
                    "TYPE P",
                    "TYPE A",
                    "TYPE A 400MS",
                    "TAB",
                    "ENTER",
                    "ENTER 400MS",
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
            self.sequence_boxes.append(box)
            row = index // self.SEQUENCE_COLUMNS
            column = (index % self.SEQUENCE_COLUMNS) * 2
            sequence_grid.addWidget(label, row, column)
            sequence_grid.addWidget(box, row, column + 1)

        actions = QGridLayout()
        fire_button = QPushButton("F1 · Fire")
        fire_button.clicked.connect(self.fire_current_clip)
        reload_round = QPushButton("R · Reload Round")
        reload_round.clicked.connect(self.reload_last_round)
        reload_clip = QPushButton("F4 · Reload Clip")
        reload_clip.clicked.connect(self.reload_last_clip)
        abort_button = QPushButton("F3 · Abort")
        abort_button.clicked.connect(self.abort)
        clear_sequence = QPushButton("Clear Sequence")
        clear_sequence.clicked.connect(self.clear_custom_sequence)
        actions.addWidget(fire_button, 0, 0)
        actions.addWidget(reload_round, 0, 1)
        actions.addWidget(reload_clip, 0, 2)
        actions.addWidget(abort_button, 1, 0)
        actions.addWidget(clear_sequence, 1, 1, 1, 2)

        legend = QLabel(
            "F1 Fire  ·  R Reload last round  ·  F4 Reload last clip  ·  "
            "F3 Abort  ·  Hotkeys work only in MAGCLIP Mode"
        )
        legend.setStyleSheet("color:#94a3b8;font-size:11px")

        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_label)
        layout.addLayout(round_grid)
        layout.addLayout(settings)
        layout.addWidget(sequence_caption)
        layout.addLayout(preset_row)
        layout.addLayout(sequence_grid)
        layout.addLayout(actions)
        layout.addWidget(legend)
        return panel

    def set_history(
        self,
        employee: Employee | None,
        records: tuple[LeaveRecord, ...] | list[LeaveRecord],
    ) -> None:
        employee_id = employee.employee_id if employee else ""
        self.employee_label.setText(employee.display_name if employee else "No employee selected")
        ordered = sorted(records, key=lambda item: (item.start, item.end, item.record_id))
        history_rows = []
        for record in ordered:
            row = leave_record_rounds(record)
            row[0] = self.name_overrides.get(record.record_id, record.name)
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
        self.history_table.blockSignals(False)
        self.magazine.load(self.history_rows)
        if self.history_rows:
            self.history_table.setCurrentItem(self.history_table.topLevelItem(0))
            self.bridge.status.emit(f"READY · {len(self.history_rows)} HISTORY CLIP(S)")
        else:
            self.bridge.status.emit("EMPTY · NO SAVED LEAVE HISTORY")
        self.bridge.refresh.emit()

    def _history_item_double_clicked(
        self,
        item: QTreeWidgetItem,
        column: int,
    ) -> None:
        if column == 0:
            self.history_table.editItem(item, column)
            return
        self.load_selected_clip()

    def _history_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
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
            self.bridge.status.emit("SELECT A LEAVE-HISTORY CLIP")
            return
        index = int(item.data(0, Qt.ItemDataRole.UserRole))
        if self.magazine.select_clip(index):
            self.bridge.status.emit(f"CLIP {index + 1} LOADED FROM NAME")
            self.bridge.refresh.emit()

    def set_rounds_per_fire(self, value: str) -> None:
        self.rounds_per_fire = None if value == "ALL" else int(value)
        if not self.custom_sequence:
            self.bridge.status.emit(f"FIRE MODE · {value} ROUND(S)")

    def set_delay_ms(self, value: int) -> None:
        self.engine.delay_ms = value
        self.bridge.status.emit(f"DELAY · {value} ms")

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
        clip = self.magazine.current_clip()
        if clip is None:
            self.bridge.status.emit("DONE · NO CLIP CHAMBERED")
            return
        remaining = clip.rounds[self.magazine.round_index :]
        if not remaining:
            return
        self.running = True
        self.abort_event.clear()
        self.bridge.status.emit("RUNNING · F3 ABORT")

        def worker() -> None:
            try:
                if self.custom_sequence:
                    value_count = sum(
                        action_consumes_round(action)
                        for action in self.custom_sequence
                    )
                    if value_count == 0:
                        self.bridge.status.emit(
                            "CUSTOM ERROR · ADD AT LEAST ONE PASTE OR TYPE"
                        )
                        return
                    if value_count > len(remaining):
                        self.bridge.status.emit("CUSTOM ERROR · NOT ENOUGH ROUNDS")
                        return
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
                        self.bridge.status.emit("READY")
                    elif result.aborted:
                        self.bridge.status.emit("ABORTED")
                    else:
                        self.bridge.status.emit("SEQUENCE ERROR")
                    return

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
                    self.bridge.status.emit("READY")
                elif result.aborted:
                    self.bridge.status.emit("ABORTED")
                else:
                    self.bridge.status.emit("CLIP ERROR")
            except Exception as error:
                LOGGER.exception("MAGCLIP firing failed")
                self.bridge.status.emit(f"MAGCLIP ERROR · {error}")
            finally:
                self.running = False
                self.bridge.refresh.emit()

        threading.Thread(target=worker, daemon=True).start()

    def abort(self) -> None:
        self.abort_event.set()

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
        if current_item is not None:
            self.history_table.setCurrentItem(current_item)
            self.history_table.scrollToItem(current_item)

    def activate_hotkeys(self) -> None:
        if self.hotkey_handles:
            return
        handles: list[Any] = []
        try:
            import keyboard

            handles.append(keyboard.add_hotkey("f1", self.fire_current_clip, suppress=True))
            handles.append(keyboard.add_hotkey("r", self.reload_last_round, suppress=True))
            handles.append(keyboard.add_hotkey("f3", self.abort, suppress=True))
            handles.append(keyboard.add_hotkey("f4", self.reload_last_clip, suppress=True))
        except Exception as error:
            LOGGER.exception("Could not enable MAGCLIP hotkeys")
            for handle in handles:
                try:
                    keyboard.remove_hotkey(handle)
                except Exception:
                    pass
            self.hotkey_handles = []
            self.hotkey_state.setText("HOTKEY ERROR")
            self.bridge.status.emit(f"HOTKEY ERROR · {error}")
            return
        self.hotkey_handles = handles
        self.hotkey_state.setText("HOTKEYS ACTIVE")
        self.hotkey_state.setStyleSheet(
            "background:#0f3d2e;color:#86efac;border-radius:8px;padding:6px 10px;"
            "font-weight:800"
        )

    def deactivate_hotkeys(self) -> None:
        self.abort()
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
