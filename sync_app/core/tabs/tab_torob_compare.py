"""تب «مقایسه‌ی قیمت با ترب» — برای محصولاتی که از قبل به فروشگاه (ووکامرس/
پرستاشاپ) لینک شده‌اند، به‌صورتِ خودکار (با جست‌وجو بر اساسِ نامِ کالا) تویِ
ترب (torob.com) کمترین قیمت رو پیدا می‌کنه و تویِ یک جدول کنارِ قیمتِ خودمون
نشون می‌ده.

⚠️ ترب API رسمی نداره — این قابلیت با خوندنِ صفحه‌ی جستجویِ ترب کار می‌کنه
و ممکنه با تغییرِ ساختارِ سایتِ ترب یا محدودیت‌هایِ ضدربات از کار بیفته.
تطبیقِ محصول هم صرفاً بر اساسِ نامِ کالا (نه بارکد/شناسه‌ی دقیق) انجام
می‌شه، پس نتیجه‌ی هر ردیف رو قبل از اعتماد، از رویِ لینکِ ترب دستی چک کنید."""

from PyQt5.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from sync_app.core.article_price import resolve_article_price
from sync_app.core.product_woo_map_helper import load_product_woo_map
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.sql_connection_helper import open_sql_connection
from sync_app.core.torob_price_helper import load_cache, save_cache, update_cache_entry


class _TorobScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    row_ready = pyqtSignal(str, str, float, dict)
    finished_all = pyqtSignal()

    def __init__(self, items, delay_seconds=1.5):
        super().__init__()
        self._items = items
        self._delay_seconds = delay_seconds
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        from sync_app.core.torob_price_helper import lookup_lowest_price
        import time

        total = len(self._items)
        for idx, item in enumerate(self._items):
            if self._cancelled:
                break
            try:
                info = lookup_lowest_price(item["name"])
            except Exception as e:
                info = {"found": False, "title": None, "price": None, "url": None, "error": str(e)}
            self.row_ready.emit(item["sku"], item["name"], item["price"], info)
            self.progress.emit(idx + 1, total, item["sku"])
            if not self._cancelled and idx < total - 1 and self._delay_seconds:
                time.sleep(self._delay_seconds)
        self.finished_all.emit()


class TorobCompareTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = {}
        self._worker = None
        self._row_by_sku = {}
        self._build_ui()
        self._load_cached_rows()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("🛒 مقایسه‌ی قیمت با ترب")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("برایِ محصولاتی که به فروشگاه لینک شده‌اند، کمترین قیمتِ ترب رو با جست‌وجویِ نامِ کالا پیدا می‌کنه")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        caveat = QLabel(
            "⚠️ ترب API رسمی نداره — این قابلیت با خوندنِ صفحه‌ی جستجویِ ترب کار می‌کنه و ممکنه "
            "گاهی خطا بده یا نتیجه پیدا نکنه. تطبیق هم بر اساسِ نامِ کالاست (نه بارکد دقیق)، پس هر "
            "ردیف رو قبل از اعتماد از رویِ لینکِ ترب چک کنید. برایِ جلوگیری از مسدودشدن، بینِ هر "
            "درخواست یه مکثِ کوتاه گذاشته شده — اسکنِ تعدادِ زیاد ممکنه طول بکشه."
        )
        caveat.setWordWrap(True)
        caveat.setStyleSheet("color:#b45309; font-size:11px;")
        outer.addWidget(caveat)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("حداکثرِ تعدادِ محصول در هر اسکن:"))
        self.max_count_spin = QSpinBox()
        self.max_count_spin.setRange(1, 500)
        self.max_count_spin.setValue(20)
        self.max_count_spin.setToolTip("برایِ جلوگیری از مسدودشدنِ IP توسطِ ترب، تعدادِ زیاد رو مرحله‌به‌مرحله اسکن کنید.")
        top_row.addWidget(self.max_count_spin)

        self.scan_btn = QPushButton("🔍 شروعِ اسکن")
        self.scan_btn.setMinimumHeight(36)
        self.scan_btn.clicked.connect(self._start_scan)
        top_row.addWidget(self.scan_btn)

        self.stop_btn = QPushButton("⏹ توقف")
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_scan)
        top_row.addWidget(self.stop_btn)

        top_row.addStretch()
        outer.addLayout(top_row)

        self.status_label = QLabel("برایِ شروع، دکمه‌ی «شروعِ اسکن» رو بزنید.")
        self.status_label.setStyleSheet("color:#4b5563; font-size:11px;")
        outer.addWidget(self.status_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "کدِ کالا", "نامِ کالا", "قیمتِ ما", "کمترین قیمتِ ترب", "اختلاف", "لینکِ ترب",
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        outer.addWidget(self.table)

        self.setLayout(outer)

    # ── بارگذاریِ محصولاتِ لینک‌شده از ERP ─────────────────────────
    def _linked_products(self, limit: int) -> list[dict]:
        config = load_secure_config(None) or {}
        product_map = load_product_woo_map()
        if not product_map:
            return []

        price_col = config.get("PRICE_LIST_COLUMN", "Sel_Price")
        is_toman = bool(config.get("WC_CURRENCY_IS_TOMAN"))
        conn, _, _ = open_sql_connection(config, timeout=5)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5 "
            "FROM Article WHERE LEN(A_Code) >= 4"
        )
        rows = cursor.fetchall()
        conn.close()

        items = []
        for row in rows:
            sku = str(row[0]).strip()
            if sku not in product_map:
                continue
            name = str(row[1]).strip()
            if not name:
                continue
            raw_price = resolve_article_price(row, price_col, price_start_index=2)
            price = raw_price / (10.0 if is_toman else 1.0)
            items.append({"sku": sku, "name": name, "price": price})
            if len(items) >= limit:
                break
        return items

    def _load_cached_rows(self):
        cache = load_cache()
        for sku, entry in cache.items():
            info = {
                "found": entry.get("found"),
                "title": entry.get("torob_title"),
                "price": entry.get("torob_price"),
                "url": entry.get("torob_url"),
                "error": entry.get("error"),
            }
            self._add_or_update_row(sku, entry.get("name") or "", entry.get("our_price") or 0.0, info)

    # ── اسکن ───────────────────────────────────────────────────────
    def _start_scan(self):
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            items = self._linked_products(self.max_count_spin.value())
        except Exception as e:
            QMessageBox.critical(self, "خطا", f"دریافتِ لیستِ محصولاتِ لینک‌شده ناموفق بود:\n{e}")
            return

        if not items:
            QMessageBox.information(
                self, "محصولی پیدا نشد",
                "هیچ محصولِ لینک‌شده‌ای به فروشگاه پیدا نشد — ابتدا چند محصول رو تویِ تبِ محصولات به فروشگاه لینک/سینک کنید.",
            )
            return

        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"⏳ در حالِ اسکن... 0/{len(items)}")

        self._worker = _TorobScanWorker(items)
        self._worker.progress.connect(self._on_progress)
        self._worker.row_ready.connect(self._on_row_ready)
        self._worker.finished_all.connect(self._on_scan_finished)
        self._worker.start()

    def _stop_scan(self):
        if self._worker is not None:
            self._worker.cancel()
            self.status_label.setText("⏹ در حالِ توقف... (منتظرِ پایانِ درخواستِ جاری)")

    def _on_progress(self, done, total, sku):
        self.status_label.setText(f"⏳ در حالِ اسکن... {done}/{total} — آخرین کد: {sku}")

    def _on_row_ready(self, sku, name, our_price, info):
        self._add_or_update_row(sku, name, our_price, info)
        cache = load_cache()
        update_cache_entry(cache, sku, name, our_price, info)
        save_cache(cache)

    def _on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"✅ اسکن تمام شد — {self.table.rowCount()} ردیف تویِ جدول.")
        self._worker = None

    # ── جدول ─────────────────────────────────────────────────────
    def _add_or_update_row(self, sku, name, our_price, info):
        row = self._row_by_sku.get(sku)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._row_by_sku[sku] = row

        self.table.setItem(row, 0, QTableWidgetItem(sku))
        self.table.setItem(row, 1, QTableWidgetItem(name))
        self.table.setItem(row, 2, QTableWidgetItem(f"{our_price:,.0f}"))

        torob_price = info.get("price")
        torob_url = info.get("url") or ""
        if info.get("found") and torob_price is not None:
            self.table.setItem(row, 3, QTableWidgetItem(f"{torob_price:,.0f}"))
            diff = our_price - torob_price
            diff_item = QTableWidgetItem(f"{diff:+,.0f}")
            if diff > 0:
                diff_item.setForeground(Qt.red)  # قیمتِ ما گرون‌تره
            elif diff < 0:
                diff_item.setForeground(Qt.darkGreen)  # قیمتِ ما ارزون‌تره
            self.table.setItem(row, 4, diff_item)
            link_item = QTableWidgetItem("🔗 مشاهده در ترب")
            link_item.setData(Qt.UserRole, torob_url)
            self.table.setItem(row, 5, link_item)
        else:
            err = info.get("error") or "پیدا نشد"
            self.table.setItem(row, 3, QTableWidgetItem(f"⭕ {err}"))
            self.table.setItem(row, 4, QTableWidgetItem("—"))
            link_item = QTableWidgetItem("—")
            link_item.setData(Qt.UserRole, torob_url)
            self.table.setItem(row, 5, link_item)

    def _on_row_double_clicked(self, row, column):
        if column != 5:
            return
        item = self.table.item(row, 5)
        url = item.data(Qt.UserRole) if item else ""
        if url:
            QDesktopServices.openUrl(QUrl(url))
