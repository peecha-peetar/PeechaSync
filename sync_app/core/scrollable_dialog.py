"""دیالوگِ قابلِ‌اسکرول — محتوایِ اصلی تویِ QScrollArea می‌ره و دکمه‌هایِ
ثابتِ پایین (تأیید/لغو) همیشه بیرونِ اسکرول و در دیدِ کاربر می‌مونن.

چرا: چند فرمِ معلق (مثلِ دیالوگِ سئو، AI Content Studio) محتوایِ
زیادی دارن؛ رویِ صفحه‌نمایش‌هایِ کوچیک/رزولوشنِ پایین، اگه همه‌چی از
جمله دکمه‌هایِ پایین تویِ یک QVBoxLayoutِ ساده باشن، ارتفاعِ کلِ دیالوگ
از صفحه بیشتر می‌شه و دکمه‌هایِ تأیید/لغو (که همیشه از همه چیز مهم‌ترن)
از دیدِ کاربر خارج می‌شن — انگار اصلاً وجود ندارن."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QScrollArea, QVBoxLayout, QWidget

_FOOTER_MARGINS = (14, 8, 14, 12)


def build_scrollable_dialog_body(dialog: QDialog) -> tuple[QVBoxLayout, QVBoxLayout]:
    """dialog رو با یه QScrollArea آماده می‌کنه.

    خروجی: (content_layout, outer_layout)
    - content_layout: محتوایِ معمولیِ دیالوگ (لیبل‌ها، کادرها، چک‌باکس‌ها) رو
      با addWidget/addLayoutِ همین لایه اضافه کنید — قابلِ‌اسکرول می‌شه.
    - outer_layout: فقط دکمه‌هایِ ثابتِ پایین (تأیید/لغو) رو با
      addWidget/addLayوutِ همین لایه اضافه کنید (بعد از این‌که همه‌ی
      محتوا به content_layout اضافه شد) — همیشه ثابت و قابل‌مشاهده می‌مونه.
    """
    outer_layout = QVBoxLayout(dialog)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    outer_layout.addWidget(scroll, 1)

    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(14, 14, 14, 14)
    scroll.setWidget(content)

    return content_layout, outer_layout


def add_footer_widget(outer_layout: QVBoxLayout, widget) -> None:
    """widget (معمولاً QDialogButtonBox) رو با یه حاشیه‌ی مناسب به
    outer_layout اضافه می‌کنه — چون outer_layout خودش بدونِ حاشیه‌ست
    (برایِ اینکه اسکرول‌اریا لبه‌به‌لبه بشه)."""
    footer = QWidget()
    footer_layout = QVBoxLayout(footer)
    footer_layout.setContentsMargins(*_FOOTER_MARGINS)
    footer_layout.addWidget(widget)
    outer_layout.addWidget(footer)
