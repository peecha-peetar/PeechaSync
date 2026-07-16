"""
دکمه‌های کوچک ردیفی (آیکون‌فقط) — تا الان تو هر تب یه رنگ/سایز دستی جدا
انتخاب می‌شد که ظاهر برنامه رو ناهماهنگ می‌کرد. این ماژول یه نقطه‌ی
مشترک می‌سازه: سایز ثابت، شعاع گوشه‌ی ثابت، و رنگ‌ها یا از تمِ فعال
برنامه (برای اکشن‌های خنثی) یا از یه پالت معناییِ ثابت (موفقیت/خطر/
هشدار — که باید همیشه همون معنی رو بدن، مستقل از تم انتخابی کاربر).
"""

from __future__ import annotations

from PyQt5.QtWidgets import QToolButton
from PyQt5.QtCore import Qt

ROW_BUTTON_SIZE = 28
ROW_BUTTON_SIZE_SMALL = 24
ROW_BUTTON_RADIUS = 6

# رنگ‌های معنایی ثابت — این‌ها نباید با تغییر تمِ برنامه عوض بشن، چون
# معنی مشخصی دارن (مثلاً دکمه‌ی حذف همیشه باید «خطر» به‌نظر برسه).
_SEMANTIC_COLORS = {
    "danger": ("#fecaca", "#fff1f2", "#fee2e2", "#b91c1c"),
    "success": ("#86efac", "#dcfce7", "#bbf7d0", "#166534"),
    "warning": ("#fde68a", "#fef9c3", "#fef08a", "#92400e"),
    "info": ("#c7d2fe", "#eef2ff", "#e0e7ff", "#3730a3"),
}


def _neutral_colors() -> tuple[str, str, str, str]:
    from sync_app.core.app_theme import get_active_theme_palette

    _, palette = get_active_theme_palette()
    border = palette.get("soft_border", "#c9c7ff")
    bg = palette.get("soft", "#ecebff")
    hover = palette.get("hover", bg)
    text = palette.get("primary", "#020025")
    return border, bg, hover, text


def row_button_style(kind: str = "neutral") -> str:
    if kind == "neutral":
        border, bg, hover, _text = _neutral_colors()
    else:
        border, bg, hover, _text = _SEMANTIC_COLORS.get(kind, _SEMANTIC_COLORS["info"])
    return (
        f"QToolButton {{ border: 1px solid {border}; border-radius: {ROW_BUTTON_RADIUS}px; "
        f"background: {bg}; }}"
        f"QToolButton:hover {{ background: {hover}; }}"
        f"QToolButton:disabled {{ opacity: 0.5; }}"
    )


def make_row_button(
    text: str,
    tooltip: str = "",
    *,
    kind: str = "neutral",
    size: int = ROW_BUTTON_SIZE,
) -> QToolButton:
    """دکمه‌ی کوچک آیکونی با ظاهر یکپارچه — برای همه‌ی اکشن‌های داخل هر ردیف."""
    btn = QToolButton()
    btn.setText(text)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(row_button_style(kind))
    return btn
