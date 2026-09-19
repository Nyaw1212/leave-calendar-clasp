from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPainter, QPixmap
from .card_attachment_store import CardAttachmentError, CardAttachmentStore

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

    Source documents are shown read-only. Attached cards are copied locally for
    the selected employee; this page never changes the source document, touches
    the leave database, or changes any draft/history state.
    """

    back_requested = Signal()

    DEFAULT_HISTORY_LEFT = 0
    DEFAULT_HISTORY_TOP = 0
    DEFAULT_HISTORY_WIDTH = 28
    DEFAULT_HISTORY_HEIGHT = 100
    DEFAULT_MARK_LEFT = 58
    DEFAULT_MARK_WIDTH = 18

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self.embedded = embedded
        self._source_image = QImage()
        self._source_path = ""
        self._attached_employee_id = ""
        self._employee_id = ""
        self._employee_name = ""
        self._attachment_store = CardAttachmentStore()
        self._page_index = 0
        self._page_count = 0
        self._show_history = False
        self._build_ui()
        self._apply_default_crop()
        self._update_page_controls()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        header = QHBoxLayout()
        back_button = QPushButton("← Calendar Mode")
        back_button.clicked.connect(self.back_requested.emit)
        title = QLabel("Leave Card Preview")
        title.setStyleSheet("font-size:22px;font-weight:800;color:#f8fafc")
        self.safety_label = QLabel("READ-ONLY SOURCE · LOCAL ATTACHMENT")
        self.safety_label.setStyleSheet(
            "background:#0f3d2e;color:#86efac;border-radius:8px;padding:6px 10px;"
            "font-weight:800"
        )
        self.maximize_button = QPushButton("Maximize Window")
        self.maximize_button.clicked.connect(self.toggle_maximize_window)
        if not self.embedded:
            header.addWidget(back_button)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.maximize_button)
        header.addWidget(self.safety_label)
        root.addLayout(header)

        controls = QHBoxLayout()
        open_button = QPushButton("Open Temporary File…")
        open_button.clicked.connect(self.open_card_file)
        self.attach_button = QPushButton("Attach to Employee…")
        self.attach_button.setToolTip(
            "Copy a local PDF or image into the app's local employee attachment folder."
        )
        self.attach_button.setEnabled(False)
        self.attach_button.clicked.connect(self.attach_card_file)
        self.full_button = QPushButton("Full Card")
        self.full_button.setCheckable(True)
        self.full_button.setChecked(True)
        self.full_button.clicked.connect(lambda: self.set_view(False))
        self.history_button = QPushButton("History Preview")
        self.history_button.setCheckable(True)
        self.history_button.clicked.connect(lambda: self.set_view(True))
        self.adjust_button = QPushButton("Adjust History Crop")
        self.adjust_button.setCheckable(True)
        reset_button = QPushButton("Reset Default Crop")
        reset_button.clicked.connect(self.reset_crop)
        self.previous_page_button = QPushButton("← Previous Page")
        self.previous_page_button.clicked.connect(lambda: self.change_page(-1))
        self.next_page_button = QPushButton("Next Page →")
        self.next_page_button.clicked.connect(lambda: self.change_page(1))
        self.page_label = QLabel("Page —")
        self.page_label.setMinimumWidth(88)
        controls.addWidget(open_button)
        controls.addWidget(self.attach_button)
        controls.addWidget(self.full_button)
        controls.addWidget(self.history_button)
        controls.addWidget(self.adjust_button)
        controls.addWidget(reset_button)
        controls.addSpacing(12)
        controls.addWidget(self.previous_page_button)
        controls.addWidget(self.page_label)
        controls.addWidget(self.next_page_button)
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
        self.crop_x = self._crop_spinbox("History Left")
        self.crop_w = self._crop_spinbox("History Width")
        self.mark_x = self._crop_spinbox("VL/SL Left")
        for column, (caption, control) in enumerate(
            (("History Left", self.crop_x), ("History Width", self.crop_w), ("VL/SL Left", self.mark_x))
        ):
            crop_layout.addWidget(QLabel(caption), 0, column)
            crop_layout.addWidget(control, 1, column)
        crop_note = QLabel(
            "The middle is omitted in the display only; the VL/SL marking strip is joined beside "
            "Inclusive Dates and Particulars. The source file is never changed."
        )
        crop_note.setWordWrap(True)
        crop_note.setStyleSheet("color:#94a3b8;font-size:11px")
        crop_layout.addWidget(crop_note, 2, 0, 1, 3)
        self.crop_group.hide()
        self.adjust_button.toggled.connect(self.crop_group.setVisible)
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

    def toggle_maximize_window(self) -> None:
        target = self.window()
        if target.isMaximized():
            target.showNormal()
            self.maximize_button.setText("Maximize Window")
        else:
            target.showMaximized()
            self.maximize_button.setText("Restore Window")

    def _crop_spinbox(self, _caption: str) -> QSpinBox:
        box = QSpinBox()
        box.setRange(0, 100)
        box.setSuffix("%")
        box.valueChanged.connect(self._render_image)
        return box

    def _apply_default_crop(self) -> None:
        for control, value in (
            (self.crop_x, self.DEFAULT_HISTORY_LEFT),
            (self.crop_w, self.DEFAULT_HISTORY_WIDTH),
            (self.mark_x, self.DEFAULT_MARK_LEFT),
        ):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)

    def reset_crop(self) -> None:
        self._apply_default_crop()
        self._render_image()

    def set_employee_context(self, employee_id: str, employee_name: str) -> None:
        """Load this employee's attached card, if one exists."""
        self._employee_id = str(employee_id).strip()
        self._employee_name = str(employee_name).strip()
        self.attach_button.setEnabled(bool(self._employee_id))
        attached_path = self._attachment_store.path_for(self._employee_id)
        if attached_path is not None:
            self._load_source_path(str(attached_path), attached=True)
        elif self._attached_employee_id and self._attached_employee_id != self._employee_id:
            self._clear_preview(
                f"No card attached for {self._employee_name or "this employee"}."
            )

    @staticmethod
    def _choose_card_file(parent: QWidget, title: str) -> str:
        path, _selected_filter = QFileDialog.getOpenFileName(
            parent,
            title,
            "",
            "Leave Cards (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
            "PDF Files (*.pdf);;Image Files (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        return path

    def open_card_file(self) -> None:
        path = self._choose_card_file(self, "Open Leave Card Preview")
        if path:
            self._load_source_path(path, attached=False)

    def attach_card_file(self) -> None:
        if not self._employee_id:
            self.source_label.setText("Select an employee before attaching a leave card.")
            return
        path = self._choose_card_file(
            self,
            f"Attach Leave Card · {self._employee_name or self._employee_id}",
        )
        if not path:
            return
        try:
            attached_path = self._attachment_store.attach(self._employee_id, path)
        except CardAttachmentError as error:
            self.source_label.setText(str(error))
            return
        self._load_source_path(str(attached_path), attached=True)

    def _load_source_path(self, path: str, *, attached: bool) -> None:
        self._source_path = path
        self._attached_employee_id = self._employee_id if attached else ""
        self._page_index = 0
        self._load_current_page()

    def _clear_preview(self, message: str) -> None:
        self._source_image = QImage()
        self._source_path = ""
        self._attached_employee_id = ""
        self._page_index = 0
        self._page_count = 0
        self.canvas.setPixmap(QPixmap())
        self.canvas.setText("Open or attach a card file to begin.")
        self.source_label.setText(message)
        self._update_page_controls()

    def change_page(self, change: int) -> None:
        target = self._page_index + change
        if not self._source_path or target < 0 or target >= self._page_count:
            return
        self._page_index = target
        self._load_current_page()

    def _load_current_page(self) -> None:
        if not self._source_path:
            return
        try:
            image, page_count = self._load_page(
                Path(self._source_path),
                self._page_index,
            )
        except RuntimeError as error:
            self._source_image = QImage()
            self._page_count = 0
            self.source_label.setText(f"Could not open card: {error}")
            self.canvas.setPixmap(QPixmap())
            self.canvas.setText("Preview unavailable.")
            self._update_page_controls()
            return
        self._source_image = image
        self._page_count = page_count
        if self._attached_employee_id:
            label = (
                f"Attached to {self._employee_name or self._employee_id} · "
                f"{Path(self._source_path).name} · source file is unchanged"
            )
        else:
            label = (
                f"Temporary read-only preview · {Path(self._source_path).name} · "
                "source file is unchanged"
            )
        self.source_label.setText(label)
        self._update_page_controls()
        self._render_image()

    def _update_page_controls(self) -> None:
        current = self._page_index + 1 if self._page_count else 0
        self.page_label.setText(
            f"Page {current} of {self._page_count}" if current else "Page —"
        )
        self.previous_page_button.setEnabled(self._page_index > 0)
        self.next_page_button.setEnabled(
            self._page_count > 0 and self._page_index < self._page_count - 1
        )

    @staticmethod
    def _load_page(path: Path, page_index: int) -> tuple[QImage, int]:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                from PySide6.QtPdf import QPdfDocument
            except ImportError as error:
                raise RuntimeError(
                    "PDF preview support is not available in this PySide6 installation."
                ) from error
            document = QPdfDocument()
            document.load(str(path))
            page_count = document.pageCount()
            if page_count < 1:
                raise RuntimeError("The PDF has no readable pages.")
            if not 0 <= page_index < page_count:
                raise RuntimeError("The requested PDF page is unavailable.")
            page_size = document.pagePointSize(page_index)
            rendered_size = page_size.toSize() * 2
            image = document.render(page_index, rendered_size)
            if image.isNull():
                raise RuntimeError("The selected PDF page could not be rendered.")
            return image, page_count

        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            raise RuntimeError(reader.errorString() or "The image could not be read.")
        return image, 1

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
        """Join the left history section and a narrow VL/SL-marking strip."""
        image = self._source_image
        if image.isNull():
            return image
        width = image.width()
        height = image.height()
        top = min(round(height * self.DEFAULT_HISTORY_TOP / 100), height - 1)
        crop_height = min(
            max(1, round(height * self.DEFAULT_HISTORY_HEIGHT / 100)),
            height - top,
        )

        def strip(left_percent: int, width_percent: int) -> QImage:
            left = min(round(width * left_percent / 100), width - 1)
            strip_width = min(
                max(1, round(width * width_percent / 100)),
                width - left,
            )
            return image.copy(left, top, strip_width, crop_height)

        history = strip(self.crop_x.value(), self.crop_w.value())
        markings = strip(self.mark_x.value(), self.DEFAULT_MARK_WIDTH)
        joined = QImage(
            history.width() + markings.width(),
            crop_height,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        joined.fill(Qt.GlobalColor.white)
        painter = QPainter(joined)
        painter.drawImage(0, 0, history)
        painter.drawImage(history.width(), 0, markings)
        painter.end()
        return joined

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
