"""
ارائه‌دهنده‌ی آیکون — آیکون‌های SVG واقعی Lucide را با رنگ دلخواه (بر اساس
تم فعلی) رندر می‌کند. چون خودِ فایل‌های SVG با stroke="currentColor" هستند،
فقط با جایگزینی متن ساده، رنگ عوض می‌شود — بدون نیاز به کتابخانه‌ی اضافه.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QByteArray, QSize, Qt
from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtSvg import QSvgRenderer

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")
_render_cache: dict[str, QIcon] = {}


def available_icons() -> list[str]:
    if not os.path.isdir(_ICONS_DIR):
        return []
    return sorted(f[:-4] for f in os.listdir(_ICONS_DIR) if f.endswith(".svg"))


def _load_raw_svg(name: str) -> str | None:
    path = os.path.join(_ICONS_DIR, f"{name}.svg")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_icon(name: str, color: str = "#0F172A", *, size: int = 20) -> QIcon:
    """
    آیکون رنگی — کش می‌شود (کلید = نام+رنگ+سایز) تا هربار SVG دوباره رندر نشود.
    اگر آیکون پیدا نشود، QIcon خالی برمی‌گردد (نه خطا) — تا UI کرش نکند.
    """
    cache_key = f"{name}|{color}|{size}"
    if cache_key in _render_cache:
        return _render_cache[cache_key]

    raw = _load_raw_svg(name)
    if raw is None:
        icon = QIcon()
        _render_cache[cache_key] = icon
        return icon

    colored_svg = raw.replace('stroke="currentColor"', f'stroke="{color}"')
    renderer = QSvgRenderer(QByteArray(colored_svg.encode("utf-8")))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    icon = QIcon(pixmap)
    _render_cache[cache_key] = icon
    return icon


def clear_icon_cache() -> None:
    """موقع تعویض تم صدا زده می‌شود — چون رنگ آیکون‌ها باید عوض شود."""
    _render_cache.clear()
