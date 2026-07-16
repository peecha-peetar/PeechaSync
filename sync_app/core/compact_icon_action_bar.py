"""نوار دکمه فشرده — همه کپشن وقتی جا باشد؛ فشرده‌شدن فقط با کمبود فضا (بدون واکنش هاور)."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget


def split_icon_caption(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", ""
    if raw.startswith("⏹"):
        return "⏹", raw[1:].strip()
    if raw.startswith("⏳"):
        return "⏳", raw[1:].strip()
    for index, char in enumerate(raw):
        if char == " " and index > 0:
            return raw[:index].strip(), raw[index + 1 :].strip()
    return raw, ""


class CompactCaptionButton(QPushButton):
    COLLAPSED_WIDTH = 46
    MAX_EXPANDED_WIDTH = 320

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setProperty("compactActionBtn", True)
        self.setProperty("compactExpanded", "false")
        self._full_text = ""
        self._caption_visible = False
        self._pinned_open = False
        self._tooltip_text = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(44)
        self.setMaximumHeight(44)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(self.COLLAPSED_WIDTH)
        if text:
            self.setText(text)

    def setToolTip(self, tip: str) -> None:  # noqa: N802 — Qt API
        if (tip or "").strip():
            self._tooltip_text = tip.strip()
        expanded = self._caption_visible or self._pinned_open
        if expanded:
            super().setToolTip("")
        else:
            super().setToolTip(self._tooltip_text or self._full_text)

    def setText(self, text: str) -> None:  # noqa: N802 — Qt API
        was_pinned = self._pinned_open
        self._full_text = (text or "").strip()
        self._pinned_open = self._full_text.startswith(("⏹", "⏳"))
        if self._full_text.startswith("⏹"):
            self.setProperty("compactActionStop", "true")
        elif self._full_text.startswith("⏳"):
            self.setProperty("compactActionStop", "stopping")
        else:
            self.setProperty("compactActionStop", "false")
        if not self._tooltip_text:
            self._tooltip_text = super().toolTip() or ""
        self.style().unpolish(self)
        self.style().polish(self)
        self._apply_display()
        if was_pinned and not self._pinned_open:
            self._force_bar_relayout()
        else:
            self._notify_bar_relayout()

    def natural_expanded_width(self) -> int:
        metrics = self.fontMetrics()
        width = metrics.horizontalAdvance(self._full_text) + 30
        return max(self.COLLAPSED_WIDTH, min(width, self.MAX_EXPANDED_WIDTH))

    def set_expansion_flags(
        self,
        *,
        space: bool = False,
        hover: bool = False,
        sticky: bool = False,
        fill_stretch: bool = False,
        width_cap: int | None = None,
    ) -> None:
        del hover, sticky, fill_stretch, width_cap
        self.set_caption_visible(bool(space or self._pinned_open))

    def set_caption_visible(self, visible: bool) -> None:
        if visible == self._caption_visible:
            if not self._pinned_open:
                return
        self._caption_visible = visible
        self._apply_display()

    def minimumSizeHint(self):  # noqa: N802 — Qt API
        # توجه: عمداً super().minimumSizeHint() صدا زده نمی‌شود — چون در برخی
        # نسخه‌های Qt، QPushButton.minimumSizeHint() خودش داخلی sizeHint() را
        # صدا می‌زند که (چون اینجا override شده) باعث recursion بی‌نهایت می‌شود.
        return QSize(self.COLLAPSED_WIDTH, self.minimumHeight())

    def sizeHint(self):  # noqa: N802 — Qt API
        return self.minimumSizeHint()

    def _apply_display(self) -> None:
        expanded = self._caption_visible or self._pinned_open
        self.setProperty("compactExpanded", "true" if expanded else "false")
        self.style().unpolish(self)
        self.style().polish(self)

        if expanded:
            super().setText(self._full_text)
            self.setFixedWidth(self.natural_expanded_width())
            super().setToolTip("")
        else:
            icon, _ = split_icon_caption(self._full_text)
            super().setText(icon or self._full_text[:1] or "?")
            self.setFixedWidth(self.COLLAPSED_WIDTH)
            super().setToolTip((self._tooltip_text or self._full_text).strip())

    def _force_bar_relayout(self) -> None:
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, CompactIconActionBar):
                widget._last_mask = []
                QTimer.singleShot(0, widget._relayout)
                return
            widget = widget.parentWidget()

    def _notify_bar_relayout(self) -> None:
        self._force_bar_relayout()

    def refresh_theme_styles(self) -> None:
        """پس از تغییر تم — پاک‌سازی استایل inline و اعمال مجدد QSS."""
        self.setStyleSheet("")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class CompactIconActionBar(QWidget):
    """عرض نوار = کل پنل؛ دکمه‌ها به اندازه کپشن؛ فضای خالی با stretch پر می‌شود."""

    WIDTH_PADDING = 12

    def __init__(self, buttons: list, *, parent=None):
        super().__init__(parent)
        self.setObjectName("compactIconActionBar")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)

        self._buttons: list[CompactCaptionButton] = []
        self._last_mask: list[bool] = []

        items = [btn for btn in (buttons or []) if btn is not None]
        count = len(items)
        for index, button in enumerate(items):
            if not isinstance(button, CompactCaptionButton):
                raise TypeError("CompactIconActionBar فقط CompactCaptionButton می‌پذیرد.")
            if count == 1:
                position = "only"
            elif index == 0:
                position = "first"
            elif index == count - 1:
                position = "last"
            else:
                position = "middle"
            button.setProperty("compactSegPosition", position)
            self._buttons.append(button)
            self._row.addWidget(button)

        self._row.addStretch(1)

    def minimumSizeHint(self):  # noqa: N802 — Qt API
        hint = super().minimumSizeHint()
        floor = CompactCaptionButton.COLLAPSED_WIDTH + self.WIDTH_PADDING
        return QSize(floor, hint.height())

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._relayout)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _available_width(self) -> int:
        return max(0, self.width() - self.WIDTH_PADDING)

    def _row_width(self, mask: list[bool]) -> int:
        total = 0
        for index, button in enumerate(self._buttons):
            if mask[index]:
                total += button.natural_expanded_width()
            else:
                total += CompactCaptionButton.COLLAPSED_WIDTH
        return total

    def _compute_caption_mask(self, available: int) -> list[bool]:
        """
        اول همه کپشن باز؛ اگر جا نشد از چپ (index بزرگ‌تر) یکی‌یکی مخفی می‌شود.
        index=0 سمت راست (اولویت) — آخرین چیزی که مخفی می‌شود.
        """
        n = len(self._buttons)
        if n == 0:
            return []

        mask = [True] * n
        if self._row_width(mask) <= available:
            return mask

        for index in range(n - 1, -1, -1):
            mask[index] = False
            if self._row_width(mask) <= available:
                return mask

        return [False] * n

    def _update_layout_mode(self) -> None:
        """سازگاری با apply_theme — همان _relayout."""
        self._relayout()

    def refresh_theme_styles(self) -> None:
        for button in self._buttons:
            button.refresh_theme_styles()
        self._last_mask = []
        self._relayout()
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _relayout(self) -> None:
        if not self._buttons:
            return

        mask = self._compute_caption_mask(self._available_width())
        if mask == self._last_mask:
            return
        self._last_mask = mask

        for index, button in enumerate(self._buttons):
            button.set_caption_visible(mask[index])


def build_compact_icon_action_bar(buttons: list, *, parent=None) -> CompactIconActionBar:
    return CompactIconActionBar(buttons, parent=parent)
