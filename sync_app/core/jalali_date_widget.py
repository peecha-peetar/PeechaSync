"""ویجتِ سبکِ ورودیِ تاریخِ شمسی (روز/ماه/سال) — بدونِ وابستگی به کتابخانه‌ی
خارجی یا پاپ‌آپِ تقویم، برایِ فیلترهایِ بازه‌ی تاریخ (مثلِ سفارشات)."""

from __future__ import annotations

from datetime import date

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QSpinBox, QWidget

from sync_app.core.jalali_date_utils import jalali_now, jalali_to_gregorian

JALALI_MONTH_NAMES = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


def _is_jalali_leap_year(jy: int) -> bool:
    """قاعده‌ی متداولِ چرخه‌ی ۳۳ساله برایِ تشخیصِ سالِ کبیسه‌یِ شمسی."""
    return (jy % 33) in (1, 5, 9, 13, 17, 22, 26, 30)


class JalaliDateEdit(QWidget):
    """روز/ماه/سالِ شمسی — سه ویجتِ ساده (بدونِ پاپ‌آپِ تقویم). ترتیبِ
    نمایش (RTL) به شکلِ متعارفِ فارسی: روز، ماه، سال."""

    dateChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # عرضِ ثابتِ کوچیک برایِ هر سه — تا وقتی کنارِ فیلترهایِ دیگه میاد،
        # فضایِ زیادی نگیره (قبلاً هر سه با عرضِ پیش‌فرضِ Qt جاگیر بودن).
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 31)
        self.day_spin.setFixedWidth(54)
        self.month_combo = QComboBox()
        self.month_combo.setLayoutDirection(Qt.RightToLeft)
        for i, name in enumerate(JALALI_MONTH_NAMES, start=1):
            self.month_combo.addItem(name, i)
        self.month_combo.setFixedWidth(110)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(1380, 1420)
        self.year_spin.setFixedWidth(78)

        layout.addWidget(self.day_spin)
        layout.addWidget(self.month_combo)
        layout.addWidget(self.year_spin)

        self.day_spin.valueChanged.connect(self.dateChanged.emit)
        self.month_combo.currentIndexChanged.connect(self._on_month_or_year_changed)
        self.year_spin.valueChanged.connect(self._on_month_or_year_changed)

        self.set_today()

    def _on_month_or_year_changed(self):
        self._update_day_range()
        self.dateChanged.emit()

    def _update_day_range(self):
        """تعدادِ روزهایِ ماهِ انتخاب‌شده رو تنظیم می‌کنه — ۶ ماهِ اول ۳۱،
        ۵ ماهِ بعد ۳۰، اسفند ۲۹ (یا ۳۰ در سالِ کبیسه)."""
        jy = self.year_spin.value()
        jm = int(self.month_combo.currentData() or 1)
        if jm <= 6:
            max_day = 31
        elif jm <= 11:
            max_day = 30
        else:
            max_day = 30 if _is_jalali_leap_year(jy) else 29
        if self.day_spin.value() > max_day:
            self.day_spin.blockSignals(True)
            self.day_spin.setValue(max_day)
            self.day_spin.blockSignals(False)
        self.day_spin.setMaximum(max_day)

    def set_today(self):
        jy, jm, jd = jalali_now()
        self.set_jalali(jy, jm, jd)

    def set_start_of_month(self):
        jy, jm, _jd = jalali_now()
        self.set_jalali(jy, jm, 1)

    def set_jalali(self, jy: int, jm: int, jd: int):
        self.year_spin.blockSignals(True)
        self.month_combo.blockSignals(True)
        self.day_spin.blockSignals(True)
        try:
            self.year_spin.setValue(jy)
            idx = self.month_combo.findData(jm)
            self.month_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.day_spin.setValue(jd)
        finally:
            self.year_spin.blockSignals(False)
            self.month_combo.blockSignals(False)
            self.day_spin.blockSignals(False)
        self._update_day_range()

    def get_jalali(self) -> tuple[int, int, int]:
        return self.year_spin.value(), int(self.month_combo.currentData() or 1), self.day_spin.value()

    def get_gregorian_date(self) -> date:
        jy, jm, jd = self.get_jalali()
        gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
        return date(gy, gm, gd)
