from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class LeaveCardPreviewPage(QWidget):
    """Read-only local leave-card viewer.

    Source documents are loaded into memory only. This page never writes a file,
    touches the leave database, or changes any draft/history state.
    """

    back_requested = Signal()

    DEFAULT_CROP = (0, 14, 28, 86)  # x, y, width, height as page percentages

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_image = QImage()
        self._source_path = ""
        self._show_history = False
        self._build_ui()
        self._apply_default_crop()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        header = QHBoxLayout()
        back_button = QPushButton("← Calendar Mode")
        back_button.clicked.connect(self.back_requested.emit)
        title = QLabel("Leave Card Preview")
        title.setStyleSheet("font-size:22px;font-weight:800;color:#f8fafc")
        self.safety_label = QLabel("READ-ONLY · LOCAL FILE · NO SAVING")
        self.safety_label.setStyleSheet(
            "background:#0f3d2e;color:#86efac;border-radius:8px;padding:6px 10px;"
            "font-weight:800"
        )
        header.addWidget(back_button)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.safety_label)
        root.addLayout(header)

        controls = QHBoxLayout()
        open_button = QPushButton("Open Card File…")
        open_button.clicked.connect(self.open_card_file)
        self.full_button = QPushButton("Full Card")
        self.full_button.setCheckable(True)
        self.full_button.setChecked(True)
        self.full_button.clicked.connect(lambda: self.set_view(False))
        self.history_button = QPushButton("History Preview")
        self.history_button.setCheckable(True)
        self.history_button.clicked.connect(lambda: self.set_view(True))
        self.adjust_button = QPushButton("Adjust History Crop")
        self.adjust_button.setCheckable(True)
        self.adjust_button.toggled.connect(self.crop_group.setVisible)
        reset_button = QPushButton("Reset Default Crop")
        reset_button.clicked.connect(self.reset_crop)
        controls.addWidget(open_button)
        controls.addWidget(self.full_button)
        controls.addWidget(self.history_button)
        controls.addWidget(self.adjust_button)
        controls.addWidget(reset_button)
        controls.addSpacing(12)
        controls.addWidget(QLabel("Zoom"))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(35, 180)
        self.zoom_slider.setValue(80)
        self.zoom_slider.setMinimumWidth(160)
        self.zoom_slider.valueChanged.connect(self._render_image)
        self.zoom_value = QLabel("80%")
        self.zoom_value.setMinimumWidth(42)
        controls.addWidget(self.zoom_slider)
        controls.addWidget(self.zoom_value)
        controls.addStretch(1)
        root.addLayout(controls)

        self.source_label = QLabel("No card loaded. Open a local PDF or image to preview it.")
        self.source_label.setStyleSheet("color:#94a3b8;font-weight:700")
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.source_label)

        self.crop_group = QGroupBox("History Crop · percentages of the first page")
        crop_layout = QGridLayout(self.crop_group)
        self.crop_x = self._crop_spinbox("Left")
        self.crop_y = self._crop_spinbox("Top")
        self.crop_w = self._crop_spinbox("Width")
        self.crop_h = self._crop_spinbox("Height")
        for column, (caption, control) in enumerate(
            (("Left", self.crop_x), ("Top", self.crop_y), ("Width", self.crop_w), ("Height", self.crop_h))
        ):
            crop_layout.addWidget(QLabel(caption), 0, column)
            crop_layout.addWidget(control, 1, column)
        crop_note = QLabel(
            "Default focuses on the left-side Name / Position / Status / Period / Particulars / Remarks history. "
            "VL, SL, balance, and undertime columns stay outside the crop."
        )
        crop_note.setWordWrap(True)
        crop_note.setStyleSheet("color:#94a3b8;font-size:11px")
        crop_layout.addWidget(crop_note, 2, 0, 1, 4)
        self.crop_group.hide()
        root.addWidget(self.crop_group)

        self.canvas = QLabel("Open a card file to begin.")
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.canvas.setStyleSheet(
            "background:#0b1016;color:#94a3b8;border:1px solid #334155;"
            "padding:16px"
        )
        self.canvas.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.canvas)
        root.addWidget(self.scroll, 1)

    def _crop_spinbox(self, _caption: str) -> QSpinBox:
        box = QSpinBox()
        box.setRange(0, 100)
        box.setSuffix("%")
        box.valueChanged.connect(self._render_image)
        return box

    def _apply_default_crop(self) -> None:
        for control, value in zip(
            (self.crop_x, self.crop_y, self.crop_w, self.crop_h),
            self.DEFAULT_CROP,
        ):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)

    def reset_crop(self) -> None:
        self._apply_default_crop()
        self._render_image()

    def open_card_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Open Leave Card Preview",
            "",
            "Leave Cards (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
            "PDF Files (*.pdf);;Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if not path:
            return
        try:
            image = self._load_first_page(Path(path))
        except RuntimeError as error:
            self._source_image = QImage()
            self.source_label.setText(f"Could not open card: {error}")
            self.canvas.setPixmap(QPixmap())
            self.canvas.setText("Preview unavailable.")
            return
        self._source_path = path
        self._source_image = image
        self.source_label.setText(
            f"Read-only preview · {Path(path).name} · source file is unchanged"
        )
        self._render_image()

    @staticmethod
    def _load_first_page(path: Path) -> QImage:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                from PySide6.QtPdf import QPdfDocument
            except ImportError as error:
                raise RuntimeError("PDF preview support is not available in this PySide6 installation.") from error
            document = QPdfDocument()
            document.load(str(path))
            if document.pageCount() < 1:
                raise RuntimeError("The PDF has no readable first page.")
            page_size = document.pagePointSize(0)
            rendered_size = page_size.toSize() * 2
            image = document.render(0, rendered_size)
            if image.isNull():
                raise RuntimeError("The first PDF page could not be rendered.")
            return image

        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            raise RuntimeError(reader.errorString() or "The image could not be read.")
        return image

    def set_view(self, history: bool) -> None:
        self._show_history = history
        self.full_button.blockSignals(True)
        self.history_button.blockSignals(True)
        self.full_button.setChecked(not history)
        self.history_button.setChecked(history)
        self.full_button.blockSignals(False)
        self.history_button.blockSignals(False)
        self._render_image()

    def _history_crop(self) -> QImage:
        image = self._source_image
        if image.isNull():
            return image
        width = image.width()
        height = image.height()
        left = round(width * self.crop_x.value() / 100)
        top = round(height * self.crop_y.value() / 100)
        crop_width = max(1, round(width * self.crop_w.value() / 100))
        crop_height = max(1, round(height * self.crop_h.value() / 100))
        left = min(left, width - 1)
        top = min(top, height - 1)
        crop_width = min(crop_width, width - left)
        crop_height = min(crop_height, height - top)
        return image.copy(left, top, crop_width, crop_height)

    def _render_image(self) -> None:
        self.zoom_value.setText(f"{self.zoom_slider.value()}%")
        if self._source_image.isNull():
            return
        image = self._history_crop() if self._show_history else self._source_image
        scale = self.zoom_slider.value() / 100
        target_width = max(1, round(image.width() * scale))
        target_height = max(1, round(image.height() * scale))
        scaled = image.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.canvas.setText("")
        self.canvas.setPixmap(QPixmap.fromImage(scaled))
        self.canvas.resize(scaled.size())
