"""تب مرکزی مشاهده و فیلتر sync.log — تمام جریان‌های نرم‌افزار."""

from __future__ import annotations

import os

from PyQt5.QtCore import QDate, Qt, QTimer
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.jalali_log_formatter import format_log_lines_jalali
from sync_app.core.log_catalog import (
    LOG_TOPIC_CHOICES,
    clear_all_sync_logs,
    filter_log_lines,
    get_sync_log_path,
    read_sync_log_lines,
)
from sync_app.core.message_boxes_fa import ask_yes_no


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621

    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)

    return jy, jm, jd


def jalali_to_gregorian(jy, jm, jd):
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186)
    gy = 400 * (days // 146097)
    days %= 146097

    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1

    gy += 4 * (days // 1461)
    days %= 1461

    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365

    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    months = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    gm = 1
    while gm <= 12 and gd > months[gm]:
        gd -= months[gm]
        gm += 1

    return gy, gm, gd


def jalali_is_leap(jy):
    return (((jy - (474 if jy > 0 else 473)) % 2820 + 474 + 38) * 682) % 2816 < 682


def jalali_month_days(jy, jm):
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return 30 if jalali_is_leap(jy) else 29


class JalaliDatePicker(QWidget):
    def __init__(self, initial_date, parent=None):
        super().__init__(parent)
        self._date = QDate.currentDate()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.input = QLineEdit()
        self.input.setReadOnly(True)
        self.input.setLayoutDirection(Qt.LeftToRight)
        self.input.setMinimumWidth(110)
        self.input.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.input)

        self.pick_btn = QToolButton()
        self.pick_btn.setText("📅")
        self.pick_btn.setCursor(Qt.PointingHandCursor)
        self.pick_btn.clicked.connect(self._open_picker)
        layout.addWidget(self.pick_btn)

        self.setDate(initial_date)

    def date(self):
        return self._date

    def setDate(self, qdate):
        if isinstance(qdate, QDate) and qdate.isValid():
            self._date = qdate
            jy, jm, jd = gregorian_to_jalali(qdate.year(), qdate.month(), qdate.day())
            self.input.setText(f"{jy:04d}/{jm:02d}/{jd:02d}")

    def _open_picker(self):
        jy, jm, jd = gregorian_to_jalali(self._date.year(), self._date.month(), self._date.day())

        dialog = QDialog(self)
        dialog.setWindowTitle("انتخاب تاریخ شمسی")
        dialog.setLayoutDirection(Qt.RightToLeft)

        form = QFormLayout(dialog)

        year_box = QSpinBox()
        year_box.setRange(1300, 1600)
        year_box.setValue(jy)

        month_box = QSpinBox()
        month_box.setRange(1, 12)
        month_box.setValue(jm)

        day_box = QSpinBox()
        day_box.setRange(1, jalali_month_days(jy, jm))
        day_box.setValue(min(jd, day_box.maximum()))

        def sync_day_limit():
            yv = year_box.value()
            mv = month_box.value()
            day_box.setMaximum(jalali_month_days(yv, mv))

        year_box.valueChanged.connect(sync_day_limit)
        month_box.valueChanged.connect(sync_day_limit)

        form.addRow("سال:", year_box)
        form.addRow("ماه:", month_box)
        form.addRow("روز:", day_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("تأیید")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec_() == QDialog.Accepted:
            gy, gm, gd = jalali_to_gregorian(year_box.value(), month_box.value(), day_box.value())
            qdate = QDate(gy, gm, gd)
            if qdate.isValid():
                self.setDate(qdate)


class LogsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("logsRoot")
        self.setLayoutDirection(Qt.RightToLeft)
        self.log_file_path = get_sync_log_path()
        self._last_rendered = ""

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._auto_refresh_if_changed)
        self.refresh_timer.start(1500)

        self._build_ui()
        self.refresh_logs()

    def showEvent(self, event):
        super().showEvent(event)
        self.log_file_path = get_sync_log_path()
        self.refresh_logs()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        info = QFrame()
        info.setObjectName("logsInfoCard")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(14, 10, 14, 10)
        info_title = QLabel("📄 مرکز گزارش رویدادها")
        info_title.setObjectName("logsInfoTitle")
        info_layout.addWidget(info_title)
        info_body = QLabel(
            "تمام عملیات همگام‌سازی، تطبیق، اتصال، بکاپ، تنظیمات و خطاهای برنامه "
            "در فایل sync.log ثبت می‌شود. فیلتر موضوع/سطح برای یافتن سریع‌تر رویدادهاست."
        )
        info_body.setObjectName("logsInfoBody")
        info_body.setWordWrap(True)
        info_layout.addWidget(info_body)
        root_layout.addWidget(info)

        filter_panel = QWidget()
        filter_panel.setObjectName("logsFilterPanel")
        filter_layout = QHBoxLayout(filter_panel)
        filter_layout.setSpacing(8)

        self.from_date = JalaliDatePicker(QDate.currentDate().addDays(-7))
        self.to_date = JalaliDatePicker(QDate.currentDate())

        self.topic_combo = QComboBox()
        self.topic_combo.setObjectName("logsTopicCombo")
        for label, value in LOG_TOPIC_CHOICES:
            self.topic_combo.addItem(label, value)

        self.level_combo = QComboBox()
        self.level_combo.setObjectName("logsLevelCombo")
        self.level_combo.addItem("همه سطوح", "all")
        self.level_combo.addItem("اطلاعات", "info")
        self.level_combo.addItem("هشدار", "warning")
        self.level_combo.addItem("خطا", "error")

        self.search_input = QLineEdit()
        self.search_input.setObjectName("logsSearchInput")
        self.search_input.setPlaceholderText("جستجوی متن در لاگ...")
        self.search_input.returnPressed.connect(self.refresh_logs)

        apply_button = QPushButton("اعمال فیلتر")
        apply_button.setObjectName("logsApplyBtn")
        apply_button.clicked.connect(self.refresh_logs)
        clear_button = QPushButton("حذف فیلتر")
        clear_button.setObjectName("logsClearFilterBtn")
        clear_button.clicked.connect(self.clear_filters)
        clear_logs_button = QPushButton("🧹 پاکسازی کامل")
        clear_logs_button.setObjectName("logsClearAllBtn")
        clear_logs_button.clicked.connect(self.clear_all_logs)

        filter_layout.addWidget(QLabel("از:"))
        filter_layout.addWidget(self.from_date)
        filter_layout.addWidget(QLabel("تا:"))
        filter_layout.addWidget(self.to_date)
        filter_layout.addWidget(QLabel("موضوع:"))
        filter_layout.addWidget(self.topic_combo)
        filter_layout.addWidget(QLabel("سطح:"))
        filter_layout.addWidget(self.level_combo)
        filter_layout.addWidget(self.search_input, 1)
        filter_layout.addWidget(apply_button)
        filter_layout.addWidget(clear_button)
        filter_layout.addWidget(clear_logs_button)
        root_layout.addWidget(filter_panel)

        self.stats_label = QLabel("")
        self.stats_label.setObjectName("logsStatsLabel")
        self.stats_label.setWordWrap(True)
        root_layout.addWidget(self.stats_label)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LeftToRight)
        self.log_view.setLineWrapMode(QTextEdit.NoWrap)
        root_layout.addWidget(self.log_view, 1)

        footer = QHBoxLayout()
        self.path_label = QLabel("")
        self.path_label.setObjectName("logsPathLabel")
        self.path_label.setWordWrap(True)
        footer.addWidget(self.path_label, 1)

        refresh_button = QPushButton("🔄 بازخوانی")
        refresh_button.setObjectName("logsRefreshBtn")
        refresh_button.clicked.connect(self.refresh_logs)
        footer.addWidget(refresh_button)
        root_layout.addLayout(footer)

        self.path_label.setText(f"مسیر: {self.log_file_path}")

    def _collect_filtered_lines(self) -> list[str]:
        lines = read_sync_log_lines()
        if not lines:
            return []
        return filter_log_lines(
            lines,
            from_date=self.from_date.date().toPyDate(),
            to_date=self.to_date.date().toPyDate(),
            topic=self.topic_combo.currentData(),
            level=self.level_combo.currentData(),
            text_filter=self.search_input.text(),
        )

    def refresh_logs(self):
        self.log_file_path = get_sync_log_path()
        self.path_label.setText(f"مسیر: {self.log_file_path}")

        try:
            all_lines = read_sync_log_lines()
            if not all_lines and not os.path.exists(self.log_file_path):
                self.stats_label.setText("هنوز رویدادی ثبت نشده — پس از اولین عملیات، لاگ اینجا نمایش داده می‌شود.")
                self.log_view.setPlainText("هنوز لاگی ایجاد نشده است.")
                self._last_rendered = ""
                return

            filtered = self._collect_filtered_lines()
            content = format_log_lines_jalali(filtered)
            self.stats_label.setText(
                f"نمایش {len(filtered):,} خط از {len(all_lines):,} خط کل "
                f"(موضوع: {self.topic_combo.currentText()} | سطح: {self.level_combo.currentText()})"
            )

            scrollbar = self.log_view.verticalScrollBar()
            at_bottom = scrollbar.value() >= max(0, scrollbar.maximum() - 2)
            self.log_view.setPlainText(content or "موردی با این فیلتر یافت نشد.")
            self._last_rendered = content
            if at_bottom:
                scrollbar.setValue(scrollbar.maximum())
        except Exception as exc:
            self.log_view.setPlainText(f"❌ خطا در خواندن لاگ‌ها: {exc}")
            self.stats_label.setText("")

    def _auto_refresh_if_changed(self):
        if not self.isVisible():
            return
        try:
            filtered = self._collect_filtered_lines()
            content = format_log_lines_jalali(filtered)
            if content == self._last_rendered:
                return
            self.refresh_logs()
        except Exception:
            pass

    def clear_filters(self):
        self.from_date.setDate(QDate.currentDate().addDays(-7))
        self.to_date.setDate(QDate.currentDate())
        self.topic_combo.setCurrentIndex(0)
        self.level_combo.setCurrentIndex(0)
        self.search_input.clear()
        self.refresh_logs()

    def clear_all_logs(self):
        if not ask_yes_no(
            self,
            "پاکسازی کامل لاگ‌ها",
            "همه فایل‌های sync.log (شامل نسخه‌های rotate) پاک شوند؟\n"
            "این کار قابل بازگشت نیست.",
            tone="warning",
            default_yes=False,
        ):
            return
        try:
            cleared = clear_all_sync_logs()
            self.refresh_logs()
            self.stats_label.setText(f"🧹 {cleared} فایل لاگ پاکسازی شد.")
        except Exception as exc:
            self.log_view.setPlainText(f"❌ خطا در پاکسازی لاگ‌ها: {exc}")
