"""تب تنظیمات امکانات محصول — واترمارک، کیفیت WebP، و تنظیمات مرتبط با ردیف محصولات."""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit,
    QPushButton, QFileDialog, QSpinBox, QDoubleSpinBox, QComboBox,
    QMessageBox, QScrollArea,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap

from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

WATERMARK_PATH_KEY = "PRODUCT_WATERMARK_PATH"
WATERMARK_OPACITY_KEY = "PRODUCT_WATERMARK_OPACITY"
WATERMARK_SCALE_KEY = "PRODUCT_WATERMARK_SCALE"
WATERMARK_POSITION_KEY = "PRODUCT_WATERMARK_POSITION"
WEBP_QUALITY_KEY = "PRODUCT_WEBP_QUALITY"

POSITION_LABELS = {
    "bottom-right": "پایین راست",
    "bottom-left": "پایین چپ",
    "top-right": "بالا راست",
    "top-left": "بالا چپ",
    "center": "وسط",
}


class ProductFeaturesSettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("⚙️ تنظیمات امکانات محصول")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("تنظیمات واترمارک، کیفیت WebP و سایر امکانات دکمه‌های روی ردیف محصولات")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(14)

        c_layout.addWidget(self._build_watermark_group())
        c_layout.addWidget(self._build_webp_group())
        c_layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

        save_row = QHBoxLayout()
        save_row.addStretch()
        self.save_btn = QPushButton("💾 ذخیره تنظیمات")
        self.save_btn.setMinimumHeight(40)
        self.save_btn.setMinimumWidth(160)
        self.save_btn.clicked.connect(self._save)
        save_row.addWidget(self.save_btn)
        outer.addLayout(save_row)

    def _build_watermark_group(self) -> QGroupBox:
        group = QGroupBox("🎨 واترمارک")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        row1 = QHBoxLayout()
        self.watermark_path_input = QLineEdit(str(self.config.get(WATERMARK_PATH_KEY) or ""))
        self.watermark_path_input.setPlaceholderText("مسیر فایل لوگو/واترمارک (PNG با پس‌زمینه شفاف پیشنهاد می‌شود)")
        self.watermark_path_input.setLayoutDirection(Qt.LeftToRight)
        row1.addWidget(self.watermark_path_input)
        pick_btn = QPushButton("📁 انتخاب فایل")
        pick_btn.clicked.connect(self._pick_watermark_file)
        row1.addWidget(pick_btn)
        layout.addLayout(row1)

        self.watermark_preview = QLabel("پیش‌نمایشی موجود نیست")
        self.watermark_preview.setFixedHeight(80)
        self.watermark_preview.setAlignment(Qt.AlignCenter)
        self.watermark_preview.setStyleSheet(
            "background:#f8fafc; border:1px dashed #cbd5e1; border-radius:6px; color:#94a3b8;"
        )
        layout.addWidget(self.watermark_preview)
        self._refresh_watermark_preview()

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("شفافیت:"))
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.1, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(float(self.config.get(WATERMARK_OPACITY_KEY, 0.55)))
        row2.addWidget(self.opacity_spin)

        row2.addWidget(QLabel("اندازه (نسبت به عرض تصویر):"))
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.05, 0.6)
        self.scale_spin.setSingleStep(0.01)
        self.scale_spin.setValue(float(self.config.get(WATERMARK_SCALE_KEY, 0.18)))
        row2.addWidget(self.scale_spin)

        row2.addWidget(QLabel("موقعیت:"))
        self.position_combo = QComboBox()
        for key, label in POSITION_LABELS.items():
            self.position_combo.addItem(label, key)
        current_pos = self.config.get(WATERMARK_POSITION_KEY, "bottom-right")
        idx = self.position_combo.findData(current_pos)
        self.position_combo.setCurrentIndex(idx if idx >= 0 else 0)
        row2.addWidget(self.position_combo)
        row2.addStretch()
        layout.addLayout(row2)

        note = QLabel(
            "این واترمارک فقط از طریق دکمه‌ی 🎨 روی ردیف محصول (تب محصولات) اعمال می‌شود — "
            "خودکار روی همه‌ی تصاویر اجرا نمی‌شود."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b; font-size:11px;")
        layout.addWidget(note)

        group.setLayout(layout)
        return group

    def _pick_watermark_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل لوگو/واترمارک", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        self.watermark_path_input.setText(path)
        self._refresh_watermark_preview()

    def _refresh_watermark_preview(self):
        path = self.watermark_path_input.text().strip()
        if path and os.path.isfile(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self.watermark_preview.setPixmap(
                    pix.scaledToHeight(76, Qt.SmoothTransformation)
                )
                return
        self.watermark_preview.setText("پیش‌نمایشی موجود نیست")
        self.watermark_preview.setPixmap(QPixmap())

    def _build_webp_group(self) -> QGroupBox:
        group = QGroupBox("🗜️ کیفیت WebP پیش‌فرض (برای دکمه‌ی روی ردیف محصول)")
        layout = QHBoxLayout()
        layout.addWidget(QLabel("کیفیت:"))
        self.webp_quality_spin = QSpinBox()
        self.webp_quality_spin.setRange(40, 100)
        self.webp_quality_spin.setValue(int(self.config.get(WEBP_QUALITY_KEY, 82)))
        layout.addWidget(self.webp_quality_spin)
        layout.addStretch()
        group.setLayout(layout)
        return group

    def _save(self):
        cfg = load_secure_config(None) or {}
        cfg[WATERMARK_PATH_KEY] = self.watermark_path_input.text().strip()
        cfg[WATERMARK_OPACITY_KEY] = self.opacity_spin.value()
        cfg[WATERMARK_SCALE_KEY] = self.scale_spin.value()
        cfg[WATERMARK_POSITION_KEY] = self.position_combo.currentData()
        cfg[WEBP_QUALITY_KEY] = self.webp_quality_spin.value()
        try:
            save_secure_config(cfg)
            self.config = cfg
            QMessageBox.information(self, "ذخیره شد", "تنظیمات امکانات محصول ذخیره شد.")
        except Exception as exc:
            QMessageBox.critical(self, "خطا", f"ذخیره ناموفق بود:\n{exc}")
