"""تب گزارش تحلیلی فروش — از سفارشات ووکامرس، با کش محلی."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
)
from PyQt5.QtCore import Qt

from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.wc_sync_helper import build_wcapi, apply_network_overrides
from sync_app.core.sales_report_helper import (
    build_sales_report,
    save_sales_report,
    load_sales_report,
)


class SalesReportTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()
        self._load_cached()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("📈 گزارش تحلیلی فروش")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("فروش سایت (ووکامرس) — بر اساس سفارشات completed / processing / on-hold")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("بازه:"))
        self.range_combo = QComboBox()
        self.range_combo.addItem("۳۰ روز اخیر", 30)
        self.range_combo.addItem("۹۰ روز اخیر", 90)
        self.range_combo.addItem("۳۶۵ روز اخیر", 365)
        self.range_combo.addItem("کل تاریخچه", None)
        self.range_combo.setCurrentIndex(1)
        top_row.addWidget(self.range_combo)

        self.refresh_btn = QPushButton("🔄 دریافت/بروزرسانی گزارش")
        self.refresh_btn.setMinimumHeight(38)
        self.refresh_btn.clicked.connect(self._refresh)
        top_row.addWidget(self.refresh_btn)
        top_row.addStretch()
        outer.addLayout(top_row)

        self.summary_label = QLabel("گزارشی موجود نیست — دکمه‌ی «دریافت/بروزرسانی» را بزنید.")
        self.summary_label.setStyleSheet("font-weight:700; color:#166534;")
        outer.addWidget(self.summary_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["محصول", "کد", "تعداد فروش", "درآمد", "آخرین فروش"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table)

    def _load_cached(self):
        report = load_sales_report()
        if report:
            self._show_report(report, from_cache=True)

    def _refresh(self):
        config = load_secure_config(None) or {}
        if not config.get("WC_URL"):
            QMessageBox.warning(self, "تنظیمات ناقص", "ابتدا آدرس سایت ووکامرس را در تنظیمات وارد کنید.")
            return

        since_days = self.range_combo.currentData()
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("⏳ در حال دریافت سفارشات...")

        def _progress(count):
            pass  # می‌تواند بعداً به یک progress bar وصل شود

        def _worker():
            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            report = build_sales_report(wcapi, since_days=since_days, progress_cb=_progress)
            save_sales_report(report)
            return report

        def _done(report):
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("🔄 دریافت/بروزرسانی گزارش")
            self._show_report(report, from_cache=False)

        def _fail(msg):
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("🔄 دریافت/بروزرسانی گزارش")
            QMessageBox.critical(self, "خطا", f"دریافت گزارش فروش ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _show_report(self, report, *, from_cache: bool):
        tag = "📦 (از کش قبلی)" if from_cache else "✅ به‌روز شد"
        self.summary_label.setText(
            f"{tag} | زمان تولید: {report.generated_at} | تعداد سفارش: {report.total_orders} | "
            f"جمع فروش: {report.total_revenue:,.0f}"
        )
        self.table.setRowCount(0)
        for stat in report.top_products(50):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(stat.name or "—"))
            self.table.setItem(row, 1, QTableWidgetItem(stat.sku))
            self.table.setItem(row, 2, QTableWidgetItem(str(stat.qty_sold)))
            self.table.setItem(row, 3, QTableWidgetItem(f"{stat.revenue:,.0f}"))
            self.table.setItem(row, 4, QTableWidgetItem(stat.last_sale_date or "—"))
