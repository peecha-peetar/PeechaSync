"""دیالوگِ گزارشِ تاریخچهٔ همگام‌سازی — نسخه‌یِ سادهٔ خواندنی به‌جایِ
لاگِ خامِ پیچیده، جداگانه برایِ هر بخش (دسته‌بندی/ویژگی/متغیر/محصول)،
با فیلترِ بازه‌یِ تاریخِ شمسی و پیش‌نمایشِ چاپ."""

from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextDocument
from PyQt5.QtPrintSupport import QPrinter, QPrintPreviewDialog
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.jalali_date_widget import JalaliDateEdit
from sync_app.core.jalali_log_formatter import format_datetime_jalali
from sync_app.core.sync_history import ENTITY_LABELS, query_sync_history


class _EntityReportTab(QWidget):
    """یک تبِ گزارش برایِ یک نوعِ آیتم (مثلاً فقط «محصول»)."""

    def __init__(self, entity_type: str, parent=None):
        super().__init__(parent)
        self.entity_type = entity_type
        self._events: list[dict] = []

        root = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("از تاریخ:"))
        self.date_from = JalaliDateEdit()
        self.date_from.set_start_of_month()
        filter_row.addWidget(self.date_from)
        filter_row.addWidget(QLabel("تا تاریخ:"))
        self.date_to = JalaliDateEdit()
        self.date_to.set_today()
        filter_row.addWidget(self.date_to)
        self.refresh_btn = QPushButton("🔄 نمایش")
        self.refresh_btn.clicked.connect(self.refresh)
        filter_row.addWidget(self.refresh_btn)
        filter_row.addStretch(1)
        self.print_btn = QPushButton("🖨 پیش‌نمایشِ چاپ")
        self.print_btn.clicked.connect(self.open_print_preview)
        filter_row.addWidget(self.print_btn)
        root.addLayout(filter_row)

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(self.count_label)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["نام", "تاریخ و ساعت"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 360)
        root.addWidget(self.table, 1)

        self.refresh()

    def refresh(self):
        date_from = self.date_from.get_gregorian_date()
        date_to = self.date_to.get_gregorian_date()
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        self._events = query_sync_history(self.entity_type, date_from=date_from, date_to=date_to)

        self.table.setRowCount(len(self._events))
        for row, ev in enumerate(self._events):
            name_item = QTableWidgetItem(ev.get("name") or "")
            name_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 0, name_item)

            dt = datetime.fromtimestamp(ev.get("ts") or 0)
            dt_item = QTableWidgetItem(format_datetime_jalali(dt))
            dt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 1, dt_item)

        label = ENTITY_LABELS.get(self.entity_type, self.entity_type)
        self.count_label.setText(f"{len(self._events)} موردِ «{label}» در این بازه همگام‌سازی شده.")

    def build_report_html(self) -> str:
        label = ENTITY_LABELS.get(self.entity_type, self.entity_type)
        jy1, jm1, jd1 = self.date_from.get_jalali()
        jy2, jm2, jd2 = self.date_to.get_jalali()
        from_str = f"{jy1:04d}/{jm1:02d}/{jd1:02d}"
        to_str = f"{jy2:04d}/{jm2:02d}/{jd2:02d}"
        rows_html = "".join(
            f"<tr><td>{i + 1}</td><td>{ev.get('name', '')}</td>"
            f"<td>{format_datetime_jalali(datetime.fromtimestamp(ev.get('ts') or 0))}</td></tr>"
            for i, ev in enumerate(self._events)
        )
        return f"""
        <html dir="rtl"><head><meta charset="utf-8"></head>
        <body style="font-family:Tahoma, sans-serif;">
        <h2>گزارشِ همگام‌سازیِ {label}</h2>
        <p>بازه: {from_str} تا {to_str} — تعداد: {len(self._events)}</p>
        <table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse; width:100%;">
        <tr style="background:#f1f5f9;"><th>#</th><th>نام</th><th>تاریخ و ساعت</th></tr>
        {rows_html}
        </table>
        </body></html>
        """

    def open_print_preview(self):
        doc = QTextDocument()
        doc.setHtml(self.build_report_html())
        printer = QPrinter(QPrinter.HighResolution)
        preview = QPrintPreviewDialog(printer, self)
        preview.paintRequested.connect(lambda p: doc.print_(p))
        preview.exec_()


class SyncHistoryReportDialog(QDialog):
    """چهار تبِ جداگانه (دسته‌بندی/ویژگی/متغیر/محصول) — هرکدوم فیلترِ
    تاریخِ خودش و دکمه‌یِ پیش‌نمایشِ چاپِ خودش رو داره."""

    ENTITY_ORDER = ("category", "attribute", "variation", "product")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 گزارشِ همگام‌سازی")
        self.resize(780, 560)
        self.setLayoutDirection(Qt.RightToLeft)

        root = QVBoxLayout(self)

        hint = QLabel(
            "برایِ هر بخش، فهرستِ سادهٔ «چه چیزی، کِی همگام شده» — به‌جایِ لاگِ خامِ پیچیده. "
            "بازهٔ تاریخ را انتخاب و «🔄 نمایش» بزنید؛ «🖨 پیش‌نمایشِ چاپ» هم یک نسخهٔ قابلِ‌چاپ می‌سازد."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        root.addWidget(hint)

        self.tabs = QTabWidget()
        self.entity_tabs: dict[str, _EntityReportTab] = {}
        for entity_type in self.ENTITY_ORDER:
            tab = _EntityReportTab(entity_type)
            self.entity_tabs[entity_type] = tab
            self.tabs.addTab(tab, ENTITY_LABELS.get(entity_type, entity_type))
        root.addWidget(self.tabs, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)
