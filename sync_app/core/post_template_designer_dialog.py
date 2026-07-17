"""دیالوگِ «طراحِ قالبِ پست» — ویرایشگرِ پارامتریِ بصری با پیش‌نمایشِ زنده:
رنگ/شفافیت/ارتفاعِ نوارِ متن، رنگ/سایزِ نامِ محصول و قیمت، چیدمانِ متن،
برچسبِ تخفیف — همه با یک تصویرِ نمونه بلافاصله روی صفحه رندر می‌شن.
خروجی، یک دیکشنریِ «قالب» است که با post_template_store.py ذخیره می‌شه
و بعداً روی هر محصولی قابلِ استفاده‌ی مجدده."""

from __future__ import annotations

import os
import tempfile

from PIL import Image
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from sync_app.core.post_template_renderer import (
    CANVAS_LABELS,
    CANVAS_SIZES,
    TEXT_ALIGN_LABELS,
    normalize_template,
    render_post_template,
)

_SAMPLE_PRODUCT = {"name": "نمونه محصول شما", "price": 1250000}


def _color_button(initial_rgb: list) -> QPushButton:
    btn = QPushButton()
    btn.setFixedWidth(60)
    btn.setMinimumHeight(30)
    _apply_button_color(btn, initial_rgb)
    return btn


def _apply_button_color(btn: QPushButton, rgb: list) -> None:
    r, g, b = (int(c) for c in rgb)
    btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #94a3b8;")
    btn.setProperty("rgb", [r, g, b])


class PostTemplateDesignerDialog(QDialog):
    def __init__(self, parent=None, *, template: dict | None = None, sample_image_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("🎨 طراحِ قالبِ پست")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(760, 560)

        self._template = normalize_template(template)
        self._sample_image_path = sample_image_path if os.path.isfile(sample_image_path or "") else self._make_placeholder_image()
        self._preview_tmp_dir = tempfile.mkdtemp(prefix="peecha_template_preview_")
        self.saved_template: dict | None = None

        root = QHBoxLayout(self)

        # --- پیش‌نمایش ---
        preview_col = QVBoxLayout()
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(300, 420)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background:#f1f5f9; border:1px solid #cbd5e1;")
        preview_col.addWidget(self.preview_label)
        preview_col.addStretch()
        root.addLayout(preview_col)

        # --- کنترل‌ها ---
        form = QFormLayout()

        self.title_input = QLineEdit(str(self._template.get("title") or ""))
        form.addRow("عنوانِ قالب:", self.title_input)

        self.canvas_combo = QComboBox()
        for key, label in CANVAS_LABELS.items():
            self.canvas_combo.addItem(label, key)
        idx = self.canvas_combo.findData(self._template["canvas"])
        self.canvas_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.canvas_combo.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("اندازه‌ی بوم:", self.canvas_combo)

        self.band_color_btn = _color_button(self._template["band_color"])
        self.band_color_btn.clicked.connect(lambda: self._pick_color(self.band_color_btn))
        form.addRow("رنگِ نوارِ متن:", self.band_color_btn)

        self.band_opacity_slider = QSlider(Qt.Horizontal)
        self.band_opacity_slider.setRange(0, 255)
        self.band_opacity_slider.setValue(int(self._template["band_opacity"]))
        self.band_opacity_slider.valueChanged.connect(self._refresh_preview)
        form.addRow("شفافیتِ نوار:", self.band_opacity_slider)

        self.band_height_slider = QSlider(Qt.Horizontal)
        self.band_height_slider.setRange(10, 40)
        self.band_height_slider.setValue(int(float(self._template["band_height_pct"]) * 100))
        self.band_height_slider.valueChanged.connect(self._refresh_preview)
        form.addRow("ارتفاعِ نوار (٪):", self.band_height_slider)

        self.name_color_btn = _color_button(self._template["name_color"])
        self.name_color_btn.clicked.connect(lambda: self._pick_color(self.name_color_btn))
        form.addRow("رنگِ متنِ نام:", self.name_color_btn)

        self.name_size_slider = QSlider(Qt.Horizontal)
        self.name_size_slider.setRange(2, 8)
        self.name_size_slider.setValue(int(float(self._template["name_size_pct"]) * 100))
        self.name_size_slider.valueChanged.connect(self._refresh_preview)
        form.addRow("سایزِ متنِ نام (٪):", self.name_size_slider)

        self.price_color_btn = _color_button(self._template["price_color"])
        self.price_color_btn.clicked.connect(lambda: self._pick_color(self.price_color_btn))
        form.addRow("رنگِ متنِ قیمت:", self.price_color_btn)

        self.price_size_slider = QSlider(Qt.Horizontal)
        self.price_size_slider.setRange(2, 8)
        self.price_size_slider.setValue(int(float(self._template["price_size_pct"]) * 100))
        self.price_size_slider.valueChanged.connect(self._refresh_preview)
        form.addRow("سایزِ متنِ قیمت (٪):", self.price_size_slider)

        self.align_combo = QComboBox()
        for key, label in TEXT_ALIGN_LABELS.items():
            self.align_combo.addItem(label, key)
        idx = self.align_combo.findData(self._template["text_align"])
        self.align_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.align_combo.currentIndexChanged.connect(self._refresh_preview)
        form.addRow("چیدمانِ متن:", self.align_combo)

        self.badge_check = QCheckBox("نمایشِ برچسب (مثلاً تخفیف)")
        self.badge_check.setChecked(bool(self._template.get("show_badge")))
        self.badge_check.stateChanged.connect(self._refresh_preview)
        form.addRow("", self.badge_check)

        self.badge_text_input = QLineEdit(str(self._template.get("badge_text") or ""))
        self.badge_text_input.textChanged.connect(self._refresh_preview)
        form.addRow("متنِ برچسب:", self.badge_text_input)

        self.badge_color_btn = _color_button(self._template["badge_color"])
        self.badge_color_btn.clicked.connect(lambda: self._pick_color(self.badge_color_btn))
        form.addRow("رنگِ برچسب:", self.badge_color_btn)

        controls_col = QVBoxLayout()
        controls_col.addLayout(form)

        actions_row = QHBoxLayout()
        actions_row.addStretch()
        cancel_btn = QPushButton("انصراف")
        cancel_btn.clicked.connect(self.reject)
        actions_row.addWidget(cancel_btn)
        save_btn = QPushButton("💾 ذخیره قالب")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        actions_row.addWidget(save_btn)
        controls_col.addLayout(actions_row)

        root.addLayout(controls_col, 1)

        self._refresh_preview()

    def _make_placeholder_image(self) -> str:
        path = os.path.join(tempfile.gettempdir(), "peecha_template_placeholder.jpg")
        if not os.path.isfile(path):
            Image.new("RGB", (800, 800), color=(180, 190, 210)).save(path)
        return path

    def _pick_color(self, btn: QPushButton):
        current = btn.property("rgb") or [0, 0, 0]
        color = QColorDialog.getColor(QColor(*current), self, "انتخابِ رنگ")
        if color.isValid():
            _apply_button_color(btn, [color.red(), color.green(), color.blue()])
            self._refresh_preview()

    def current_template_fields(self) -> dict:
        return {
            "canvas": self.canvas_combo.currentData(),
            "band_color": self.band_color_btn.property("rgb"),
            "band_opacity": self.band_opacity_slider.value(),
            "band_height_pct": self.band_height_slider.value() / 100.0,
            "name_color": self.name_color_btn.property("rgb"),
            "name_size_pct": self.name_size_slider.value() / 100.0,
            "price_color": self.price_color_btn.property("rgb"),
            "price_size_pct": self.price_size_slider.value() / 100.0,
            "text_align": self.align_combo.currentData(),
            "show_badge": self.badge_check.isChecked(),
            "badge_text": self.badge_text_input.text().strip(),
            "badge_color": self.badge_color_btn.property("rgb"),
        }

    def _refresh_preview(self, *_args):
        template = normalize_template(self.current_template_fields())
        dst = os.path.join(self._preview_tmp_dir, "preview.jpg")
        result = render_post_template(self._sample_image_path, _SAMPLE_PRODUCT, dst, template)
        if not result.ok:
            self.preview_label.setText(f"خطا در پیش‌نمایش:\n{result.error}")
            return
        pix = QPixmap(dst)
        if pix.isNull():
            return
        self.preview_label.setPixmap(
            pix.scaled(self.preview_label.width(), self.preview_label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _save(self):
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "طراحِ قالب", "یک عنوان برای قالب وارد کنید.")
            return
        fields = self.current_template_fields()
        fields["title"] = title
        fields["id"] = self._template.get("id") or ""
        self.saved_template = normalize_template(fields)
        self.accept()
