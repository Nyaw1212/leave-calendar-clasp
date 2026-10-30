"""Session print checklist and Windows printer status monitor."""
from __future__ import annotations

import json
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtPrintSupport import QPrinterInfo
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

# Printer names are passed via the process environment, not interpolated into code.
_STATUS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$name = $env:LEAVE_TRACKER_PRINTER
$printer = Get-Printer -Name $name -ErrorAction Stop
$jobs = @(Get-PrintJob -PrinterName $name -ErrorAction Stop | ForEach-Object {
    [PSCustomObject]@{ Name = $_.DocumentName; Status = [string]$_.JobStatus }
})
[PSCustomObject]@{ PrinterStatus = [string]$printer.PrinterStatus; Jobs = $jobs } |
    ConvertTo-Json -Depth 4 -Compress
'''

# Only act on exact random document names created by this queue session.
_CONTROL_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$names = @($env:LEAVE_TRACKER_JOBS | ConvertFrom-Json)
$jobs = @(Get-PrintJob -PrinterName $env:LEAVE_TRACKER_PRINTER | Where-Object { $names -contains $_.DocumentName })
foreach ($job in $jobs) {
    switch ($env:LEAVE_TRACKER_ACTION) {
        'pause' { $job | Suspend-PrintJob -ErrorAction Stop }
        'resume' { $job | Resume-PrintJob -ErrorAction Stop }
        'stop' { $job | Remove-PrintJob -ErrorAction Stop }
    }
}
Write-Output $jobs.Count
'''


class PrintTrackerDialog(QDialog):
    def __init__(self, parent, queue):
        super().__init__(parent)
        self.queue = queue
        self.setWindowTitle('Print tracker')
        self.resize(780, 600)
        layout = QVBoxLayout(self)
        info = QLabel('Select the same printer used in the print dialog. Windows status depends on printer and driver reporting. Confirm printed cards manually. VER2 confirmations are saved for this balance date.')
        info.setWordWrap(True)
        layout.addWidget(info)
        row = QHBoxLayout()
        row.addWidget(QLabel('Monitor printer:'))
        self.printers = QComboBox()
        self.printers.addItems(QPrinterInfo.availablePrinterNames())
        default = QPrinterInfo.defaultPrinterName()
        if default:
            self.printers.setCurrentText(default)
        row.addWidget(self.printers, 1)
        refresh = QPushButton('Refresh status')
        refresh.clicked.connect(self._poll)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.status = QLabel('Printer status not checked yet.')
        self.status.setWordWrap(True)
        self.status.setStyleSheet('font-size: 15px; font-weight: bold;')
        layout.addWidget(self.status)
        self.jobs = QLabel()
        self.jobs.setWordWrap(True)
        layout.addWidget(self.jobs)
        job_controls = QHBoxLayout()
        for label, action in [('Pause jobs', 'pause'), ('Resume jobs', 'resume'), ('Stop jobs', 'stop')]:
            button = QPushButton(label)
            button.setToolTip('Controls only matching Leave Calendar jobs from this queue session on the selected printer.')
            button.clicked.connect(lambda _checked=False, a=action: self._control(a))
            job_controls.addWidget(button)
        layout.addLayout(job_controls)
        self.action_status = QLabel('Pause and stop affect only jobs from this queue session still in the Windows queue.')
        self.action_status.setWordWrap(True)
        layout.addWidget(self.action_status)
        self.table = QTableWidget(len(queue.entries), 3)
        self.table.setHorizontalHeaderLabels(['#', 'Name', 'Card status'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(1, 360)
        layout.addWidget(self.table, 1)
        for i, (_, name) in enumerate(queue.entries):
            for col, value in enumerate((str(i + 1), name, queue.print_tracker_status[i])):
                self.table.setItem(i, col, QTableWidgetItem(value))
        self.table.selectRow(queue.index)
        buttons = QHBoxLayout()
        for label, status in [('Mark confirmed printed', 'Confirmed printed'),
                              ('Mark needs review', 'Needs review'),
                              ('Clear status', 'Not confirmed')]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, s=status: self._mark(s))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.control_process = QProcess(self)
        self.control_process.finished.connect(self._control_finished)
        self.control_process.errorOccurred.connect(lambda _error: self.action_status.setText('Could not run print job control.'))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.printers.currentTextChanged.connect(self._poll)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(5000)
        self._poll()

    def closeEvent(self, event):
        self.timer.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        super().closeEvent(event)

    def _mark(self, status):
        for row in {index.row() for index in self.table.selectionModel().selectedRows()}:
            self.queue.mark_print_status(row, status)
            self.table.item(row, 2).setText(status)

    def _control(self, action):
        if sys.platform != 'win32' or not self.printers.currentText():
            self.action_status.setText('Select a Windows printer first.')
            return
        if self.control_process.state() != QProcess.ProcessState.NotRunning:
            return
        if not self.queue.print_job_names:
            self.action_status.setText('No print jobs have been started from this queue session.')
            return
        env = QProcessEnvironment.systemEnvironment()
        env.insert('LEAVE_TRACKER_PRINTER', self.printers.currentText())
        env.insert('LEAVE_TRACKER_JOBS', json.dumps(sorted(self.queue.print_job_names)))
        env.insert('LEAVE_TRACKER_ACTION', action)
        self.control_process.setProcessEnvironment(env)
        self.control_process.setProperty('action', action)
        self.action_status.setText(f'Requesting {action} from Windows…')
        self.control_process.start('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', _CONTROL_SCRIPT])

    def _control_finished(self, code, _exit_status):
        if code:
            self.action_status.setText('Windows could not control this job. Check the printer, permissions, and Windows print queue.')
            return
        count = bytes(self.control_process.readAllStandardOutput()).decode('utf-8', errors='replace').strip()
        if count == '0':
            self.action_status.setText('No matching jobs remain in the selected Windows print queue. A job may already have reached the printer.')
        else:
            self.action_status.setText(f"Windows accepted {self.control_process.property('action')} for {count} matching job(s). Check the physical cards.")
        self._poll()

    def _poll(self):
        if not self.isVisible() or self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if sys.platform != 'win32':
            self.status.setText('Automatic printer monitoring is available on Windows.')
            return
        name = self.printers.currentText()
        if not name:
            self.status.setText('No printer selected.')
            return
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('LEAVE_TRACKER_PRINTER', name)
        self.process.setProcessEnvironment(environment)
        self.process.setProperty('monitoredPrinter', name)
        self.process.start('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', _STATUS_SCRIPT])

    def _process_error(self, _error):
        self.status.setText('Unable to check Windows printer status. Check the Windows print queue.')

    def _finished(self, code, _exit_status):
        if self.process.property('monitoredPrinter') != self.printers.currentText():
            self._poll()
            return
        try:
            if code != 0:
                raise ValueError('Printer status unavailable')
            data = json.loads(bytes(self.process.readAllStandardOutput()).decode('utf-8-sig'))
            printer_status = data.get('PrinterStatus') or 'Unknown'
            self.status.setText(f'Windows printer status: {printer_status}')
            jobs = data.get('Jobs') or []
            if isinstance(jobs, dict):
                jobs = [jobs]
            text = '; '.join(f"{j.get('Name') or 'Document'}: {j.get('Status') or 'Unknown'}" for j in jobs[:5])
            self.jobs.setText(f'Windows queue: {text}' if text else 'Windows queue: no jobs currently reported.')
        except (ValueError, TypeError, UnicodeError, AttributeError):
            self.status.setText('Unable to check Windows printer status. Check the Windows print queue.')
            self.jobs.clear()
