"""
نمودار میله‌ای ساده و سبک برای داشبورد — بدون نیاز به matplotlib/QtChart،
فقط با QPainter. برای نمودارهای کوچیک (فروش روزانه، پرفروش‌ها، سلامت سینک).
"""

from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtGui import QPainter, QColor, QFont, QPen
from PyQt5.QtCore import Qt, QRectF


class MiniBarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self._items: list[tuple[str, float, str]] = []  # (برچسب, مقدار, رنگ اختیاری)
        self._title = ""
        self._value_formatter = lambda v: f"{v:,.0f}"
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, items: list[tuple[str, float]], *, title: str = "", value_formatter=None, colors: list[str] | None = None):
        colors = colors or []
        self._items = [
            (label, value, colors[i] if i < len(colors) else "#3B82F6")
            for i, (label, value) in enumerate(items)
        ]
        self._title = title
        if value_formatter:
            self._value_formatter = value_formatter
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setLayoutDirection(Qt.RightToLeft)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#ffffff"))

        top_pad = 26 if self._title else 8
        bottom_pad = 34
        side_pad = 12

        if self._title:
            painter.setPen(QColor("#334155"))
            painter.setFont(QFont("IranSans", 10, QFont.Bold))
            painter.drawText(QRectF(side_pad, 4, w - side_pad * 2, 20), Qt.AlignRight | Qt.AlignVCenter, self._title)

        if not self._items:
            painter.setPen(QColor("#94a3b8"))
            painter.setFont(QFont("IranSans", 9))
            painter.drawText(self.rect(), Qt.AlignCenter, "داده‌ای برای نمایش نیست")
            return

        chart_top = top_pad
        chart_bottom = h - bottom_pad
        chart_h = max(10, chart_bottom - chart_top)
        max_val = max((v for _l, v, _c in self._items), default=0) or 1

        n = len(self._items)
        avail_w = w - side_pad * 2
        gap = 8
        bar_w = max(6, (avail_w - gap * (n - 1)) / n) if n else 0

        painter.setPen(QPen(QColor("#e2e8f0"), 1))
        painter.drawLine(int(side_pad), int(chart_bottom), int(w - side_pad), int(chart_bottom))

        x = side_pad
        for label, value, color in self._items:
            ratio = (value / max_val) if max_val else 0
            bar_h = max(2, ratio * chart_h)
            bar_rect = QRectF(x, chart_bottom - bar_h, bar_w, bar_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(bar_rect, 3, 3)

            painter.setPen(QColor("#0f172a"))
            painter.setFont(QFont("IranSans", 8, QFont.Bold))
            val_text = self._value_formatter(value)
            painter.drawText(
                QRectF(x - 10, chart_bottom - bar_h - 16, bar_w + 20, 14),
                Qt.AlignCenter, val_text,
            )

            painter.setPen(QColor("#64748b"))
            painter.setFont(QFont("IranSans", 8))
            label_short = label if len(label) <= 10 else label[:9] + "…"
            painter.drawText(
                QRectF(x - 14, chart_bottom + 4, bar_w + 28, bottom_pad - 6),
                Qt.AlignHCenter | Qt.AlignTop, label_short,
            )
            x += bar_w + gap
