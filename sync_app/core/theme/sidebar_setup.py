"""
تبدیل ظاهری نوار تب افقی به یک Sidebar عمودی سمت راست (چون برنامه RTL است)
— فقط موقعیت و آیکون تب‌ها عوض می‌شود؛ خودِ ویجت‌ها، محتوا، و منطق
lazy-loading هرکدام کاملاً دست‌نخورده می‌ماند (این تابع فقط روی
QTabWidget موجود کار می‌کند، هیچ تب جدیدی نمی‌سازد و هیچ‌کدام را حذف نمی‌کند).
"""

from __future__ import annotations

from PyQt5.QtWidgets import QTabWidget
from PyQt5.QtCore import QSize, Qt

from sync_app.core.theme.icon_provider import get_icon
from sync_app.core.theme.tab_icon_map import icon_name_for_title
from sync_app.core.theme.colors import get_theme


def apply_sidebar_style(tabs: QTabWidget, *, mode: str = "light", icon_size: int = 18) -> None:
    """
    tabs: همان QTabWidget اصلی برنامه (self.tabs در PeechaLauncher).

    نکته‌ی مهم (بعد از یک باگ جدی): نسخه‌ی قبلی این تابع موقعیت تب‌ها را
    به عمودی (East) عوض می‌کرد و تب‌بار را با یک نمونه‌ی سفارشی جایگزین
    می‌کرد — که چون این تابع ممکن است چندبار صدا زده شود (هر بار تغییر
    سایز پنجره)، هر بار یک تب‌بار تازه جایگزین می‌شد و با کد دیگری در
    peecha_launcher.py (که فرض می‌کند تب‌بار افقی و از نوع AdaptiveTabBar
    است) تداخل پیدا می‌کرد و باعث از بین رفتن نمایش تب‌ها می‌شد.

    برای امنیت کامل، این نسخه فقط رنگ آیکون‌ها را به‌روز می‌کند — موقعیت و
    نوع تب‌بار اصلاً دست‌کاری نمی‌شود.
    """
    tabs.setIconSize(QSize(icon_size, icon_size))
    c = get_theme(mode)
    icon_color = c["sidebar_text"]

    for index in range(tabs.count()):
        title = tabs.tabText(index)
        icon_name = icon_name_for_title(title)
        icon = get_icon(icon_name, color=icon_color, size=icon_size)
        tabs.setTabIcon(index, icon)

    c = get_theme(mode)
    icon_color = c["sidebar_text"]

    for index in range(tabs.count()):
        title = tabs.tabText(index)
        icon_name = icon_name_for_title(title)
        icon = get_icon(icon_name, color=icon_color, size=icon_size)
        tabs.setTabIcon(index, icon)
