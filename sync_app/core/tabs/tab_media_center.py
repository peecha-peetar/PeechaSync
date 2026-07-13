"""تب مرکز رسانه — فاز ۱: خروجی‌های چندگانه با پروفایل، تشخیص تکراری، تشخیص کیفیت پایین، آمادگی انتشار."""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QSpinBox,
    QMessageBox, QScrollArea, QListWidget, QListWidgetItem, QAbstractItemView,
    QCheckBox, QDialog, QDialogButtonBox, QRadioButton, QButtonGroup, QComboBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap

from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.sql_connection_helper import open_sql_connection, format_db_error
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.article_price import resolve_article_price
from sync_app.core.category_resolver import load_category_map
from sync_app.core.category_rules import resolve_product_categories
from sync_app.core.product_woo_map_helper import load_product_woo_map
from sync_app.core.media_center import (
    convert_to_webp,
    find_duplicate_groups,
    seo_filename,
    product_readiness,
    is_supported_image,
    is_valid_image_data,
    is_valid_image_file,
    heic_available_for_ui,
    scan_product_image_folder,
    build_product_code_lookup,
    load_image_profiles,
    generate_profile_outputs,
    detect_low_quality,
    IMAGE_PROFILES_KEY,
)
from sync_app.core.wc_sync_helper import (
    build_wcapi,
    apply_network_overrides,
    wp_upload_media_ex,
    update_wc_product_images,
)
from sync_app.core.integrations.commerce_provider import is_prestashop


class MediaCenterTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self._webp_files: list[str] = []
        self._dup_folder = ""
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("🖼️ مرکز رسانه")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        heic_note = "" if heic_available_for_ui() else " (⚠️ پشتیبانی HEIC نصب نیست)"
        subtitle = QLabel(f"تبدیل/بهینه‌سازی تصاویر، تشخیص تکراری، و بررسی آمادگی انتشار محصولات{heic_note}")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(14)

        c_layout.addWidget(self._build_webp_group())
        c_layout.addWidget(self._build_bulk_import_group())
        c_layout.addWidget(self._build_duplicate_group())
        c_layout.addWidget(self._build_low_quality_group())
        c_layout.addWidget(self._build_readiness_group())
        c_layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ------------------------------------------------------------------
    # بخش ۱: تبدیل به WebP + خروجی‌های چندگانه با پروفایل
    # ------------------------------------------------------------------
    def _build_webp_group(self) -> QGroupBox:
        group = QGroupBox("۱) خروجی‌های چندگانه (WebP)")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        row1 = QHBoxLayout()
        self.webp_pick_btn = QPushButton("📁 انتخاب تصاویر (JPG/PNG/BMP/TIFF" + ("/HEIC" if heic_available_for_ui() else "") + ")")
        self.webp_pick_btn.clicked.connect(self._pick_webp_files)
        row1.addWidget(self.webp_pick_btn)
        self.webp_files_label = QLabel("هیچ فایلی انتخاب نشده")
        self.webp_files_label.setStyleSheet("color:#64748b;")
        row1.addWidget(self.webp_files_label)
        row1.addStretch()
        layout.addLayout(row1)

        profiles_label = QLabel("پروفایل‌های خروجی (هر کدوم رو تیک بزنید، یک فایل جدا با سایز دقیق همون پروفایل ساخته می‌شه — بدون تیک، فقط یک WebP ساده با تنظیمات پایین ساخته می‌شه):")
        profiles_label.setWordWrap(True)
        profiles_label.setStyleSheet("color:#475569; font-size:11px;")
        layout.addWidget(profiles_label)

        self.profile_checks_row = QHBoxLayout()
        self.profile_checkboxes = {}
        self._rebuild_profile_checkboxes()
        layout.addLayout(self.profile_checks_row)

        self.apply_watermark_check = QCheckBox("🖊️ اعمال واترمارک روی خروجی‌ها (طبق تنظیمات لوگو در «انتشار هوشمند»)")
        self.apply_watermark_check.setStyleSheet("font-size:11px;")
        layout.addWidget(self.apply_watermark_check)

        manage_profiles_btn = QPushButton("⚙️ مدیریت پروفایل‌ها")
        manage_profiles_btn.clicked.connect(self._open_profile_manager)
        layout.addWidget(manage_profiles_btn)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("کیفیت WebP:"))
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(40, 100)
        self.quality_spin.setValue(82)
        row2.addWidget(self.quality_spin)
        row2.addWidget(QLabel("حداکثر عرض (فقط حالت بدون پروفایل):"))
        self.max_w_spin = QSpinBox()
        self.max_w_spin.setRange(0, 8000)
        self.max_w_spin.setValue(1200)
        self.max_w_spin.setSpecialValueText("بدون محدودیت")
        row2.addWidget(self.max_w_spin)
        row2.addWidget(QLabel("حداکثر ارتفاع:"))
        self.max_h_spin = QSpinBox()
        self.max_h_spin.setRange(0, 8000)
        self.max_h_spin.setValue(1200)
        self.max_h_spin.setSpecialValueText("بدون محدودیت")
        row2.addWidget(self.max_h_spin)
        self.seo_rename_check = QPushButton("🏷️ نام‌گذاری سئو (از روی نام فایل فعلی)")
        self.seo_rename_check.setCheckable(True)
        row2.addWidget(self.seo_rename_check)
        row2.addStretch()
        layout.addLayout(row2)

        self.webp_run_btn = QPushButton("▶️ شروع تبدیل")
        self.webp_run_btn.setMinimumHeight(38)
        self.webp_run_btn.clicked.connect(self._run_webp_conversion)
        layout.addWidget(self.webp_run_btn)

        self.webp_table = QTableWidget(0, 4)
        self.webp_table.setHorizontalHeaderLabels(["فایل", "حجم قبل", "حجم بعد", "صرفه‌جویی"])
        self.webp_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.webp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.webp_table.setMinimumHeight(160)
        self.webp_table.setToolTip("روی هر ردیف کلیک کنید تا پیش‌نمایش تصویر خروجی را ببینید")
        self.webp_table.cellClicked.connect(self._preview_webp_row)
        layout.addWidget(self.webp_table)

        self.webp_summary_label = QLabel("")
        self.webp_summary_label.setStyleSheet("font-weight:700; color:#166534;")
        layout.addWidget(self.webp_summary_label)

        group.setLayout(layout)
        return group

    def _rebuild_profile_checkboxes(self):
        while self.profile_checks_row.count():
            item = self.profile_checks_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.profile_checkboxes = {}

        profiles = load_image_profiles(self.config)
        for name, dims in profiles.items():
            cb = QCheckBox(name)
            self.profile_checks_row.addWidget(cb)
            self.profile_checkboxes[name] = cb
        self.profile_checks_row.addStretch()

    def _open_profile_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("مدیریت پروفایل‌های سایز")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.resize(680, 420)
        layout = QVBoxLayout(dialog)

        hint = QLabel(
            "«نام پروفایل» فقط برای نمایش در چک‌باکس است. «پسوند نام فایل» اختیاریه — "
            "اگه پر کنید، به فرم «نام‌فایل$پسوند» به آخر نام فایل خروجی اضافه می‌شه "
            "(مثلاً «کفش.jpg» + پسوند «wc» = «کفش$wc.webp»). اگه پسوند رو خالی بذارید، "
            "خروجی دقیقاً با همون نام فایل ورودی ذخیره می‌شه."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:11px;")
        layout.addWidget(hint)

        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(
            ["نام پروفایل", "پسوند نام فایل (اختیاری)", "عرض", "ارتفاع", "کیفیت (%)", "حاشیه (%)"]
        )
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(table)

        def _add_row(name="پروفایل جدید", suffix="", w=1000, h=1000, quality=85, margin=0):
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(suffix))
            w_spin = QSpinBox(); w_spin.setRange(50, 8000); w_spin.setValue(int(w))
            table.setCellWidget(row, 2, w_spin)
            h_spin = QSpinBox(); h_spin.setRange(50, 8000); h_spin.setValue(int(h))
            table.setCellWidget(row, 3, h_spin)
            q_spin = QSpinBox(); q_spin.setRange(40, 100); q_spin.setValue(int(quality))
            table.setCellWidget(row, 4, q_spin)
            m_spin = QSpinBox(); m_spin.setRange(0, 45); m_spin.setValue(int(margin))
            m_spin.setSuffix("%")
            table.setCellWidget(row, 5, m_spin)

        for name, dims in load_image_profiles(self.config).items():
            _add_row(
                name, dims.get("suffix", ""), dims["w"], dims["h"],
                dims.get("quality", 85), dims.get("margin", 0),
            )

        btn_row = QHBoxLayout()
        add_btn = QPushButton("➕ پروفایل جدید")
        add_btn.clicked.connect(lambda: _add_row())
        btn_row.addWidget(add_btn)
        remove_btn = QPushButton("🗑️ حذف ردیف انتخابی")
        remove_btn.clicked.connect(lambda: table.removeRow(table.currentRow()) if table.currentRow() >= 0 else None)
        btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("💾 ذخیره")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        new_profiles = {}
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            name = (name_item.text().strip() if name_item else "")
            if not name:
                continue
            suffix_item = table.item(row, 1)
            suffix = (suffix_item.text().strip() if suffix_item else "")
            w = table.cellWidget(row, 2).value()
            h = table.cellWidget(row, 3).value()
            quality = table.cellWidget(row, 4).value()
            margin = table.cellWidget(row, 5).value()
            new_profiles[name] = {"w": w, "h": h, "quality": quality, "suffix": suffix, "margin": margin}

        cfg = load_secure_config(None) or {}
        cfg[IMAGE_PROFILES_KEY] = new_profiles
        save_secure_config(cfg)
        self.config = cfg
        self._rebuild_profile_checkboxes()
        QMessageBox.information(self, "ذخیره شد", "پروفایل‌ها به‌روزرسانی شدند.")

    def _pick_webp_files(self):
        exts = "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"
        if heic_available_for_ui():
            exts += " *.heic *.heif"
        files, _ = QFileDialog.getOpenFileNames(self, "انتخاب تصاویر", "", f"Images ({exts})")
        if not files:
            return
        self._webp_files = files
        self.webp_files_label.setText(f"{len(files)} فایل انتخاب شد")

    def _run_webp_conversion(self):
        if not self._webp_files:
            QMessageBox.information(self, "فایلی انتخاب نشده", "ابتدا تصاویر را انتخاب کنید.")
            return

        out_dir = QFileDialog.getExistingDirectory(self, "پوشه‌ی خروجی را انتخاب کنید")
        if not out_dir:
            return

        quality = self.quality_spin.value()
        max_w = self.max_w_spin.value() or None
        max_h = self.max_h_spin.value() or None
        use_seo_name = self.seo_rename_check.isChecked()
        files = list(self._webp_files)
        selected_profiles = [name for name, cb in self.profile_checkboxes.items() if cb.isChecked()]
        profiles = load_image_profiles(self.config)

        watermark_settings = None
        if self.apply_watermark_check.isChecked():
            from sync_app.core.smart_publish import load_watermark_settings
            watermark_settings = load_watermark_settings(self.config)
            if not watermark_settings.get("path"):
                QMessageBox.warning(
                    self, "لوگوی واترمارک تنظیم نشده",
                    "برای اعمال واترمارک، اول باید در تب «انتشار هوشمند» یک فایل لوگو انتخاب کنید.",
                )
                return

        self.webp_run_btn.setEnabled(False)
        self.webp_run_btn.setText("⏳ در حال تبدیل...")

        def _worker():
            results = []
            if selected_profiles:
                for src in files:
                    results.extend(
                        generate_profile_outputs(
                            src, out_dir, selected_profiles, profiles,
                            to_webp=True, watermark=watermark_settings,
                        )
                    )
                return results

            for src in files:
                if use_seo_name:
                    base = os.path.splitext(os.path.basename(src))[0]
                    out_name = seo_filename(base, src)
                else:
                    out_name = os.path.splitext(os.path.basename(src))[0] + ".webp"
                dst = os.path.join(out_dir, out_name)
                results.append(
                    convert_to_webp(src, dst, quality=quality, max_width=max_w, max_height=max_h)
                )
            return results

        def _done(results):
            self.webp_run_btn.setEnabled(True)
            self.webp_run_btn.setText("▶️ شروع تبدیل")
            self._fill_webp_table(results)
            # ریست انتخاب فایل بعد از اتمام عملیات — طبق درخواست
            self._webp_files = []
            self.webp_files_label.setText("هیچ فایلی انتخاب نشده")

        def _fail(msg):
            self.webp_run_btn.setEnabled(True)
            self.webp_run_btn.setText("▶️ شروع تبدیل")
            QMessageBox.critical(self, "خطا", f"تبدیل ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _show_image_preview_dialog(self, path: str):
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "پیش‌نمایش", "فایل تصویر پیدا نشد (شاید جابه‌جا/حذف شده).")
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.information(self, "پیش‌نمایش", "این فایل به‌عنوان تصویر قابل‌نمایش نیست.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(os.path.basename(path))
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(dialog)
        scaled = pixmap.scaled(560, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        img_label = QLabel()
        img_label.setPixmap(scaled)
        img_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(img_label)
        path_label = QLabel(path)
        path_label.setStyleSheet("color:#64748b; font-size:10px;")
        path_label.setLayoutDirection(Qt.LeftToRight)
        path_label.setWordWrap(True)
        layout.addWidget(path_label)
        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec_()

    def _preview_webp_row(self, row, _column):
        item = self.webp_table.item(row, 0)
        path = item.data(Qt.UserRole) if item else None
        if path:
            self._show_image_preview_dialog(path)

    def _fill_webp_table(self, results):
        self.webp_table.setRowCount(0)
        total_before = 0
        total_after = 0
        ok_count = 0
        for r in results:
            row = self.webp_table.rowCount()
            self.webp_table.insertRow(row)
            name = os.path.basename(r.src_path)
            if r.ok:
                ok_count += 1
                total_before += r.size_before
                total_after += r.size_after
                self.webp_table.setItem(row, 0, QTableWidgetItem(f"✅ {name} → {os.path.basename(r.dst_path)}"))
                self.webp_table.item(row, 0).setData(Qt.UserRole, r.dst_path)
                self.webp_table.setItem(row, 1, QTableWidgetItem(f"{r.size_before/1024:,.0f} KB"))
                self.webp_table.setItem(row, 2, QTableWidgetItem(f"{r.size_after/1024:,.0f} KB"))
                self.webp_table.setItem(row, 3, QTableWidgetItem(f"{r.saved_percent:.0f}%"))
            else:
                self.webp_table.setItem(row, 0, QTableWidgetItem(f"❌ {name} — {r.error}"))
                self.webp_table.setItem(row, 1, QTableWidgetItem("-"))
                self.webp_table.setItem(row, 2, QTableWidgetItem("-"))
                self.webp_table.setItem(row, 3, QTableWidgetItem("-"))

        if ok_count:
            saved_pct = (1 - total_after / total_before) * 100 if total_before else 0
            self.webp_summary_label.setText(
                f"📊 {ok_count} تصویر تبدیل شد | حجم قبل: {total_before/1024/1024:.1f}MB | "
                f"حجم بعد: {total_after/1024/1024:.1f}MB | صرفه‌جویی کل: {saved_pct:.0f}%"
            )
        else:
            self.webp_summary_label.setText("هیچ تصویری با موفقیت تبدیل نشد.")

    # ------------------------------------------------------------------
    # بخش ۲: وارد کردن گروهی تصاویر بر اساس کد کالا (نام فایل)
    # ------------------------------------------------------------------
    def _build_bulk_import_group(self) -> QGroupBox:
        group = QGroupBox("۲) وارد کردن گروهی بر اساس کد کالا")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        note = QLabel(
            "کد کالا در نام فایل می‌تواند کد اتوماتیک یا کد دستی (A_Code_C) باشد — هر دو تشخیص داده می‌شوند."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748b; font-size:11px;")
        layout.addWidget(note)

        row1 = QHBoxLayout()
        self.bulk_pick_btn = QPushButton("📁 انتخاب پوشه‌ی تصاویر آماده")
        self.bulk_pick_btn.clicked.connect(self._pick_bulk_folder)
        row1.addWidget(self.bulk_pick_btn)
        self.bulk_folder_label = QLabel("پوشه‌ای انتخاب نشده")
        self.bulk_folder_label.setStyleSheet("color:#64748b;")
        row1.addWidget(self.bulk_folder_label)
        row1.addStretch()
        self.bulk_scan_btn = QPushButton("🔎 بررسی تطبیق با کالاها")
        self.bulk_scan_btn.clicked.connect(self._run_bulk_scan)
        row1.addWidget(self.bulk_scan_btn)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("نمایش:"))
        self.bulk_filter_combo = QComboBox()
        self.bulk_filter_combo.addItem("همه", "all")
        self.bulk_filter_combo.addItem("✅ فقط آماده‌ی آپلود", "ready")
        self.bulk_filter_combo.addItem("⚠️/❌ فقط تطبیق‌نشده", "not_ready")
        self.bulk_filter_combo.currentIndexChanged.connect(self._apply_bulk_filter)
        row2.addWidget(self.bulk_filter_combo)
        self.bulk_select_all_btn = QPushButton("☑️ انتخاب همه")
        self.bulk_select_all_btn.clicked.connect(lambda: self._bulk_select_all(True))
        row2.addWidget(self.bulk_select_all_btn)
        self.bulk_select_none_btn = QPushButton("⬜ هیچ‌کدام")
        self.bulk_select_none_btn.clicked.connect(lambda: self._bulk_select_all(False))
        row2.addWidget(self.bulk_select_none_btn)
        row2.addStretch()
        layout.addLayout(row2)

        self.bulk_table = QTableWidget(0, 7)
        self.bulk_table.setHorizontalHeaderLabels(
            ["", "کد در نام فایل", "نام کالا", "کد کالا اتوماتیک", "کد کالا دستی", "تعداد عکس", "وضعیت"]
        )
        self.bulk_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.bulk_table.setColumnWidth(0, 32)
        self.bulk_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.bulk_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.bulk_table.setMinimumHeight(180)
        self.bulk_table.setToolTip("روی یک ردیف (به‌جز چک‌باکس) کلیک کنید تا اولین تصویرش پیش‌نمایش داده شود")
        self.bulk_table.cellClicked.connect(self._preview_bulk_row)
        layout.addWidget(self.bulk_table)

        warn = QLabel(
            "ℹ️ موقع شروع آپلود، می‌توانید انتخاب کنید تصاویر جایگزین گالری فعلی محصول شوند "
            "یا به آن اضافه شوند."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#0369a1; font-size:11px;")
        layout.addWidget(warn)

        self.bulk_upload_btn = QPushButton("📤 شروع آپلود موارد تطبیق‌یافته")
        self.bulk_upload_btn.setMinimumHeight(38)
        self.bulk_upload_btn.clicked.connect(self._run_bulk_upload)
        layout.addWidget(self.bulk_upload_btn)

        self.bulk_summary_label = QLabel("")
        self.bulk_summary_label.setStyleSheet("font-weight:700;")
        layout.addWidget(self.bulk_summary_label)

        group.setLayout(layout)
        self._bulk_folder = ""
        self._bulk_matched_groups = {}  # a_code -> [(idx, path), ...]
        return group

    def _pick_bulk_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "پوشه‌ی تصاویر آماده")
        if not folder:
            return
        self._bulk_folder = folder
        self.bulk_folder_label.setText(folder)

    def _run_bulk_scan(self):
        if not self._bulk_folder or not os.path.isdir(self._bulk_folder):
            QMessageBox.information(self, "پوشه انتخاب نشده", "ابتدا یک پوشه انتخاب کنید.")
            return

        config = load_secure_config(None) or {}
        folder = self._bulk_folder
        self.bulk_scan_btn.setEnabled(False)
        self.bulk_scan_btn.setText("⏳ در حال بررسی...")

        def _worker():
            groups = scan_product_image_folder(folder)
            conn, _, _ = open_sql_connection(config, timeout=8)
            cursor = conn.cursor()
            cursor.execute("SELECT A_Code, A_Code_C, A_Name FROM Article")
            all_rows = cursor.fetchall()
            code_rows = [(str(r[0] or "").strip(), str(r[1] or "").strip()) for r in all_rows]
            name_by_code = {str(r[0] or "").strip(): str(r[2] or "").strip() for r in all_rows}
            manual_by_code = {str(r[0] or "").strip(): str(r[1] or "").strip() for r in all_rows}
            conn.close()
            lookup = build_product_code_lookup(code_rows)
            product_map = load_product_woo_map()

            results = []
            for file_code, items in groups.items():
                a_code = lookup.resolve(file_code)
                if not a_code:
                    results.append((file_code, "—", "—", "—", len(items), "❌ کد ناشناس (در ERP نیست)", None))
                    continue
                name = name_by_code.get(a_code, "—")
                manual_code = manual_by_code.get(a_code, "") or "—"
                if a_code not in product_map:
                    results.append((file_code, name, a_code, manual_code, len(items), "⚠️ این کالا با فروشگاه سینک نشده", None))
                    continue
                results.append((file_code, name, a_code, manual_code, len(items), "✅ آماده‌ی آپلود", items))
            return results

        def _done(results):
            self.bulk_scan_btn.setEnabled(True)
            self.bulk_scan_btn.setText("🔎 بررسی تطبیق با کالاها")
            self._fill_bulk_table(results)

        def _fail(msg):
            self.bulk_scan_btn.setEnabled(True)
            self.bulk_scan_btn.setText("🔎 بررسی تطبیق با کالاها")
            err = format_db_error(Exception(str(msg)))
            QMessageBox.critical(self, "خطا", f"بررسی ناموفق بود:\n{err}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _fill_bulk_table(self, results):
        self.bulk_table.setRowCount(0)
        self._bulk_matched_groups = {}
        self._bulk_row_checkboxes = {}
        self._bulk_row_items = {}  # row -> (a_code, items) فقط برای ردیف‌های آماده
        self._bulk_row_ready = {}  # row -> bool (برای فیلتر)
        ready_count = 0
        for file_code, name, a_code, manual_code, count, status, items in results:
            row = self.bulk_table.rowCount()
            self.bulk_table.insertRow(row)

            is_ready = bool(items)
            cb = QCheckBox()
            cb.setEnabled(is_ready)
            cb_wrap = QWidget()
            cb_layout = QHBoxLayout(cb_wrap)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.setAlignment(Qt.AlignCenter)
            cb_layout.addWidget(cb)
            self.bulk_table.setCellWidget(row, 0, cb_wrap)
            self._bulk_row_checkboxes[row] = cb
            if is_ready:
                cb.setChecked(True)  # پیش‌فرض: آماده‌ها انتخاب‌شده باشن (رفتار قبلی حفظ می‌شه)

            self.bulk_table.setItem(row, 1, QTableWidgetItem(file_code))
            self.bulk_table.setItem(row, 2, QTableWidgetItem(name))
            self.bulk_table.setItem(row, 3, QTableWidgetItem(a_code))
            self.bulk_table.setItem(row, 4, QTableWidgetItem(manual_code))
            self.bulk_table.setItem(row, 5, QTableWidgetItem(str(count)))
            self.bulk_table.setItem(row, 6, QTableWidgetItem(status))

            self._bulk_row_ready[row] = is_ready
            if items:
                self._bulk_row_items[row] = (a_code, items)
                ready_count += 1

        self.bulk_summary_label.setText(
            f"📊 {len(results)} کد در پوشه پیدا شد | {ready_count} مورد آماده‌ی آپلود"
        )
        self._apply_bulk_filter()

    def _apply_bulk_filter(self):
        mode = self.bulk_filter_combo.currentData() if hasattr(self, "bulk_filter_combo") else "all"
        for row, is_ready in getattr(self, "_bulk_row_ready", {}).items():
            show = True
            if mode == "ready":
                show = is_ready
            elif mode == "not_ready":
                show = not is_ready
            self.bulk_table.setRowHidden(row, not show)

    def _bulk_select_all(self, checked: bool):
        for row, cb in getattr(self, "_bulk_row_checkboxes", {}).items():
            if cb.isEnabled() and not self.bulk_table.isRowHidden(row):
                cb.setChecked(checked)

    def _preview_bulk_row(self, row, column):
        if column == 0:
            return  # کلیک روی خودِ چک‌باکس نباید پیش‌نمایش باز کنه
        entry = self._bulk_row_items.get(row)
        if not entry:
            return
        _a_code, items = entry
        if items:
            first_path = items[0][1] if isinstance(items[0], (list, tuple)) else items[0]
            self._show_image_preview_dialog(first_path)

    def _run_bulk_upload(self):
        self._bulk_matched_groups = {
            a_code: items
            for row, (a_code, items) in getattr(self, "_bulk_row_items", {}).items()
            if self._bulk_row_checkboxes.get(row) and self._bulk_row_checkboxes[row].isChecked()
        }
        if not self._bulk_matched_groups:
            QMessageBox.information(
                self, "چیزی برای آپلود نیست",
                "هیچ ردیفی تیک نخورده — یا «بررسی تطبیق» را بزنید یا از لیست، ردیف‌های ✅ را تیک بزنید.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("تأیید آپلود")
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"{len(self._bulk_matched_groups)} کالا با تصاویر این پوشه به‌روزرسانی می‌شوند."))

        mode_group = QButtonGroup(dialog)
        replace_radio = QRadioButton("🔁 جایگزینی — گالری فعلی محصول پاک و با این تصاویر جایگزین شود")
        append_radio = QRadioButton("➕ اضافه‌کردن — این تصاویر به گالری فعلی اضافه شوند (چیزی حذف نشود)")
        replace_radio.setChecked(True)
        mode_group.addButton(replace_radio)
        mode_group.addButton(append_radio)
        layout.addWidget(replace_radio)
        layout.addWidget(append_radio)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("📤 شروع آپلود")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return
        append_mode = append_radio.isChecked()

        config = load_secure_config(None) or {}
        product_map = load_product_woo_map()
        matched_groups = dict(self._bulk_matched_groups)

        self.bulk_upload_btn.setEnabled(False)
        self.bulk_upload_btn.setText("⏳ در حال آپلود...")

        ps_mode = is_prestashop(config)

        def _worker():
            if ps_mode:
                from sync_app.core.ps_sync_helper import (
                    ps_delete_product_image, ps_get_product_image_ids, ps_upload_product_image,
                )
            else:
                apply_network_overrides(config)
                wcapi = build_wcapi(config)

            ok_count = 0
            failed = []
            for a_code, items in matched_groups.items():
                wc_id = product_map.get(a_code)
                if not wc_id:
                    failed.append(f"{a_code} (سینک نشده)")
                    continue
                try:
                    if ps_mode:
                        # پرستاشاپ آرایه‌ی «ست‌کردن یک‌جا» گالری نداره — برای
                        # جایگزینی، اول تصاویر فعلی یکی‌یکی حذف می‌شن.
                        pid = int(wc_id)
                        if not append_mode:
                            for existing_id in ps_get_product_image_ids(config, pid):
                                ps_delete_product_image(config, pid, existing_id)
                        for _idx, path in items:
                            with open(path, "rb") as f:
                                data = f.read()
                            ps_upload_product_image(config, pid, data, os.path.basename(path))
                        ok_count += 1
                        continue

                    image_ids = []
                    if append_mode:
                        resp = wcapi.get(f"products/{int(wc_id)}", params={"_fields": "images"})
                        data_existing = resp.json()
                        existing = data_existing.get("images") or [] if isinstance(data_existing, dict) else []
                        image_ids = [{"id": im.get("id")} for im in existing if isinstance(im, dict) and im.get("id")]

                    for _idx, path in items:
                        with open(path, "rb") as f:
                            data = f.read()
                        ok, media_id, _url, err = wp_upload_media_ex(
                            config, data, os.path.basename(path), fallback_stem=a_code
                        )
                        if not ok:
                            raise RuntimeError(err)
                        image_ids.append({"id": media_id})
                    ok2, _resp, err2 = update_wc_product_images(config, wc_id, image_ids)
                    if not ok2:
                        raise RuntimeError(err2)
                    ok_count += 1
                except Exception as exc:
                    failed.append(f"{a_code} ({exc})")
            return ok_count, failed

        def _done(result):
            ok_count, failed = result
            self.bulk_upload_btn.setEnabled(True)
            self.bulk_upload_btn.setText("📤 شروع آپلود موارد تطبیق‌یافته")
            msg = f"✅ {ok_count} کالا با موفقیت آپلود شد."
            if failed:
                msg += f"\n❌ ناموفق ({len(failed)}): {', '.join(failed[:10])}"
            QMessageBox.information(self, "نتیجه آپلود", msg)

        def _fail(msg):
            self.bulk_upload_btn.setEnabled(True)
            self.bulk_upload_btn.setText("📤 شروع آپلود موارد تطبیق‌یافته")
            QMessageBox.critical(self, "خطا", f"آپلود گروهی ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    # ------------------------------------------------------------------
    # بخش ۳: تشخیص تصویر تکراری
    # ------------------------------------------------------------------
    def _build_duplicate_group(self) -> QGroupBox:
        group = QGroupBox("۳) تصاویر تکراری")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        row = QHBoxLayout()
        self.dup_pick_btn = QPushButton("📁 انتخاب پوشه‌ی تصاویر")
        self.dup_pick_btn.clicked.connect(self._pick_dup_folder)
        row.addWidget(self.dup_pick_btn)
        self.dup_folder_label = QLabel("پوشه‌ای انتخاب نشده")
        self.dup_folder_label.setStyleSheet("color:#64748b;")
        row.addWidget(self.dup_folder_label)
        row.addStretch()
        self.dup_run_btn = QPushButton("🔍 اسکن تکراری‌ها")
        self.dup_run_btn.clicked.connect(self._run_duplicate_scan)
        row.addWidget(self.dup_run_btn)
        layout.addLayout(row)

        self.dup_list = QListWidget()
        self.dup_list.setMinimumHeight(140)
        self.dup_list.itemClicked.connect(self._preview_dup_item)
        layout.addWidget(self.dup_list)

        group.setLayout(layout)
        return group

    def _preview_dup_item(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self._show_image_preview_dialog(path)

    def _pick_dup_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "پوشه‌ی تصاویر برای اسکن")
        if not folder:
            return
        self._dup_folder = folder
        self.dup_folder_label.setText(folder)

    def _run_duplicate_scan(self):
        if not self._dup_folder or not os.path.isdir(self._dup_folder):
            QMessageBox.information(self, "پوشه انتخاب نشده", "ابتدا یک پوشه انتخاب کنید.")
            return

        folder = self._dup_folder
        self.dup_run_btn.setEnabled(False)
        self.dup_run_btn.setText("⏳ در حال اسکن...")
        self.dup_list.clear()

        def _worker():
            paths = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if is_supported_image(os.path.join(folder, f))
            ]
            return find_duplicate_groups(paths, max_distance=10)

        def _done(groups):
            self.dup_run_btn.setEnabled(True)
            self.dup_run_btn.setText("🔍 اسکن تکراری‌ها")
            if not groups:
                self.dup_list.addItem("✅ هیچ تصویر تکراری/مشابهی پیدا نشد.")
                return
            for idx, group in enumerate(groups, start=1):
                header = QListWidgetItem(f"── گروه {idx} ({len(group)} تصویر مشابه) ──")
                header.setFlags(Qt.NoItemFlags)
                self.dup_list.addItem(header)
                for path in group:
                    item = QListWidgetItem("   " + os.path.basename(path))
                    item.setData(Qt.UserRole, path)
                    item.setToolTip("برای پیش‌نمایش کلیک کنید")
                    self.dup_list.addItem(item)

        def _fail(msg):
            self.dup_run_btn.setEnabled(True)
            self.dup_run_btn.setText("🔍 اسکن تکراری‌ها")
            QMessageBox.critical(self, "خطا", f"اسکن ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    # ------------------------------------------------------------------
    # بخش ۴: تشخیص تصاویر بی‌کیفیت (رزولوشن پایین / تار)
    # ------------------------------------------------------------------
    def _build_low_quality_group(self) -> QGroupBox:
        group = QGroupBox("۴) تصاویر بی‌کیفیت")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        note = QLabel(
            "⚠️ این یک بررسی heuristic ساده است (نه ابزار حرفه‌ای تشخیص تاری) — "
            "بر اساس رزولوشن و میزان جزئیات لبه‌های تصویر. ممکن است گاهی اشتباه تشخیص دهد."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#b45309; font-size:11px;")
        layout.addWidget(note)

        row = QHBoxLayout()
        self.lq_pick_btn = QPushButton("📁 انتخاب پوشه‌ی تصاویر")
        self.lq_pick_btn.clicked.connect(self._pick_lq_folder)
        row.addWidget(self.lq_pick_btn)
        self.lq_folder_label = QLabel("پوشه‌ای انتخاب نشده")
        self.lq_folder_label.setStyleSheet("color:#64748b;")
        row.addWidget(self.lq_folder_label)
        row.addStretch()
        self.lq_run_btn = QPushButton("🔍 بررسی کیفیت")
        self.lq_run_btn.clicked.connect(self._run_low_quality_scan)
        row.addWidget(self.lq_run_btn)
        layout.addLayout(row)

        self.lq_table = QTableWidget(0, 2)
        self.lq_table.setHorizontalHeaderLabels(["تصویر", "دلیل پرچم‌گذاری"])
        self.lq_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.lq_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lq_table.setMinimumHeight(140)
        layout.addWidget(self.lq_table)

        group.setLayout(layout)
        self._lq_folder = ""
        return group

    def _pick_lq_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "پوشه‌ی تصاویر برای بررسی کیفیت")
        if not folder:
            return
        self._lq_folder = folder
        self.lq_folder_label.setText(folder)

    def _run_low_quality_scan(self):
        if not self._lq_folder or not os.path.isdir(self._lq_folder):
            QMessageBox.information(self, "پوشه انتخاب نشده", "ابتدا یک پوشه انتخاب کنید.")
            return

        folder = self._lq_folder
        self.lq_run_btn.setEnabled(False)
        self.lq_run_btn.setText("⏳ در حال بررسی...")
        self.lq_table.setRowCount(0)

        def _worker():
            flagged = []
            for f in os.listdir(folder):
                path = os.path.join(folder, f)
                if not is_supported_image(path):
                    continue
                is_low, reasons = detect_low_quality(path)
                if is_low:
                    flagged.append((f, "، ".join(reasons)))
            return flagged

        def _done(flagged):
            self.lq_run_btn.setEnabled(True)
            self.lq_run_btn.setText("🔍 بررسی کیفیت")
            if not flagged:
                self.lq_table.setRowCount(1)
                self.lq_table.setItem(0, 0, QTableWidgetItem("✅"))
                self.lq_table.setItem(0, 1, QTableWidgetItem("هیچ تصویر مشکوکی پیدا نشد."))
                return
            for name, reason in flagged:
                row = self.lq_table.rowCount()
                self.lq_table.insertRow(row)
                self.lq_table.setItem(row, 0, QTableWidgetItem(name))
                self.lq_table.setItem(row, 1, QTableWidgetItem(reason))

        def _fail(msg):
            self.lq_run_btn.setEnabled(True)
            self.lq_run_btn.setText("🔍 بررسی کیفیت")
            QMessageBox.critical(self, "خطا", f"بررسی ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    # ------------------------------------------------------------------
    # بخش ۳: امتیاز آمادگی انتشار محصولات
    # ------------------------------------------------------------------
    def _build_readiness_group(self) -> QGroupBox:
        group = QGroupBox("۵) آمادگی انتشار محصولات")
        group.setAlignment(Qt.AlignRight)
        layout = QVBoxLayout()
        layout.setSpacing(8)

        self.readiness_run_btn = QPushButton("📊 بررسی آمادگی محصولات")
        self.readiness_run_btn.setMinimumHeight(38)
        self.readiness_run_btn.clicked.connect(self._run_readiness_check)
        layout.addWidget(self.readiness_run_btn)

        self.readiness_table = QTableWidget(0, 4)
        self.readiness_table.setHorizontalHeaderLabels(["نام کالا", "کد کالا", "امتیاز", "موارد ناقص"])
        self.readiness_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.readiness_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.readiness_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.readiness_table.setMinimumHeight(220)
        layout.addWidget(self.readiness_table)

        group.setLayout(layout)
        return group

    def _run_readiness_check(self):
        config = load_secure_config(None) or {}
        selected_groups = [str(g).strip() for g in config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()]
        if not selected_groups:
            QMessageBox.warning(
                self, "گروهی انتخاب نشده",
                "ابتدا در تب «دسته‌بندی‌ها» زیرگروه موردنظر را تیک بزنید.",
            )
            return

        self.readiness_run_btn.setEnabled(False)
        self.readiness_run_btn.setText("⏳ در حال بررسی...")

        def _worker():
            return self._fetch_readiness_rows(config, selected_groups)

        def _done(rows):
            self.readiness_run_btn.setEnabled(True)
            self.readiness_run_btn.setText("📊 بررسی آمادگی محصولات")
            self._fill_readiness_table(rows)

        def _fail(msg):
            self.readiness_run_btn.setEnabled(True)
            self.readiness_run_btn.setText("📊 بررسی آمادگی محصولات")
            err = format_db_error(Exception(str(msg)))
            QMessageBox.critical(self, "خطای دیتابیس", f"بررسی آمادگی ناموفق بود:\n{err}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _fetch_readiness_rows(self, config, selected_groups):
        from sync_app.core.erp_image_helper import resolve_erp_picture_path
        from sync_app.core.sync_utils import app_path

        price_col = config.get("PRICE_LIST_COLUMN", "Sel_Price")
        product_map = load_product_woo_map()
        cat_map = load_category_map()

        conn, _, _ = open_sql_connection(config, timeout=8)
        cursor = conn.cursor()
        like_conditions = " OR ".join(["A_Code LIKE ?" for _ in selected_groups])
        query = f"""
            SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5,
                   Exist, Picture, PicturePath, Attribute
            FROM Article
            WHERE {like_conditions}
        """
        cursor.execute(query, [f"{g}%" for g in selected_groups])
        sql_rows = cursor.fetchall()
        conn.close()

        # چک زنده‌ی ووکامرس — چون محصول ممکنه عکسش رو مستقیم توی خود سایت
        # (نه از طریق ERP) آپلود کرده باشن که چک‌های محلی هیچ‌وقت نمی‌بینن.
        # فقط برای محصولاتی که از قبل سینک شدن (تا کند نشه).
        woo_has_image = {}
        try:
            synced_wc_ids = [
                int(product_map[str(r[0]).strip()])
                for r in sql_rows
                if str(r[0]).strip() in product_map
            ]
            if synced_wc_ids and is_prestashop(config):
                # پرستاشاپ فیلتر ارزانِ چندشناسه‌ایِ معادل include ووکامرس
                # نداره — یکی‌یکی می‌خونیم؛ شکست هر محصول باعث توقف بقیه نمی‌شه.
                from sync_app.core.ps_sync_helper import ps_get_product_image_ids

                for pid in synced_wc_ids:
                    try:
                        woo_has_image[pid] = bool(ps_get_product_image_ids(config, pid))
                    except Exception:
                        continue
            elif synced_wc_ids:
                apply_network_overrides(config)
                wcapi = build_wcapi(config)
                for i in range(0, len(synced_wc_ids), 80):
                    batch_ids = synced_wc_ids[i:i + 80]
                    resp = wcapi.get(
                        "products",
                        params={
                            "include": ",".join(str(x) for x in batch_ids),
                            "per_page": 100,
                            "_fields": "id,images",
                        },
                    )
                    data = resp.json()
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                woo_has_image[item.get("id")] = bool(item.get("images"))
        except Exception:
            pass  # چک زنده اختیاریه — اگه اینترنت/سایت مشکل داشت، فقط به چک محلی بسنده می‌کنیم

        rows = []
        for row in sql_rows:
            sku = str(row[0]).strip()
            name = str(row[1]).strip()
            price = resolve_article_price(row, price_col, price_start_index=2)
            stock = int(row[7] or 0)

            # عکس واقعاً موجود است — نه فقط ستون خالی نبودن یا پسوند درست:
            # داده‌ی هر منبع واقعاً با PIL باز و تأیید می‌شود (img.verify())
            # تا مقادیر جای‌گذار کوچک/خراب ERP اشتباهی «دارد» تشخیص داده نشوند.
            picture_blob = row[8]
            picture_path_raw = str(row[9] or "").strip()
            has_blob_image = is_valid_image_data(bytes(picture_blob)) if picture_blob else False
            resolved_path = resolve_erp_picture_path(picture_path_raw, config) if picture_path_raw else ""
            has_path_image = is_valid_image_file(resolved_path) if resolved_path else False
            manual_dir = app_path("product_images", sku)
            has_manual_image = os.path.isdir(manual_dir) and any(
                is_valid_image_file(os.path.join(manual_dir, f)) for f in os.listdir(manual_dir)
            )
            wc_id = product_map.get(sku)
            has_woo_image = bool(woo_has_image.get(int(wc_id))) if wc_id else False
            has_image = has_blob_image or has_path_image or has_manual_image or has_woo_image

            description = str(row[10] or "").strip() if len(row) > 10 else ""
            categories = resolve_product_categories(sku, cat_map, {})

            product = {
                "has_image": has_image,
                "has_category": bool(categories),
                "price": price,
                "stock": stock,
                "description": description,
                "synced_to_woo": sku in product_map,
            }
            result = product_readiness(product)
            missing = [c.missing_label for c in result.checks if not c.ok]
            rows.append((sku, name, result.score, missing))
        rows.sort(key=lambda r: r[2])
        return rows

    def _fill_readiness_table(self, rows):
        self.readiness_table.setRowCount(0)
        for sku, name, score, missing in rows:
            row = self.readiness_table.rowCount()
            self.readiness_table.insertRow(row)
            self.readiness_table.setItem(row, 0, QTableWidgetItem(name))
            self.readiness_table.setItem(row, 1, QTableWidgetItem(sku))
            score_item = QTableWidgetItem(f"{score}")
            if score >= 90:
                score_item.setForeground(Qt.darkGreen)
            elif score >= 60:
                score_item.setForeground(Qt.darkYellow)
            else:
                score_item.setForeground(Qt.red)
            self.readiness_table.setItem(row, 2, score_item)
            self.readiness_table.setItem(row, 3, QTableWidgetItem("، ".join(missing) if missing else "✅ کامل"))
