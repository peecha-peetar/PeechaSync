"""تب تطبیق ERP ↔ ووکامرس برای فروشگاه‌های از قبل فعال."""

from __future__ import annotations

import threading

from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.message_boxes_fa import ask_yes_no
from sync_app.core.connectivity_guard import ensure_connectivity
from sync_app.core.live_site_backup_guard import confirm_live_site_backup
from sync_app.core.reconciliation_link_guard import confirm_reconciliation_link_risks
from sync_app.core.jalali_log_formatter import format_log_lines_jalali
from sync_app.core.log_panel_ui import LogActionRail, LogPanelController
from sync_app.core.compact_icon_action_bar import (
    CompactCaptionButton,
    build_compact_icon_action_bar,
)
from sync_app.core.reconciliation_service import (
    ENTITY_ATTRIBUTES,
    ENTITY_CATEGORIES,
    ENTITY_LABELS,
    ENTITY_PRODUCTS,
    ENTITY_VARIATIONS,
    ComparisonResult,
    ReconRow,
    auto_link_all,
    load_comparison,
    find_saved_link_pair,
    find_entity_counterpart,
    format_recon_load_error,
    mark_comparison_pairs_synced,
    recompute_comparison_stats,
    remove_link_pair,
    product_pair_in_map,
    save_link_pairs,
    suggest_auto_pairs,
    format_suggestion_tooltip,
)
from sync_app.core.rtl_item_delegate import RightAlignedItemDelegate
from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.sync_utils import app_path, clear_filtered_logs, log
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.user_guide_snippets import recon_hero_html_for_entity

RECON_LOG_TOKENS = (
    "نگاشت",
    "مقایسه",
    "reconciliation",
    "category_map",
    "product_woo_map",
    "تطبیق",
    "بارگذاری مقایسه",
    "link_manual",
    "auto_link",
)

COLOR_SYNCED = QColor("#dcfce7")
COLOR_UNSYNCED = QColor("#fef9c3")
COLOR_PENDING = QColor("#eef2ff")
COLOR_AUTO = QColor("#f5f3ff")
COLOR_AUTO_MATCHED = QColor("#dbeafe")
COLOR_ORPHAN = QColor("#fee2e2")
COLOR_SECTION = QColor("#f1f4fb")
COLOR_SELECTION_PAIRED = QColor("#4ade80")
COLOR_SELECTION_MANUAL = QColor("#60a5fa")

ITEM_ROLE_SECTION = Qt.UserRole + 1
SECTION_PENDING = "pending"
SECTION_AUTO = "auto"
SECTION_UNPAIRED = "unpaired"
SECTION_SYNCED = "synced"

# پیام کوتاه تب تطبیق — نوع «ویژگی»
ATTR_RECON_TITLE = "ویژگی‌ها"
ATTR_RECON_BODY = (
    "ویژگی با «نام یکسان» خودکار تطبیق می‌شود.\n"
    "همگام‌سازی با سایت: تب «ویژگی‌ها»."
)
ATTR_RECON_SYNCED_HEADER = "── ✅ نام یکسان — تطبیق خودکار (فقط مشاهده) ──"

RECON_COLUMNS_SPLITTER_KEY = "RECON_COLUMNS_SPLITTER_SIZES"
DEFAULT_RECON_COLUMNS_SPLITTER_SIZES = [380, 196, 380]
MIDDLE_COLUMN_WIDTH = 196
RECON_ONLY_UNSYNCED_KEY = "RECON_ONLY_UNSYNCED"
RECON_TOP_SPLITTER_KEY = "RECON_TOP_SPLITTER_SIZES"
DEFAULT_RECON_TOP_SPLITTER_SIZES = [320, 480]
RECON_TOP_MIN_HEIGHT = 0
RECON_BOTTOM_MIN_HEIGHT = 220
RECON_TOP_EXPANDED_DEFAULT = 320
RECON_COLUMN_MIN_WIDTH = 180
RECON_HERO_FONT_SIZE_KEY = "RECON_HERO_FONT_SIZE"
RECON_HERO_FONT_SIZES = (10, 11, 12, 13, 14, 16, 18, 20, 22, 24)
DEFAULT_RECON_HERO_FONT_SIZE = 12


class ReconciliationTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self._comparison: ComparisonResult | None = None
        self._comparison_unfiltered: ComparisonResult | None = None
        self._pending_pairs: list[tuple[ReconRow, ReconRow]] = []
        self._auto_suggested_pairs: list[tuple[ReconRow, ReconRow, str]] = []
        self._active_entity = ENTITY_PRODUCTS
        self._load_generation = 0
        self._loading = False
        self._initial_load_started = False
        self._columns_splitter_layout_applied = False
        self._top_splitter_layout_applied = False
        self._syncing_list_selection = False
        self._auto_highlight_keys: set[str] = set()
        self._selection_paired_keys: set[str] = set()
        self._selection_manual_keys: set[str] = set()
        self._load_cancel_event = threading.Event()
        self._status_search_open = False
        self._hero_font_size = DEFAULT_RECON_HERO_FONT_SIZE
        self._tables_fullscreen = False
        self._fullscreen_restore: dict = {}
        self._splitter_programmatic = False
        self._build_ui()
        self._active_entity = self._current_entity()
        self._update_entity_guide()
        self._restore_hero_display_prefs()

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._refresh_logs_if_visible)
        self.log_timer.start(2000)
        self.refresh_logs()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setDirection(QHBoxLayout.LeftToRight)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setLayoutDirection(Qt.LeftToRight)
        self.splitter.setHandleWidth(6)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LeftToRight)
        self.log_view.setMinimumWidth(260)
        self.splitter.addWidget(self.log_view)

        panel = QWidget()
        panel.setObjectName("reconRoot")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        self.log_actions = LogActionRail(clear_text="حذف لاگ‌های تب تطبیق", parent=self)

        self.status_bar = QFrame()
        self.status_bar.setObjectName("reconStatusBar")
        self.status_bar.setProperty("state", "ready")
        status_row = QHBoxLayout(self.status_bar)
        status_row.setContentsMargins(10, 6, 10, 6)
        status_row.setSpacing(8)

        self.status_message = QLabel(
            "✓ آماده — نوع داده را انتخاب و «بارگذاری مقایسه» را بزنید"
        )
        self.status_message.setObjectName("reconStatusMessage")
        self.status_message.setWordWrap(False)
        self.status_message.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        status_row.addWidget(self.status_message, 1)

        self.type_filter = QWidget()
        self.type_filter.setObjectName("reconStatusTypeFilter")
        type_row = QHBoxLayout(self.type_filter)
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(6)
        type_label = QLabel("نوع:")
        type_label.setProperty("role", "caption")
        type_label.setObjectName("reconStatusTypeLabel")
        self.entity_combo = QComboBox()
        self.entity_combo.setObjectName("reconStatusEntityCombo")
        self.entity_combo.setLayoutDirection(Qt.RightToLeft)
        self.entity_combo.setMinimumWidth(118)
        self.entity_combo.setMaximumWidth(150)
        from sync_app.core.product_mode import is_simple_only
        simple_only = is_simple_only()
        for key, label in (
            (ENTITY_CATEGORIES, "📂 دسته‌بندی"),
            (ENTITY_PRODUCTS, "📦 محصول"),
            (ENTITY_VARIATIONS, "🎨 متغیر"),
            (ENTITY_ATTRIBUTES, "🎯 ویژگی"),
        ):
            if simple_only and key in (ENTITY_VARIATIONS, ENTITY_ATTRIBUTES):
                continue
            self.entity_combo.addItem(label, key)
        for i in range(self.entity_combo.count()):
            if str(self.entity_combo.itemData(i)) == ENTITY_PRODUCTS:
                self.entity_combo.setCurrentIndex(i)
                break
        self.entity_combo.currentIndexChanged.connect(self._on_entity_changed)
        type_row.addWidget(type_label)
        type_row.addWidget(self.entity_combo)

        self.category_filter_label = QLabel("دسته‌بندی:")
        self.category_filter_label.setProperty("role", "caption")
        self.category_filter_combo = QComboBox()
        self.category_filter_combo.setObjectName("reconCategoryFilterCombo")
        self.category_filter_combo.setLayoutDirection(Qt.RightToLeft)
        self.category_filter_combo.setMinimumWidth(120)
        self.category_filter_combo.setMaximumWidth(170)
        self.category_filter_combo.addItem("همه دسته‌بندی‌ها", "")
        self.category_filter_combo.setToolTip(
            "فقط محصولات/متغیرهای همین دسته‌بندی رو تو لیست پایین نشون بده — "
            "این فقط روی نمایشه، چیزی رو حذف/غیرفعال نمی‌کنه."
        )
        self.category_filter_combo.currentIndexChanged.connect(self._on_category_filter_changed)
        type_row.addWidget(self.category_filter_label)
        type_row.addWidget(self.category_filter_combo)
        self._update_category_filter_visibility()

        status_row.addWidget(self.type_filter)

        self.only_unsynced_cb = QCheckBox("فقط غیرسینک")
        self.only_unsynced_cb.setObjectName("reconStatusOnlyUnsynced")
        self._restore_only_unsynced_filter()
        self.only_unsynced_cb.toggled.connect(self._on_only_unsynced_toggled)
        status_row.addWidget(self.only_unsynced_cb)

        self.search_toggle_btn = QPushButton("🔍")
        self.search_toggle_btn.setObjectName("reconStatusSearchToggle")
        self.search_toggle_btn.setToolTip("جستجو در لیست")
        self.search_toggle_btn.setFixedSize(36, 32)
        self.search_toggle_btn.setProperty("syncAction", False)
        self.search_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.search_toggle_btn.clicked.connect(self._open_status_search)
        status_row.addWidget(self.search_toggle_btn)

        self.tables_fullscreen_btn = QPushButton("⛶ تمام‌صفحه جداول")
        self.tables_fullscreen_btn.setObjectName("reconTablesFullscreenBtn")
        self.tables_fullscreen_btn.setToolTip(
            "لاگ و راهنما مخفی می‌شوند — جداول تطبیق بیشترین فضا را می‌گیرند"
        )
        self.tables_fullscreen_btn.setProperty("syncAction", False)
        self.tables_fullscreen_btn.setCursor(Qt.PointingHandCursor)
        self.tables_fullscreen_btn.setMinimumHeight(32)
        self.tables_fullscreen_btn.clicked.connect(self._toggle_tables_fullscreen)
        status_row.addWidget(self.tables_fullscreen_btn)

        self.search_expanded = QWidget()
        self.search_expanded.setObjectName("reconStatusSearchExpanded")
        self.search_expanded.setVisible(False)
        search_row = QHBoxLayout(self.search_expanded)
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(6)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("reconStatusSearchInput")
        self.search_input.setPlaceholderText("جستجو در ERP و فروشگاه...")
        self.search_input.setLayoutDirection(Qt.RightToLeft)
        self.search_input.textChanged.connect(self._refresh_lists)
        self.search_close_btn = QPushButton("×")
        self.search_close_btn.setObjectName("reconStatusSearchClose")
        self.search_close_btn.setToolTip("بستن جستجو")
        self.search_close_btn.setFixedSize(36, 32)
        self.search_close_btn.setProperty("syncAction", False)
        self.search_close_btn.setCursor(Qt.PointingHandCursor)
        self.search_close_btn.clicked.connect(self._close_status_search)
        search_row.addWidget(self.search_input, 1)
        search_row.addWidget(self.search_close_btn)
        status_row.addWidget(self.search_expanded, 2)

        layout.addWidget(self.status_bar)
        self._set_status("ready", self.status_message.text())

        self.load_progress = QProgressBar()
        self.load_progress.setObjectName("siteFetchProgress")
        self.load_progress.setRange(0, 0)
        self.load_progress.setTextVisible(False)
        self.load_progress.setFixedHeight(8)
        self.load_progress.setVisible(False)
        layout.addWidget(self.load_progress)

        self.hero_card = QFrame()
        self.hero_card.setObjectName("reconHeroCard")
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        hero_layout.setSpacing(0)

        hero_header = QFrame()
        hero_header.setObjectName("reconHeroHeader")
        self.hero_header = hero_header
        header_layout = QHBoxLayout(hero_header)
        header_layout.setContentsMargins(18, 12, 18, 10)
        header_layout.setSpacing(14)

        self.hero_title = QLabel(
            "⚖️ تطبیق موجودی نرم‌افزار با فروشگاه — برای مشتریانی که سایت از قبل فعال دارند"
        )
        self.hero_title.setWordWrap(True)
        self.hero_title.setObjectName("reconHeroTitle")
        header_layout.addWidget(self.hero_title, 1)
        hero_layout.addWidget(hero_header)

        hero_content = QFrame()
        hero_content.setObjectName("reconHeroContent")
        self.hero_content = hero_content
        content_layout = QVBoxLayout(hero_content)
        content_layout.setContentsMargins(18, 4, 18, 16)
        content_layout.setSpacing(0)

        self.hero_body = QLabel(recon_hero_html_for_entity(ENTITY_PRODUCTS))
        self.hero_body.setObjectName("reconHeroBody")
        self.hero_body.setWordWrap(True)
        self.hero_body.setTextFormat(Qt.RichText)
        self.hero_body.setOpenExternalLinks(False)
        content_layout.addWidget(self.hero_body)
        hero_layout.addWidget(hero_content)

        self._build_hero_font_float()
        self.hero_card.installEventFilter(self)

        self.top_scroll = QScrollArea()
        self.top_scroll.setObjectName("reconTopScroll")
        self.top_scroll.setWidgetResizable(True)
        self.top_scroll.setFrameShape(QFrame.NoFrame)
        self.top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.top_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.top_scroll.setMinimumHeight(RECON_TOP_MIN_HEIGHT)

        top_inner = QWidget()
        top_inner.setObjectName("reconTopPanel")
        top_inner.setMinimumHeight(0)
        top_layout = QVBoxLayout(top_inner)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        top_layout.addWidget(self.hero_card)
        self.top_scroll.setWidget(top_inner)

        self.stats_label = QLabel("آمار: —")
        self.stats_label.setObjectName("reconStatsLabel")

        self.pair_count_label = QLabel("آماده ثبت: ۰ | پیشنهاد بنفش: ۰")
        self.pair_count_label.setObjectName("reconPairCountBar")

        bottom_panel = QWidget()
        bottom_panel.setObjectName("reconBottomPanel")
        self.bottom_panel = bottom_panel
        bottom_layout = QVBoxLayout(bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)

        bottom_layout.addWidget(self.stats_label)
        bottom_layout.addWidget(self.pair_count_label)

        self.columns_splitter = QSplitter(Qt.Horizontal)
        self.columns_splitter.setLayoutDirection(Qt.LeftToRight)
        self.columns_splitter.setHandleWidth(6)
        self.columns_splitter.setChildrenCollapsible(False)

        erp_card = QFrame()
        erp_card.setObjectName("reconColumnCard")
        erp_box = QVBoxLayout(erp_card)
        erp_box.setContentsMargins(8, 8, 8, 8)
        erp_box.setSpacing(6)
        erp_title = QLabel("🗄️ نرم‌افزار (ERP)")
        erp_title.setProperty("role", "section-title")
        erp_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        erp_box.addWidget(erp_title)
        self.erp_list = QListWidget()
        self.erp_list.setObjectName("reconList")
        self.erp_list.setLayoutDirection(Qt.RightToLeft)
        self.erp_list.setMinimumHeight(160)
        self.erp_list.setSelectionMode(QListWidget.SingleSelection)
        self.erp_list.setItemDelegate(RightAlignedItemDelegate(self.erp_list))
        self.erp_list.itemSelectionChanged.connect(self._on_list_selection_changed)
        erp_box.addWidget(self.erp_list)
        self.columns_splitter.addWidget(erp_card)

        middle_panel = QFrame()
        middle_panel.setObjectName("reconMiddlePanel")
        middle_panel_layout = QVBoxLayout(middle_panel)
        middle_panel_layout.setContentsMargins(0, 0, 0, 0)
        middle_panel_layout.setSpacing(0)

        middle_scroll = QScrollArea()
        middle_scroll.setObjectName("reconMiddleScroll")
        middle_scroll.setWidgetResizable(True)
        middle_scroll.setFrameShape(QFrame.NoFrame)
        middle_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        middle_inner = QWidget()
        middle_inner.setObjectName("reconMiddleInner")
        middle_col = QVBoxLayout(middle_inner)
        middle_col.setContentsMargins(6, 8, 6, 8)
        middle_col.setSpacing(6)

        flow_hint = QLabel("ERP  ←  عملیات  →  Woo")
        flow_hint.setObjectName("reconMiddleFlowHint")
        flow_hint.setAlignment(Qt.AlignCenter)
        middle_col.addWidget(flow_hint)

        auto_group, auto_layout = self._make_middle_group(
            "۱",
            "پیشنهاد سیستم",
            "جستجوی خودکار بر اساس کد یا نام محصول",
            group_role="auto",
            icon="⚡",
        )
        self.auto_suggest_btn = self._make_middle_button(
            "🔍  یافتن پیشنهادها",
            self.run_auto_suggest,
            "لیست بنفش: پیشنهادهای سیستم — بعداً «پذیرش» یا «رد» کنید",
            role="action",
        )
        auto_layout.addWidget(self.auto_suggest_btn)

        review_box = QFrame()
        review_box.setObjectName("reconMiddleReviewBox")
        review_layout = QVBoxLayout(review_box)
        review_layout.setContentsMargins(8, 8, 8, 8)
        review_layout.setSpacing(5)

        review_hint = QLabel("بررسی پیشنهادهای بنفش:")
        review_hint.setObjectName("reconMiddleReviewHint")
        review_hint.setAlignment(Qt.AlignCenter)
        review_layout.addWidget(review_hint)

        self.confirm_auto_btn = self._make_middle_button(
            "✓  پذیرش انتخاب",
            self.confirm_selected_auto_pair,
            "پیشنهاد انتخاب‌شده → آماده ثبت (آبی)",
            role="secondary",
        )
        self.confirm_auto_btn.setEnabled(False)
        review_layout.addWidget(self.confirm_auto_btn)

        self.confirm_all_auto_btn = self._make_middle_button(
            "✓✓  پذیرش همه",
            self.confirm_all_auto_pairs,
            "همه پیشنهادهای بنفش → آماده ثبت",
            role="secondary",
        )
        self.confirm_all_auto_btn.setEnabled(False)
        review_layout.addWidget(self.confirm_all_auto_btn)

        self.reject_auto_btn = self._make_middle_button(
            "✗  رد پیشنهاد",
            self.reject_selected_auto_pair,
            "پیشنهاد انتخاب‌شده را حذف کن (بدون ثبت)",
            role="danger",
        )
        self.reject_auto_btn.setEnabled(False)
        review_layout.addWidget(self.reject_auto_btn)
        auto_layout.addWidget(review_box)
        middle_col.addWidget(auto_group)
        middle_col.addWidget(self._make_middle_or_divider())

        manual_group, manual_layout = self._make_middle_group(
            "۲",
            "اتصال دستی",
            "در هر دو ستون یک ردیف زرد انتخاب کنید — "
            "آبی = آماده جفت دستی | سبز = جفت موجود",
            group_role="manual",
            icon="✋",
        )
        self.pair_btn = self._make_middle_button(
            "🔗  اتصال\nERP ↔ Woo",
            self.pair_selected_rows,
            "دو ردیف انتخاب‌شده را به هم وصل کن → آماده ثبت",
            role="primary",
        )
        self.pair_btn.setEnabled(False)
        manual_layout.addWidget(self.pair_btn)

        self.unpair_btn = self._make_middle_button(
            "⊘  لغو اتصال",
            self.unpair_selected_row,
            "جفت آبی (آماده ثبت) یا سبز (ثبت‌شده) را لغو کن",
            role="danger",
        )
        self.unpair_btn.setEnabled(False)
        manual_layout.addWidget(self.unpair_btn)
        middle_col.addWidget(manual_group)
        middle_scroll.setWidget(middle_inner)
        middle_panel_layout.addWidget(middle_scroll)
        self.columns_splitter.addWidget(middle_panel)

        wc_card = QFrame()
        wc_card.setObjectName("reconColumnCard")
        wc_box = QVBoxLayout(wc_card)
        wc_box.setContentsMargins(8, 8, 8, 8)
        wc_box.setSpacing(6)
        wc_title = QLabel("🌐 فروشگاه (سایت)")
        wc_title.setProperty("role", "section-title")
        wc_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        wc_box.addWidget(wc_title)

        wc_export_row = QHBoxLayout()
        wc_export_row.setSpacing(6)
        self.export_products_btn = QPushButton("📊 خروجی اکسل محصولات")
        self.export_products_btn.setToolTip("خروجی اکسل از محصولاتی که همین الان در ستون فروشگاه لود شده‌اند")
        self.export_products_btn.clicked.connect(self._export_wc_products_excel)
        wc_export_row.addWidget(self.export_products_btn)
        self.export_variations_btn = QPushButton("📊 خروجی اکسل متغیرها")
        self.export_variations_btn.setToolTip("خروجی اکسل جدا فقط برای متغیرهای محصولات (رنگ/سایز و...)")
        self.export_variations_btn.clicked.connect(self._export_wc_variations_excel)
        wc_export_row.addWidget(self.export_variations_btn)
        wc_export_row.addStretch()
        wc_box.addLayout(wc_export_row)

        self.wc_list = QListWidget()
        self.wc_list.setObjectName("reconList")
        self.wc_list.setLayoutDirection(Qt.RightToLeft)
        self.wc_list.setMinimumHeight(160)
        self.wc_list.setSelectionMode(QListWidget.SingleSelection)
        self.wc_list.setItemDelegate(RightAlignedItemDelegate(self.wc_list))
        self.wc_list.itemSelectionChanged.connect(self._on_list_selection_changed)
        self.wc_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.wc_list.customContextMenuRequested.connect(self._show_wc_list_context_menu)
        wc_box.addWidget(self.wc_list)
        self.columns_splitter.addWidget(wc_card)
        self.columns_splitter.setStretchFactor(0, 1)
        self.columns_splitter.setStretchFactor(1, 0)
        self.columns_splitter.setStretchFactor(2, 1)
        self._restore_columns_splitter_sizes()
        self.columns_splitter.splitterMoved.connect(self._schedule_save_columns_splitter_sizes)

        bottom_layout.addWidget(self.columns_splitter, 1)

        self.top_splitter = QSplitter(Qt.Vertical)
        self.top_splitter.setObjectName("reconTopSplitter")
        self.top_splitter.setLayoutDirection(Qt.LeftToRight)
        self.top_splitter.setHandleWidth(8)
        self.top_splitter.setChildrenCollapsible(True)
        self.top_splitter.addWidget(self.top_scroll)
        self.top_splitter.addWidget(bottom_panel)
        self.top_splitter.setCollapsible(0, True)
        self.top_splitter.setCollapsible(1, False)
        self.top_splitter.setStretchFactor(0, 0)
        self.top_splitter.setStretchFactor(1, 1)
        self.top_splitter.splitterMoved.connect(self._on_top_splitter_moved)
        self.top_splitter.splitterMoved.connect(self._schedule_save_top_splitter_sizes)
        self.top_scroll.viewport().installEventFilter(self)
        self.top_splitter.installEventFilter(self)

        layout.addWidget(self.top_splitter, 1)

        self.refresh_btn = CompactCaptionButton("🔄 بارگذاری مقایسه")
        self.refresh_btn.setObjectName("reconRefreshBtn")
        self.refresh_btn.setProperty("reconLoadMode", "load")
        self.refresh_btn.setToolTip(
            "اولین بار: دریافت لیست از ERP و فروشگاه\n"
            "بارگذاری مجدد: فقط در صورت نیاز — قبل از آن تأیید می‌گیرد"
        )
        self.refresh_btn.clicked.connect(self._on_load_btn_clicked)

        self.auto_btn = CompactCaptionButton("⚡ ثبت سریع کد یکسان")
        self.auto_btn.setObjectName("reconQuickSkuBtn")
        self.auto_btn.setProperty("syncAction", False)
        self.auto_btn.setToolTip(
            "بدون پیش‌نمایش، همه جفت‌های با کد محصول یکسان را مستقیم در فایل تطبیق ذخیره می‌کند.\n"
            "برای بررسی قبل از ثبت، از «یافتن پیشنهادها» در ستون وسط استفاده کنید."
        )
        self.auto_btn.clicked.connect(self.run_auto_link)

        self.commit_btn = CompactCaptionButton("💾 ثبت نهایی تطبیق")
        self.commit_btn.setObjectName("reconCommitBtn")
        self.commit_btn.setProperty("syncAction", False)
        self.commit_btn.setEnabled(False)
        self.commit_btn.clicked.connect(self.run_final_commit)

        self.bottom_btn_bar = build_compact_icon_action_bar(
            [self.refresh_btn, self.auto_btn, self.commit_btn],
            parent=panel,
        )
        layout.addWidget(self.bottom_btn_bar)

        self.splitter.addWidget(panel)
        self.log_panel_controller = LogPanelController(
            splitter=self.splitter,
            button=self.log_actions.toggle_button,
            open_size=360,
            duration_ms=160,
            log_widget=self.log_view,
            parent=self,
        )
        self.log_actions.bind_toggle(self.log_panel_controller.toggle)
        self.log_actions.bind_clear(self.clear_tab_logs)
        self.log_panel_controller.collapse_initial()  # پیش‌فرض: لاگ مخفی — با دکمه‌ی کناری نمایش داده می‌شود

        root.addWidget(self.splitter, 1)
        root.addWidget(self.log_actions)

    def _toggle_tables_fullscreen(self) -> None:
        if self._tables_fullscreen:
            self._exit_tables_fullscreen()
        else:
            self._enter_tables_fullscreen()

    def _enter_tables_fullscreen(self) -> None:
        if self._tables_fullscreen:
            return
        log_open, log_left = False, 0
        if self.log_panel_controller is not None:
            log_open, log_left = self.log_panel_controller._read_open_state()
        self._fullscreen_restore = {
            "log_open": log_open,
            "log_left": log_left,
            "main_sizes": list(self.splitter.sizes()),
            "top_sizes": list(self.top_splitter.sizes()),
            "log_actions_visible": self.log_actions.isVisible(),
            "list_min_height": self.erp_list.minimumHeight(),
            "fullscreen_btn_text": self.tables_fullscreen_btn.text(),
            "fullscreen_btn_tooltip": self.tables_fullscreen_btn.toolTip(),
        }
        self._tables_fullscreen = True
        self.tables_fullscreen_btn.setText("↙ خروج از تمام‌صفحه")
        self.tables_fullscreen_btn.setToolTip("بازگشت به حالت عادی (نمایش لاگ و راهنما)")
        self.tables_fullscreen_btn.setProperty("active", True)
        self.tables_fullscreen_btn.style().unpolish(self.tables_fullscreen_btn)
        self.tables_fullscreen_btn.style().polish(self.tables_fullscreen_btn)

        if self.log_panel_controller is not None:
            self.log_panel_controller.collapse_initial()
        main_sizes = self.splitter.sizes() or [0, 0]
        total = max(sum(main_sizes), 1)
        self.splitter.setSizes([0, total])

        self.log_actions.setVisible(False)
        self.load_progress.setVisible(False)
        self.top_scroll.setVisible(False)
        self.stats_label.setVisible(False)
        self.pair_count_label.setVisible(False)

        bottom_total = max(self.top_splitter.height(), 480)
        self._splitter_programmatic = True
        try:
            self.top_splitter.setSizes([0, bottom_total])
        finally:
            self._splitter_programmatic = False

        list_min = max(360, self.bottom_panel.height() - 80)
        self.erp_list.setMinimumHeight(list_min)
        self.wc_list.setMinimumHeight(list_min)

    def _exit_tables_fullscreen(self) -> None:
        if not self._tables_fullscreen:
            return
        self._tables_fullscreen = False
        saved = self._fullscreen_restore or {}

        self.tables_fullscreen_btn.setText(saved.get("fullscreen_btn_text", "⛶ تمام‌صفحه جداول"))
        self.tables_fullscreen_btn.setToolTip(
            saved.get(
                "fullscreen_btn_tooltip",
                "لاگ و راهنما مخفی می‌شوند — جداول تطبیق بیشترین فضا را می‌گیرند",
            )
        )
        self.tables_fullscreen_btn.setProperty("active", False)
        self.tables_fullscreen_btn.style().unpolish(self.tables_fullscreen_btn)
        self.tables_fullscreen_btn.style().polish(self.tables_fullscreen_btn)
        self.log_actions.setVisible(saved.get("log_actions_visible", True))
        self.top_scroll.setVisible(True)
        self.stats_label.setVisible(True)
        self.pair_count_label.setVisible(True)

        list_min = int(saved.get("list_min_height", 280))
        self.erp_list.setMinimumHeight(list_min)
        self.wc_list.setMinimumHeight(list_min)

        main_sizes = saved.get("main_sizes")
        if isinstance(main_sizes, list) and len(main_sizes) >= 2:
            self.splitter.setSizes(main_sizes)
        elif saved.get("log_open") and self.log_panel_controller is not None:
            self.log_panel_controller.expand_initial()
        else:
            total = max(sum(self.splitter.sizes()), 1)
            self.splitter.setSizes([0, total])

        top_sizes = saved.get("top_sizes")
        if isinstance(top_sizes, list) and len(top_sizes) >= 1:
            self._apply_top_splitter_sizes(int(top_sizes[0]))
        else:
            self._restore_top_splitter_sizes()

        if self.log_panel_controller is not None:
            if saved.get("log_open"):
                width = int(saved.get("log_left") or self.log_panel_controller._saved_open_width)
                self.log_panel_controller._apply_left_width(width, sync_button=True)
            else:
                self.log_panel_controller.collapse_initial()

        self._fullscreen_restore = {}

    def _make_middle_group(
        self,
        step: str,
        title: str,
        hint: str,
        *,
        group_role: str = "auto",
        icon: str = "",
    ) -> tuple[QFrame, QVBoxLayout]:
        group = QFrame()
        object_name = (
            "reconMiddleGroupManual" if group_role == "manual" else "reconMiddleGroupAuto"
        )
        group.setObjectName(object_name)
        group.setProperty("reconGroupRole", group_role)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_bar = QFrame()
        header_bar.setObjectName("reconMiddleGroupHeader")
        header_bar.setProperty("reconGroupRole", group_role)
        header_row = QHBoxLayout(header_bar)
        header_row.setContentsMargins(8, 6, 8, 6)
        header_row.setSpacing(8)

        badge = QLabel(step)
        badge.setObjectName("reconMiddleStepBadge")
        badge.setProperty("reconGroupRole", group_role)
        badge.setAlignment(Qt.AlignCenter)
        header_row.addWidget(badge)

        title_text = f"{icon}  {title}".strip() if icon else title
        header = QLabel(title_text)
        header.setObjectName("reconMiddleGroupTitle")
        header.setProperty("reconGroupRole", group_role)
        header.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_row.addWidget(header, 1)
        layout.addWidget(header_bar)

        sub = QLabel(hint)
        sub.setObjectName("reconMiddleGroupHint")
        sub.setProperty("reconGroupRole", group_role)
        sub.setWordWrap(True)
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(sub)
        return group, layout

    def _make_middle_or_divider(self) -> QFrame:
        wrap = QFrame()
        wrap.setObjectName("reconMiddleOrDivider")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(4, 6, 4, 6)
        row.setSpacing(6)

        line_left = QFrame()
        line_left.setObjectName("reconMiddleOrLine")
        line_left.setFrameShape(QFrame.HLine)
        line_left.setFrameShadow(QFrame.Sunken)
        row.addWidget(line_left, 1)

        label = QLabel("یا")
        label.setObjectName("reconMiddleOrLabel")
        label.setAlignment(Qt.AlignCenter)
        row.addWidget(label)

        line_right = QFrame()
        line_right.setObjectName("reconMiddleOrLine")
        line_right.setFrameShape(QFrame.HLine)
        line_right.setFrameShadow(QFrame.Sunken)
        row.addWidget(line_right, 1)
        return wrap

    def _make_middle_divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("reconMiddleDivider")
        line.setFixedHeight(8)
        return line

    def _make_middle_button(
        self,
        text: str,
        handler,
        tooltip: str = "",
        *,
        accent: bool = False,
        role: str = "",
    ) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("reconMiddleBtn")
        btn.setLayoutDirection(Qt.RightToLeft)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_h = 44 if "\n" in text else 36
        btn.setFixedHeight(btn_h)
        btn.setToolTip(tooltip)
        btn.setProperty("syncAction", False)
        if not role:
            role = "primary" if accent else "secondary"
        btn.setProperty("reconBtnRole", role)
        btn.clicked.connect(handler)
        return btn

    def _make_hero_float_button(
        self,
        object_name: str,
        text: str,
        tooltip: str,
        handler,
        *,
        close: bool = False,
    ) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName(object_name)
        btn.setProperty("reconHeroFloatBtn", True)
        btn.setProperty("reconHeroCloseBtn", close)
        btn.setProperty("syncAction", False)
        btn.setFixedSize(34, 34)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(handler)
        return btn

    def _build_hero_font_float(self):
        self.hero_font_float = QFrame(self.hero_card)
        self.hero_font_float.setObjectName("reconHeroFontFloat")
        self.hero_font_float.setAttribute(Qt.WA_StyledBackground, True)
        float_layout = QVBoxLayout(self.hero_font_float)
        float_layout.setContentsMargins(4, 4, 4, 4)
        float_layout.setSpacing(2)

        self.hero_guide_close = self._make_hero_float_button(
            "reconHeroGuideClose",
            "✕",
            "بستن راهنما (ارتفاع صفر)",
            self._collapse_hero_guide,
            close=True,
        )
        self.hero_font_plus = self._make_hero_float_button(
            "reconHeroFontPlus",
            "+",
            "بزرگ‌تر کردن متن راهنما",
            lambda: self._step_hero_font_size(1),
        )
        self.hero_font_minus = self._make_hero_float_button(
            "reconHeroFontMinus",
            "−",
            "کوچک‌تر کردن متن راهنما",
            lambda: self._step_hero_font_size(-1),
        )
        float_layout.addWidget(self.hero_guide_close)
        float_layout.addWidget(self.hero_font_plus)
        float_layout.addWidget(self.hero_font_minus)

        shadow = QGraphicsDropShadowEffect(self.hero_font_float)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 23, 42, 70))
        self.hero_font_float.setGraphicsEffect(shadow)
        QTimer.singleShot(0, self._position_hero_font_float)

    def _hero_float_bounds(self) -> tuple[int, int, int] | None:
        if not hasattr(self, "hero_font_float"):
            return None
        margin = 8
        header_h = self.hero_header.height()
        y = header_h + margin
        viewport = self.top_scroll.viewport() if hasattr(self, "top_scroll") else None
        viewport_h = viewport.height() if viewport is not None else self.hero_card.height()
        card_h = self.hero_card.height()
        visible_bottom = min(viewport_h, card_h) - margin
        available = visible_bottom - y
        if available <= 0:
            return None
        return y, visible_bottom, available

    def _position_hero_font_float(self):
        if not hasattr(self, "hero_font_float"):
            return
        if hasattr(self, "top_splitter"):
            sizes = self.top_splitter.sizes()
            if sizes and int(sizes[0]) <= 4:
                self.hero_font_float.hide()
                return

        bounds = self._hero_float_bounds()
        if bounds is None:
            self.hero_font_float.hide()
            return

        y, visible_bottom, available = bounds
        margin = 8
        x = 10

        self.hero_guide_close.setVisible(True)
        self.hero_font_plus.setVisible(True)
        self.hero_font_minus.setVisible(True)
        self.hero_font_float.adjustSize()
        full_h = self.hero_font_float.sizeHint().height()
        float_w = self.hero_font_float.sizeHint().width()

        if full_h <= available and y + full_h <= visible_bottom:
            use_h = full_h
        else:
            self.hero_font_plus.setVisible(False)
            self.hero_font_minus.setVisible(False)
            self.hero_font_float.adjustSize()
            compact_h = self.hero_font_float.sizeHint().height()
            if compact_h <= available and y + compact_h <= visible_bottom:
                use_h = compact_h
            else:
                self.hero_font_float.hide()
                return

        self.hero_font_float.show()
        self.hero_font_float.setGeometry(x, y, float_w, use_h)
        self.hero_font_float.raise_()

    def eventFilter(self, obj, event):
        watched = (
            getattr(self, "hero_card", None),
            getattr(self, "top_scroll", None) and self.top_scroll.viewport(),
            getattr(self, "top_splitter", None),
        )
        if obj in watched and event.type() in (QEvent.Resize, QEvent.Show):
            self._position_hero_font_float()
        return super().eventFilter(obj, event)

    def _snap_hero_font_size(self, size: int) -> int:
        try:
            target = int(size)
        except (TypeError, ValueError):
            target = DEFAULT_RECON_HERO_FONT_SIZE
        return min(RECON_HERO_FONT_SIZES, key=lambda s: abs(s - target))

    def _hero_font_index(self) -> int:
        try:
            return RECON_HERO_FONT_SIZES.index(self._hero_font_size)
        except ValueError:
            return RECON_HERO_FONT_SIZES.index(DEFAULT_RECON_HERO_FONT_SIZE)

    def _step_hero_font_size(self, delta: int):
        idx = self._hero_font_index()
        new_idx = max(0, min(len(RECON_HERO_FONT_SIZES) - 1, idx + delta))
        self._apply_hero_font_size(RECON_HERO_FONT_SIZES[new_idx])

    def _restore_hero_display_prefs(self):
        cfg = self.config or load_secure_config(None) or {}
        try:
            font_size = int(cfg.get(RECON_HERO_FONT_SIZE_KEY, DEFAULT_RECON_HERO_FONT_SIZE))
        except (TypeError, ValueError):
            font_size = DEFAULT_RECON_HERO_FONT_SIZE
        self._apply_hero_font_size(font_size, save=False)

    def _apply_hero_font_size(self, size: int, *, save: bool = True):
        size = self._snap_hero_font_size(size)
        self._hero_font_size = size
        title_px = size + 2
        body_px = size
        self.hero_title.setStyleSheet(
            f"color: #1a2785; font-size: {title_px}px; font-weight: 800; background: transparent;"
        )
        self.hero_body.setStyleSheet(
            f"color: #334155; font-size: {body_px}px; line-height: 1.55; background: transparent;"
        )
        tip = f"اندازه متن راهنما: {size} پیکسل"
        self.hero_font_plus.setToolTip(tip)
        self.hero_font_minus.setToolTip(tip)
        self.hero_font_plus.setEnabled(self._hero_font_index() < len(RECON_HERO_FONT_SIZES) - 1)
        self.hero_font_minus.setEnabled(self._hero_font_index() > 0)
        if save:
            self._save_hero_font_size()

    def _save_hero_font_size(self):
        cfg = load_secure_config(None) or {}
        cfg[RECON_HERO_FONT_SIZE_KEY] = int(self._hero_font_size)
        save_secure_config(cfg)
        self.config = cfg

    def _collapse_hero_guide(self):
        sizes = self.top_splitter.sizes()
        bottom_h = max(int(sizes[1]) if sizes else RECON_BOTTOM_MIN_HEIGHT, RECON_BOTTOM_MIN_HEIGHT)
        self._splitter_programmatic = True
        try:
            self.top_splitter.setSizes([RECON_TOP_MIN_HEIGHT, bottom_h])
        finally:
            self._splitter_programmatic = False
        self._sync_top_splitter_handle_hint()
        self._schedule_save_top_splitter_sizes()
        self._position_hero_font_float()

    def ensure_tab_data_loaded(self):
        if self._initial_load_started:
            return
        self._initial_load_started = True
        self.refresh_logs()

    def _refresh_logs_if_visible(self):
        if self.isVisible():
            self.refresh_logs()

    def _columns_splitter_usable_width(self) -> int:
        total = self.columns_splitter.width()
        if total <= 0:
            total = sum(DEFAULT_RECON_COLUMNS_SPLITTER_SIZES)
        handles = self.columns_splitter.handleWidth() * max(self.columns_splitter.count() - 1, 0)
        return max(total - MIDDLE_COLUMN_WIDTH - handles, RECON_COLUMN_MIN_WIDTH * 2)

    def _apply_columns_splitter_sizes(self, erp_w: int, wc_w: int) -> None:
        usable = self._columns_splitter_usable_width()
        min_w = RECON_COLUMN_MIN_WIDTH
        erp_w = max(min_w, int(erp_w))
        wc_w = max(min_w, int(wc_w))
        pair_total = erp_w + wc_w
        if pair_total > usable and pair_total > 0:
            erp_w = max(min_w, int(erp_w * usable / pair_total))
            wc_w = max(min_w, usable - erp_w)
        elif pair_total < usable:
            extra = usable - pair_total
            erp_w += extra // 2
            wc_w += extra - (extra // 2)
        self._splitter_programmatic = True
        try:
            self.columns_splitter.setSizes([erp_w, MIDDLE_COLUMN_WIDTH, wc_w])
        finally:
            self._splitter_programmatic = False

    def _restore_columns_splitter_sizes(self):
        cfg = self.config or load_secure_config(None) or {}
        raw = cfg.get(RECON_COLUMNS_SPLITTER_KEY)
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            try:
                erp_w = max(int(raw[0]), RECON_COLUMN_MIN_WIDTH)
                wc_w = max(int(raw[1]), RECON_COLUMN_MIN_WIDTH)
                self._apply_columns_splitter_sizes(erp_w, wc_w)
                return
            except (TypeError, ValueError):
                pass
        erp_w, _, wc_w = DEFAULT_RECON_COLUMNS_SPLITTER_SIZES
        self._apply_columns_splitter_sizes(erp_w, wc_w)

    def _restore_only_unsynced_filter(self):
        cfg = self.config or load_secure_config(None) or {}
        checked = bool(cfg.get(RECON_ONLY_UNSYNCED_KEY, False))
        self.only_unsynced_cb.blockSignals(True)
        self.only_unsynced_cb.setChecked(checked)
        self.only_unsynced_cb.blockSignals(False)

    def _on_only_unsynced_toggled(self, *_args):
        self._refresh_lists()
        self._schedule_save_only_unsynced_filter()

    def _schedule_save_only_unsynced_filter(self):
        timer = getattr(self, "_only_unsynced_save_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(self._save_only_unsynced_filter)
            self._only_unsynced_save_timer = timer
        timer.start()

    def _save_only_unsynced_filter(self):
        cfg = load_secure_config(None) or {}
        cfg[RECON_ONLY_UNSYNCED_KEY] = bool(self.only_unsynced_cb.isChecked())
        save_secure_config(cfg)
        self.config = cfg

    def _schedule_save_columns_splitter_sizes(self, *_args):
        timer = getattr(self, "_columns_splitter_save_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._save_columns_splitter_sizes)
            self._columns_splitter_save_timer = timer
        timer.start()

    def _save_columns_splitter_sizes(self):
        if self._splitter_programmatic:
            return
        sizes = self.columns_splitter.sizes()
        if len(sizes) < 3 or sum(sizes) <= 0:
            return
        cfg = load_secure_config(None) or {}
        cfg[RECON_COLUMNS_SPLITTER_KEY] = [int(sizes[0]), int(sizes[2])]
        save_secure_config(cfg)
        self.config = cfg

    def _top_splitter_usable_height(self) -> int:
        total = self.top_splitter.height()
        if total <= 0:
            total = sum(DEFAULT_RECON_TOP_SPLITTER_SIZES)
        handle = self.top_splitter.handleWidth()
        return max(total - handle, RECON_BOTTOM_MIN_HEIGHT)

    def _apply_top_splitter_sizes(self, top_h: int) -> None:
        usable = self._top_splitter_usable_height()
        top_h = max(RECON_TOP_MIN_HEIGHT, min(int(top_h), usable))
        bottom_h = max(usable - top_h, RECON_BOTTOM_MIN_HEIGHT)
        if top_h + bottom_h > usable:
            top_h = max(RECON_TOP_MIN_HEIGHT, usable - bottom_h)
        self._splitter_programmatic = True
        try:
            self.top_splitter.setSizes([top_h, bottom_h])
        finally:
            self._splitter_programmatic = False
        self._sync_top_splitter_handle_hint()
        self._position_hero_font_float()

    def _restore_top_splitter_sizes(self):
        cfg = self.config or load_secure_config(None) or {}
        raw = cfg.get(RECON_TOP_SPLITTER_KEY)
        if isinstance(raw, (list, tuple)) and len(raw) >= 1:
            try:
                top_h = max(int(raw[0]), RECON_TOP_MIN_HEIGHT)
                self._apply_top_splitter_sizes(top_h)
                return
            except (TypeError, ValueError):
                pass
        top_h, _bottom_h = DEFAULT_RECON_TOP_SPLITTER_SIZES
        self._apply_top_splitter_sizes(top_h)

    def _sync_splitters_to_available_space(self) -> None:
        if self._tables_fullscreen or self._splitter_programmatic:
            return
        top_sizes = self.top_splitter.sizes()
        if len(top_sizes) >= 2:
            self._apply_top_splitter_sizes(int(top_sizes[0]))
        col_sizes = self.columns_splitter.sizes()
        if len(col_sizes) >= 3:
            self._apply_columns_splitter_sizes(int(col_sizes[0]), int(col_sizes[2]))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._tables_fullscreen:
            QTimer.singleShot(0, self._sync_splitters_to_available_space)

    def _on_top_splitter_moved(self, *_args):
        self._sync_top_splitter_handle_hint()
        self._position_hero_font_float()

    def _sync_top_splitter_handle_hint(self):
        sizes = self.top_splitter.sizes()
        if not sizes:
            return
        top_h = int(sizes[0])
        if top_h <= 4:
            self.top_scroll.setToolTip("راهنما مخفی است — اهرم را به پایین بکشید")
        elif top_h < RECON_TOP_EXPANDED_DEFAULT:
            self.top_scroll.setToolTip("برای دیدن کل راهنما، اهرم را بیشتر به پایین بکشید")
        else:
            self.top_scroll.setToolTip("")

    def _schedule_save_top_splitter_sizes(self, *_args):
        timer = getattr(self, "_top_splitter_save_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._save_top_splitter_sizes)
            self._top_splitter_save_timer = timer
        timer.start()

    def _save_top_splitter_sizes(self):
        if self._splitter_programmatic:
            return
        sizes = self.top_splitter.sizes()
        if len(sizes) < 2 or sum(sizes) <= 0:
            return
        top_h = max(int(sizes[0]), RECON_TOP_MIN_HEIGHT)
        bottom_h = max(int(sizes[1]), RECON_BOTTOM_MIN_HEIGHT)
        cfg = load_secure_config(None) or {}
        cfg[RECON_TOP_SPLITTER_KEY] = [top_h, bottom_h]
        cfg.pop("RECON_HERO_COLLAPSED", None)
        save_secure_config(cfg)
        self.config = cfg

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_logs()
        if not self._columns_splitter_layout_applied:
            self._columns_splitter_layout_applied = True
            QTimer.singleShot(0, self._restore_columns_splitter_sizes)
        if not self._top_splitter_layout_applied:
            self._top_splitter_layout_applied = True
            QTimer.singleShot(0, self._restore_top_splitter_sizes)
            QTimer.singleShot(0, self._position_hero_font_float)

    def _set_status(self, state, text):
        self.status_message.setText(text)
        self.status_bar.setProperty("state", state)
        self.status_bar.style().unpolish(self.status_bar)
        self.status_bar.style().polish(self.status_bar)

    def _open_status_search(self):
        if self._status_search_open:
            return
        self._status_search_open = True
        self.type_filter.hide()
        self.search_toggle_btn.hide()
        self.search_expanded.show()
        self.search_input.setFocus()

    def _close_status_search(self):
        if not self._status_search_open:
            return
        self._status_search_open = False
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.search_expanded.hide()
        self.type_filter.show()
        self.search_toggle_btn.show()
        self._refresh_lists()

    def _current_entity(self) -> str:
        return str(self.entity_combo.currentData() or ENTITY_PRODUCTS)

    def _is_attributes_view(self) -> bool:
        return (
            self._comparison is not None
            and self._comparison.entity == ENTITY_ATTRIBUTES
        ) or self._current_entity() == ENTITY_ATTRIBUTES

    def _show_attributes_recon_info(self, extra: str = "") -> None:
        text = ATTR_RECON_BODY
        if extra:
            text = f"{extra}\n\n{text}"
        QMessageBox.information(self, ATTR_RECON_TITLE, text)

    def _update_entity_guide(self):
        if hasattr(self, "hero_body"):
            self.hero_body.setText(recon_hero_html_for_entity(self._current_entity()))

    def _update_category_filter_visibility(self):
        show = self._current_entity() in (ENTITY_PRODUCTS, ENTITY_VARIATIONS)
        self.category_filter_label.setVisible(show)
        self.category_filter_combo.setVisible(show)

    def _populate_category_filter_options(self):
        """گزینه‌های فیلتر رو از جدول S_Group واقعی SQL (کد + نام) پر می‌کنه."""
        current_data = self.category_filter_combo.currentData()

        def _worker():
            from sync_app.core.sql_connection_helper import open_sql_connection
            config = load_secure_config(None) or {}
            conn, _, _ = open_sql_connection(config, timeout=5)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT S_Groupcode, S_GroupName FROM S_Group ORDER BY S_Groupcode")
                return [(str(r[0]).strip(), str(r[1]).strip()) for r in cursor.fetchall()]
            finally:
                conn.close()

        def _done(groups):
            self.category_filter_combo.blockSignals(True)
            self.category_filter_combo.clear()
            self.category_filter_combo.addItem("همه دسته‌بندی‌ها", "")
            for code, name in groups:
                if code:
                    self.category_filter_combo.addItem(f"{name} ({code})" if name else code, code)
            idx = self.category_filter_combo.findData(current_data)
            self.category_filter_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.category_filter_combo.blockSignals(False)

        def _fail(_msg):
            pass  # اگه نشد، فقط «همه دسته‌بندی‌ها» می‌مونه — چیزی رو خراب نمی‌کنه

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _on_category_filter_changed(self):
        self._apply_category_filter()
        self._refresh_lists()

    def _apply_category_filter(self):
        """
        فیلتر رو روی نسخه‌ی کامل و دست‌نخورده (self._comparison_unfiltered)
        اعمال می‌کنه — یعنی تغییر/برداشتن فیلتر هیچ‌وقت داده گم نمی‌کنه.
        فقط برای نمایش/کار روزمره‌ست، آمار و match هم بر اساس همین فیلتر
        محاسبه می‌شن (چون از همون self._comparison مشترک می‌خونن).
        """
        if not self._comparison_unfiltered:
            return
        group_code = str(self.category_filter_combo.currentData() or "").strip()
        if not group_code or self._current_entity() not in (ENTITY_PRODUCTS, ENTITY_VARIATIONS):
            self._comparison = self._comparison_unfiltered
            return

        def _sku_of(row: ReconRow) -> str:
            return str(row.erp_key or row.key or "").split(":")[-1].strip()

        def _matches(row: ReconRow) -> bool:
            sku = _sku_of(row)
            return bool(sku) and sku.startswith(group_code)

        from sync_app.core.reconciliation_service import _compute_stats

        filtered_erp = [r for r in self._comparison_unfiltered.erp_rows if _matches(r)]
        filtered_wc = [r for r in self._comparison_unfiltered.wc_rows if _matches(r)]
        filtered = ComparisonResult(
            entity=self._comparison_unfiltered.entity,
            erp_rows=filtered_erp,
            wc_rows=filtered_wc,
            stats=_compute_stats(filtered_erp, filtered_wc),
        )
        self._comparison = filtered

    def _on_entity_changed(self):
        new_entity = self._current_entity()
        if new_entity == self._active_entity:
            return

        pending_count = len(self._pending_pairs)
        if pending_count:
            if not ask_yes_no(
                self,
                "جفت‌های آماده ثبت",
                f"{pending_count} جفت آماده ثبت دارید.\n"
                "با تغییر نوع داده، این جفت‌ها پاک می‌شوند.\n"
                "ادامه می‌دهید؟",
                icon=QMessageBox.Warning,
            ):
                self.entity_combo.blockSignals(True)
                for i in range(self.entity_combo.count()):
                    if str(self.entity_combo.itemData(i)) == self._active_entity:
                        self.entity_combo.setCurrentIndex(i)
                        break
                self.entity_combo.blockSignals(False)
                return

        self._active_entity = new_entity
        self._update_entity_guide()
        self._update_category_filter_visibility()
        self._comparison = None
        self._comparison_unfiltered = None
        self._pending_pairs = []
        self._auto_suggested_pairs = []
        self.erp_list.clear()
        self.wc_list.clear()
        self.stats_label.setText("آمار: —")
        self._update_pair_count_label()
        self._set_load_btn_mode("load")
        self.load_comparison_data(manual=False)

    def invalidate_stale_sql_data(self):
        """پس از تغییر دیتابیس SQL — پاک‌سازی دادهٔ قدیمی بدون بارگذاری خودکار."""
        self._comparison = None
        self._pending_pairs = []
        self._auto_suggested_pairs = []
        self.erp_list.clear()
        self.wc_list.clear()
        self.stats_label.setText("آمار: —")
        self._update_pair_count_label()
        self._set_load_btn_mode("load")
        self._set_status(
            "info",
            "دیتابیس SQL تغییر کرد — برای مشاهده دادهٔ جدید دکمه «بارگذاری» را بزنید.",
        )

    def _filter_text(self) -> str:
        return (self.search_input.text() or "").strip().lower()

    def _row_passes_filter(self, row: ReconRow) -> bool:
        if self.only_unsynced_cb.isChecked() and row.synced:
            return False
        query = self._filter_text()
        if not query:
            return True
        hay = f"{row.label} {row.erp_key or ''} {row.match_key}".lower()
        return query in hay

    def _pending_row_keys(self) -> tuple[set[str], set[str]]:
        erp_keys = {erp.key for erp, _ in self._pending_pairs}
        wc_keys = {wc.key for _, wc in self._pending_pairs}
        return erp_keys, wc_keys

    def _auto_row_keys(self) -> tuple[set[str], set[str]]:
        erp_keys = {erp.key for erp, _, _ in self._auto_suggested_pairs}
        wc_keys = {wc.key for _, wc, _ in self._auto_suggested_pairs}
        return erp_keys, wc_keys

    def _reserved_row_keys(self) -> tuple[set[str], set[str]]:
        pending_erp, pending_wc = self._pending_row_keys()
        auto_erp, auto_wc = self._auto_row_keys()
        return pending_erp | auto_erp, pending_wc | auto_wc

    def _find_auto_suggestion(
        self, row_key: str | None
    ) -> tuple[ReconRow, ReconRow, str] | None:
        if not row_key:
            return None
        for erp, wc, reason in self._auto_suggested_pairs:
            if erp.key == row_key or wc.key == row_key:
                return erp, wc, reason
        return None

    def _find_auto_pair_by_both_keys(
        self, erp_key: str | None, wc_key: str | None
    ) -> tuple[ReconRow, ReconRow, str] | None:
        if not erp_key or not wc_key:
            return None
        for erp, wc, reason in self._auto_suggested_pairs:
            if erp.key == erp_key and wc.key == wc_key:
                return erp, wc, reason
        return None

    def _resolve_selected_auto_pair(
        self,
        *,
        warn_on_mismatch: bool = False,
    ) -> tuple[ReconRow, ReconRow, str] | None:
        erp_row, erp_section = self._selected_list_row(self.erp_list)
        wc_row, wc_section = self._selected_list_row(self.wc_list)

        if (
            erp_row
            and erp_section == SECTION_AUTO
            and wc_row
            and wc_section == SECTION_AUTO
        ):
            hit = self._find_auto_pair_by_both_keys(erp_row.key, wc_row.key)
            if hit:
                return hit
            if warn_on_mismatch:
                QMessageBox.information(
                    self,
                    "جفت نامعتبر",
                    "دو مورد انتخاب‌شده در بخش خودکار، یک جفت پیشنهادی نیستند.\n"
                    "هر دو طرف همان جفت را انتخاب کنید یا فقط یک طرف را برگزینید.",
                )
            return None

        if erp_row and erp_section == SECTION_AUTO:
            return self._find_auto_suggestion(erp_row.key)
        if wc_row and wc_section == SECTION_AUTO:
            return self._find_auto_suggestion(wc_row.key)
        return None

    def _show_wc_list_context_menu(self, pos):
        if self._current_entity() not in (ENTITY_PRODUCTS, ENTITY_VARIATIONS):
            return
        item = self.wc_list.itemAt(pos)
        if item is None:
            return
        row: ReconRow = item.data(Qt.UserRole)
        if not isinstance(row, ReconRow) or not row.wc_id:
            return

        from sync_app.core.integrations.commerce_provider import (
            is_prestashop, store_platform_label,
        )

        config = load_secure_config(None) or {}
        ps_mode = is_prestashop(config)
        platform_label = store_platform_label(config)

        if ps_mode and self._current_entity() == ENTITY_VARIATIONS:
            # تطبیق واریانت‌های پرستاشاپ هنوز پیاده نشده (فقط دسته‌بندی/محصول/ویژگی) —
            # این ردیف‌ها اصلاً از پرستاشاپ نمیان، پس چیزی برای حذف نیست.
            return

        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setLayoutDirection(Qt.RightToLeft)
        if ps_mode:
            # پرستاشاپ زباله‌دان (soft-delete) نداره — فقط حذف کامل.
            act_trash = None
            act_perm = menu.addAction(f"⚠️ حذف کامل و همیشگی از {platform_label}")
        else:
            act_trash = menu.addAction(f"🗑️ انتقال به زباله‌دان {platform_label}")
            act_perm = menu.addAction(f"⚠️ حذف کامل و همیشگی از {platform_label}")
        chosen = menu.exec_(self.wc_list.mapToGlobal(pos))
        if chosen is None:
            return
        force = ps_mode or chosen is act_perm
        if force:
            if not ask_yes_no(
                self, "تأیید نهایی حذف کامل",
                f"مطمئنید؟ «{row.label}» برای همیشه از {platform_label} پاک می‌شه.",
                icon=QMessageBox.Warning,
            ):
                return
        self._delete_recon_wc_row(row, force)

    def _delete_recon_wc_row(self, row: "ReconRow", force: bool):
        entity = self._current_entity()
        config = load_secure_config(None) or {}

        def _worker():
            from sync_app.core.integrations.commerce_provider import build_store_api, is_prestashop
            from sync_app.core.wc_sync_helper import apply_network_overrides, wc_http_error_message

            if not is_prestashop(config):
                apply_network_overrides(config)
            wcapi = build_store_api(config)
            if entity == ENTITY_VARIATIONS:
                from sync_app.core.product_woo_map_helper import load_product_woo_map

                parent_sku = str((row.extra or {}).get("parent_sku") or "").strip()
                parent_wc_id = load_product_woo_map().get(parent_sku)
                if not parent_wc_id:
                    raise RuntimeError(f"محصول والدِ این واریانت ({parent_sku}) لینک نشده.")
                resp = wcapi.delete(
                    f"products/{int(parent_wc_id)}/variations/{int(row.wc_id)}", params={"force": force}
                )
            else:
                resp = wcapi.delete(f"products/{int(row.wc_id)}", params={"force": force})
            if int(getattr(resp, "status_code", 0) or 0) >= 400:
                raise RuntimeError(wc_http_error_message(resp))
            return resp.json()

        def _done(_data):
            msg = "برای همیشه حذف شد" if force else "به زباله‌دان منتقل شد"
            QMessageBox.information(self, "انجام شد", f"«{row.label}» {msg}.")
            self.load_comparison_data(manual=False)

        def _fail(err_msg):
            QMessageBox.critical(self, "خطا در حذف", f"حذف «{row.label}» ناموفق بود:\n{err_msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _on_list_selection_changed(self):
        sender = self.sender()
        if not self._syncing_list_selection and sender in (self.erp_list, self.wc_list):
            counterpart_key, preferred_sections = self._resolve_counterpart_for_selection(
                sender
            )
            if counterpart_key:
                target = self.wc_list if sender is self.erp_list else self.erp_list
                self._select_row_in_list(
                    target,
                    counterpart_key,
                    preferred_sections=preferred_sections,
                )
        self._update_pair_buttons()
        self._refresh_selection_highlights()

    def _resolve_counterpart_for_selection(
        self, source: QListWidget
    ) -> tuple[str | None, tuple[str, ...]]:
        row, section = self._selected_list_row(source)
        if row is None:
            return None, ()

        if section == SECTION_AUTO:
            hit = self._find_auto_suggestion(row.key)
            if hit:
                erp, wc, _ = hit
                key = wc.key if source is self.erp_list else erp.key
                return key, (SECTION_AUTO,)
            return None, ()

        if section == SECTION_SYNCED and self._comparison:
            hit = find_saved_link_pair(
                self._comparison.entity,
                self._comparison.erp_rows,
                self._comparison.wc_rows,
                erp_row=row if source is self.erp_list else None,
                wc_row=row if source is self.wc_list else None,
            )
            if hit:
                erp, wc = hit
                key = wc.key if source is self.erp_list else erp.key
                return key, (SECTION_SYNCED,)
            return None, ()

        if section == SECTION_PENDING:
            pair = self._find_pending_pair_by_key(row.key)
            if pair:
                erp, wc = pair
                key = wc.key if source is self.erp_list else erp.key
                return key, (SECTION_PENDING,)
            return None, ()

        if self._comparison and section in (SECTION_SYNCED, SECTION_UNPAIRED):
            entity = self._comparison.entity
            if entity in (
                ENTITY_CATEGORIES,
                ENTITY_PRODUCTS,
                ENTITY_VARIATIONS,
                ENTITY_ATTRIBUTES,
            ):
                candidates = (
                    self._comparison.wc_rows
                    if source is self.erp_list
                    else self._comparison.erp_rows
                )
                hit = find_entity_counterpart(entity, row, candidates)
                if hit:
                    return hit.key, (section, SECTION_SYNCED, SECTION_UNPAIRED)

        return None, ()

    def _clear_list_selection(self, widget: QListWidget):
        if widget.currentItem() is None and not widget.selectedItems():
            return
        self._syncing_list_selection = True
        try:
            widget.blockSignals(True)
            widget.clearSelection()
            widget.setCurrentItem(None)
        finally:
            widget.blockSignals(False)
            self._syncing_list_selection = False

    def _select_row_in_list(
        self,
        widget: QListWidget,
        row_key: str,
        *,
        preferred_sections: tuple[str, ...] = (),
    ):
        self._syncing_list_selection = True
        try:
            for section in preferred_sections:
                for index in range(widget.count()):
                    item = widget.item(index)
                    if item.data(ITEM_ROLE_SECTION) != section:
                        continue
                    candidate = item.data(Qt.UserRole)
                    if isinstance(candidate, ReconRow) and candidate.key == row_key:
                        widget.setCurrentItem(item)
                        widget.scrollToItem(item)
                        return
            for index in range(widget.count()):
                item = widget.item(index)
                candidate = item.data(Qt.UserRole)
                if isinstance(candidate, ReconRow) and candidate.key == row_key:
                    widget.setCurrentItem(item)
                    widget.scrollToItem(item)
                    return
        finally:
            self._syncing_list_selection = False

    def _find_pending_pair_by_key(self, row_key: str | None) -> tuple[ReconRow, ReconRow] | None:
        if not row_key:
            return None
        for erp, wc in self._pending_pairs:
            if erp.key == row_key or wc.key == row_key:
                return erp, wc
        return None

    def _resolve_selected_pending_pair(
        self,
        *,
        warn_on_mismatch: bool = False,
    ) -> tuple[ReconRow, ReconRow] | None:
        erp_row, erp_section = self._selected_list_row(self.erp_list)
        wc_row, wc_section = self._selected_list_row(self.wc_list)

        if (
            erp_row
            and erp_section == SECTION_PENDING
            and wc_row
            and wc_section == SECTION_PENDING
        ):
            for erp, wc in self._pending_pairs:
                if erp.key == erp_row.key and wc.key == wc_row.key:
                    return erp, wc
            if warn_on_mismatch:
                QMessageBox.information(
                    self,
                    "جفت نامعتبر",
                    "دو مورد انتخاب‌شده در بخش آبی، یک جفت آماده ثبت نیستند.\n"
                    "فقط یک طرف جفت را انتخاب کنید یا هر دو طرف همان جفت را برگزینید.",
                )
            return None

        if erp_row and erp_section == SECTION_PENDING:
            return self._find_pending_pair_by_key(erp_row.key)
        if wc_row and wc_section == SECTION_PENDING:
            return self._find_pending_pair_by_key(wc_row.key)
        return None

    def _resolve_selected_synced_pair(
        self,
        *,
        warn_on_mismatch: bool = False,
    ) -> tuple[ReconRow, ReconRow] | None:
        if not self._comparison:
            return None
        erp_row, erp_section = self._selected_list_row(self.erp_list)
        wc_row, wc_section = self._selected_list_row(self.wc_list)
        if erp_section != SECTION_SYNCED and wc_section != SECTION_SYNCED:
            return None
        if erp_section == SECTION_SYNCED and wc_section == SECTION_SYNCED:
            hit = find_saved_link_pair(
                self._comparison.entity,
                self._comparison.erp_rows,
                self._comparison.wc_rows,
                erp_row=erp_row,
                wc_row=wc_row,
            )
            if hit:
                return hit
            if warn_on_mismatch:
                QMessageBox.information(
                    self,
                    "جفت نامعتبر",
                    "دو مورد انتخاب‌شده در بخش سبز، در فایل تطبیق جفت یکدیگر نیستند.\n"
                    "فقط یک طرف را انتخاب کنید یا هر دو طرف همان تطبیق ذخیره‌شده را برگزینید.",
                )
            return None
        if erp_section == SECTION_SYNCED and erp_row:
            return find_saved_link_pair(
                self._comparison.entity,
                self._comparison.erp_rows,
                self._comparison.wc_rows,
                erp_row=erp_row,
            )
        if wc_section == SECTION_SYNCED and wc_row:
            return find_saved_link_pair(
                self._comparison.entity,
                self._comparison.erp_rows,
                self._comparison.wc_rows,
                wc_row=wc_row,
            )
        return None

    def _mark_rows_unsynced_locally(self, erp_key: str, wc_key: str):
        if not self._comparison:
            return
        for row in self._comparison.erp_rows:
            if row.key == erp_key:
                row.synced = False
        for row in self._comparison.wc_rows:
            if row.key == wc_key:
                row.synced = False
        recompute_comparison_stats(self._comparison)

    def _friendly_load_error(self, message: str) -> str:
        return format_recon_load_error(message, self.config)

    def _find_pending_pair_by_both_keys(
        self, erp_key: str | None, wc_key: str | None
    ) -> tuple[ReconRow, ReconRow] | None:
        if not erp_key or not wc_key:
            return None
        for erp, wc in self._pending_pairs:
            if erp.key == erp_key and wc.key == wc_key:
                return erp, wc
        return None

    def _default_row_bg(self, row: ReconRow, section: str) -> QColor:
        if section == SECTION_PENDING:
            return COLOR_PENDING
        if section == SECTION_AUTO:
            return COLOR_AUTO_MATCHED if row.key in self._auto_highlight_keys else COLOR_AUTO
        if section == SECTION_SYNCED or row.synced:
            return COLOR_SYNCED
        return COLOR_UNSYNCED

    def _selection_link_kind(
        self,
        erp_row: ReconRow | None,
        erp_section: str | None,
        wc_row: ReconRow | None,
        wc_section: str | None,
    ) -> str | None:
        if not erp_row or not wc_row or not erp_section or not wc_section:
            return None

        if (
            erp_section == SECTION_AUTO
            and wc_section == SECTION_AUTO
            and self._find_auto_pair_by_both_keys(erp_row.key, wc_row.key)
        ):
            return "linked"
        if (
            erp_section == SECTION_PENDING
            and wc_section == SECTION_PENDING
            and self._find_pending_pair_by_both_keys(erp_row.key, wc_row.key)
        ):
            return "linked"
        if erp_section == SECTION_SYNCED and wc_section == SECTION_SYNCED and self._comparison:
            hit = find_saved_link_pair(
                self._comparison.entity,
                self._comparison.erp_rows,
                self._comparison.wc_rows,
                erp_row=erp_row,
                wc_row=wc_row,
            )
            if hit:
                return "linked"
        if (
            erp_section == SECTION_UNPAIRED
            and wc_section == SECTION_UNPAIRED
            and self._comparison
        ):
            entity = self._comparison.entity
            if entity in (
                ENTITY_CATEGORIES,
                ENTITY_PRODUCTS,
                ENTITY_VARIATIONS,
                ENTITY_ATTRIBUTES,
            ):
                hit = find_entity_counterpart(entity, erp_row, [wc_row])
                if hit and hit.key == wc_row.key:
                    return "linked"
            return "manual"
        return None

    def _compute_selection_highlight_keys(self) -> tuple[set[str], set[str]]:
        erp_row, erp_section = self._selected_list_row(self.erp_list)
        wc_row, wc_section = self._selected_list_row(self.wc_list)
        paired: set[str] = set()
        manual: set[str] = set()

        if erp_row and wc_row:
            kind = self._selection_link_kind(erp_row, erp_section, wc_row, wc_section)
            if kind == "linked":
                paired = {erp_row.key, wc_row.key}
            elif kind == "manual":
                manual = {erp_row.key, wc_row.key}
        elif erp_row and erp_section == SECTION_UNPAIRED:
            manual.add(erp_row.key)
        elif wc_row and wc_section == SECTION_UNPAIRED:
            manual.add(wc_row.key)

        return paired, manual

    def _refresh_selection_highlights(self):
        paired, manual = self._compute_selection_highlight_keys()
        if (
            paired == self._selection_paired_keys
            and manual == self._selection_manual_keys
        ):
            return

        self._selection_paired_keys = paired
        self._selection_manual_keys = manual
        self._auto_highlight_keys = paired if paired else set()

        for widget in (self.erp_list, self.wc_list):
            for index in range(widget.count()):
                item = widget.item(index)
                row = item.data(Qt.UserRole)
                section = str(item.data(ITEM_ROLE_SECTION) or "")
                if not isinstance(row, ReconRow):
                    continue
                if row.key in paired:
                    item.setBackground(COLOR_SELECTION_PAIRED)
                elif row.key in manual:
                    item.setBackground(COLOR_SELECTION_MANUAL)
                else:
                    item.setBackground(self._default_row_bg(row, section))

    def _highlight_matched_auto_pair(self):
        """سازگاری با فراخوانی‌های قدیمی."""
        self._refresh_selection_highlights()

    def _add_section_header(self, widget: QListWidget, text: str):
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        item.setTextAlignment(Qt.AlignCenter)
        item.setBackground(COLOR_SECTION)
        item.setForeground(QColor("#475569"))
        widget.addItem(item)

    def _add_row_item(
        self,
        widget: QListWidget,
        row: ReconRow,
        *,
        section: str,
        pair_index: int | None = None,
        tooltip: str = "",
    ):
        if section == SECTION_PENDING:
            prefix = f"🔗{pair_index} "
            bg = COLOR_PENDING
        elif section == SECTION_AUTO:
            prefix = f"🤖{pair_index} "
            bg = self._default_row_bg(row, section)
        elif section == SECTION_SYNCED or row.synced:
            prefix = "✅ "
            bg = COLOR_SYNCED
        else:
            prefix = "⚠️ "
            bg = COLOR_UNSYNCED

        item = QListWidgetItem(f"{prefix}{row.label}")
        item.setData(Qt.UserRole, row)
        item.setData(ITEM_ROLE_SECTION, section)
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        item.setBackground(bg)
        if tooltip:
            item.setToolTip(tooltip)
        widget.addItem(item)

    def _render_reconciliation_lists(self):
        if not self._comparison:
            return

        pending_erp, pending_wc = self._pending_row_keys()
        reserved_erp, reserved_wc = self._reserved_row_keys()
        erp_unpaired: list[ReconRow] = []
        wc_unpaired: list[ReconRow] = []
        erp_synced: list[ReconRow] = []
        wc_synced: list[ReconRow] = []

        for row in self._comparison.erp_rows:
            if row.key in reserved_erp:
                continue
            if not self._row_passes_filter(row):
                continue
            if row.synced:
                erp_synced.append(row)
            else:
                erp_unpaired.append(row)

        for row in self._comparison.wc_rows:
            if row.key in reserved_wc:
                continue
            if not self._row_passes_filter(row):
                continue
            if row.synced:
                wc_synced.append(row)
            else:
                wc_unpaired.append(row)

        self.erp_list.blockSignals(True)
        self.wc_list.blockSignals(True)
        self.erp_list.clear()
        self.wc_list.clear()

        if self._pending_pairs:
            count = len(self._pending_pairs)
            self._add_section_header(
                self.erp_list,
                f"── 🔗 جفت‌های آماده ثبت ({count}) ──",
            )
            self._add_section_header(
                self.wc_list,
                f"── 🔗 جفت‌های آماده ثبت ({count}) ──",
            )
            for index, (erp, wc) in enumerate(self._pending_pairs, start=1):
                self._add_row_item(
                    self.erp_list, erp, section=SECTION_PENDING, pair_index=index
                )
                self._add_row_item(
                    self.wc_list, wc, section=SECTION_PENDING, pair_index=index
                )

        if self._auto_suggested_pairs:
            auto_count = len(self._auto_suggested_pairs)
            self._add_section_header(
                self.erp_list,
                f"── 🤖 پیشنهاد سیستم — نیاز بررسی ({auto_count}) ──",
            )
            self._add_section_header(
                self.wc_list,
                f"── 🤖 پیشنهاد سیستم — نیاز بررسی ({auto_count}) ──",
            )
            for index, (erp, wc, reason) in enumerate(self._auto_suggested_pairs, start=1):
                suggestion_tip = format_suggestion_tooltip(reason, erp, wc)
                self._add_row_item(
                    self.erp_list,
                    erp,
                    section=SECTION_AUTO,
                    pair_index=index,
                    tooltip=suggestion_tip,
                )
                self._add_row_item(
                    self.wc_list,
                    wc,
                    section=SECTION_AUTO,
                    pair_index=index,
                    tooltip=suggestion_tip,
                )

        self._add_section_header(self.erp_list, "── ⏳ منتظر جفت (ERP) ──")
        self._add_section_header(self.wc_list, "── ⏳ منتظر جفت (فروشگاه) ──")

        if erp_unpaired:
            for row in erp_unpaired:
                self._add_row_item(self.erp_list, row, section=SECTION_UNPAIRED)
        else:
            self._add_empty_hint(
                self.erp_list,
                self._comparison.erp_rows,
                side="erp",
            )

        if wc_unpaired:
            for row in wc_unpaired:
                self._add_row_item(self.wc_list, row, section=SECTION_UNPAIRED)
        else:
            self._add_empty_hint(
                self.wc_list,
                self._comparison.wc_rows,
                side="wc",
            )

        if erp_synced or wc_synced:
            synced_header = (
                ATTR_RECON_SYNCED_HEADER
                if self._comparison.entity == ENTITY_ATTRIBUTES
                else "── ✅ قبلاً تطبیق داده شده (انتخاب + «لغو جفت») ──"
            )
            self._add_section_header(self.erp_list, synced_header)
            self._add_section_header(self.wc_list, synced_header)
            for row in erp_synced:
                self._add_row_item(self.erp_list, row, section=SECTION_SYNCED)
            for row in wc_synced:
                self._add_row_item(self.wc_list, row, section=SECTION_SYNCED)

        self.erp_list.blockSignals(False)
        self.wc_list.blockSignals(False)
        self._refresh_selection_highlights()
        self._update_pair_buttons()

    def _add_empty_hint(self, widget: QListWidget, rows: list[ReconRow], *, side: str):
        if rows and self.only_unsynced_cb.isChecked() and all(r.synced for r in rows):
            text = "همه موارد سینک‌شده‌اند — تیک «فقط غیرسینک» را بردارید."
        elif rows and self._filter_text():
            text = "نتیجه‌ای با این جستجو یافت نشد."
        elif side == "erp" and self._pending_pairs and not self._filter_text():
            text = "همه موارد ERP جفت شده‌اند."
        elif side == "wc" and self._pending_pairs and not self._filter_text():
            text = "همه موارد فروشگاه جفت شده‌اند."
        else:
            text = "موردی برای نمایش نیست."
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        widget.addItem(item)

    def _refresh_lists(self):
        if not self._comparison:
            return
        self._render_reconciliation_lists()
        self._update_stats_label()
        self._update_pair_count_label()

    def _update_pair_count_label(self):
        pending_count = len(self._pending_pairs)
        auto_count = len(self._auto_suggested_pairs)
        self.pair_count_label.setText(
            f"آماده ثبت: {pending_count} | پیشنهاد بنفش: {auto_count}"
        )
        self.commit_btn.setEnabled(
            pending_count > 0
            and not self._loading
            and not self._is_attributes_view()
        )
        self.commit_btn.setText(
            f"💾 ثبت نهایی تطبیق ({pending_count} جفت)"
            if pending_count
            else "💾 ثبت نهایی تطبیق"
        )
        self.confirm_all_auto_btn.setEnabled(
            auto_count > 0 and not self._loading and not self._is_attributes_view()
        )

    def _selected_list_row(self, widget: QListWidget) -> tuple[ReconRow | None, str | None]:
        item = widget.currentItem()
        if not item:
            return None, None
        row = item.data(Qt.UserRole)
        section = item.data(ITEM_ROLE_SECTION)
        if isinstance(row, ReconRow):
            return row, str(section or "")
        return None, None

    def _update_pair_buttons(self):
        erp_row, erp_section = self._selected_list_row(self.erp_list)
        wc_row, wc_section = self._selected_list_row(self.wc_list)
        is_attrs = self._is_attributes_view()

        can_pair = (
            not is_attrs
            and erp_row is not None
            and wc_row is not None
            and erp_section == SECTION_UNPAIRED
            and wc_section == SECTION_UNPAIRED
            and not erp_row.synced
            and not wc_row.synced
            and not self._loading
        )
        self.pair_btn.setEnabled(can_pair)

        pending_pair = self._resolve_selected_pending_pair()
        saved_pair = self._resolve_selected_synced_pair()
        can_unpair = not self._loading and (
            pending_pair is not None
            or (saved_pair is not None and not is_attrs)
        )
        self.unpair_btn.setEnabled(can_unpair)

        auto_hit = self._resolve_selected_auto_pair()
        can_confirm_auto = auto_hit is not None and not self._loading and not is_attrs
        self.confirm_auto_btn.setEnabled(can_confirm_auto)
        self.reject_auto_btn.setEnabled(can_confirm_auto)
        self.auto_suggest_btn.setEnabled(
            bool(self._comparison) and not self._loading and not is_attrs
        )

        if is_attrs:
            attr_tip = "ویژگی‌ها خودکار تطبیق می‌شوند — فقط مشاهده"
            self.pair_btn.setToolTip(attr_tip)
            self.unpair_btn.setToolTip(
                "جفت سبز = نام یکسان — کلیک کنید تا توضیح ببینید"
            )
            self.auto_suggest_btn.setToolTip(attr_tip)
        else:
            self.pair_btn.setToolTip(
                "یک ردیف ERP و یک ردیف فروشگاه (زرد) انتخاب کنید — "
                "آبی = آماده جفت دستی | سبز = جفت موجود"
            )
            self.unpair_btn.setToolTip(
                "جفت آبی (آماده ثبت) یا سبز (ثبت‌شده) را لغو کن"
            )
            self.auto_suggest_btn.setToolTip(
                "جفت‌های محتمل با کد یا نام یکسان را پیشنهاد می‌دهد"
            )

    def _wc_rows_for_guard(self) -> list[ReconRow] | None:
        return self._comparison.wc_rows if self._comparison else None

    def _wc_ids_loaded(self) -> list[int]:
        """شناسه‌های ووکامرسِ همین الان لود‌شده در ستون فروشگاه تب تطبیق."""
        wc_rows = self._wc_rows_for_guard()
        if not wc_rows:
            return []
        return [int(r.wc_id) for r in wc_rows if getattr(r, "wc_id", None)]

    def _export_wc_products_excel(self):
        self._run_wc_excel_export(kind="products")

    def _export_wc_variations_excel(self):
        self._run_wc_excel_export(kind="variations")

    def _run_wc_excel_export(self, *, kind: str):
        if self._active_entity != ENTITY_PRODUCTS:
            QMessageBox.information(
                self, "ابتدا محصولات را انتخاب کنید",
                "خروجی اکسل فقط برای «محصول» ساخته می‌شه — از باکس بالا نوع رو روی «📦 محصول» بذارید و دوباره داده رو لود کنید.",
            )
            return

        wc_ids = self._wc_ids_loaded()
        if not wc_ids:
            QMessageBox.information(
                self, "چیزی لود نشده",
                "اول باید محصولات فروشگاه در تب تطبیق لود شده باشن (دکمه‌ی بارگذاری رو بزنید).",
            )
            return

        default_name = "محصولات_سایت.xlsx" if kind == "products" else "متغیرهای_سایت.xlsx"
        out_path, _ = QFileDialog.getSaveFileName(self, "ذخیره‌ی خروجی اکسل", default_name, "Excel (*.xlsx)")
        if not out_path:
            return
        if not out_path.lower().endswith(".xlsx"):
            out_path += ".xlsx"

        btn = self.export_products_btn if kind == "products" else self.export_variations_btn
        btn.setEnabled(False)
        original_text = btn.text()
        btn.setText("⏳ در حال آماده‌سازی...")

        config = load_secure_config(None) or {}

        def _worker():
            from sync_app.core.reconciliation_export import (
                fetch_products_for_export, export_products_to_excel, export_variations_to_excel,
            )

            def _progress(done, total):
                pct = int(done / max(1, total) * 100)
                btn_text = f"⏳ {done}/{total} ({pct}%)"
                try:
                    btn.setText(btn_text)
                except Exception:
                    pass

            rows = fetch_products_for_export(config, wc_ids, progress_cb=_progress)
            if kind == "products":
                count = export_products_to_excel(rows, out_path)
            else:
                count = export_variations_to_excel(rows, out_path)
            return count

        def _done(count):
            btn.setEnabled(True)
            btn.setText(original_text)
            noun = "محصول" if kind == "products" else "متغیر"
            QMessageBox.information(self, "انجام شد", f"{count:,} {noun} در فایل زیر ذخیره شد:\n{out_path}")

        def _fail(msg):
            btn.setEnabled(True)
            btn.setText(original_text)
            QMessageBox.critical(self, "خطا در ساخت خروجی اکسل", str(msg))

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _promote_pairs_to_pending(
        self, pairs: list[tuple[ReconRow, ReconRow]], *, entity: str
    ) -> bool:
        if not pairs:
            return False
        if not confirm_reconciliation_link_risks(
            self, entity, pairs, wc_rows=self._wc_rows_for_guard()
        ):
            return False
        pending_erp, pending_wc = self._pending_row_keys()
        promoted = 0
        for erp, wc in pairs:
            if erp.key in pending_erp or wc.key in pending_wc:
                continue
            self._pending_pairs.append((erp, wc))
            pending_erp.add(erp.key)
            pending_wc.add(wc.key)
            promoted += 1
        remove_keys = {erp.key for erp, _ in pairs} | {wc.key for _, wc in pairs}
        self._auto_suggested_pairs = [
            item
            for item in self._auto_suggested_pairs
            if item[0].key not in remove_keys and item[1].key not in remove_keys
        ]
        return promoted > 0

    def run_auto_suggest(self):
        if not self._comparison:
            QMessageBox.warning(self, "بارگذاری نشده", "ابتدا «بارگذاری مقایسه» را بزنید.")
            return
        if self._current_entity() == ENTITY_ATTRIBUTES:
            self._show_attributes_recon_info(
                "پیشنهاد خودکار برای ویژگی‌ها فعال نیست."
            )
            return

        entity = self._current_entity()
        reserved_erp, reserved_wc = self._reserved_row_keys()
        suggestions = suggest_auto_pairs(
            entity,
            self._comparison.erp_rows,
            self._comparison.wc_rows,
            exclude_erp_keys=reserved_erp,
            exclude_wc_keys=reserved_wc,
        )
        if not suggestions:
            QMessageBox.information(
                self,
                "پیشنهادی نیست",
                "جفت جدیدی با کد یا نام یکسان (هر کدام فقط یک طرف) پیدا نشد.",
            )
            return

        existing = {(e.key, w.key) for e, w, _ in self._auto_suggested_pairs}
        added = 0
        for item in suggestions:
            key = (item.erp.key, item.wc.key)
            if key in existing:
                continue
            self._auto_suggested_pairs.append((item.erp, item.wc, item.reason))
            existing.add(key)
            added += 1

        if not added:
            QMessageBox.information(self, "پیشنهادی نیست", "همه جفت‌های ممکن قبلاً پیشنهاد شده‌اند.")
            return

        self._refresh_lists()
        self._set_status(
            "info",
            f"🤖 {added} پیشنهاد خودکار اضافه شد — در بخش بنفش بررسی و تأیید کنید.",
        )
        log.info(f"🤖 پیشنهاد خودکار {entity}: {added} جفت")

    def confirm_selected_auto_pair(self):
        if not self._comparison:
            return
        hit = self._resolve_selected_auto_pair(warn_on_mismatch=True)
        if not hit:
            QMessageBox.information(
                self,
                "انتخاب نشده",
                "یک جفت از بخش «جفت‌سازی خودکار — نیاز به تأیید» (بنفش) را انتخاب کنید.\n"
                "می‌توانید فقط یک طرف یا هر دو طرف همان جفت را انتخاب کنید.",
            )
            return
        erp, wc, _reason = hit
        if self._promote_pairs_to_pending([(erp, wc)], entity=self._current_entity()):
            self._auto_highlight_keys = set()
            self._refresh_lists()
            self._set_status("success", "✓ پیشنهاد تأیید شد — به بخش آبی «آماده ثبت» منتقل شد.")
        else:
            self._set_status("info", "تأیید انجام نشد — احتمالاً انصراف دادید یا جفت تکراری بود.")

    def confirm_all_auto_pairs(self):
        if not self._auto_suggested_pairs:
            return
        pairs = [(erp, wc) for erp, wc, _ in self._auto_suggested_pairs]
        before = len(self._pending_pairs)
        if self._promote_pairs_to_pending(pairs, entity=self._current_entity()):
            added = len(self._pending_pairs) - before
            self._auto_highlight_keys = set()
            self._refresh_lists()
            self._set_status(
                "success",
                f"✓ {added} پیشنهاد تأیید شد — به بخش آبی «آماده ثبت» منتقل شد.",
            )
        else:
            self._set_status(
                "info",
                "تأیید همه انجام نشد — در دیالوگ هشدار «انصراف» زده‌اید یا جفتی برای انتقال نبود.",
            )

    def reject_selected_auto_pair(self):
        hit = self._resolve_selected_auto_pair(warn_on_mismatch=True)
        if not hit:
            QMessageBox.information(
                self,
                "انتخاب نشده",
                "یک جفت از بخش بنفش را برای رد کردن انتخاب کنید.",
            )
            return
        erp, wc, _ = hit
        self._auto_suggested_pairs = [
            item
            for item in self._auto_suggested_pairs
            if item[0].key != erp.key and item[1].key != wc.key
        ]
        self._refresh_lists()
        self._set_status("info", "✗ پیشنهاد خودکار رد شد.")

    def pair_selected_rows(self):
        if not self._comparison:
            return
        if self._current_entity() == ENTITY_ATTRIBUTES:
            self._show_attributes_recon_info(
                "اتصال دستی لازم نیست — اگر نام یکسان است، سبز یعنی تطبیق شده."
            )
            return
        erp_row, erp_section = self._selected_list_row(self.erp_list)
        wc_row, wc_section = self._selected_list_row(self.wc_list)
        if not erp_row or not wc_row:
            QMessageBox.information(
                self,
                "انتخاب ناقص",
                "از ستون ERP و ستون فروشگاه هر کدام یک مورد انتخاب کنید.",
            )
            return
        if erp_section != SECTION_UNPAIRED or wc_section != SECTION_UNPAIRED:
            QMessageBox.information(
                self,
                "بخش اشتباه",
                "فقط از بخش «منتظر جفت» (زرد) در هر دو ستون انتخاب کنید.",
            )
            return
        if erp_row.synced or wc_row.synced:
            if self._current_entity() == ENTITY_ATTRIBUTES:
                self._show_attributes_recon_info(
                    "این ویژگی قبلاً با نام یکسان تشخیص داده شده."
                )
                return
            QMessageBox.warning(
                self,
                "قبلاً تطبیق داده شده",
                "این مورد قبلاً تطبیق داده شده است.\n"
                "برای حذف تطبیق، از بخش سبز انتخاب کنید و «لغو جفت» را بزنید.",
            )
            return

        entity = self._current_entity()
        pair = (erp_row, wc_row)
        if not confirm_reconciliation_link_risks(
            self, entity, [pair], wc_rows=self._wc_rows_for_guard()
        ):
            return

        self._pending_pairs.append(pair)
        self._refresh_lists()
        erp_short = erp_row.label if len(erp_row.label) <= 45 else erp_row.label[:45] + "…"
        wc_short = wc_row.label if len(wc_row.label) <= 45 else wc_row.label[:45] + "…"
        self._set_status(
            "info",
            f"🔗 جفت {len(self._pending_pairs)} آماده — ERP: {erp_short} ↔ Woo: {wc_short}",
        )
        log.info(f"🔗 جفت آماده: ERP={erp_row.erp_key or erp_row.key} ↔ Woo={wc_row.wc_id}")

    def unpair_selected_row(self):
        if self._current_entity() == ENTITY_ATTRIBUTES:
            pending_pair = self._resolve_selected_pending_pair(warn_on_mismatch=True)
            if pending_pair:
                erp, wc = pending_pair
                self._pending_pairs = [
                    pair
                    for pair in self._pending_pairs
                    if pair[0].key != erp.key or pair[1].key != wc.key
                ]
                self._refresh_lists()
                self._set_status("info", "↩ جفت لغو شد.")
                return
            saved_pair = self._resolve_selected_synced_pair(warn_on_mismatch=True)
            if saved_pair:
                self._show_attributes_recon_info(
                    "جفت سبز با «نام یکسان» است — از اینجا لغو نمی‌شود."
                )
                return

        pending_pair = self._resolve_selected_pending_pair(warn_on_mismatch=True)
        if pending_pair:
            erp, wc = pending_pair
            before = len(self._pending_pairs)
            self._pending_pairs = [
                pair
                for pair in self._pending_pairs
                if pair[0].key != erp.key or pair[1].key != wc.key
            ]
            if len(self._pending_pairs) == before:
                return
            self._refresh_lists()
            self._set_status(
                "info",
                "↩ جفت لغو شد — موارد به بخش «منتظر جفت» برگشتند.",
            )
            return

        saved_pair = self._resolve_selected_synced_pair(warn_on_mismatch=True)
        if saved_pair:
            self._unpair_saved_link(saved_pair)
            return

        QMessageBox.information(
            self,
            "انتخاب نشده",
            "یک جفت از بخش آبی (آماده ثبت) یا سبز (تطبیق داده‌شده) را انتخاب کنید.",
        )

    def _unpair_saved_link(self, pair: tuple[ReconRow, ReconRow]):
        if not self._comparison:
            return
        entity = self._current_entity()
        if entity == ENTITY_ATTRIBUTES:
            self._show_attributes_recon_info(
                "ثبت فایل تطبیق برای ویژگی‌ها انجام نمی‌شود."
            )
            return

        erp, wc = pair
        erp_short = erp.label if len(erp.label) <= 50 else erp.label[:50] + "…"
        wc_short = wc.label if len(wc.label) <= 50 else wc.label[:50] + "…"
        if not ask_yes_no(
            self,
            "لغو تطبیق ذخیره‌شده",
            f"تطبیق زیر از فایل تطبیق حذف شود؟\n\n"
            f"ERP: {erp_short}\n"
            f"Woo: {wc_short}\n\n"
            "بعد از حذف، این موارد دوباره در بخش زرد «منتظر جفت» قرار می‌گیرند.",
            icon=QMessageBox.Warning,
        ):
            return
        if not confirm_live_site_backup(self, "لغو تطبیق"):
            return

        if remove_link_pair(entity, erp, wc):
            self._mark_rows_unsynced_locally(erp.key, wc.key)
            self._refresh_lists()
            self._set_status("success", "↩ تطبیق از فایل تطبیق حذف شد.")
        elif entity == ENTITY_PRODUCTS and not product_pair_in_map(erp, wc):
            QMessageBox.information(
                self,
                "در فایل ثبت نشده",
                "این جفت فقط با «کد یکسان» تشخیص داده می‌شود و در فایل تطبیق نیست.\n\n"
                "برای ثبت: «ثبت سریع کد یکسان» یا اتصال دستی.\n"
                "نیازی به لغو نیست — در بخش زرد منتظر جفت است.",
            )
        else:
            QMessageBox.warning(
                self,
                "حذف نشد",
                "این تطبیق در فایل پیدا نشد یا قبلاً حذف شده.\n"
                "یک‌بار «بارگذاری مقایسه» را بزنید.",
            )

    def run_final_commit(self):
        if not self._comparison:
            QMessageBox.warning(self, "بارگذاری نشده", "ابتدا «بارگذاری مقایسه» را بزنید.")
            return
        if self._current_entity() == ENTITY_ATTRIBUTES:
            self._show_attributes_recon_info("ثبت نهایی تطبیق برای ویژگی‌ها لازم نیست.")
            return
        if not self._pending_pairs:
            QMessageBox.information(
                self,
                "جفتی نیست",
                "ابتدا با «اتصال دستی» یا «یافتن پیشنهادها» حداقل یک جفت بسازید.",
            )
            return
        if not confirm_live_site_backup(self, "ثبت نهایی تطبیق"):
            return

        entity = self._current_entity()
        pairs = list(self._pending_pairs)
        if not confirm_reconciliation_link_risks(
            self, entity, pairs, wc_rows=self._wc_rows_for_guard()
        ):
            return
        count = save_link_pairs(entity, pairs, wc_rows=self._wc_rows_for_guard())
        if count:
            log.info(f"✅ تطبیق {ENTITY_LABELS.get(entity, entity)}: {count} مورد ثبت شد.")
            QMessageBox.information(
                self,
                "تطبیق ثبت شد",
                f"{count} جفت با موفقیت در فایل تطبیق ذخیره شد.\n"
                "اکنون می‌توانید از تب محصولات همگام‌سازی را اجرا کنید.",
            )
            if self._comparison:
                mark_comparison_pairs_synced(self._comparison, pairs)
            self._pending_pairs = []
            self._auto_suggested_pairs = []
            self._refresh_lists()
            self._set_status("success", f"✅ {count} جفت در فایل تطبیق ذخیره شد.")
        else:
            QMessageBox.warning(self, "ثبت نشد", "هیچ تطبیقی ذخیره نشد — کلیدها را بررسی کنید.")

    def _update_stats_label(self):
        if not self._comparison:
            self.stats_label.setText("آمار: —")
            return
        s = self._comparison.stats
        entity = ENTITY_LABELS.get(self._comparison.entity, self._comparison.entity)
        self.stats_label.setText(
            f"{entity} — ERP: {s['erp_total']} (سینک {s['erp_synced']} / "
            f"غیرسینک {s['erp_unsynced']}) | "
            f"Woo: {s['wc_total']} (سینک {s['wc_synced']} / غیرسینک {s['wc_unsynced']})"
        )

    def _rebind_pending_pairs(self, result: ComparisonResult) -> int:
        """بعد از بارگذاری مجدد، جفت‌های آماده را با داده تازه وصل می‌کند."""
        if not self._pending_pairs:
            return 0

        snapshot = [(erp.key, wc.key) for erp, wc in self._pending_pairs]
        erp_index = {row.key: row for row in result.erp_rows}
        wc_index = {row.key: row for row in result.wc_rows}
        restored: list[tuple[ReconRow, ReconRow]] = []
        for erp_key, wc_key in snapshot:
            erp = erp_index.get(erp_key)
            wc = wc_index.get(wc_key)
            if erp and wc and not erp.synced and not wc.synced:
                restored.append((erp, wc))

        lost = len(snapshot) - len(restored)
        self._pending_pairs = restored
        return lost

    def _rebind_auto_suggestions(self, result: ComparisonResult) -> int:
        if not self._auto_suggested_pairs:
            return 0

        snapshot = [(erp.key, wc.key, reason) for erp, wc, reason in self._auto_suggested_pairs]
        erp_index = {row.key: row for row in result.erp_rows}
        wc_index = {row.key: row for row in result.wc_rows}
        restored: list[tuple[ReconRow, ReconRow, str]] = []
        for erp_key, wc_key, reason in snapshot:
            erp = erp_index.get(erp_key)
            wc = wc_index.get(wc_key)
            if erp and wc and not erp.synced and not wc.synced:
                restored.append((erp, wc, reason))

        lost = len(snapshot) - len(restored)
        self._auto_suggested_pairs = restored
        return lost

    def _load_btn_idle_text(self) -> str:
        if self._comparison is not None:
            return "🔄 بارگذاری مجدد"
        return "🔄 بارگذاری مقایسه"

    def _set_load_btn_mode(self, mode: str):
        mode = "stop" if mode == "stop" else "load"
        self.refresh_btn.setProperty("reconLoadMode", mode)
        if mode == "stop":
            self.refresh_btn.setText("⏹ توقف بارگذاری")
            self.refresh_btn.setToolTip("توقف عملیات بارگذاری در جریان")
            self.refresh_btn.setEnabled(True)
        else:
            self.refresh_btn.setText(self._load_btn_idle_text())
            self.refresh_btn.setToolTip(
                "اولین بار: دریافت لیست از ERP و فروشگاه\n"
                "بارگذاری مجدد: فقط در صورت نیاز — قبل از آن تأیید می‌گیرد"
            )
            self.refresh_btn.setEnabled(not self._loading)
        self.refresh_btn.style().unpolish(self.refresh_btn)
        self.refresh_btn.style().polish(self.refresh_btn)
        self.refresh_btn.update()

    def _on_load_btn_clicked(self):
        if self._loading:
            self._cancel_load_comparison()
        else:
            self.load_comparison_data(manual=True)

    def _begin_load_comparison_ui(self, entity: str):
        self._loading = True
        self._load_cancel_event.clear()
        self.load_progress.setVisible(True)
        self._set_load_btn_mode("stop")
        self.auto_btn.setEnabled(False)
        self.commit_btn.setEnabled(False)
        self.pair_btn.setEnabled(False)
        self.auto_suggest_btn.setEnabled(False)
        self.confirm_auto_btn.setEnabled(False)
        self.confirm_all_auto_btn.setEnabled(False)
        self.reject_auto_btn.setEnabled(False)
        self._set_status(
            "loading",
            f"⏳ در حال دریافت {ENTITY_LABELS.get(entity, entity)} از ERP و ووکامرس...",
        )

    def _end_load_comparison_ui(self):
        self._loading = False
        self.load_progress.setVisible(False)
        self._set_load_btn_mode("load")
        self.auto_btn.setEnabled(True)
        self._update_pair_count_label()
        self.pair_btn.setEnabled(False)

    def _cancel_load_comparison(self):
        if not self._loading:
            return
        self._load_cancel_event.set()
        self._load_generation += 1
        self._end_load_comparison_ui()
        self._set_status("warning", "⏹ بارگذاری مقایسه متوقف شد.")
        log.info("⏹ کاربر: بارگذاری مقایسه متوقف شد.")

    def load_comparison_data(self, manual=False):
        # فقط وقتی هر دو badge هدر (SQL + Woo) سبز باشند ادامه بده
        if not ensure_connectivity(self, need_sql=True, need_wc=True, live=False):
            if manual:
                self._set_status(
                    "error",
                    "❌ اتصال SQL یا WooCommerce برقرار نیست — "
                    "ابتدا دکمه‌های بالای برنامه را سبز کنید.",
                )
            return
        if self._loading:
            if manual:
                QMessageBox.information(self, "در حال بارگذاری", "بارگذاری قبلی هنوز در جریان است.")
            return

        pending_count = len(self._pending_pairs)
        auto_count = len(self._auto_suggested_pairs)
        if manual and self._comparison is not None:
            entity_label = ENTITY_LABELS.get(self._current_entity(), self._current_entity())
            if pending_count or auto_count:
                confirm_text = (
                    f"شما {pending_count} جفت آماده ثبت"
                    f" و {auto_count} پیشنهاد خودکار دارید.\n\n"
                    "بارگذاری مجدد لیست را از ERP و فروشگاه می‌خواند.\n"
                    "جفت‌ها و پیشنهادها تا حد ممکن حفظ می‌شوند، اما بهتر است ابتدا "
                    "«ثبت نهایی تطبیق» را بزنید.\n\n"
                    "ادامه می‌دهید؟"
                )
            else:
                confirm_text = (
                    f"لیست «{entity_label}» قبلاً بارگذاری شده است.\n\n"
                    "بارگذاری مجدد دوباره از ERP و فروشگاه می‌خواند "
                    "و ممکن است چند لحظه طول بکشد.\n\n"
                    "آیا واقعاً می‌خواهید دوباره بارگذاری کنید؟"
                )
            if not ask_yes_no(
                self,
                "بارگذاری مجدد مقایسه",
                confirm_text,
                icon=QMessageBox.Warning if (pending_count or auto_count) else QMessageBox.Question,
            ):
                return

        self.config = load_secure_config(None) or {}
        entity = self._current_entity()
        self._load_generation += 1
        generation = self._load_generation
        self._begin_load_comparison_ui(entity)

        def _worker():
            return load_comparison(
                self.config,
                entity,
                cancel_check=self._load_cancel_event.is_set,
                use_cache=not manual,
            )

        def _done(result: ComparisonResult):
            if generation != self._load_generation:
                return
            lost_pairs = self._rebind_pending_pairs(result)
            lost_auto = self._rebind_auto_suggestions(result)
            lost_total = lost_pairs + lost_auto
            self._comparison_unfiltered = result
            self._apply_category_filter()
            if self._current_entity() in (ENTITY_PRODUCTS, ENTITY_VARIATIONS):
                self._populate_category_filter_options()
            self._refresh_lists()
            self._end_load_comparison_ui()
            status = (
                f"✅ مقایسه {ENTITY_LABELS.get(entity, entity)} آماده — "
                f"{result.stats['erp_unsynced']} مورد ERP و "
                f"{result.stats['wc_unsynced']} مورد Woo هنوز سینک نشده‌اند."
            )
            if lost_total:
                status += f" ⚠️ {lost_total} جفت/پیشنهاد بازیابی نشد."
                if manual:
                    QMessageBox.warning(
                        self,
                        "بخشی از جفت‌ها از دست رفت",
                        f"{lost_total} مورد از جفت‌ها یا پیشنهادهای خودکار "
                        "بعد از بارگذاری مجدد بازیابی نشد.\n"
                        "احتمالاً آن کالا دیگر در لیست نیست یا قبلاً تطبیق داده شده.",
                    )
            self._set_status("success" if not lost_total else "warning", status)
            self._set_load_btn_mode("load")
            log.info(
                f"📊 مقایسه {entity}: ERP={result.stats['erp_total']} "
                f"Woo={result.stats['wc_total']}"
            )
            self.refresh_logs()

        def _fail(msg):
            if generation != self._load_generation:
                return
            had_comparison = self._comparison is not None
            self._end_load_comparison_ui()
            cancelled = "متوقف شد" in str(msg)
            if cancelled:
                self._set_status("warning", f"⏹ {msg}")
                log.info(f"⏹ {msg}")
                if had_comparison:
                    self._refresh_lists()
                return

            friendly = self._friendly_load_error(str(msg))
            short = friendly.split("\n", 1)[0]
            self._set_status("error", f"❌ {short[:160]}")
            log.error(f"❌ خطا در بارگذاری مقایسه: {msg}")
            if had_comparison:
                self._refresh_lists()
                friendly += (
                    "\n\nلیست قبلی حفظ شد — بعد از برقراری اتصال، "
                    "«بارگذاری مجدد» را بزنید."
                )
            if manual or had_comparison:
                QMessageBox.warning(self, "خطای بارگذاری", friendly)

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def run_auto_link(self):
        if not ensure_connectivity(self, need_sql=False, need_wc=False):
            return
        if not self._comparison:
            QMessageBox.warning(self, "بارگذاری نشده", "ابتدا «بارگذاری مقایسه» را بزنید.")
            return
        if self._pending_pairs or self._auto_suggested_pairs:
            parts = []
            if self._pending_pairs:
                parts.append(f"{len(self._pending_pairs)} جفت آماده ثبت")
            if self._auto_suggested_pairs:
                parts.append(f"{len(self._auto_suggested_pairs)} پیشنهاد خودکار")
            answer = ask_yes_no(
                self,
                "جفت‌های آماده",
                " و ".join(parts) + " دارید که هنوز ذخیره نشده‌اند.\n"
                "ثبت سریع با کد یکسان ممکن است با آن‌ها تداخل کند. ادامه می‌دهید؟",
            )
            if not answer:
                return
            self._pending_pairs = []
            self._auto_suggested_pairs = []
            self._refresh_lists()
        if not confirm_live_site_backup(self, "تطبیق خودکار (کد یکسان)"):
            return

        entity = self._current_entity()
        if not ask_yes_no(
            self,
            "ثبت سریع کد یکسان",
            f"همه موارد {ENTITY_LABELS.get(entity, entity)} با کد محصول یکسان "
            "بدون پیش‌نمایش در فایل تطبیق ذخیره شوند؟",
        ):
            return

        self.config = load_secure_config(None) or {}
        count, message = auto_link_all(self.config, entity)
        if count:
            QMessageBox.information(self, "تطبیق خودکار", message)
            self.load_comparison_data(manual=False)
        else:
            QMessageBox.information(self, "تطبیق خودکار", message)

    def refresh_logs(self):
        log_path = app_path("sync.log")
        try:
            import os

            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                tokens = [t.lower() for t in RECON_LOG_TOKENS]
                filtered = [line for line in lines if any(tok in line.lower() for tok in tokens)]
                body = format_log_lines_jalali(filtered[-50:])
            else:
                body = "هنوز لاگی ثبت نشده است."
            self.log_view.setPlainText(body)
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
        except Exception as exc:
            self.log_view.setPlainText(f"خطا در خواندن لاگ: {exc}")

    def clear_tab_logs(self):
        removed = clear_filtered_logs(list(RECON_LOG_TOKENS))
        self.refresh_logs()
        self._set_status("info", f"🧹 {removed} خط لاگ پاک شد")
