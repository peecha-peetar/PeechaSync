"""
نگاشت آیکون هر تب — بر اساس متن عنوان تب (که از قبل ثابت و مشخص است).
این فایل فقط داده است؛ منطق اعمال آن در sidebar_icons.apply_sidebar_icons است.
"""

from __future__ import annotations

# ترتیب مهم است: اولین تطبیقِ substring در عنوان تب استفاده می‌شود.
TAB_ICON_MAP: list[tuple[str, str]] = [
    ("شروع", "house"),
    ("داشبورد", "layout-dashboard"),
    ("دسته‌بندی", "folder-tree"),
    ("ویژگی", "tag"),
    ("محصولات", "package"),
    ("متغیر", "shuffle"),
    ("مرکز رسانه", "image"),
    ("سئو", "search-check"),
    ("Marketing", "trending-up"),
    ("بازاریابی", "trending-up"),
    ("Advisor", "compass"),
    ("دستیار هوشمند", "compass"),
    ("مشتریان", "users"),
    ("سفارش", "shopping-cart"),
    ("تطبیق", "scale"),
    ("مغایرت", "scale"),
    ("لاگ", "activity"),
    ("آپدیت خودکار", "refresh-cw"),
    ("همگام", "refresh-cw"),
    ("تنظیمات", "settings"),
    ("فعال‌سازی", "badge-check"),
    ("لایسنس", "badge-check"),
]

DEFAULT_ICON = "circle-dot"


def icon_name_for_title(title: str) -> str:
    for keyword, icon_name in TAB_ICON_MAP:
        if keyword in title:
            return icon_name
    return DEFAULT_ICON
