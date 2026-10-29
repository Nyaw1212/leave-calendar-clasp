"""Reusable leave-card print template editor (no employee data required)."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPixmap, QPainter
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QGraphicsItem,
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
FIELDS = [
    ("header_name", "Header Name", "SAMPLE EMPLOYEE NAME", 8.0, 5.0, 20),
    ("name", "Name", "SAMPLE EMPLOYEE NAME", 24.0, 29.0, 12),
    ("entrance_of_duty", "Entrance of Duty", "01/01/2020", 137.0, 35.0, 12),
]


class FieldItem(QGraphicsTextItem):
    def __init__(self, key: str, label: str, text: str, x: float, y: float, size: int):
        super().__init__(text)
        self.key, self.label, self.point_size = key, label, size
        self.apply_font_size()
        self.document().setDocumentMargin(0)
        self.setDefaultTextColor(QColor("#000000"))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(x, y)
        self.setToolTip(label + " — drag to position, use arrow keys for fine adjustment")

    def apply_font_size(self):
        # Graphics scene coordinates are millimetres, not screen pixels.
        font = QFont("Arial")
        font.setBold(True)
        font.setPixelSize(max(1, round(self.point_size * MM_PER_POINT)))
        self.setFont(font)

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


class TemplateEditorDialog(QDialog):
    def __init__(self, parent=None, employee=None):
        super().__init__(parent)
        self.employee = employee
        self.setWindowTitle("Leave Card · Template Editor")
        self.resize(1250, 850)
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, PAGE_W, PAGE_H)
        self.view = QGraphicsView(self.scene)
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
        root.addWidget(QLabel("Letter Landscape · 11 × 8.5 in (279.4 × 215.9 mm) · Drag fields · Arrows: 0.1 mm · Shift + arrows: 1 mm"))
        root.addWidget(self.view, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Field"))
        bottom.addWidget(self.field_select)
        bottom.addWidget(QLabel("Font size (pt)"))
        bottom.addWidget(self.size_spin)
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
            "entrance_of_duty": assumption.strftime("%m/%d/%Y") if assumption else "DATE NOT SET",
        }
        for key, value in values.items():
            item = self.items_by_key.get(key)
            if item:
                item.setPlainText(value)

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
        self.size_spin.blockSignals(True)
        self.size_spin.setValue(item.point_size)
        self.size_spin.blockSignals(False)

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

    def change_size(self, value):
        key = self.field_select.currentData()
        if key in self.items_by_key:
            item = self.items_by_key[key]
            item.point_size = value
            item.apply_font_size()

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
                    item.apply_font_size()
            self._set_background(payload.get("background"))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            QMessageBox.warning(self, "Template", "Could not load template: " + str(exc))
