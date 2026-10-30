"""Three consecutive leave-card previews for the selected print queue."""
from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QGraphicsView,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout)

from .print_preview import LeaveCardPrintPreview
from .print_queue_order import batch_queue_entries, preview_queue_slots


class ThreeCardQueuePreview(QDialog):
    def __init__(self, queue):
        super().__init__(queue)
        self.queue = queue
        self.setWindowTitle('Leave Card · Three-card Print Preview')
        self._editors = []
        self._previews = []
        self._views = []
        self._labels = []
        self._tracker = None
        self.resize(1500, 700)
        layout = QVBoxLayout(self)
        self.counter = QLabel()
        self.counter.setStyleSheet('font-size: 16px; font-weight: bold;')
        layout.addWidget(self.counter)
        row = QHBoxLayout()
        for title in ('CURRENT', 'NEXT', 'NEXT + 1'):
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            column = QVBoxLayout(frame)
            label = QLabel(title)
            label.setWordWrap(True)
            label.setStyleSheet('font-size: 15px; font-weight: bold;')
            view = QGraphicsView()
            view.setRenderHint(QPainter.RenderHint.Antialiasing)
            view.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            column.addWidget(label)
            column.addWidget(view, 1)
            row.addWidget(frame, 1)
            self._views.append(view)
            self._labels.append(label)
        layout.addLayout(row, 1)
        self.background = QCheckBox('Show card background (preview only)')
        self.background.setToolTip('Shows the card background in these previews only. The background is never printed.')
        self.background.toggled.connect(self._toggle_background)
        layout.addWidget(self.background)
        note = QLabel('The background is preview only. Print batch includes up to 10 cards starting with CURRENT. Sent to printer is recorded automatically, but does not confirm physical printing. Check cards after a jam.')
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        self.previous = QPushButton('← Previous')
        self.previous.clicked.connect(lambda: self._advance(-1))
        controls.addWidget(self.previous)
        self.next = QPushButton('Next →')
        self.next.clicked.connect(lambda: self._advance(1))
        controls.addWidget(self.next)
        self.next_batch = QPushButton('Next 10 →')
        self.next_batch.clicked.connect(lambda: self._advance(10))
        controls.addWidget(self.next_batch)
        controls.addStretch(1)
        tracker = QPushButton('Print tracker…')
        tracker.clicked.connect(self._open_tracker)
        controls.addWidget(tracker)
        self.print_current = QPushButton('Print current…')
        self.print_current.clicked.connect(self._print_current)
        controls.addWidget(self.print_current)
        if self.queue.mode.currentData() == 'away':
            all_button = QPushButton('Print batch (up to 10)…')
            all_button.setToolTip('Preview and print up to 10 cards starting with the current card.')
            all_button.clicked.connect(self._print_all)
            controls.addWidget(all_button)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        controls.addWidget(close)
        layout.addLayout(controls)
        self.finished.connect(lambda _result: self._clear_previews())
        self._refresh()

    def _clear_previews(self):
        for view in self._views:
            view.setScene(None)
        for editor in self._editors:
            editor.deleteLater()
        self._editors.clear()
        self._previews.clear()

    def _refresh(self):
        self._clear_previews()
        self.counter.setText(f'Employee {self.queue.index + 1} of {len(self.queue.entries)}')
        self.previous.setEnabled(self.queue.index > 0)
        self.next.setEnabled(self.queue.index < len(self.queue.entries) - 1)
        self.next_batch.setEnabled(self.queue.index + 10 < len(self.queue.entries))
        slots = preview_queue_slots(self.queue.entries, self.queue.index)
        for slot, view in enumerate(self._views):
            if slot >= len(slots):
                self._labels[slot].setText(('CURRENT', 'NEXT', 'NEXT + 1')[slot] + ' · No more employees')
                continue
            position, (employee_id, name) = slots[slot]
            self._labels[slot].setText(f"{('CURRENT', 'NEXT', 'NEXT + 1')[slot]} · {position + 1}. {name}")
            editor = self.queue._employee_editor(employee_id, name)
            preview = LeaveCardPrintPreview(editor)
            preview.toggle_background(self.background.isChecked())
            self._editors.append(editor)
            self._previews.append(preview)
            view.setScene(preview.scene)
        QTimer.singleShot(0, self._fit_all)

    def _fit_all(self):
        for view in self._views:
            if view.scene() is not None:
                view.fitInView(view.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_all()

    def _toggle_background(self, checked):
        for preview in self._previews:
            preview.toggle_background(checked)

    def _advance(self, direction):
        self.queue.advance(direction)
        self._refresh()

    def _open_tracker(self):
        from .print_tracker import PrintTrackerDialog
        if self._tracker is None:
            self._tracker = PrintTrackerDialog(self, self.queue)
        self._tracker.show()
        self._tracker.raise_()
        self._tracker.activateWindow()

    @staticmethod
    def _printer():
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        printer.setFullPage(True)
        return printer

    def _print_current(self):
        if not self._previews:
            return
        printer = self._printer()
        self._tag_job(printer)
        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle('Current Leave Card · Printer Preview')
        dialog.resize(1150, 830)
        # Keep the on-screen preview unchanged while rendering a background-free print.
        print_preview = LeaveCardPrintPreview(self._editors[0])
        print_preview.toggle_background(False)
        dialog.paintRequested.connect(print_preview.render_print_page)
        dialog.exec()

    def _print_all(self):
        batch = batch_queue_entries(self.queue.entries, self.queue.index)
        if not batch:
            return
        printer = self._printer()
        self._tag_job(printer)
        dialog = QPrintPreviewDialog(printer, self)
        start = self.queue.index
        first = start + 1
        dialog.setWindowTitle(f'Leave Cards {first}–{first + len(batch) - 1} · Printer Preview ({len(batch)} pages)')
        dialog.resize(1200, 850)
        dialog.paintRequested.connect(lambda target: self.queue.render_batch(target, batch))
        result = dialog.exec()
        if result != QDialog.DialogCode.Accepted:
            return
        if (printer.outputFormat() != QPrinter.OutputFormat.NativeFormat
                or bool(printer.outputFileName())
                or printer.printRange() != QPrinter.PrintRange.AllPages
                or printer.printerState() in (QPrinter.PrinterState.Error, QPrinter.PrinterState.Aborted)):
            QMessageBox.information(self, 'Print tracking', 'The batch was not marked sent because the output was a file, a partial page range, or the printer reported an error. Check and mark the cards manually.')
            return
        try:
            self.queue.mark_batch_sent(start, len(batch))
        except Exception as error:
            QMessageBox.warning(self, 'Print tracking', f'The print request was sent, but its status could not be saved: {error}')
            return
        if self._tracker is not None:
            self._tracker.refresh_card_statuses()

    def _tag_job(self, printer):
        name = 'LeaveCalendar-' + uuid4().hex
        printer.setDocName(name)
        self.queue.print_job_names.add(name)

    def closeEvent(self, event):
        self._clear_previews()
        super().closeEvent(event)
