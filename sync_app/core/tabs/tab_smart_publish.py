"""تب تنظیمات Smart Publish — واترمارک، تعریف روش پردازش تصویر، و حالت اجرای خودکار هنگام ارسال."""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit,
    QPushButton, QFileDialog, QDoubleSpinBox, QComboBox, QCheckBox,
    QMessageBox, QScrollArea, QListWidget, QListWidgetItem, QInputDialog,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap

from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.media_center import load_image_profiles
from sync_app.core.smart_publish import (
    WATERMARK_PATH_KEY, WATERMARK_OPACITY_KEY, WATERMARK_SCALE_KEY,
    WATERMARK_POSITION_KEY, WATERMARK_MARGIN_KEY, PIPELINES_KEY,
    AUTO_RUN_KEY, AUTO_PIPELINE_KEY, STEP_LABELS, STEP_ORDER,
    POSITION_LABELS, load_pipelines, pipeline_summary,
    WATERMARK_PROFILES_KEY, WATERMARK_ACTIVE_PROFILE_KEY,
    load_watermark_profiles, save_watermark_profile, delete_watermark_profile,
    TEXT_ENGRAVE_SOURCE_KEY, TEXT_ENGRAVE_FONT_SIZE_KEY, TEXT_ENGRAVE_POSITION_KEY,
    QR_CODE_POSITION_KEY, TEXT_SOURCE_LABELS,
)


class SmartPublishSettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("✨ تنظیمات Smart Publish")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("واترمارک، تعریف روش پردازش تصویر، و اجرای خودکار هنگام ارسال محصول")
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
        c_layout.addWidget(self._build_engrave_group())
        c_layout.addWidget(self._build_pipeline_group())
        c_layout.addWidget(self._build_auto_group())
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

    # ------------------------------------------------------------------
    # واترمارک
    # ------------------------------------------------------------------
    def _build_watermark_group(self) -> QGroupBox:
        group = QGroupBox("🎨 واترمارک")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("پروفایل:"))
        self.watermark_profile_combo = QComboBox()
        self.watermark_profile_combo.setMinimumWidth(160)
        self.watermark_profile_combo.currentIndexChanged.connect(self._on_watermark_profile_selected)
        profile_row.addWidget(self.watermark_profile_combo)

        self.watermark_active_label = QLabel("")
        self.watermark_active_label.setStyleSheet("color:#16a34a; font-weight:700; font-size:11px;")
        profile_row.addWidget(self.watermark_active_label)
        profile_row.addStretch()

        set_active_btn = QPushButton("⭐ استفاده به‌عنوان پیش‌فرض")
        set_active_btn.setToolTip("پایپ‌لاین‌ها و مرکز رسانه از این پروفایل استفاده کنند")
        set_active_btn.clicked.connect(self._set_watermark_profile_active)
        profile_row.addWidget(set_active_btn)

        new_btn = QPushButton("➕ پروفایل جدید")
        new_btn.clicked.connect(self._new_watermark_profile)
        profile_row.addWidget(new_btn)

        delete_profile_btn = QPushButton("🗑️ حذف این پروفایل")
        delete_profile_btn.clicked.connect(self._delete_watermark_profile)
        profile_row.addWidget(delete_profile_btn)
        layout.addLayout(profile_row)

        row1 = QHBoxLayout()
        self.watermark_path_input = QLineEdit(str(self.config.get(WATERMARK_PATH_KEY) or ""))
        self.watermark_path_input.setPlaceholderText("مسیر فایل لوگو (PNG با پس‌زمینه شفاف پیشنهاد می‌شود)")
        self.watermark_path_input.setLayoutDirection(Qt.LeftToRight)
        row1.addWidget(self.watermark_path_input)
        pick_btn = QPushButton("📁 انتخاب فایل")
        pick_btn.clicked.connect(self._pick_watermark_file)
        row1.addWidget(pick_btn)
        layout.addLayout(row1)

        self.watermark_preview = QLabel("پیش‌نمایشی موجود نیست")
        self.watermark_preview.setFixedHeight(70)
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

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("فاصله از لبه (٪ عرض تصویر):"))
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0.0, 0.15)
        self.margin_spin.setSingleStep(0.01)
        self.margin_spin.setValue(float(self.config.get(WATERMARK_MARGIN_KEY, 0.03)))
        row3.addWidget(self.margin_spin)
        row3.addStretch()
        layout.addLayout(row3)

        group.setLayout(layout)
        self._populate_watermark_profiles()
        return group

    def _populate_watermark_profiles(self):
        cfg = load_secure_config(None) or self.config
        profiles = load_watermark_profiles(cfg)
        active = str(cfg.get(WATERMARK_ACTIVE_PROFILE_KEY) or next(iter(profiles), ""))

        self.watermark_profile_combo.blockSignals(True)
        self.watermark_profile_combo.clear()
        for name in profiles:
            self.watermark_profile_combo.addItem(name, name)
        idx = self.watermark_profile_combo.findData(active)
        self.watermark_profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.watermark_profile_combo.blockSignals(False)
        self._load_watermark_profile_into_fields(self.watermark_profile_combo.currentData())
        self._update_watermark_active_label()

    def _update_watermark_active_label(self):
        cfg = load_secure_config(None) or self.config
        active = str(cfg.get(WATERMARK_ACTIVE_PROFILE_KEY) or "")
        current = self.watermark_profile_combo.currentData()
        if active and active == current:
            self.watermark_active_label.setText("⭐ پیش‌فرض فعلی")
        else:
            self.watermark_active_label.setText("")

    def _load_watermark_profile_into_fields(self, name: str):
        if not name:
            return
        cfg = load_secure_config(None) or self.config
        profiles = load_watermark_profiles(cfg)
        data = profiles.get(name, {})
        self.watermark_path_input.setText(str(data.get("path") or ""))
        self.opacity_spin.setValue(float(data.get("opacity", 0.55)))
        self.scale_spin.setValue(float(data.get("scale", 0.18)))
        idx = self.position_combo.findData(data.get("position", "bottom-right"))
        self.position_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.margin_spin.setValue(float(data.get("margin", 0.03)))
        self._refresh_watermark_preview()

    def _on_watermark_profile_selected(self, _index):
        name = self.watermark_profile_combo.currentData()
        self._load_watermark_profile_into_fields(name)
        self._update_watermark_active_label()

    def _new_watermark_profile(self):
        name, ok = QInputDialog.getText(self, "پروفایل جدید واترمارک", "اسم پروفایل جدید را وارد کنید:")
        name = (name or "").strip()
        if not ok or not name:
            return
        save_watermark_profile(name, {
            "path": "", "opacity": 0.55, "scale": 0.18, "position": "bottom-right", "margin": 0.03,
        })
        self.config = load_secure_config(None) or {}
        self._populate_watermark_profiles()
        idx = self.watermark_profile_combo.findData(name)
        if idx >= 0:
            self.watermark_profile_combo.setCurrentIndex(idx)

    def _set_watermark_profile_active(self):
        name = self.watermark_profile_combo.currentData()
        if not name:
            return
        cfg = load_secure_config(None) or {}
        cfg[WATERMARK_ACTIVE_PROFILE_KEY] = name
        save_secure_config(cfg)
        self.config = cfg
        self._update_watermark_active_label()
        QMessageBox.information(self, "انجام شد", f"پروفایل «{name}» پیش‌فرض شد — پایپ‌لاین‌ها از این استفاده می‌کنند.")

    def _delete_watermark_profile(self):
        name = self.watermark_profile_combo.currentData()
        if not name:
            return
        profiles = load_watermark_profiles(load_secure_config(None) or {})
        if len(profiles) <= 1:
            QMessageBox.information(self, "امکان‌پذیر نیست", "حداقل یک پروفایل واترمارک باید باقی بماند.")
            return
        confirm = QMessageBox.question(
            self, "تأیید حذف", f"پروفایل «{name}» حذف شود؟", QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        delete_watermark_profile(name)
        self.config = load_secure_config(None) or {}
        self._populate_watermark_profiles()

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
                self.watermark_preview.setPixmap(pix.scaledToHeight(66, Qt.SmoothTransformation))
                return
        self.watermark_preview.setText("پیش‌نمایشی موجود نیست")
        self.watermark_preview.setPixmap(QPixmap())

    # ------------------------------------------------------------------
    # روش‌های پردازش تصویر
    # ------------------------------------------------------------------
    def _build_engrave_group(self) -> QGroupBox:
        group = QGroupBox("🖋️ حک متن دلخواه + QR کد لینک محصول")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        hint = QLabel(
            "برخلاف واترمارک (که روی همه‌ی تصاویر یکسانه)، این دوتا برای هر محصول فرق دارن — "
            "باید مراحل «حک متن» و «QR کد» رو تو پایپ‌لاین موردنظرتون هم تیک بزنید تا واقعاً اجرا بشن."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        layout.addWidget(hint)

        text_row = QHBoxLayout()
        text_row.addWidget(QLabel("متن حک‌شونده:"))
        self.engrave_source_combo = QComboBox()
        for key, label in TEXT_SOURCE_LABELS.items():
            self.engrave_source_combo.addItem(label, key)
        saved_source = str(self.config.get(TEXT_ENGRAVE_SOURCE_KEY) or "auto_code")
        idx = self.engrave_source_combo.findData(saved_source)
        self.engrave_source_combo.setCurrentIndex(idx if idx >= 0 else 0)
        text_row.addWidget(self.engrave_source_combo)

        text_row.addWidget(QLabel("سایز فونت:"))
        self.engrave_font_size_spin = QDoubleSpinBox()
        self.engrave_font_size_spin.setDecimals(0)
        self.engrave_font_size_spin.setRange(10, 80)
        self.engrave_font_size_spin.setValue(float(self.config.get(TEXT_ENGRAVE_FONT_SIZE_KEY, 22)))
        text_row.addWidget(self.engrave_font_size_spin)

        text_row.addWidget(QLabel("موقعیت:"))
        self.engrave_position_combo = QComboBox()
        engrave_positions = [
            ("bottom-center", "پایین وسط"), ("bottom-left", "پایین چپ"),
            ("bottom-right", "پایین راست"), ("top-center", "بالا وسط"),
        ]
        for key, label in engrave_positions:
            self.engrave_position_combo.addItem(label, key)
        saved_pos = str(self.config.get(TEXT_ENGRAVE_POSITION_KEY) or "bottom-center")
        idx2 = self.engrave_position_combo.findData(saved_pos)
        self.engrave_position_combo.setCurrentIndex(idx2 if idx2 >= 0 else 0)
        text_row.addWidget(self.engrave_position_combo)
        text_row.addStretch()
        layout.addLayout(text_row)

        qr_row = QHBoxLayout()
        qr_row.addWidget(QLabel("موقعیت QR کد:"))
        self.qr_position_combo = QComboBox()
        qr_positions = [
            ("bottom-left", "پایین چپ (کنار واترمارک راست)"), ("bottom-right", "پایین راست"),
            ("top-left", "بالا چپ"), ("top-right", "بالا راست"),
        ]
        for key, label in qr_positions:
            self.qr_position_combo.addItem(label, key)
        saved_qr_pos = str(self.config.get(QR_CODE_POSITION_KEY) or "bottom-left")
        idx3 = self.qr_position_combo.findData(saved_qr_pos)
        self.qr_position_combo.setCurrentIndex(idx3 if idx3 >= 0 else 0)
        qr_row.addWidget(self.qr_position_combo)
        qr_row.addStretch()
        layout.addLayout(qr_row)

        group.setLayout(layout)
        return group

    def _build_pipeline_group(self) -> QGroupBox:
        group = QGroupBox("🔗 روش‌های پردازش تصویر (بهینه‌سازی)")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        note = QLabel(
            "ترتیب اجرا همیشه ثابت است (فنی درست‌ترین ترتیب): "
            "Resize ← Watermark ← Compress/WebP. فقط انتخاب کنید کدام مرحله‌ها روشن باشند و اسمش رو بذارید."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b; font-size:11px;")
        layout.addWidget(note)

        self.pipeline_list = QListWidget()
        self.pipeline_list.setMinimumHeight(120)
        layout.addWidget(self.pipeline_list)
        self._refresh_pipeline_list()

        form_row = QHBoxLayout()
        self.pipeline_name_input = QLineEdit()
        self.pipeline_name_input.setPlaceholderText("اسم روش پردازش تصویر (مثلاً «آماده برای فروشگاه»)")
        form_row.addWidget(self.pipeline_name_input)
        layout.addLayout(form_row)

        self.profile_combo = QComboBox()
        for name in load_image_profiles(self.config):
            self.profile_combo.addItem(name, name)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("پروفایل سایز (برای مرحله‌ی Resize):"))
        profile_row.addWidget(self.profile_combo)
        profile_row.addStretch()
        layout.addLayout(profile_row)

        steps_row = QHBoxLayout()
        self.step_checks = {}
        for step in STEP_ORDER:
            cb = QCheckBox(STEP_LABELS[step])
            steps_row.addWidget(cb)
            self.step_checks[step] = cb
        steps_row.addStretch()
        layout.addLayout(steps_row)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("➕ ذخیره روش پردازش تصویر")
        add_btn.clicked.connect(self._save_pipeline)
        btn_row.addWidget(add_btn)
        remove_btn = QPushButton("🗑️ حذف روش پردازش تصویر انتخابی")
        remove_btn.clicked.connect(self._remove_pipeline)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        group.setLayout(layout)
        return group

    def _refresh_pipeline_list(self):
        self.pipeline_list.clear()
        pipelines = load_pipelines(self.config)
        for name, data in pipelines.items():
            steps = data.get("steps", []) if isinstance(data, dict) else data
            profile = data.get("profile", "") if isinstance(data, dict) else ""
            summary = pipeline_summary(steps)
            extra = f" | پروفایل: {profile}" if profile else ""
            self.pipeline_list.addItem(f"{name}: {summary}{extra}")

    def _save_pipeline(self):
        name = self.pipeline_name_input.text().strip()
        if not name:
            QMessageBox.information(self, "اسم لازم است", "یک اسم برای روش پردازش تصویر وارد کنید.")
            return
        steps = [s for s, cb in self.step_checks.items() if cb.isChecked()]
        if not steps:
            QMessageBox.information(self, "مرحله‌ای انتخاب نشده", "حداقل یک مرحله را تیک بزنید.")
            return
        profile_name = self.profile_combo.currentData() if "resize" in steps else ""

        cfg = load_secure_config(None) or {}
        pipelines = load_pipelines(cfg)
        pipelines[name] = {"steps": steps, "profile": profile_name}
        cfg[PIPELINES_KEY] = pipelines
        save_secure_config(cfg)
        self.config = cfg
        self._refresh_pipeline_list()
        self._refresh_auto_pipeline_combo()
        QMessageBox.information(self, "ذخیره شد", f"روش پردازش تصویر «{name}» ذخیره شد.")

    def _remove_pipeline(self):
        row = self.pipeline_list.currentRow()
        if row < 0:
            return
        pipelines = load_pipelines(self.config)
        names = list(pipelines.keys())
        if row >= len(names):
            return
        name = names[row]
        confirm = QMessageBox.question(self, "حذف روش پردازش تصویر", f"روش پردازش تصویر «{name}» حذف شود؟")
        if confirm != QMessageBox.Yes:
            return
        pipelines.pop(name, None)
        cfg = load_secure_config(None) or {}
        cfg[PIPELINES_KEY] = pipelines
        save_secure_config(cfg)
        self.config = cfg
        self._refresh_pipeline_list()
        self._refresh_auto_pipeline_combo()

    # ------------------------------------------------------------------
    # اجرای خودکار هنگام ارسال
    # ------------------------------------------------------------------
    def _build_auto_group(self) -> QGroupBox:
        group = QGroupBox("⚡ اجرای خودکار هنگام آپلود تصویر محصول")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        self.auto_run_check = QCheckBox("وقتی از تب محصولات عکسی برای یک کالا آپلود می‌کنید، خودکار این روش پردازش تصویر روی آن اجرا شود")
        self.auto_run_check.setChecked(bool(self.config.get(AUTO_RUN_KEY, False)))
        layout.addWidget(self.auto_run_check)

        auto_row = QHBoxLayout()
        auto_row.addWidget(QLabel("روش پردازش تصویر:"))
        self.auto_pipeline_combo = QComboBox()
        auto_row.addWidget(self.auto_pipeline_combo)
        auto_row.addStretch()
        layout.addLayout(auto_row)
        self._refresh_auto_pipeline_combo()

        note = QLabel(
            "ℹ️ این حالت فقط روی آپلود دستی تصویر از تب محصولات اثر دارد. برای اجرای دستی روی هر "
            "محصول (بدون فعال کردن حالت خودکار)، از دکمه‌ی 🎨 روی همان ردیف محصول استفاده کنید."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b; font-size:11px;")
        layout.addWidget(note)

        group.setLayout(layout)
        return group

    def _refresh_auto_pipeline_combo(self):
        self.auto_pipeline_combo.clear()
        pipelines = load_pipelines(self.config)
        for name in pipelines:
            self.auto_pipeline_combo.addItem(name, name)
        current = self.config.get(AUTO_PIPELINE_KEY)
        idx = self.auto_pipeline_combo.findData(current)
        if idx >= 0:
            self.auto_pipeline_combo.setCurrentIndex(idx)

    def _save(self):
        cfg = load_secure_config(None) or {}
        cfg[WATERMARK_PATH_KEY] = self.watermark_path_input.text().strip()
        cfg[WATERMARK_OPACITY_KEY] = self.opacity_spin.value()
        cfg[WATERMARK_SCALE_KEY] = self.scale_spin.value()
        cfg[WATERMARK_POSITION_KEY] = self.position_combo.currentData()
        cfg[WATERMARK_MARGIN_KEY] = self.margin_spin.value()
        cfg[TEXT_ENGRAVE_SOURCE_KEY] = self.engrave_source_combo.currentData()
        cfg[TEXT_ENGRAVE_FONT_SIZE_KEY] = int(self.engrave_font_size_spin.value())
        cfg[TEXT_ENGRAVE_POSITION_KEY] = self.engrave_position_combo.currentData()
        cfg[QR_CODE_POSITION_KEY] = self.qr_position_combo.currentData()
        cfg[AUTO_RUN_KEY] = self.auto_run_check.isChecked()
        cfg[AUTO_PIPELINE_KEY] = self.auto_pipeline_combo.currentData()

        # فیلدهای فعلی رو داخل همون پروفایل واترمارکی که الان انتخابه هم
        # ذخیره کن — تا سیستم چندپروفایلی هم به‌روز بمونه.
        current_profile = self.watermark_profile_combo.currentData()
        if current_profile:
            profiles = dict(cfg.get(WATERMARK_PROFILES_KEY) or {})
            profiles[current_profile] = {
                "path": cfg[WATERMARK_PATH_KEY],
                "opacity": cfg[WATERMARK_OPACITY_KEY],
                "scale": cfg[WATERMARK_SCALE_KEY],
                "position": cfg[WATERMARK_POSITION_KEY],
                "margin": cfg[WATERMARK_MARGIN_KEY],
            }
            cfg[WATERMARK_PROFILES_KEY] = profiles
            if not cfg.get(WATERMARK_ACTIVE_PROFILE_KEY):
                cfg[WATERMARK_ACTIVE_PROFILE_KEY] = current_profile

        try:
            save_secure_config(cfg)
            self.config = cfg
            QMessageBox.information(self, "ذخیره شد", "تنظیمات Smart Publish ذخیره شد.")
        except Exception as exc:
            QMessageBox.critical(self, "خطا", f"ذخیره ناموفق بود:\n{exc}")
