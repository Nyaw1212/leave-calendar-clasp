"""Reusable leave-card print template editor (no employee data required)."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPixmap, QPainter, QTextOption
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QDoubleSpinBox, QGraphicsItem,
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .settings import app_data_dir

# Letter landscape; scene units are millimetres.
PAGE_W, PAGE_H = 279.4, 215.9
MM_PER_POINT = 25.4 / 72.0
TEMPLATE_DIR = app_data_dir() / "printing_aligner"
TEMPLATE_FILE = TEMPLATE_DIR / "leave_card_template.json"
BACKGROUND_FILE = TEMPLATE_DIR / "background.png"
FONT_OPTIONS = ("Arial Bold", "Bahnschrift SemiBold", "Arial Black", "Stencil", "Agency FB Bold", "Bahnschrift Light")
FIELDS = [
    ("header_name", "Header Name", "SAMPLE EMPLOYEE NAME", 8.0, 5.0, 20),
    ("name", "Name", "SAMPLE EMPLOYEE NAME", 24.0, 29.0, 12),
    ("entrance_of_duty", "Entrance of Duty", "01/01/2020", 137.0, 35.0, 12),
    # Phase 2: brought-forward row. Values below are calibration samples only.
    ("bf_period", "B/F · Period", "OCT 2026", 9.0, 73.0, 8),
    ("bf_vl_balance", "B/F · VL Balance", "00.000", 154.0, 73.0, 8),
    ("bf_sl_balance", "B/F · SL Balance", "00.000", 226.0, 73.0, 8),
    ("bf_remarks", "B/F · Remarks (FL / WL / SPL BAL)", "FL: 0  WL: 0  SPL BAL: 0", 249.0, 73.0, 6),
]


class FieldItem(QGraphicsTextItem):
    def __init__(self, key: str, label: str, text: str, x: float, y: float, size: int):
        super().__init__(text)
        self.key, self.label, self.point_size = key, label, size
        self.font_choice = "Arial Bold"
        self.char_spacing = 0.0
        self.h_align = "Left"
        self.v_align = "Top"
        self.apply_font_size()
        self.document().setDocumentMargin(0)
        self.setDefaultTextColor(QColor("#000000"))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(x, y)
        self.setToolTip(label + " — drag to position, use arrow keys for fine adjustment")

    def apply_font_size(self):
        family, weight = {
            "Arial Bold": ("Arial", QFont.Weight.Bold),
            "Bahnschrift SemiBold": ("Bahnschrift", QFont.Weight.DemiBold),
            "Arial Black": ("Arial Black", QFont.Weight.Black),
            "Stencil": ("Stencil", QFont.Weight.Normal),
            "Agency FB Bold": ("Agency FB", QFont.Weight.Bold),
            "Bahnschrift Light": ("Bahnschrift", QFont.Weight.Light),
        }[self.font_choice]
        font = QFont(family)
        font.setWeight(weight)
        font.setPixelSize(max(1, round(self.point_size * MM_PER_POINT)))
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self.char_spacing)
        self.setFont(font)
        self.adjust_text_bounds()
        self.apply_alignment()

    def apply_alignment(self):
        option = self.document().defaultTextOption()
        option.setAlignment({
            "Left": Qt.AlignmentFlag.AlignLeft,
            "Center": Qt.AlignmentFlag.AlignHCenter,
            "Right": Qt.AlignmentFlag.AlignRight,
        }.get(self.h_align, Qt.AlignmentFlag.AlignLeft))
        self.document().setDefaultTextOption(option)
        self.update()

    def adjust_text_bounds(self):
        # QGraphicsTextItem otherwise retains a stale width and wraps long names.
        option = self.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.NoWrap)
        self.document().setDefaultTextOption(option)
        width = QFontMetricsF(self.font()).horizontalAdvance(self.toPlainText())
        self.setTextWidth(max(1.0, width + 8.0))
        self.update()

    def keyPressEvent(self, event):
        directions = {
            Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
        }
        if event.key() in directions:
            dx, dy = directions[event.key()]
            step = 1.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.1
            self.moveBy(dx * step, dy * step)
            event.accept()
            return
        super().keyPressEvent(event)


class TemplateView(QGraphicsView):
    def keyPressEvent(self, event):
        directions = {
            Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
        }
        selected = [item for item in self.scene().selectedItems() if isinstance(item, FieldItem)]
        if selected and event.key() in directions:
            dx, dy = directions[event.key()]
            step = 1.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.1
            for item in selected:
                item.moveBy(dx * step, dy * step)
            event.accept()
            return
        super().keyPressEvent(event)


class TemplateEditorDialog(QDialog):
    def __init__(self, parent=None, employee=None):
        super().__init__(parent)
        self.employee = employee
        self.setWindowTitle("Leave Card · Template Editor")
        self.resize(1250, 850)
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, PAGE_W, PAGE_H)
        self.view = TemplateView(self.scene)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.view.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.view.setBackgroundBrush(QBrush(QColor("#28313d")))
        self.background = None
        self.items_by_key = {}
        self.field_select = QComboBox()
        self.field_select.currentIndexChanged.connect(self.select_field)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 72)
        self.size_spin.valueChanged.connect(self.change_size)
        self.font_combo = QComboBox()
        self.font_combo.addItems(FONT_OPTIONS)
        self.font_combo.currentTextChanged.connect(self.change_font)
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(-1.0, 10.0)
        self.spacing_spin.setDecimals(2)
        self.spacing_spin.setSingleStep(0.1)
        self.spacing_spin.setSuffix(" mm")
        self.spacing_spin.valueChanged.connect(self.change_spacing)
        self.h_align_combo = QComboBox()
        self.h_align_combo.addItems(["Left", "Center", "Right"])
        self.h_align_combo.currentTextChanged.connect(self.change_alignment)
        self.v_align_combo = QComboBox()
        self.v_align_combo.addItems(["Top", "Middle", "Bottom"])
        self.v_align_combo.currentTextChanged.connect(self.change_alignment)

        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        for label, callback in [
            ("Load BG", self.load_background),
            ("Remove BG", self.remove_background),
            ("Save Template", self.save_template),
            ("Print Preview", self.open_print_preview),
            ("Reset Fields", self.reset_fields),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()
        root.addLayout(toolbar)
        alignment_toolbar = QHBoxLayout()
        alignment_toolbar.addWidget(QLabel("Align selected boxes:"))
        for title, mode in [
            ("Left", "left"), ("Center", "center"), ("Right", "right"),
            ("Top", "top"), ("Middle", "middle"), ("Bottom", "bottom"),
        ]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, mode=mode: self.align_selected(mode))
            alignment_toolbar.addWidget(button)
        alignment_toolbar.addStretch()
        root.addLayout(alignment_toolbar)
        root.addWidget(QLabel("Letter Landscape · 11 × 8.5 in · Ctrl+Click to multi-select · Drag or arrows: 0.1 mm · Shift+arrows: 1 mm"))
        root.addWidget(self.view, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Field"))
        bottom.addWidget(self.field_select)
        bottom.addWidget(QLabel("Font size (pt)"))
        bottom.addWidget(self.size_spin)
        bottom.addWidget(QLabel("Font"))
        bottom.addWidget(self.font_combo)
        bottom.addWidget(QLabel("Character spacing"))
        bottom.addWidget(self.spacing_spin)
        bottom.addWidget(QLabel("Horizontal"))
        bottom.addWidget(self.h_align_combo)
        bottom.addWidget(QLabel("Vertical"))
        bottom.addWidget(self.v_align_combo)
        bottom.addStretch()
        root.addLayout(bottom)
        self.load_template()
        self.apply_employee()
        self.scene.selectionChanged.connect(self.sync_selection)

    def apply_employee(self):
        """Preview the selected employee without changing saved template positions."""
        if self.employee is None:
            return
        name = str(self.employee.name or "").strip().upper()
        assumption = self.employee.assumption_date
        values = {
            "header_name": name,
            "name": name,
            "entrance_of_duty": assumption.strftime("%m/%d/%Y") if assumption else "",
        }
        for key, value in values.items():
            item = self.items_by_key.get(key)
            if item:
                item.setPlainText(value)
                item.adjust_text_bounds()

    def showEvent(self, event):
        super().showEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def reset_fields(self):
        for item in self.items_by_key.values():
            self.scene.removeItem(item)
        self.items_by_key.clear()
        self.field_select.blockSignals(True)
        self.field_select.clear()
        for key, label, sample, x, y, size in FIELDS:
            item = FieldItem(key, label, sample, x, y, size)
            self.scene.addItem(item)
            self.items_by_key[key] = item
            self.field_select.addItem(label, key)
        self.field_select.blockSignals(False)
        self.select_field(0)

    def select_field(self, index):
        key = self.field_select.itemData(index)
        if key not in self.items_by_key:
            return
        for item in self.items_by_key.values():
            item.setSelected(False)
        item = self.items_by_key[key]
        item.setSelected(True)
        item.setFocus()
        self.view.setFocus()
        self.size_spin.blockSignals(True)
        self.size_spin.setValue(item.point_size)
        self.size_spin.blockSignals(False)
        self._sync_font_controls(item)

    def _sync_font_controls(self, item):
        self.font_combo.blockSignals(True)
        self.font_combo.setCurrentText(item.font_choice)
        self.font_combo.blockSignals(False)
        self.spacing_spin.blockSignals(True)
        self.spacing_spin.setValue(item.char_spacing)
        self.spacing_spin.blockSignals(False)
        self.h_align_combo.blockSignals(True)
        self.h_align_combo.setCurrentText(item.h_align)
        self.h_align_combo.blockSignals(False)
        self.v_align_combo.blockSignals(True)
        self.v_align_combo.setCurrentText(item.v_align)
        self.v_align_combo.blockSignals(False)

    def sync_selection(self):
        selected = [item for item in self.scene.selectedItems() if isinstance(item, FieldItem)]
        if selected:
            index = self.field_select.findData(selected[0].key)
            self.field_select.blockSignals(True)
            self.field_select.setCurrentIndex(index)
            self.field_select.blockSignals(False)
            self.size_spin.blockSignals(True)
            self.size_spin.setValue(selected[0].point_size)
            self.size_spin.blockSignals(False)
            self._sync_font_controls(selected[0])

    def align_selected(self, mode):
        selected = [item for item in self.scene.selectedItems() if isinstance(item, FieldItem)]
        if len(selected) < 2:
            QMessageBox.information(self, "Align Boxes", "Ctrl+Click at least two text boxes first.")
            return
        rectangles = [item.sceneBoundingRect() for item in selected]
        if mode == "left":
            target = min(rect.left() for rect in rectangles)
        elif mode == "center":
            target = (min(rect.left() for rect in rectangles) + max(rect.right() for rect in rectangles)) / 2
        elif mode == "right":
            target = max(rect.right() for rect in rectangles)
        elif mode == "top":
            target = min(rect.top() for rect in rectangles)
        elif mode == "middle":
            target = (min(rect.top() for rect in rectangles) + max(rect.bottom() for rect in rectangles)) / 2
        else:
            target = max(rect.bottom() for rect in rectangles)
        for item, rect in zip(selected, rectangles):
            current = {
                "left": rect.left(), "center": rect.center().x(),
                "right": rect.right(), "top": rect.top(),
                "middle": rect.center().y(), "bottom": rect.bottom(),
            }[mode]
            delta = target - current
            if mode in ("left", "center", "right"):
                item.moveBy(delta, 0)
            else:
                item.moveBy(0, delta)

    def change_size(self, value):
        key = self.field_select.currentData()
        if key in self.items_by_key:
            item = self.items_by_key[key]
            item.point_size = value
            item.apply_font_size()

    def change_font(self, choice):
        item = self.items_by_key.get(self.field_select.currentData())
        if item and choice in FONT_OPTIONS:
            item.font_choice = choice
            item.apply_font_size()

    def change_spacing(self, value):
        item = self.items_by_key.get(self.field_select.currentData())
        if item:
            item.char_spacing = value
            item.apply_font_size()

    def change_alignment(self, _value):
        item = self.items_by_key.get(self.field_select.currentData())
        if item:
            item.h_align = self.h_align_combo.currentText()
            item.v_align = self.v_align_combo.currentText()
            item.apply_alignment()

    def _set_background(self, path):
        if self.background is not None:
            self.scene.removeItem(self.background)
            self.background = None
        if path and Path(path).is_file():
            image = QImage(str(path))
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                item = QGraphicsPixmapItem(pixmap)
                # Fit exactly to Letter landscape, matching Printing Aligner.
                item.setTransformOriginPoint(0, 0)
                from PySide6.QtGui import QTransform
                item.setTransform(QTransform.fromScale(PAGE_W / pixmap.width(),
                                                        PAGE_H / pixmap.height()))
                item.setZValue(-10)
                self.scene.addItem(item)
                self.background = item

    def load_background(self):
        path, _ = QFileDialog.getOpenFileName(self, "Background", "",
            "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        image = QImage(path)
        if image.isNull() or not image.save(str(BACKGROUND_FILE)):
            QMessageBox.warning(self, "Background", "Could not cache image.")
            return
        self._set_background(BACKGROUND_FILE)

    def remove_background(self):
        self._set_background(None)

    def open_print_preview(self):
        from .print_preview import LeaveCardPrintPreview
        LeaveCardPrintPreview(self).exec()

    def save_template(self):
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "leave-card-template-v1",
            "page_mm": [PAGE_W, PAGE_H],
            "background": str(BACKGROUND_FILE) if self.background else None,
            "fields": [
                {"mapping": item.key, "text": next((definition[2] for definition in FIELDS if definition[0] == item.key), ""),
                 "x": round(item.pos().x(), 3), "y": round(item.pos().y(), 3),
                 "size": item.point_size, "family": item.font().family(),
                 "font_choice": item.font_choice, "character_spacing_mm": item.char_spacing,
                 "h_align": item.h_align, "v_align": item.v_align,
                 "color": "#000000", "spacing": 0.0}
                for item in self.items_by_key.values()
            ],
        }
        TEMPLATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Template saved", "Template saved locally. Employee mapping will be connected next.")

    def load_template(self):
        self.reset_fields()
        if not TEMPLATE_FILE.is_file():
            return
        try:
            payload = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
            for record in payload.get("fields", []):
                item = self.items_by_key.get(record.get("mapping"))
                if item:
                    item.setPos(float(record["x"]), float(record["y"]))
                    item.point_size = int(record.get("size", item.point_size))
                    item.font_choice = record.get("font_choice", "Arial Bold")
                    if item.font_choice not in FONT_OPTIONS:
                        item.font_choice = "Arial Bold"
                    item.char_spacing = float(record.get("character_spacing_mm", 0.0))
                    item.h_align = record.get("h_align", "Left")
                    item.v_align = record.get("v_align", "Top")
                    item.apply_font_size()
            self.select_field(self.field_select.currentIndex())
            self._set_background(payload.get("background"))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            QMessageBox.warning(self, "Template", "Could not load template: " + str(exc))
