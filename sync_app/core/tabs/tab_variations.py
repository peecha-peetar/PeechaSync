import json
import os
import shutil
import sys
import time
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QToolButton,
    QListWidget, QListWidgetItem, QMessageBox, QHBoxLayout, QTextEdit, QSplitter,
    QProgressBar, QLineEdit, QCheckBox, QFileDialog, QSizePolicy, QDialog,
    QComboBox, QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QTimer, QEvent, QPoint, QSize
from PyQt5.QtGui import QColor, QFont, QPixmap, QCursor, QGuiApplication
from sync_app.core.log_panel_ui import LogPanelController, LogActionRail
from sync_app.core.rtl_item_delegate import RightAlignedCheckableItemDelegate, make_rtl_item
from sync_app.core.product_selection import is_product_enabled, is_variation_enabled
from sync_app.core.article_price import (
    article_price_sc_id,
    load_bulk_article_variant_prices,
    resolve_article_price,
)
from sync_app.core.currency_helper import erp_price_divisor
from sync_app.core.jalali_log_formatter import format_log_lines_jalali

# اصلاح مسیر ایمپورت برای جلوگیری از خطای ModuleNotFoundError
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.sync_utils import app_path, clear_filtered_logs, log
from sync_app.core.sync_job_runner import run_background_sync, cancel_background_sync
from sync_app.core.connectivity_guard import ensure_connectivity
from sync_app.core.connectivity_wait import wait_for_connectivity_blocking, is_transient_connectivity_issue
from sync_app.core.variation_query import variation_sku_aliases
from sync_app.core.scripts import update_variations
from sync_app.core.wc_sync_helper import wp_upload_media_ex, build_wcapi, apply_network_overrides, wc_http_error_message
from sync_app.core.erp_image_helper import stage_erp_images
from sync_app.core.product_woo_map_helper import load_product_woo_map
from sync_app.core.sql_connection_helper import open_sql_connection, format_db_error
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.tab_action_controller import TabActionController, ActionSpec
from sync_app.core.compact_icon_action_bar import (
    CompactCaptionButton,
    build_compact_icon_action_bar,
)
from sync_app.core.wc_admin_links import make_wc_admin_open_button
from sync_app.core.selection_toggle_bar import attach_selection_toggle
from sync_app.core.user_guide_snippets import (
    variations_sync_button_tooltip,
    VARIATIONS_TAB_GUIDE_TEXT,
)
from sync_app.core.message_boxes_fa import ask_yes_no


# همان توکن‌ها برای نمایش و پاک‌کردن لاگ — هر تغییر در یکی باید در دیگری هم باشد.
VARIATION_LOG_TOKENS = (
    "واریانت",
    "متغیر",
    "متغیرها",
    "variation",
    "variations",
    "update_variations",
    "Poshak",
    "▸",
    "batch واریانت",
    "variations/batch",
    "/variations",
    "همگام‌سازی متغیر",
    "لیست واریانت",
    "بارگذاری لیست واریانت",
    "upsert",
    "bind attributes",
    "bind سایز",
    "سایز + رنگ",
    "تصویر واریانت",
    "انتقال تصویر",
    "media_id",
    "آپلود",
)


def _filter_variation_log_lines(lines):
    tokens = [t.lower() for t in VARIATION_LOG_TOKENS]
    return [line for line in lines if any(tok in line.lower() for tok in tokens)]


class VariationRowWidget(QWidget):
    """ردیف واریانت — آپلود تصویر + روش پردازش تصویر + حذف + تیک انتخاب (مثل محصولات/دسته‌بندی)."""

    def __init__(self, text, checked, on_toggle, on_upload, on_clear=None, on_pipeline=None, on_stock_mode_changed=None, on_delete=None, parent=None):
        super().__init__(parent)
        self._on_upload = on_upload
        self._on_clear = on_clear
        self._on_pipeline = on_pipeline
        self._on_stock_mode_changed = on_stock_mode_changed
        self._on_delete = on_delete
        self.setLayoutDirection(Qt.LeftToRight)
        row = QHBoxLayout(self)
        row.setDirection(QHBoxLayout.LeftToRight)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(6)

        self.upload_button = QPushButton("آپلود تصویر")
        self.upload_button.setStyleSheet("padding: 2px 6px; font-size: 11px; min-height: 28px;")
        self.upload_button.setFixedWidth(120)
        self.upload_button.setFixedHeight(36)
        self.upload_button.clicked.connect(self._on_upload)
        row.addWidget(self.upload_button)

        from sync_app.core.row_action_button import make_row_button, row_button_style
        self.pipeline_button = make_row_button(
            "🎨", "اجرای روش پردازش تصویر Smart Publish روی تصویر این واریانت", kind="neutral"
        )
        self.pipeline_button.clicked.connect(self._handle_pipeline)
        row.addWidget(self.pipeline_button)

        self.clear_button = make_row_button("✕", "حذف تصویر این واریانت", kind="danger", size=24)
        self.clear_button.setStyleSheet(
            row_button_style("danger") + "QToolButton { color: #b91c1c; font-weight: bold; font-size: 13px; }"
        )
        self.clear_button.clicked.connect(self._handle_clear)
        self.clear_button.hide()
        row.addWidget(self.clear_button)

        from sync_app.core.stock_mode import STOCK_MODE_LABELS
        self.stock_mode_combo = QComboBox()
        self.stock_mode_combo.setLayoutDirection(Qt.RightToLeft)
        self.stock_mode_combo.setMaximumWidth(150)
        self.stock_mode_combo.setFixedHeight(28)
        self.stock_mode_combo.setStyleSheet("font-size: 11px; padding: 1px 4px;")
        self.stock_mode_combo.setToolTip(
            "حالت موجودی این واریانت — «ارث‌بری از محصول» یعنی همون تنظیم "
            "محصول والدش (که خودش می‌تونه از دسته‌بندی ارث برده باشه) رو داشته باشه."
        )
        self.stock_mode_combo.addItem("↩️ ارث‌بری از محصول", "")
        for key, label in STOCK_MODE_LABELS.items():
            self.stock_mode_combo.addItem(label, key)
        self._stock_mode_ready = False
        self.stock_mode_combo.currentIndexChanged.connect(self._handle_stock_mode_changed)
        row.addWidget(self.stock_mode_combo)

        self.delete_button = make_row_button(
            "🗑️", "حذف این واریانت از فروشگاه (موقت/زباله‌دان یا برای همیشه)", kind="danger"
        )
        self.delete_button.clicked.connect(self._handle_delete)
        row.addWidget(self.delete_button)

        row.addStretch(1)

        self.title = QLabel(text)
        self.title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.title.setWordWrap(False)
        row.addWidget(self.title)

        self.checkbox = QCheckBox()
        self.checkbox.setLayoutDirection(Qt.RightToLeft)
        self.checkbox.setChecked(bool(checked))
        self.checkbox.toggled.connect(on_toggle)
        row.addWidget(self.checkbox)

    def _handle_clear(self):
        if callable(self._on_clear):
            self._on_clear()

    def set_stock_mode_override(self, mode: str | None):
        self._stock_mode_ready = False
        self.stock_mode_combo.blockSignals(True)
        idx = self.stock_mode_combo.findData(mode or "")
        self.stock_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.stock_mode_combo.blockSignals(False)
        self._stock_mode_ready = True

    def _handle_stock_mode_changed(self):
        if not self._stock_mode_ready:
            return
        if callable(self._on_stock_mode_changed):
            self._on_stock_mode_changed(self.stock_mode_combo.currentData() or None)

    def _handle_pipeline(self):
        if callable(self._on_pipeline):
            self._on_pipeline()

    def _handle_delete(self):
        if callable(self._on_delete):
            self._on_delete()

    def set_wc_image_count(self, count: int):
        import re
        current = self.title.text()
        current = re.sub(r"\s*\|\s*فروشگاه: \d+$", "", current)
        self.title.setText(f"{current} | فروشگاه: {count}")

    def set_image_count(self, count):
        n = int(count or 0)
        self.clear_button.setVisible(n > 0)
        if n > 0:
            label = f"آپلود تصویر ({n}) ✔" if n > 1 else "آپلود تصویر ✔"
            self.upload_button.setText(label)
            self.upload_button.setStyleSheet(
                "background-color: #166534; color: white; "
                "padding: 2px 6px; font-size: 11px; min-height: 28px;"
            )
        else:
            self.upload_button.setText("آپلود تصویر")
            self.upload_button.setStyleSheet(
                "padding: 2px 6px; font-size: 11px; min-height: 28px;"
            )


class VariationsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        # بارگذاری تنظیمات امن
        self.config = load_secure_config(None)
        self._loading_variations = False
        self._initial_empty_refresh_done = False
        self._initial_load_started = False
        self._variations_load_generation = 0
        self._refresh_button_default_text = "🔄 بروزرسانی و مشاهده لیست"
        self._sync_started_at = 0.0
        self._live_log_hint = ""
        self._all_variation_rows = []
        self._variation_images_map = self._load_variation_images_map()
        self._variation_pixmap_cache = {}
        self._current_hover_item = None
        self._show_all_db_variants = False
        self._variant_code_label = "کد متغیر"
        self.init_ui()

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(lambda: self.refresh_logs() if self.isVisible() else None)
        self.log_timer.start(2000)

        self._sync_live_timer = QTimer(self)
        self._sync_live_timer.setInterval(400)
        self._sync_live_timer.timeout.connect(self._tick_sync_ui)

    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setDirection(QHBoxLayout.LeftToRight)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setLayoutDirection(Qt.LeftToRight)
        self.splitter.setHandleWidth(6)

        # لاگ اختصاصی تب در سمت چپ - با استایل تیره مثل ترمینال
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LeftToRight)
        self.log_view.setMinimumWidth(260)
        self.splitter.addWidget(self.log_view)

        right_panel = QWidget()
        right_panel.setMinimumWidth(0)
        layout = QVBoxLayout(right_panel)

        self.log_actions = LogActionRail(clear_text="حذف لاگ‌های تب متغیرها", parent=self)

        self.workflow_guide = QLabel(VARIATIONS_TAB_GUIDE_TEXT)
        self.workflow_guide.setWordWrap(True)
        self.workflow_guide.setMinimumWidth(0)
        self.workflow_guide.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.workflow_guide.setStyleSheet(
            "color: #1e3a5f; background-color: #e0f2fe; padding: 8px 12px; "
            "border-radius: 8px; font-size: 11px; border: 1px solid #bae6fd;"
        )
        layout.addWidget(self.workflow_guide)

        self.status_label = QLabel("✓ آماده — برای بارگذاری دکمه بروزرسانی را بزنید")
        self._set_variations_status("ready", self.status_label.text())
        layout.addWidget(self.status_label)

        self.load_progress = QProgressBar()
        self.load_progress.setRange(0, 0)
        self.load_progress.setTextVisible(False)
        self.load_progress.setFixedHeight(8)
        self.load_progress.setVisible(False)
        layout.addWidget(self.load_progress)

        self.sync_progress = QProgressBar()
        self.sync_progress.setRange(0, 100)
        self.sync_progress.setValue(0)
        self.sync_progress.setFormat("%p% — همگام‌سازی")
        self.sync_progress.setTextVisible(True)
        self.sync_progress.setFixedHeight(22)
        self.sync_progress.setVisible(False)
        layout.addWidget(self.sync_progress)

        self.sync_detail_label = QLabel("")
        self.sync_detail_label.setWordWrap(True)
        self.sync_detail_label.setStyleSheet(
            "color: #1e3a8a; font-size: 11px; padding: 2px 4px;"
        )
        self.sync_detail_label.setVisible(False)
        layout.addWidget(self.sync_detail_label)

        self.price_label = QLabel(
            "📋 لیست واریانت‌ها (فیلتر: دسته‌بندی + محصولات تیک‌خورده در تب محصولات)"
        )
        self.price_label.setStyleSheet("font-weight: bold;")
        self.price_label.setWordWrap(True)
        self.price_label.setMinimumWidth(0)
        self.price_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.price_label)

        self.show_all_variants_cb = QCheckBox("نمایش همه واریانت‌های دیتابیس")
        self.show_all_variants_cb.setToolTip(
            "واریانت‌های محصولاتی که در تب محصولات تیک نخورده‌اند هم نمایش داده می‌شوند؛ "
            "فقط جهت مشاهده هستند و در همگام‌سازی استفاده نمی‌شوند."
        )
        self.show_all_variants_cb.toggled.connect(self._on_show_all_variants_toggled)
        layout.addWidget(self.show_all_variants_cb)

        self.display_only_hint = QLabel("")
        self.display_only_hint.setWordWrap(True)
        self.display_only_hint.setStyleSheet(
            "color: #92400e; background-color: #fef3c7; padding: 6px 10px; "
            "border-radius: 6px; font-size: 11px;"
        )
        self.display_only_hint.setVisible(False)
        layout.addWidget(self.display_only_hint)

        variation_search_row = QHBoxLayout()
        variation_search_row.setSpacing(8)
        self.variation_search = QLineEdit()
        self.variation_search.setPlaceholderText("🔍 جستجو در متغیرها (نام محصول، کد، واریانت، ویژگی)...")
        self.variation_search.setLayoutDirection(Qt.RightToLeft)
        self.variation_search.setMinimumHeight(36)
        self.variation_search.textChanged.connect(self._filter_variations)
        variation_search_row.addWidget(self.variation_search, 1)

        self.variation_link_filter = QComboBox()
        self.variation_link_filter.addItem("همه", "all")
        self.variation_link_filter.addItem("✅ فقط محصول والدشان لینک است", "linked")
        self.variation_link_filter.addItem("⭕ فقط محصول والدشان لینک نیست", "unlinked")
        self.variation_link_filter.setMinimumHeight(36)
        self.variation_link_filter.currentIndexChanged.connect(
            lambda _=0: self._filter_variations(self.variation_search.text())
        )
        variation_search_row.addWidget(self.variation_link_filter)

        self._variation_selection_toggle = attach_selection_toggle(
            variation_search_row,
            self,
            on_select_all=lambda: self._set_all_variations_checked(True),
            on_select_none=lambda: self._set_all_variations_checked(False),
        )
        layout.addLayout(variation_search_row)

        self.variation_list = QListWidget()
        self.variation_list.setLayoutDirection(Qt.RightToLeft)
        self.variation_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.variation_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.variation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.variation_list.setItemDelegate(RightAlignedCheckableItemDelegate(self.variation_list))
        self.variation_list.setMouseTracking(True)
        self.variation_list.itemEntered.connect(self._on_variation_hover)
        self.variation_list.viewport().installEventFilter(self)
        self.variation_list.itemChanged.connect(self._on_variation_item_changed)
        self.variation_list.setStyleSheet("font-size: 11pt; padding: 5px;")
        layout.addWidget(self.variation_list, 1)

        self.image_preview = QLabel(None)
        self.image_preview.setWindowFlags(Qt.ToolTip)
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setStyleSheet(
            "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px;"
            "padding: 4px;"
        )
        self.image_preview.setVisible(False)

        self._sync_button_idle_text = "📤 همگام‌سازی واریانت‌ها"
        self._sync_button_stop_text = "⏹ توقف همگام‌سازی"

        self.refresh_button = CompactCaptionButton(self._refresh_button_default_text)
        self.refresh_button.clicked.connect(self._on_refresh_clicked)

        self.sync_button = CompactCaptionButton(self._sync_button_idle_text)
        self.sync_button.setToolTip(variations_sync_button_tooltip(self.config))
        self.sync_button.clicked.connect(self._on_sync_clicked)

        self.var_pick_image_btn = CompactCaptionButton("📷 انتخاب تصویر واریانت")
        self.var_pick_image_btn.setToolTip(
            "یک تصویر برای همه واریانت‌های تیک‌خورده — یا از «آپلود تصویر» در هر ردیف"
        )
        self.var_pick_image_btn.clicked.connect(self._pick_images_for_checked_variations)

        self.var_edit_image_btn = CompactCaptionButton("✏️ ویرایش تصویر واریانت")
        self.var_edit_image_btn.setToolTip("تعویض یا مدیریت تصاویر انتخاب‌شده واریانت‌های تیک‌خورده")
        self.var_edit_image_btn.clicked.connect(self._edit_images_for_checked_variations)

        self.var_remove_image_btn = CompactCaptionButton("🗑 حذف تصویر واریانت")
        self.var_remove_image_btn.setToolTip("حذف تصاویر انتخاب‌شده از حافظه محلی (و در صورت تأیید، از فروشگاه)")
        self.var_remove_image_btn.clicked.connect(self._remove_images_for_checked_variations)

        self._var_images_idle_text = "📤 انتقال تصاویر واریانت"
        self._var_images_idle_style = (
            "QPushButton { background-color: #1e40af; color: white; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
            "QPushButton:disabled { background-color: #666; }"
        )
        self._var_images_stop_style = (
            "QPushButton { background-color: #b45309; color: white; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background-color: #d97706; }"
        )
        self.var_send_image_btn = CompactCaptionButton(self._var_images_idle_text)
        self.var_send_image_btn.setProperty("compactActionRole", "upload")
        self.var_send_image_btn.setToolTip("ارسال تصاویر انتخاب‌شده واریانت‌ها به فروشگاه")
        self.var_send_image_btn.clicked.connect(self._on_send_variation_images_clicked)

        self.wc_admin_button = make_wc_admin_open_button(
            self,
            "variations",
            button_factory=CompactCaptionButton,
        )

        self.check_wc_images_button = CompactCaptionButton("🖼️ بررسی تعداد تصویر فروشگاه")
        self.check_wc_images_button.setToolTip(
            "برای هر محصولِ والدِ نمایش‌داده‌شده، لیست واریانت‌هاش رو از فروشگاه "
            "می‌گیره و تعداد تصویر هر واریانت رو کنارش نشون می‌ده."
        )
        self.check_wc_images_button.clicked.connect(self._check_wc_variation_image_counts)
        self._wc_image_count_cache = {}

        self._action_ops = TabActionController(self)
        self._action_ops.register(
            "refresh",
            ActionSpec(
                button=self.refresh_button,
                idle_text=self._refresh_button_default_text,
                stop_text="⏹ توقف بارگذاری",
                on_stop=self._stop_variations_load,
            ),
        )
        self._action_ops.register(
            "sync",
            ActionSpec(
                button=self.sync_button,
                idle_text=self._sync_button_idle_text,
                stop_style=(
                    "QPushButton { background-color: #b91c1c; color: #ffffff; font-weight: bold; border-radius: 6px; }"
                    "QPushButton:hover { background-color: #991b1b; }"
                ),
                on_stop=self.stop_variations_sync,
            ),
        )
        self._action_ops.register(
            "var_images",
            ActionSpec(
                button=self.var_send_image_btn,
                idle_text=self._var_images_idle_text,
                idle_style=self._var_images_idle_style,
                stop_style=self._var_images_stop_style,
                on_stop=self._stop_variation_images_upload,
            ),
        )
        self._action_ops.register_extra_widgets(
            self.variation_search,
            self.show_all_variants_cb,
            self.variation_list,
            self._variation_selection_toggle,
            self.var_pick_image_btn,
            self.var_edit_image_btn,
            self.var_remove_image_btn,
        )

        layout.addWidget(
            build_compact_icon_action_bar(
                [
                    self.refresh_button,
                    self.sync_button,
                    self.var_pick_image_btn,
                    self.var_edit_image_btn,
                    self.var_remove_image_btn,
                    self.var_send_image_btn,
                    self.check_wc_images_button,
                    self.wc_admin_button,
                ],
                parent=right_panel,
            )
        )

        right_panel.setLayoutDirection(Qt.RightToLeft)
        self.splitter.addWidget(right_panel)
        self.log_panel_controller = LogPanelController(
            splitter=self.splitter,
            button=self.log_actions.toggle_button,
            open_size=380,
            duration_ms=160,
            log_widget=self.log_view,
            storage_key="variations",
            parent=self
        )
        self.log_actions.bind_toggle(self.log_panel_controller.toggle)
        self.log_actions.bind_clear(self.clear_tab_logs)
        self.log_panel_controller.collapse_initial()  # پیش‌فرض: لاگ مخفی — با دکمه‌ی کناری نمایش داده می‌شود

        main_layout.addWidget(self.splitter, 1)
        main_layout.addWidget(self.log_actions)

        self.setLayout(main_layout)
        self.refresh_logs()

    def ensure_tab_data_loaded(self):
        from sync_app.core.tab_operation_guard import consume_pending_sql_reload

        consume_pending_sql_reload(
            self,
            lambda: self.load_variations(silent=False, manual=False),
        )

    def showEvent(self, event):
        super().showEvent(event)
        if self._loading_variations:
            return
        config = load_secure_config(None) or {}
        groups = [str(g).strip() for g in config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()]
        if not groups:
            return
        products_changed = config.get("DISABLED_PRODUCT_SKUS") != self.config.get("DISABLED_PRODUCT_SKUS")
        if products_changed:
            self.config = config
            self.load_variations(silent=True, manual=False)
            return
        if self.variation_list.count() == 0 or (
            self.variation_list.count() == 1
            and (self.variation_list.item(0).text() or "").startswith("⚠️")
        ):
            self.load_variations(silent=True, manual=False)

    def _set_variations_status(self, state, text):
        styles = {
            "ready": ("#dcfce7", "#16a34a"),
            "loading": ("#fef3c7", "#92400e"),
            "success": ("#dcfce7", "#16a34a"),
            "warning": ("#fef3c7", "#92400e"),
            "error": ("#fee2e2", "#b91c1c"),
            "info": ("#dbeafe", "#1d4ed8"),
        }
        bg, fg = styles.get(state, styles["ready"])
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"background-color: {bg}; color: {fg}; padding: 8px 12px; "
            "border-radius: 6px; font-weight: bold; font-size: 12px;"
        )

    def _begin_variations_load(self, manual=False):
        self._loading_variations = True
        self.load_progress.setVisible(True)
        self._action_ops.begin("refresh", lock_tabs=False)
        self._set_variations_status("loading", "⏳ در حال دریافت واریانت‌ها از SQL...")
        if manual:
            log.info("🔄 کاربر: بروزرسانی لیست واریانت‌ها آغاز شد.")

    def _end_variations_load(self):
        self._loading_variations = False
        self.load_progress.setVisible(False)
        if self._action_ops.active == "refresh":
            self._action_ops.end()

    def _stop_variations_load(self):
        self._variations_load_generation += 1
        self._loading_variations = False
        self.load_progress.setVisible(False)
        self._set_variations_status("warning", "⏹ بارگذاری واریانت‌ها متوقف شد.")
        if self._action_ops.active == "refresh":
            self._action_ops.end()

    def _on_refresh_clicked(self):
        self._action_ops.handle_click(
            "refresh",
            lambda: self.load_variations(silent=False, manual=True),
        )

    def _on_sync_clicked(self):
        self._action_ops.handle_click("sync", self.send_variations)

    def _on_show_all_variants_toggled(self, checked: bool):
        self._show_all_db_variants = bool(checked)
        self.display_only_hint.setVisible(bool(checked))
        if checked:
            self.display_only_hint.setText(
                "⚠️ بخش «فقط نمایش» مربوط به محصولاتی است که در تب محصولات انتخاب نشده‌اند. "
                "روی آن‌ها هیچ عملیاتی انجام نمی‌شود و صرفاً برای مقایسه با دیتابیس است."
            )
        self._render_variation_list(self._all_variation_rows)

    def _fetch_variations_from_sql(self, config, selected_groups):
        from sync_app.core.variation_query import fetch_variation_list_rows
        from sync_app.core.variation_rules import fetch_variant_code_label, parse_list_row_for_ui

        conn, _, _ = open_sql_connection(config, timeout=3)
        cursor = conn.cursor()
        self._variant_code_label = fetch_variant_code_label(conn)
        from sync_app.core.article_price import article_price_sale_list_id
        sc_id = article_price_sc_id(config)
        sale_sc_id = article_price_sale_list_id(config)
        price_div = erp_price_divisor(config)
        price_col = (config.get("PRICE_LIST_COLUMN") or "Sel_Price").strip()
        is_toman = bool(config.get("WC_CURRENCY_IS_TOMAN"))
        display_div = price_div * (10.0 if is_toman else 1.0)

        article_prices: dict[str, float] = {}
        cursor.execute(
            "SELECT A_Code, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5 "
            "FROM Article WHERE LEN(A_Code) >= 4"
        )
        for art_row in cursor.fetchall():
            code = str(art_row[0] or "").strip()
            if code:
                article_prices[code] = resolve_article_price(art_row, price_col)

        def _row_sku(r):
            # ردیف می‌تواند dict (مدل چندسطحی) یا tuple (مسیر قدیمی) باشد
            if isinstance(r, dict):
                return str(r.get("a_code") or r.get("sku") or "").strip()
            return str((r[0] if r else "") or "").strip()

        candidate_rows = []
        candidate_skus: set[str] = set()
        for row in fetch_variation_list_rows(cursor):
            sku = _row_sku(row)
            if not sku or not any(sku.startswith(g) for g in selected_groups):
                continue
            candidate_rows.append(row)
            candidate_skus.add(sku)

        price_cache = load_bulk_article_variant_prices(cursor, sorted(candidate_skus), sc_id=sc_id)
        if sc_id != 1:
            missing = [sku for sku in candidate_skus if not price_cache.get(sku)]
            if missing:
                fallback = load_bulk_article_variant_prices(cursor, missing, sc_id=1)
                for code, prices in fallback.items():
                    price_cache.setdefault(code, {}).update(prices)

        sale_cache: dict[str, dict[int, float]] = {}
        if sale_sc_id and sale_sc_id != sc_id:
            sale_cache = load_bulk_article_variant_prices(cursor, sorted(candidate_skus), sc_id=sale_sc_id)

        rows = []
        for row in candidate_rows:
            sku = _row_sku(row)
            parsed = parse_list_row_for_ui(
                row,
                variant_code_label=self._variant_code_label,
                price_by_poshak_id=price_cache.get(sku),
                sale_price_by_poshak_id=sale_cache.get(sku),
                base_price=article_prices.get(sku, 0.0),
                price_divisor=display_div,
            )
            if not parsed:
                continue
            parsed["product_enabled"] = is_product_enabled(sku, config)
            rows.append(parsed)
        conn.close()
        rows.sort(key=lambda r: (r.get("name") or "", r.get("sku") or "", r.get("variant_sku") or ""))
        return rows

    def load_variations(self, silent=False, manual=False):
        """بارگذاری لیست واریانت‌ها با منطق کوئری فایل سالم شما"""
        if manual and not ensure_connectivity(self, need_sql=True, need_wc=False):
            return

        if self._loading_variations or self._action_ops.busy:
            return

        self.config = load_secure_config(None)
        selected_groups = [str(g).strip() for g in self.config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()]

        if not selected_groups:
            self.variation_list.clear()
            self.variation_list.addItem(make_rtl_item("⚠️ هیچ گروهی در تب دسته‌بندی انتخاب نشده است."))
            self._set_variations_status(
                "warning",
                "⚠️ هیچ گروهی انتخاب نشده — ابتدا در تب دسته‌بندی‌ها گروه را تیک بزنید.",
            )
            if manual:
                QMessageBox.warning(
                    self,
                    "گروه انتخاب نشده",
                    "هیچ گروهی برای فیلتر واریانت‌ها انتخاب نشده است.\n"
                    "لطفاً در تب «دسته‌بندی‌ها» زیرگروه موردنظر را تیک بزنید.",
                )
            return

        self._variations_load_generation += 1
        generation = self._variations_load_generation
        if not silent:
            self.variation_list.clear()
            self.variation_list.addItem(make_rtl_item("⏳ در حال بارگذاری واریانت‌ها از SQL..."))
        self._begin_variations_load(manual=manual)

        def _worker():
            return self._fetch_variations_from_sql(self.config, selected_groups)

        def _done(rows):
            if generation != self._variations_load_generation:
                return
            self._all_variation_rows = list(rows or [])
            self._render_variation_list(self._all_variation_rows, selected_groups)
            row_count = len(self._all_variation_rows)
            if manual and row_count > 0:
                log.info(f"✅ بروزرسانی لیست واریانت‌ها: {row_count} مورد بارگذاری شد.")
            self._end_variations_load()
            if manual:
                if row_count == 0:
                    QMessageBox.information(
                        self,
                        "نتیجه بروزرسانی",
                        "برای گروه‌های انتخاب‌شده واریانتی در دیتابیس یافت نشد.",
                    )
                else:
                    from sync_app.core.integrations.erp_provider import erp_provider_label

                    QMessageBox.information(
                        self,
                        "بروزرسانی موفق",
                        f"{row_count} واریانت از {erp_provider_label(self.config)} بارگذاری شد.",
                    )

        def _fail(error_msg):
            if generation != self._variations_load_generation:
                return
            err = format_db_error(Exception(str(error_msg)))
            self.variation_list.clear()
            self.variation_list.addItem(make_rtl_item(f"❌ خطا در استخراج داده‌ها: {err[:300]}"))
            self._set_variations_status("error", f"❌ خطا در بارگذاری واریانت‌ها: {err[:120]}")
            log.error(f"❌ خطا در بارگذاری لیست واریانت‌ها: {err}")
            self._end_variations_load()
            if manual:
                QMessageBox.critical(self, "خطای دیتابیس", f"خطا در استخراج داده‌ها:\n{err}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _format_variation_display(self, row: dict) -> str:
        full_path = row.get("full_path") or row.get("name", "")
        stock = row.get("stock", 0)
        price = float(row.get("price") or 0)
        sale = float(row.get("sale_price") or 0)
        price_part = f"قیمت: {price:,.0f}" if price > 0 else "قیمت: —"
        sale_part = f" | قیمت ویژه: {sale:,.0f}" if sale > 0 else ""
        return f"{full_path} | موجودی: {stock} | {price_part}{sale_part}"

    def _append_variation_section(
        self,
        rows: list[dict],
        *,
        section_kind: str,
        disabled: set[str],
    ):
        product_map = load_product_woo_map()
        last_product = None
        for row in rows:
            product_key = row.get("sku")
            is_parent_linked = product_key in product_map
            if product_key != last_product:
                link_mark = "✅ " if is_parent_linked else "⭕ "
                header = QListWidgetItem(f"━━━ {link_mark}{row.get('name', '')} ({product_key}) ━━━")
                header.setFlags(Qt.ItemIsEnabled)
                header.setData(Qt.UserRole, "")
                header.setData(Qt.UserRole + 1, "header")
                header.setData(Qt.UserRole + 2, section_kind)
                header.setData(Qt.UserRole + 8, is_parent_linked)
                header.setForeground(QColor("#1d4ed8"))
                font = QFont()
                font.setBold(True)
                header.setFont(font)
                self.variation_list.addItem(header)
                last_product = product_key

            variant_sku = str(row.get("variant_sku") or "")
            display = self._format_variation_display(row)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, variant_sku)
            item.setData(Qt.UserRole + 1, section_kind)
            item.setData(Qt.UserRole + 2, product_key)
            item.setData(Qt.UserRole + 6, display.lower())
            item.setData(Qt.UserRole + 7, display)
            item.setData(Qt.UserRole + 8, is_parent_linked)
            if section_kind == "display_only":
                item.setText(display)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setForeground(QColor("#6b7280"))
                self.variation_list.addItem(item)
            else:
                checked = variant_sku not in disabled
                row_widget = VariationRowWidget(
                    display,
                    checked,
                    on_toggle=lambda c, s=variant_sku: self._on_variation_toggle_by_sku(s, c),
                    on_upload=lambda _=False, s=variant_sku, it=item: self._upload_images_for_variation(
                        s, it
                    ),
                    on_clear=lambda s=variant_sku, it=item: self._clear_images_for_variation(s, it),
                    on_pipeline=lambda s=variant_sku, it=item: self._open_variation_pipeline_dialog(s, it),
                    on_stock_mode_changed=lambda mode, s=variant_sku: self._set_variation_stock_mode(s, mode),
                    on_delete=lambda s=variant_sku, pk=product_key, d=display: self._delete_variation_from_wc(pk, s, d),
                    parent=self.variation_list,
                )
                from sync_app.core.stock_mode import get_variation_stock_mode_override
                row_widget.set_stock_mode_override(get_variation_stock_mode_override(self.config, variant_sku))
                row_widget.set_image_count(len(self._picked_image_paths(variant_sku)))
                item.setSizeHint(QSize(0, 52))
                self.variation_list.addItem(item)
                self.variation_list.setItemWidget(item, row_widget)

    def _render_variation_list(self, rows, selected_groups=None):
        self.variation_list.blockSignals(True)
        self.variation_list.clear()
        disabled = set(self.config.get("DISABLED_VARIATION_SKUS", []) or [])
        all_rows = list(rows or [])
        operational_rows = [r for r in all_rows if r.get("product_enabled", True)]
        display_only_rows = [r for r in all_rows if not r.get("product_enabled", True)]

        if not operational_rows and not (self._show_all_db_variants and display_only_rows):
            self.variation_list.addItem(make_rtl_item("⚠️ هیچ واریانتی برای فیلتر فعلی یافت نشد."))
            groups = selected_groups or [
                str(g).strip() for g in self.config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()
            ]
            if groups:
                self._set_variations_status(
                    "info",
                    "ℹ️ واریانتی برای گروه/محصول انتخاب‌شده یافت نشد.",
                )
            log.info("ℹ️ بروزرسانی لیست واریانت‌ها: موردی یافت نشد.")
        else:
            if operational_rows:
                self._append_variation_section(
                    operational_rows,
                    section_kind="variant",
                    disabled=disabled,
                )

            if self._show_all_db_variants and display_only_rows:
                divider = QListWidgetItem(
                    "━━━ ⚠️ فقط نمایش — محصولات بدون تیک در تب محصولات ━━━"
                )
                divider.setFlags(Qt.ItemIsEnabled)
                divider.setData(Qt.UserRole, "")
                divider.setData(Qt.UserRole + 1, "section_notice")
                divider.setForeground(QColor("#b45309"))
                font = QFont()
                font.setBold(True)
                divider.setFont(font)
                self.variation_list.addItem(divider)
                self._append_variation_section(
                    display_only_rows,
                    section_kind="display_only",
                    disabled=disabled,
                )

            groups = selected_groups or [
                str(g).strip() for g in self.config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()
            ]
            groups_text = "، ".join(groups)
            product_count = len({r.get("sku") for r in operational_rows})
            status_parts = [
                f"{len(operational_rows)} واریانت عملیاتی از {product_count} محصول"
            ]
            if self._show_all_db_variants and display_only_rows:
                status_parts.append(f"{len(display_only_rows)} فقط نمایش")
            self._set_variations_status(
                "success",
                f"✅ {' | '.join(status_parts)} (گروه‌ها: {groups_text})",
            )
        self.variation_list.blockSignals(False)
        self._filter_variations(self.variation_search.text())

    def _filter_variations(self, text):
        search = (text or "").strip().lower()
        link_mode = self.variation_link_filter.currentData() if hasattr(self, "variation_link_filter") else "all"
        active_filter = bool(search) or link_mode != "all"
        row_kinds = {"variant", "display_only"}

        def _link_ok(item):
            if link_mode == "all":
                return True
            is_linked = bool(item.data(Qt.UserRole + 8))
            return is_linked if link_mode == "linked" else not is_linked

        for i in range(self.variation_list.count()):
            item = self.variation_list.item(i)
            kind = item.data(Qt.UserRole + 1)
            if kind in ("header", "section_notice"):
                item.setHidden(False)
                continue
            hay = (item.data(Qt.UserRole + 6) or item.text() or "").lower()
            text_ok = not search or search in hay
            item.setHidden(not (text_ok and _link_ok(item)))

        visible_headers = set()
        for i in range(self.variation_list.count()):
            item = self.variation_list.item(i)
            if item.data(Qt.UserRole + 1) not in row_kinds or item.isHidden():
                continue
            parent_sku = ""
            for j in range(i - 1, -1, -1):
                prev = self.variation_list.item(j)
                if prev.data(Qt.UserRole + 1) == "header":
                    parent_sku = prev.text()
                    break
            if parent_sku:
                visible_headers.add(parent_sku)
        for i in range(self.variation_list.count()):
            item = self.variation_list.item(i)
            if item.data(Qt.UserRole + 1) == "header":
                item.setHidden(item.text() not in visible_headers and active_filter)
            elif item.data(Qt.UserRole + 1) == "section_notice":
                has_visible_display = False
                for j in range(i + 1, self.variation_list.count()):
                    next_item = self.variation_list.item(j)
                    next_kind = next_item.data(Qt.UserRole + 1)
                    if next_kind == "section_notice":
                        break
                    if next_kind == "display_only" and not next_item.isHidden():
                        has_visible_display = True
                        break
                item.setHidden(active_filter and not has_visible_display)

    def _set_all_variations_checked(self, checked: bool):
        self.variation_list.blockSignals(True)
        for i in range(self.variation_list.count()):
            item = self.variation_list.item(i)
            if item.data(Qt.UserRole + 1) != "variant" or item.isHidden():
                continue
            widget = self.variation_list.itemWidget(item)
            if isinstance(widget, VariationRowWidget):
                widget.checkbox.setChecked(checked)
        self.variation_list.blockSignals(False)
        self._persist_variation_selection()

    def _on_variation_item_changed(self, item):
        if self._loading_variations:
            return
        if item.data(Qt.UserRole + 1) != "variant":
            return
        self._persist_variation_selection()

    def _variation_item_checked(self, item) -> bool:
        widget = self.variation_list.itemWidget(item)
        if isinstance(widget, VariationRowWidget):
            return widget.checkbox.isChecked()
        return item.checkState() == Qt.Checked

    def _check_wc_variation_image_counts(self):
        self.check_wc_images_button.setEnabled(False)
        self.check_wc_images_button.setText("⏳ در حال دریافت از فروشگاه...")
        config = load_secure_config(None) or {}
        product_map = load_product_woo_map()

        # SKU محصول والدِ هرکدوم از واریانت‌های نمایش‌داده‌شده — چون endpoint
        # واریانت‌های فروشگاه زیرمجموعه‌ی هر محصوله، نه یه لیست تخت مشترک.
        parent_skus = set()
        for i in range(self.variation_list.count()):
            item = self.variation_list.item(i)
            parent_sku = item.data(Qt.UserRole + 2)
            if parent_sku:
                parent_skus.add(str(parent_sku))

        def _worker():
            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            counts: dict[str, int] = {}
            for parent_sku in parent_skus:
                wc_id = product_map.get(parent_sku)
                if not wc_id:
                    continue
                try:
                    resp = wcapi.get(
                        f"products/{int(wc_id)}/variations",
                        params={"per_page": 100, "_fields": "sku,image"},
                    )
                    if int(getattr(resp, "status_code", 0) or 0) >= 400:
                        continue
                    for v in resp.json() or []:
                        sku = str(v.get("sku") or "").strip()
                        if sku:
                            counts[sku] = 1 if v.get("image") else 0
                except Exception:
                    continue
            return counts

        def _done(counts):
            self._wc_image_count_cache.update(counts)
            self.check_wc_images_button.setEnabled(True)
            self.check_wc_images_button.setText("🖼️ بررسی تعداد تصویر فروشگاه")
            for i in range(self.variation_list.count()):
                item = self.variation_list.item(i)
                sku = str(item.data(Qt.UserRole) or "").strip()
                if sku not in self._wc_image_count_cache:
                    continue
                row_widget = self.variation_list.itemWidget(item)
                if isinstance(row_widget, VariationRowWidget):
                    row_widget.set_wc_image_count(self._wc_image_count_cache[sku])
            QMessageBox.information(
                self, "انجام شد", f"تعداد تصویر {len(counts)} واریانت از فروشگاه دریافت شد."
            )

        def _fail(msg):
            self.check_wc_images_button.setEnabled(True)
            self.check_wc_images_button.setText("🖼️ بررسی تعداد تصویر فروشگاه")
            QMessageBox.critical(self, "خطا", f"دریافت تعداد تصویر ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _delete_variation_from_wc(self, parent_sku, variant_sku, display_name=""):
        from sync_app.core.integrations.commerce_provider import (
            is_prestashop, store_platform_label,
        )

        config = load_secure_config(None) or {}
        ps_mode = is_prestashop(config)
        product_map = load_product_woo_map()
        parent_wc_id = product_map.get(parent_sku)
        if not parent_wc_id:
            QMessageBox.information(
                self, "لینک نشده",
                f"محصول والدِ {variant_sku} (کد {parent_sku}) اصلاً به "
                f"{store_platform_label(config)} لینک نشده.",
            )
            return

        if ps_mode:
            confirmed = ask_yes_no(
                self, "حذف واریانت از پرستاشاپ",
                f"واریانت «{display_name or variant_sku}» برای همیشه از پرستاشاپ پاک بشه؟\n"
                "هیچ راه بازگردانی‌ای نداره.",
                icon=QMessageBox.Warning,
            )
            if not confirmed:
                return
            force = True
        else:
            box = QMessageBox(self)
            box.setWindowTitle("حذف واریانت از فروشگاه")
            box.setText(
                f"واریانت «{display_name or variant_sku}» از سایت حذف بشه؟\n\n"
                "🗑️ زباله‌دان: قابل بازیابی از پنل وردپرس تا وقتی خودتون خالی‌اش کنید.\n"
                "⚠️ حذف کامل: برای همیشه پاک می‌شه، هیچ راه بازگشتی نداره."
            )
            trash_btn = box.addButton("🗑️ انتقال به زباله‌دان", QMessageBox.ActionRole)
            perm_btn = box.addButton("⚠️ حذف کامل و همیشگی", QMessageBox.DestructiveRole)
            box.addButton("انصراف", QMessageBox.RejectRole)
            box.setIcon(QMessageBox.Warning)
            box.exec_()
            clicked = box.clickedButton()
            if clicked not in (trash_btn, perm_btn):
                return
            force = clicked is perm_btn

            if force:
                confirm2 = ask_yes_no(
                    self, "تأیید نهایی حذف کامل",
                    f"مطمئنید؟ واریانت «{display_name or variant_sku}» برای همیشه پاک می‌شه.",
                    icon=QMessageBox.Warning,
                )
                if not confirm2:
                    return

        def _worker():
            if ps_mode:
                from sync_app.core.ps_variation_helper import (
                    ps_delete_combination, ps_list_combinations,
                )

                combos = ps_list_combinations(config, int(parent_wc_id))
                match = next((c for c in combos if c.get("reference") == variant_sku), None)
                if not match:
                    raise RuntimeError("این واریانت روی پرستاشاپ پیدا نشد (شاید قبلاً حذف شده).")
                ps_delete_combination(config, int(match["id"]))
                return {"id": match["id"], "deleted": True}

            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            resp = wcapi.get(f"products/{int(parent_wc_id)}/variations", params={"sku": variant_sku})
            if int(getattr(resp, "status_code", 0) or 0) >= 400:
                raise RuntimeError(wc_http_error_message(resp))
            found = resp.json()
            if not isinstance(found, list) or not found:
                raise RuntimeError("این واریانت روی فروشگاه پیدا نشد (شاید قبلاً حذف شده).")
            variation_id = found[0]["id"]
            del_resp = wcapi.delete(
                f"products/{int(parent_wc_id)}/variations/{variation_id}", params={"force": force}
            )
            if int(getattr(del_resp, "status_code", 0) or 0) >= 400:
                raise RuntimeError(wc_http_error_message(del_resp))
            return del_resp.json()

        def _done(_data):
            msg = "برای همیشه حذف شد" if force else "به زباله‌دان منتقل شد"
            QMessageBox.information(self, "انجام شد", f"واریانت {variant_sku} {msg}.")
            self.load_variations(manual=False)

        def _fail(err_msg):
            QMessageBox.critical(self, "خطا در حذف", f"حذف واریانت {variant_sku} ناموفق بود:\n{err_msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _set_variation_stock_mode(self, variant_sku, mode):
        from sync_app.core.stock_mode import set_variation_stock_mode_override
        set_variation_stock_mode_override(variant_sku, mode)
        self.config = load_secure_config(None) or {}

    def _on_variation_toggle_by_sku(self, sku, checked):
        if self._loading_variations or not sku:
            return
        cfg = load_secure_config(None) or {}
        disabled = set(cfg.get("DISABLED_VARIATION_SKUS", []) or [])
        if checked:
            disabled.discard(sku)
        else:
            disabled.add(sku)
        cfg["DISABLED_VARIATION_SKUS"] = sorted(disabled)
        from sync_app.core.secure_config_loader import save_secure_config
        save_secure_config(cfg)
        self.config = cfg

    def _persist_variation_selection(self):
        disabled = set()
        for i in range(self.variation_list.count()):
            item = self.variation_list.item(i)
            if item.data(Qt.UserRole + 1) != "variant":
                continue
            sku = str(item.data(Qt.UserRole) or "").strip()
            if sku and not self._variation_item_checked(item):
                disabled.add(sku)
        cfg = load_secure_config(None) or {}
        cfg["DISABLED_VARIATION_SKUS"] = sorted(disabled)
        from sync_app.core.secure_config_loader import save_secure_config
        save_secure_config(cfg)
        self.config = cfg

    def clear_tab_logs(self):
        removed = clear_filtered_logs(VARIATION_LOG_TOKENS)
        self.refresh_logs()
        QMessageBox.information(self, "انجام شد", f"{removed} خط لاگ مربوط به تب متغیرها پاک شد.")

    def _variation_images_manifest(self):
        return app_path("variation_images_map.json")

    def _load_variation_images_map(self):
        path = self._variation_images_manifest()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {str(k): list(v) for k, v in data.items() if isinstance(v, list)}
        except Exception:
            pass
        return {}

    def _save_variation_images_map(self):
        with open(self._variation_images_manifest(), "w", encoding="utf-8") as f:
            json.dump(self._variation_images_map, f, ensure_ascii=False, indent=2)

    def _variation_map_keys(self, variant_sku: str) -> list[str]:
        from sync_app.core.variation_query import variation_skus_match

        return [
            key
            for key in (self._variation_images_map or {})
            if variation_skus_match(str(key), variant_sku)
        ]

    def _primary_map_key(self, variant_sku: str) -> str:
        keys = self._variation_map_keys(variant_sku)
        return keys[0] if keys else str(variant_sku)

    def _abs_path_for_rel(self, rel: str) -> str:
        return rel if os.path.isabs(rel) else app_path(rel)

    def _delete_image_files(self, rel_paths: list[str]):
        for rel in rel_paths or []:
            try:
                path = self._abs_path_for_rel(rel)
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass

    def _remove_picked_images_for_skus(self, skus: list[str]) -> int:
        removed = 0
        touched_keys: set[str] = set()
        for vsku in skus:
            for key in self._variation_map_keys(vsku):
                if key in touched_keys:
                    continue
                touched_keys.add(key)
                rels = list(self._variation_images_map.pop(key, []))
                if rels:
                    removed += len(rels)
                    self._delete_image_files(rels)
        if removed:
            self._variation_pixmap_cache.clear()
            self._save_variation_images_map()
        return removed

    def _refresh_variation_labels_for_skus(self, skus: set[str]):
        for i in range(self.variation_list.count()):
            item = self.variation_list.item(i)
            if item.data(Qt.UserRole + 1) != "variant":
                continue
            sku = str(item.data(Qt.UserRole) or "").strip()
            if sku not in skus:
                continue
            count = len(self._picked_image_paths(sku))
            widget = self.variation_list.itemWidget(item)
            if isinstance(widget, VariationRowWidget):
                widget.set_image_count(count)
                continue
            base = str(item.data(Qt.UserRole + 7) or item.text() or "").strip()
            display = base
            item.setText(display)
            item.setData(Qt.UserRole + 6, display.lower())

    def _upload_images_for_variation(self, vsku, item):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            f"انتخاب تصویر برای واریانت {vsku}",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not files:
            return
        if not self._copy_images_to_skus([vsku], files, replace=False):
            return
        widget = self.variation_list.itemWidget(item)
        if isinstance(widget, VariationRowWidget):
            widget.set_image_count(len(self._picked_image_paths(vsku)))

    def _clear_images_for_variation(self, vsku, item):
        if not self._picked_image_paths(vsku):
            return
        confirm = QMessageBox.question(
            self,
            "حذف تصویر",
            f"تصویر(های) انتخاب‌شده واریانت {vsku} حذف شود؟\n"
            "(تصویر روی سایت فروشگاه تا زمان «انتقال» تغییری نمی‌کند.)",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._remove_picked_images_for_skus([vsku])
        self._refresh_variation_labels_for_skus({vsku})

    def _open_variation_pipeline_dialog(self, vsku, item):
        """
        اجرای روش پردازش تصویر Smart Publish روی تصویرِ محلیِ آماده‌شده‌ی این واریانت.
        برخلاف محصولات، اینجا هیچ تماس زنده‌ای با فروشگاه گرفته نمی‌شود —
        فقط فایل محلی (که با دکمه‌ی «انتقال» بعداً به سایت می‌رود) پردازش می‌شود.
        """
        from sync_app.core.smart_publish import (
            load_pipelines, load_watermark_settings, load_ai_studio_settings, run_pipeline,
            load_text_engrave_settings, load_qr_code_settings,
        )
        from sync_app.core.media_center import load_image_profiles

        config = load_secure_config(None) or {}
        pipelines = load_pipelines(config)
        if not pipelines:
            QMessageBox.information(
                self, "روش پردازش تصویری تعریف نشده",
                "ابتدا در تب «⚙️ تنظیمات Smart Publish» حداقل یک روش پردازش تصویر بسازید.",
            )
            return

        existing = self._picked_image_paths(vsku)
        if existing:
            src = self._abs_path_for_rel(existing[0])
        else:
            src, _ = QFileDialog.getOpenFileName(
                self, f"انتخاب تصویر واریانت {vsku}", "", "Images (*.jpg *.jpeg *.png *.bmp *.webp)"
            )
            if not src:
                return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"اجرای Smart Publish — واریانت {vsku}")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.addWidget(QLabel(f"فایل: {os.path.basename(src)}"))
        dlg_layout.addWidget(QLabel("روش پردازش تصویر:"))
        combo = QComboBox()
        for name in pipelines:
            combo.addItem(name, name)
        dlg_layout.addWidget(combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("▶️ اجرا")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dlg_layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        pipeline_name = combo.currentData()
        pipeline_data = pipelines.get(pipeline_name) or {}
        steps = pipeline_data.get("steps", [])
        profile_name = pipeline_data.get("profile", "")

        profiles = load_image_profiles(config)
        profile = profiles.get(profile_name) if profile_name else None
        watermark = load_watermark_settings(config)
        ai_studio = load_ai_studio_settings(config)
        out_dir = app_path("variation_images", vsku)

        def _worker():
            result = run_pipeline(
                src, steps, out_dir=out_dir, profile=profile, watermark=watermark,
                ai_studio=ai_studio, webp_quality=85,
                text_engrave=load_text_engrave_settings(config),
                qr_code=load_qr_code_settings(config),
                product_info={"a_code": vsku, "a_code_c": vsku, "name": vsku, "product_url": ""},
            )
            if not result.ok:
                raise RuntimeError(result.error)
            return result

        def _done(result):
            rel_path = os.path.join("variation_images", vsku, os.path.basename(result.dst_path)).replace("\\", "/")
            self._assign_picked_images(vsku, [rel_path])
            self._variation_pixmap_cache.clear()
            self._save_variation_images_map()
            self._refresh_variation_labels_for_skus({vsku})
            QMessageBox.information(
                self, "انجام شد",
                f"روش پردازش تصویر «{pipeline_name}» روی تصویر واریانت {vsku} اجرا شد.\n"
                f"حجم قبل: {result.size_before/1024:,.0f}KB → بعد: {result.size_after/1024:,.0f}KB\n"
                "(برای رفتن به سایت، از دکمه‌ی «انتقال» استفاده کنید.)",
            )

        def _fail(msg):
            QMessageBox.critical(self, "خطا", str(msg))

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _assign_picked_images(self, vsku: str, rel_paths: list[str]):
        key = self._primary_map_key(vsku)
        for old_key in self._variation_map_keys(vsku):
            if old_key != key:
                self._variation_images_map.pop(old_key, None)
        self._variation_images_map[key] = list(rel_paths)

    def _copy_images_to_skus(self, skus: list[str], files: list[str], *, replace: bool) -> bool:
        if replace:
            self._remove_picked_images_for_skus(skus)
        for vsku in skus:
            dst_dir = app_path("variation_images", vsku)
            os.makedirs(dst_dir, exist_ok=True)
            rel_paths = [] if replace else list(self._picked_image_paths(vsku))
            for src in files:
                base = os.path.basename(src)
                dst_name = f"{int(time.time() * 1000)}_{base}"
                try:
                    shutil.copy2(src, os.path.join(dst_dir, dst_name))
                    rel_paths.insert(
                        0,
                        os.path.join("variation_images", vsku, dst_name).replace("\\", "/"),
                    )
                except OSError as exc:
                    QMessageBox.warning(self, "خطا", f"کپی تصویر ناموفق: {exc}")
                    return False
            self._assign_picked_images(vsku, rel_paths)
        self._variation_pixmap_cache.clear()
        self._save_variation_images_map()
        self._refresh_variation_labels_for_skus(set(skus))
        return True

    def _checked_variant_skus(self) -> list[str]:
        out = []
        for i in range(self.variation_list.count()):
            item = self.variation_list.item(i)
            if item.data(Qt.UserRole + 1) != "variant":
                continue
            if not self._variation_item_checked(item):
                continue
            sku = str(item.data(Qt.UserRole) or "").strip()
            if sku:
                out.append(sku)
        return out

    def _pick_images_for_checked_variations(self, *, replace: bool = False):
        skus = self._checked_variant_skus()
        if not skus:
            QMessageBox.information(
                self,
                "راهنمای تصویر واریانت",
                "هیچ واریانتی تیک‌خورده نیست.\n\n"
                "ابتدا در لیست بالا، واریانت(های) مورد نظر را تیک بزنید، "
                "سپس دوباره این دکمه را بزنید.",
            )
            return
        if replace:
            if not ask_yes_no(
                self,
                "تعویض تصویر",
                f"تصاویر قبلی {len(skus)} واریانت تیک‌خورده حذف و تصویر جدید جایگزین می‌شود.\n\nادامه می‌دهید؟",
                tone="warning",
                default_yes=False,
            ):
                return
        elif len(skus) == 1:
            guide = (
                f"تصویری که در مرحله بعد انتخاب می‌کنید، فقط روی واریانت «{skus[0]}» ثبت می‌شود.\n\n"
                "می‌توانید یک یا چند تصویر انتخاب کنید (اولین تصویر، تصویر اصلی واریانت می‌شود).\n\n"
                "راه سریع‌تر: دکمه «آپلود تصویر» همان ردیف در لیست."
            )
        else:
            guide = (
                f"شما {len(skus)} واریانت را تیک زده‌اید.\n\n"
                "⚠️ تصویری که انتخاب می‌کنید روی «همهٔ» این واریانت‌ها ثبت می‌شود.\n\n"
                "اگر می‌خواهید هر واریانت تصویرِ متفاوت داشته باشد:\n"
                "این پنجره را ببندید، فقط «یک» واریانت را تیک بزنید و این دکمه را بزنید — "
                "این کار را برای هر واریانت جداگانه تکرار کنید.\n\n"
                "مرحله بعد: انتخاب تصویر  ->  سپس دکمه «انتقال تصاویر واریانت» برای ارسال به سایت."
            )
        if not replace:
            resp = QMessageBox.question(
                self,
                "راهنمای انتخاب تصویر واریانت",
                guide + "\n\nادامه می‌دهید؟",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if resp != QMessageBox.Yes:
                return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "انتخاب تصویر واریانت",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not files:
            return
        if not self._copy_images_to_skus(skus, files, replace=replace):
            return
        action = "تعویض شد" if replace else "ذخیره شد"
        QMessageBox.information(
            self,
            "انجام شد",
            f"تصویر برای {len(skus)} واریانت {action}.\n\n"
            "مرحله بعد: برای ارسال به سایت، دکمه «انتقال تصاویر واریانت» را بزنید "
            "(واریانت‌ها باید همچنان تیک‌خورده باشند).",
        )

    def _edit_images_for_checked_variations(self):
        skus = self._checked_variant_skus()
        if not skus:
            QMessageBox.information(self, "توجه", "ابتدا یک یا چند واریانت را تیک بزنید.")
            return
        if len(skus) == 1 and self._picked_image_paths(skus[0]):
            self._open_variation_images_editor(skus[0])
            return
        if not ask_yes_no(
            self,
            "ویرایش تصویر",
            f"برای {len(skus)} واریانت تیک‌خورده، تصاویر فعلی حذف و تصویر جدید انتخاب می‌شود.\n\n"
            "برای حذف/ویرایش تک‌تک تصاویر، فقط یک واریانت را تیک بزنید.\n\nادامه می‌دهید؟",
            tone="warning",
            default_yes=False,
        ):
            return
        self._pick_images_for_checked_variations(replace=True)

    def _open_variation_images_editor(self, vsku: str):
        rels = list(self._picked_image_paths(vsku))
        if not rels:
            QMessageBox.information(self, "توجه", "تصویر انتخاب‌شده‌ای برای این واریانت نیست.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"مدیریت تصویر — {vsku}")
        dlg.setLayoutDirection(Qt.RightToLeft)
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)

        hint = QLabel("تصاویر ثبت‌شده برای این واریانت:")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        list_w = QListWidget()
        list_w.setLayoutDirection(Qt.RightToLeft)
        for rel in rels:
            row = QListWidgetItem(os.path.basename(self._abs_path_for_rel(rel)))
            row.setData(Qt.UserRole, rel)
            list_w.addItem(row)
        layout.addWidget(list_w, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("افزودن")
        del_btn = QPushButton("حذف انتخاب")
        replace_btn = QPushButton("تعویض همه")
        close_btn = QPushButton("بستن")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(replace_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        def reload_list():
            list_w.clear()
            for rel in self._picked_image_paths(vsku):
                row = QListWidgetItem(os.path.basename(self._abs_path_for_rel(rel)))
                row.setData(Qt.UserRole, rel)
                list_w.addItem(row)

        def on_add():
            files, _ = QFileDialog.getOpenFileNames(
                dlg,
                "افزودن تصویر",
                "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if files and self._copy_images_to_skus([vsku], files, replace=False):
                reload_list()

        def on_delete():
            item = list_w.currentItem()
            if not item:
                QMessageBox.information(dlg, "توجه", "یک تصویر را از لیست انتخاب کنید.")
                return
            rel = str(item.data(Qt.UserRole) or "")
            if not rel:
                return
            key = self._primary_map_key(vsku)
            paths = list(self._variation_images_map.get(key, []))
            if rel in paths:
                paths.remove(rel)
            self._delete_image_files([rel])
            if paths:
                self._variation_images_map[key] = paths
            else:
                self._variation_images_map.pop(key, None)
            self._variation_pixmap_cache.clear()
            self._save_variation_images_map()
            self._refresh_variation_labels_for_skus({vsku})
            reload_list()

        def on_replace():
            files, _ = QFileDialog.getOpenFileNames(
                dlg,
                "تعویض تصاویر",
                "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if files and self._copy_images_to_skus([vsku], files, replace=True):
                reload_list()

        add_btn.clicked.connect(on_add)
        del_btn.clicked.connect(on_delete)
        replace_btn.clicked.connect(on_replace)
        close_btn.clicked.connect(dlg.accept)
        dlg.exec_()

    def _remove_images_for_checked_variations(self):
        skus = self._checked_variant_skus()
        if not skus:
            QMessageBox.information(self, "توجه", "ابتدا واریانت‌هایی را که می‌خواهید تصویرشان حذف شود تیک بزنید.")
            return
        with_images = [s for s in skus if self._picked_image_paths(s)]
        if not with_images:
            QMessageBox.information(self, "توجه", "واریانت تیک‌خورده‌ای با تصویر انتخاب‌شده نیست.")
            return
        if not ask_yes_no(
            self,
            "حذف تصویر",
            f"تصاویر {len(with_images)} واریانت از حافظه محلی حذف می‌شود.\n\nادامه می‌دهید؟",
            tone="warning",
            default_yes=False,
        ):
            return
        count = self._remove_picked_images_for_skus(with_images)
        self._refresh_variation_labels_for_skus(set(with_images))
        if ask_yes_no(
            self,
            "حذف از فروشگاه",
            "تصویر از سایت (فروشگاه) هم برای همین واریانت‌ها حذف شود؟",
            tone="warning",
            default_yes=False,
        ):
            self._clear_variation_images_on_woo(with_images)
        QMessageBox.information(
            self,
            "انجام شد",
            f"{count} تصویر از {len(with_images)} واریانت حذف شد.",
        )

    def _clear_variation_images_on_woo(self, skus: list[str]):
        cfg = load_secure_config(None) or {}
        if not ensure_connectivity(self, need_sql=False, need_wc=True, live=True):
            return

        def job():
            apply_network_overrides(cfg)
            wcapi = build_wcapi(cfg, verify_ssl=bool(cfg.get("WC_VERIFY_SSL", False)))
            if not wcapi:
                raise RuntimeError("اتصال Woo برقرار نیست.")
            product_map = load_product_woo_map()
            ok = fail = 0
            by_product: dict[int, list[str]] = {}
            for variant_sku in skus:
                parent_sku = variant_sku.rsplit("-V", 1)[0]
                pid = int(product_map.get(parent_sku) or 0)
                if not pid:
                    fail += 1
                    continue
                by_product.setdefault(pid, []).append(variant_sku)
            for pid, items in by_product.items():
                vid_index = self._variation_id_by_sku_index(wcapi, pid, cfg)
                for variant_sku in items:
                    vid, wc_sku = self._lookup_variation_id(vid_index, variant_sku)
                    if not vid:
                        fail += 1
                        continue
                    while True:
                        wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True)
                        try:
                            update_res = wcapi.put(
                                f"products/{pid}/variations/{vid}",
                                {"image": {}},
                            )
                        except Exception as exc:
                            if is_transient_connectivity_issue(str(exc)):
                                continue
                            log.error(f"❌ حذف تصویر واریانت {variant_sku}: {exc}")
                            fail += 1
                            break
                        if update_res.status_code in (200, 201):
                            log.info(f"✅ تصویر واریانت {variant_sku} از Woo حذف شد")
                            ok += 1
                        else:
                            fail += 1
                        break
            return {"ok": ok, "fail": fail}

        def done(result):
            ok = int((result or {}).get("ok", 0) or 0)
            fail = int((result or {}).get("fail", 0) or 0)
            if ok:
                QMessageBox.information(self, "فروشگاه", f"تصویر {ok} واریانت از سایت حذف شد.")
            if fail:
                QMessageBox.warning(self, "فروشگاه", f"{fail} واریانت از سایت به‌روز نشد — لاگ را ببینید.")

        def fail(err):
            QMessageBox.warning(self, "خطا", str(err))

        run_in_thread(job, on_complete=done, on_error=fail)

    def _picked_image_paths(self, variant_sku: str) -> list[str]:
        """مسیرهای تصویر انتخاب‌شده — با تطبیق aliasهای SKU."""
        from sync_app.core.variation_query import variation_skus_match

        out: list[str] = []
        seen: set[str] = set()
        for key, rels in (self._variation_images_map or {}).items():
            if not variation_skus_match(str(key), variant_sku):
                continue
            for rel in rels or []:
                if rel and rel not in seen:
                    seen.add(rel)
                    out.append(rel)
        return out

    def _variation_image_paths(self, variant_sku: str, *, picked_only: bool = False) -> list[str]:
        paths = self._picked_image_paths(variant_sku)
        if picked_only:
            return paths
        parent_sku = variant_sku.rsplit("-V", 1)[0] if "-V" in variant_sku.upper() else ""
        if parent_sku:
            for rel in stage_erp_images(parent_sku, b"", "", self.config or {}, subdir="product_images"):
                if rel not in paths:
                    paths.append(rel)
        return paths

    def _variation_preview_image_path(self, variant_sku: str) -> str:
        """فقط تصویر انتخاب‌شده — بدون fallback ERP (سپر)."""
        for rel in self._picked_image_paths(variant_sku):
            abs_path = rel if os.path.isabs(rel) else app_path(rel)
            if os.path.exists(abs_path):
                return abs_path
        return ""

    def _on_variation_hover(self, item):
        """hover روی واریانت — نمایش انگشتی تصویر لوکال."""
        if item.data(Qt.UserRole + 1) != "variant":
            self.image_preview.hide()
            return
        variant_sku = str(item.data(Qt.UserRole) or "").strip()
        if not variant_sku:
            self.image_preview.hide()
            return

        abs_path = self._variation_preview_image_path(variant_sku)
        if not abs_path:
            self.image_preview.hide()
            return

        cache_key = f"local:{abs_path}"
        pixmap = self._variation_pixmap_cache.get(cache_key)
        if pixmap is None:
            loaded = QPixmap(abs_path)
            if loaded.isNull():
                self.image_preview.hide()
                return
            pixmap = loaded.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._variation_pixmap_cache[cache_key] = pixmap

        self._current_hover_item = item
        self.image_preview.setPixmap(pixmap)
        self.image_preview.resize(pixmap.width() + 10, pixmap.height() + 10)
        self._move_preview_near_cursor()
        self.image_preview.show()

    def _move_preview_near_cursor(self):
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None

        preview_width = self.image_preview.width()
        preview_height = self.image_preview.height()
        left_offset = QPoint(-(preview_width + 22), 12)
        right_offset = QPoint(22, 12)

        preferred_pos = cursor_pos + left_offset
        fallback_pos = cursor_pos + right_offset

        if available is None:
            self.image_preview.move(preferred_pos)
            return

        pos = preferred_pos
        if preferred_pos.x() < available.left():
            pos = fallback_pos

        if pos.x() + preview_width > available.right():
            pos.setX(max(available.left() + 6, available.right() - preview_width - 6))

        if pos.x() < available.left():
            pos.setX(available.left() + 6)

        if pos.y() + preview_height > available.bottom():
            pos.setY(max(available.top() + 6, cursor_pos.y() - preview_height - 12))

        if pos.y() < available.top():
            pos.setY(available.top() + 6)

        self.image_preview.move(pos)

    def eventFilter(self, obj, event):
        if obj is self.variation_list.viewport():
            if event.type() == QEvent.Leave:
                self.image_preview.hide()
                self._current_hover_item = None
            elif event.type() == QEvent.MouseMove and self.image_preview.isVisible():
                self._move_preview_near_cursor()
        return super().eventFilter(obj, event)

    def _on_send_variation_images_clicked(self):
        self._action_ops.handle_click("var_images", self._send_variation_images_to_woo)

    def _begin_var_images_ui(self):
        self._action_ops.begin("var_images", working_text="⏳ در حال انتقال تصاویر...")
        self._sync_started_at = time.monotonic()
        self._live_log_hint = "⏳ انتقال تصاویر واریانت به فروشگاه..."
        self.sync_progress.setFormat("%p% — انتقال تصاویر")
        self.sync_progress.setValue(5)
        self.sync_progress.setVisible(True)
        self.sync_detail_label.setText("آماده‌سازی آپلود...")
        self.sync_detail_label.setVisible(True)
        self._set_variations_status("loading", "⏳ در حال انتقال تصاویر واریانت...")
        try:
            self.log_panel_controller.ensure_visible()
        except Exception:
            pass
        self._sync_live_timer.start()
        self.log_timer.setInterval(400)
        self.refresh_logs()

    def _end_var_images_ui(self):
        self._sync_live_timer.stop()
        self._live_log_hint = ""
        self.log_timer.setInterval(2000)
        self.sync_progress.setVisible(False)
        self.sync_detail_label.setVisible(False)
        self.sync_progress.setFormat("%p% — همگام‌سازی")
        if self._action_ops.active == "var_images":
            self._action_ops.end()

    def _stop_variation_images_upload(self):
        if self._action_ops.active != "var_images":
            return
        if cancel_background_sync(self):
            self._action_ops.set_stopping("var_images")
            self._live_log_hint = "⏹ درخواست توقف ارسال تصاویر..."
            self._set_variations_status("warning", "⏹ در حال توقف انتقال تصاویر...")
            self.refresh_logs()
        else:
            QMessageBox.information(self, "توقف", "عملیات فعالی برای توقف یافت نشد.")

    def _var_images_done(self, result=None):
        self._end_var_images_ui()
        self.refresh_logs()
        ok_count = int((result or {}).get("ok", 0) or 0)
        fail_count = int((result or {}).get("fail", 0) or 0)
        if ok_count > 0:
            msg = f"تصویر {ok_count} واریانت ارسال شد."
            if fail_count:
                msg += f"\n({fail_count} مورد ناموفق)"
            self._set_variations_status("success", f"✅ {msg}")
            QMessageBox.information(self, "موفق", msg)
        else:
            self._set_variations_status("info", "ℹ️ تصویر واریانتی ارسال نشد.")
            QMessageBox.information(self, "نتیجه", "تصویر واریانتی ارسال نشد.")

    def _var_images_error(self, message):
        self._end_var_images_ui()
        self.refresh_logs()
        short = str(message).split("\n")[0][:160]
        self._set_variations_status("error", f"❌ {short}")
        if "متوقف شد" in str(message):
            QMessageBox.information(self, "توقف", str(message))
        else:
            QMessageBox.warning(self, "خطا", str(message))

    def _variation_id_by_sku_index(self, wcapi, product_id: int, cfg: dict) -> dict:
        """ایندکس واریانت‌های یک محصول — هر دو فرمت SKU (0302001-V3 و V3-0302001)."""
        index: dict[str, tuple[int, str]] = {}
        page = 1
        while True:
            wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True)
            batch = wcapi.get(
                f"products/{product_id}/variations",
                params={"per_page": 100, "page": page, "_fields": "id,sku"},
            ).json()
            if not isinstance(batch, list) or not batch:
                break
            for row in batch:
                wc_sku = str(row.get("sku") or "").strip()
                vid = int(row.get("id") or 0)
                if not vid or not wc_sku:
                    continue
                for alias in variation_sku_aliases(wc_sku):
                    index.setdefault(alias, (vid, wc_sku))
            if len(batch) < 100:
                break
            page += 1
        return index

    @staticmethod
    def _lookup_variation_id(index: dict, variant_sku: str):
        for alias in variation_sku_aliases(variant_sku):
            hit = index.get(alias)
            if hit:
                return hit
        return None, ""

    def _send_variation_images_to_woo(self):
        cfg = load_secure_config(None) or {}
        skus = self._checked_variant_skus()
        if not skus:
            QMessageBox.information(self, "توجه", "واریانت تیک‌خورده‌ای نیست.")
            return
        targets = [(s, self._variation_image_paths(s, picked_only=True)) for s in skus]
        targets = [(s, p) for s, p in targets if p]
        if not targets:
            targets = [(s, self._variation_image_paths(s)) for s in skus]
            targets = [(s, p) for s, p in targets if p]
        if not targets:
            from sync_app.core.integrations.erp_provider import erp_provider_label

            QMessageBox.information(
                self,
                "توجه",
                "تصویری برای واریانت‌های تیک‌خورده نیست.\n"
                f"اول «انتخاب تصویر واریانت» را بزنید یا تصویر محصول مادر را در "
                f"{erp_provider_label(self.config)} بگذارید.",
            )
            return

        def job_ps():
            from sync_app.core.ps_variation_helper import ps_set_combination_image, ps_list_combinations

            log.info(f"▸ انتقال تصویر {len(targets)} واریانت به پرستاشاپ...")
            product_map = load_product_woo_map()
            ok = fail = 0
            by_product: dict[int, list[tuple[str, list[str]]]] = {}
            for variant_sku, paths in targets:
                parent_sku = variant_sku.rsplit("-V", 1)[0]
                pid = int(product_map.get(parent_sku) or 0)
                if not pid:
                    log.warning(f"⚠️ والد {parent_sku} برای {variant_sku} در پرستاشاپ نیست")
                    fail += 1
                    continue
                by_product.setdefault(pid, []).append((variant_sku, paths))

            for pid, items in by_product.items():
                try:
                    combos = ps_list_combinations(cfg, pid)
                except Exception as exc:
                    log.error(f"❌ دریافت combinationهای محصول #{pid}: {exc}")
                    fail += len(items)
                    continue
                combo_by_ref = {
                    str(c.get("reference") or "").strip().lower(): c for c in combos if c.get("reference")
                }
                for variant_sku, paths in items:
                    combo = None
                    for alias in variation_sku_aliases(variant_sku):
                        combo = combo_by_ref.get(alias.lower())
                        if combo:
                            break
                    if not combo:
                        log.warning(
                            f"⚠️ واریانت {variant_sku} در پرستاشاپ (محصول #{pid}) پیدا نشد "
                            f"(SKUهای موجود: {', '.join(sorted(combo_by_ref)[:6]) or '—'})"
                        )
                        fail += 1
                        continue
                    combo_id = int(combo["id"])
                    uploaded = False
                    for rel in paths:
                        abs_path = rel if os.path.isabs(rel) else app_path(rel)
                        if not os.path.exists(abs_path):
                            log.warning(f"⚠️ فایل تصویر پیدا نشد: {abs_path}")
                            continue
                        try:
                            with open(abs_path, "rb") as f:
                                data = f.read()
                            new_id = ps_set_combination_image(
                                cfg, pid, combo_id, data, os.path.basename(abs_path)
                            )
                            log.info(f"✅ تصویر واریانت {variant_sku} → combination #{combo_id} (image={new_id})")
                            ok += 1
                            uploaded = True
                            break
                        except Exception as exc:
                            log.error(f"❌ آپلود تصویر {variant_sku}: {exc}")
                    if not uploaded:
                        fail += 1
            if ok == 0:
                raise RuntimeError("هیچ تصویر واریانتی به پرستاشاپ نرفت.")
            return {"ok": ok, "fail": fail}

        def job():
            log.info(f"▸ انتقال تصویر {len(targets)} واریانت به Woo...")
            apply_network_overrides(cfg)
            wcapi = build_wcapi(cfg, verify_ssl=bool(cfg.get("WC_VERIFY_SSL", False)))
            if not wcapi:
                raise RuntimeError("اتصال Woo برقرار نیست.")
            product_map = load_product_woo_map()
            ok = fail = 0
            by_product: dict[int, list[tuple[str, list[str]]]] = {}
            for variant_sku, paths in targets:
                parent_sku = variant_sku.rsplit("-V", 1)[0]
                pid = int(product_map.get(parent_sku) or 0)
                if not pid:
                    log.warning(f"⚠️ والد {parent_sku} برای {variant_sku} در Woo نیست")
                    fail += 1
                    continue
                by_product.setdefault(pid, []).append((variant_sku, paths))

            for pid, items in by_product.items():
                vid_index = self._variation_id_by_sku_index(wcapi, pid, cfg)
                for variant_sku, paths in items:
                    vid, wc_sku = self._lookup_variation_id(vid_index, variant_sku)
                    if not vid:
                        log.warning(
                            f"⚠️ واریانت {variant_sku} در Woo پیدا نشد "
                            f"(محصول #{pid} — SKUهای موجود: "
                            f"{', '.join(sorted({v[1] for v in vid_index.values()})[:6]) or '—'})"
                        )
                        fail += 1
                        continue
                    # فقط اولین تصویر برای واریانت لازم است؛ با id رسانه می‌چسبد (مطمئن‌تر از src)
                    media_id = 0
                    src_url = ""
                    uploaded_name = ""
                    for rel in paths:
                        abs_path = rel if os.path.isabs(rel) else app_path(rel)
                        if not os.path.exists(abs_path):
                            log.warning(f"⚠️ فایل تصویر پیدا نشد: {abs_path}")
                            continue
                        with open(abs_path, "rb") as f:
                            data = f.read()
                        ok_up, mid, url, err = wp_upload_media_ex(
                            cfg, data, os.path.basename(abs_path), fallback_stem=variant_sku, label=variant_sku
                        )
                        if ok_up and url:
                            media_id = mid
                            src_url = url
                            uploaded_name = os.path.basename(abs_path)
                            log.info(
                                f"📷 آپلود {uploaded_name} برای {variant_sku} "
                                f"(media_id={media_id})"
                            )
                            break
                        log.error(f"❌ آپلود تصویر {variant_sku}: {err}")
                    if not src_url:
                        fail += 1
                        continue

                    # id ارجح است؛ اگر media_id نبود به src برمی‌گردیم
                    image_payload = {"id": media_id} if media_id else {"src": src_url}
                    while True:
                        wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True)
                        try:
                            update_res = wcapi.put(
                                f"products/{pid}/variations/{vid}",
                                {"image": image_payload},
                            )
                        except Exception as exc:
                            if is_transient_connectivity_issue(str(exc)):
                                continue
                            log.error(f"❌ تنظیم تصویر واریانت {variant_sku}: {exc}")
                            fail += 1
                            break
                        if update_res.status_code in (200, 201):
                            # بازخوانی پاسخ — اگر image تهی باشد یعنی واقعاً نچسبیده
                            try:
                                body = update_res.json() or {}
                            except Exception:
                                body = {}
                            img = body.get("image") or {}
                            set_id = (img or {}).get("id")
                            if img and set_id:
                                log.info(
                                    f"✅ تصویر واریانت {variant_sku} "
                                    f"(Woo sku={wc_sku}) → #{vid} (media={set_id})"
                                )
                                ok += 1
                            else:
                                # یک GET تأییدی — گاهی پاسخ PUT image نمی‌دهد ولی ذخیره شده
                                try:
                                    verify = wcapi.get(
                                        f"products/{pid}/variations/{vid}",
                                        params={"_fields": "id,image"},
                                    ).json()
                                    v_img = (verify or {}).get("image") or {}
                                    v_id = v_img.get("id")
                                except Exception:
                                    v_id = None
                                if v_id:
                                    log.info(
                                        f"✅ تصویر واریانت {variant_sku} "
                                        f"(Woo sku={wc_sku}) → #{vid} (media={v_id} — تأیید GET)"
                                    )
                                    ok += 1
                                else:
                                    log.error(
                                        f"❌ واریانت {variant_sku} (#{vid}): API ۲۰۰ داد ولی "
                                        f"image خالی ماند — media_id={media_id}، "
                                        f"فایل={uploaded_name or '?'}"
                                    )
                                    fail += 1
                            break
                        detail = (getattr(update_res, "text", None) or "")[:200]
                        if is_transient_connectivity_issue(detail):
                            continue
                        log.error(
                            f"❌ تنظیم تصویر واریانت {variant_sku} (Woo #{vid}): "
                            f"API {update_res.status_code} — {detail}"
                        )
                        fail += 1
                        break
            if ok == 0:
                raise RuntimeError("هیچ تصویر واریانتی به Woo نرفت.")
            return {"ok": ok, "fail": fail}

        from sync_app.core.integrations.commerce_provider import is_prestashop

        if not run_background_sync(
            self, job_ps if is_prestashop(cfg) else job,
            on_success=self._var_images_done,
            on_error=self._var_images_error,
            need_sql=False,
            need_wc=True,
            wait_on_disconnect=True,
        ):
            thread = getattr(self, "_peecha_bg_sync_thread", None)
            if thread is not None and thread.isRunning():
                QMessageBox.information(self, "در حال اجرا", "یک عملیات دیگر در حال اجرا است.")
            else:
                QMessageBox.warning(
                    self,
                    "شروع نشد",
                    "انتقال تصاویر شروع نشد.\n"
                    "اتصال Woo را در نوار بالا چک کنید.",
                )
            return
        self._begin_var_images_ui()

    def send_variations(self):
        """همگام‌سازی واریانت‌ها در پس‌زمینه"""
        if not run_background_sync(
            self,
            update_variations.main,
            on_success=self._var_sync_done,
            on_error=self._var_sync_error,
            need_sql=True,
            need_wc=True,
        ):
            thread = getattr(self, "_peecha_bg_sync_thread", None)
            if thread is not None and thread.isRunning():
                QMessageBox.information(self, "در حال اجرا", "عملیات دیگری در جریان است.")
            return
        self._sync_started_at = time.monotonic()
        self._sync_progress_total = 0
        self._sync_progress_current = 0
        self._live_log_hint = "⏳ همگام‌سازی واریانت‌ها با فروشگاه..."
        self.sync_progress.setValue(0)
        self.sync_progress.setVisible(True)
        self.sync_detail_label.setText("آماده‌سازی اتصال و دریافت ویژگی‌ها...")
        self.sync_detail_label.setVisible(True)
        self._action_ops.begin("sync")
        self._set_variations_status("loading", "⏳ در حال همگام‌سازی واریانت‌ها با فروشگاه...")
        try:
            self.log_panel_controller.ensure_visible()
        except Exception:
            pass
        self._sync_live_timer.start()
        self.log_timer.setInterval(400)
        self.refresh_logs()

    def _tick_sync_ui(self):
        self.refresh_logs()
        if self._action_ops.active == "sync":
            elapsed = int(time.monotonic() - self._sync_started_at)
            step, phase_pct = self._parse_sync_progress()
            if step:
                self._set_variations_status("loading", f"⏳ {step} ({elapsed}s)")
                self.sync_detail_label.setText(step)
            else:
                self._set_variations_status("loading", f"⏳ همگام‌سازی... ({elapsed}s)")
            if phase_pct is not None:
                self.sync_progress.setValue(max(0, min(100, int(phase_pct))))
        elif self._action_ops.active == "var_images":
            elapsed = int(time.monotonic() - self._sync_started_at)
            step = self._last_var_image_step()
            if step:
                self._set_variations_status("loading", f"⏳ {step} ({elapsed}s)")
                self.sync_detail_label.setText(step)
                self.sync_progress.setValue(min(95, self.sync_progress.value() + 2))
            else:
                self._set_variations_status("loading", f"⏳ انتقال تصاویر... ({elapsed}s)")
                self.sync_progress.setValue(min(90, 10 + elapsed * 3))

    def _parse_sync_progress(self):
        import re

        step = self._last_sync_step()
        if not step:
            return "", None
        m = re.search(r"محصول\s+(\d+)\s*/\s*(\d+)", step)
        if m:
            current, total = int(m.group(1)), max(1, int(m.group(2)))
            self._sync_progress_current = current
            self._sync_progress_total = total
            base = 15
            span = 80
            return step, base + int((current / total) * span)
        m2 = re.search(r"مرحله\s+(\d+)\s*/\s*(\d+)", step)
        if m2:
            phase, total_phases = int(m2.group(1)), max(1, int(m2.group(2)))
            return step, int((phase / total_phases) * 12)
        if "batch" in step.lower():
            return step, max(self.sync_progress.value(), 20)
        if "✅" in step:
            return step, 100
        return step, None

    def _last_var_image_step(self):
        try:
            log_path = app_path("sync.log")
            if not os.path.exists(log_path):
                return ""
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines[-60:]):
                low = line.lower()
                if "تصویر واریانت" in line or "آپلود" in line or "انتقال تصویر" in line:
                    if " - INFO - " in line:
                        part = line.split(" - INFO - ", 1)[-1].strip()
                        if "SyncApp - " in part:
                            part = part.split("SyncApp - ", 1)[-1].strip()
                        return part[:120]
                    if "▸" in line:
                        return line.split("▸", 1)[-1].strip()[:120]
        except Exception:
            pass
        return ""

    def _last_sync_step(self):
        try:
            log_path = app_path("sync.log")
            if not os.path.exists(log_path):
                return ""
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines[-80:]):
                if "▸" in line:
                    part = line.split("▸", 1)[-1].strip()
                    if part:
                        return part[:120]
        except Exception:
            pass
        return ""

    def stop_variations_sync(self):
        if self._action_ops.active != "sync":
            return
        if cancel_background_sync(self):
            self._action_ops.set_stopping("sync")
            self._live_log_hint = "⏹ درخواست توقف ارسال شد — لطفاً صبر کنید..."
            self._set_variations_status("warning", "⏹ در حال توقف همگام‌سازی...")
            self.refresh_logs()
        else:
            QMessageBox.information(self, "توقف", "عملیات فعالی برای توقف یافت نشد.")

    def _end_var_sync_ui(self):
        self._sync_live_timer.stop()
        self._live_log_hint = ""
        self.log_timer.setInterval(2000)
        self.sync_progress.setVisible(False)
        self.sync_detail_label.setVisible(False)
        if self._action_ops.active == "sync":
            self._action_ops.end()

    def _var_sync_done(self, result=None):
        self._end_var_sync_ui()
        self.refresh_logs()
        ok_count = (result or {}).get("ok", 0) if isinstance(result, dict) else 0
        if ok_count > 0:
            self._set_variations_status("success", f"✅ {ok_count} محصول با واریانت‌هایش همگام شد.")
            QMessageBox.information(self, "موفق", f"{ok_count} محصول با واریانت‌هایش همگام شد.")
            self.load_variations(silent=True, manual=False)
        else:
            self._set_variations_status("info", "ℹ️ واریانتی برای همگام‌سازی یافت نشد.")
            QMessageBox.information(
                self,
                "نتیجه",
                "واریانتی برای همگام‌سازی یافت نشد.",
            )

    def _var_sync_error(self, message):
        self._end_var_sync_ui()
        self.refresh_logs()
        short = str(message).split("\n")[0][:160]
        self._set_variations_status("error", f"❌ {short}")
        if "متوقف شد" in str(message):
            QMessageBox.information(self, "توقف", str(message))
        else:
            QMessageBox.critical(self, "خطا در همگام‌سازی", str(message))

    def refresh_logs(self):
        try:
            log_path = app_path("sync.log")
            if not os.path.exists(log_path):
                self.log_view.setPlainText("هنوز لاگی ایجاد نشده است.")
                return

            with open(log_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()

            filtered = _filter_variation_log_lines(all_lines)
            if not filtered:
                self.log_view.setPlainText("لاگ تب متغیرها خالی است.")
                return
            body = format_log_lines_jalali(filtered[-60:])
            if self._live_log_hint and self._sync_live_timer.isActive():
                elapsed = int(time.monotonic() - self._sync_started_at)
                step = self._last_sync_step()
                step_line = f"📍 {step}" if step else self._live_log_hint
                header = f"{step_line}\n⏱️ {elapsed} ثانیه\n{'─' * 28}"
                body = f"{header}\n\n{body}" if body.strip() else header
            self.log_view.setPlainText(body)
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
        except Exception as e:
            self.log_view.setPlainText(f"خطا در خواندن لاگ: {e}")

    def ensure_initial_variations_loaded(self):
        if self._initial_empty_refresh_done:
            return

        self._initial_empty_refresh_done = True
        self.load_variations(silent=True, manual=False)