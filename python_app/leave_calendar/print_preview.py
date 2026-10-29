"""Print preview and printing for Letter-landscape leave card templates."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QBrush, QPixmap, QTransform
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PySide6.QtGui import QPageSize, QPageLayout
from PySide6.QtWidgets import (
    QDialog, QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QGraphicsTextItem, QHBoxLayout, QPushButton, QVBoxLayout, QLabel, QMessageBox,
)

PAGE_W, PAGE_H = 279.4, 215.9


class LeaveCardPrintPreview(QDialog):
    def __init__(self, editor):
        super().__init__(editor)
        self.setWindowTitle("Leave Card · Print Preview")
        self.resize(1150, 830)
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, PAGE_W, PAGE_H)
        self.scene.setBackgroundBrush(QBrush(QColor("white")))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.background = None
        self.show_bg = True

        if editor.background is not None:
            source = editor.background.pixmap()
            self.background = QGraphicsPixmapItem(QPixmap(source))
            self.background.setTransform(QTransform.fromScale(
                PAGE_W / source.width(), PAGE_H / source.height()
            ))
            self.background.setZValue(-10)
            self.scene.addItem(self.background)

        for source in editor.items_by_key.values():
            item = QGraphicsTextItem(source.toPlainText())
            item.setFont(source.font())
            item.document().setDocumentMargin(0)
            item.setDefaultTextColor(QColor("#000000"))
            item.setPos(source.pos())
            self.scene.addItem(item)

        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.bg_button = QPushButton("View: With BG")
        self.bg_button.setCheckable(True)
        self.bg_button.setChecked(True)
        self.bg_button.clicked.connect(self.toggle_background)
        controls.addWidget(self.bg_button)
        controls.addWidget(QLabel("11 × 8.5 in · Letter Landscape"))
        controls.addStretch()
        print_button = QPushButton("Print…")
        print_button.clicked.connect(self.print_page)
        controls.addWidget(print_button)
        root.addLayout(controls)
        root.addWidget(self.view, 1)
        root.addWidget(QLabel(
            "With BG prints the scanned card image and text. Without BG prints text only "
            "for an existing physical leave card."
        ))

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_page()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_page()

    def fit_page(self):
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def toggle_background(self, checked):
        self.show_bg = checked
        if self.background is not None:
            self.background.setVisible(checked)
        self.bg_button.setText("View: With BG" if checked else "View: Without BG")

    def print_page(self):
        """Use Qt's print preview so the page is visible before printing."""
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        printer.setFullPage(True)
        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle("Leave Card · Actual Print Preview")
        dialog.resize(1150, 830)
        dialog.paintRequested.connect(self.render_print_page)
        dialog.exec()

    def render_print_page(self, printer):
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "Print Preview", "Unable to render the print page.")
            return
        try:
            target = QRectF(0, 0, printer.width(), printer.height())
            self.scene.render(
                painter, target, QRectF(0, 0, PAGE_W, PAGE_H),
                Qt.AspectRatioMode.IgnoreAspectRatio,
            )
        finally:
            painter.end()
