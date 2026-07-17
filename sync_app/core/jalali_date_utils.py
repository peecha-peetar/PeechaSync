"""تبدیل تاریخِ شمسی↔میلادی — برای ورودیِ تاریخ/ساعتِ زمان‌بندیِ پست‌ها.

الگوریتمِ gregorian_to_jalali از jalali_log_formatter.py دوباره استفاده
می‌شه (برای نمایش)؛ jalali_to_gregorian اینجا اضافه شده (برای پارسِ
ورودیِ کاربر) — جفتِ استانداردِ همون الگوریتم."""

from __future__ import annotations

from datetime import datetime

from sync_app.core.jalali_log_formatter import gregorian_to_jalali

__all__ = ["gregorian_to_jalali", "jalali_to_gregorian", "jalali_now", "to_jalali_datetime_str"]


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    jy = jy + 1595
    days = (
        -355668
        + (365 * jy)
        + ((jy // 33) * 8)
        + (((jy % 33) + 3) // 4)
        + jd
        + ((jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186)
    )
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        gy += 100 * ((days - 1) // 36524)
        days = (days - 1) % 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    is_leap = gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)
    g_days_in_month = [31, 29 if is_leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    for gm in range(12):
        if gd <= g_days_in_month[gm]:
            break
        gd -= g_days_in_month[gm]
    return gy, gm + 1, gd


def jalali_now() -> tuple[int, int, int]:
    now = datetime.now()
    return gregorian_to_jalali(now.year, now.month, now.day)


def to_jalali_datetime_str(dt: datetime) -> str:
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {dt.hour:02d}:{dt.minute:02d}"
