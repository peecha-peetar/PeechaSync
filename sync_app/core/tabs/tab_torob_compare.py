"""تب «مقایسه‌ی قیمت با ترب» — برای محصولاتی که از قبل به فروشگاه (ووکامرس/
پرستاشاپ) لینک شده‌اند، کمترین قیمتِ ترب (torob.com) رو کنارِ قیمتِ خودمون
تویِ یک جدول نشون می‌ده. محصولات اول به‌طورِ کامل از ERP بارگذاری می‌شن،
بعد با فیلترِ دسته‌بندی/جستجو و تیک‌زدن، مشخص می‌کنیم کدوم‌ها اسکن بشن —
پس هر اجرا دقیقاً همون ردیف‌هایِ تیک‌خورده رو اسکن می‌کنه (نه یه «N تای اول»ی
که هر بار تکرار بشه).

⚠️ ترب API رسمی نداره — این قابلیت با خوندنِ صفحه‌ی جستجو/محصولِ ترب کار
می‌کنه و ممکنه با تغییرِ ساختارِ سایتِ ترب یا محدودیت‌هایِ ضدربات (مثلِ
HTTP 403/429) از کار بیفته یا کند بشه. برایِ هر کالا می‌شه لینکِ دقیقِ
صفحه‌ی ترب رو دستی وارد کرد — در اون صورت به‌جایِ جستجویِ نامی، مستقیم
همون صفحه خونده می‌شه (دقیق‌تره)."""

from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from sync_app.core.article_price import resolve_article_price
from sync_app.core.product_woo_map_helper import load_product_woo_map
from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.sql_connection_helper import open_sql_connection
from sync_app.core.torob_price_helper import (
    load_cache, save_cache, suggest_new_price, update_cache_entry,
)

COL_CHECK = 0
COL_SKU = 1
COL_NAME = 2
COL_CATEGORY = 3
COL_OUR_PRICE = 4
COL_TOROB_PRICE = 5
COL_DIFF = 6
COL_SUGGESTED = 7
COL_MANUAL_LINK = 8
COL_RESULT_LINK = 9
COLUMN_COUNT = 10

ALL_CATEGORIES = "— همه‌ی دسته‌ها —"


class _TorobScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    row_ready = pyqtSignal(str, str, float, dict)
    browser_start_failed = pyqtSignal(str)
    finished_all = pyqtSignal()

    def __init__(self, items, delay_seconds, exclude_domain, use_browser=False):
        super().__init__()
        self._items = items  # لیستِ (sku, name, our_price, manual_url)
        self._delay_seconds = delay_seconds
        self._exclude_domain = exclude_domain
        self._use_browser = use_browser
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from sync_app.core.torob_price_helper import lookup_product, TorobBrowserSession
        import time

        session = None
        if self._use_browser:
            try:
                session = TorobBrowserSession()
                session.start()
            except Exception as e:
                self.browser_start_failed.emit(str(e))
                session = None

        try:
            total = len(self._items)
            for idx, (sku, name, our_price, manual_url) in enumerate(self._items):
                if self._cancelled:
                    break
                try:
                    info = lookup_product(name, manual_url, self._exclude_domain, session)
                except Exception as e:
                    info = {"found": False, "title": None, "price": None, "url": None, "error": str(e)}
                self.row_ready.emit(sku, name, our_price, info)
                self.progress.emit(idx + 1, total, sku)
                if not self._cancelled and idx < total - 1 and self._delay_seconds:
                    time.sleep(self._delay_seconds)
        finally:
            if session is not None:
                session.close()
        self.finished_all.emit()


class TorobCompareTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = {}
        self._worker = None
        self._row_by_sku = {}
        self._categories_by_sku = {}
        self._is_toman = False
        self._build_ui()
        self._load_config_into_ui()
        self._load_cached_rows()

    # ── UI ───────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        title = QLabel("🛒 مقایسه‌ی قیمت با ترب")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("برایِ محصولاتی که به فروشگاه لینک شده‌اند، کمترین قیمتِ ترب رو کنارِ قیمتِ ما نشون می‌ده")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        caveat = QLabel(
            "⚠️ ترب API رسمی نداره — ممکنه گاهی خطا بده (مثلاً HTTP 403 یعنی موقتاً محدودمون کرده) یا نتیجه پیدا "
            "نکنه. تطبیقِ خودکار بر اساسِ نامِ کالاست، نه بارکدِ دقیق — برایِ دقتِ بیشتر، لینکِ دقیقِ صفحه‌ی ترب "
            "رو تویِ ستونِ «لینکِ دستیِ ترب» وارد کنید. قیمتِ ترب با فرضِ «تومان» خونده می‌شه — اگه واحدش با سایتِ "
            "شما جور درنیومد، خبر بدید تا اصلاح بشه."
        )
        caveat.setWordWrap(True)
        caveat.setStyleSheet("color:#b45309; font-size:11px;")
        outer.addWidget(caveat)

        # ردیفِ بارگذاری + فیلتر
        load_row = QHBoxLayout()
        self.load_btn = QPushButton("📥 بارگذاریِ محصولاتِ لینک‌شده")
        self.load_btn.setMinimumHeight(34)
        self.load_btn.clicked.connect(self._load_linked_products)
        load_row.addWidget(self.load_btn)

        load_row.addWidget(QLabel("دسته‌بندی:"))
        self.category_combo = QComboBox()
        self.category_combo.addItem(ALL_CATEGORIES)
        self.category_combo.currentIndexChanged.connect(self._apply_filters)
        load_row.addWidget(self.category_combo)

        load_row.addWidget(QLabel("جستجو:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("کد یا نامِ کالا...")
        self.search_input.textChanged.connect(self._apply_filters)
        load_row.addWidget(self.search_input, 1)

        self.select_all_btn = QPushButton("☑️ تیکِ همه‌یِ نمایش‌داده‌شده‌ها")
        self.select_all_btn.clicked.connect(lambda: self._set_visible_checked(True))
        load_row.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("⬜ برداشتنِ تیکِ همه")
        self.select_none_btn.clicked.connect(lambda: self._set_visible_checked(False))
        load_row.addWidget(self.select_none_btn)
        outer.addLayout(load_row)

        # تنظیماتِ به‌روزرسانیِ خودکارِ قیمت
        price_box = QGroupBox("⚙️ پیشنهادِ قیمتِ جدید (وقتی ترب ارزون‌تره)")
        price_layout = QHBoxLayout(price_box)
        price_layout.addWidget(QLabel("دامنه‌ی سایتِ ما در ترب (نادیده‌گرفتنِ خودمون):"))
        self.exclude_domain_input = QLineEdit()
        self.exclude_domain_input.setPlaceholderText("مثلاً mysite.com")
        self.exclude_domain_input.editingFinished.connect(self._save_config_from_ui)
        price_layout.addWidget(self.exclude_domain_input)

        price_layout.addWidget(QLabel("روش:"))
        self.discount_mode_combo = QComboBox()
        self.discount_mode_combo.addItem("درصد", "percent")
        self.discount_mode_combo.addItem("مبلغِ ثابت (تومان)", "amount")
        self.discount_mode_combo.currentIndexChanged.connect(self._save_config_from_ui)
        price_layout.addWidget(self.discount_mode_combo)

        self.discount_value_spin = QDoubleSpinBox()
        self.discount_value_spin.setRange(0, 1_000_000_000)
        self.discount_value_spin.setDecimals(0)
        self.discount_value_spin.setValue(1)
        self.discount_value_spin.valueChanged.connect(self._save_config_from_ui)
        price_layout.addWidget(self.discount_value_spin)

        self.apply_prices_btn = QPushButton("✏️ اعمالِ قیمت‌هایِ پیشنهادی روی ردیف‌هایِ تیک‌خورده")
        self.apply_prices_btn.clicked.connect(self._apply_suggested_prices)
        price_layout.addWidget(self.apply_prices_btn)
        outer.addWidget(price_box)

        # ردیفِ اسکن
        scan_row = QHBoxLayout()
        self.use_browser_checkbox = QCheckBox("🌐 استفاده از مرورگرِ واقعی (پیشنهادی — کندتره ولی از محدودیتِ ضدربات رد می‌شه)")
        self.use_browser_checkbox.setLayoutDirection(Qt.RightToLeft)
        self.use_browser_checkbox.toggled.connect(self._save_config_from_ui)
        scan_row.addWidget(self.use_browser_checkbox)

        self.install_browser_btn = QPushButton("📥 نصبِ مرورگرِ لازم (یک‌بار، ~۱۵۰ مگابایت)")
        self.install_browser_btn.clicked.connect(self._install_browser)
        scan_row.addWidget(self.install_browser_btn)

        scan_row.addWidget(QLabel("تاخیرِ بینِ درخواست‌ها (ثانیه):"))
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.5, 10.0)
        self.delay_spin.setSingleStep(0.5)
        self.delay_spin.setValue(1.5)
        self.delay_spin.valueChanged.connect(self._save_config_from_ui)
        scan_row.addWidget(self.delay_spin)

        self.scan_btn = QPushButton("🔍 شروعِ اسکنِ ردیف‌هایِ تیک‌خورده")
        self.scan_btn.setMinimumHeight(36)
        self.scan_btn.clicked.connect(self._start_scan)
        scan_row.addWidget(self.scan_btn)

        self.stop_btn = QPushButton("⏹ توقف")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_scan)
        scan_row.addWidget(self.stop_btn)
        scan_row.addStretch()
        outer.addLayout(scan_row)

        self.status_label = QLabel("برایِ شروع، «بارگذاریِ محصولاتِ لینک‌شده» رو بزنید، فیلتر/تیک کنید، بعد اسکن کنید.")
        self.status_label.setStyleSheet("color:#4b5563; font-size:11px;")
        outer.addWidget(self.status_label)

        self.table = QTableWidget(0, COLUMN_COUNT)
        self.table.setHorizontalHeaderLabels([
            "✔", "کدِ کالا", "نامِ کالا", "دسته", "قیمتِ ما", "کمترین قیمتِ ترب",
            "اختلاف", "قیمتِ پیشنهادی", "لینکِ دستیِ ترب", "نتیجه",
        ])
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_MANUAL_LINK, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        outer.addWidget(self.table)

        self.setLayout(outer)

    # ── تنظیمات (کش‌شده تویِ کانفیگِ اصلی) ───────────────────────
    def _load_config_into_ui(self):
        cfg = load_secure_config(None) or {}
        self.exclude_domain_input.setText(str(cfg.get("TOROB_EXCLUDE_DOMAIN") or ""))
        mode = cfg.get("TOROB_DISCOUNT_MODE") or "percent"
        idx = self.discount_mode_combo.findData(mode)
        self.discount_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        try:
            self.discount_value_spin.setValue(float(cfg.get("TOROB_DISCOUNT_VALUE") or 1))
        except (TypeError, ValueError):
            pass
        try:
            self.delay_spin.setValue(float(cfg.get("TOROB_SCAN_DELAY_SECONDS") or 1.5))
        except (TypeError, ValueError):
            pass
        self.use_browser_checkbox.setChecked(bool(cfg.get("TOROB_USE_BROWSER", True)))

    def _save_config_from_ui(self):
        cfg = load_secure_config(None) or {}
        cfg["TOROB_EXCLUDE_DOMAIN"] = self.exclude_domain_input.text().strip()
        cfg["TOROB_DISCOUNT_MODE"] = self.discount_mode_combo.currentData()
        cfg["TOROB_DISCOUNT_VALUE"] = self.discount_value_spin.value()
        cfg["TOROB_SCAN_DELAY_SECONDS"] = self.delay_spin.value()
        cfg["TOROB_USE_BROWSER"] = self.use_browser_checkbox.isChecked()
        save_secure_config(cfg)

    def _manual_links(self) -> dict:
        cfg = load_secure_config(None) or {}
        links = cfg.get("TOROB_MANUAL_LINKS")
        return dict(links) if isinstance(links, dict) else {}

    def _save_manual_link(self, sku: str, url: str) -> None:
        cfg = load_secure_config(None) or {}
        links = cfg.get("TOROB_MANUAL_LINKS")
        links = dict(links) if isinstance(links, dict) else {}
        if url:
            links[sku] = url
        else:
            links.pop(sku, None)
        cfg["TOROB_MANUAL_LINKS"] = links
        save_secure_config(cfg)

    # ── بارگذاریِ محصولاتِ لینک‌شده از ERP (کامل، بدونِ محدودیتِ تعداد) ──
    def _sub_group_labels(self, cursor) -> list[tuple[str, str]]:
        try:
            cursor.execute("SELECT S_Groupcode, S_GroupName FROM S_Group ORDER BY LEN(S_Groupcode) DESC")
            return [(str(r[0]).strip(), str(r[1]).strip()) for r in cursor.fetchall() if str(r[0]).strip()]
        except Exception:
            return []

    def _category_for_sku(self, sku: str, groups: list[tuple[str, str]]) -> str:
        for code, name in groups:
            if code and sku.startswith(code):
                return name or code
        return "—"

    def _all_linked_products(self) -> list[dict]:
        config = load_secure_config(None) or {}
        product_map = load_product_woo_map()
        if not product_map:
            return []

        price_col = config.get("PRICE_LIST_COLUMN", "Sel_Price")
        self._is_toman = bool(config.get("WC_CURRENCY_IS_TOMAN"))
        conn, _, _ = open_sql_connection(config, timeout=8)
        cursor = conn.cursor()
        groups = self._sub_group_labels(cursor)
        cursor.execute(
            "SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5 "
            "FROM Article WHERE LEN(A_Code) >= 4"
        )
        rows = cursor.fetchall()
        conn.close()

        manual_links = self._manual_links()
        items = []
        for row in rows:
            sku = str(row[0]).strip()
            if sku not in product_map:
                continue
            name = str(row[1]).strip()
            if not name:
                continue
            raw_price = resolve_article_price(row, price_col, price_start_index=2)
            price = raw_price / (10.0 if self._is_toman else 1.0)
            items.append({
                "sku": sku,
                "name": name,
                "price": price,
                "category": self._category_for_sku(sku, groups),
                "manual_url": manual_links.get(sku, ""),
            })
        return items

    def _load_linked_products(self):
        try:
            items = self._all_linked_products()
        except Exception as e:
            QMessageBox.critical(self, "خطا", f"دریافتِ لیستِ محصولاتِ لینک‌شده ناموفق بود:\n{e}")
            return

        if not items:
            QMessageBox.information(
                self, "محصولی پیدا نشد",
                "هیچ محصولِ لینک‌شده‌ای به فروشگاه پیدا نشد — ابتدا چند محصول رو تویِ تبِ محصولات به فروشگاه لینک/سینک کنید.",
            )
            return

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self._row_by_sku.clear()
        for item in items:
            self._insert_or_get_row(item["sku"])
            self._fill_base_row(item["sku"], item["name"], item["price"], item["category"], item["manual_url"])
        self.table.blockSignals(False)

        self._refresh_category_filter(items)
        self._apply_filters()
        self.status_label.setText(f"✅ {len(items)} محصولِ لینک‌شده بارگذاری شد — فیلتر/تیک کنید و اسکن رو بزنید.")

    def _refresh_category_filter(self, items):
        current = self.category_combo.currentText()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem(ALL_CATEGORIES)
        seen = set()
        for cat in sorted({it["category"] for it in items}):
            if cat and cat not in seen:
                seen.add(cat)
                self.category_combo.addItem(cat)
        idx = self.category_combo.findText(current)
        self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.category_combo.blockSignals(False)

    # ── فیلتر ────────────────────────────────────────────────────
    def _apply_filters(self):
        category = self.category_combo.currentText()
        search = self.search_input.text().strip().lower()
        for row in range(self.table.rowCount()):
            sku_item = self.table.item(row, COL_SKU)
            name_item = self.table.item(row, COL_NAME)
            cat_item = self.table.item(row, COL_CATEGORY)
            sku = sku_item.text() if sku_item else ""
            name = name_item.text() if name_item else ""
            cat = cat_item.text() if cat_item else ""
            cat_ok = (category == ALL_CATEGORIES) or (cat == category)
            search_ok = (not search) or (search in sku.lower()) or (search in name.lower())
            self.table.setRowHidden(row, not (cat_ok and search_ok))

    def _set_visible_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, COL_CHECK)
            if item:
                item.setCheckState(state)

    # ── جدول: ساختِ/پرکردنِ ردیفِ پایه ────────────────────────────
    def _insert_or_get_row(self, sku: str) -> int:
        row = self._row_by_sku.get(sku)
        if row is not None:
            return row
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._row_by_sku[sku] = row

        check_item = QTableWidgetItem()
        check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        check_item.setCheckState(Qt.Unchecked)
        self.table.setItem(row, COL_CHECK, check_item)
        return row

    def _readonly_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _fill_base_row(self, sku, name, our_price, category, manual_url):
        row = self._insert_or_get_row(sku)
        self.table.setItem(row, COL_SKU, self._readonly_item(sku))
        self.table.setItem(row, COL_NAME, self._readonly_item(name))
        self.table.setItem(row, COL_CATEGORY, self._readonly_item(category))
        self.table.setItem(row, COL_OUR_PRICE, self._readonly_item(f"{our_price:,.0f}"))
        self.table.item(row, COL_OUR_PRICE).setData(Qt.UserRole, our_price)
        link_item = QTableWidgetItem(manual_url or "")
        self.table.setItem(row, COL_MANUAL_LINK, link_item)

    def _on_item_changed(self, item):
        if item.column() != COL_MANUAL_LINK:
            return
        sku_item = self.table.item(item.row(), COL_SKU)
        if not sku_item:
            return
        self._save_manual_link(sku_item.text(), item.text().strip())

    def _load_cached_rows(self):
        cache = load_cache()
        for sku, entry in cache.items():
            row = self._row_by_sku.get(sku)
            if row is None:
                continue
            info = {
                "found": entry.get("found"),
                "title": entry.get("torob_title"),
                "price": entry.get("torob_price"),
                "url": entry.get("torob_url"),
                "error": entry.get("error"),
            }
            self._apply_scan_result(sku, entry.get("our_price") or 0.0, info)

    # ── اسکن ───────────────────────────────────────────────────────
    def _checked_items(self):
        items = []
        for sku, row in self._row_by_sku.items():
            check_item = self.table.item(row, COL_CHECK)
            if not check_item or check_item.checkState() != Qt.Checked:
                continue
            name_item = self.table.item(row, COL_NAME)
            price_item = self.table.item(row, COL_OUR_PRICE)
            link_item = self.table.item(row, COL_MANUAL_LINK)
            name = name_item.text() if name_item else ""
            our_price = price_item.data(Qt.UserRole) if price_item else 0.0
            manual_url = (link_item.text().strip() if link_item else "") or None
            items.append((sku, name, our_price, manual_url))
        return items

    def _start_scan(self):
        if self._worker is not None and self._worker.isRunning():
            return
        items = self._checked_items()
        if not items:
            QMessageBox.information(
                self, "چیزی تیک نخورده",
                "هیچ ردیفی تیک نخورده — بعدِ «بارگذاریِ محصولاتِ لینک‌شده»، ردیف‌هایِ موردنظر رو تیک بزنید.",
            )
            return

        self._save_config_from_ui()
        exclude_domain = self.exclude_domain_input.text().strip()
        delay = self.delay_spin.value()
        use_browser = self.use_browser_checkbox.isChecked()

        if use_browser:
            from sync_app.core.torob_price_helper import browser_available

            if not browser_available():
                confirm = QMessageBox.question(
                    self, "مرورگر نصب نیست",
                    "برایِ «استفاده از مرورگرِ واقعی»، اول باید یه‌بار Chromium نصب بشه (~۱۵۰ مگابایت).\n"
                    "الان نصب کنیم؟ (ممکنه چند دقیقه طول بکشه)",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if confirm == QMessageBox.Yes:
                    self._install_browser()
                return

        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"⏳ در حالِ اسکن... 0/{len(items)}")

        self._worker = _TorobScanWorker(items, delay, exclude_domain, use_browser)
        self._worker.progress.connect(self._on_progress)
        self._worker.row_ready.connect(self._on_row_ready)
        self._worker.browser_start_failed.connect(self._on_browser_start_failed)
        self._worker.finished_all.connect(self._on_scan_finished)
        self._worker.start()

    def _stop_scan(self):
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("⏹ در حالِ توقف... (منتظرِ پایانِ درخواستِ جاری)")

    def _on_progress(self, done, total, sku):
        self.status_label.setText(f"⏳ در حالِ اسکن... {done}/{total} — آخرین کد: {sku}")

    def _on_row_ready(self, sku, name, our_price, info):
        self._apply_scan_result(sku, our_price, info)
        cache = load_cache()
        update_cache_entry(cache, sku, name, our_price, info)
        save_cache(cache)

    def _on_browser_start_failed(self, error_msg):
        self.status_label.setText(f"⚠️ راه‌اندازیِ مرورگر ناموفق بود — با درخواستِ ساده ادامه می‌ده: {error_msg[:200]}")

    def _on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("✅ اسکن تمام شد.")
        self._worker = None

    def _install_browser(self):
        from sync_app.core.torob_price_helper import install_browser

        self.install_browser_btn.setEnabled(False)
        self.status_label.setText("⏳ در حالِ نصبِ مرورگر... (ممکنه چند دقیقه طول بکشه)")

        def _worker():
            return install_browser()

        def _done(result):
            ok, msg = result
            self.install_browser_btn.setEnabled(True)
            if ok:
                self.status_label.setText("✅ مرورگر نصب شد — می‌تونید اسکن رو دوباره شروع کنید.")
            else:
                QMessageBox.warning(self, "نصب ناموفق بود", f"نصبِ مرورگر ناموفق بود:\n{msg}")
                self.status_label.setText("❌ نصبِ مرورگر ناموفق بود.")

        def _fail(msg):
            self.install_browser_btn.setEnabled(True)
            QMessageBox.warning(self, "نصب ناموفق بود", f"نصبِ مرورگر ناموفق بود:\n{msg}")
            self.status_label.setText("❌ نصبِ مرورگر ناموفق بود.")

        from sync_app.core.threading_helper import run_in_thread

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    # ── نمایشِ نتیجه‌یِ اسکن روی ردیف ──────────────────────────────
    def _apply_scan_result(self, sku, our_price, info):
        row = self._row_by_sku.get(sku)
        if row is None:
            return

        torob_price = info.get("price")
        torob_url = info.get("url") or ""
        cfg = load_secure_config(None) or {}
        discount_mode = cfg.get("TOROB_DISCOUNT_MODE") or "percent"
        discount_value = float(cfg.get("TOROB_DISCOUNT_VALUE") or 0)

        if info.get("found") and torob_price is not None:
            self.table.setItem(row, COL_TOROB_PRICE, self._readonly_item(f"{torob_price:,.0f}"))
            diff = our_price - torob_price
            diff_item = self._readonly_item(f"{diff:+,.0f}")
            if diff > 0:
                diff_item.setForeground(Qt.red)
            elif diff < 0:
                diff_item.setForeground(Qt.darkGreen)
            self.table.setItem(row, COL_DIFF, diff_item)

            suggested = suggest_new_price(our_price, torob_price, discount_mode, discount_value)
            suggested_item = self._readonly_item(f"{suggested:,.0f}" if suggested is not None else "—")
            if suggested is not None:
                suggested_item.setData(Qt.UserRole, suggested)
            self.table.setItem(row, COL_SUGGESTED, suggested_item)

            result_item = self._readonly_item("🔗 مشاهده در ترب")
            result_item.setData(Qt.UserRole, torob_url)
            self.table.setItem(row, COL_RESULT_LINK, result_item)
        else:
            err = info.get("error") or "پیدا نشد"
            self.table.setItem(row, COL_TOROB_PRICE, self._readonly_item(f"⭕ {err}"))
            self.table.setItem(row, COL_DIFF, self._readonly_item("—"))
            self.table.setItem(row, COL_SUGGESTED, self._readonly_item("—"))
            result_item = self._readonly_item("—")
            result_item.setData(Qt.UserRole, torob_url)
            self.table.setItem(row, COL_RESULT_LINK, result_item)

    def _on_cell_double_clicked(self, row, column):
        if column != COL_RESULT_LINK:
            return
        item = self.table.item(row, COL_RESULT_LINK)
        url = item.data(Qt.UserRole) if item else ""
        if url:
            QDesktopServices.openUrl(QUrl(url))

    # ── اعمالِ قیمت‌هایِ پیشنهادی رویِ فروشگاه ─────────────────────
    def _apply_suggested_prices(self):
        product_map = load_product_woo_map()
        changes = []
        for sku, row in self._row_by_sku.items():
            check_item = self.table.item(row, COL_CHECK)
            if not check_item or check_item.checkState() != Qt.Checked:
                continue
            suggested_item = self.table.item(row, COL_SUGGESTED)
            suggested = suggested_item.data(Qt.UserRole) if suggested_item else None
            if suggested is None:
                continue
            product_id = product_map.get(sku)
            if not product_id:
                continue
            name_item = self.table.item(row, COL_NAME)
            changes.append((sku, name_item.text() if name_item else sku, product_id, suggested))

        if not changes:
            QMessageBox.information(
                self, "چیزی برای اعمال نیست",
                "برایِ هیچ‌کدوم از ردیف‌هایِ تیک‌خورده، قیمتِ پیشنهادی محاسبه نشده (یا اسکن نشده‌اند).",
            )
            return

        preview = "\n".join(f"— {name} ({sku}): {price:,.0f}" for sku, name, _pid, price in changes[:20])
        more = f"\n... و {len(changes) - 20} موردِ دیگر" if len(changes) > 20 else ""
        confirm = QMessageBox.question(
            self, "تأییدِ به‌روزرسانیِ قیمت",
            f"قیمتِ {len(changes)} محصول رویِ فروشگاه به‌روز می‌شه:\n\n{preview}{more}\n\n"
            "این تغییر مستقیم رویِ سایتِ زنده اعمال می‌شه. ادامه بدیم؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        from sync_app.core.integrations.commerce_provider import store_rest_json

        config = load_secure_config(None) or {}
        errors = []
        for sku, name, product_id, new_price in changes:
            try:
                store_rest_json(
                    config, "PUT", f"products/{product_id}",
                    json_body={"regular_price": str(int(round(new_price)))},
                    label="به‌روزرسانیِ قیمت (ترب)",
                )
            except Exception as e:
                errors.append(f"{name} ({sku}): {e}")

        if errors:
            QMessageBox.warning(
                self, "بعضی موارد ناموفق بود",
                f"{len(changes) - len(errors)} از {len(changes)} با موفقیت به‌روز شد.\n\nخطاها:\n" + "\n".join(errors[:10]),
            )
        else:
            QMessageBox.information(self, "انجام شد", f"قیمتِ {len(changes)} محصول با موفقیت به‌روز شد.")
