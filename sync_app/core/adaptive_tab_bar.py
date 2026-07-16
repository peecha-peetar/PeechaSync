"""
تب‌بار با عرض تطبیقی — عرض هر تب را بر اساس متن واقعی + سایز فونت محاسبه
می‌کند (نه عرض ثابت پیش‌فرض Qt) تا هیچ لیبلی بریده/نصفه نشود. قبلاً فقط
داخل peecha_launcher.py بود و فقط برای تب‌های سطح اول استفاده می‌شد؛
اینجا مستقل شده تا تب‌های گروهی (مثل «همگام‌سازی»/«دستیار هوشمند») هم
برای زیرتب‌هاشون همین رفتار درست را داشته باشند.
"""

from PyQt5.QtWidgets import QTabBar, QScroller, QScrollerProperties, QToolButton
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QFontMetrics


class AdaptiveTabBar(QTabBar):
    """عرض هر تب بر اساس متن + سایز فونت — با اسکرول افقی در صورت کمبود جا."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tab_font_px = 15
        self._tab_hpad = 16
        self._tab_vpad = 12
        self._tab_extra = 12
        self.setUsesScrollButtons(True)
        self.setExpanding(False)
        self.setElideMode(Qt.ElideNone)
        self.setMovable(False)

        # پشتیبانی از اسکرول با کشیدن انگشت/موس — چون قبلاً فقط با کلیک
        # روی دکمه‌های فلش کوچیک می‌شد اسکرول کرد که با تاچ عملاً کار
        # نمی‌کرد. QScroller راه‌حل رسمی خودِ Qt برای این کاره (هم لمسی
        # هم کشیدن با دکمه‌ی چپ موس رو پشتیبانی می‌کنه، بدون خراب کردن
        # کلیک ساده برای انتخاب تب).
        QScroller.grabGesture(self, QScroller.LeftMouseButtonGesture)
        scroller = QScroller.scroller(self)
        props = scroller.scrollerProperties()
        props.setScrollMetric(QScrollerProperties.MousePressEventDelay, 0.0)
        props.setScrollMetric(QScrollerProperties.DragStartDistance, 0.006)
        scroller.setScrollerProperties(props)

    def wheelEvent(self, event):
        # خیلی از تاچ‌پدها/موس‌های چرخ‌دار به‌جای کشیدن، رویداد چرخ می‌فرستن —
        # این رو با کلیک برنامه‌ای روی همون دکمه‌های فلش داخلیِ خودِ Qt
        # (که setUsesScrollButtons(True) می‌سازه) به اسکرول واقعی تبدیل
        # می‌کنیم، بدون اینکه تب انتخاب‌شده عوض بشه.
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta == 0:
            super().wheelEvent(event)
            return
        buttons = sorted(self.findChildren(QToolButton), key=lambda b: b.geometry().x())
        if len(buttons) < 2:
            super().wheelEvent(event)
            return
        scroll_backward, scroll_forward = buttons[0], buttons[-1]
        target_btn = scroll_backward if delta > 0 else scroll_forward
        if self.layoutDirection() == Qt.RightToLeft:
            target_btn = scroll_forward if delta > 0 else scroll_backward
        if target_btn.isEnabled():
            target_btn.click()
        event.accept()

    def configure(self, effective_font_size: int):
        self._tab_font_px = max(14, int(effective_font_size) + 2)
        self._tab_vpad = max(10, int(effective_font_size) - 3)
        self._tab_hpad = max(14, int(effective_font_size) + 1)
        self.setMinimumHeight(max(58, self._tab_font_px + 46))
        self.updateGeometry()

    def _metrics(self):
        font = QFont(self.font())
        font.setPixelSize(self._tab_font_px)
        font.setBold(True)
        return QFontMetrics(font)

    def tabSizeHint(self, index):
        text = self.tabText(index).strip()
        fm = self._metrics()
        width = fm.horizontalAdvance(text) + (self._tab_hpad * 2) + self._tab_extra
        height = max(super().tabSizeHint(index).height(), fm.height() + (self._tab_vpad * 2))
        return QSize(max(width, 72), height)
