"""Sequential or unattended printing for checked Personnel Files employees."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPageSize, QPageLayout
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (
    QComboBox, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
)

from .print_template_editor import TEMPLATE_FILE, TemplateEditorDialog
from .print_preview import LeaveCardPrintPreview, PAGE_W, PAGE_H


class PersonnelPrintQueue(QDialog):
    def __init__(self, parent, entries, repository):
        super().__init__(parent)
        self.setWindowTitle("Personnel Files · Print Queue")
        self.resize(590, 265)
        self.entries = entries
        self.repository = repository
        self.index = 0
        layout = QVBoxLayout(self)
        self.counter = QLabel()
        self.counter.setStyleSheet("font-size:16px;font-weight:bold")
        self.person = QLabel()
        self.person.setStyleSheet("font-size:20px;font-weight:bold")
        layout.addWidget(self.counter)
        layout.addWidget(self.person)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Printing Mode"))
        self.mode = QComboBox()
        self.mode.addItem("Print Away (default)", "away")
        self.mode.addItem("Ask Before Printing", "ask")
        self.mode.currentIndexChanged.connect(self.update_mode)
        mode_row.addWidget(self.mode, 1)
        layout.addLayout(mode_row)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        controls = QHBoxLayout()
        self.previous = QPushButton("← Previous")
        self.previous.clicked.connect(lambda: self.advance(-1))
        self.preview = QPushButton("Print Preview / Print…")
        self.preview.clicked.connect(self.open_preview)
        self.start = QPushButton("Start Printing")
        self.start.clicked.connect(self.start_printing)
        self.next = QPushButton("Next →")
        self.next.clicked.connect(lambda: self.advance(1))
        controls.addWidget(self.previous)
        controls.addWidget(self.preview)
        controls.addWidget(self.start)
        controls.addWidget(self.next)
        layout.addLayout(controls)
        self.update_mode()
        self.refresh()

    def update_mode(self):
        away = self.mode.currentData() == "away"
        self.description.setText(
            "Print Away: preview all checked employees as Letter-landscape pages. "
            "Choose printer and settings once, then print the entire batch without per-card prompts."
            if away else
            "Ask Before Printing: open the current employee's preview. "
            "Print only after you approve it, then use Next for the next card."
        )
        self.start.setText("Preview All Checked" if away else "Review Current Card")
        self.preview.setVisible(not away)

    def refresh(self):
        employee_id, name = self.entries[self.index]
        self.counter.setText(f"Employee {self.index + 1} of {len(self.entries)}")
        self.person.setText(f"{name}\n{employee_id}")
        self.previous.setEnabled(self.index > 0)
        self.next.setEnabled(self.index < len(self.entries) - 1)

    def advance(self, direction):
        self.index = max(0, min(len(self.entries) - 1, self.index + direction))
        self.refresh()

    def _employee_editor(self, employee_id, name):
        employee = self.repository.employee_by_id(employee_id) if self.repository else None
        if employee is None:
            employee = SimpleNamespace(name=name, assumption_date=None)
        return TemplateEditorDialog(self, employee=employee)

    def open_preview(self):
        if not TEMPLATE_FILE.is_file():
            QMessageBox.warning(self, "Print Queue", "Save a print template in Editor Mode first.")
            return
        employee_id, name = self.entries[self.index]
        editor = self._employee_editor(employee_id, name)
        LeaveCardPrintPreview(editor).exec()

    def start_printing(self):
        if self.mode.currentData() == "ask":
            self.open_preview()
            return
        if not TEMPLATE_FILE.is_file():
            QMessageBox.warning(self, "Print Queue", "Save a print template in Editor Mode first.")
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        printer.setFullPage(True)
        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle(f"Leave Cards · Batch Print Preview ({len(self.entries)} pages)")
        dialog.resize(1200, 850)
        dialog.paintRequested.connect(self.render_batch)
        dialog.exec()

    def render_batch(self, printer):
        """Called for both preview rendering and actual printing by Qt."""
        painter = QPainter()
        if not painter.begin(printer):
            return
        try:
            for index, (employee_id, name) in enumerate(self.entries):
                if index and not printer.newPage():
                    break
                editor = self._employee_editor(employee_id, name)
                preview = LeaveCardPrintPreview(editor)
                preview.toggle_background(False)
                preview.scene.render(
                    painter,
                    QRectF(0, 0, printer.width(), printer.height()),
                    QRectF(0, 0, PAGE_W, PAGE_H),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                )
        finally:
            painter.end()
