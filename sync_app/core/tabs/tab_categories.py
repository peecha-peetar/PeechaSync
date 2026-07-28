import sys
import os
import re
import json
import shutil
import time
import requests
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QMessageBox, QHBoxLayout, QTextEdit, QSplitter, QLineEdit, QDialog,
    QDialogButtonBox, QFileDialog, QProgressBar, QToolButton, QComboBox
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QEvent, QPoint, QSize
from PyQt5.QtGui import QPixmap, QCursor, QGuiApplication
from sync_app.core.log_panel_ui import LogPanelController, VerticalTextButton, LogActionRail
from sync_app.core.rtl_item_delegate import RightAlignedCheckableItemDelegate
from sync_app.core.jalali_log_formatter import format_log_lines_jalali

# 📌 اصلاح مسیرهای import به شکل پکیجی
from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.event_notifier import append_system_log
from sync_app.core.sql_connection_helper import connect_with_fallback, repair_sql_config_if_needed, format_db_error, open_sql_connection
from sync_app.core.sync_utils import log, app_path, site_scoped_path, clear_filtered_logs
import pyodbc

# ماژول sync دسته‌ها
from sync_app.core.scripts import ProductCategoriesSync
from sync_app.core.sync_job_runner import run_background_sync, cancel_background_sync
from sync_app.core.connectivity_wait import wait_for_connectivity_dialog
from sync_app.core.tabs.tab_license import LicenseTab
from sync_app.core.connectivity_wait import wait_for_connectivity_blocking
from sync_app.core.connectivity_guard import ensure_connectivity
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.tab_action_controller import TabActionController, ActionSpec
from sync_app.core.responsive_action_bar import build_responsive_action_row
from sync_app.core.compact_icon_action_bar import CompactCaptionButton
from sync_app.core.wc_admin_links import make_wc_admin_open_button
from sync_app.core.selection_toggle_bar import attach_selection_toggle
from sync_app.core.wc_api_helper import wc_endpoint, get_wc_auth, wc_store_host
from sync_app.core.wc_site_profiles import ensure_wc_sites
from sync_app.core.wc_sync_helper import (
    apply_network_overrides,
    wc_sync_timeout,
    WC_SYNC_RETRIES,
    WC_SYNC_BACKOFF,
    wp_upload_media_ex,
    update_wc_category_image,
    get_wp_media_credentials,
    wcapi_parse_json,
    verify_wp_media_credentials,
    should_retry_upload_error,
    is_wp_upload_fatal_error,
    WP_UPLOAD_MAX_ATTEMPTS,
)
from sync_app.core.category_rules import merge_category_map_with_slug_map
from sync_app.core.sync_cancel import check_cancelled, SyncCancelled
from sync_app.core.diagnostics import diagnose_wc, format_wc_error
from sync_app.core.category_resolver import (
    dejavu_category_slug,
    extract_code_from_wc_slug,
    load_category_map,
    save_category_map,
    resolve_wc_category_id,
    fetch_wc_slug_map,
)
from urllib.parse import unquote


# یک لیست برای نمایش و پاک‌کردن — اگر جدا باشند «پاک شد» می‌گوید ولی لاگ می‌ماند.
CATEGORY_LOG_TOKENS = (
    "دسته‌بندی",
    "دسته",
    "category_map",
    "products/categories",
    "ProductCategoriesSync",
    "گروه",
    "زیرگروه",
    "بروزرسانی گروه",
    "همگام‌سازی دسته",
    "خطای بررسی فروشگاه",
    "بررسی وضعیت دسته",
    "دریافت categories",
    "تب دسته‌بندی",
    "ارسال تصاویر دسته",
    "تصویر دسته",
    "نگاشت دسته",
)

CATEGORY_LISTS_SPLITTER_KEY = "CATEGORY_LISTS_SPLITTER_SIZES"
DEFAULT_CATEGORY_LISTS_SPLITTER_SIZES = [300, 420]


def _filter_category_log_lines(lines):
    tokens = [t.lower() for t in CATEGORY_LOG_TOKENS]
    return [line for line in lines if any(tok in line.lower() for tok in tokens)]


def _guess_mime_cat(filename):
    ext = os.path.splitext(filename.lower())[1]
    return {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.webp': 'image/webp',
        '.gif': 'image/gif', '.bmp': 'image/bmp',
    }.get(ext, 'image/jpeg')


class CategoryRowWidget(QWidget):
    """ردیف دسته‌بندی در لیست انتخاب‌شده‌ها — دکمه آپلود + حذف تصویر + نام + حالت موجودی"""
    def __init__(
        self, text, on_upload, on_clear=None, on_stock_mode_changed=None,
        on_price_list_changed=None, parent=None, show_image_buttons=True,
    ):
        super().__init__(parent)
        self._on_clear = on_clear
        self._on_stock_mode_changed = on_stock_mode_changed
        self._on_price_list_changed = on_price_list_changed
        self.setLayoutDirection(Qt.LeftToRight)
        row = QHBoxLayout(self)
        row.setDirection(QHBoxLayout.LeftToRight)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(6)

        if show_image_buttons:
            self.upload_button = QPushButton("آپلود تصویر")
            self.upload_button.setStyleSheet("padding: 2px 6px; font-size: 11px; min-height: 28px;")
            self.upload_button.setFixedWidth(120)
            self.upload_button.setFixedHeight(36)
            self.upload_button.clicked.connect(on_upload)
            row.addWidget(self.upload_button)

            from sync_app.core.row_action_button import make_row_button, row_button_style
            self.clear_button = make_row_button("✕", "حذف تصویر این دسته", kind="danger", size=24)
            self.clear_button.setStyleSheet(
                row_button_style("danger") + "QToolButton { color: #b91c1c; font-weight: bold; font-size: 13px; }"
            )
            self.clear_button.clicked.connect(self._handle_clear)
            self.clear_button.hide()
            row.addWidget(self.clear_button)
        else:
            self.upload_button = None
            self.clear_button = None

        from sync_app.core.stock_mode import STOCK_MODE_LABELS
        self.stock_mode_combo = QComboBox()
        self.stock_mode_combo.setLayoutDirection(Qt.RightToLeft)
        self.stock_mode_combo.setMaximumWidth(150)
        self.stock_mode_combo.setFixedHeight(28)
        self.stock_mode_combo.setStyleSheet("font-size: 11px; padding: 1px 4px;")
        if show_image_buttons:
            self.stock_mode_combo.setToolTip(
                "حالت موجودی این زیر-دسته — اگر خالی/پیش‌فرض بمونه، از حالت "
                "موجودیِ دسته‌ی اصلی (بالای همین لیست) ارث می‌بره. هر محصول هم "
                "می‌تونه جدا تو تب «محصولات» بازنویسی بشه."
            )
        else:
            self.stock_mode_combo.setToolTip(
                "حالت موجودی پیش‌فرض برای همه‌ی زیر-دسته‌های این دسته‌ی اصلی — "
                "روی هر زیر-دسته که جدا override نشده باشه اعمال می‌شه."
            )
        for key, label in STOCK_MODE_LABELS.items():
            self.stock_mode_combo.addItem(label, key)
        self.stock_mode_combo.currentIndexChanged.connect(self._handle_stock_mode_changed)
        row.addWidget(self.stock_mode_combo)

        self.price_list_combo = QComboBox()
        self.price_list_combo.setLayoutDirection(Qt.RightToLeft)
        self.price_list_combo.setMaximumWidth(150)
        self.price_list_combo.setFixedHeight(28)
        self.price_list_combo.setStyleSheet("font-size: 11px; padding: 1px 4px;")
        if show_image_buttons:
            self.price_list_combo.setToolTip(
                "لیستِ قیمتِ این زیر-دسته — اگر «پیش‌فرض» بمونه، از لیستِ قیمتِ "
                "سراسریِ تنظیمات یا لیستِ قیمتِ دسته‌ی اصلی (بالای همین لیست) "
                "ارث می‌بره. هر محصول هم می‌تونه جدا تو تب «محصولات» بازنویسی بشه."
            )
        else:
            self.price_list_combo.setToolTip(
                "لیستِ قیمتِ پیش‌فرض برای همه‌ی زیر-دسته‌های این دسته‌ی اصلی — "
                "روی هر زیر-دسته که جدا override نشده باشه اعمال می‌شه."
            )
        self.price_list_combo.addItem("پیش‌فرض (سراسری)", None)
        for i in range(10):
            self.price_list_combo.addItem(f"لیست قیمت {i + 1}", i)
        self.price_list_combo.currentIndexChanged.connect(self._handle_price_list_changed)
        row.addWidget(self.price_list_combo)

        row.addStretch(1)

        self.title = QLabel(text)
        self.title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.title.setWordWrap(False)
        if not show_image_buttons:
            font = self.title.font()
            font.setBold(True)
            self.title.setFont(font)
        row.addWidget(self.title)

    def set_stock_mode(self, mode: str):
        self.stock_mode_combo.blockSignals(True)
        idx = self.stock_mode_combo.findData(mode)
        self.stock_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.stock_mode_combo.blockSignals(False)

    def _handle_stock_mode_changed(self):
        if callable(self._on_stock_mode_changed):
            self._on_stock_mode_changed(self.stock_mode_combo.currentData())

    def set_price_list_index(self, index):
        self.price_list_combo.blockSignals(True)
        idx = self.price_list_combo.findData(index)
        self.price_list_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.price_list_combo.blockSignals(False)

    def _handle_price_list_changed(self):
        if callable(self._on_price_list_changed):
            self._on_price_list_changed(self.price_list_combo.currentData())

    def _handle_clear(self):
        if callable(self._on_clear):
            self._on_clear()

    def set_has_image(self, has):
        self.clear_button.setVisible(bool(has))
        if has:
            self.upload_button.setText("آپلود تصویر ✔")
            self.upload_button.setStyleSheet(
                "background-color: #166534; color: white; "
                "padding: 2px 6px; font-size: 11px; min-height: 28px;"
            )
        else:
            self.upload_button.setText("آپلود تصویر")
            self.upload_button.setStyleSheet(
                "padding: 2px 6px; font-size: 11px; min-height: 28px;"
            )


# ---------------------------------------------------------
# مسیر داینامیک برای فایل‌های منابع (فقط qss, فونت, config)
# ---------------------------------------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # حالت EXE
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


# ---------------------------------------------------------
# Worker برای بررسی وضعیت دسته‌بندی‌ها در فروشگاه
# ---------------------------------------------------------
class ImageLoaderWorker(QObject):
    """دانلود async تصویر پیش‌نمایش — روی thread جداگانه اجرا می‌شه"""
    loaded = pyqtSignal(str, QPixmap)   # url, pixmap
    failed = pyqtSignal(str)            # url

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            data = requests.get(self.url, timeout=5).content
            pix = QPixmap()
            if pix.loadFromData(data):
                scaled = pix.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.loaded.emit(self.url, scaled)
                return
        except Exception:
            pass
        self.failed.emit(self.url)


class WCCategoryCheckWorker(QObject):
    """بررسی نامک (slug) دسته‌بندی‌ها در فروشگاه و مقایسه با نرم‌افزار"""
    finished = pyqtSignal(dict, list)  # (wc_slug_map, all_wc_cats)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config or {}
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def run(self):
        from sync_app.core.integrations.commerce_provider import is_prestashop

        if is_prestashop(self.config):
            self._run_prestashop()
            return
        try:
            apply_network_overrides(self.config)
            wc_url = (self.config.get("WC_URL") or "").strip().rstrip("/")
            ck = (self.config.get("WC_CONSUMER_KEY") or "").strip()
            cs = (self.config.get("WC_CONSUMER_SECRET") or "").strip()
            timeout = wc_sync_timeout(self.config)

            if not wc_url or not ck or not cs:
                self.error.emit("تنظیمات فروشگاه کامل نیست.")
                return

            categories_endpoint = wc_endpoint(self.config.get("WC_URL", ""), "products/categories")
            auth = get_wc_auth(self.config)

            all_wc_cats = []
            page = 1
            while True:
                if self._cancel_requested:
                    self.error.emit("متوقف شد")
                    return
                last_error = None
                data = None
                for attempt in range(1, WC_SYNC_RETRIES + 2):
                    try:
                        resp = requests.get(
                            categories_endpoint,
                            auth=auth,
                            params={"per_page": 100, "page": page},
                            timeout=timeout,
                        )
                        resp.raise_for_status()
                        data = wcapi_parse_json(
                            resp, f"دریافت categories صفحه {page}", self.config
                        )
                        break
                    except Exception as err:
                        last_error = err
                        if attempt <= WC_SYNC_RETRIES:
                            wait = WC_SYNC_BACKOFF[min(attempt - 1, len(WC_SYNC_BACKOFF) - 1)]
                            log.warning(
                                f"⚠️ دریافت categories صفحه {page} — "
                                f"تلاش {attempt} ناموفق ({wait:.0f}s صبر): {err}"
                            )
                            time.sleep(wait)
                if data is None:
                    raise last_error

                if not data or not isinstance(data, list):
                    break
                all_wc_cats.extend(data)
                if len(data) < 100:
                    break
                page += 1

            wc_slug_map = {}
            for cat in all_wc_cats:
                slug = unquote((cat.get("slug") or "").strip().lower())
                if slug:
                    wc_slug_map[slug] = {
                        "id": cat.get("id"),
                        "name": cat.get("name", ""),
                        "slug": slug,
                        "image": cat.get("image") or {}
                    }

            self.finished.emit(wc_slug_map, all_wc_cats)

        except Exception as e:
            log.error(f"❌ خطای بررسی وضعیت دسته‌ها در Woo: {e}")
            self.error.emit(format_wc_error(exc=e, config=self.config))

    def _run_prestashop(self):
        from sync_app.core.integrations.commerce_provider import fetch_store_slug_map

        def _cancel_probe():
            if self._cancel_requested:
                raise RuntimeError("متوقف شد")

        try:
            if not self.config.get("PS_URL") or not self.config.get("PS_API_KEY"):
                self.error.emit("تنظیمات پرستاشاپ کامل نیست.")
                return
            timeout = wc_sync_timeout(self.config)
            wc_slug_map = fetch_store_slug_map(
                self.config, timeout=timeout, cancel_check=_cancel_probe,
            )
            all_wc_cats = list(wc_slug_map.values())
            self.finished.emit(wc_slug_map, all_wc_cats)
        except Exception as e:
            log.error(f"❌ خطای بررسی وضعیت دسته‌ها در پرستاشاپ: {e}")
            self.error.emit(str(e))


class CategoryTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None)
        self.product_tab_ref = None
        self.variation_tab_ref = None
        self._wc_check_thread = None
        self._wc_check_worker = None
        self._wc_slug_map = {}
        self._sql_dejavu_codes = set()
        self._tree_bulk_update = False
        self._category_image_url_cache = {}
        self._category_pixmap_cache = {}
        self._current_hover_item = None
        self._category_images_map = self._load_category_images_map()
        self._loading_groups = False
        self._initial_load_started = False
        self._groups_load_generation = 0
        self._refresh_button_default_text = "🔄 بروزرسانی"
        self._lists_splitter_layout_applied = False
        self.init_ui()

        self._sync_started_at = 0.0
        self._live_log_hint = ""

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

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName("log_view")
        self.log_view.setLayoutDirection(Qt.LeftToRight)
        self.log_view.setMinimumWidth(260)
        self.splitter.addWidget(self.log_view)

        right_panel = QWidget()
        layout = QVBoxLayout(right_panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.log_actions = LogActionRail(clear_text="حذف لاگ‌های تب دسته‌بندی", parent=self)

        layout.addWidget(QLabel("✅ انتخاب گروه‌های اصلی و فرعی:"))

        # ── جستجو + انتخاب همه/هیچ ─────────────────────
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 جستجو در گروه‌ها...")
        self.search_input.setLayoutDirection(Qt.RightToLeft)
        self.search_input.setMinimumHeight(36)
        self.search_input.textChanged.connect(self._filter_tree)
        search_row.addWidget(self.search_input, 1)

        self.category_link_filter = QComboBox()
        self.category_link_filter.addItem("همه گروه‌ها", "all")
        self.category_link_filter.addItem("✅ فقط لینک‌شده به فروشگاه", "linked")
        self.category_link_filter.addItem("⭕ فقط لینک‌نشده", "unlinked")
        self.category_link_filter.setMinimumHeight(36)
        self.category_link_filter.currentIndexChanged.connect(
            lambda _=0: self._filter_tree(self.search_input.text())
        )
        search_row.addWidget(self.category_link_filter)

        self._tree_selection_toggle = attach_selection_toggle(
            search_row,
            self,
            on_select_all=self._select_all_tree_groups,
            on_select_none=self._select_none_tree_groups,
        )
        layout.addLayout(search_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["نام گروه"])
        self.tree.setLayoutDirection(Qt.RightToLeft)
        self.tree.setItemDelegate(RightAlignedCheckableItemDelegate(self.tree))
        self.tree.setMouseTracking(True)
        self.tree.setStyleSheet("QTreeWidget::item { padding: 4px 10px 4px 4px; }")
        self.tree.headerItem().setTextAlignment(0, Qt.AlignRight | Qt.AlignVCenter)
        self.tree.setMinimumWidth(240)
        self.tree.itemEntered.connect(self.on_group_hover)
        self.tree.viewport().installEventFilter(self)

        self.image_preview = QLabel(None)
        self.image_preview.setWindowFlags(Qt.ToolTip)
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setStyleSheet(
            "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px;"
            "padding: 4px;"
        )
        self.image_preview.setVisible(False)

        self.tree.itemChanged.connect(self._handle_item_changed)
        self.tree.itemClicked.connect(self._on_tree_item_clicked)

        self.selected_list = QListWidget()
        self.selected_list.setLayoutDirection(Qt.RightToLeft)
        self.selected_list.setMouseTracking(True)
        self.selected_list.setItemDelegate(RightAlignedCheckableItemDelegate(self.selected_list))
        self.selected_list.setStyleSheet("QListWidget::item { padding: 4px 10px 4px 4px; }")
        self.selected_list.setMinimumWidth(200)
        self.selected_list.itemEntered.connect(self._on_selected_hover)
        self.selected_list.viewport().installEventFilter(self)

        # دو ستون کنار هم با splitter — درخت انتخاب (راست) + انتخاب‌شده‌ها (چپ)
        self.lists_splitter = QSplitter(Qt.Horizontal)
        self.lists_splitter.setLayoutDirection(Qt.LeftToRight)
        self.lists_splitter.setHandleWidth(6)
        self.lists_splitter.setChildrenCollapsible(False)
        self.lists_splitter.setMinimumHeight(300)

        tree_section = QWidget()
        tree_section_layout = QVBoxLayout(tree_section)
        tree_section_layout.setContentsMargins(0, 0, 0, 0)
        tree_section_layout.setSpacing(4)
        tree_section_layout.addWidget(QLabel("🗂️ همه گروه‌ها:"))
        tree_section_layout.addWidget(self.tree, 1)

        selected_section = QWidget()
        selected_section_layout = QVBoxLayout(selected_section)
        selected_section_layout.setContentsMargins(0, 0, 0, 0)
        selected_section_layout.setSpacing(4)
        selected_section_layout.addWidget(QLabel("📋 گروه‌های انتخاب‌شده:"))
        selected_section_layout.addWidget(self.selected_list, 1)

        # چپ: انتخاب‌شده | راست: درخت (مطابق RTL)
        self.lists_splitter.addWidget(selected_section)
        self.lists_splitter.addWidget(tree_section)
        self.lists_splitter.setStretchFactor(0, 2)
        self.lists_splitter.setStretchFactor(1, 3)
        self._restore_lists_splitter_sizes()
        self.lists_splitter.splitterMoved.connect(self._schedule_save_lists_splitter_sizes)

        layout.addWidget(self.lists_splitter, 1)

        layout.addWidget(QLabel("✔️ تغییر انتخاب‌ها به‌صورت خودکار ذخیره و در تب محصولات اعمال می‌شود."))

        self.status_label = QLabel("✓ آماده — برای بارگذاری دکمه بروزرسانی را بزنید")
        self._set_categories_status("ready", self.status_label.text())
        layout.addWidget(self.status_label)

        self.load_progress = QProgressBar()
        self.load_progress.setRange(0, 0)
        self.load_progress.setTextVisible(False)
        self.load_progress.setFixedHeight(8)
        self.load_progress.setVisible(False)
        layout.addWidget(self.load_progress)

        self.refresh_button = CompactCaptionButton(self._refresh_button_default_text)
        self.refresh_button.clicked.connect(self.on_refresh_clicked)

        self.wc_check_button = CompactCaptionButton("🔍 بررسی وضعیت")
        self.wc_check_button.setToolTip("بررسی وضعیت دسته‌بندی‌ها در فروشگاه")
        self.wc_check_button.clicked.connect(self._on_wc_check_clicked)

        self._sync_button_idle_text = "📤 همگام‌سازی"
        self._sync_button_stop_text = "⏹ توقف همگام‌سازی"
        self.sync_button = CompactCaptionButton(self._sync_button_idle_text)
        self.sync_button.clicked.connect(self._on_sync_button_clicked)

        self._cat_images_idle_text = "📷 ارسال تصاویر"
        self._cat_images_idle_style = (
            "QPushButton { background-color: #1a6b2e; color: white; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background-color: #228B3A; }"
            "QPushButton:disabled { background-color: #666; }"
        )
        self._cat_images_stop_style = (
            "QPushButton { background-color: #b45309; color: white; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background-color: #d97706; }"
        )
        self.send_cat_images_button = CompactCaptionButton(self._cat_images_idle_text)
        self.send_cat_images_button.setProperty("compactActionRole", "images")
        self.send_cat_images_button.setToolTip("ارسال تصاویر دسته‌بندی‌ها به فروشگاه")
        self.send_cat_images_button.clicked.connect(self._on_send_cat_images_clicked)

        self.wc_admin_button = make_wc_admin_open_button(
            self, "categories", button_factory=CompactCaptionButton
        )

        self._action_ops = TabActionController(self)
        self._action_ops.register(
            "refresh",
            ActionSpec(
                button=self.refresh_button,
                idle_text=self._refresh_button_default_text,
                stop_text="⏹ توقف بارگذاری",
                on_stop=self._stop_groups_load,
            ),
        )
        self._action_ops.register(
            "wc_check",
            ActionSpec(
                button=self.wc_check_button,
                idle_text="🔍 بررسی وضعیت",
                on_stop=self._stop_wc_check,
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
                on_stop=self.stop_categories_sync,
            ),
        )
        self._action_ops.register(
            "cat_images",
            ActionSpec(
                button=self.send_cat_images_button,
                idle_text=self._cat_images_idle_text,
                idle_style=self._cat_images_idle_style,
                stop_style=self._cat_images_stop_style,
                on_stop=self._stop_category_images_upload,
            ),
        )
        self._action_ops.register_extra_widgets(
            self.search_input,
            self.tree,
            self.selected_list,
            self._tree_selection_toggle,
        )

        layout.addWidget(
            build_responsive_action_row(
                [
                    self.refresh_button,
                    self.wc_check_button,
                    self.sync_button,
                    self.send_cat_images_button,
                    self.wc_admin_button,
                ],
                parent=right_panel,
            )
        )

        self.splitter.addWidget(right_panel)
        self.log_panel_controller = LogPanelController(
            splitter=self.splitter,
            button=self.log_actions.toggle_button,
            open_size=380,
            duration_ms=160,
            log_widget=self.log_view,
            parent=self
        )
        self.log_actions.bind_toggle(self.log_panel_controller.toggle)
        self.log_actions.bind_clear(self.clear_tab_logs)
        self.log_panel_controller.collapse_initial()  # پیش‌فرض: لاگ مخفی — با دکمه‌ی کناری نمایش داده می‌شود

        main_layout.addWidget(self.splitter, 1)
        main_layout.addWidget(self.log_actions)

        self.setLayout(main_layout)
        self.refresh_logs()

    def _restore_lists_splitter_sizes(self):
        cfg = self.config or load_secure_config(None) or {}
        raw = cfg.get(CATEGORY_LISTS_SPLITTER_KEY)
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            try:
                left = max(int(raw[0]), 160)
                right = max(int(raw[1]), 200)
                self.lists_splitter.setSizes([left, right])
                return
            except (TypeError, ValueError):
                pass
        self.lists_splitter.setSizes(list(DEFAULT_CATEGORY_LISTS_SPLITTER_SIZES))

    def _schedule_save_lists_splitter_sizes(self, *_args):
        timer = getattr(self, "_lists_splitter_save_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._save_lists_splitter_sizes)
            self._lists_splitter_save_timer = timer
        timer.start()

    def _save_lists_splitter_sizes(self):
        sizes = self.lists_splitter.sizes()
        if len(sizes) < 2 or sum(sizes) <= 0:
            return
        cfg = load_secure_config(None) or {}
        cfg[CATEGORY_LISTS_SPLITTER_KEY] = [int(sizes[0]), int(sizes[1])]
        save_secure_config(cfg)
        self.config = cfg

    def showEvent(self, event):
        super().showEvent(event)
        if self._lists_splitter_layout_applied:
            return
        self._lists_splitter_layout_applied = True
        QTimer.singleShot(0, self._restore_lists_splitter_sizes)

    def _ops_busy(self) -> bool:
        ops = getattr(self, "_action_ops", None)
        return bool(ops and ops.busy)

    def ensure_tab_data_loaded(self):
        """بارگذاری SQL فقط با دکمه بروزرسانی یا پس از تعویض دیتابیس."""
        from sync_app.core.tab_operation_guard import consume_pending_sql_reload

        consume_pending_sql_reload(self, lambda: self.load_groups(silent=False, manual=False))

    def _set_categories_status(self, state, text):
        styles = {
            "ready": ("#dcfce7", "#16a34a"),
            "loading": ("#fef3c7", "#92400e"),
            "success": ("#dcfce7", "#16a34a"),
            "warning": ("#fef3c7", "#92400e"),
            "error": ("#fee2e2", "#b91c1c"),
            "info": ("#dbeafe", "#1d4ed8"),
        }
        bg, fg = styles.get(state, styles["ready"])
        self.status_label.setText(self._rtl_display(text))
        self.status_label.setStyleSheet(
            f"background-color: {bg}; color: {fg}; padding: 8px 12px; "
            "border-radius: 6px; font-weight: bold; font-size: 12px;"
        )

    def _begin_groups_load(self, manual=False):
        self._loading_groups = True
        self.load_progress.setVisible(True)
        self._action_ops.begin("refresh", lock_tabs=False)
        self._set_categories_status("loading", "⏳ در حال دریافت گروه‌ها از SQL...")
        if manual:
            log.info("🔄 کاربر: بروزرسانی گروه‌های دسته‌بندی آغاز شد.")

    def _end_groups_load(self):
        self._loading_groups = False
        self.load_progress.setVisible(False)
        if self._action_ops.active == "refresh":
            self._action_ops.end()

    def _stop_groups_load(self):
        self._groups_load_generation += 1
        self._loading_groups = False
        self.load_progress.setVisible(False)
        self.tree.blockSignals(False)
        self._set_categories_status("warning", "⏹ بارگذاری گروه‌ها متوقف شد.")
        if self._action_ops.active == "refresh":
            self._action_ops.end()

    def _fetch_groups_from_sql(self, config, previously_selected_sub_groups):
        conn, auth_mode, conn_string = open_sql_connection(config, timeout=3)
        cursor = conn.cursor()
        cursor.execute("SELECT M_Groupcode, M_GroupName FROM M_Group ORDER BY M_Groupcode")
        main_groups = {
            str(row[0]).strip(): str(row[1]).strip()
            for row in cursor.fetchall()
        }
        cursor.execute(
            "SELECT M_Groupcode, S_Groupcode, S_GroupName FROM S_Group ORDER BY M_Groupcode, S_Groupcode"
        )
        sub_groups = [
            (str(row[0]).strip(), str(row[1]).strip(), str(row[2]).strip())
            for row in cursor.fetchall()
        ]
        conn.close()
        return {
            "main_groups": main_groups,
            "sub_groups": sub_groups,
            "auth_mode": auth_mode,
            "conn_string": conn_string,
            "previously_selected_sub_groups": previously_selected_sub_groups,
        }

    def load_groups(self, silent=False, manual=False):
        if not LicenseTab.guard_usable(self):
            return
        if self._loading_groups or self._ops_busy():
            return
        if manual and not ensure_connectivity(self, need_sql=True, need_wc=False):
            return

        self._groups_load_generation += 1
        generation = self._groups_load_generation
        self.tree.blockSignals(True)
        self.config = load_secure_config(None)
        previously_selected_sub_groups = set(self.config.get("SELECTED_SUB_GROUPS", []))
        self._begin_groups_load(manual=manual)

        def _worker():
            return self._fetch_groups_from_sql(self.config, previously_selected_sub_groups)

        def _done(payload):
            if generation != self._groups_load_generation:
                return
            try:
                self._apply_groups_payload(payload, silent=silent)
                payload = payload or {}
                main_count = len(payload.get("main_groups") or {})
                sub_count = len(payload.get("sub_groups") or [])
                selected_count = len(self.config.get("SELECTED_SUB_GROUPS", []))
                self._set_categories_status(
                    "success",
                    f"✅ {main_count} گروه اصلی، {sub_count} زیرگروه ({selected_count} انتخاب‌شده)",
                )
                log.info(
                    f"✅ بروزرسانی دسته‌بندی‌ها: {main_count} گروه اصلی، "
                    f"{sub_count} زیرگروه، {selected_count} انتخاب‌شده"
                )
                self._end_groups_load()
                if manual:
                    from sync_app.core.integrations.erp_provider import erp_provider_label

                    QMessageBox.information(
                        self,
                        "بروزرسانی موفق",
                        f"{main_count} گروه اصلی و {sub_count} زیرگروه از {erp_provider_label(self.config)} بارگذاری شد.\n"
                        f"تعداد انتخاب‌شده: {selected_count}",
                    )
            except Exception as e:
                err = format_db_error(e)
                self.tree.blockSignals(False)
                self._set_categories_status("error", f"❌ خطا در بارگذاری: {err[:120]}")
                log.error(f"❌ خطا در بارگذاری گروه‌ها: {err}")
                self._end_groups_load()
                if manual:
                    QMessageBox.critical(self, "خطا در بارگذاری گروه‌ها", err)

        def _fail(error_msg):
            if generation != self._groups_load_generation:
                return
            self.tree.blockSignals(False)
            err = format_db_error(Exception(str(error_msg)))
            append_system_log("categories", f"خطا در بارگذاری گروه‌ها: {err}", level="ERROR")
            self._set_categories_status("error", f"❌ خطا در بارگذاری گروه‌ها: {err[:120]}")
            log.error(f"❌ خطا در بارگذاری گروه‌ها: {err}")
            self._end_groups_load()
            if manual:
                QMessageBox.critical(self, "خطا در بارگذاری گروه‌ها", err)

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _apply_groups_payload(self, payload, silent=False):
        try:
            payload = payload or {}
            main_groups = payload.get("main_groups") or {}
            sub_groups = payload.get("sub_groups") or []
            auth_mode = payload.get("auth_mode")
            conn_string = payload.get("conn_string")
            previously_selected_sub_groups = set(payload.get("previously_selected_sub_groups") or [])

            repaired_config = repair_sql_config_if_needed(self.config, auth_mode, conn_string)
            if repaired_config != self.config:
                save_secure_config(repaired_config)
                self.config = repaired_config

            self.tree.clear()
            self.selected_list.clear()
            self._sql_dejavu_codes.clear()
            tree_items = {}

            for m_code, m_name in main_groups.items():
                parent_item = QTreeWidgetItem(self.tree)
                parent_item.setData(0, Qt.UserRole, m_name)
                parent_item.setData(0, Qt.UserRole + 1, m_code)
                parent_item.setText(0, self._format_group_text(m_name, m_code))
                parent_item.setTextAlignment(0, Qt.AlignRight | Qt.AlignVCenter)
                parent_item.setFlags(parent_item.flags() | Qt.ItemIsUserCheckable)
                parent_item.setCheckState(0, Qt.Unchecked)
                tree_items[m_code] = parent_item
                self._sql_dejavu_codes.add(m_code)

            for m_code, s_code, s_name in sub_groups:
                if m_code in tree_items:
                    parent_item = tree_items[m_code]
                    child_item = QTreeWidgetItem(parent_item)
                    child_item.setData(0, Qt.UserRole, s_name)
                    child_item.setData(0, Qt.UserRole + 1, s_code)
                    child_item.setText(0, self._format_group_text(s_name, s_code))
                    child_item.setTextAlignment(0, Qt.AlignRight | Qt.AlignVCenter)
                    child_item.setFlags(child_item.flags() | Qt.ItemIsUserCheckable)

                    full_code = m_code + s_code
                    self._sql_dejavu_codes.add(full_code)
                    if full_code in previously_selected_sub_groups:
                        child_item.setCheckState(0, Qt.Checked)
                    else:
                        child_item.setCheckState(0, Qt.Unchecked)
        except Exception as e:
            err = format_db_error(e)
            append_system_log("categories", f"خطا در بارگذاری گروه‌ها: {err}", level="ERROR")
            raise

        # بازحساب وضعیت تیک پدرها از روی فرزندان (هنوز signals بلوک هستند)
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            num_children = parent.childCount()
            if num_children == 0:
                continue
            num_checked = sum(
                1 for j in range(num_children)
                if parent.child(j).checkState(0) == Qt.Checked
            )
            if num_checked == 0:
                parent.setCheckState(0, Qt.Unchecked)
            elif num_checked == num_children:
                parent.setCheckState(0, Qt.Checked)
                parent.setExpanded(True)
            else:
                parent.setCheckState(0, Qt.PartiallyChecked)
                parent.setExpanded(True)

        self.tree.blockSignals(False)
        self.update_selected_list_only()

        if self._wc_slug_map:
            self._apply_wc_status_to_tree()

    def _on_tree_item_clicked(self, item, column):
        """کلیک روی ردیف گروه اصلی - cascade توسط _handle_item_changed انجام می‌شود"""
        # ⚠️ نباید اینجا toggle کنیم: itemChanged قبل از itemClicked فایر می‌شه
        # و اگر اینجا هم toggle کنیم، دو بار toggle = بازگشت به حالت قبل
        # _handle_item_changed به تنهایی cascade فرزندان را مدیریت می‌کند
        return

    def _handle_item_changed(self, item, column):
        """وقتی تیک گروه اصلی زده می‌شود، همه فرزندانش انتخاب/رد انتخاب می‌شوند"""
        if getattr(self, "_tree_bulk_update", False):
            return
        is_parent = item.childCount() > 0
        if is_parent:
            check_state = item.checkState(column)
            self.tree.blockSignals(True)
            for i in range(item.childCount()):
                item.child(i).setCheckState(column, check_state)
            self.tree.blockSignals(False)
            self.save_selected_groups()
            return

        # فرزند تغییر کرد - آپدیت وضعیت چک والد
        parent = item.parent()
        if parent:
            checked_count = sum(
                1 for i in range(parent.childCount())
                if parent.child(i).checkState(0) == Qt.Checked
            )
            total = parent.childCount()
            self.tree.blockSignals(True)
            if checked_count == total:
                parent.setCheckState(0, Qt.Checked)
            elif checked_count == 0:
                parent.setCheckState(0, Qt.Unchecked)
            else:
                parent.setCheckState(0, Qt.PartiallyChecked)
            self.tree.blockSignals(False)

        self.save_selected_groups()

    def _iter_visible_sub_groups(self):
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            if parent.isHidden():
                continue
            for j in range(parent.childCount()):
                child = parent.child(j)
                if not child.isHidden():
                    yield parent, child

    def _select_all_tree_groups(self):
        if self._ops_busy():
            return
        self._tree_bulk_update = True
        self.tree.blockSignals(True)
        try:
            touched_parents = set()
            for parent, child in self._iter_visible_sub_groups():
                child.setCheckState(0, Qt.Checked)
                touched_parents.add(parent)
            for parent in touched_parents:
                visible_children = [
                    parent.child(j)
                    for j in range(parent.childCount())
                    if not parent.child(j).isHidden()
                ]
                checked = sum(1 for c in visible_children if c.checkState(0) == Qt.Checked)
                total = len(visible_children)
                if total == 0:
                    continue
                if checked == total:
                    parent.setCheckState(0, Qt.Checked)
                elif checked == 0:
                    parent.setCheckState(0, Qt.Unchecked)
                else:
                    parent.setCheckState(0, Qt.PartiallyChecked)
        finally:
            self.tree.blockSignals(False)
            self._tree_bulk_update = False
        self.save_selected_groups()

    def _select_none_tree_groups(self):
        if self._ops_busy():
            return
        self._tree_bulk_update = True
        self.tree.blockSignals(True)
        try:
            touched_parents = set()
            for parent, child in self._iter_visible_sub_groups():
                child.setCheckState(0, Qt.Unchecked)
                touched_parents.add(parent)
            for parent in touched_parents:
                visible_children = [
                    parent.child(j)
                    for j in range(parent.childCount())
                    if not parent.child(j).isHidden()
                ]
                checked = sum(1 for c in visible_children if c.checkState(0) == Qt.Checked)
                total = len(visible_children)
                if total == 0:
                    continue
                if checked == total:
                    parent.setCheckState(0, Qt.Checked)
                elif checked == 0:
                    parent.setCheckState(0, Qt.Unchecked)
                else:
                    parent.setCheckState(0, Qt.PartiallyChecked)
        finally:
            self.tree.blockSignals(False)
            self._tree_bulk_update = False
        self.save_selected_groups()

    def _filter_tree(self, text):
        """فیلتر کردن درخت بر اساس متن جستجو + وضعیت لینک فروشگاه"""
        search = text.strip().lower()
        link_mode = self.category_link_filter.currentData() if hasattr(self, "category_link_filter") else "all"

        def _link_ok(tree_item):
            if link_mode == "all":
                return True
            # همون علامتی که با _apply_wc_status_to_tree روی متن گذاشته شده رو
            # مستقیم می‌خونیم — تا با چیزی که کاربر واقعاً می‌بینه ۱۰۰٪ هماهنگ باشه
            is_linked = tree_item.text(0).strip().startswith("✅")
            return is_linked if link_mode == "linked" else not is_linked

        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            parent_name = (parent.data(0, Qt.UserRole) or "")
            parent_code = (parent.data(0, Qt.UserRole + 1) or "")
            parent_match = (not search or search in parent_name.lower() or search in parent_code.lower())
            parent_link_ok = _link_ok(parent)

            any_child_visible = False
            for j in range(parent.childCount()):
                child = parent.child(j)
                child_name = (child.data(0, Qt.UserRole) or "")
                child_code = (child.data(0, Qt.UserRole + 1) or "")
                child_match = not search or search in child_name.lower() or search in child_code.lower() or parent_match
                child_link_ok = _link_ok(child)
                child.setHidden(not (child_match and child_link_ok))
                if child_match and child_link_ok:
                    any_child_visible = True

            parent.setHidden(not (((parent_match and parent_link_ok) or any_child_visible)))
            if search and any_child_visible:
                parent.setExpanded(True)

    def update_selected_list_only(self):
        selected_display = []
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            m_name = parent.data(0, Qt.UserRole) or parent.text(0)
            m_code = parent.data(0, Qt.UserRole + 1) or ""
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    child_name = child.data(0, Qt.UserRole) or child.text(0)
                    child_code = child.data(0, Qt.UserRole + 1) or ""
                    full_code = m_code + child_code
                    selected_display.append({
                        "text": self._format_selection_text(m_name, m_code, child_name, child_code),
                        "full_code": full_code,
                        "s_name": child_name,
                        "m_name": m_name,
                        "m_code": m_code,
                        "s_code": child_code,
                    })

        self._populate_selected_list(selected_display)

    def save_selected_groups(self):
        selected_display = []
        selected_main_codes = set()
        selected_sub_codes = []

        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            m_name = parent.data(0, Qt.UserRole) or parent.text(0)
            m_code = parent.data(0, Qt.UserRole + 1) or ""

            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    s_name = child.data(0, Qt.UserRole) or child.text(0)
                    s_code = child.data(0, Qt.UserRole + 1) or ""
                    full_code = m_code + s_code

                    selected_main_codes.add(m_code)
                    selected_sub_codes.append(full_code)
                    selected_display.append({
                        "text": self._format_selection_text(m_name, m_code, s_name, s_code),
                        "full_code": full_code,
                        "s_name": s_name,
                        "m_name": m_name,
                        "m_code": m_code,
                        "s_code": s_code,
                    })

        self._populate_selected_list(selected_display)

        self.config["SELECTED_CATEGORY_GROUPS"] = list(selected_main_codes)
        self.config["SELECTED_SUB_GROUPS"] = selected_sub_codes
        save_secure_config(self.config)

        from sync_app.core.tab_operation_guard import run_sql_reload_if_active

        if self.product_tab_ref:
            run_sql_reload_if_active(self.product_tab_ref, self.product_tab_ref.load_products)
        if self.variation_tab_ref:
            run_sql_reload_if_active(self.variation_tab_ref, self.variation_tab_ref.load_variations)

    def _populate_selected_list(self, entries):
        """entries: list of dicts with keys: text, full_code, s_name, m_code, m_name, ..."""
        from sync_app.core.stock_mode import get_category_stock_mode
        from sync_app.core.category_price_list import get_category_price_list_index

        self.selected_list.clear()
        seen_main_codes = set()
        for entry in entries:
            full_code = entry["full_code"]
            text = entry["text"]
            s_name = entry["s_name"]
            m_code = entry.get("m_code", "")
            m_name = entry.get("m_name", "")

            if m_code and m_code not in seen_main_codes:
                seen_main_codes.add(m_code)
                header_item = QListWidgetItem()
                header_item.setFlags(Qt.NoItemFlags)
                header_row = CategoryRowWidget(
                    f"🗂 {m_name} (کل دسته)",
                    on_upload=None,
                    on_stock_mode_changed=lambda mode, mc=m_code: self._set_category_stock_mode(mc, mode),
                    on_price_list_changed=lambda idx, mc=m_code: self._set_category_price_list(mc, idx),
                    parent=self.selected_list,
                    show_image_buttons=False,
                )
                header_row.set_stock_mode(get_category_stock_mode(self.config, m_code))
                header_row.set_price_list_index(get_category_price_list_index(self.config, m_code))
                header_item.setSizeHint(QSize(0, 40))
                self.selected_list.addItem(header_item)
                self.selected_list.setItemWidget(header_item, header_row)

            item = QListWidgetItem()
            item.setData(Qt.UserRole, full_code)
            item.setData(Qt.UserRole + 1, s_name)
            uploaded_path = self._category_images_map.get(full_code, "")
            item.setData(Qt.UserRole + 2, uploaded_path)

            row_widget = CategoryRowWidget(
                text,
                on_upload=lambda _=False, fc=full_code, it=item: self._upload_image_for_category(fc, it),
                on_clear=lambda fc=full_code, it=item: self._clear_image_for_category(fc, it),
                on_stock_mode_changed=lambda mode, fc=full_code: self._set_category_stock_mode(fc, mode),
                on_price_list_changed=lambda idx, fc=full_code: self._set_category_price_list(fc, idx),
                parent=self.selected_list,
            )
            row_widget.set_stock_mode(get_category_stock_mode(self.config, full_code))
            row_widget.set_price_list_index(get_category_price_list_index(self.config, full_code))
            row_widget.set_has_image(self._category_has_local_image(full_code))
            item.setSizeHint(QSize(0, 48))

            self.selected_list.addItem(item)
            self.selected_list.setItemWidget(item, row_widget)

    def _format_group_text(self, name, code):
        return self._rtl_display(f"{name} (کد: {code})")

    def _set_category_stock_mode(self, group_code, mode):
        from sync_app.core.stock_mode import set_category_stock_mode
        set_category_stock_mode(group_code, mode)
        self.config = load_secure_config(None) or {}

    def _set_category_price_list(self, group_code, index):
        from sync_app.core.category_price_list import set_category_price_list_index
        set_category_price_list_index(group_code, index)
        self.config = load_secure_config(None) or {}

    def _format_selection_text(self, main_name, main_code, child_name, child_code):
        return self._rtl_display(
            f"گروه اصلی: {main_name} (کد: {main_code}) | زیرگروه: {child_name} (کد: {child_code})"
        )

    def _rtl_display(self, text):
        return f"\u202B{text}\u202C"

    def _normalize_name(self, name):
        return re.sub(r"\s+", " ", (name or "").strip()).lower()

    def _expected_slug(self, name, code):
        return dejavu_category_slug(code)

    def _wc_category_synced(self, name, code):
        """ملاک: کد ERP در slug فروشگاه + تطابق نام با ERP"""
        if not self._wc_slug_map:
            return False
        code = str(code or "").strip()
        expected = self._expected_slug(name, code)
        entry = self._wc_slug_map.get(expected)
        if not entry:
            for slug, item in self._wc_slug_map.items():
                if extract_code_from_wc_slug(slug) == code:
                    entry = item
                    break
        if not entry:
            return False
        wc_name = (entry.get("name") or "").strip()
        return self._normalize_name(wc_name) == self._normalize_name(name)

    def _collect_slug_name_mismatches(self):
        """نامک در WC هست ولی نام با ERP یکی نیست."""
        rows = []
        if not self._wc_slug_map:
            return rows

        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            m_code = (parent.data(0, Qt.UserRole + 1) or "").strip()
            m_name = (parent.data(0, Qt.UserRole) or "").strip()
            slug = self._expected_slug(m_name, m_code)
            entry = self._wc_slug_map.get(slug)
            if entry and not self._wc_category_synced(m_name, m_code):
                rows.append({
                    "wc_id": entry.get("id"),
                    "erp_name": m_name,
                    "wc_name": entry.get("name", ""),
                    "slug": slug,
                    "code": m_code,
                    "parent_code": None,
                })

            for j in range(parent.childCount()):
                child = parent.child(j)
                s_code = (child.data(0, Qt.UserRole + 1) or "").strip()
                s_name = (child.data(0, Qt.UserRole) or "").strip()
                full_code = m_code + s_code
                slug = self._expected_slug(s_name, full_code)
                entry = self._wc_slug_map.get(slug)
                if entry and not self._wc_category_synced(s_name, full_code):
                    rows.append({
                        "wc_id": entry.get("id"),
                        "erp_name": s_name,
                        "wc_name": entry.get("name", ""),
                        "slug": slug,
                        "code": full_code,
                        "parent_code": m_code,
                    })
        return rows

    def _show_mismatch_dialog(self, mismatches):
        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label = erp_provider_label(self.config)
        dialog = QDialog(self)
        dialog.setWindowTitle("نامک موجود — نام مغایر")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.setMinimumWidth(580)
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel(
            f"{len(mismatches)} دسته در فروشگاه نامک درست دارند ولی نام با {erp_label} فرق دارد.\n"
            f"می‌توانید نام و نامک را طبق {erp_label} در فروشگاه به‌روزرسانی کنید."
        ))

        lst = QListWidget()
        lst.setLayoutDirection(Qt.RightToLeft)
        for row in mismatches:
            item = QListWidgetItem(
                f"{erp_label}: {row['erp_name']}  ←  WC: {row['wc_name']}  |  slug: {row['slug']}"
            )
            item.setData(Qt.UserRole, row)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lst.addItem(item)
        layout.addWidget(lst)

        row_btns = QHBoxLayout()
        fix_btn = QPushButton(f"به‌روزرسانی همه در فروشگاه (طبق {erp_label})")
        fix_btn.clicked.connect(lambda: self._repair_wc_mismatches(mismatches, dialog))
        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(dialog.reject)
        row_btns.addWidget(fix_btn)
        row_btns.addStretch()
        row_btns.addWidget(close_btn)
        layout.addLayout(row_btns)
        dialog.exec_()

    def _repair_wc_mismatches(self, mismatches, dialog):
        cfg = load_secure_config(None) or {}
        auth = get_wc_auth(cfg)
        timeout = int(cfg.get("WC_TIMEOUT", 30) or 30)
        fixed = 0
        for row in mismatches:
            wc_id = row.get("wc_id")
            if not wc_id:
                continue
            url = wc_endpoint(cfg.get("WC_URL", ""), f"products/categories/{wc_id}")
            payload = {"name": row["erp_name"], "slug": row["slug"]}
            if row.get("parent_code"):
                parent_slug = self._expected_slug(
                    self._name_for_code(row["parent_code"], main=True),
                    row["parent_code"],
                )
                parent = self._wc_slug_map.get(parent_slug)
                if parent:
                    payload["parent"] = parent.get("id", 0)
            try:
                resp = requests.put(url, auth=auth, json=payload, timeout=timeout)
                if resp.status_code in (200, 201):
                    fixed += 1
                    log.info(f"✅ به‌روزرسانی WC دسته: {row['erp_name']}")
            except Exception as exc:
                log.error(f"❌ خطا در به‌روزرسانی WC دسته {row['erp_name']}: {exc}")
        QMessageBox.information(self, "پایان", f"{fixed} دسته در فروشگاه به‌روزرسانی شد.")
        dialog.accept()
        self.check_wc_status()

    def _name_for_code(self, code, main=False):
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            m_code = (parent.data(0, Qt.UserRole + 1) or "").strip()
            if main and m_code == code:
                return (parent.data(0, Qt.UserRole) or "").strip()
            for j in range(parent.childCount()):
                child = parent.child(j)
                s_code = (child.data(0, Qt.UserRole + 1) or "").strip()
                if m_code + s_code == code:
                    return (child.data(0, Qt.UserRole) or "").strip()
        return ""

    # ── بررسی وضعیت دسته‌بندی‌ها در فروشگاه ──────────────────
    def _on_wc_check_clicked(self):
        self._action_ops.handle_click("wc_check", self._start_wc_check)

    def _start_wc_check(self):
        """دریافت دسته‌بندی‌های فروشگاه و مقایسه نامک با درخت SQL"""
        if not ensure_connectivity(self, need_sql=False, need_wc=True, live=True):
            return
        if self._wc_check_thread is not None:
            return
        if not self._action_ops.begin("wc_check", working_text="⏳ در حال بررسی..."):
            return

        self._set_categories_status("loading", "🔍 در حال اتصال به فروشگاه...")
        self.config = load_secure_config(None)

        self._wc_check_thread = QThread(self)
        self._wc_check_worker = WCCategoryCheckWorker(self.config)
        self._wc_check_worker.moveToThread(self._wc_check_thread)
        self._wc_check_thread.started.connect(self._wc_check_worker.run)
        self._wc_check_worker.finished.connect(self._on_wc_check_done)
        self._wc_check_worker.error.connect(self._on_wc_check_error)
        self._wc_check_worker.error.connect(self._wc_check_thread.quit)
        self._wc_check_worker.finished.connect(self._wc_check_thread.quit)
        self._wc_check_worker.finished.connect(self._wc_check_worker.deleteLater)
        self._wc_check_thread.finished.connect(self._wc_check_thread.deleteLater)
        self._wc_check_thread.finished.connect(self._on_wc_check_thread_done)
        self._wc_check_thread.start()

    def check_wc_status(self):
        if self._ops_busy():
            return
        self._start_wc_check()

    def _stop_wc_check(self):
        if self._wc_check_worker is not None:
            self._wc_check_worker.request_cancel()
        if self._wc_check_thread is not None:
            self._wc_check_thread.quit()
        self._action_ops.set_stopping("wc_check")
        self._set_categories_status("warning", "⏹ در حال توقف بررسی فروشگاه...")

    def _apply_icons_from_category_map(self):
        """بعد sync از category_map بخون."""
        try:
            map_path = site_scoped_path("category_map.json")
            with open(map_path, "r", encoding="utf-8") as f:
                cat_map = json.load(f)
        except Exception:
            return
        if not isinstance(cat_map, dict):
            return
        for code, wc_id in cat_map.items():
            slug = dejavu_category_slug(str(code).strip())
            if slug:
                self._wc_slug_map[slug] = {
                    "id": wc_id,
                    "name": "",
                    "slug": slug,
                    "image": {},
                }
        self._apply_wc_status_to_tree()
        self._set_categories_status(
            "success",
            f"✅ {len(cat_map)} دسته همگام شد — برای بررسی کامل Woo دکمه «بررسی وضعیت» را بزنید",
        )

    def _on_wc_check_done(self, wc_slug_map, all_wc_cats):
        """پس از دریافت دسته‌بندی‌های فروشگاه، مقایسه با SQL"""
        self._wc_slug_map = wc_slug_map
        log.info(f"✅ {len(wc_slug_map)} دسته‌بندی از فروشگاه دریافت شد")

        self._apply_wc_status_to_tree()

        # دسته‌بندی‌های فروشگاه که با pattern dejavu تطابق ندارند (orphan)
        orphan_cats = []
        for cat in all_wc_cats:
            slug = unquote((cat.get("slug") or "").strip().lower())
            dejavu_code = extract_code_from_wc_slug(slug)
            if dejavu_code and dejavu_code not in self._sql_dejavu_codes:
                orphan_cats.append({
                    "id": cat.get("id"),
                    "name": cat.get("name", ""),
                    "slug": slug,
                    "dejavu_code": dejavu_code
                })

        status_text = f"✅ بررسی فروشگاه تمام شد - {len(wc_slug_map)} دسته"
        if orphan_cats:
            status_text += f" | {len(orphan_cats)} دسته مغایر"
            log.warning(f"⚠️ {len(orphan_cats)} دسته‌بندی در فروشگاه که در نرم‌افزار نیستند:")
            for cat in orphan_cats:
                log.warning(f"  - {cat['name']} (slug: {cat['slug']})")
            self._show_orphan_dialog(orphan_cats)

        mismatches = self._collect_slug_name_mismatches()
        if mismatches:
            status_text += f" | {len(mismatches)} نام مغایر"
            log.warning(f"⚠️ {len(mismatches)} دسته با نامک موجود ولی نام متفاوت:")
            from sync_app.core.integrations.erp_provider import erp_provider_label

            erp_label = erp_provider_label(self.config)
            for row in mismatches:
                log.warning(
                    f"  - {erp_label}: {row['erp_name']} | WC: {row['wc_name']} | slug: {row['slug']}"
                )
            self._show_mismatch_dialog(mismatches)

        self._set_categories_status("success", status_text)
        self.refresh_logs()

    def _restore_selection_from_config(self):
        """بازگردانی تیک‌ها از config — بعد از به‌روزرسانی متن درخت."""
        self.config = load_secure_config(None) or {}
        selected = set(self.config.get("SELECTED_SUB_GROUPS", []) or [])
        if not selected:
            self.update_selected_list_only()
            return

        self._tree_bulk_update = True
        self.tree.blockSignals(True)
        try:
            for i in range(self.tree.topLevelItemCount()):
                parent = self.tree.topLevelItem(i)
                m_code = (parent.data(0, Qt.UserRole + 1) or "").strip()
                for j in range(parent.childCount()):
                    child = parent.child(j)
                    s_code = (child.data(0, Qt.UserRole + 1) or "").strip()
                    full_code = m_code + s_code
                    child.setCheckState(
                        0,
                        Qt.Checked if full_code in selected else Qt.Unchecked,
                    )
                checked_count = sum(
                    1 for j in range(parent.childCount())
                    if parent.child(j).checkState(0) == Qt.Checked
                )
                total = parent.childCount()
                if checked_count == 0:
                    parent.setCheckState(0, Qt.Unchecked)
                elif checked_count == total:
                    parent.setCheckState(0, Qt.Checked)
                    parent.setExpanded(True)
                else:
                    parent.setCheckState(0, Qt.PartiallyChecked)
                    parent.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
            self._tree_bulk_update = False
        self.update_selected_list_only()

    def _apply_wc_status_to_tree(self):
        """اعمال آیکون وضعیت فروشگاه (🟢/🔴) روی هر آیتم درخت"""
        if not self._wc_slug_map:
            return

        self._tree_bulk_update = True
        self.tree.blockSignals(True)
        try:
            for i in range(self.tree.topLevelItemCount()):
                parent = self.tree.topLevelItem(i)
                m_code = (parent.data(0, Qt.UserRole + 1) or "").strip()
                m_name = (parent.data(0, Qt.UserRole) or "").strip()

                m_synced = self._wc_category_synced(m_name, m_code)
                indicator = "✅ " if m_synced else ""
                parent.setText(0, f"{indicator}{self._format_group_text(m_name, m_code)}")

                for j in range(parent.childCount()):
                    child = parent.child(j)
                    s_code = (child.data(0, Qt.UserRole + 1) or "").strip()
                    s_name = (child.data(0, Qt.UserRole) or "").strip()
                    full_code = m_code + s_code
                    s_synced = self._wc_category_synced(s_name, full_code)
                    child_indicator = "✅ " if s_synced else ""
                    child.setText(0, f"{child_indicator}{self._format_group_text(s_name, s_code)}")
        finally:
            self.tree.blockSignals(False)
            self._tree_bulk_update = False
        self._restore_selection_from_config()

        # چون فیلتر «لینک‌شده/لینک‌نشده» از روی همین متن (✅) تصمیم می‌گیره،
        # بعد از به‌روزرسانی نشانگرها، فیلتر هم باید دوباره اجرا بشه.
        if hasattr(self, "category_link_filter") and hasattr(self, "search_input"):
            self._filter_tree(self.search_input.text())

    def _show_orphan_dialog(self, orphan_cats):
        """دیالوگ دسته‌های فروشگاه بدون معادل ERP — حذف از سایت"""
        dialog = QDialog(self)
        dialog.setWindowTitle("دسته‌بندی‌های مغایر در فروشگاه")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.setMinimumWidth(560)
        dialog_layout = QVBoxLayout(dialog)

        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label = erp_provider_label(self.config)
        label = QLabel(
            f"این دسته‌ها در فروشگاه هستند ولی در {erp_label} نیستند ({len(orphan_cats)} مورد).\n"
            f"ملاک تطابق: نامک (slug). برای همگام‌سازی از تب دسته‌بندی، گروه {erp_label} را تیک بزنید."
        )
        label.setWordWrap(True)
        dialog_layout.addWidget(label)

        orphan_list = QListWidget()
        orphan_list.setLayoutDirection(Qt.RightToLeft)
        for cat in orphan_cats:
            item = QListWidgetItem(
                f"{cat['name']} — نامک: {cat['slug']} — کد استخراج‌شده: {cat.get('dejavu_code', '—')}"
            )
            item.setData(Qt.UserRole, cat)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            orphan_list.addItem(item)
        dialog_layout.addWidget(orphan_list)

        action_row = QHBoxLayout()
        delete_btn = QPushButton("حذف از فروشگاه")
        delete_btn.clicked.connect(lambda: self._delete_orphan_categories(orphan_cats, dialog))
        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(dialog.reject)
        action_row.addWidget(delete_btn)
        action_row.addStretch()
        action_row.addWidget(close_btn)
        dialog_layout.addLayout(action_row)
        dialog.exec_()

    def _delete_orphan_categories(self, orphan_cats, dialog):
        if not orphan_cats:
            dialog.reject()
            return
        answer = QMessageBox.question(
            self,
            "تأیید حذف",
            f"{len(orphan_cats)} دسته از فروشگاه حذف شود؟\nاین عمل قابل بازگشت نیست.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        cfg = load_secure_config(None) or {}
        auth = get_wc_auth(cfg)
        timeout = int(cfg.get("WC_TIMEOUT", 30) or 30)

        deleted = 0
        for cat in orphan_cats:
            try:
                url = wc_endpoint(cfg.get("WC_URL", ""), f"products/categories/{cat['id']}")
                resp = requests.delete(
                    url,
                    auth=auth,
                    params={"force": True},
                    timeout=timeout,
                )
                if resp.status_code in (200, 204):
                    deleted += 1
            except Exception as exc:
                log.error(f"❌ خطا در حذف دسته {cat.get('name')}: {exc}")

        QMessageBox.information(self, "پایان", f"{deleted} دسته از فروشگاه حذف شد.")
        dialog.accept()
        self.check_wc_status()

    def _on_wc_check_error(self, error_msg):
        if str(error_msg).strip() == "متوقف شد":
            log.info("⏹ بررسی وضعیت فروشگاه متوقف شد.")
            self._set_categories_status("warning", "⏹ بررسی وضعیت فروشگاه متوقف شد.")
        else:
            log.error(f"❌ خطای بررسی فروشگاه: {error_msg}")
            status = error_msg.strip().split("\n")[0]
            if len(status) > 140:
                status = status[:137] + "..."
            self._set_categories_status("error", status)
        self.refresh_logs()

    def _on_wc_check_thread_done(self):
        self._wc_check_thread = None
        self._wc_check_worker = None
        if self._action_ops.active == "wc_check":
            self._action_ops.end()

    def on_refresh_clicked(self):
        """دکمه رفرش — بارگذاری واقعی از SQL با بازخورد UI"""
        self._action_ops.handle_click(
            "refresh",
            lambda: self.load_groups(silent=False, manual=True),
        )

    def _tick_sync_ui(self):
        self.refresh_logs()
        if self._action_ops.active != "sync":
            return
        elapsed = int(time.monotonic() - self._sync_started_at)
        step = self._last_sync_step()
        if step:
            self._set_categories_status("loading", f"⏳ {step} ({elapsed}s)")
        else:
            self._set_categories_status("loading", f"⏳ همگام‌سازی دسته‌ها... ({elapsed}s)")

    def _last_sync_step(self):
        try:
            log_path = app_path("sync.log")
            if not os.path.exists(log_path):
                return ""
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            tokens = [t.lower() for t in CATEGORY_LOG_TOKENS]
            for line in reversed(lines[-120:]):
                low = line.lower()
                if not any(tok in low for tok in tokens):
                    continue
                if "▸" in line:
                    part = line.split("▸", 1)[-1].strip()
                    if part:
                        return part[:120]
                stripped = line.strip()
                if stripped:
                    return stripped[:120]
        except Exception:
            pass
        return ""

    def _on_sync_button_clicked(self):
        self._action_ops.handle_click("sync", self.sync_categories)

    def _begin_categories_sync_ui(self):
        self._sync_started_at = time.monotonic()
        self._live_log_hint = "⏳ همگام‌سازی دسته‌ها با فروشگاه..."
        self._action_ops.begin("sync")
        self.load_progress.setVisible(True)
        self._set_categories_status("loading", "⏳ در حال بررسی اتصال فروشگاه...")
        try:
            self.log_panel_controller.ensure_visible()
        except Exception:
            pass
        self._sync_live_timer.start()
        self.log_timer.setInterval(400)

    def _end_categories_sync_ui(self, done_text=None):
        self._sync_live_timer.stop()
        self._live_log_hint = ""
        self.log_timer.setInterval(2000)
        self.load_progress.setVisible(False)
        if self._action_ops.active == "sync":
            self._action_ops.end()

    def stop_categories_sync(self):
        if self._action_ops.active != "sync":
            return
        if cancel_background_sync(self):
            self._action_ops.set_stopping("sync")
            self._live_log_hint = "⏹ درخواست توقف ارسال شد..."
            self._set_categories_status("warning", "⏹ در حال توقف همگام‌سازی...")
            self.refresh_logs()

    def sync_categories(self):
        """همگام‌سازی فقط گروه‌های تیک‌خورده (و نمایان — طبق فیلتر) — پس‌زمینه"""
        self.config = load_secure_config(None) or {}
        selected = self.config.get("SELECTED_SUB_GROUPS", [])
        if not selected:
            QMessageBox.warning(
                self,
                "هشدار",
                "هیچ گروهی انتخاب نشده است.\nلطفاً ابتدا گروه‌های مورد نظر را از درخت بالا تیک بزنید.",
            )
            return

        # اگه فیلتر (جستجو یا وضعیت لینک) فعاله، زیرگروه‌هایی که تیک خوردن
        # ولی الان مخفی‌ان نباید همگام بشن — موقتی، ترجیح واقعی کاربر برای
        # دفعه‌ی بعد دست‌نخورده می‌مونه.
        # محافظ مهم: اگه تنظیمات فعلی مشکوک به خالی/ناقص بودن باشه، اصلاً
        # وارد بازی محدودسازی موقت نشو — چون بعداً ذخیره‌ش می‌تونه کل
        # تنظیمات واقعی رو پاک کنه.
        self._temp_extra_excluded_codes = set()
        if isinstance(self.config, dict) and len(self.config) >= 5:
            self._temp_extra_excluded_codes = self._hidden_checked_sub_codes()
        if self._temp_extra_excluded_codes:
            remaining = [c for c in selected if c not in self._temp_extra_excluded_codes]
            if not remaining:
                QMessageBox.information(
                    self, "چیزی برای ارسال نیست",
                    "همه‌ی گروه‌های تیک‌خورده الان به‌خاطر فیلتر مخفی‌ان.\n"
                    "فیلتر را پاک کنید یا گروه دیگری تیک بزنید.",
                )
                self._temp_extra_excluded_codes = None
                return
            self.config["SELECTED_SUB_GROUPS"] = remaining
            save_secure_config(self.config)
            selected = remaining

        if not wait_for_connectivity_dialog(
            self,
            need_sql=True,
            need_wc=True,
            operation_label="همگام‌سازی دسته‌بندی‌ها",
        ):
            self._restore_temp_excluded_codes()
            self._set_categories_status(
                "warning",
                "⚠️ اتصال SQL یا فروشگاه برقرار نشد — دوباره تلاش کنید.",
            )
            return

        def _job():
            return ProductCategoriesSync.main()

        def _ok(result=None):
            self._end_categories_sync_ui()
            self._restore_temp_excluded_codes()
            self.refresh_logs()
            stats = result if isinstance(result, dict) else {}
            if not stats:
                try:
                    with open(site_scoped_path("category_map.json"), "r", encoding="utf-8") as f:
                        local_map = json.load(f)
                    if isinstance(local_map, dict) and local_map:
                        stats = {
                            "synced": len(local_map),
                            "total": len(local_map),
                            "failed": [],
                            "update_failed": [],
                            "used_local_map": True,
                        }
                except Exception:
                    pass
            failed = stats.get("failed") or []
            update_failed = stats.get("update_failed") or []
            synced = stats.get("synced", 0)
            total = stats.get("total", synced)
            patched = stats.get("products_patched", 0)
            patch_failed = stats.get("products_patch_failed", 0)
            patch_skipped = int(stats.get("products_skipped") or 0)
            used_local = stats.get("used_local_map", False)
            last_err = (stats.get("last_error") or "").strip()

            def _wc_failure_hint():
                if not last_err and not failed:
                    return ""
                return diagnose_wc(
                    config=self.config,
                    error_text=last_err,
                    exc=Exception(last_err) if last_err else None,
                ).full_message()

            if failed and synced == 0:
                names = "، ".join(str(x) for x in failed[:5])
                wc_hint = _wc_failure_hint()
                QMessageBox.warning(
                    self,
                    "همگام‌سازی ناموفق",
                    f"هیچ دسته‌ای در فروشگاه ثبت نشد.\n"
                    f"خطا در: {names}\n\n{wc_hint}",
                )
            elif failed:
                names = "، ".join(str(x) for x in failed[:5])
                extra = ""
                if patched:
                    extra = f"\n\n✅ دسته روی {patched} محصول اعمال شد."
                wc_hint = _wc_failure_hint()
                QMessageBox.warning(
                    self,
                    "همگام‌سازی ناقص",
                    f"{synced} از {total} دسته شناسایی شد.\n"
                    f"خطا در ایجاد: {names}{extra}\n\n{wc_hint}",
                )
            elif synced == 0:
                wc_hint = _wc_failure_hint()
                QMessageBox.warning(
                    self,
                    "همگام‌سازی ناموفق",
                    f"هیچ دسته‌ای در فروشگاه ثبت نشد.\n\n{wc_hint}",
                )
            else:
                msg = f"✅ {synced} از {total} دسته شناسایی شد."
                if used_local:
                    msg += "\n⚡ از map محلی (بدون sync سنگین Woo)."
                if update_failed:
                    names = "، ".join(str(x) for x in update_failed[:3])
                    msg += (
                        f"\n⚠️ به‌روزرسانی نام ({names}) timeout شد — "
                        "دسته‌ها موجودند."
                    )
                if patched:
                    msg += f"\n✅ دسته روی {patched} محصول اعمال شد."
                elif patch_failed:
                    failed_skus = stats.get("products_patch_failed_skus") or []
                    sku_hint = "، ".join(str(s) for s in failed_skus[:3])
                    msg += (
                        "\n⚠️ دسته شناسایی شد ولی روی محصول اعمال نشد"
                        + (f" ({sku_hint})" if sku_hint else "")
                        + ".\n"
                        "۱) تب تطبیق: محصول به Woo وصل باشد\n"
                        "۲) تب محصولات: یک بار ارسال کنید\n"
                        "۳) Timeout تنظیمات را ۱۲۰ بگذارید و دوباره همگام‌سازی بزنید"
                    )
                else:
                    # دسته روی Woo ساخته شد ولی محصولی برای اعمال نبود — جدا از «اعمال شد» بگو
                    if patch_skipped:
                        msg += (
                            f"\nℹ️ دسته روی محصول اعمال نشد — {patch_skipped} مورد رد شد "
                            "(در Woo نیست یا دسته resolve نشد).\n"
                            "تب تطبیق و محصولات را بررسی کنید."
                        )
                    else:
                        msg += (
                            "\nℹ️ دسته‌ها فقط روی سایت ساخته شدند؛ "
                            "در زیرگروه انتخاب‌شده محصولی برای اعمال نبود.\n"
                            "اگر کالا زیرگروه دیگری است همان را تیک بزنید، "
                            "یا از تب محصولات ارسال کنید."
                        )
                QMessageBox.information(self, "پایان", msg)
            self._apply_icons_from_category_map()
            self.refresh_logs()

        def _err(msg):
            self._end_categories_sync_ui()
            self._restore_temp_excluded_codes()
            self.refresh_logs()
            if "متوقف شد" in str(msg):
                self._set_categories_status("warning", "⏹ همگام‌سازی متوقف شد.")
                QMessageBox.information(self, "توقف", str(msg))
            else:
                self._set_categories_status("error", f"❌ {str(msg).split(chr(10))[0][:120]}")
                QMessageBox.critical(self, "خطا", msg)

        if not run_background_sync(
            self,
            _job,
            on_success=_ok,
            on_error=_err,
            need_sql=True,
            need_wc=True,
            wait_on_disconnect=True,
        ):
            self._restore_temp_excluded_codes()
            thread = getattr(self, "_peecha_bg_sync_thread", None)
            if thread is not None and thread.isRunning():
                QMessageBox.information(self, "در حال اجرا", "عملیات دیگری در جریان است.")
            return
        self._begin_categories_sync_ui()
        self.refresh_logs()

    def clear_tab_logs(self):
        removed = clear_filtered_logs(CATEGORY_LOG_TOKENS)
        self.refresh_logs()
        QMessageBox.information(self, "انجام شد", f"{removed} خط لاگ مربوط به تب دسته‌بندی پاک شد.")

    def _hidden_checked_sub_codes(self) -> set:
        """کدهای زیرگروهی که تیک خوردن ولی الان (به‌خاطر فیلتر) روی درخت مخفی‌ان."""
        hidden = set()
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            m_code = (parent.data(0, Qt.UserRole + 1) or "").strip()
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) != Qt.Checked:
                    continue
                if not child.isHidden():
                    continue
                s_code = (child.data(0, Qt.UserRole + 1) or "").strip()
                hidden.add(m_code + s_code)
        return hidden

    def _restore_temp_excluded_codes(self):
        """بعد از یک همگام‌سازی محدودشده‌ی موقت به فیلتر، ترجیحات واقعی تیک کاربر رو برمی‌گردونه."""
        extra = getattr(self, "_temp_extra_excluded_codes", None)
        if not extra:
            return
        cfg = load_secure_config(None) or {}
        if not isinstance(cfg, dict) or len(cfg) < 5:
            # تنظیمات مشکوک به خالی/ناقص — دست‌کاریش نکن، امن‌تره
            self._temp_extra_excluded_codes = None
            return
        current = list(cfg.get("SELECTED_SUB_GROUPS", []) or [])
        for code in extra:
            if code not in current:
                current.append(code)
        cfg["SELECTED_SUB_GROUPS"] = current
        save_secure_config(cfg)
        self._temp_extra_excluded_codes = None

    def _category_code_for_item(self, item):
        if item is None:
            return "", ""
        if item.parent() is None:
            main_code = (item.data(0, Qt.UserRole + 1) or "").strip()
            return main_code, main_code
        main_code = (item.parent().data(0, Qt.UserRole + 1) or "").strip()
        sub_code = (item.data(0, Qt.UserRole + 1) or "").strip()
        return main_code + sub_code, main_code

    def _get_wc_category_image_url(self, name, full_code, parent_code=None):
        """فقط از داده‌های از‌پیش‌بارگذاری‌شده (_wc_slug_map) استفاده می‌کند — بدون HTTP blocking"""
        cache_key = f"{full_code}:{name}"
        if cache_key in self._category_image_url_cache:
            return self._category_image_url_cache[cache_key]

        slug = self._expected_slug(name, full_code)
        entry = self._wc_slug_map.get(slug, {}) if self._wc_slug_map else {}
        image = entry.get("image") if isinstance(entry, dict) else None
        src = ""
        if isinstance(image, dict):
            src = (image.get("src") or "").strip()

        self._category_image_url_cache[cache_key] = src
        return src

    def _pixmap_from_url(self, url):
        """فقط کش چک می‌کنه — برای دانلود از _load_image_async استفاده کن"""
        if not url:
            return None
        return self._category_pixmap_cache.get(url)

    def _load_image_async(self, url, on_loaded):
        """دانلود تصویر روی thread جداگانه، فراخوانی on_loaded(pixmap) بعد از اتمام"""
        if not url:
            return
        if url in self._category_pixmap_cache:
            on_loaded(self._category_pixmap_cache[url])
            return

        thread = QThread(self)
        worker = ImageLoaderWorker(url)
        worker.moveToThread(thread)

        def _on_loaded(u, pix):
            self._category_pixmap_cache[u] = pix
            on_loaded(pix)
            thread.quit()

        def _on_failed(u):
            self._category_pixmap_cache[u] = None
            thread.quit()

        worker.loaded.connect(_on_loaded)
        worker.failed.connect(_on_failed)
        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        thread.start()

    def on_group_hover(self, item, _column):
        name = (item.data(0, Qt.UserRole) or "").strip()
        full_code, parent_code = self._category_code_for_item(item)
        if not name or not full_code:
            self.image_preview.hide()
            return

        image_url = self._get_wc_category_image_url(name, full_code, parent_code)
        if not image_url:
            self.image_preview.hide()
            return

        cached = self._pixmap_from_url(image_url)
        if cached:
            self._current_hover_item = item
            self.image_preview.setPixmap(cached)
            self.image_preview.resize(cached.width() + 10, cached.height() + 10)
            self._move_preview_near_cursor()
            self.image_preview.show()
            return

        # دانلود async — نمایش بعد از اتمام دانلود
        def _show(pix):
            if self._current_hover_item is not item:
                return
            if pix:
                self.image_preview.setPixmap(pix)
                self.image_preview.resize(pix.width() + 10, pix.height() + 10)
                self._move_preview_near_cursor()
                self.image_preview.show()

        self._current_hover_item = item
        self._load_image_async(image_url, _show)

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
        viewports = [self.tree.viewport()]
        if hasattr(self, "selected_list"):
            viewports.append(self.selected_list.viewport())
        if obj in viewports:
            if event.type() == QEvent.Leave:
                self.image_preview.hide()
                self._current_hover_item = None
            elif event.type() == QEvent.MouseMove and self.image_preview.isVisible():
                self._move_preview_near_cursor()
        return super().eventFilter(obj, event)

    def refresh_logs(self):
        try:
            log_path = app_path("sync.log")
            if not os.path.exists(log_path):
                self.log_view.setPlainText("هنوز لاگی ایجاد نشده است.")
                return

            with open(log_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()

            filtered = _filter_category_log_lines(all_lines)
            if not filtered:
                body = "لاگی برای تب دسته‌بندی نیست."
            else:
                body = format_log_lines_jalali(filtered[-50:])
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

    # ─── مدیریت تصاویر دسته‌بندی ────────────────────────────────────────────

    def _category_image_abs_path(self, rel_path: str) -> str:
        """مسیر مطلق فایل تصویر — خالی اگر وجود نداشته باشد."""
        path = (rel_path or "").strip()
        if not path:
            return ""
        abs_path = path if os.path.isabs(path) else app_path(path)
        return abs_path if os.path.isfile(abs_path) else ""

    def _category_has_local_image(self, full_code: str) -> bool:
        rel = self._category_images_map.get(full_code, "")
        return bool(self._category_image_abs_path(rel))

    def _collect_categories_for_image_upload(self):
        """
        فقط دسته‌های انتخاب‌شده که فایل تصویر واقعی دارند.
        برمی‌گرداند: (ready, skipped_no_image, stale_removed)
        """
        ready = []
        skipped_no_image = []
        stale_removed = []

        for i in range(self.selected_list.count()):
            item = self.selected_list.item(i)
            full_code = item.data(Qt.UserRole)
            if not full_code:
                continue
            s_name = item.data(Qt.UserRole + 1) or ""
            rel_path = (self._category_images_map.get(full_code) or "").strip()
            if not rel_path:
                skipped_no_image.append((full_code, s_name))
                continue
            abs_path = self._category_image_abs_path(rel_path)
            if not abs_path:
                stale_removed.append((full_code, s_name))
                self._category_images_map.pop(full_code, None)
                item.setData(Qt.UserRole + 2, "")
                row_widget = self.selected_list.itemWidget(item)
                if isinstance(row_widget, CategoryRowWidget):
                    row_widget.set_has_image(False)
                continue
            ready.append((full_code, s_name, rel_path))

        if stale_removed:
            self._save_category_images_map()

        return ready, skipped_no_image, stale_removed

    def _category_images_map_path(self):
        return site_scoped_path("category_images_map.json")

    def _load_category_images_map(self):
        path = self._category_images_map_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {str(k): str(v) for k, v in data.items() if v}
        except Exception:
            pass
        return {}

    def reload_site_scoped_caches(self):
        """بعد از سوئیچِ سایت/پریست (بدونِ بستنِ تب) صدا زده می‌شه — چون
        self._category_images_map یک‌بار موقعِ ساختِ تب لود شده و اگه اینجا
        دوباره از دیسک لود نشه، همچنان دیتایِ سایتِ قبلی رو تویِ حافظه
        نگه می‌داره، حتی با اینکه مسیرِ فایل حالا به‌درستی برایِ سایتِ
        جدید scoped شده."""
        self._category_images_map = self._load_category_images_map()

    def _save_category_images_map(self):
        path = self._category_images_map_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._category_images_map, f, ensure_ascii=False, indent=2)

    def _upload_image_for_category(self, full_code, item):
        """انتخاب و ذخیره یک تصویر برای دسته‌بندی"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"انتخاب تصویر برای دسته {full_code}",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not file_path:
            return

        dst_dir = app_path("category_images")
        os.makedirs(dst_dir, exist_ok=True)

        base = os.path.basename(file_path)
        timestamp = str(int(time.time() * 1000))
        dst_name = f"{full_code}_{timestamp}_{base}"
        dst_abs = os.path.join(dst_dir, dst_name)

        try:
            shutil.copy2(file_path, dst_abs)
        except Exception as exc:
            QMessageBox.warning(self, "خطا", f"کپی تصویر ناموفق بود: {exc}")
            return

        rel_path = os.path.join("category_images", dst_name).replace("\\", "/")
        self._category_images_map[full_code] = rel_path
        self._save_category_images_map()

        item.setData(Qt.UserRole + 2, rel_path)
        # پاک کردن کش تصویر تا hover preview آپدیت شود
        self._category_pixmap_cache.pop(rel_path, None)

        row_widget = self.selected_list.itemWidget(item)
        if isinstance(row_widget, CategoryRowWidget):
            row_widget.set_has_image(True)

    def _clear_image_for_category(self, full_code, item):
        """حذف تصویر لوکال یک دسته از نگاشت و دیسک."""
        rel_path = (self._category_images_map.get(full_code) or "").strip()
        if not rel_path and not self._category_has_local_image(full_code):
            return

        confirm = QMessageBox.question(
            self,
            "حذف تصویر",
            f"تصویر لوکال دسته {full_code} حذف شود؟\n"
            "(تصویر روی سایت فروشگاه تغییری نمی‌کند.)",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        abs_path = self._category_image_abs_path(rel_path)
        self._category_images_map.pop(full_code, None)
        self._save_category_images_map()
        item.setData(Qt.UserRole + 2, "")
        if rel_path:
            self._category_pixmap_cache.pop(rel_path, None)
        row_widget = self.selected_list.itemWidget(item)
        if isinstance(row_widget, CategoryRowWidget):
            row_widget.set_has_image(False)
        if abs_path and os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
            except Exception as exc:
                log.warning(f"⚠️ حذف فایل تصویر {abs_path}: {exc}")
        self.image_preview.hide()

    def _on_selected_hover(self, item):
        """hover روی لیست گروه‌های انتخابی — نمایش تصویر لوکال یا فروشگاه"""
        full_code = item.data(Qt.UserRole) or ""
        s_name = item.data(Qt.UserRole + 1) or ""
        if not full_code:
            self.image_preview.hide()
            return

        # اول تصویر لوکال آپلودشده را بررسی کن (disk read — سریع)
        rel_path = self._category_images_map.get(full_code, "")
        if rel_path:
            abs_path = rel_path if os.path.isabs(rel_path) else app_path(rel_path)
            if os.path.exists(abs_path):
                cache_key = f"local:{abs_path}"
                pixmap = self._category_pixmap_cache.get(cache_key)
                if pixmap is None:
                    loaded = QPixmap(abs_path)
                    if not loaded.isNull():
                        pixmap = loaded.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self._category_pixmap_cache[cache_key] = pixmap
                if pixmap:
                    self._current_hover_item = item
                    self.image_preview.setPixmap(pixmap)
                    self.image_preview.resize(pixmap.width() + 10, pixmap.height() + 10)
                    self._move_preview_near_cursor()
                    self.image_preview.show()
                    return

        # fallback: تصویر فروشگاه (async — بدون block کردن UI)
        image_url = self._get_wc_category_image_url(s_name, full_code)
        if not image_url:
            self.image_preview.hide()
            return

        cached = self._pixmap_from_url(image_url)
        if cached:
            self._current_hover_item = item
            self.image_preview.setPixmap(cached)
            self.image_preview.resize(cached.width() + 10, cached.height() + 10)
            self._move_preview_near_cursor()
            self.image_preview.show()
            return

        def _show(pix):
            if self._current_hover_item is not item:
                return
            if pix:
                self.image_preview.setPixmap(pix)
                self.image_preview.resize(pix.width() + 10, pix.height() + 10)
                self._move_preview_near_cursor()
                self.image_preview.show()

        self._current_hover_item = item
        self._load_image_async(image_url, _show)

    def _on_send_cat_images_clicked(self):
        self._action_ops.handle_click("cat_images", self._send_category_images_to_woo)

    def _begin_cat_images_ui(self):
        self._action_ops.begin("cat_images")

    def _end_cat_images_ui(self):
        if self._action_ops.active == "cat_images":
            self._action_ops.end()

    def _stop_category_images_upload(self):
        if cancel_background_sync(self):
            self._action_ops.set_stopping("cat_images")
            log.info("⏹ درخواست توقف ارسال تصاویر دسته‌ها ثبت شد.")
        else:
            QMessageBox.information(self, "توقف", "عملیات فعالی برای توقف یافت نشد.")

    def _send_category_images_to_woo(self):
        """ارسال تصاویر آپلودشده دسته‌بندی‌ها به فروشگاه"""
        to_process, skipped, stale_removed = self._collect_categories_for_image_upload()
        selected_count = self.selected_list.count()

        if not to_process:
            parts = [
                "هیچ دسته‌ای با تصویر آماده برای ارسال یافت نشد.",
                "ابتدا با دکمه «آپلود تصویر» کنار هر دسته، تصویر را انتخاب کنید.",
            ]
            if skipped:
                parts.append(f"\n{len(skipped)} دسته انتخاب‌شده بدون تصویر است.")
            if stale_removed:
                parts.append(
                    f"\n{len(stale_removed)} مورد در نگاشت قدیمی بود ولی فایل روی دیسک نبود — پاک شد."
                )
            QMessageBox.information(self, "توجه", "\n".join(parts))
            return

        confirm_lines = [
            f"از {selected_count} دسته انتخاب‌شده، {len(to_process)} تصویر واقعی برای ارسال آماده است.",
            f"آیا {len(to_process)} تصویر به فروشگاه ارسال شود؟",
        ]
        ignored = len(skipped) + len(stale_removed)
        if ignored:
            confirm_lines.append(f"({ignored} دسته بدون تصویر نادیده گرفته می‌شود)")
        confirm = QMessageBox.question(
            self,
            "تأیید ارسال",
            "\n".join(confirm_lines),
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self._begin_cat_images_ui()

        self._last_cat_upload_result = (0, 0)
        wc_slug_map_snapshot = dict(self._wc_slug_map)

        from sync_app.core.integrations.commerce_provider import is_prestashop

        def job():
            if is_prestashop(self.config):
                self._do_send_category_images_to_ps(to_process, wc_slug_map_snapshot)
            else:
                self._do_send_category_images_to_woo(to_process, wc_slug_map_snapshot)

        if not run_background_sync(
            self, job,
            on_success=self._category_images_upload_done,
            on_error=self._category_images_upload_error,
            need_sql=False,
            need_wc=True,
            wait_on_disconnect=True,
        ):
            thread = getattr(self, "_peecha_bg_sync_thread", None)
            if thread is not None and thread.isRunning():
                QMessageBox.information(self, "در حال اجرا", "یک عملیات دیگر در حال اجرا است.")
            self._end_cat_images_ui()

    def _do_send_category_images_to_woo(self, to_process, wc_slug_map_snapshot):
        """اجرا در thread پس‌زمینه — آپلود تصویر به WordPress Media و بروزرسانی دسته"""
        cfg = ensure_wc_sites(load_secure_config(None) or {})
        wp_user, wp_pwd = get_wp_media_credentials(cfg)
        self._last_cat_upload_detail = ""
        if not wp_user or not wp_pwd:
            detail = (
                "WP Username یا Application Password برای سایت فعال خالی است.\n"
                "تنظیمات → سایت Woo فعال → WP Username / WP App Password\n"
                "Users → Profile → Application Passwords\n"
                "پس از پر کردن، «ذخیره تنظیمات» را بزنید."
            )
            log.error(f"❌ {detail}")
            self._last_cat_upload_detail = detail
            self._last_cat_upload_result = (0, len(to_process))
            return
        timeout = int(cfg.get("WC_TIMEOUT", 60) or 60)

        store_host = wc_store_host(cfg) or (cfg.get("WC_URL") or "").strip()
        log.info(
            f"📷 شروع ارسال {len(to_process)} تصویر دسته‌بندی → {store_host} "
            f"(WP user: {wp_user}) — فقط دسته‌های دارای فایل تصویر"
        )
        ok_auth, auth_err = verify_wp_media_credentials(cfg)
        if not ok_auth:
            log.error(f"❌ بررسی Application Password ناموفق: {auth_err}")
            self._last_cat_upload_detail = auth_err
            self._last_cat_upload_result = (0, len(to_process))
            return
        log.info("✅ Application Password برای آپلود تصویر تأیید شد.")

        success_count = 0
        fail_count = 0

        category_map = load_category_map()
        slug_map = dict(wc_slug_map_snapshot or {})

        unresolved = [
            full_code
            for full_code, _s_name, _rel_path in to_process
            if not resolve_wc_category_id(full_code, category_map, slug_map)
        ]
        if unresolved:
            log.info(
                f"ℹ️ {len(unresolved)} دسته در نگاشت محلی نیست — واکشی از API "
                f"({', '.join(unresolved[:4])}{'...' if len(unresolved) > 4 else ''})"
            )
            try:
                check_cancelled()
                fresh_slug_map = fetch_wc_slug_map(
                    cfg,
                    timeout=min(45, timeout),
                    cancel_check=check_cancelled,
                )
                if fresh_slug_map:
                    slug_map = fresh_slug_map
                    merged = merge_category_map_with_slug_map(category_map, slug_map)
                    if merged != category_map:
                        save_category_map(merged)
                        category_map = merged
                    log.info(f"ℹ️ نگاشت دسته‌ها از API واکشی شد ({len(slug_map)} مورد).")
            except SyncCancelled:
                raise
            except Exception as exc:
                log.warning(f"⚠️ واکشی نگاشت دسته ناموفق: {exc} — از cache محلی استفاده می‌شود.")

        if slug_map:
            log.info(f"ℹ️ نگاشت دسته‌ها از cache/API ({len(slug_map)} مورد).")
        elif category_map:
            log.info("ℹ️ نگاشت دسته‌ها از category_map محلی.")

        still_missing = [
            full_code
            for full_code, _s_name, _rel_path in to_process
            if not resolve_wc_category_id(full_code, category_map, slug_map)
        ]
        if still_missing:
            detail = (
                f"{len(still_missing)} دسته در فروشگاه پیدا نشد "
                f"({', '.join(still_missing[:4])}{'...' if len(still_missing) > 4 else ''}).\n"
                "ابتدا «بررسی وضعیت» یا «همگام‌سازی» دسته‌ها را بزنید."
            )
            log.error(f"❌ بدون نگاشت دسته، ارسال تصویر ممکن نیست — {detail}")
            self._last_cat_upload_detail = detail
            self._last_cat_upload_result = (0, len(to_process))
            return

        total = len(to_process)
        for index, (full_code, s_name, rel_path) in enumerate(to_process, start=1):
            try:
                log.info(f"📷 ({index}/{total}) دسته {full_code} ({s_name})...")
                wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True, log_waiting=False)

                abs_path = self._category_image_abs_path(rel_path)
                if not abs_path:
                    log.warning(f"⚠️ فایل تصویر پیدا نشد — دسته {full_code} رد شد")
                    continue

                cat_id = resolve_wc_category_id(full_code, category_map, slug_map)
                if not cat_id:
                    log.warning(
                        f"⚠️ دسته {full_code} ({s_name}) در فروشگاه پیدا نشد — "
                        f"ابتدا «همگام‌سازی» دسته‌ها را بزنید."
                    )
                    fail_count += 1
                    continue

                filename = os.path.basename(abs_path)
                with open(abs_path, "rb") as f:
                    img_data = f.read()

                src_url = None
                media_id = 0
                upload_err = ""
                for attempt in range(1, WP_UPLOAD_MAX_ATTEMPTS + 1):
                    check_cancelled()
                    wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True, log_waiting=False)
                    ok, media_id, src_url, upload_err = wp_upload_media_ex(
                        cfg,
                        img_data,
                        filename,
                        fallback_stem=f"cat-{full_code}",
                        label=f"دسته {full_code}",
                    )
                    if ok and src_url:
                        break
                    if is_wp_upload_fatal_error(upload_err) or not should_retry_upload_error(upload_err):
                        break
                    log.warning(
                        f"⚠️ آپلود {filename} — تلاش {attempt}/{WP_UPLOAD_MAX_ATTEMPTS}: {upload_err}"
                    )
                if not src_url:
                    log.error(f"❌ آپلود تصویر {filename} برای دسته {full_code}: {upload_err}")
                    if is_wp_upload_fatal_error(upload_err):
                        self._last_cat_upload_detail = upload_err
                    fail_count += 1
                    if is_wp_upload_fatal_error(upload_err):
                        fail_count += total - index
                        log.error("⛔ خطای قطعی آپلود — بقیه تصاویر رد شد.")
                        break
                    continue

                for attempt in range(1, WP_UPLOAD_MAX_ATTEMPTS + 1):
                    check_cancelled()
                    wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True, log_waiting=False)
                    try:
                        ok_cat, _update_resp, update_err = update_wc_category_image(
                            cfg,
                            cat_id,
                            media_id=media_id,
                            src_url=src_url,
                            timeout=timeout,
                        )
                    except Exception as exc:
                        update_err = str(exc)
                        ok_cat = False
                        if should_retry_upload_error(update_err) and attempt < WP_UPLOAD_MAX_ATTEMPTS:
                            log.warning(
                                f"⚠️ تنظیم تصویر دسته {full_code} — تلاش {attempt}/{WP_UPLOAD_MAX_ATTEMPTS}: {update_err}"
                            )
                            continue
                        log.error(f"❌ خطا در تنظیم تصویر دسته {full_code}: {update_err}")
                        fail_count += 1
                        break

                    if ok_cat:
                        if category_map.get(full_code) != cat_id:
                            category_map[full_code] = cat_id
                            save_category_map(category_map)
                        log.info(f"✅ تصویر دسته {full_code} ({s_name}) ارسال شد.")
                        success_count += 1
                        break

                    if should_retry_upload_error(update_err) and attempt < WP_UPLOAD_MAX_ATTEMPTS:
                        log.warning(
                            f"⚠️ تنظیم تصویر دسته {full_code} — تلاش {attempt}/{WP_UPLOAD_MAX_ATTEMPTS}: {update_err}"
                        )
                        continue
                    log.error(
                        f"❌ خطا در تنظیم تصویر دسته {full_code} (wc id={cat_id}): {update_err}"
                    )
                    self._last_cat_upload_detail = update_err
                    fail_count += 1
                    break

            except SyncCancelled:
                raise
            except Exception as exc:
                if should_retry_upload_error(str(exc)):
                    log.warning(f"⚠️ خطای موقت در پردازش دسته {full_code}: {exc}")
                    fail_count += 1
                    continue
                log.error(f"❌ خطای کلی در پردازش دسته {full_code}: {exc}")
                fail_count += 1

        if fail_count == 0:
            log.info(f"✅ ارسال تصاویر دسته‌بندی تمام شد. {success_count} موفق.")
        else:
            log.warning(f"⚠️ ارسال تمام شد. موفق: {success_count} | ناموفق: {fail_count}")
        self._last_cat_upload_result = (success_count, fail_count)

    def _do_send_category_images_to_ps(self, to_process, ps_slug_map_snapshot):
        """اجرا در thread پس‌زمینه — آپلود تصویر مستقیم به پرستاشاپ (images/categories/{id}).

        برخلاف ووکامرس، پرستاشاپ کتابخانه رسانه‌ی جدا نداره — تصویر مستقیم
        روی خودِ دسته آپلود می‌شه، پس نیازی به مرحله‌ی جدای «آپلود به رسانه +
        اتصال به دسته» نیست.
        """
        from sync_app.core.ps_sync_helper import ps_upload_category_image

        cfg = load_secure_config(None) or {}
        timeout = int(cfg.get("PS_TIMEOUT", 60) or 60)
        self._last_cat_upload_detail = ""

        category_map = load_category_map()
        slug_map = dict(ps_slug_map_snapshot or {})

        unresolved = [
            full_code
            for full_code, _s_name, _rel_path in to_process
            if not resolve_wc_category_id(full_code, category_map, slug_map)
        ]
        if unresolved:
            log.info(
                f"ℹ️ {len(unresolved)} دسته در نگاشت محلی نیست — واکشی از API "
                f"({', '.join(unresolved[:4])}{'...' if len(unresolved) > 4 else ''})"
            )
            try:
                check_cancelled()
                from sync_app.core.integrations.commerce_provider import fetch_store_slug_map

                fresh_slug_map = fetch_store_slug_map(cfg, timeout=min(45, timeout), cancel_check=check_cancelled)
                if fresh_slug_map:
                    slug_map = fresh_slug_map
                    merged = merge_category_map_with_slug_map(category_map, slug_map)
                    if merged != category_map:
                        save_category_map(merged)
                        category_map = merged
                    log.info(f"ℹ️ نگاشت دسته‌ها از API واکشی شد ({len(slug_map)} مورد).")
            except SyncCancelled:
                raise
            except Exception as exc:
                log.warning(f"⚠️ واکشی نگاشت دسته ناموفق: {exc} — از cache محلی استفاده می‌شود.")

        still_missing = [
            full_code
            for full_code, _s_name, _rel_path in to_process
            if not resolve_wc_category_id(full_code, category_map, slug_map)
        ]
        if still_missing:
            detail = (
                f"{len(still_missing)} دسته در فروشگاه پیدا نشد "
                f"({', '.join(still_missing[:4])}{'...' if len(still_missing) > 4 else ''}).\n"
                "ابتدا «بررسی وضعیت» یا «همگام‌سازی» دسته‌ها را بزنید."
            )
            log.error(f"❌ بدون نگاشت دسته، ارسال تصویر ممکن نیست — {detail}")
            self._last_cat_upload_detail = detail
            self._last_cat_upload_result = (0, len(to_process))
            return

        success_count = 0
        fail_count = 0
        total = len(to_process)
        store_host = (cfg.get("PS_URL") or "").strip()
        log.info(f"📷 شروع ارسال {total} تصویر دسته‌بندی → {store_host} (پرستاشاپ)")

        for index, (full_code, s_name, rel_path) in enumerate(to_process, start=1):
            try:
                log.info(f"📷 ({index}/{total}) دسته {full_code} ({s_name})...")
                wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True, log_waiting=False)

                abs_path = self._category_image_abs_path(rel_path)
                if not abs_path:
                    log.warning(f"⚠️ فایل تصویر پیدا نشد — دسته {full_code} رد شد")
                    continue

                cat_id = resolve_wc_category_id(full_code, category_map, slug_map)
                if not cat_id:
                    log.warning(
                        f"⚠️ دسته {full_code} ({s_name}) در فروشگاه پیدا نشد — "
                        f"ابتدا «همگام‌سازی» دسته‌ها را بزنید."
                    )
                    fail_count += 1
                    continue

                filename = os.path.basename(abs_path)
                with open(abs_path, "rb") as f:
                    img_data = f.read()

                try:
                    check_cancelled()
                    ps_upload_category_image(cfg, cat_id, img_data, filename, timeout=timeout)
                except SyncCancelled:
                    raise
                except Exception as exc:
                    log.error(f"❌ آپلود تصویر دسته {full_code} (ps id={cat_id}): {exc}")
                    self._last_cat_upload_detail = str(exc)
                    fail_count += 1
                    continue

                if category_map.get(full_code) != cat_id:
                    category_map[full_code] = cat_id
                    save_category_map(category_map)
                log.info(f"✅ تصویر دسته {full_code} ({s_name}) ارسال شد.")
                success_count += 1

            except SyncCancelled:
                raise
            except Exception as exc:
                log.error(f"❌ خطای کلی در پردازش دسته {full_code}: {exc}")
                fail_count += 1

        if fail_count == 0:
            log.info(f"✅ ارسال تصاویر دسته‌بندی تمام شد. {success_count} موفق.")
        else:
            log.warning(f"⚠️ ارسال تمام شد. موفق: {success_count} | ناموفق: {fail_count}")
        self._last_cat_upload_result = (success_count, fail_count)

    def _category_images_upload_done(self):
        self._end_cat_images_ui()
        self.refresh_logs()
        ok, fail = getattr(self, "_last_cat_upload_result", (0, 0))
        if ok > 0 and fail == 0:
            QMessageBox.information(
                self, "✅ موفق",
                f"ارسال تصاویر دسته‌بندی با موفقیت انجام شد.\n{ok} دسته‌بندی بروزرسانی شد."
            )
        elif ok > 0 and fail > 0:
            QMessageBox.warning(
                self, "⚠️ ناقص",
                f"ارسال تصاویر تمام شد.\nموفق: {ok} | ناموفق: {fail}\nجزئیات را در لاگ تب دسته‌بندی‌ها ببینید."
            )
        else:
            detail = getattr(self, "_last_cat_upload_detail", "") or ""
            from sync_app.core.wc_site_profiles import ensure_wc_sites
            from sync_app.core.secure_config_loader import load_secure_config
            from sync_app.core.wp_auth_error_ui import show_wp_media_auth_error_if_applicable

            cfg = ensure_wc_sites(load_secure_config(None) or {})
            if show_wp_media_auth_error_if_applicable(
                self,
                detail,
                cfg,
                context="ارسال تصاویر دسته‌بندی متوقف شد — مشکل Application Password",
            ):
                return
            extra = f"\n\n{detail}" if detail else ""
            wp_hint = ""
            low = detail.lower()
            if not detail or any(
                token in low
                for token in (
                    "application password",
                    "wp username",
                    "wp/v2/media",
                    "litespeed",
                    "waf",
                )
            ):
                wp_hint = (
                    "\n\nتوجه: آپلود تصویر به wp/v2/media نیاز به WP Username + Application Password دارد "
                    "(نه Consumer Key/Secret فروشگاه)."
                )
            if "products/categories" in low or "wc/v3" in low:
                wp_hint = (
                    "\n\nتوجه: تنظیم تصویر روی دسته از API فروشگاه (Consumer Key با مجوز Write) انجام می‌شود — "
                    "نه Application Password."
                )
            QMessageBox.critical(
                self,
                "❌ خطا",
                f"ارسال تصاویر ناموفق بود.\nموفق: {ok} | ناموفق: {fail}\n"
                f"جزئیات را در لاگ تب دسته‌بندی‌ها ببینید.{wp_hint}{extra}",
            )

    def _category_images_upload_error(self, message):
        self._end_cat_images_ui()
        self.refresh_logs()
        if "متوقف" in (message or ""):
            QMessageBox.information(self, "توقف", "ارسال تصاویر دسته‌ها متوقف شد.")
            return
        QMessageBox.critical(self, "خطا", message)


