"""Three consecutive leave-card previews for the selected print queue."""
from __future__ import annotations

import json
import sys
from uuid import uuid4

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QTimer
from PySide6.QtGui import QKeySequence, QPainter, QPageLayout, QPageSize, QShortcut
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QGraphicsView,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout)

from .print_preview import LeaveCardPrintPreview
from .print_queue_order import batch_queue_entries, preview_queue_slots, reported_queue_position

_PROGRESS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$name = $env:LEAVE_PROGRESS_DOCUMENT
$prefix = $env:LEAVE_PROGRESS_PRINTER + ', '
$job = Get-CimInstance Win32_PrintJob | Where-Object {
    $_.Document -eq $name -and $_.Name.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
} | Select-Object -First 1
if ($null -eq $job) { '{"found":false}' }
else {
    [PSCustomObject]@{found=$true; printed=$job.PagesPrinted; total=$job.TotalPages; status=[string]$job.JobStatus} | ConvertTo-Json -Compress
}
'''


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
        self._direct_printer = None
        self._direct_ready = False
        self._direct_busy = False
        self._last_print_end = -1
        self._progress = None
        self._progress_process = QProcess(self)
        self._progress_process.finished.connect(self._progress_finished)
        self._progress_process.errorOccurred.connect(self._progress_error)
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._poll_progress)
        self.resize(1500, 700)
        layout = QVBoxLayout(self)
        self.counter = QLabel()
        self.counter.setStyleSheet('font-size: 16px; font-weight: bold;')
        layout.addWidget(self.counter)
        self.progress_label = QLabel('Printer page progress: not tracking.')
        self.progress_label.setWordWrap(True)
        layout.addWidget(self.progress_label)
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
        note = QLabel('The background is preview only. Print the first batch with printer settings, then press Enter to load and send the next 10 directly. Sent does not confirm physical printing; check cards after a jam.')
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
        self.next_batch.clicked.connect(self._load_next_batch)
        controls.addWidget(self.next_batch)
        self.direct_button = QPushButton('Print next 10 (Enter)')
        self.direct_button.setEnabled(False)
        self.direct_button.setAutoDefault(False)
        self.direct_button.clicked.connect(self._print_next_direct)
        controls.addWidget(self.direct_button)
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
        self._enter_shortcuts = []
        for key in ('Return', 'Enter'):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setAutoRepeat(False)
            shortcut.activated.connect(self._print_next_direct)
            self._enter_shortcuts.append(shortcut)
        self.finished.connect(lambda _result: self._stop_progress())
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
        self.next_batch.setEnabled(self.queue.next_batch_loader is not None or self.queue.index + 10 < len(self.queue.entries))
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
        self._stop_progress('Live following paused for manual navigation.')
        self.queue.advance(direction)
        self._refresh()

    def _load_next_batch(self):
        self._set_direct_ready(False)
        self._stop_progress('Live following stopped when changing batches.')
        if self.queue.next_batch_loader is None:
            if self.queue.index + 1 < len(self.queue.entries):
                self._advance(1)
                return True
            QMessageBox.information(self, 'Print queue', 'There are no more matching cards in this queue.')
            return False
        if not self.queue.load_next_batch():
            self._refresh()
            QMessageBox.information(self, 'Print queue', 'There are no more matching cards in this queue.')
            return False
        if self._tracker is not None:
            self._tracker.reload_batch()
        self._refresh()
        return True

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
        self._stop_progress('Live following stopped for a new print request.')
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
        self._set_direct_ready(False)
        self._stop_progress('Live following stopped for a new print request.')
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
        self._direct_printer = printer
        self._batch_submitted(start, len(batch))

    def _set_direct_ready(self, ready):
        self._direct_ready = ready
        self.direct_button.setEnabled(ready and not self._direct_busy)

    def _batch_submitted(self, start, count):
        self._last_print_end = start + count - 1
        self.queue.advance(self._last_print_end - self.queue.index)
        self._refresh()
        self.progress_label.setText(f'Batch sent; showing its last card ({count} card(s)). Press Enter to send the next 10. Verify physical cards after any interruption.')
        self._set_direct_ready(True)

    def _print_next_direct(self):
        if not self._direct_ready or self._direct_busy or self._direct_printer is None:
            return
        self._direct_busy = True
        self._set_direct_ready(False)
        try:
            if not self._load_next_batch():
                return
            start = self.queue.index
            batch = batch_queue_entries(self.queue.entries, start)
            if not batch:
                return
            printer = self._direct_printer
            self._tag_job(printer)
            if not self.queue.render_batch(printer, batch) or printer.printerState() in (QPrinter.PrinterState.Error, QPrinter.PrinterState.Aborted):
                QMessageBox.warning(self, 'Print queue', 'Windows reported a printing error. The batch was not marked sent; check the printer and use Print batch to retry.')
                return
            try:
                self.queue.mark_batch_sent(start, len(batch))
            except Exception as error:
                QMessageBox.warning(self, 'Print tracking', f'The batch was sent, but its status could not be saved: {error}')
                return
            if self._tracker is not None:
                self._tracker.refresh_card_statuses()
            self._batch_submitted(start, len(batch))
        except Exception as error:
            QMessageBox.warning(self, 'Print queue', f'Could not send the next batch: {error}')
        finally:
            self._direct_busy = False
            self.direct_button.setEnabled(self._direct_ready)

    def _tag_job(self, printer):
        name = 'LeaveCalendar-' + uuid4().hex
        printer.setDocName(name)
        self.queue.print_job_names.add(name)
        return name

    def _start_progress(self, printer, document, start, count):
        self._stop_progress()
        if sys.platform != 'win32' or not printer:
            self.progress_label.setText('Live page progress is unavailable. Use Next to follow manually.')
            return
        self._progress = {'printer': printer, 'document': document, 'start': start,
                          'count': count, 'missing': 0, 'last': 0}
        self.progress_label.setText('Waiting for Windows page progress; reported progress may lead the physical printer.')
        self._progress_timer.start(1500)
        self._poll_progress()

    def _stop_progress(self, message=None):
        self._progress_timer.stop()
        self._progress = None
        if self._progress_process.state() != QProcess.ProcessState.NotRunning:
            self._progress_process.kill()
            self._progress_process.waitForFinished(1000)
        if message:
            self.progress_label.setText(message)

    def _poll_progress(self):
        if self._progress is None or self._progress_process.state() != QProcess.ProcessState.NotRunning:
            return
        env = QProcessEnvironment.systemEnvironment()
        env.insert('LEAVE_PROGRESS_DOCUMENT', self._progress['document'])
        env.insert('LEAVE_PROGRESS_PRINTER', self._progress['printer'])
        self._progress_process.setProcessEnvironment(env)
        self._progress_process.start('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', _PROGRESS_SCRIPT])

    def _progress_error(self, _error):
        if self._progress is not None:
            self._stop_progress('Windows page progress is unavailable. Use Next to follow manually.')

    def _progress_finished(self, code, _exit_status):
        progress = self._progress
        if progress is None:
            return
        try:
            if code:
                raise ValueError('status query failed')
            data = json.loads(bytes(self._progress_process.readAllStandardOutput()).decode('utf-8-sig'))
            if not data.get('found'):
                progress['missing'] += 1
                if progress['missing'] >= 5:
                    self._stop_progress('Windows no longer reports this job. Physical completion is unknown; check the cards and use Next manually.')
                return
            progress['missing'] = 0
            printed, total = int(data['printed'] or 0), int(data['total'] or 0)
            position = reported_queue_position(progress['start'], progress['count'], printed, total)
            if position is None or printed < progress['last']:
                self._stop_progress('This printer does not provide usable per-page progress. Use Next to follow manually.')
                return
            progress['last'] = printed
            status = data.get('status') or 'Unknown'
            self.progress_label.setText(f'Windows reports {printed} of {total} pages processed · {status}. This may lead the physical printer.')
            if position != self.queue.index:
                self.queue.advance(position - self.queue.index)
                self._refresh()
            if printed == total:
                self._stop_progress('Windows reports all pages processed; verify the physical cards before continuing.')
        except (ValueError, KeyError, TypeError, UnicodeError):
            self._stop_progress('Windows page progress is unavailable. Use Next to follow manually.')

    def closeEvent(self, event):
        self._stop_progress()
        self._clear_previews()
        super().closeEvent(event)
