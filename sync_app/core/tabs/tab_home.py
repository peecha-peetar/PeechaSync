"""تب شروع — راهنمای مسیر همگام‌سازی و دسترسی سریع."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.home_guide_data import HOME_FLOW_STEPS, HOME_INFO_CARDS

HOME_QUICK_ACTIONS: tuple[tuple[str, str], ...] = (
    ("📊 داشبورد", "داشبورد"),
    ("🔄 همگام‌سازی", "همگام‌سازی"),
    ("📂 دسته‌بندی‌ها", "دسته"),
    ("📦 محصولات", "محصول"),
    ("🎯 ویژگی‌ها", "ویژگی"),
    ("🎨 متغیرها", "متغیر"),
    ("👥 مشتریان", "مشتری"),
    ("🧾 سفارشات", "سفارش"),
    ("🧠 دستیار هوشمند", "دستیار هوشمند"),
    ("🖼️ مرکز رسانه", "رسانه"),
    ("✨ انتشار هوشمند", "انتشار"),
    ("🩺 سئو و سلامت سایت", "سئو"),
    ("📈 مدیریت بازاریابی", "بازاریاب"),
    ("🧭 مشاور پیچا", "مشاور"),
    ("⚖️ تطبیق", "تطبیق"),
    ("📄 لاگ‌ها", "لاگ"),
    ("⚡ همگام‌سازی خودکار", "خودکار"),
    ("⚙️ تنظیمات", "تنظیمات"),
    ("🔐 فعال‌سازی", "فعال"),
)

class HomeTab(QWidget):
    def __init__(self, navigate_callback=None):
        super().__init__()
        self.setObjectName("homeRoot")
        self.setLayoutDirection(Qt.RightToLeft)
        self.navigate_callback = navigate_callback
        self._is_compact = False
        self._is_extra_compact = False
        self._info_cards: list[QFrame] = []
        self._quick_buttons: list[QPushButton] = []
        self._build_ui()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("homeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content.setObjectName("homeContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 20)
        content_layout.setSpacing(14)

        hero_card = QFrame()
        hero_card.setObjectName("homeHeroCard")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(0)

        hero_header = QFrame()
        hero_header.setObjectName("homeHeroHeader")
        hero_header_layout = QVBoxLayout(hero_header)
        hero_header_layout.setContentsMargins(20, 18, 20, 16)
        hero_header_layout.setSpacing(6)

        hero_badge = QLabel("🏠 نقطه شروع پیچا")
        hero_badge.setObjectName("homeHeroBadge")
        hero_header_layout.addWidget(hero_badge)

        hero_title = QLabel("خوش آمدید — همگام‌سازی ERP ↔ ووکامرس")
        hero_title.setObjectName("homeHeroTitle")
        hero_title.setWordWrap(True)
        hero_header_layout.addWidget(hero_title)

        hero_subtitle = QLabel(
            "پیچا پنل یکپارچه برای همگام‌سازی دسته‌ها، محصولات، متغیرها، "
            "مشتریان و سفارشات بین ERP و فروشگاه آنلاین است."
        )
        hero_subtitle.setWordWrap(True)
        hero_subtitle.setObjectName("homeHeroSubtitle")
        hero_header_layout.addWidget(hero_subtitle)
        hero_layout.addWidget(hero_header)

        hero_body = QFrame()
        hero_body.setObjectName("homeHeroBody")
        hero_body_layout = QVBoxLayout(hero_body)
        hero_body_layout.setContentsMargins(20, 14, 20, 16)
        hero_body_layout.setSpacing(8)

        hero_tip = QLabel(
            "💡 اگر فروشگاه از قبل کالا دارد، قبل از همگام‌سازی حتماً تب «تطبیق» را انجام دهید "
            "تا قیمت و موجودی روی کالای درست اعمال شود."
        )
        hero_tip.setObjectName("homeHeroTip")
        hero_tip.setWordWrap(True)
        hero_body_layout.addWidget(hero_tip)

        hero_actions = QHBoxLayout()
        hero_actions.setSpacing(8)
        btn_start = self._make_quick_button("⚙️ شروع از تنظیمات", "تنظیمات")
        btn_recon = self._make_quick_button("⚖️ تطبیق ERP و سایت", "تطبیق")
        btn_dash = self._make_quick_button("📊 داشبورد گزارشات", "داشبورد")
        hero_actions.addWidget(btn_start)
        hero_actions.addWidget(btn_recon)
        hero_actions.addWidget(btn_dash)
        hero_body_layout.addLayout(hero_actions)
        hero_layout.addWidget(hero_body)
        content_layout.addWidget(hero_card)

        flow_card = QFrame()
        flow_card.setObjectName("homeFlowCard")
        flow_layout = QVBoxLayout(flow_card)
        flow_layout.setContentsMargins(16, 14, 16, 14)
        flow_layout.setSpacing(10)

        flow_title = QLabel("مسیر استاندارد همگام‌سازی")
        flow_title.setObjectName("homeSectionTitle")
        flow_layout.addWidget(flow_title)

        flow_hint = QLabel("مراحل را به ترتیب پیش ببرید — روی هر مرحله کلیک کنید تا به تب مربوط بروید.")
        flow_hint.setObjectName("homeSectionHint")
        flow_hint.setWordWrap(True)
        flow_layout.addWidget(flow_hint)

        for number, title, desc, keyword in HOME_FLOW_STEPS:
            flow_layout.addWidget(self._build_flow_step(number, title, desc, keyword))
        content_layout.addWidget(flow_card)

        self.info_grid = QGridLayout()
        self.info_grid.setHorizontalSpacing(10)
        self.info_grid.setVerticalSpacing(10)
        for title, text in HOME_INFO_CARDS:
            self._info_cards.append(self._build_info_card(title, text))
        self._arrange_info_cards(columns=2)
        content_layout.addLayout(self.info_grid)

        quick_card = QFrame()
        quick_card.setObjectName("homeQuickCard")
        quick_layout = QVBoxLayout(quick_card)
        quick_layout.setContentsMargins(16, 14, 16, 14)
        quick_layout.setSpacing(10)

        quick_title = QLabel("دسترسی سریع")
        quick_title.setObjectName("homeSectionTitle")
        quick_layout.addWidget(quick_title)

        self.quick_buttons_grid = QGridLayout()
        self.quick_buttons_grid.setHorizontalSpacing(8)
        self.quick_buttons_grid.setVerticalSpacing(8)
        from sync_app.core.product_mode import is_simple_only
        simple_only = is_simple_only()
        for label, keyword in HOME_QUICK_ACTIONS:
            if simple_only and keyword in ("ویژگی", "متغیر"):
                continue
            self._quick_buttons.append(self._make_quick_button(label, keyword))
        self._arrange_quick_buttons(columns=4)
        quick_layout.addLayout(self.quick_buttons_grid)
        content_layout.addWidget(quick_card)

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

    def _build_flow_step(self, number: str, title: str, desc: str, keyword: str) -> QFrame:
        row = QFrame()
        row.setObjectName("homeStepRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        num_lbl = QLabel(number)
        num_lbl.setObjectName("homeStepNumber")
        num_lbl.setAlignment(Qt.AlignCenter)
        num_lbl.setFixedSize(34, 34)
        layout.addWidget(num_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("homeStepTitle")
        text_col.addWidget(title_lbl)
        desc_lbl = QLabel(desc)
        desc_lbl.setObjectName("homeStepDesc")
        desc_lbl.setWordWrap(True)
        text_col.addWidget(desc_lbl)
        layout.addLayout(text_col, 1)

        go_btn = QPushButton("برو ←")
        go_btn.setObjectName("homeStepBtn")
        go_btn.setCursor(Qt.PointingHandCursor)
        go_btn.setFixedHeight(34)
        go_btn.clicked.connect(lambda: self._navigate(keyword))
        layout.addWidget(go_btn)
        return row

    def _build_info_card(self, title: str, text: str) -> QFrame:
        card = QFrame()
        card.setObjectName("homeInfoCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("homeCardTitle")
        layout.addWidget(title_lbl)

        text_lbl = QLabel(text)
        text_lbl.setWordWrap(True)
        text_lbl.setObjectName("homeCardText")
        layout.addWidget(text_lbl)
        return card

    def _make_quick_button(self, label: str, target_keyword: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setObjectName("homeQuickBtn")
        btn.setMinimumHeight(42)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._navigate(target_keyword))
        return btn

    def _navigate(self, keyword: str):
        if callable(self.navigate_callback):
            self.navigate_callback(keyword)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _arrange_info_cards(self, columns: int):
        self._clear_layout(self.info_grid)
        for index, card in enumerate(self._info_cards):
            self.info_grid.addWidget(card, index // columns, index % columns)

    def _arrange_quick_buttons(self, columns: int):
        self._clear_layout(self.quick_buttons_grid)
        for index, btn in enumerate(self._quick_buttons):
            self.quick_buttons_grid.addWidget(btn, index // columns, index % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()
        compact = width <= 980
        extra_compact = width <= 760
        if compact != self._is_compact:
            self._arrange_info_cards(1 if compact else 2)
            self._is_compact = compact
        if extra_compact != self._is_extra_compact:
            self._arrange_quick_buttons(2 if extra_compact else 4)
            self._is_extra_compact = extra_compact
