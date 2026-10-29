"""Sequential print queue for checked Personnel Files employees."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
from .print_template_editor import TEMPLATE_FILE, TemplateEditorDialog
from .print_preview import LeaveCardPrintPreview


class PersonnelPrintQueue(QDialog):
    def __init__(self, parent, entries, repository):
        super().__init__(parent)
        self.setWindowTitle("Personnel Files · Print Queue")
        self.resize(550, 230)
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
        layout.addWidget(QLabel("Print Preview opens text-only by default. Print each card, then move to Next."))
        controls = QHBoxLayout()
        self.previous = QPushButton("← Previous")
        self.previous.clicked.connect(lambda: self.advance(-1))
        self.preview = QPushButton("Print Preview / Print…")
        self.preview.clicked.connect(self.open_preview)
        self.next = QPushButton("Next →")
        self.next.clicked.connect(lambda: self.advance(1))
        controls.addWidget(self.previous)
        controls.addWidget(self.preview)
        controls.addWidget(self.next)
        layout.addLayout(controls)
        self.refresh()

    def refresh(self):
        employee_id, name = self.entries[self.index]
        self.counter.setText(f"Employee {self.index + 1} of {len(self.entries)}")
        self.person.setText(f"{name}\n{employee_id}")
        self.previous.setEnabled(self.index > 0)
        self.next.setEnabled(self.index < len(self.entries) - 1)

    def advance(self, direction):
        self.index = max(0, min(len(self.entries) - 1, self.index + direction))
        self.refresh()

    def open_preview(self):
        if not TEMPLATE_FILE.is_file():
            QMessageBox.warning(self, "Print Queue", "Save a print template in Editor Mode first.")
            return
        employee_id, name = self.entries[self.index]
        employee = self.repository.employee_by_id(employee_id) if self.repository else None
        if employee is None:
            from types import SimpleNamespace
            employee = SimpleNamespace(name=name, assumption_date=None)
        editor = TemplateEditorDialog(self, employee=employee)
        LeaveCardPrintPreview(editor).exec()
