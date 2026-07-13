"""تب مدیریت بازاریابی — تحلیل فروش، پیشنهاد تخفیف/کمپین، تقویم مناسبتی، امتیازهای کلی."""

import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
    QScrollArea, QComboBox, QTabWidget,
)
from PyQt5.QtCore import Qt

from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.sql_connection_helper import open_sql_connection, format_db_error
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.sales_report_helper import (
    build_sales_report, save_sales_report, load_sales_report,
)
from sync_app.core.marketing_helper import (
    build_marketing_infos, no_sale_products, best_sellers, high_stock_low_sales,
    low_stock_warning, suggest_action, upcoming_occasions,
)


class MarketingTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._infos = []
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("📈 مدیریت بازاریابی")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("تحلیل فروش واقعی سایت + موجودی ERP — پیشنهادهای قالب‌محور (بدون هوش مصنوعی)")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("بازه‌ی فروش:"))
        self.range_combo = QComboBox()
        self.range_combo.addItem("۹۰ روز اخیر", 90)
        self.range_combo.addItem("۳۶۵ روز اخیر", 365)
        self.range_combo.addItem("کل تاریخچه", None)
        self.range_combo.setCurrentIndex(0)
        top_row.addWidget(self.range_combo)
        self.refresh_btn = QPushButton("🔄 دریافت فروش و بروزرسانی تحلیل")
        self.refresh_btn.setMinimumHeight(38)
        self.refresh_btn.clicked.connect(self._run_analysis)
        top_row.addWidget(self.refresh_btn)
        top_row.addStretch()
        outer.addLayout(top_row)

        self.summary_label = QLabel("برای شروع، «دریافت فروش و بروزرسانی تحلیل» را بزنید.")
        self.summary_label.setStyleSheet("font-weight:700; color:#166534;")
        outer.addWidget(self.summary_label)

        self.sub_tabs = QTabWidget()
        self.sub_tabs.setLayoutDirection(Qt.RightToLeft)

        self.no_sale_table = self._make_table(["کد", "نام", "موجودی", "پیشنهاد"])
        self.sub_tabs.addTab(self._wrap(self.no_sale_table), "🚫 بدون فروش")

        self.best_sellers_table = self._make_table(["کد", "نام", "تعداد فروش", "درآمد"])
        self.sub_tabs.addTab(self._wrap(self.best_sellers_table), "🔥 پرفروش‌ها")

        self.high_stock_table = self._make_table(["کد", "نام", "موجودی", "فروش", "پیشنهاد"])
        self.sub_tabs.addTab(self._wrap(self.high_stock_table), "📦 موجودی زیاد، فروش کم")

        self.low_stock_table = self._make_table(["کد", "نام", "موجودی", "فروش", "پیشنهاد"])
        self.sub_tabs.addTab(self._wrap(self.low_stock_table), "⚠️ نزدیک اتمام موجودی")

        self.calendar_table = self._make_table(["مناسبت", "فاصله (ماه)", "پیشنهاد"])
        self.sub_tabs.addTab(self._wrap(self.calendar_table), "📅 تقویم مناسبتی")
        self._fill_calendar()

        self.trend_table = self._make_table(["ماه", "درآمد"])
        self.sub_tabs.addTab(self._wrap(self.trend_table), "📊 روند ماهانه فروش")

        outer.addWidget(self.sub_tabs)

    def _make_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        return table

    def _wrap(self, table):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(table)
        return w

    def _fill_calendar(self):
        self.calendar_table.setRowCount(0)
        for occ in upcoming_occasions(window_months=12):
            row = self.calendar_table.rowCount()
            self.calendar_table.insertRow(row)
            self.calendar_table.setItem(row, 0, QTableWidgetItem(occ["name"]))
            self.calendar_table.setItem(row, 1, QTableWidgetItem(str(occ["months_away"])))
            self.calendar_table.setItem(row, 2, QTableWidgetItem(occ["note"]))

    def _run_analysis(self):
        config = load_secure_config(None) or {}
        from sync_app.core.integrations.commerce_provider import is_prestashop, store_platform_label

        store_configured = bool(config.get("PS_URL")) if is_prestashop(config) else bool(config.get("WC_URL"))
        if not store_configured:
            QMessageBox.warning(
                self, "تنظیمات ناقص",
                f"ابتدا آدرس سایت {store_platform_label(config)} را در تنظیمات وارد کنید.",
            )
            return
        selected_groups = [str(g).strip() for g in config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()]
        if not selected_groups:
            QMessageBox.warning(self, "گروهی انتخاب نشده", "ابتدا در تب «دسته‌بندی‌ها» زیرگروه موردنظر را تیک بزنید.")
            return

        since_days = self.range_combo.currentData()
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("⏳ در حال دریافت...")

        def _worker():
            report = build_sales_report(config, since_days=since_days)
            save_sales_report(report)

            conn, _, _ = open_sql_connection(config, timeout=8)
            cursor = conn.cursor()
            like_conditions = " OR ".join(["A_Code LIKE ?" for _ in selected_groups])
            cursor.execute(
                f"SELECT A_Code, A_Name, Exist FROM Article WHERE {like_conditions}",
                [f"{g}%" for g in selected_groups],
            )
            sql_products = [
                {"sku": str(r[0]).strip(), "name": str(r[1]).strip(), "stock": int(r[2] or 0)}
                for r in cursor.fetchall()
            ]
            conn.close()

            return build_marketing_infos(sql_products, report), report

        def _done(result):
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("🔄 دریافت فروش و بروزرسانی تحلیل")
            infos, report = result
            self._infos = infos
            self.summary_label.setText(
                f"📊 {len(infos)} محصول بررسی شد | {report.total_orders} سفارش | "
                f"جمع فروش: {report.total_revenue:,.0f} | زمان: {report.generated_at}"
            )
            self._fill_all_tables(infos)
            self._fill_trend(report)

        def _fail(msg):
            self.refresh_btn.setEnabled(True)
            self.refresh_btn.setText("🔄 دریافت فروش و بروزرسانی تحلیل")
            err = format_db_error(Exception(str(msg))) if "SQL" in str(msg) else str(msg)
            QMessageBox.critical(self, "خطا", f"تحلیل ناموفق بود:\n{err}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _fill_trend(self, report):
        self.trend_table.setRowCount(0)
        max_rev = max((rev for _m, rev in report.sorted_months()), default=1) or 1
        for month, revenue in report.sorted_months():
            row = self.trend_table.rowCount()
            self.trend_table.insertRow(row)
            self.trend_table.setItem(row, 0, QTableWidgetItem(month))
            bar_len = int((revenue / max_rev) * 30)
            bar = "█" * bar_len
            self.trend_table.setItem(row, 1, QTableWidgetItem(f"{revenue:,.0f}   {bar}"))

    def _fill_all_tables(self, infos):
        self.no_sale_table.setRowCount(0)
        for i in no_sale_products(infos):
            row = self.no_sale_table.rowCount()
            self.no_sale_table.insertRow(row)
            self.no_sale_table.setItem(row, 0, QTableWidgetItem(i.sku))
            self.no_sale_table.setItem(row, 1, QTableWidgetItem(i.name))
            self.no_sale_table.setItem(row, 2, QTableWidgetItem(str(i.stock)))
            self.no_sale_table.setItem(row, 3, QTableWidgetItem(suggest_action(i)))

        self.best_sellers_table.setRowCount(0)
        for i in best_sellers(infos):
            row = self.best_sellers_table.rowCount()
            self.best_sellers_table.insertRow(row)
            self.best_sellers_table.setItem(row, 0, QTableWidgetItem(i.sku))
            self.best_sellers_table.setItem(row, 1, QTableWidgetItem(i.name))
            self.best_sellers_table.setItem(row, 2, QTableWidgetItem(str(i.qty_sold)))
            self.best_sellers_table.setItem(row, 3, QTableWidgetItem(f"{i.revenue:,.0f}"))

        self.high_stock_table.setRowCount(0)
        for i in high_stock_low_sales(infos):
            row = self.high_stock_table.rowCount()
            self.high_stock_table.insertRow(row)
            self.high_stock_table.setItem(row, 0, QTableWidgetItem(i.sku))
            self.high_stock_table.setItem(row, 1, QTableWidgetItem(i.name))
            self.high_stock_table.setItem(row, 2, QTableWidgetItem(str(i.stock)))
            self.high_stock_table.setItem(row, 3, QTableWidgetItem(str(i.qty_sold)))
            self.high_stock_table.setItem(row, 4, QTableWidgetItem(suggest_action(i)))

        self.low_stock_table.setRowCount(0)
        for i in low_stock_warning(infos):
            row = self.low_stock_table.rowCount()
            self.low_stock_table.insertRow(row)
            self.low_stock_table.setItem(row, 0, QTableWidgetItem(i.sku))
            self.low_stock_table.setItem(row, 1, QTableWidgetItem(i.name))
            self.low_stock_table.setItem(row, 2, QTableWidgetItem(str(i.stock)))
            self.low_stock_table.setItem(row, 3, QTableWidgetItem(str(i.qty_sold)))
            self.low_stock_table.setItem(row, 4, QTableWidgetItem(suggest_action(i)))
