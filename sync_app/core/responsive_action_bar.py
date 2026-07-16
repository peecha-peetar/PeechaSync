"""ردیف دکمه‌های واکنش‌گرا — از نوار compact استفاده می‌کند."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from sync_app.core.compact_icon_action_bar import (
    CompactCaptionButton,
    build_compact_icon_action_bar,
)


def _apply_button_policy(btn):
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setMinimumHeight(40)
    btn.setMinimumWidth(0)


def build_responsive_action_row(buttons: list, *, parent=None, spacing: int = 6) -> QWidget:
    """نوار compact یک‌ردیفه — دکمه‌ها باید CompactCaptionButton باشند."""
    compact = [btn for btn in (buttons or []) if btn is not None]
    if compact and not all(isinstance(btn, CompactCaptionButton) for btn in compact):
        raise TypeError(
            "build_responsive_action_row فقط CompactCaptionButton می‌پذیرد؛ "
            "از sync_app.core.compact_icon_action_bar import کنید."
        )
    return build_compact_icon_action_bar(compact, parent=parent)


def build_responsive_action_grid(
    buttons: list,
    *,
    parent=None,
    spacing: int = 6,
    max_per_row: int = 4,
) -> QWidget:
    """چند ردیف دکمه — برای تب‌هایی با دکمه‌های زیاد (مثلاً متغیرها)."""
    host = QWidget(parent)
    host.setLayoutDirection(Qt.RightToLeft)
    grid = QVBoxLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(spacing)

    per_row = max(2, int(max_per_row or 4))
    items = list(buttons or [])
    for index in range(0, len(items), per_row):
        chunk = items[index : index + per_row]
        row_host = QWidget(host)
        row_host.setLayoutDirection(Qt.RightToLeft)
        row = QHBoxLayout(row_host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(spacing)
        for btn in chunk:
            _apply_button_policy(btn)
            row.addWidget(btn, 1)
        for _pad in range(per_row - len(chunk)):
            pad = QWidget(row_host)
            pad.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            pad.setMinimumHeight(0)
            pad.setMaximumHeight(0)
            row.addWidget(pad, 1)
        grid.addWidget(row_host)

    return host
