import sys
import os
import json
import re
import shutil
import time
import pyodbc
import urllib.request
import requests
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QListWidget, QMessageBox, QHBoxLayout, QTextEdit, QListWidgetItem, QToolTip, QSplitter,
    QLineEdit, QCheckBox, QFileDialog, QProgressBar, QToolButton, QDialog, QDialogButtonBox,
    QComboBox, QApplication, QTabWidget, QInputDialog, QSpinBox, QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, QPoint, QEvent, QSize
from PyQt5.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPixmap
from sync_app.core.log_panel_ui import LogPanelController, VerticalTextButton, LogActionRail
from sync_app.core.rtl_item_delegate import RightAlignedCheckableItemDelegate
from sync_app.core.jalali_log_formatter import format_log_lines_jalali

# 📌 مسیر پکیجی درست برای بارگذاری تنظیمات
from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.sync_utils import app_path, site_scoped_path, clear_filtered_logs, log
from sync_app.core.article_price import resolve_article_price
from sync_app.core.sql_connection_helper import open_sql_connection, format_db_error
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.selection_toggle_bar import attach_selection_toggle
from sync_app.core.responsive_action_bar import build_responsive_action_row
from sync_app.core.compact_icon_action_bar import CompactCaptionButton
from sync_app.core.wc_admin_links import make_wc_admin_open_button
from sync_app.core.tab_action_controller import TabActionController, ActionSpec

# 📌 اجرای مستقیم اسکریپت محصولات
from sync_app.core.scripts import sync_fullproduct
from sync_app.core.sync_job_runner import run_background_sync, cancel_background_sync
from sync_app.core.connectivity_wait import wait_for_connectivity_blocking, is_transient_connectivity_issue
from sync_app.core.connectivity_guard import ensure_connectivity
from sync_app.core.live_site_backup_guard import confirm_live_site_backup
from sync_app.core.product_sync_guard import build_products_sync_preview, ProductSyncPreviewDialog
from sync_app.core.wc_site_profiles import ensure_wc_sites
from sync_app.core.wc_sync_helper import (
    wp_upload_media_ex,
    update_wc_product_images,
    verify_wp_media_credentials,
    should_retry_upload_error,
    is_wp_upload_fatal_error,
    WP_UPLOAD_MAX_ATTEMPTS,
    wc_rest_request,
    build_wcapi,
    apply_network_overrides,
    wc_http_error_message,
)
from sync_app.core.erp_image_helper import stage_erp_images
from sync_app.core.product_woo_map_helper import load_product_woo_map, save_product_woo_map
from sync_app.core.message_boxes_fa import ask_yes_no
from sync_app.core.seo_helper import analyze_product_seo_live, apply_seo_fixes

try:
    from woocommerce import API as WCAPI
except ImportError:
    WCAPI = None


def _fetch_ps_seo_bundle(config, product_id):
    """معادل analyze_product_seo_live برای پرستاشاپ — برای دیالوگ‌های تک‌محصولیِ
    سئو/آماده‌سازی هوشمند در همین تب (همون منطق _fetch_and_score_ps تب سئو و
    سلامت سایت، فقط برای یک محصول به‌جای کل فروشگاه)."""
    from sync_app.core.ps_sync_helper import ps_get_product, ps_list_categories
    from sync_app.core.seo_helper import analyze_ps_product_seo

    product = ps_get_product(config, int(product_id)) or {}
    categories = ps_list_categories(config)
    cat_by_id = {int(c["id"]): c for c in categories if isinstance(c, dict) and c.get("id")}
    cats = product.get("categories") or []
    cat_id = int(cats[0].get("id") or 0) if cats and isinstance(cats[0], dict) else 0
    category_name = str((cat_by_id.get(cat_id) or {}).get("name") or "")
    return analyze_ps_product_seo(product, category_name=category_name)


def _guess_mime(filename):
    ext = os.path.splitext(filename.lower())[1]
    return {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.webp': 'image/webp',
        '.gif': 'image/gif', '.bmp': 'image/bmp',
    }.get(ext, 'image/jpeg')


def _derive_site_address_display(cfg: dict) -> str:
    """آدرسِ نمایشیِ سایت برای فیلدِ «آدرسِ سایت» در قالبِ پست — یا از
    SITE_ADDRESS_DISPLAYِ تنظیمات (اگه واردشده)، یا خودکار از آدرسِ فروشگاه."""
    override = str((cfg or {}).get("SITE_ADDRESS_DISPLAY") or "").strip()
    if override:
        return override
    from sync_app.core.integrations.commerce_provider import is_prestashop

    url = (cfg or {}).get("PS_URL") if is_prestashop(cfg) else (cfg or {}).get("WC_URL")
    return re.sub(r"^https?://", "", str(url or "").strip()).rstrip("/")


def _build_template_context(product: dict, fetched: dict, cfg: dict, fallback_link: str = "") -> dict:
    """context برای render_post_text — فیلدهای واقعیِ محصول + تماس/برندینگِ تنظیمات."""
    return {
        "name": product.get("name") or "",
        "price": product.get("price"),
        "description": (fetched or {}).get("description") or "",
        "permalink": (fetched or {}).get("permalink") or fallback_link,
        "site_address": _derive_site_address_display(cfg),
        "phone": (cfg or {}).get("CONTACT_PHONE") or "",
        "social_instagram": (cfg or {}).get("SOCIAL_INSTAGRAM") or "",
        "social_telegram": (cfg or {}).get("SOCIAL_TELEGRAM") or "",
        "social_whatsapp": (cfg or {}).get("SOCIAL_WHATSAPP") or "",
    }


class ProductRowWidget(QWidget):
    def __init__(self, text, checked, on_toggle, on_upload, on_clear=None, on_seo=None, on_pipeline=None, on_content=None, on_smart_prep=None, on_delete=None, on_stock_mode_changed=None, on_stock_group=None, on_store_category=None, parent=None):
        super().__init__(parent)
        self.setLayoutDirection(Qt.LeftToRight)
        self._on_upload = on_upload
        self._on_clear = on_clear
        self._on_pipeline = on_pipeline
        self._on_content = on_content
        self._on_smart_prep = on_smart_prep
        self._on_seo = on_seo
        self._on_delete = on_delete
        self._on_stock_mode_changed = on_stock_mode_changed
        self._on_stock_group = on_stock_group
        self._on_store_category = on_store_category
        row = QHBoxLayout(self)
        row.setDirection(QHBoxLayout.LeftToRight)
        row.setContentsMargins(6, 2, 6, 2)
        row.setSpacing(6)

        self.upload_button = QPushButton("آپلود تصاویر")
        self.upload_button.setLayoutDirection(Qt.LeftToRight)
        self.upload_button.setStyleSheet("padding: 2px 6px; font-size: 11px; min-height: 28px;")
        self.upload_button.setFixedWidth(148)
        self.upload_button.setFixedHeight(36)
        self.upload_button.clicked.connect(self._on_upload)
        row.addWidget(self.upload_button)

        from sync_app.core.row_action_button import make_row_button, row_button_style

        self.seo_button = make_row_button(
            "📝", "امتیاز سئو + رفع موارد ناقص این محصول", kind="warning"
        )
        self.seo_button.clicked.connect(self._handle_seo)
        row.addWidget(self.seo_button)

        self.pipeline_button = make_row_button(
            "🎨", "اجرای روش پردازش تصویر Smart Publish روی تصویر این محصول", kind="neutral"
        )
        self.pipeline_button.clicked.connect(self._handle_pipeline)
        row.addWidget(self.pipeline_button)

        self.content_button = make_row_button(
            "📢", "تولید متن/بنر تبلیغاتی این محصول (AI Content Studio)", kind="neutral"
        )
        self.content_button.clicked.connect(self._handle_content)
        row.addWidget(self.content_button)

        self.smart_prep_button = make_row_button(
            "🤖", "آماده‌سازی هوشمند محصول با یک کلیک (سئو ناقص را خودش پیدا و رفع می‌کند)", kind="neutral"
        )
        self.smart_prep_button.clicked.connect(self._handle_smart_prep)
        row.addWidget(self.smart_prep_button)

        self.delete_button = make_row_button(
            "🗑️", "حذف این محصول از فروشگاه (موقت/زباله‌دان یا برای همیشه)", kind="danger"
        )
        self.delete_button.clicked.connect(self._handle_delete)
        row.addWidget(self.delete_button)

        from sync_app.core.stock_mode import STOCK_MODE_LABELS
        self.stock_mode_combo = QComboBox()
        self.stock_mode_combo.setLayoutDirection(Qt.RightToLeft)
        self.stock_mode_combo.setMaximumWidth(150)
        self.stock_mode_combo.setFixedHeight(28)
        self.stock_mode_combo.setStyleSheet("font-size: 11px; padding: 1px 4px;")
        self.stock_mode_combo.setToolTip(
            "حالت موجودی این محصول:\n"
            "«ارث‌بری از دسته» یعنی همون تنظیم دسته‌بندیش رو داشته باشه.\n"
            "بقیه‌ی گزینه‌ها فقط همین محصول رو بازنویسی می‌کنن."
        )
        self.stock_mode_combo.addItem("↩️ ارث‌بری از دسته", "")
        for key, label in STOCK_MODE_LABELS.items():
            self.stock_mode_combo.addItem(label, key)
        self._stock_mode_ready = False
        self.stock_mode_combo.currentIndexChanged.connect(self._handle_stock_mode_changed)
        row.addWidget(self.stock_mode_combo)

        self.stock_group_button = make_row_button(
            "🔗",
            "این محصول رو «فرعی» یه کد کالای دیگه کن:\n"
            "خودش دیگه به فروشگاه ارسال نشه، فقط موجودیش\n"
            "به اون کالای اصلی اضافه بشه.",
            kind="neutral",
        )
        self.stock_group_button.clicked.connect(self._handle_stock_group)
        row.addWidget(self.stock_group_button)

        self.store_category_button = make_row_button(
            "🏷️",
            "دسته‌بندیِ این محصول را مستقیم از دسته‌بندی‌هایِ واقعیِ سایت "
            "(نه ERP) انتخاب کن — این انتخاب در همگام‌سازی‌هایِ بعدی هم "
            "حفظ می‌شه، مگه خودتون دوباره تغییرش بدید.",
            kind="neutral",
        )
        self.store_category_button.clicked.connect(self._handle_store_category)
        row.addWidget(self.store_category_button)

        self.clear_button = make_row_button(
            "✕", "حذف تصاویر دستی این محصول", kind="danger", size=24,
        )
        self.clear_button.setStyleSheet(
            row_button_style("danger") + "QToolButton { color: #b91c1c; font-weight: bold; font-size: 13px; }"
        )
        self.clear_button.clicked.connect(self._handle_clear)
        self.clear_button.hide()
        row.addWidget(self.clear_button)

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

    def _handle_seo(self):
        if callable(self._on_seo):
            self._on_seo()

    def _handle_pipeline(self):
        if callable(self._on_pipeline):
            self._on_pipeline()

    def _handle_content(self):
        if callable(self._on_content):
            self._on_content()

    def _handle_smart_prep(self):
        if callable(self._on_smart_prep):
            self._on_smart_prep()

    def _handle_delete(self):
        if callable(self._on_delete):
            self._on_delete()

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

    def _handle_stock_group(self):
        if callable(self._on_stock_group):
            self._on_stock_group()

    # وضعیت گروه موجودی → «نوع» رنگ (طبق سیستم مشترک row_action_button)
    _STOCK_GROUP_KIND = {"none": "neutral", "primary": "success", "secondary": "warning"}

    def set_stock_group_state(self, state: str, tooltip_extra: str = ""):
        from sync_app.core.row_action_button import row_button_style

        kind = self._STOCK_GROUP_KIND.get(state, "neutral")
        self.stock_group_button.setStyleSheet(row_button_style(kind))
        base_tooltip = "پیوند این محصول به یه محصول اصلیِ دیگه (موجودی مشترک)"
        self.stock_group_button.setToolTip(f"{base_tooltip}\n{tooltip_extra}" if tooltip_extra else base_tooltip)

    def _handle_store_category(self):
        if callable(self._on_store_category):
            self._on_store_category()

    def set_store_category_state(self, manual: bool, tooltip_extra: str = ""):
        from sync_app.core.row_action_button import row_button_style

        kind = "success" if manual else "neutral"
        self.store_category_button.setStyleSheet(row_button_style(kind))
        base_tooltip = (
            "دسته‌بندیِ این محصول را مستقیم از دسته‌بندی‌هایِ واقعیِ سایت "
            "(نه ERP) انتخاب کن"
        )
        self.store_category_button.setToolTip(
            f"{base_tooltip}\n{tooltip_extra}" if tooltip_extra else base_tooltip
        )

    def set_wc_image_count(self, count: int):
        current = self.title.text()
        # اگه قبلاً یه‌بار اضافه شده، اول پاکش کن تا تکراری نشه
        import re
        current = re.sub(r"\s*\|\s*فروشگاه: \d+$", "", current)
        self.title.setText(f"{current} | فروشگاه: {count}")

    def set_manual_upload_count(self, count):
        """تعداد تصاویر دستی — ✔ سبز و دکمه حذف."""
        n = int(count or 0)
        self.clear_button.setVisible(n > 0)
        if n > 0:
            self.upload_button.setText(f"آپلود تصاویر ({n}) ✔")
            self.upload_button.setStyleSheet(
                "background-color: #166534; color: white; "
                "padding: 2px 6px; font-size: 11px; min-height: 28px;"
            )
        else:
            self.upload_button.setText("آپلود تصاویر")
            self.upload_button.setStyleSheet(
                "padding: 2px 6px; font-size: 11px; min-height: 28px;"
            )

    def set_upload_count(self, count):
        """سازگاری قدیمی — همان manual count."""
        self.set_manual_upload_count(count)


class ProductTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None)
        self._loading_products = False
        self._image_url_cache = {}
        self._wc_image_count_cache = {}
        self._image_pixmap_cache = {}
        self._wc_api = None
        self._current_hover_item = None
        self._uploaded_images_map = self._load_uploaded_images_map()
        self._initial_load_started = False
        self._products_load_generation = 0
        self._refresh_button_default_text = "🔄 بروزرسانی"
        self._sync_button_idle_text = "📤 ارسال محصولات"
        self._upload_images_idle_text = "📷 انتقال تصاویر"
        self._upload_images_idle_style = (
            "QPushButton { background-color: #1a6b2e; color: white; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background-color: #228B3A; }"
            "QPushButton:disabled { background-color: #666; }"
        )
        self._upload_images_stop_style = (
            "QPushButton { background-color: #b45309; color: white; border-radius: 6px; font-weight: bold; }"
            "QPushButton:hover { background-color: #d97706; }"
        )
        self._sync_stop_style = (
            "QPushButton { background-color: #b91c1c; color: #ffffff; font-weight: bold; border-radius: 6px; }"
            "QPushButton:hover { background-color: #991b1b; }"
        )
        self.init_ui()

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(lambda: self.refresh_logs() if self.isVisible() else None)
        self.log_timer.start(2000)

        self._sync_started_at = 0.0
        self._sync_live_timer = QTimer(self)
        self._sync_live_timer.setInterval(400)
        self._sync_live_timer.timeout.connect(self._tick_products_sync_ui)

        self._mobile_inbox_timer = QTimer(self)
        self._mobile_inbox_timer.setInterval(15000)
        self._mobile_inbox_timer.timeout.connect(
            lambda: self._refresh_mobile_inbox_badge() if self.isVisible() else None
        )
        self._mobile_inbox_timer.start()
        self._refresh_mobile_inbox_badge()

    def _erp_label(self) -> str:
        from sync_app.core.integrations.erp_provider import erp_provider_label

        return erp_provider_label(self.config)

    def _tick_products_sync_ui(self):
        """آپدیت زنده‌ی درصد پیشرفت — با خواندن همون خط لاگ «محصول X/Y» که خودِ اسکریپت سینک می‌نویسه."""
        import re
        import time as _time

        elapsed = int(_time.monotonic() - self._sync_started_at)
        try:
            log_path = app_path("sync.log")
            step = ""
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                for line in reversed(lines[-60:]):
                    if "محصول" in line and "/" in line:
                        if " - INFO - " in line:
                            part = line.split(" - INFO - ", 1)[-1].strip()
                        else:
                            part = line.strip()
                        if "SyncApp - " in part:
                            part = part.split("SyncApp - ", 1)[-1].strip()
                        step = part
                        break
            m = re.search(r"محصول\s+(\d+)\s*/\s*(\d+)", step)
            if m:
                current, total = int(m.group(1)), max(1, int(m.group(2)))
                pct = min(99, int((current / total) * 100))
                self.sync_progress.setValue(pct)
                self.sync_detail_label.setText(f"{step} — {elapsed} ثانیه")
                self._set_products_status("loading", f"⏳ {step}")
            else:
                self._set_products_status("loading", f"⏳ در حال ارسال محصولات... ({elapsed} ثانیه)")
        except Exception:
            pass

    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setDirection(QHBoxLayout.LeftToRight)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setLayoutDirection(Qt.LeftToRight)
        self.splitter.setHandleWidth(6)

        # پنل لاگ در سمت چپ - با استایل تیره مثل ترمینال
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LeftToRight)
        self.log_view.setMinimumWidth(260)
        self.splitter.addWidget(self.log_view)

        right_panel = QWidget()
        layout = QVBoxLayout(right_panel)

        self.log_actions = LogActionRail(clear_text="حذف لاگ‌های تب محصولات", parent=self)

        self.status_label = QLabel("✓ آماده — برای بارگذاری دکمه بروزرسانی را بزنید")
        self._set_products_status("ready", self.status_label.text())
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
        self.sync_progress.setFormat("%p% — ارسال محصولات")
        self.sync_progress.setTextVisible(True)
        self.sync_progress.setFixedHeight(22)
        self.sync_progress.setVisible(False)
        layout.addWidget(self.sync_progress)

        self.sync_detail_label = QLabel("")
        self.sync_detail_label.setWordWrap(True)
        self.sync_detail_label.setStyleSheet("color:#475569; font-size:11px;")
        self.sync_detail_label.setVisible(False)
        layout.addWidget(self.sync_detail_label)

        self.price_label = QLabel("")
        self.price_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.price_label)

        layout.addWidget(QLabel("📋 محصولات مرتبط با گروه‌های انتخاب‌شده:"))

        # ── جستجو + فیلتر وضعیت لینک + انتخاب همه/هیچ ────────────────────
        product_search_row = QHBoxLayout()
        product_search_row.setSpacing(8)
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("🔍 جستجو در محصولات (نام، کد، قیمت)...")
        self.product_search.setLayoutDirection(Qt.RightToLeft)
        self.product_search.setMinimumHeight(36)
        self.product_search.textChanged.connect(self._filter_products)
        product_search_row.addWidget(self.product_search, 1)

        self.product_link_filter = QComboBox()
        self.product_link_filter.addItem("همه محصولات", "all")
        self.product_link_filter.addItem("✅ فقط لینک‌شده به فروشگاه", "linked")
        self.product_link_filter.addItem("⭕ فقط لینک‌نشده", "unlinked")
        self.product_link_filter.setMinimumHeight(36)
        self.product_link_filter.currentIndexChanged.connect(
            lambda _=0: self._filter_products(self.product_search.text())
        )
        product_search_row.addWidget(self.product_link_filter)

        self.product_type_filter = QComboBox()
        self.product_type_filter.addItem("همه انواع", "all")
        self.product_type_filter.addItem("⬜ فقط ساده", "simple")
        self.product_type_filter.addItem("🎨 فقط متغیر", "variant")
        self.product_type_filter.setMinimumHeight(36)
        self.product_type_filter.currentIndexChanged.connect(
            lambda _=0: self._filter_products(self.product_search.text())
        )
        product_search_row.addWidget(self.product_type_filter)

        self.stock_group_filter_input = QLineEdit()
        self.stock_group_filter_input.setPlaceholderText("🔗 کد کالای اصلی برای دیدن فرعی‌هاش...")
        self.stock_group_filter_input.setMaximumWidth(220)
        self.stock_group_filter_input.setMinimumHeight(36)
        self.stock_group_filter_input.setClearButtonEnabled(True)
        self.stock_group_filter_input.textChanged.connect(
            lambda _=None: self._filter_products(self.product_search.text())
        )
        product_search_row.addWidget(self.stock_group_filter_input)

        self.image_presence_filter = QComboBox()
        self.image_presence_filter.setLayoutDirection(Qt.RightToLeft)
        self.image_presence_filter.addItem("🖼️ همه (فیلتر تصویر خاموش)", "all")
        self.image_presence_filter.addItem("دارای تصویر در دیتابیس", "db")
        self.image_presence_filter.addItem("دارای تصویر در سایت", "site")
        self.image_presence_filter.addItem("دارای تصویر در هر دو", "both")
        self.image_presence_filter.addItem("بدون تصویر در هیچ‌کدام", "none")
        self.image_presence_filter.setMinimumHeight(36)
        self.image_presence_filter.setToolTip(
            f"فیلتر بر اساس اینکه محصول تو دیتابیس {self._erp_label()} و/یا سایت تصویر داره یا نه.\n"
            "برای تصویر «سایت»، اول یه‌بار دکمه‌ی «بررسی تعداد تصویر فروشگاه» رو بزنید."
        )
        self.image_presence_filter.currentIndexChanged.connect(
            lambda _=0: self._filter_products(self.product_search.text())
        )
        product_search_row.addWidget(self.image_presence_filter)

        self._product_selection_toggle = attach_selection_toggle(
            product_search_row,
            self,
            on_select_all=lambda: self._set_all_products_checked(True),
            on_select_none=lambda: self._set_all_products_checked(False),
        )
        layout.addLayout(product_search_row)

        self.product_list = QListWidget()
        self.product_list.setLayoutDirection(Qt.RightToLeft)
        self.product_list.setMouseTracking(True)
        self.product_list.itemEntered.connect(self.on_product_hover)
        self.product_list.viewport().installEventFilter(self)
        layout.addWidget(self.product_list)

        self.image_preview = QLabel(None)
        self.image_preview.setWindowFlags(Qt.ToolTip)
        self.image_preview.setAlignment(Qt.AlignCenter)
        self.image_preview.setStyleSheet(
            "background: #ffffff; border: 1px solid #cbd5e1; border-radius: 10px;"
            "padding: 4px;"
        )
        self.image_preview.setVisible(False)

        self.refresh_button = CompactCaptionButton(self._refresh_button_default_text)
        self.refresh_button.setToolTip(f"بروزرسانی لیست محصولات از {self._erp_label()}")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)

        self.sync_button = CompactCaptionButton(self._sync_button_idle_text)
        self.sync_button.setToolTip("ارسال محصولات انتخاب‌شده به فروشگاه")
        self.sync_button.clicked.connect(self._on_sync_clicked)

        self.upload_images_button = CompactCaptionButton(self._upload_images_idle_text)
        self.upload_images_button.setProperty("compactActionRole", "images")
        self.upload_images_button.setToolTip("انتقال تصاویر محصولات انتخابی به فروشگاه")
        self.upload_images_button.clicked.connect(self._on_upload_images_clicked)

        self.wc_admin_button = make_wc_admin_open_button(
            self, "products", button_factory=CompactCaptionButton
        )

        self.check_wc_images_button = CompactCaptionButton("🖼️ بررسی تعداد تصویر فروشگاه")
        self.check_wc_images_button.setToolTip(
            "با یه درخواست کارآمد (نه یکی‌یکی)، تعداد واقعی تصویر هر محصول رو "
            f"از فروشگاه می‌گیره و کنار تعداد تصویر {self._erp_label()} نشون می‌ده."
        )
        self.check_wc_images_button.clicked.connect(self._check_wc_image_counts)

        self.batch_schedule_button = CompactCaptionButton("📅 زمان‌بندیِ گروهی")
        self.batch_schedule_button.setToolTip(
            "برای محصولاتی که با چک‌باکسِ کنارشون انتخاب کرده‌اید، برای هرکدام "
            "یک پستِ جداگانه (با متن/عکسِ اختصاصی) در یک زمانِ مشخص به تقویمِ محتوا اضافه می‌کند."
        )
        self.batch_schedule_button.clicked.connect(self._open_batch_schedule_dialog)

        self._mobile_inbox_idle_text = "📥 عکس‌هایِ موبایل"
        self.mobile_inbox_button = CompactCaptionButton(self._mobile_inbox_idle_text)
        self.mobile_inbox_button.setToolTip(
            "عکس‌هایی که از برنامه‌ی همراهِ موبایل دریافت شده — بررسی و پیوست به محصولات"
        )
        self.mobile_inbox_button.clicked.connect(self._open_mobile_inbox_dialog)

        self._action_ops = TabActionController(self)
        self._action_ops.register(
            "refresh",
            ActionSpec(
                button=self.refresh_button,
                idle_text=self._refresh_button_default_text,
                stop_text="⏹ توقف بارگذاری",
                on_stop=self._stop_products_load,
            ),
        )
        self._action_ops.register(
            "sync",
            ActionSpec(
                button=self.sync_button,
                idle_text=self._sync_button_idle_text,
                stop_text="⏹ توقف ارسال محصولات",
                stop_style=self._sync_stop_style,
                on_stop=self._stop_products_sync,
            ),
        )
        self._action_ops.register(
            "images",
            ActionSpec(
                button=self.upload_images_button,
                idle_text=self._upload_images_idle_text,
                stop_text="⏹ توقف ارسال تصاویر",
                idle_style=self._upload_images_idle_style,
                stop_style=self._upload_images_stop_style,
                on_stop=self._stop_product_images_upload,
            ),
        )
        self._action_ops.register_extra_widgets(
            self.product_search,
            self.product_list,
            self._product_selection_toggle,
        )

        layout.addWidget(
            build_responsive_action_row(
                [self.refresh_button, self.sync_button, self.upload_images_button,
                 self.check_wc_images_button, self.batch_schedule_button,
                 self.mobile_inbox_button, self.wc_admin_button],
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

    def ensure_tab_data_loaded(self):
        if getattr(self, "_action_ops", None) is None:
            return
        from sync_app.core.tab_operation_guard import consume_pending_sql_reload

        consume_pending_sql_reload(self, lambda: self.load_products(manual=False))

    def _ops_busy(self) -> bool:
        ops = getattr(self, "_action_ops", None)
        return bool(ops and ops.busy)

    def _on_refresh_clicked(self):
        self._action_ops.handle_click(
            "refresh",
            lambda: self.load_products(manual=True),
        )

    def _on_sync_clicked(self):
        self._action_ops.handle_click("sync", self._start_send_products)

    def _set_products_status(self, state, text):
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

    def _begin_products_load(self, manual=False):
        self._loading_products = True
        self.load_progress.setVisible(True)
        self._action_ops.begin("refresh", lock_tabs=False)
        self._set_products_status("loading", "⏳ در حال دریافت محصولات از SQL...")
        if manual:
            log.info("🔄 کاربر: بروزرسانی لیست محصولات آغاز شد.")

    def _end_products_load(self):
        self._loading_products = False
        self.load_progress.setVisible(False)
        if self._action_ops.active == "refresh":
            self._action_ops.end()

    def _stop_products_load(self):
        self._products_load_generation += 1
        self._loading_products = False
        self.load_progress.setVisible(False)
        self._set_products_status("warning", "⏹ بارگذاری محصولات متوقف شد.")
        if self._action_ops.active == "refresh":
            self._action_ops.end()

    def _fetch_products_from_sql(self, config, selected_groups):
        price_col = config.get("PRICE_LIST_COLUMN", "Sel_Price")
        conn, _, _ = open_sql_connection(config, timeout=3)
        cursor = conn.cursor()
        like_conditions = " OR ".join(["A_Code LIKE ?" for _ in selected_groups])
        query = f"""
            SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5,
                   Exist
            FROM Article
            WHERE {like_conditions}
        """
        cursor.execute(query, [f"{group}%" for group in selected_groups])
        raw_rows = cursor.fetchall()

        # نکته‌ی مهم: تصویر واقعیِ کالا تو ستون Article.Picture/PicturePath
        # ذخیره نمی‌شه (اون‌ها ملاک نیستن) — منبع درست جدول HLOpictures هست
        # (Code = کد کالا، Type = 1 یعنی مال کالا، و می‌تونه چند تصویر
        # برای یه کد داشته باشه). این‌جا برای همون گروه‌های انتخابی،
        # تعداد + اولین تصویر واقعی رو می‌گیریم.
        pic_like_conditions = " OR ".join(["Code LIKE ?" for _ in selected_groups])
        pic_query = f"""
            SELECT Code, Picture, PicturePath
            FROM HLOpictures
            WHERE Type = 1 AND ({pic_like_conditions})
        """
        try:
            cursor.execute(pic_query, [f"{group}%" for group in selected_groups])
            pic_rows = cursor.fetchall()
        except Exception:
            pic_rows = []

        erp_images_by_code: dict[str, list[tuple[bytes, str]]] = {}
        for prow in pic_rows:
            code = str(prow[0]).strip()
            blob = bytes(prow[1]) if prow[1] else b""
            path = str(prow[2] or "").strip()
            if not blob and not path:
                continue
            erp_images_by_code.setdefault(code, []).append((blob, path))

        from sync_app.core.variation_query import load_variable_a_codes
        variable_codes = load_variable_a_codes(cursor)

        rows = []
        for row in raw_rows:
            sku = str(row[0]).strip()
            erp_images = erp_images_by_code.get(sku, [])
            first_blob, first_path = erp_images[0] if erp_images else (b"", "")
            rows.append({
                "sku": sku,
                "name": str(row[1]).strip(),
                "price": resolve_article_price(row, price_col, price_start_index=2),
                "stock": int(row[7] or 0),
                "picture_blob": first_blob,
                "picture_path": first_path,
                "erp_images": erp_images,  # لیست کامل (blob, path) — برای آپلود همه‌ی تصاویر
                "erp_image_count": len(erp_images),
                "is_variant": sku in variable_codes,
            })
        conn.close()
        return rows

    def load_products(self, manual=False):
        if manual and not ensure_connectivity(self, need_sql=True, need_wc=False):
            return

        self.config = load_secure_config(None)
        self._wc_api = None
        price_idx = self.config.get("PRICE_LIST_INDEX", 0) + 1
        self.price_label.setText(f"💰 قیمت‌ها بر اساس: لیست قیمت شماره {price_idx}")

        selected_groups = [str(g).strip() for g in self.config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()]
        if not selected_groups:
            self.product_list.clear()
            self._add_product_message("⚠️ هیچ گروهی انتخاب نشده است.")
            self._set_products_status(
                "warning",
                "⚠️ هیچ گروهی انتخاب نشده — ابتدا در تب دسته‌بندی‌ها گروه را تیک بزنید.",
            )
            if manual:
                QMessageBox.warning(
                    self,
                    "گروه انتخاب نشده",
                    "هیچ گروهی برای فیلتر محصولات انتخاب نشده است.\n"
                    "لطفاً در تب «دسته‌بندی‌ها» زیرگروه موردنظر را تیک بزنید.",
                )
            return

        if self._loading_products or self._ops_busy():
            self._set_products_status("warning", "⏳ بارگذاری قبلی هنوز در جریان است...")
            if manual:
                QMessageBox.information(
                    self,
                    "در حال بارگذاری",
                    "بارگذاری لیست محصولات هنوز تمام نشده است.\nلطفاً چند ثانیه صبر کنید.",
                )
            return

        self._products_load_generation += 1
        generation = self._products_load_generation
        self.product_list.clear()
        self._add_product_message("⏳ در حال بارگذاری محصولات از SQL...")
        self._begin_products_load(manual=manual)

        def _worker():
            return self._fetch_products_from_sql(self.config, selected_groups)

        def _done(rows):
            if generation != self._products_load_generation:
                return
            self._apply_products_rows(rows, manual=manual)

        def _fail(msg):
            if generation != self._products_load_generation:
                return
            self._products_load_failed(msg, manual=manual)

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _products_load_failed(self, error_msg, manual=False):
        err = format_db_error(Exception(str(error_msg)))
        self._end_products_load()
        self.product_list.clear()
        self._add_product_message(f"❌ خطا: {err[:400]}")
        self._set_products_status("error", f"❌ خطا در بارگذاری محصولات: {err[:120]}")
        log.error(f"❌ خطا در بارگذاری لیست محصولات: {err}")
        if manual:
            QMessageBox.critical(self, "خطای دیتابیس", f"بارگذاری محصولات ناموفق بود:\n{err}")

    def _apply_products_rows(self, rows, manual=False):
        self.product_list.clear()
        disabled_products = set(self.config.get("DISABLED_PRODUCT_SKUS", []))
        is_toman = bool(self.config.get("WC_CURRENCY_IS_TOMAN"))
        row_count = 0
        product_map = load_product_woo_map()

        try:
            for row in rows or []:
                row_count += 1
                sku = row["sku"]
                product_name = row["name"]
                price = row["price"] / (10.0 if is_toman else 1.0)
                picture_blob = row["picture_blob"]
                picture_path = row["picture_path"]
                erp_image_count = int(row.get("erp_image_count") or 0)
                has_erp_image = erp_image_count > 0
                image_url = self._image_url_cache.get(sku, "")
                if has_erp_image:
                    image_status = f"ERP ({erp_image_count})" if erp_image_count > 1 else "ERP"
                elif image_url:
                    image_status = "Woo"
                else:
                    image_status = "ندارد"

                is_linked = sku in product_map
                link_status = "✅ لینک" if is_linked else "⭕ لینک‌نشده"
                is_variant = bool(row.get("is_variant"))
                type_badge = "🎨 متغیر" if is_variant else "⬜ ساده"

                raw_text = (
                    f"{link_status} | {type_badge} | {product_name} | کد: {sku} | قیمت: {price:,.0f} | "
                    f"موجودی: {row['stock']} | تصویر: {image_status}"
                )
                item = QListWidgetItem()
                item.setData(Qt.UserRole, sku)
                item.setData(Qt.UserRole + 1, image_url)
                item.setData(Qt.UserRole + 2, picture_blob)
                item.setData(Qt.UserRole + 3, picture_path)
                item.setData(Qt.UserRole + 14, row.get("erp_images") or [])
                item.setData(Qt.UserRole + 4, product_name)
                item.setData(Qt.UserRole + 6, raw_text.lower())
                item.setData(Qt.UserRole + 10, row.get("stock"))
                item.setData(Qt.UserRole + 11, price)
                item.setData(Qt.UserRole + 12, is_linked)
                item.setData(Qt.UserRole + 13, is_variant)
                item.setData(Qt.UserRole + 15, erp_image_count)

                row_widget = ProductRowWidget(
                    self._rtl_display(raw_text),
                    sku not in disabled_products,
                    on_toggle=lambda checked, s=sku: self._on_product_toggle_by_sku(s, checked),
                    on_upload=lambda _=False, s=sku, it=item: self._upload_images_for_product(s, it),
                    on_clear=lambda s=sku, it=item: self._clear_images_for_product(s, it),
                    on_seo=lambda s=sku, it=item: self._open_seo_dialog(s, it),
                    on_pipeline=lambda s=sku, it=item: self._open_pipeline_dialog(s, it),
                    on_content=lambda s=sku, it=item: self._open_content_studio_dialog(s, it),
                    on_smart_prep=lambda s=sku, it=item: self._run_smart_prep(s, it),
                    on_delete=lambda s=sku, it=item, n=product_name: self._delete_product_from_wc(s, it, n),
                    on_stock_mode_changed=lambda mode, s=sku: self._set_product_stock_mode(s, mode),
                    on_stock_group=lambda s=sku, n=product_name: self._manage_stock_group(s, n),
                    on_store_category=lambda s=sku, n=product_name: self._manage_store_category(s, n),
                    parent=self.product_list,
                )
                from sync_app.core.stock_mode import get_product_stock_mode_override
                row_widget.set_stock_mode_override(get_product_stock_mode_override(self.config, sku))

                from sync_app.core.stock_group import get_primary_of, get_secondaries_of
                _primary_of_this = get_primary_of(self.config, sku)
                _secondaries_of_this = get_secondaries_of(self.config, sku)
                if _primary_of_this:
                    row_widget.set_stock_group_state("secondary", f"فرعیِ کد: {_primary_of_this}")
                elif _secondaries_of_this:
                    row_widget.set_stock_group_state(
                        "primary", f"اصلیِ {len(_secondaries_of_this)} کد فرعی: {', '.join(_secondaries_of_this)}"
                    )
                else:
                    row_widget.set_stock_group_state("none")

                from sync_app.core.product_category_override import get_manual_category_ids
                _manual_cat_ids = get_manual_category_ids(sku)
                if _manual_cat_ids:
                    row_widget.set_store_category_state(
                        True, f"idِ دسته‌بندی‌هایِ دستی: {', '.join(str(i) for i in _manual_cat_ids)}"
                    )
                else:
                    row_widget.set_store_category_state(False)
                manual_paths = self._existing_manual_image_paths(sku)
                row_widget.set_manual_upload_count(len(manual_paths))
                item.setData(Qt.UserRole + 7, manual_paths)
                item.setSizeHint(QSize(0, 52))
                self.product_list.addItem(item)
                self.product_list.setItemWidget(item, row_widget)

            if row_count == 0:
                self._add_product_message(
                    "ℹ️ برای گروه‌های انتخاب‌شده محصولی یافت نشد. کد گروه/داده Article را بررسی کنید."
                )
                self._set_products_status(
                    "info",
                    "ℹ️ محصولی برای گروه‌های انتخاب‌شده یافت نشد.",
                )
                log.info("ℹ️ بروزرسانی لیست محصولات: موردی یافت نشد.")
            else:
                groups_text = "، ".join(
                    str(g).strip()
                    for g in self.config.get("SELECTED_SUB_GROUPS", [])
                    if str(g).strip()
                )
                self._set_products_status(
                    "success",
                    f"✅ {row_count} محصول بارگذاری شد (گروه‌ها: {groups_text})",
                )
                log.info(f"✅ بروزرسانی لیست محصولات: {row_count} مورد بارگذاری شد.")
            self._filter_products(self.product_search.text())
            self._end_products_load()
            if manual:
                if row_count == 0:
                    QMessageBox.information(
                        self,
                        "نتیجه بروزرسانی",
                        "برای گروه‌های انتخاب‌شده محصولی در دیتابیس یافت نشد.",
                    )
                else:
                    QMessageBox.information(
                        self,
                        "بروزرسانی موفق",
                        f"{row_count} محصول از {self._erp_label()} بارگذاری شد.",
                    )
        except Exception:
            self._end_products_load()
            raise

    def _rtl_display(self, text):
        return f"\u202B{text}\u202C"

    def _add_product_message(self, text):
        item = QListWidgetItem(self._rtl_display(text))
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.product_list.addItem(item)

    def on_product_toggle(self, item):
        # backward compatibility: in layout جدید از _on_product_toggle_by_sku استفاده می‌شود
        if self._loading_products:
            return

        sku = item.data(Qt.UserRole)
        if not sku:
            return

        cfg = load_secure_config(None) or {}
        disabled_products = set(cfg.get("DISABLED_PRODUCT_SKUS", []))

        if item.checkState() == Qt.Checked:
            disabled_products.discard(sku)
        else:
            disabled_products.add(sku)

        cfg["DISABLED_PRODUCT_SKUS"] = sorted(disabled_products)
        from sync_app.core.secure_config_loader import save_secure_config
        save_secure_config(cfg)

    def _on_product_toggle_by_sku(self, sku, checked):
        if self._loading_products or not sku:
            return

        cfg = load_secure_config(None) or {}
        disabled_products = set(cfg.get("DISABLED_PRODUCT_SKUS", []))
        if checked:
            disabled_products.discard(sku)
        else:
            disabled_products.add(sku)
        cfg["DISABLED_PRODUCT_SKUS"] = sorted(disabled_products)
        from sync_app.core.secure_config_loader import save_secure_config
        save_secure_config(cfg)

    def _images_manifest_path(self):
        return site_scoped_path("product_images_map.json")

    def _load_uploaded_images_map(self):
        path = self._images_manifest_path()
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {str(k): list(v) for k, v in data.items() if isinstance(v, list)}
        except Exception:
            pass
        return {}

    def reload_site_scoped_caches(self):
        """بعد از سوئیچِ سایت/پریست (بدونِ بستنِ تب) صدا زده می‌شه — چون
        self._uploaded_images_map یک‌بار موقعِ ساختِ تب لود شده و اگه اینجا
        دوباره از دیسک لود نشه، همچنان دیتایِ سایتِ قبلی رو تویِ حافظه
        نگه می‌داره، حتی با اینکه مسیرِ فایل حالا به‌درستی برایِ سایتِ
        جدید scoped شده."""
        self._uploaded_images_map = self._load_uploaded_images_map()

    def _save_uploaded_images_map(self):
        path = self._images_manifest_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._uploaded_images_map, f, ensure_ascii=False, indent=2)

    def _product_image_abs_path(self, rel_path: str) -> str:
        path = (rel_path or "").strip()
        if not path:
            return ""
        abs_path = path if os.path.isabs(path) else app_path(path)
        return abs_path if os.path.isfile(abs_path) else ""

    def _existing_manual_image_paths(self, sku: str) -> list[str]:
        out = []
        for rel in self._uploaded_images_map.get(sku, []) or []:
            if self._product_image_abs_path(rel):
                out.append(rel)
        return out

    def _erp_image_paths_for_item(self, sku, item) -> list[str]:
        if item is None:
            return []
        blob = item.data(Qt.UserRole + 2) or b""
        picture_path = item.data(Qt.UserRole + 3) or ""
        all_erp_images = item.data(Qt.UserRole + 14) or []
        # اولین تصویر همون blob/picture_path بالاست — بقیه‌شون (اگه بیشتر
        # از یکی باشه) به‌عنوان extra_images پاس داده می‌شن تا همه منتقل بشن.
        extra_images = list(all_erp_images[1:]) if len(all_erp_images) > 1 else []
        out = []
        for rel in stage_erp_images(sku, blob, picture_path, self.config or {}, extra_images=extra_images):
            if self._product_image_abs_path(rel):
                out.append(rel)
        return out

    def _existing_image_paths_for_product(self, sku, item) -> list[str]:
        """فقط مسیرهایی که فایل روی دیسک دارند — دستی + ERP."""
        paths = list(self._existing_manual_image_paths(sku))
        for rel in self._erp_image_paths_for_item(sku, item):
            if rel not in paths:
                paths.append(rel)
        return paths

    def _prune_stale_manual_images(self, sku, item=None):
        """حذف مسیرهای مرده از نگاشت + به‌روز UI."""
        raw = list(self._uploaded_images_map.get(sku, []) or [])
        valid = self._existing_manual_image_paths(sku)
        if raw == valid:
            return False
        if valid:
            self._uploaded_images_map[sku] = valid
        else:
            self._uploaded_images_map.pop(sku, None)
        self._save_uploaded_images_map()
        if item is not None:
            item.setData(Qt.UserRole + 7, valid)
            row_widget = self.product_list.itemWidget(item)
            if isinstance(row_widget, ProductRowWidget):
                row_widget.set_manual_upload_count(len(valid))
        return True

    def _find_item_by_sku(self, sku):
        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            if str(item.data(Qt.UserRole) or "") == sku:
                return item
        return None

    def _attach_manual_image_file(self, sku, src_path, product_name=""):
        """کپیِ یک فایلِ تصویر به پوشه‌ی محصول + اجرایِ پایپ‌لاینِ خودکار
        (اگه فعال باشه) + افزودن به نگاشتِ تصاویرِ دستیِ محصول. اگه ردیفِ
        محصول تویِ لیستِ فعلاً بارگذاری‌شده باشه، UI هم به‌روز می‌شه.
        مسیرِ نسبیِ ذخیره‌شده رو برمی‌گردونه."""
        dst_dir = app_path("product_images", sku)
        os.makedirs(dst_dir, exist_ok=True)

        from sync_app.core.smart_publish import (
            AUTO_RUN_KEY, AUTO_PIPELINE_KEY, load_pipelines, load_watermark_settings,
            load_ai_studio_settings, run_pipeline, load_text_engrave_settings, load_qr_code_settings,
        )
        from sync_app.core.media_center import load_image_profiles

        config = load_secure_config(None) or {}
        auto_run = bool(config.get(AUTO_RUN_KEY, False))
        auto_pipeline_name = config.get(AUTO_PIPELINE_KEY)
        pipelines = load_pipelines(config) if auto_run else {}
        auto_pipeline = pipelines.get(auto_pipeline_name) if auto_pipeline_name else None

        # اطلاعاتی که مراحل «حک متن» و «QR کد» بهشون نیاز دارن — کد کالا،
        # نام محصول، و لینک محصول رو سایت (اگه قبلاً به فروشگاه لینک شده باشه).
        product_url = ""
        try:
            wc_id = load_product_woo_map().get(sku)
            site_url = str(config.get("WC_URL") or "").strip().rstrip("/")
            if wc_id and site_url:
                product_url = f"{site_url}/?p={int(wc_id)}"
        except Exception:
            product_url = ""
        product_info = {"a_code": sku, "a_code_c": sku, "name": product_name, "product_url": product_url}

        base = os.path.basename(src_path)
        timestamp = str(int(time.time() * 1000))
        dst_name = f"{timestamp}_{base}"
        dst_abs = os.path.join(dst_dir, dst_name)
        shutil.copy2(src_path, dst_abs)

        if auto_pipeline:
            steps = auto_pipeline.get("steps", [])
            profile_name = auto_pipeline.get("profile", "")
            profiles = load_image_profiles(config)
            profile = profiles.get(profile_name) if profile_name else None
            watermark = load_watermark_settings(config)
            ai_studio = load_ai_studio_settings(config)
            result = run_pipeline(
                dst_abs, steps, out_dir=dst_dir, profile=profile, watermark=watermark,
                ai_studio=ai_studio,
                text_engrave=load_text_engrave_settings(config),
                qr_code=load_qr_code_settings(config),
                product_info=product_info,
            )
            if result.ok:
                # فایل نهایی پردازش‌شده جای فایل خام می‌شینه
                final_ext = os.path.splitext(result.dst_path)[1]
                final_name = f"{timestamp}_{os.path.splitext(base)[0]}{final_ext}"
                final_abs = os.path.join(dst_dir, final_name)
                os.replace(result.dst_path, final_abs)
                if os.path.isfile(dst_abs) and dst_abs != final_abs:
                    os.remove(dst_abs)
                dst_name = final_name
            else:
                log.warning(f"⚠️ Smart Publish خودکار روی {base} ناموفق بود: {result.error}")

        rel_path = os.path.join("product_images", sku, dst_name).replace("\\", "/")

        rel_paths = list(self._existing_manual_image_paths(sku))
        rel_paths.append(rel_path)
        self._uploaded_images_map[sku] = rel_paths
        self._save_uploaded_images_map()

        item = self._find_item_by_sku(sku)
        if item is not None:
            item.setData(Qt.UserRole + 7, rel_paths)
            row_widget = self.product_list.itemWidget(item)
            if isinstance(row_widget, ProductRowWidget):
                row_widget.set_manual_upload_count(len(rel_paths))

        return rel_path

    def _upload_images_for_product(self, sku, item):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            f"انتخاب تصاویر برای محصول {sku}",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not files:
            return

        product_name = str(item.data(Qt.UserRole + 4) or "") if item else ""
        for src in files:
            try:
                self._attach_manual_image_file(sku, src, product_name)
            except Exception as exc:
                QMessageBox.warning(self, "خطا", f"کپی تصویر ناموفق بود: {exc}")

    def _clear_images_for_product(self, sku, item):
        """حذف تصاویر دستی محصول از نگاشت و دیسک."""
        manual = self._existing_manual_image_paths(sku)
        if not manual and not self._uploaded_images_map.get(sku):
            return

        confirm = QMessageBox.question(
            self,
            "حذف تصاویر",
            f"تصاویر دستی محصول {sku} حذف شوند؟\n"
            f"(تصاویر {self._erp_label()} و گالری فروشگاه تغییری نمی‌کند.)",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        for rel in list(self._uploaded_images_map.get(sku, []) or []):
            abs_path = self._product_image_abs_path(rel)
            if abs_path and os.path.isfile(abs_path):
                try:
                    os.remove(abs_path)
                except Exception as exc:
                    log.warning(f"⚠️ حذف فایل {abs_path}: {exc}")

        self._uploaded_images_map.pop(sku, None)
        self._save_uploaded_images_map()
        item.setData(Qt.UserRole + 7, [])
        row_widget = self.product_list.itemWidget(item)
        if isinstance(row_widget, ProductRowWidget):
            row_widget.set_manual_upload_count(0)
        self.image_preview.hide()

    # ------------------------------------------------------------------
    # صندوقِ ورودیِ عکس‌هایِ موبایل — بررسی/پیوستِ عکس‌هایی که برنامه‌ی
    # همراه رویِ شبکه‌ی محلی به سرورِ محلیِ پیچا فرستاده.
    # ------------------------------------------------------------------
    _MOBILE_INBOX_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

    def _list_mobile_inbox_files(self):
        from sync_app.core import mobile_photo_server

        directory = mobile_photo_server.inbox_dir()
        try:
            return directory, sorted(
                f for f in os.listdir(directory)
                if f.lower().endswith(self._MOBILE_INBOX_IMAGE_EXTS)
                and os.path.isfile(os.path.join(directory, f))
            )
        except Exception:
            return directory, []

    def _refresh_mobile_inbox_badge(self):
        try:
            _, filenames = self._list_mobile_inbox_files()
        except Exception:
            return
        count = len(filenames)
        if count > 0:
            self.mobile_inbox_button.setText(f"{self._mobile_inbox_idle_text} ({count})")
        else:
            self.mobile_inbox_button.setText(self._mobile_inbox_idle_text)

    def _guess_sku_for_filename(self, filename, known_skus):
        stem = os.path.splitext(filename)[0]
        tokens = [t for t in re.split(r"[^A-Za-z0-9؀-ۿ]+", stem) if t]
        for t in tokens:
            if t in known_skus:
                return t
        upper_map = {str(s).upper(): s for s in known_skus}
        for t in tokens:
            if t.upper() in upper_map:
                return upper_map[t.upper()]
        for s in known_skus:
            if s and s in stem:
                return s
        return ""

    def _open_mobile_inbox_dialog(self):
        directory, filenames = self._list_mobile_inbox_files()
        if not filenames:
            QMessageBox.information(
                self,
                "خالی",
                "فعلاً هیچ عکسی از برنامه‌ی همراهِ موبایل دریافت نشده.\n"
                "اگه تازه از گوشی فرستادید، چند لحظه صبر کنید و دوباره امتحان کنید.",
            )
            self._refresh_mobile_inbox_badge()
            return

        known_skus = {
            str(self.product_list.item(i).data(Qt.UserRole) or "")
            for i in range(self.product_list.count())
        }
        known_skus.discard("")

        dlg = QDialog(self)
        dlg.setWindowTitle(f"📥 عکس‌هایِ دریافتی از موبایل ({len(filenames)})")
        dlg.setLayoutDirection(Qt.RightToLeft)
        dlg.resize(560, 620)
        outer = QVBoxLayout(dlg)

        hint = QLabel(
            "کدِ کالایِ هر عکس از رویِ نامِ فایل حدس زده شده — در صورتِ نیاز اصلاحش "
            "کنید و «پیوست» بزنید تا به تصاویرِ دستیِ همون محصول اضافه بشه (همون "
            "مسیرِ «انتقال تصاویر» — با پایپ‌لاینِ خودکار در صورتِ فعال بودن). "
            "«حذف» فقط از صفِ دریافتی پاک می‌کنه، بدونِ پیوست‌کردن."
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_body = QWidget()
        rows_layout = QVBoxLayout(scroll_body)
        rows_layout.setSpacing(8)
        scroll.setWidget(scroll_body)
        outer.addWidget(scroll, 1)

        remaining = {"count": len(filenames)}

        def _forget_row(row_widget):
            row_widget.setParent(None)
            row_widget.deleteLater()
            remaining["count"] -= 1
            dlg.setWindowTitle(f"📥 عکس‌هایِ دریافتی از موبایل ({remaining['count']})")
            self._refresh_mobile_inbox_badge()
            if remaining["count"] <= 0:
                dlg.accept()

        def _do_discard(path, row_widget):
            confirm = QMessageBox.question(
                dlg, "حذف",
                f"عکسِ «{os.path.basename(path)}» بدونِ پیوست‌شدن حذف بشه؟",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            try:
                os.remove(path)
            except Exception as exc:
                QMessageBox.warning(dlg, "خطا", f"حذف ناموفق بود:\n{exc}")
                return
            _forget_row(row_widget)

        def _do_attach(path, sku_edit, row_widget):
            sku = sku_edit.text().strip()
            if not sku:
                QMessageBox.warning(dlg, "کدِ کالا خالیه", "لطفاً کدِ کالا رو وارد کنید.")
                return
            item = self._find_item_by_sku(sku)
            product_name = str(item.data(Qt.UserRole + 4) or "") if item is not None else ""
            try:
                self._attach_manual_image_file(sku, path, product_name)
                os.remove(path)
            except Exception as exc:
                QMessageBox.warning(dlg, "خطا", f"پیوستِ عکس ناموفق بود:\n{exc}")
                return
            _forget_row(row_widget)

        for filename in filenames:
            full_path = os.path.join(directory, filename)
            row = QWidget()
            row.setStyleSheet(
                "background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;"
            )
            row_layout = QHBoxLayout(row)

            thumb = QLabel()
            pix = QPixmap(full_path)
            if not pix.isNull():
                thumb.setPixmap(
                    pix.scaled(64, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                )
            thumb.setFixedSize(64, 64)
            thumb.setScaledContents(True)
            row_layout.addWidget(thumb)

            info_col = QVBoxLayout()
            fname_label = QLabel(filename)
            fname_label.setStyleSheet("font-size: 11px; color: #64748b;")
            fname_label.setWordWrap(True)
            info_col.addWidget(fname_label)

            sku_row = QHBoxLayout()
            sku_row.addWidget(QLabel("کدِ کالا:"))
            sku_edit = QLineEdit(self._guess_sku_for_filename(filename, known_skus))
            sku_edit.setPlaceholderText("کدِ کالا را وارد کنید...")
            sku_row.addWidget(sku_edit, 1)
            info_col.addLayout(sku_row)
            row_layout.addLayout(info_col, 1)

            attach_btn = QPushButton("✅ پیوست")
            attach_btn.setStyleSheet(
                "background: #16a34a; color: white; border-radius: 8px; padding: 6px 12px; font-weight: bold;"
            )
            discard_btn = QPushButton("🗑️ حذف")
            discard_btn.setStyleSheet(
                "background: #fee2e2; color: #b91c1c; border-radius: 8px; padding: 6px 12px;"
            )
            row_layout.addWidget(attach_btn)
            row_layout.addWidget(discard_btn)

            attach_btn.clicked.connect(
                lambda _=False, p=full_path, e=sku_edit, r=row: _do_attach(p, e, r)
            )
            discard_btn.clicked.connect(lambda _=False, p=full_path, r=row: _do_discard(p, r))

            rows_layout.addWidget(row)

        rows_layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)

        dlg.exec_()
        self._refresh_mobile_inbox_badge()

    # ------------------------------------------------------------------
    # سئو: امتیاز واقعی (از روی داده‌ی زنده‌ی سایت) + رفع موارد ناقص
    # ------------------------------------------------------------------
    def _manage_stock_group(self, sku, product_name=""):
        from sync_app.core.stock_group import get_primary_of, get_secondaries_of, set_secondary_link

        config = load_secure_config(None) or {}
        current_primary = get_primary_of(config, sku) or ""
        my_secondaries = get_secondaries_of(config, sku)

        info = ""
        if my_secondaries:
            info = f"\n\nاین محصول الان «اصلیه» و این کدها فرعی‌اش هستن: {', '.join(my_secondaries)}"

        text, ok = QInputDialog.getText(
            self, f"گروه موجودی مشترک — {product_name or sku}",
            "اگه این محصول «فرعیِ» یه کد کالای دیگه‌ست، اون کد رو اینجا بنویسید "
            "(خودش دیگه به سایت ارسال نمی‌شه، فقط موجودیش به اون کد اضافه می‌شه).\n"
            "برای پاک‌کردن لینک، خالی بذارید و تأیید کنید." + info,
            text=current_primary,
        )
        if not ok:
            return
        new_primary = text.strip()

        if my_secondaries and new_primary:
            QMessageBox.warning(
                self, "غیرممکن",
                "این محصول خودش الان «اصلیِ» یه گروهه — نمی‌تونه هم‌زمان فرعی یه کد دیگه هم باشه.",
            )
            return

        set_secondary_link(sku, new_primary or None)
        if new_primary:
            QMessageBox.information(self, "ثبت شد", f"محصول {sku} فرعیِ {new_primary} شد و دیگه مستقل به سایت ارسال نمی‌شه.")
        else:
            QMessageBox.information(self, "پاک شد", f"محصول {sku} دیگه فرعی هیچ کدی نیست.")
        self.config = load_secure_config(None) or {}
        self.load_products(manual=False)

    def _manage_store_category(self, sku, product_name=""):
        """دسته‌بندیِ این محصول رو مستقیم از دسته‌بندی‌هایِ واقعیِ سایت
        (نه ERP) انتخاب می‌کنه — برایِ سایت‌هایی که از قبل ساختارِ
        دسته‌بندیِ خودشون رو دارن. لیستِ زنده از خودِ فروشگاه گرفته می‌شه."""
        from sync_app.core.product_category_override import get_manual_category_ids

        config = load_secure_config(None) or {}
        current_ids = set(get_manual_category_ids(sku) or [])

        site_url = str(config.get("WC_URL") or config.get("PS_URL") or "").strip()
        if not site_url:
            QMessageBox.warning(
                self,
                "سایت تنظیم نشده",
                "برای دریافتِ دسته‌بندی‌هایِ زنده‌ی سایت، ابتدا آدرسِ فروشگاه را در تبِ "
                "تنظیمات وارد و ذخیره کنید.",
            )
            return

        progress = QMessageBox(self)
        progress.setWindowTitle("در حال دریافت")
        progress.setText(
            f"دریافتِ دسته‌بندی‌هایِ زنده‌ی سایت برایِ «{product_name or sku}»...\n"
            "(اگر بیش از حد طول کشید، «لغو» بزنید)"
        )
        progress.setStandardButtons(QMessageBox.Cancel)
        progress.show()
        QApplication.processEvents()

        state = {"finished": False}

        watchdog = QTimer(self)
        watchdog.setSingleShot(True)
        watchdog.setInterval(45000)

        def _finish_once():
            if state["finished"]:
                return False
            state["finished"] = True
            watchdog.stop()
            progress.close()
            return True

        def _on_cancel():
            if _finish_once():
                log.warning("⚠️ دریافتِ دسته‌بندی‌هایِ زنده‌ی سایت توسطِ کاربر لغو شد.")

        progress.rejected.connect(_on_cancel)

        def _on_watchdog_timeout():
            if _finish_once():
                QMessageBox.critical(
                    self,
                    "پایانِ زمان",
                    "دریافتِ دسته‌بندی‌هایِ سایت بیش از حدِ انتظار طول کشید.\n"
                    "اتصال به اینترنت و تنظیماتِ فروشگاه را بررسی کنید.",
                )

        watchdog.timeout.connect(_on_watchdog_timeout)
        watchdog.start()

        def _worker():
            from sync_app.core.integrations.commerce_provider import fetch_store_slug_map

            return fetch_store_slug_map(config, timeout=25)

        def _done(slug_map):
            if not _finish_once():
                return
            self._open_store_category_picker(sku, product_name, slug_map, current_ids)

        def _fail(msg):
            if not _finish_once():
                return
            QMessageBox.critical(self, "خطا", f"دریافتِ دسته‌بندی‌هایِ سایت ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _open_store_category_picker(self, sku, product_name, slug_map, current_ids):
        cats = sorted((slug_map or {}).values(), key=lambda c: str(c.get("name") or ""))
        if not cats:
            QMessageBox.warning(self, "خالی", "هیچ دسته‌بندی‌ای از سایت دریافت نشد.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"دسته‌بندیِ سایت — {product_name or sku}")
        dlg.setLayoutDirection(Qt.RightToLeft)
        dlg.resize(420, 480)
        layout = QVBoxLayout(dlg)

        hint = QLabel(
            "دسته‌بندیِ(هایِ) واقعیِ سایت رو برایِ این محصول انتخاب کنید. "
            "این انتخاب رویِ منطقِ خودکارِ (ERP→دسته‌بندی) اولویت داره و در "
            "همگام‌سازی‌هایِ بعدی هم حفظ می‌شه — تا خودتون دوباره تغییرش بدید."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        search = QLineEdit()
        search.setPlaceholderText("جستجویِ نام دسته‌بندی...")
        layout.addWidget(search)

        list_widget = QListWidget()
        list_widget.setLayoutDirection(Qt.RightToLeft)
        for cat in cats:
            cid = int(cat.get("id") or 0)
            if not cid:
                continue
            name = str(cat.get("name") or f"#{cid}")
            item = QListWidgetItem(f"{name} ({cid})")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if cid in current_ids else Qt.Unchecked)
            item.setData(Qt.UserRole, cid)
            item.setData(Qt.UserRole + 1, name.lower())
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        def _apply_search(text):
            needle = (text or "").strip().lower()
            for i in range(list_widget.count()):
                it = list_widget.item(i)
                it.setHidden(bool(needle) and needle not in (it.data(Qt.UserRole + 1) or ""))

        search.textChanged.connect(_apply_search)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("↩️ بازگشت به حالتِ خودکار")
        clear_btn.setToolTip("حذفِ کاملِ این override — دوباره از منطقِ خودکارِ ERP→دسته‌بندی استفاده می‌شه")
        btn_row.addWidget(clear_btn)
        btn_row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

        result = {"action": None}

        def _on_clear():
            result["action"] = "clear"
            dlg.accept()

        clear_btn.clicked.connect(_on_clear)
        buttons.accepted.connect(lambda: (result.__setitem__("action", "save"), dlg.accept()))
        buttons.rejected.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted or result["action"] is None:
            return

        from sync_app.core.product_category_override import set_manual_category_ids

        if result["action"] == "clear":
            set_manual_category_ids(sku, None)
            QMessageBox.information(self, "پاک شد", f"دسته‌بندیِ دستیِ محصول {sku} پاک شد — دوباره خودکار می‌شه.")
        else:
            selected_ids = [
                list_widget.item(i).data(Qt.UserRole)
                for i in range(list_widget.count())
                if list_widget.item(i).checkState() == Qt.Checked
            ]
            set_manual_category_ids(sku, selected_ids or None)
            if selected_ids:
                QMessageBox.information(self, "ثبت شد", f"دسته‌بندیِ دستیِ محصول {sku} ثبت شد.")
            else:
                QMessageBox.information(self, "پاک شد", f"دسته‌بندیِ دستیِ محصول {sku} پاک شد — دوباره خودکار می‌شه.")

        self.load_products(manual=False)

    def _set_product_stock_mode(self, sku, mode):
        from sync_app.core.stock_mode import set_product_stock_mode_override
        set_product_stock_mode_override(sku, mode)
        self.config = load_secure_config(None) or {}

    def _check_wc_image_counts(self):
        self.check_wc_images_button.setEnabled(False)
        self.check_wc_images_button.setText("⏳ در حال دریافت از فروشگاه...")
        config = load_secure_config(None) or {}

        def _worker():
            from sync_app.core.wc_sync_helper import wc_rest_json

            counts: dict[str, int] = {}
            page = 1
            while True:
                batch = wc_rest_json(
                    config, "GET", "products",
                    params={"per_page": 100, "page": page, "_fields": "sku,images"},
                    label=f"دریافت تعداد تصویر محصولات صفحه {page}",
                )
                if not batch:
                    break
                for p in batch:
                    sku = str(p.get("sku") or "").strip()
                    if sku:
                        counts[sku] = len(p.get("images") or [])
                if len(batch) < 100:
                    break
                page += 1
            return counts

        def _done(counts):
            self._wc_image_count_cache.update(counts)
            self.check_wc_images_button.setEnabled(True)
            self.check_wc_images_button.setText("🖼️ بررسی تعداد تصویر فروشگاه")
            self._refresh_row_texts_with_wc_counts()
            QMessageBox.information(
                self, "انجام شد", f"تعداد تصویر {len(counts)} محصول از فروشگاه دریافت شد."
            )

        def _fail(msg):
            self.check_wc_images_button.setEnabled(True)
            self.check_wc_images_button.setText("🖼️ بررسی تعداد تصویر فروشگاه")
            QMessageBox.critical(self, "خطا", f"دریافت تعداد تصویر از فروشگاه ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _refresh_row_texts_with_wc_counts(self):
        """بعد از دریافت تعداد تصویر فروشگاه، متن هر ردیف رو (بدون بارگذاری مجدد از SQL) به‌روز می‌کنه."""
        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            sku = str(item.data(Qt.UserRole) or "").strip()
            if sku not in self._wc_image_count_cache:
                continue
            row_widget = self.product_list.itemWidget(item)
            if isinstance(row_widget, ProductRowWidget):
                row_widget.set_wc_image_count(self._wc_image_count_cache[sku])

    def _delete_product_from_wc(self, sku, item, product_name=""):
        from sync_app.core.integrations.commerce_provider import (
            is_prestashop, store_platform_label,
        )

        config = load_secure_config(None) or {}
        ps_mode = is_prestashop(config)
        product_map = load_product_woo_map()
        wc_id = product_map.get(sku)
        if not wc_id:
            QMessageBox.information(
                self, "لینک نشده",
                f"محصول {sku} اصلاً به {store_platform_label(config)} لینک نشده — چیزی برای حذف روی سایت نیست.",
            )
            return

        if ps_mode:
            # پرستاشاپ زباله‌دان (soft-delete) نداره — فقط حذف کامل.
            confirmed = ask_yes_no(
                self, "حذف محصول از پرستاشاپ",
                f"محصول «{product_name or sku}» (کد {sku}) برای همیشه از پرستاشاپ پاک بشه؟\n"
                "هیچ راه بازگردانی‌ای نداره.",
                icon=QMessageBox.Warning,
            )
            if not confirmed:
                return
            force = True
        else:
            box = QMessageBox(self)
            box.setWindowTitle("حذف محصول از فروشگاه")
            box.setText(
                f"محصول «{product_name or sku}» (کد {sku}) از سایت حذف بشه؟\n\n"
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
                    f"مطمئنید؟ محصول «{product_name or sku}» برای همیشه از فروشگاه پاک می‌شه "
                    "و هیچ راه بازگردانی‌ای نداره.",
                    icon=QMessageBox.Warning,
                )
                if not confirm2:
                    return

        def _worker():
            from sync_app.core.integrations.commerce_provider import build_store_api

            if not ps_mode:
                apply_network_overrides(config)
            wcapi = build_store_api(config)
            resp = wcapi.delete(f"products/{int(wc_id)}", params={"force": force})
            if int(getattr(resp, "status_code", 0) or 0) >= 400:
                raise RuntimeError(wc_http_error_message(resp))
            return resp.json()

        def _done(_data):
            pmap = load_product_woo_map()
            pmap.pop(sku, None)
            save_product_woo_map(pmap)
            msg = "برای همیشه حذف شد" if force else "به زباله‌دان منتقل شد"
            QMessageBox.information(self, "انجام شد", f"محصول {sku} {msg}.")
            self.load_products(manual=False)

        def _fail(err_msg):
            QMessageBox.critical(self, "خطا در حذف", f"حذف محصول {sku} ناموفق بود:\n{err_msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _open_seo_dialog(self, sku, item):
        product_map = load_product_woo_map()
        wc_id = product_map.get(sku)
        if not wc_id:
            QMessageBox.information(
                self,
                "ابتدا همگام‌سازی کنید",
                f"محصول {sku} هنوز با فروشگاه همگام نشده — ابتدا سینک کنید.",
            )
            return

        config = load_secure_config(None) or {}
        fallback_name = item.data(Qt.UserRole + 4)

        def _worker():
            from sync_app.core.integrations.commerce_provider import is_prestashop

            if is_prestashop(config):
                return _fetch_ps_seo_bundle(config, wc_id)
            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            resp = wcapi.get(
                f"products/{int(wc_id)}",
                params={"_fields": "id,name,short_description,description,categories,images,meta_data"},
            )
            live = resp.json()
            if not isinstance(live, dict) or not live.get("id"):
                raise RuntimeError(f"دریافت اطلاعات زنده‌ی محصول ناموفق بود: {live}")
            return analyze_product_seo_live(live, fallback_name=fallback_name, fallback_desc="")

        def _done(bundle):
            self._show_seo_review_dialog(sku, wc_id, bundle)

        def _fail(msg):
            QMessageBox.critical(self, "خطا", f"دریافت وضعیت سئوی محصول {sku} ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _show_seo_review_dialog(self, sku, wc_id, bundle):
        field_labels = {
            "description": "توضیحات کامل محصول",
            "short_description": "توضیح کوتاه",
            "alt_text": "Alt تصویر",
            "meta_description": "متا دیسکریپشن",
            "seo_title": "عنوان سئو",
            "meta_keywords": "کلمات کلیدی",
        }
        checks = bundle["checks"]
        suggestions = bundle["suggestions"]

        dialog = QDialog(self)
        dialog.setWindowTitle(f"سئوی محصول — {sku}")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.resize(560, 680)
        layout = QVBoxLayout(dialog)

        score_label = QLabel(f"امتیاز فعلی (واقعی، از روی سایت): {bundle['current_score']}/100")
        score_label.setStyleSheet("font-weight:700; font-size:14px;")
        layout.addWidget(score_label)

        status_lines = "\n".join(f"{'✅' if c.ok else '❌'} {c.label}" for c in checks)
        status_label = QLabel(status_lines)
        status_label.setStyleSheet("color:#334155;")
        layout.addWidget(status_label)

        if not bundle["has_image"]:
            warn = QLabel("⚠️ این محصول روی سایت اصلاً تصویر ندارد — Alt تصویر تا وقتی عکسی آپلود نشود قابل ثبت نیست.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color:#b45309;")
            layout.addWidget(warn)

        if not suggestions:
            layout.addWidget(QLabel("✅ همه‌ی موارد سئوی قابل‌بررسی از قبل تکمیل است — چیزی برای پیشنهاد نیست."))
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            buttons.accepted.connect(dialog.accept)
            layout.addWidget(buttons)
            dialog.exec_()
            return

        layout.addWidget(QLabel("موارد ناقص — تیک بزنید تا پیشنهاد ساخته‌شده روی سایت ثبت شود:"))

        checkbox_map = {}
        edit_map = {}
        for field_key, suggested_text in suggestions.items():
            label_text = field_labels.get(field_key, field_key)
            if field_key == "alt_text" and not bundle["has_image"]:
                label_text += " (تصویر ندارد — غیرفعال)"
            if field_key == "description":
                label_text += " — می‌توانید همینجا بنویسید یا از جای دیگر پیست کنید (Ctrl+V)"
            cb = QCheckBox(label_text)
            enabled = field_key != "alt_text" or bundle["has_image"]
            cb.setEnabled(enabled)
            cb.setChecked(enabled)
            layout.addWidget(cb)
            edit = QTextEdit(suggested_text)
            edit.setMaximumHeight(160 if field_key == "description" else 50)
            edit.setPlaceholderText("توضیحات کامل محصول را اینجا بنویسید یا پیست کنید..." if field_key == "description" else "")
            layout.addWidget(edit)
            checkbox_map[field_key] = cb
            edit_map[field_key] = edit

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("📤 ارسال موارد تیک‌خورده به سایت")
        buttons.button(QDialogButtonBox.Cancel).setText("بستن")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        to_send = {
            key: edit_map[key].toPlainText().strip()
            for key, cb in checkbox_map.items()
            if cb.isChecked() and edit_map[key].toPlainText().strip()
        }
        if not to_send:
            return

        self._send_seo_fixes(sku, wc_id, to_send, bundle.get("image_id"), bundle.get("missing_alt_image_ids"))

    def _send_seo_fixes(self, sku, wc_id, to_send, image_id, extra_image_ids=None):
        config = load_secure_config(None) or {}

        def _worker():
            from sync_app.core.integrations.commerce_provider import is_prestashop

            if is_prestashop(config):
                from sync_app.core.seo_helper import apply_ps_seo_fixes

                apply_ps_seo_fixes(config, wc_id, to_send)
                return _fetch_ps_seo_bundle(config, wc_id)["current_score"]

            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            apply_seo_fixes(wcapi, config, wc_id, to_send, image_id, extra_image_ids)
            resp2 = wcapi.get(
                f"products/{int(wc_id)}",
                params={"_fields": "id,name,short_description,description,categories,images,meta_data"},
            )
            live2 = resp2.json()
            new_bundle = analyze_product_seo_live(live2)
            return new_bundle["current_score"]

        def _done(new_score):
            QMessageBox.information(
                self, "ارسال شد",
                f"موارد انتخاب‌شده روی سایت ثبت شد.\nامتیاز جدید (تأییدشده از سایت): {new_score}/100",
            )

        def _fail(msg):
            QMessageBox.critical(self, "خطا", f"ارسال سئوی محصول {sku} ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    # ------------------------------------------------------------------
    # Smart Publish: اجرای دستی روش پردازش تصویر روی تصویر محصول
    # ------------------------------------------------------------------
    def _open_pipeline_dialog(self, sku, item):
        from sync_app.core.smart_publish import (
            load_pipelines, load_watermark_settings, load_ai_studio_settings, run_pipeline,
            load_text_engrave_settings, load_qr_code_settings,
        )
        from sync_app.core.media_center import load_image_profiles
        from sync_app.core.integrations.commerce_provider import is_prestashop

        config = load_secure_config(None) or {}
        pipelines = load_pipelines(config)
        if not pipelines:
            QMessageBox.information(
                self, "روش پردازش تصویری تعریف نشده",
                "ابتدا در تب «⚙️ تنظیمات Smart Publish» حداقل یک روش پردازش تصویر بسازید.",
            )
            return

        manual_paths = self._existing_manual_image_paths(sku)
        if manual_paths:
            src = manual_paths[0]
        else:
            src, _ = QFileDialog.getOpenFileName(
                self, f"انتخاب تصویر محصول {sku}", "", "Images (*.jpg *.jpeg *.png *.bmp *.webp)"
            )
            if not src:
                return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"اجرای Smart Publish — {sku}")
        dialog.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"فایل: {os.path.basename(src)}"))
        layout.addWidget(QLabel("روش پردازش تصویر:"))
        combo = QComboBox()
        for name in pipelines:
            combo.addItem(name, name)
        layout.addWidget(combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("📤 اجرا و آپلود در سایت")
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        pipeline_name = combo.currentData()
        pipeline_data = pipelines.get(pipeline_name) or {}
        steps = pipeline_data.get("steps", [])
        profile_name = pipeline_data.get("profile", "")

        product_map = load_product_woo_map()
        wc_id = product_map.get(sku)
        if not wc_id:
            QMessageBox.information(
                self, "ابتدا همگام‌سازی کنید",
                f"محصول {sku} هنوز با فروشگاه همگام نشده — ابتدا سینک کنید.",
            )
            return

        profiles = load_image_profiles(config)
        profile = profiles.get(profile_name) if profile_name else None
        watermark = load_watermark_settings(config)
        ai_studio = load_ai_studio_settings(config)
        out_dir = os.path.dirname(src) or "."

        product_name = str(item.data(Qt.UserRole + 4) or "") if item else ""
        ps_mode = is_prestashop(config)
        if ps_mode:
            site_url = str(config.get("PS_URL") or "").strip().rstrip("/")
            product_url = f"{site_url}/index.php?id_product={int(wc_id)}&controller=product" if site_url else ""
        else:
            site_url = str(config.get("WC_URL") or "").strip().rstrip("/")
            product_url = f"{site_url}/?p={int(wc_id)}" if site_url else ""
        product_info = {"a_code": sku, "a_code_c": sku, "name": product_name, "product_url": product_url}

        def _worker():
            result = run_pipeline(
                src, steps, out_dir=out_dir, profile=profile, watermark=watermark,
                ai_studio=ai_studio, webp_quality=85,
                text_engrave=load_text_engrave_settings(config),
                qr_code=load_qr_code_settings(config),
                product_info=product_info,
            )
            if not result.ok:
                raise RuntimeError(result.error)

            with open(result.dst_path, "rb") as f:
                image_bytes = f.read()

            if ps_mode:
                from sync_app.core.ps_sync_helper import ps_upload_product_image

                try:
                    ps_upload_product_image(
                        config, int(wc_id), image_bytes, os.path.basename(result.dst_path),
                    )
                except Exception as exc:
                    raise RuntimeError(f"افزودن تصویر به گالری محصول ناموفق بود: {exc}")
                return result

            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            resp = wcapi.get(f"products/{int(wc_id)}", params={"_fields": "images"})
            data = resp.json()
            existing_images = data.get("images") or [] if isinstance(data, dict) else []
            new_images = [
                {"id": img.get("id")} for img in existing_images
                if isinstance(img, dict) and img.get("id")
            ]
            ok, media_id, _url, err = wp_upload_media_ex(
                config, image_bytes, os.path.basename(result.dst_path), fallback_stem=sku
            )
            if not ok:
                raise RuntimeError(f"آپلود رسانه ناموفق بود: {err}")
            new_images.append({"id": media_id})
            ok2, _resp2, err2 = update_wc_product_images(config, wc_id, new_images)
            if not ok2:
                raise RuntimeError(f"افزودن تصویر به گالری محصول ناموفق بود: {err2}")
            return result

        def _done(result):
            QMessageBox.information(
                self, "انجام شد",
                f"روش پردازش تصویر «{pipeline_name}» اجرا شد و به گالری محصول {sku} اضافه شد:\n"
                f"{os.path.basename(result.dst_path)}\n"
                f"حجم قبل: {result.size_before/1024:,.0f}KB → بعد: {result.size_after/1024:,.0f}KB",
            )

        def _fail(msg):
            QMessageBox.critical(self, "خطا", str(msg))

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    # ------------------------------------------------------------------
    # AI Content Studio: تولید متن/بنر تبلیغاتی برای محصول
    # ------------------------------------------------------------------
    def _open_content_studio_dialog(self, sku, item):
        from sync_app.core.content_studio_helper import (
            generate_instagram_caption, generate_telegram_text, generate_whatsapp_text,
            generate_sms_text, generate_hashtags, create_promo_image,
        )

        product = {
            "name": item.data(Qt.UserRole + 4) or sku,
            "price": item.data(Qt.UserRole + 11) or 0,
            "description": "",
        }

        # لینک کوتاه محصول — فقط اگه این محصول از قبل به فروشگاه لینک شده
        # باشه (چون بدون شناسه‌ی فروشگاه، لینکی برای ساختن نیست). از فرمت
        # کوتاه خودِ وردپرس (?p=ID) استفاده می‌شه، نه یه سرویس کوتاه‌کننده‌ی
        # بیرونی — چون نه وابستگی جدید لازم داره نه اتصال اینترنت اضافه.
        short_link = ""
        wc_id = None
        try:
            from sync_app.core.integrations.commerce_provider import is_prestashop

            product_map = load_product_woo_map()
            wc_id = product_map.get(sku)
            cfg = load_secure_config(None) or {}
            if is_prestashop(cfg):
                site_url = str(cfg.get("PS_URL") or "").strip().rstrip("/")
                if wc_id and site_url:
                    short_link = f"{site_url}/index.php?id_product={int(wc_id)}&controller=product"
            else:
                site_url = str(cfg.get("WC_URL") or "").strip().rstrip("/")
                if wc_id and site_url:
                    short_link = f"{site_url}/?p={int(wc_id)}"
        except Exception:
            short_link = ""

        dialog = QDialog(self)
        dialog.setWindowTitle(f"AI Content Studio — {sku}")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.resize(560, 620)
        outer = QVBoxLayout(dialog)

        sub_tabs = QTabWidget()
        sub_tabs.setLayoutDirection(Qt.RightToLeft)
        outer.addWidget(sub_tabs)

        # --- زیرتب متن‌ها ---
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        texts = {
            "کپشن اینستاگرام": generate_instagram_caption(product),
            "متن تلگرام": generate_telegram_text(product),
            "متن واتساپ": generate_whatsapp_text(product),
            "پیامک تبلیغاتی": generate_sms_text(product),
            "هشتگ‌ها": " ".join(generate_hashtags(product)),
        }
        if short_link:
            for key in ("کپشن اینستاگرام", "متن تلگرام", "متن واتساپ", "پیامک تبلیغاتی"):
                texts[key] = f"{texts[key]}\n\n🔗 {short_link}"
        for label, value in texts.items():
            text_layout.addWidget(QLabel(label + ":"))
            row_h = QHBoxLayout()
            edit = QTextEdit(value)
            edit.setMaximumHeight(70)
            row_h.addWidget(edit)
            copy_btn = QPushButton("📋 کپی")
            copy_btn.setFixedWidth(70)
            copy_btn.clicked.connect(lambda _=False, e=edit: QApplication.clipboard().setText(e.toPlainText()))
            row_h.addWidget(copy_btn)
            text_layout.addLayout(row_h)
        text_layout.addStretch()
        sub_tabs.addTab(text_tab, "📝 متن‌ها")

        # --- زیرتب بنر/پست/استوری ---
        banner_tab = QWidget()
        banner_layout = QVBoxLayout(banner_tab)
        banner_layout.addWidget(QLabel("برای هرکدوم، یه تصویر محصول انتخاب می‌کنید و فایل نهایی ساخته می‌شه:"))

        def _make_banner(kind, *, discount=None, seasonal=None):
            manual_paths = self._existing_manual_image_paths(sku)
            if manual_paths:
                src = manual_paths[0]
            else:
                src, _ = QFileDialog.getOpenFileName(
                    self, f"انتخاب تصویر محصول {sku}", "", "Images (*.jpg *.jpeg *.png *.webp)"
                )
                if not src:
                    return
            out_dir = os.path.dirname(src) or "."
            dst = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(src))[0]}_{kind}.jpg")
            result = create_promo_image(src, product, dst, kind=kind, discount_percent=discount, seasonal_text=seasonal)
            if result.ok:
                QMessageBox.information(self, "ساخته شد", f"فایل ذخیره شد:\n{result.dst_path}")
            else:
                QMessageBox.critical(self, "خطا", f"ساخت تصویر ناموفق بود:\n{result.error}")

        post_btn = QPushButton("🖼️ ساخت پست اینستاگرام (۱۰۸۰×۱۰۸۰)")
        post_btn.clicked.connect(lambda: _make_banner("instagram_post"))
        banner_layout.addWidget(post_btn)

        story_btn = QPushButton("📱 ساخت استوری اینستاگرام (۱۰۸۰×۱۹۲۰)")
        story_btn.clicked.connect(lambda: _make_banner("instagram_story"))
        banner_layout.addWidget(story_btn)

        discount_row = QHBoxLayout()
        discount_spin = QComboBox()
        for pct in (10, 15, 20, 30, 40, 50):
            discount_spin.addItem(f"{pct}٪", pct)
        discount_row.addWidget(QLabel("درصد تخفیف:"))
        discount_row.addWidget(discount_spin)
        discount_btn = QPushButton("🏷️ ساخت بنر تخفیف")
        discount_btn.clicked.connect(lambda: _make_banner("discount_banner", discount=discount_spin.currentData()))
        discount_row.addWidget(discount_btn)
        banner_layout.addLayout(discount_row)

        seasonal_row = QHBoxLayout()
        seasonal_input = QLineEdit()
        seasonal_input.setPlaceholderText("متن مناسبتی (مثلاً «ویژه شب یلدا»)")
        seasonal_row.addWidget(seasonal_input)
        seasonal_btn = QPushButton("🎉 ساخت بنر مناسبتی")
        seasonal_btn.clicked.connect(lambda: _make_banner("seasonal_banner", seasonal=seasonal_input.text().strip() or "پیشنهاد ویژه"))
        seasonal_row.addWidget(seasonal_btn)
        banner_layout.addLayout(seasonal_row)

        banner_layout.addStretch()
        sub_tabs.addTab(banner_tab, "🎨 بنر / پست / استوری")

        # --- زیرتب زمان‌بندیِ شبکه‌ی اجتماعی (تقویمِ محتوا) ---
        from sync_app.core.social_poster import PLATFORM_LABELS

        schedule_tab = QWidget()
        schedule_layout = QVBoxLayout(schedule_tab)

        schedule_platform_row = QHBoxLayout()
        schedule_platform_row.addWidget(QLabel("پلتفرم:"))
        schedule_platform_combo = QComboBox()
        for platform_key, platform_label in PLATFORM_LABELS.items():
            schedule_platform_combo.addItem(platform_label, platform_key)
        schedule_platform_row.addWidget(schedule_platform_combo)
        schedule_platform_row.addStretch()
        schedule_layout.addLayout(schedule_platform_row)

        schedule_recipient_row = QHBoxLayout()
        schedule_recipient_row.addWidget(QLabel("مقصدِ سفارشی (اختیاری):"))
        schedule_recipient_input = QLineEdit()
        schedule_recipient_input.setPlaceholderText("خالی = همون مقصدِ پیش‌فرضِ Settings؛ تلگرام: آیدیِ عددی یا @username؛ بله: فقط آیدیِ عددی")
        schedule_recipient_row.addWidget(schedule_recipient_input, 1)
        schedule_layout.addLayout(schedule_recipient_row)

        schedule_recipient_hint = QLabel(
            "برای ارسال به یک شخصِ خاص (نه کانالِ تنظیم‌شده)، اون شخص باید قبلاً یک پیام به باتِ شما "
            "فرستاده باشه (/start) — بات نمی‌تونه اول‌به‌اول به کسی که هنوز باهاش چت نکرده پیام بده. "
            "⚠️ بله (برخلافِ تلگرام) فقط آیدیِ عددی رو قبول می‌کنه، @username کار نمی‌کنه — با پیام‌دادنِ اون "
            "شخص به یک باتِ «نمایشِ آیدی» (مثلِ ble.ir/showchatdbot)، آیدیِ عددیِ خودش رو می‌گیره و به شما می‌ده."
        )
        schedule_recipient_hint.setWordWrap(True)
        schedule_recipient_hint.setStyleSheet("color:#64748b; font-size:10px;")
        schedule_layout.addWidget(schedule_recipient_hint)

        schedule_layout.addWidget(QLabel("متنِ پست:"))
        schedule_text_edit = QTextEdit(texts["متن تلگرام"])
        schedule_text_edit.setMinimumHeight(100)
        schedule_layout.addWidget(schedule_text_edit)

        schedule_image_row = QHBoxLayout()
        schedule_image_path = {"value": ""}
        manual_paths = self._existing_manual_image_paths(sku)
        if manual_paths:
            schedule_image_path["value"] = manual_paths[0]
        schedule_image_label = QLabel(schedule_image_path["value"] or "بدون تصویر (فقط متن ارسال می‌شود)")
        schedule_image_label.setStyleSheet("color:#64748b; font-size:10px;")
        schedule_image_label.setWordWrap(True)
        schedule_image_row.addWidget(schedule_image_label, 1)

        def _pick_schedule_image():
            path, _ = QFileDialog.getOpenFileName(
                self, f"انتخاب تصویر محصول {sku}", "", "Images (*.jpg *.jpeg *.png *.webp)"
            )
            if path:
                schedule_image_path["value"] = path
                schedule_image_label.setText(path)

        schedule_image_btn = QPushButton("📁 انتخاب تصویر")
        schedule_image_btn.clicked.connect(_pick_schedule_image)
        schedule_image_row.addWidget(schedule_image_btn)
        schedule_layout.addLayout(schedule_image_row)

        schedule_send_all_images_check = QCheckBox("همه‌ی عکس‌های این محصول از سایت هم ارسال شود (آلبوم)")
        schedule_send_all_images_check.setEnabled(False)
        schedule_layout.addWidget(schedule_send_all_images_check)

        # لینک/عکس(ها)/توضیحِ واقعیِ محصول از خودِ سایت (نه فرمتِ حدسی قدیمی) —
        # به‌صورتِ ناهمزمان دریافت می‌شه تا دیالوگ فوراً باز بشه
        schedule_fetched = {"permalink": "", "description": "", "image_urls": []}
        schedule_fetch_status = QLabel(
            "🔄 در حالِ دریافتِ لینک/عکس(ها)ی واقعیِ محصول از سایت..." if wc_id else ""
        )
        schedule_fetch_status.setStyleSheet("color:#2563eb; font-size:10px;")
        schedule_fetch_status.setWordWrap(True)
        schedule_layout.addWidget(schedule_fetch_status)

        def _fetch_real_content_worker():
            from sync_app.core.product_content_fetcher import (
                download_image_to_temp, fetch_product_content,
            )
            cfg_fetch = load_secure_config(None) or {}
            fetched = fetch_product_content(cfg_fetch, wc_id)
            image_local = ""
            if fetched.get("image_url"):
                image_local = download_image_to_temp(fetched["image_url"])
            return {
                "permalink": fetched.get("permalink") or "",
                "description": fetched.get("description") or "",
                "image_urls": fetched.get("image_urls") or [],
                "image_local": image_local,
            }

        def _apply_fetched_content(fetched):
            schedule_fetched["permalink"] = fetched.get("permalink") or ""
            schedule_fetched["description"] = fetched.get("description") or ""
            schedule_fetched["image_urls"] = fetched.get("image_urls") or []
            permalink = schedule_fetched["permalink"]
            image_local = fetched.get("image_local") or ""
            if schedule_template_combo.currentData():
                # یه قالب انتخاب شده — متن با دادهٔ واقعیِ تازه‌رسیده دوباره ساخته می‌شه
                _apply_template_to_text()
            elif permalink:
                current = schedule_text_edit.toPlainText()
                if short_link and short_link in current:
                    current = current.replace(short_link, permalink)
                elif current.strip():
                    current = f"{current}\n\n🔗 {permalink}"
                else:
                    current = f"🔗 {permalink}"
                schedule_text_edit.setPlainText(current)
            if image_local and not manual_paths:
                # فقط اگه کاربر از قبل عکسِ دستی انتخاب نکرده، عکسِ سایت جایگزین می‌شه
                schedule_image_path["value"] = image_local
                schedule_image_label.setText(f"(از روی سایت) {image_local}")
            n_images = len(schedule_fetched["image_urls"])
            if n_images > 1:
                schedule_send_all_images_check.setText(f"همه‌ی {n_images} عکسِ این محصول از سایت هم ارسال شود (آلبوم)")
                schedule_send_all_images_check.setEnabled(True)
            if permalink or image_local:
                schedule_fetch_status.setText("✅ لینک/عکس/توضیحِ واقعیِ محصول از سایت دریافت شد.")
            else:
                schedule_fetch_status.setText("⚠️ دریافتِ اطلاعاتِ سایت ناموفق بود؛ متن/عکسِ قبلی حفظ شد.")

        def _fetch_real_content_error(_msg):
            schedule_fetch_status.setText("⚠️ دریافتِ اطلاعاتِ سایت ناموفق بود؛ متن/عکسِ قبلی حفظ شد.")

        # --- قالبِ متنِ پست (اختیاری) — فیلدهای ثابت (نام/قیمت/توضیح/لینک/
        # تماس/شبکه‌های اجتماعی) + متنِ دلخواه؛ روی خودِ عکسِ محصول هیچ اثری
        # نداره، فقط متنِ پست رو می‌سازه ---
        from sync_app.core.post_template_renderer import render_post_text
        from sync_app.core.post_template_store import delete_template, find_template, list_templates, save_template

        schedule_template_row = QHBoxLayout()
        schedule_template_row.addWidget(QLabel("قالبِ متنِ پست (اختیاری):"))
        schedule_template_combo = QComboBox()

        def _reload_template_combo(select_id=""):
            schedule_template_combo.blockSignals(True)
            schedule_template_combo.clear()
            schedule_template_combo.addItem("بدونِ قالب (متنِ پیش‌فرض/دستی)", "")
            cfg_now = load_secure_config(None) or {}
            for tpl in list_templates(cfg_now):
                schedule_template_combo.addItem(tpl.get("title") or "بدون‌عنوان", tpl.get("id"))
            if select_id:
                found_idx = schedule_template_combo.findData(select_id)
                if found_idx >= 0:
                    schedule_template_combo.setCurrentIndex(found_idx)
            schedule_template_combo.blockSignals(False)

        _reload_template_combo()
        schedule_template_row.addWidget(schedule_template_combo, 1)

        def _apply_template_to_text(*_args):
            template_id = schedule_template_combo.currentData()
            if not template_id:
                return
            cfg_now = load_secure_config(None) or {}
            tpl = find_template(list_templates(cfg_now), template_id)
            if not tpl:
                return
            context = _build_template_context(product, schedule_fetched, cfg_now, short_link)
            # بله برخلافِ تلگرام، parse_mode=HTML رو رندر نمی‌کنه — پس فقط برای تلگرام از تگ‌های HTML استفاده می‌شه
            as_html = (schedule_platform_combo.currentData() or "telegram") == "telegram"
            schedule_text_edit.setPlainText(render_post_text(context, tpl, as_html=as_html))

        schedule_template_combo.currentIndexChanged.connect(_apply_template_to_text)
        schedule_platform_combo.currentIndexChanged.connect(_apply_template_to_text)

        def _design_new_template():
            from sync_app.core.post_template_designer_dialog import PostTemplateDesignerDialog

            designer = PostTemplateDesignerDialog(self)
            if designer.exec_() != QDialog.Accepted or not designer.saved_template:
                return
            import uuid as _uuid

            saved = designer.saved_template
            tid = saved.get("id") or _uuid.uuid4().hex[:12]
            cfg_now = load_secure_config(None) or {}
            cfg_new = save_template(cfg_now, saved.get("title") or "بدون‌عنوان", saved, template_id=tid)
            save_secure_config(cfg_new)
            _reload_template_combo(select_id=tid)
            _apply_template_to_text()
            QMessageBox.information(self, "قالبِ پست", "قالب ذخیره و برای این پست اعمال شد.")

        schedule_design_btn = QPushButton("🧩 قالبِ جدید")
        schedule_design_btn.clicked.connect(_design_new_template)
        schedule_template_row.addWidget(schedule_design_btn)

        def _edit_selected_template():
            template_id = schedule_template_combo.currentData()
            if not template_id:
                QMessageBox.information(self, "ویرایشِ قالب", "ابتدا یک قالب را از لیست انتخاب کنید.")
                return
            from sync_app.core.post_template_designer_dialog import PostTemplateDesignerDialog

            cfg_now = load_secure_config(None) or {}
            tpl = find_template(list_templates(cfg_now), template_id)
            if not tpl:
                return
            designer = PostTemplateDesignerDialog(self, template=tpl)
            if designer.exec_() != QDialog.Accepted or not designer.saved_template:
                return
            saved = designer.saved_template
            cfg_new = save_template(cfg_now, saved.get("title") or "بدون‌عنوان", saved, template_id=template_id)
            save_secure_config(cfg_new)
            _reload_template_combo(select_id=template_id)
            _apply_template_to_text()
            QMessageBox.information(self, "قالبِ پست", "قالب ویرایش و ذخیره شد.")

        schedule_edit_template_btn = QPushButton("✏️ ویرایش")
        schedule_edit_template_btn.clicked.connect(_edit_selected_template)
        schedule_template_row.addWidget(schedule_edit_template_btn)

        def _delete_selected_template():
            template_id = schedule_template_combo.currentData()
            if not template_id:
                QMessageBox.information(self, "حذفِ قالب", "ابتدا یک قالب را از لیست انتخاب کنید.")
                return
            title = schedule_template_combo.currentText()
            answer = QMessageBox.question(
                self, "حذفِ قالب", f"قالبِ «{title}» حذف شود؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            cfg_now = load_secure_config(None) or {}
            cfg_new = delete_template(cfg_now, template_id)
            save_secure_config(cfg_new)
            _reload_template_combo()

        schedule_delete_template_btn = QPushButton("🗑 حذف")
        schedule_delete_template_btn.clicked.connect(_delete_selected_template)
        schedule_template_row.addWidget(schedule_delete_template_btn)
        schedule_layout.addLayout(schedule_template_row)

        schedule_template_hint = QLabel(
            "با انتخابِ یک قالب، متنِ پست بر اساسِ فیلدهای انتخابی (نام/قیمت/توضیح/لینک/تماس/شبکه‌های اجتماعی/"
            "متنِ دلخواه) دوباره ساخته می‌شه — می‌تونید بعدش دستی هم ویرایشش کنید. عکسِ محصول همیشه دست‌نخورده می‌مونه."
        )
        schedule_template_hint.setWordWrap(True)
        schedule_template_hint.setStyleSheet("color:#64748b; font-size:10px;")
        schedule_layout.addWidget(schedule_template_hint)

        if wc_id:
            run_in_thread(_fetch_real_content_worker, on_complete=_apply_fetched_content, on_error=_fetch_real_content_error)

        schedule_layout.addWidget(QLabel("زمانِ ارسال (تاریخِ شمسی):"))
        from sync_app.core.jalali_date_utils import jalali_now, jalali_to_gregorian

        jy_now, jm_now, jd_now = jalali_now()
        date_row = QHBoxLayout()
        schedule_year_spin = QSpinBox()
        schedule_year_spin.setRange(1403, 1420)
        schedule_year_spin.setValue(jy_now)
        schedule_month_spin = QSpinBox()
        schedule_month_spin.setRange(1, 12)
        schedule_month_spin.setValue(jm_now)
        schedule_day_spin = QSpinBox()
        schedule_day_spin.setRange(1, 31)
        schedule_day_spin.setValue(jd_now)
        schedule_hour_spin = QSpinBox()
        schedule_hour_spin.setRange(0, 23)
        schedule_hour_spin.setValue(10)
        schedule_minute_spin = QSpinBox()
        schedule_minute_spin.setRange(0, 59)
        schedule_minute_spin.setSingleStep(5)
        schedule_minute_spin.setValue(0)
        for lbl, w in (
            ("سال", schedule_year_spin), ("ماه", schedule_month_spin), ("روز", schedule_day_spin),
            ("ساعت", schedule_hour_spin), ("دقیقه", schedule_minute_spin),
        ):
            date_row.addWidget(QLabel(lbl))
            date_row.addWidget(w)
        schedule_layout.addLayout(date_row)

        schedule_status_label = QLabel("")
        schedule_status_label.setStyleSheet("color:#166534; font-weight:700;")
        schedule_layout.addWidget(schedule_status_label)

        def _add_to_calendar():
            from datetime import datetime

            from sync_app.core.content_calendar_store import add_scheduled_post

            try:
                gy, gm, gd = jalali_to_gregorian(
                    schedule_year_spin.value(), schedule_month_spin.value(), schedule_day_spin.value()
                )
                scheduled_dt = datetime(gy, gm, gd, schedule_hour_spin.value(), schedule_minute_spin.value())
            except ValueError as exc:
                QMessageBox.critical(self, "خطا", f"تاریخِ واردشده معتبر نیست:\n{exc}")
                return

            # عکس(ها)ی خام — کاملاً دست‌نخورده (یا فقط عکسِ اصلی، یا آلبومِ همه‌ی عکس‌های سایط)
            if schedule_send_all_images_check.isChecked() and schedule_fetched["image_urls"]:
                from sync_app.core.product_content_fetcher import download_images_to_temp

                final_image_paths = download_images_to_temp(schedule_fetched["image_urls"])
                if not final_image_paths and schedule_image_path["value"]:
                    final_image_paths = [schedule_image_path["value"]]
            elif schedule_image_path["value"]:
                final_image_paths = [schedule_image_path["value"]]
            else:
                final_image_paths = []
            final_image_paths = final_image_paths[:10]

            add_scheduled_post(
                sku=sku,
                product_name=product.get("name") or sku,
                platform=schedule_platform_combo.currentData() or "telegram",
                text=schedule_text_edit.toPlainText(),
                scheduled_at=scheduled_dt.isoformat(timespec="seconds"),
                image_paths=final_image_paths,
                chat_id_override=schedule_recipient_input.text().strip(),
            )
            schedule_status_label.setText(
                f"✅ به تقویمِ محتوا اضافه شد — {schedule_year_spin.value()}/{schedule_month_spin.value():02d}/"
                f"{schedule_day_spin.value():02d} {schedule_hour_spin.value():02d}:{schedule_minute_spin.value():02d}"
            )

        add_to_calendar_btn = QPushButton("📅 افزودن به تقویم محتوا")
        add_to_calendar_btn.clicked.connect(_add_to_calendar)
        schedule_layout.addWidget(add_to_calendar_btn)

        schedule_hint = QLabel(
            "پست در زمانِ تعیین‌شده خودکار به کانال/گروهِ همون پلتفرمی که بالا انتخاب کردید "
            "(تنظیم‌شده در «تنظیمات → تلگرام» یا «تنظیمات → بله») ارسال می‌شود. "
            "برای مدیریتِ همه‌ی پست‌های زمان‌بندی‌شده، به زیرتبِ «📅 تقویم محتوا» (در دستیار هوشمند) بروید."
        )
        schedule_hint.setWordWrap(True)
        schedule_hint.setStyleSheet("color:#64748b; font-size:10px;")
        schedule_layout.addWidget(schedule_hint)
        schedule_layout.addStretch()
        sub_tabs.addTab(schedule_tab, "📅 زمان‌بندی شبکه اجتماعی")

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        outer.addWidget(buttons)

        dialog.exec_()

    # ------------------------------------------------------------------
    # زمان‌بندیِ گروهی: انتخابِ چند محصول (با چک‌باکس) و افزودنِ یک پستِ
    # جداگانه به تقویمِ محتوا برای هرکدام، همه در یک زمانِ مشخص.
    # ------------------------------------------------------------------
    def _open_batch_schedule_dialog(self):
        from datetime import datetime

        from sync_app.core.content_studio_helper import generate_telegram_text
        from sync_app.core.jalali_date_utils import jalali_now, jalali_to_gregorian
        from sync_app.core.post_template_store import find_template, list_templates
        from sync_app.core.social_poster import PLATFORM_LABELS

        selected = []
        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            sku = item.data(Qt.UserRole)
            if not sku:
                continue
            row_widget = self.product_list.itemWidget(item)
            if not isinstance(row_widget, ProductRowWidget):
                continue
            if not row_widget.checkbox.isChecked():
                continue
            selected.append({
                "sku": sku,
                "name": item.data(Qt.UserRole + 4) or sku,
                "price": item.data(Qt.UserRole + 11) or 0,
            })

        if not selected:
            QMessageBox.information(
                self, "زمان‌بندیِ گروهی",
                "ابتدا با تیک‌زدنِ چک‌باکسِ کنارِ محصولات، چند محصول را انتخاب کنید.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"📅 زمان‌بندیِ گروهیِ پست — {len(selected)} محصول")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.resize(480, 440)
        v = QVBoxLayout(dialog)

        v.addWidget(QLabel(
            f"{len(selected)} محصولِ انتخاب‌شده — برای هرکدام یک پستِ جداگانه (با متن/عکسِ اختصاصی) ساخته می‌شود:"
        ))
        names_preview = "، ".join(str(p["name"]) for p in selected[:6])
        if len(selected) > 6:
            names_preview += f" و {len(selected) - 6} موردِ دیگر"
        preview_label = QLabel(names_preview)
        preview_label.setWordWrap(True)
        preview_label.setStyleSheet("color:#64748b; font-size:10px;")
        v.addWidget(preview_label)

        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("پلتفرم:"))
        platform_combo = QComboBox()
        for key, label in PLATFORM_LABELS.items():
            platform_combo.addItem(label, key)
        platform_row.addWidget(platform_combo)
        platform_row.addStretch()
        v.addLayout(platform_row)

        recipient_row = QHBoxLayout()
        recipient_row.addWidget(QLabel("مقصدِ سفارشی (اختیاری):"))
        recipient_input = QLineEdit()
        recipient_input.setPlaceholderText("خالی = مقصدِ پیش‌فرضِ Settings؛ تلگرام: آیدیِ عددی یا @username؛ بله: فقط آیدیِ عددی (برای همه‌ی این پست‌ها)")
        recipient_row.addWidget(recipient_input, 1)
        v.addLayout(recipient_row)

        recipient_hint = QLabel(
            "⚠️ بله (برخلافِ تلگرام) فقط آیدیِ عددی رو قبول می‌کنه؛ برای ارسال به شخص، اون شخص باید قبلاً به بات پیام داده باشه."
        )
        recipient_hint.setWordWrap(True)
        recipient_hint.setStyleSheet("color:#64748b; font-size:10px;")
        v.addWidget(recipient_hint)

        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("قالبِ متنِ پست (اختیاری):"))
        template_combo = QComboBox()
        template_combo.addItem("بدونِ قالب (متنِ پیش‌فرض)", "")
        cfg_now = load_secure_config(None) or {}
        for tpl in list_templates(cfg_now):
            template_combo.addItem(tpl.get("title") or "بدون‌عنوان", tpl.get("id"))
        template_row.addWidget(template_combo, 1)
        v.addLayout(template_row)

        template_hint = QLabel(
            "با انتخابِ یک قالب، متنِ هرکدوم از پست‌ها بر اساسِ فیلدهای انتخابی (نام/قیمت/توضیح/لینک/تماس/"
            "شبکه‌های اجتماعی/متنِ دلخواه) و دادهٔ همون محصول ساخته می‌شه. عکسِ محصول همیشه دست‌نخورده می‌مونه."
        )
        template_hint.setStyleSheet("color:#64748b; font-size:10px;")
        template_hint.setWordWrap(True)
        v.addWidget(template_hint)

        send_all_images_check = QCheckBox("همه‌ی عکس‌های هر محصول از سایت هم ارسال شود (آلبوم)")
        v.addWidget(send_all_images_check)

        v.addWidget(QLabel("زمانِ ارسالِ همه (تاریخِ شمسی) — یکسان برای همه‌ی پست‌ها:"))
        jy_now, jm_now, jd_now = jalali_now()
        date_row = QHBoxLayout()
        year_spin = QSpinBox()
        year_spin.setRange(1403, 1420)
        year_spin.setValue(jy_now)
        month_spin = QSpinBox()
        month_spin.setRange(1, 12)
        month_spin.setValue(jm_now)
        day_spin = QSpinBox()
        day_spin.setRange(1, 31)
        day_spin.setValue(jd_now)
        hour_spin = QSpinBox()
        hour_spin.setRange(0, 23)
        hour_spin.setValue(10)
        minute_spin = QSpinBox()
        minute_spin.setRange(0, 59)
        minute_spin.setSingleStep(5)
        minute_spin.setValue(0)
        for lbl, w in (
            ("سال", year_spin), ("ماه", month_spin), ("روز", day_spin),
            ("ساعت", hour_spin), ("دقیقه", minute_spin),
        ):
            date_row.addWidget(QLabel(lbl))
            date_row.addWidget(w)
        v.addLayout(date_row)

        status_label = QLabel("")
        status_label.setStyleSheet("color:#166534; font-weight:700;")
        status_label.setWordWrap(True)
        v.addWidget(status_label)

        confirm_btn = QPushButton(f"📅 افزودنِ {len(selected)} پستِ جداگانه به تقویم")
        v.addWidget(confirm_btn)

        close_btn = QPushButton("انصراف")
        close_btn.clicked.connect(dialog.reject)
        v.addWidget(close_btn)

        def _run_batch():
            try:
                gy, gm, gd = jalali_to_gregorian(year_spin.value(), month_spin.value(), day_spin.value())
                scheduled_dt = datetime(gy, gm, gd, hour_spin.value(), minute_spin.value())
            except ValueError as exc:
                QMessageBox.critical(dialog, "خطا", f"تاریخِ واردشده معتبر نیست:\n{exc}")
                return

            platform = platform_combo.currentData() or "telegram"
            template_id = template_combo.currentData()
            confirm_btn.setEnabled(False)
            close_btn.setEnabled(False)
            status_label.setText("🔄 در حالِ آماده‌سازیِ پست‌ها (دریافتِ لینک/عکسِ هر محصول از سایت)...")

            send_all_images = send_all_images_check.isChecked()
            chat_id_override = recipient_input.text().strip()

            def _worker():
                from sync_app.core.content_calendar_store import add_scheduled_post
                from sync_app.core.post_template_renderer import render_post_text
                from sync_app.core.product_content_fetcher import (
                    download_image_to_temp, download_images_to_temp, fetch_product_content,
                )

                product_map = load_product_woo_map()
                cfg = load_secure_config(None) or {}
                tpl = find_template(list_templates(cfg), template_id) if template_id else None
                done = 0
                failed = []
                for p in selected:
                    sku = p["sku"]
                    product_data = {"name": p["name"], "price": p["price"], "description": ""}
                    fetched = {"permalink": "", "description": "", "image_urls": []}
                    raw_photos = []
                    wc_id = product_map.get(sku)
                    if wc_id:
                        try:
                            fetched = fetch_product_content(cfg, wc_id)
                            if send_all_images and fetched.get("image_urls"):
                                raw_photos = download_images_to_temp(fetched["image_urls"])
                            elif fetched.get("image_url"):
                                single = download_image_to_temp(fetched["image_url"])
                                raw_photos = [single] if single else []
                        except Exception:
                            pass

                    if tpl:
                        context = _build_template_context(product_data, fetched, cfg)
                        # بله parse_mode=HTML رو رندر نمی‌کنه — فقط برای تلگرام از تگ‌های HTML استفاده می‌شه
                        text = render_post_text(context, tpl, as_html=(platform == "telegram"))
                    else:
                        text = generate_telegram_text(product_data)
                        permalink = fetched.get("permalink") or ""
                        if permalink:
                            text = f"{text}\n\n🔗 {permalink}"

                    image_paths = raw_photos[:10]
                    try:
                        add_scheduled_post(
                            sku=sku,
                            product_name=p["name"],
                            platform=platform,
                            text=text,
                            scheduled_at=scheduled_dt.isoformat(timespec="seconds"),
                            image_paths=image_paths,
                            chat_id_override=chat_id_override,
                        )
                        done += 1
                    except Exception as exc:
                        failed.append(f"{sku}: {exc}")
                return {"done": done, "failed": failed}

            def _on_done(result):
                msg = f"✅ {result['done']} پست به تقویمِ محتوا اضافه شد."
                if result["failed"]:
                    msg += f"\n⚠️ {len(result['failed'])} موردِ ناموفق: " + "، ".join(result["failed"][:5])
                status_label.setText(msg)
                QMessageBox.information(dialog, "زمان‌بندیِ گروهی", msg)
                dialog.accept()

            def _on_error(err_msg):
                confirm_btn.setEnabled(True)
                close_btn.setEnabled(True)
                status_label.setText(f"❌ خطا: {err_msg}")

            run_in_thread(_worker, on_complete=_on_done, on_error=_on_error)

        confirm_btn.clicked.connect(_run_batch)

        dialog.exec_()

    # ------------------------------------------------------------------
    # Smart Automation: آماده‌سازی هوشمند محصول با یک کلیک
    # ------------------------------------------------------------------
    def _run_smart_prep(self, sku, item):
        """
        وضعیت واقعی سئوی محصول را از سایت می‌خواند، هر چیزی که ناقص باشد
        (Alt/توضیح کوتاه/متا دیسکریپشن/عنوان سئو/کلمات کلیدی) را با متن
        پیشنهادی قالب‌محور تولید و به‌طور خودکار روی سایت ثبت می‌کند —
        فقط با یک تأیید کلی، نه تیک زدن تک‌تک مثل دکمه‌ی 📝.
        """
        product_map = load_product_woo_map()
        wc_id = product_map.get(sku)
        if not wc_id:
            QMessageBox.information(
                self, "ابتدا همگام‌سازی کنید",
                f"محصول {sku} هنوز با فروشگاه همگام نشده — ابتدا سینک کنید.",
            )
            return

        config = load_secure_config(None) or {}
        fallback_name = item.data(Qt.UserRole + 4)

        def _worker():
            from sync_app.core.integrations.commerce_provider import is_prestashop

            if is_prestashop(config):
                return _fetch_ps_seo_bundle(config, wc_id)
            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            resp = wcapi.get(
                f"products/{int(wc_id)}",
                params={"_fields": "id,name,short_description,description,categories,images,meta_data"},
            )
            live = resp.json()
            if not isinstance(live, dict) or not live.get("id"):
                raise RuntimeError(f"دریافت اطلاعات زنده‌ی محصول ناموفق بود: {live}")
            return analyze_product_seo_live(live, fallback_name=fallback_name, fallback_desc="")

        def _done(bundle):
            self._confirm_and_apply_smart_prep(sku, wc_id, bundle)

        def _fail(msg):
            QMessageBox.critical(self, "خطا", f"بررسی وضعیت محصول {sku} ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _confirm_and_apply_smart_prep(self, sku, wc_id, bundle):
        field_labels = {
            "short_description": "توضیح کوتاه",
            "alt_text": "Alt تصویر",
            "meta_description": "متا دیسکریپشن",
            "seo_title": "عنوان سئو",
            "meta_keywords": "کلمات کلیدی",
        }
        suggestions = dict(bundle["suggestions"])
        if not bundle["has_image"]:
            suggestions.pop("alt_text", None)
        # توضیحات بلند رو از آماده‌سازی خودکار حذف می‌کنیم — چون قابل تولید
        # خودکار نیست (باید انسان بنویسه)؛ برای این کار از دکمه‌ی 📝 (سئو)
        # روی همین ردیف استفاده کنید که کادر نوشتن/پیست داره.
        had_description = "description" in suggestions
        suggestions.pop("description", None)

        if not suggestions:
            msg = f"محصول {sku} از نظر سئو کامل است (امتیاز {bundle['current_score']}/100) — چیزی برای رفع نیست."
            if had_description:
                msg += "\n(توضیحات کامل محصول ناقص است، ولی چون قابل تولید خودکار نیست، از دکمه‌ی 📝 سئو برای نوشتن آن استفاده کنید.)"
            QMessageBox.information(self, "همه‌چیز مرتب است", msg)
            return

        field_list = "\n".join(f"• {field_labels.get(k, k)}" for k in suggestions)
        confirm = QMessageBox.question(
            self, "تأیید آماده‌سازی هوشمند",
            f"امتیاز فعلی: {bundle['current_score']}/100\n\n"
            f"این موارد به‌طور خودکار تولید و روی سایت ثبت می‌شوند:\n{field_list}\n\n"
            "ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self._send_seo_fixes(sku, wc_id, suggestions, bundle.get("image_id"))

    def clear_tab_logs(self):
        removed = clear_filtered_logs(["محصول", "products", "sync_fullproduct", "A_Code"])
        self.refresh_logs()
        QMessageBox.information(self, "انجام شد", f"{removed} خط لاگ مربوط به تب محصولات پاک شد.")

    def _start_send_products(self):
        """همگام‌سازی محصولات در پس‌زمینه"""
        self.config = load_secure_config(None) or {}
        if not ensure_connectivity(self, need_sql=True, need_wc=True, live=False):
            return

        # اگه فیلتر (جستجو یا وضعیت لینک) فعاله، آیتم‌های تیک‌خورده‌ای که الان
        # به‌خاطر فیلتر مخفی‌ان نباید ارسال بشن — طبق انتظار کاربر. این کار
        # موقتیه: فقط برای همین یک بار ارسال، ترجیحات واقعی تیک کاربر برای
        # دفعات بعد دست‌نخورده می‌مونه.
        # محافظ مهم: اگه تنظیمات فعلی مشکوک به خالی/ناقص بودن باشه (کمتر از
        # ۵ کلید — یعنی احتمالاً یه خطای لحظه‌ای خواندن بوده، نه تنظیمات واقعی)
        # اصلاً وارد بازی محدودسازی موقت نشو — چون بعداً ذخیره‌ش می‌تونه کل
        # تنظیمات واقعی رو پاک کنه.
        self._temp_extra_disabled = set()
        if isinstance(self.config, dict) and len(self.config) >= 5:
            self._temp_extra_disabled = self._hidden_checked_skus()
            if self._temp_extra_disabled:
                original_disabled = set(self.config.get("DISABLED_PRODUCT_SKUS", []) or [])
                self.config["DISABLED_PRODUCT_SKUS"] = sorted(original_disabled | self._temp_extra_disabled)
                save_secure_config(self.config)

        previews = build_products_sync_preview(self.config)
        if not previews:
            self._restore_temp_disabled_skus()
            QMessageBox.information(
                self,
                "محصولی نیست",
                "محصولی برای ارسال یافت نشد.\n"
                "گروه انتخاب‌شده در دسته‌بندی یا تیک محصولات را بررسی کنید.",
            )
            return
        if not ProductSyncPreviewDialog.ask(self, previews, self.config):
            self._restore_temp_disabled_skus()
            return
        if not confirm_live_site_backup(self, "ارسال محصولات به فروشگاه"):
            self._restore_temp_disabled_skus()
            return

        if not run_background_sync(
            self,
            sync_fullproduct.main,
            on_success=self._products_sync_done,
            on_error=self._products_sync_error,
            need_sql=True,
            need_wc=True,
        ):
            self._restore_temp_disabled_skus()
            thread = getattr(self, "_peecha_bg_sync_thread", None)
            if thread is not None and thread.isRunning():
                QMessageBox.information(self, "در حال اجرا", "همگام‌سازی دیگری در جریان است.")
            return
        self._action_ops.begin("sync")
        self._sync_started_at = time.monotonic()
        self.sync_progress.setValue(2)
        self.sync_progress.setVisible(True)
        self.sync_detail_label.setText("آماده‌سازی ارسال...")
        self.sync_detail_label.setVisible(True)
        self._sync_live_timer.start()
        self._set_products_status("loading", "⏳ در حال ارسال محصولات به فروشگاه...")

    def _hidden_checked_skus(self) -> set:
        """SKUهایی که تیک‌خورده‌ان ولی الان (به‌خاطر فیلتر) روی صفحه مخفی‌ان."""
        hidden_checked = set()
        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            if not item.isHidden():
                continue
            sku = item.data(Qt.UserRole)
            if not sku:
                continue
            row_widget = self.product_list.itemWidget(item)
            if row_widget is not None and row_widget.checkbox.isChecked():
                hidden_checked.add(sku)
        return hidden_checked

    def _restore_temp_disabled_skus(self):
        """ترجیحات واقعی تیک کاربر رو برمی‌گردونه (بعد از یک ارسال محدودشده‌ی موقت به فیلتر)."""
        extra = getattr(self, "_temp_extra_disabled", None)
        if not extra:
            return
        cfg = load_secure_config(None) or {}
        if not isinstance(cfg, dict) or len(cfg) < 5:
            # تنظیمات مشکوک به خالی/ناقص — دست‌کاریش نکن، امن‌تره
            self._temp_extra_disabled = None
            return
        current_disabled = set(cfg.get("DISABLED_PRODUCT_SKUS", []) or [])
        cfg["DISABLED_PRODUCT_SKUS"] = sorted(current_disabled - extra)
        save_secure_config(cfg)
        self._temp_extra_disabled = None

    def _stop_products_sync(self):
        if self._action_ops.active != "sync":
            return
        if cancel_background_sync(self):
            self._action_ops.set_stopping("sync")
            self._set_products_status("warning", "⏹ در حال توقف ارسال محصولات...")

    def _products_sync_done(self, result=None):
        if self._action_ops.active == "sync":
            self._action_ops.end()
        self._restore_temp_disabled_skus()
        self._sync_live_timer.stop()
        self.sync_progress.setValue(100)
        self.sync_progress.setVisible(False)
        self.sync_detail_label.setVisible(False)
        self.refresh_logs()
        ok_count = (result or {}).get("ok", 0) if isinstance(result, dict) else 0
        if ok_count > 0:
            self._set_products_status("success", f"✅ {ok_count} محصول با موفقیت به فروشگاه ارسال شد.")
            QMessageBox.information(
                self,
                "موفق",
                f"{ok_count} محصول با موفقیت به فروشگاه ارسال شد.",
            )
        else:
            self._set_products_status(
                "info",
                "ℹ️ محصولی برای ارسال یافت نشد — گروه یا تیک محصولات را بررسی کنید.",
            )
            QMessageBox.information(
                self,
                "نتیجه",
                "محصولی برای همگام‌سازی یافت نشد.\n"
                "گروه انتخاب‌شده در دسته‌بندی یا تیک فعال محصولات را بررسی کنید.",
            )

    def _products_sync_error(self, message):
        if self._action_ops.active == "sync":
            self._action_ops.end()
        self._restore_temp_disabled_skus()
        self._sync_live_timer.stop()
        self.sync_progress.setVisible(False)
        self.sync_detail_label.setVisible(False)
        self.refresh_logs()
        if "متوقف" in (message or ""):
            self._set_products_status("info", "⏹ ارسال محصولات متوقف شد.")
            QMessageBox.information(self, "توقف", "ارسال محصولات متوقف شد.")
            return
        short = str(message).split("\n")[0][:160]
        self._set_products_status("error", f"❌ {short}")
        QMessageBox.critical(self, "خطا در همگام‌سازی", str(message))

    # ─── ارسال تصاویر به فروشگاه ──────────────────────────────────────────────

    def _get_wp_base_url(self):
        """استخراج آدرس پایه وردپرس از WC_URL تنظیمات"""
        wc_url = (self.config or {}).get("WC_URL", "").rstrip("/")
        return re.sub(r'/wp-json.*', '', wc_url, flags=re.IGNORECASE) or wc_url

    def _on_upload_images_clicked(self):
        self._action_ops.handle_click("images", self._send_selected_images_to_woo)

    def _end_prod_images_ui(self):
        if self._action_ops.active == "images":
            self._action_ops.end()

    def _stop_product_images_upload(self):
        if self._action_ops.active != "images":
            return
        if cancel_background_sync(self):
            self._action_ops.set_stopping("images")
            self._set_products_status("warning", "⏹ در حال توقف ارسال تصاویر...")
            log.info("⏹ درخواست توقف ارسال تصاویر محصولات ثبت شد.")
        else:
            QMessageBox.information(self, "توقف", "عملیات فعالی برای توقف یافت نشد.")

    def _image_paths_for_product(self, sku, item) -> list[str]:
        """مسیر تصاویر آماده ارسال — فقط فایل‌های موجود."""
        return self._existing_image_paths_for_product(sku, item)

    def _collect_products_for_image_upload(self):
        """محصولات تیک‌خورده با حداقل یک تصویر واقعی."""
        ready = []
        skipped_no_image = []
        pruned = 0

        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            sku = item.data(Qt.UserRole)
            if not sku:
                continue
            row_widget = self.product_list.itemWidget(item)
            if not isinstance(row_widget, ProductRowWidget):
                continue
            if not row_widget.checkbox.isChecked():
                continue
            if self._prune_stale_manual_images(sku, item):
                pruned += 1
            paths = self._existing_image_paths_for_product(sku, item)
            if paths:
                ready.append((sku, paths))
            else:
                skipped_no_image.append(str(sku))

        return ready, skipped_no_image, pruned

    def _send_selected_images_to_woo(self):
        """ارسال تصاویر محصولات انتخابی به فروشگاه (دستی یا از ERP)"""
        to_process, skipped, pruned = self._collect_products_for_image_upload()
        selected_checked = sum(
            1
            for i in range(self.product_list.count())
            if isinstance(self.product_list.itemWidget(self.product_list.item(i)), ProductRowWidget)
            and self.product_list.itemWidget(self.product_list.item(i)).checkbox.isChecked()
        )

        if not to_process:
            parts = [
                "هیچ محصول تیک‌خورده‌ای با تصویر آماده برای ارسال یافت نشد.",
                f"تصویر دستی بگذارید یا Picture/PicturePath در {self._erp_label()} را بررسی کنید.",
            ]
            if skipped:
                parts.append(f"\n{len(skipped)} محصول تیک‌خورده بدون فایل تصویر بود.")
            if pruned:
                parts.append(f"\n{pruned} محصول نگاشت قدیمی بدون فایل پاک‌سازی شد.")
            QMessageBox.information(self, "توجه", "\n".join(parts))
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("تصاویر موجود در فروشگاه")
        intro = (
            f"از {selected_checked} محصول تیک‌خورده، {len(to_process)} محصول تصویر واقعی دارند.\n\n"
            "اگر محصولی از قبل در فروشگاه تصویر داشته باشد چه کاری انجام شود؟"
        )
        if skipped:
            intro += f"\n\n({len(skipped)} محصول بدون تصویر نادیده گرفته می‌شود)"
        msg_box.setText(intro)
        btn_replace = msg_box.addButton("جایگزین کن", QMessageBox.YesRole)
        msg_box.addButton("به گالری اضافه کن", QMessageBox.NoRole)
        btn_cancel = msg_box.addButton("لغو", QMessageBox.RejectRole)
        msg_box.setDefaultButton(btn_replace)
        msg_box.exec_()

        clicked = msg_box.clickedButton()
        if clicked is btn_cancel:
            return
        replace_mode = (clicked is btn_replace)

        def job():
            self._do_send_images_to_woo(to_process, replace_mode)

        if not run_background_sync(
            self, job,
            on_success=self._images_upload_done,
            on_error=self._images_upload_error,
            need_sql=False,
            need_wc=True,
            wait_on_disconnect=True,
        ):
            thread = getattr(self, "_peecha_bg_sync_thread", None)
            if thread is not None and thread.isRunning():
                QMessageBox.information(self, "در حال اجرا", "یک عملیات دیگر در حال اجرا است.")
            return
        self._action_ops.begin("images")
        self._set_products_status("loading", "⏳ در حال ارسال تصاویر...")

    def _do_send_images_to_ps(self, to_process, replace_mode, cfg):
        """معادل _do_send_images_to_woo برای پرستاشاپ — بدون کتابخانه‌ی رسانه‌ی
        وردپرس؛ هر تصویر مستقیم با ps_upload_product_image به گالری محصول
        اضافه می‌شه. برای حالت «جایگزین کن»، اول تصاویر فعلی گالری حذف می‌شن."""
        from sync_app.core.ps_sync_helper import (
            ps_delete_product_image, ps_get_product_image_ids, ps_upload_product_image,
        )
        from sync_app.core.smart_publish import (
            AUTO_RUN_KEY, AUTO_PIPELINE_KEY, load_pipelines, load_watermark_settings,
            load_ai_studio_settings, run_pipeline, load_text_engrave_settings, load_qr_code_settings,
        )
        from sync_app.core.media_center import load_image_profiles

        product_map = load_product_woo_map()
        success_count = 0
        fail_count = 0
        log.info(f"📷 شروع ارسال تصاویر {len(to_process)} محصول به پرستاشاپ — فقط فایل‌های موجود روی دیسک")

        auto_run = bool(cfg.get(AUTO_RUN_KEY, False))
        auto_pipeline_name = cfg.get(AUTO_PIPELINE_KEY)
        pipelines = load_pipelines(cfg) if auto_run else {}
        auto_pipeline = pipelines.get(auto_pipeline_name) if auto_pipeline_name else None
        if auto_run and auto_pipeline:
            profiles = load_image_profiles(cfg)
            pipeline_watermark = load_watermark_settings(cfg)
            pipeline_ai_studio = load_ai_studio_settings(cfg)
            pipeline_text_engrave = load_text_engrave_settings(cfg)
            pipeline_qr_code = load_qr_code_settings(cfg)
            pipeline_steps = auto_pipeline.get("steps") or []
            pipeline_profile = profiles.get(auto_pipeline.get("profile")) if auto_pipeline.get("profile") else None
        else:
            pipeline_steps = []

        def _apply_pipeline_if_needed(sku: str, abs_path: str, pid: int) -> str:
            if not (auto_run and auto_pipeline and pipeline_steps):
                return abs_path
            try:
                site_url = str(cfg.get("PS_URL") or "").strip().rstrip("/")
                product_url = f"{site_url}/index.php?id_product={int(pid)}&controller=product" if site_url else ""
                out_dir = os.path.join(os.path.dirname(abs_path), "_pipeline_out")
                os.makedirs(out_dir, exist_ok=True)
                result = run_pipeline(
                    abs_path, pipeline_steps, out_dir=out_dir, profile=pipeline_profile,
                    watermark=pipeline_watermark, ai_studio=pipeline_ai_studio,
                    text_engrave=pipeline_text_engrave, qr_code=pipeline_qr_code,
                    product_info={"a_code": sku, "a_code_c": sku, "name": sku, "product_url": product_url},
                )
                if result.ok and result.dst_path and os.path.isfile(result.dst_path):
                    return result.dst_path
            except Exception as exc:
                log.warning(f"⚠️ روش پردازش تصویر رو {sku} اجرا نشد، فایل اصلی ارسال می‌شه: {exc}")
            return abs_path

        for sku, paths in to_process:
            try:
                pid = product_map.get(sku)
                if not pid:
                    log.warning(f"⚠️ محصول {sku} در پرستاشاپ لینک نشده — رد شد.")
                    fail_count += 1
                    continue
                pid = int(pid)

                if replace_mode:
                    try:
                        for existing_id in ps_get_product_image_ids(cfg, pid):
                            ps_delete_product_image(cfg, pid, existing_id)
                    except Exception as exc:
                        log.warning(f"⚠️ حذف تصاویر فعلی محصول {sku} ناموفق بود: {exc}")

                uploaded = 0
                for rel_or_abs in paths:
                    abs_path = self._product_image_abs_path(rel_or_abs)
                    if not abs_path:
                        log.warning(f"⚠️ فایل تصویر پیدا نشد — {sku}: {rel_or_abs}")
                        continue
                    abs_path = _apply_pipeline_if_needed(sku, abs_path, pid)
                    filename = os.path.basename(abs_path)
                    try:
                        with open(abs_path, "rb") as f:
                            img_data = f.read()
                        ps_upload_product_image(cfg, pid, img_data, filename)
                        log.info(f"✅ تصویر {filename} برای {sku} آپلود شد.")
                        uploaded += 1
                    except Exception as exc:
                        log.error(f"❌ خطا در آپلود {filename} برای {sku}: {exc}")
                        self._last_img_upload_detail = str(exc)

                if not uploaded:
                    log.warning(f"⚠️ هیچ تصویری برای {sku} با موفقیت آپلود نشد.")
                    fail_count += 1
                    continue

                log.info(f"✅ {uploaded} تصویر برای محصول {sku} (ID:{pid}) روی پرستاشاپ تنظیم شد.")
                success_count += 1

            except Exception as exc:
                from sync_app.core.sync_cancel import SyncCancelled
                if isinstance(exc, SyncCancelled):
                    raise
                log.error(f"❌ خطای کلی در پردازش {sku}: {exc}")
                fail_count += 1

        if fail_count == 0:
            log.info(f"✅ ارسال تصاویر به پایان رسید. {success_count} محصول موفق.")
        else:
            log.warning(f"⚠️ ارسال تصاویر تمام شد. موفق: {success_count} | ناموفق: {fail_count}")
        self._last_img_upload_result = (success_count, fail_count)

    def _do_send_images_to_woo(self, to_process, replace_mode):
        """اجرا در thread پس‌زمینه — آپلود فایل‌ها به WordPress Media و بروزرسانی محصول"""
        cfg = ensure_wc_sites(load_secure_config(None) or {})
        self._last_img_upload_detail = ""

        from sync_app.core.integrations.commerce_provider import is_prestashop

        if is_prestashop(cfg):
            self._do_send_images_to_ps(to_process, replace_mode, cfg)
            return

        timeout = int(cfg.get("WC_TIMEOUT", 60) or 60)

        wp_user, wp_pwd = (cfg.get("WP_USERNAME") or ""), (cfg.get("WP_APP_PASSWORD") or "")
        if wp_user and wp_pwd:
            ok_auth, auth_err = verify_wp_media_credentials(cfg)
            if not ok_auth:
                log.error(f"❌ بررسی Application Password: {auth_err}")
                self._last_img_upload_detail = auth_err
                self._last_img_upload_result = (0, len(to_process))
                return
            log.info("✅ Application Password برای آپلود تصویر تأیید شد.")

        success_count = 0
        fail_count = 0
        log.info(f"📷 شروع ارسال تصاویر {len(to_process)} محصول — فقط فایل‌های موجود روی دیسک")

        # اگه کاربر یه «روش پردازش تصویر» (پایپ‌لاین) رو به‌عنوان پیش‌فرضِ
        # اجرای خودکار انتخاب کرده، همون‌جوری که موقع آپلود دستی اعمال
        # می‌شه، اینجا هم (برای تصاویرِ ERP که مستقیم کپی شدن) اعمالش کنیم
        # — تا فرقی نکنه تصویر از کجا اومده، همه از یه مسیر پردازش رد بشن.
        from sync_app.core.smart_publish import (
            AUTO_RUN_KEY, AUTO_PIPELINE_KEY, load_pipelines, load_watermark_settings,
            load_ai_studio_settings, run_pipeline, load_text_engrave_settings, load_qr_code_settings,
        )
        from sync_app.core.media_center import load_image_profiles

        auto_run = bool(cfg.get(AUTO_RUN_KEY, False))
        auto_pipeline_name = cfg.get(AUTO_PIPELINE_KEY)
        pipelines = load_pipelines(cfg) if auto_run else {}
        auto_pipeline = pipelines.get(auto_pipeline_name) if auto_pipeline_name else None
        if auto_run and auto_pipeline:
            profiles = load_image_profiles(cfg)
            pipeline_watermark = load_watermark_settings(cfg)
            pipeline_ai_studio = load_ai_studio_settings(cfg)
            pipeline_text_engrave = load_text_engrave_settings(cfg)
            pipeline_qr_code = load_qr_code_settings(cfg)
            pipeline_steps = auto_pipeline.get("steps") or []
            pipeline_profile = profiles.get(auto_pipeline.get("profile")) if auto_pipeline.get("profile") else None
        else:
            pipeline_steps = []

        def _apply_pipeline_if_needed(sku: str, abs_path: str) -> str:
            """اگه پایپ‌لاین خودکار فعاله، تصویر رو پردازش می‌کنه و مسیر
            فایل نهایی (پردازش‌شده) رو برمی‌گردونه؛ وگرنه همون مسیر اصلی."""
            if not (auto_run and auto_pipeline and pipeline_steps):
                return abs_path
            try:
                site_url = str(cfg.get("WC_URL") or "").strip().rstrip("/")
                product_url = ""
                wc_id = load_product_woo_map().get(sku)
                if wc_id and site_url:
                    product_url = f"{site_url}/?p={int(wc_id)}"
                out_dir = os.path.join(os.path.dirname(abs_path), "_pipeline_out")
                os.makedirs(out_dir, exist_ok=True)
                result = run_pipeline(
                    abs_path, pipeline_steps, out_dir=out_dir, profile=pipeline_profile,
                    watermark=pipeline_watermark, ai_studio=pipeline_ai_studio,
                    text_engrave=pipeline_text_engrave, qr_code=pipeline_qr_code,
                    product_info={"a_code": sku, "a_code_c": sku, "name": sku, "product_url": product_url},
                )
                if result.ok and result.dst_path and os.path.isfile(result.dst_path):
                    return result.dst_path
            except Exception as exc:
                log.warning(f"⚠️ روش پردازش تصویر رو {sku} اجرا نشد، فایل اصلی ارسال می‌شه: {exc}")
            return abs_path

        for sku, paths in to_process:
            try:
                wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True)

                while True:
                    wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True)
                    try:
                        res = wc_rest_request(
                            cfg, "GET", "products", params={"sku": sku}, timeout=timeout
                        ).json()
                    except Exception as exc:
                        if is_transient_connectivity_issue(str(exc)):
                            continue
                        raise
                    break

                if not isinstance(res, list) or not res:
                    log.warning(f"⚠️ محصول {sku} در فروشگاه پیدا نشد — رد شد.")
                    fail_count += 1
                    continue

                p_id = res[0]["id"]
                existing_images = res[0].get("images", [])

                new_images = []
                for rel_or_abs in paths:
                    abs_path = self._product_image_abs_path(rel_or_abs)
                    if not abs_path:
                        log.warning(f"⚠️ فایل تصویر پیدا نشد — {sku}: {rel_or_abs}")
                        continue

                    filename = os.path.basename(abs_path)
                    abs_path = _apply_pipeline_if_needed(sku, abs_path)
                    filename = os.path.basename(abs_path)
                    with open(abs_path, "rb") as f:
                        img_data = f.read()

                    src_url = ""
                    media_id = 0
                    upload_err = ""
                    for attempt in range(1, WP_UPLOAD_MAX_ATTEMPTS + 1):
                        wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True)
                        ok, media_id, src_url, upload_err = wp_upload_media_ex(
                            cfg,
                            img_data,
                            filename,
                            fallback_stem=f"prod-{sku}",
                            label=sku,
                        )
                        if ok and src_url:
                            log.info(f"✅ تصویر {filename} برای {sku} آپلود شد.")
                            break
                        if is_wp_upload_fatal_error(upload_err) or not should_retry_upload_error(upload_err):
                            break
                        log.warning(
                            f"⚠️ آپلود {filename} — تلاش {attempt}/{WP_UPLOAD_MAX_ATTEMPTS}: {upload_err}"
                        )

                    if not src_url:
                        log.error(f"❌ خطا در آپلود {filename} برای {sku}: {upload_err}")
                        if is_wp_upload_fatal_error(upload_err):
                            self._last_img_upload_detail = upload_err
                        continue

                    if media_id:
                        new_images.append({"id": int(media_id)})
                    else:
                        new_images.append({"src": src_url})

                if not new_images:
                    log.warning(f"⚠️ هیچ تصویری برای {sku} با موفقیت آپلود نشد.")
                    fail_count += 1
                    continue

                if not replace_mode and existing_images:
                    payload_images = list(existing_images) + new_images
                else:
                    payload_images = new_images

                for attempt in range(1, WP_UPLOAD_MAX_ATTEMPTS + 1):
                    wait_for_connectivity_blocking(cfg, need_sql=False, need_wc=True)
                    try:
                        ok_up, _resp, update_err = update_wc_product_images(
                            cfg, p_id, payload_images, timeout=timeout
                        )
                    except Exception as exc:
                        update_err = str(exc)
                        ok_up = False
                        if should_retry_upload_error(update_err) and attempt < WP_UPLOAD_MAX_ATTEMPTS:
                            continue
                        log.error(f"❌ خطا در تنظیم تصویر محصول {sku}: {update_err}")
                        self._last_img_upload_detail = update_err
                        fail_count += 1
                        break

                    if ok_up:
                        log.info(
                            f"✅ {len(new_images)} تصویر برای محصول {sku} (ID:{p_id}) تنظیم شد."
                        )
                        success_count += 1
                        break

                    if should_retry_upload_error(update_err) and attempt < WP_UPLOAD_MAX_ATTEMPTS:
                        log.warning(
                            f"⚠️ تنظیم تصویر {sku} — تلاش {attempt}/{WP_UPLOAD_MAX_ATTEMPTS}: {update_err}"
                        )
                        continue
                    log.error(f"❌ خطا در تنظیم تصویر محصول {sku}: {update_err}")
                    self._last_img_upload_detail = update_err
                    fail_count += 1
                    break

            except Exception as exc:
                from sync_app.core.sync_cancel import SyncCancelled
                if isinstance(exc, SyncCancelled):
                    raise
                log.error(f"❌ خطای کلی در پردازش {sku}: {exc}")
                fail_count += 1

        if fail_count == 0:
            log.info(f"✅ ارسال تصاویر به پایان رسید. {success_count} محصول موفق.")
        else:
            log.warning(
                f"⚠️ ارسال تصاویر تمام شد. موفق: {success_count} | ناموفق: {fail_count}"
            )
        self._last_img_upload_result = (success_count, fail_count)

    def _images_upload_done(self):
        self._end_prod_images_ui()
        self.refresh_logs()
        ok, fail = getattr(self, "_last_img_upload_result", (0, 0))
        if ok > 0 and fail == 0:
            self._set_products_status("success", f"✅ ارسال تصاویر {ok} محصول با موفقیت انجام شد.")
            QMessageBox.information(
                self, "انجام شد",
                f"ارسال تصاویر با موفقیت انجام شد.\n{ok} محصول بروزرسانی شد."
            )
        elif ok > 0 and fail > 0:
            QMessageBox.warning(
                self, "ناقص",
                f"ارسال تمام شد.\nموفق: {ok} | ناموفق: {fail}\nجزئیات در لاگ تب محصولات."
            )
        else:
            detail = getattr(self, "_last_img_upload_detail", "") or ""
            from sync_app.core.wc_site_profiles import ensure_wc_sites
            from sync_app.core.secure_config_loader import load_secure_config
            from sync_app.core.wp_auth_error_ui import show_wp_media_auth_error_if_applicable

            cfg = ensure_wc_sites(load_secure_config(None) or {})
            if show_wp_media_auth_error_if_applicable(
                self,
                detail,
                cfg,
                context="ارسال تصاویر محصولات متوقف شد — مشکل Application Password",
            ):
                return
            extra = f"\n\n{detail}" if detail else ""
            wp_hint = ""
            if not detail or "application password" in detail.lower() or "wp/v2/media" in detail.lower():
                wp_hint = "\n\nتنظیمات: WP Username + Application Password"
            if "products" in detail.lower() and "wc/v3" not in detail.lower():
                wp_hint = "\n\nتنظیم تصویر محصول از API فروشگاه (Consumer Key با Write) انجام می‌شود."
            QMessageBox.critical(
                self,
                "خطا",
                f"ارسال تصاویر ناموفق بود.\nموفق: {ok} | ناموفق: {fail}\n"
                f"جزئیات در لاگ تب محصولات.{wp_hint}{extra}",
            )

    def _images_upload_error(self, message):
        self._end_prod_images_ui()
        self.refresh_logs()
        if "متوقف" in (message or ""):
            self._set_products_status("info", "⏹ ارسال تصاویر متوقف شد.")
            QMessageBox.information(self, "توقف", "ارسال تصاویر محصولات متوقف شد.")
            return
        QMessageBox.critical(self, "خطا", message)

    def get_wc_api(self):
        if self._wc_api is not None:
            return self._wc_api

        if WCAPI is None:
            return None

        cfg = self.config or {}
        url = cfg.get("WC_URL")
        ck = cfg.get("WC_CONSUMER_KEY")
        cs = cfg.get("WC_CONSUMER_SECRET")
        timeout = int(cfg.get("WC_TIMEOUT", 120))
        if not all([url, ck, cs]):
            return None

        self._wc_api = WCAPI(
            url=url,
            consumer_key=ck,
            consumer_secret=cs,
            timeout=timeout,
            version="wc/v3"
        )
        return self._wc_api

    def get_product_image_url(self, sku):
        if sku in self._image_url_cache:
            return self._image_url_cache[sku]

        try:
            wcapi = self.get_wc_api()
            if wcapi is None:
                self._image_url_cache[sku] = ""
                return ""

            res = wcapi.get("products", params={"sku": sku}).json()
            if isinstance(res, list) and res:
                images = res[0].get("images", [])
                if images:
                    image_url = images[0].get("src", "")
                    self._image_url_cache[sku] = image_url
                    return image_url
        except Exception:
            pass

        self._image_url_cache[sku] = ""
        return ""

    def _load_pixmap_from_blob(self, sku, picture_blob):
        if not picture_blob:
            return None

        cache_key = f"erp-blob:{sku}:{len(picture_blob)}"
        cached = self._image_pixmap_cache.get(cache_key)
        if cached is not None:
            return cached

        loaded_pixmap = QPixmap()
        if loaded_pixmap.loadFromData(picture_blob):
            pixmap = loaded_pixmap.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._image_pixmap_cache[cache_key] = pixmap
            return pixmap
        return None

    def _resolve_local_picture_path(self, picture_path):
        if not picture_path:
            return ""

        normalized = picture_path.strip().strip('"').replace('/', os.sep)
        candidates = [normalized]
        if not os.path.isabs(normalized):
            candidates.append(app_path(normalized))
            candidates.append(os.path.join(os.getcwd(), normalized))

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return ""

    def _load_pixmap_from_path_or_url(self, picture_path):
        if not picture_path:
            return None

        cache_key = f"erp-path:{picture_path}"
        cached = self._image_pixmap_cache.get(cache_key)
        if cached is not None:
            return cached

        pixmap = None
        if picture_path.lower().startswith(("http://", "https://")):
            try:
                data = urllib.request.urlopen(picture_path, timeout=3).read()
                loaded_pixmap = QPixmap()
                if loaded_pixmap.loadFromData(data):
                    pixmap = loaded_pixmap.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                pixmap = None
        else:
            resolved_path = self._resolve_local_picture_path(picture_path)
            if resolved_path:
                loaded_pixmap = QPixmap(resolved_path)
                if not loaded_pixmap.isNull():
                    pixmap = loaded_pixmap.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        if pixmap is not None:
            self._image_pixmap_cache[cache_key] = pixmap
        return pixmap

    def _load_pixmap_from_uploaded_paths(self, sku, paths):
        if not paths:
            return None

        for rel_or_abs in paths:
            abs_path = rel_or_abs
            if not os.path.isabs(abs_path):
                abs_path = app_path(rel_or_abs)
            cache_key = f"uploaded:{sku}:{abs_path}"
            cached = self._image_pixmap_cache.get(cache_key)
            if cached is not None:
                return cached

            if os.path.exists(abs_path):
                loaded = QPixmap(abs_path)
                if not loaded.isNull():
                    pixmap = loaded.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self._image_pixmap_cache[cache_key] = pixmap
                    return pixmap
        return None

    def _build_placeholder_pixmap(self, sku, product_name):
        cache_key = f"placeholder:{sku}"
        cached = self._image_pixmap_cache.get(cache_key)
        if cached is not None:
            return cached

        pixmap = QPixmap(220, 220)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(0, 0, 220, 220, QColor("#f8fafc"))
        painter.setPen(QColor("#cbd5e1"))
        painter.setBrush(QColor("#e2e8f0"))
        painter.drawRoundedRect(8, 8, 204, 204, 18, 18)

        badge_color = QColor("#1a2785")
        painter.setBrush(badge_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(22, 20, 176, 88, 16, 16)

        initial = (product_name or sku or "?").strip()[:1]
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 36, QFont.Bold))
        painter.drawText(22, 20, 176, 88, Qt.AlignCenter, initial)

        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(18, 126, 184, 30, Qt.AlignCenter, "بدون تصویر")

        painter.setPen(QColor("#334155"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(18, 156, 184, 26, Qt.AlignCenter, sku)
        painter.drawText(18, 182, 184, 24, Qt.AlignCenter, (product_name or "کالا")[:26])
        painter.end()

        self._image_pixmap_cache[cache_key] = pixmap
        return pixmap

    def _resolve_hover_pixmap(self, item):
        sku = item.data(Qt.UserRole) or ""
        picture_blob = item.data(Qt.UserRole + 2) or b""
        picture_path = item.data(Qt.UserRole + 3) or ""
        product_name = item.data(Qt.UserRole + 4) or sku
        uploaded_paths = item.data(Qt.UserRole + 7) or []

        pixmap = self._load_pixmap_from_blob(sku, picture_blob)
        if pixmap is not None:
            return pixmap

        pixmap = self._load_pixmap_from_path_or_url(picture_path)
        if pixmap is not None:
            return pixmap

        pixmap = self._load_pixmap_from_uploaded_paths(sku, uploaded_paths)
        if pixmap is not None:
            return pixmap

        image_url = item.data(Qt.UserRole + 1) or ""
        if not image_url and sku:
            image_url = self.get_product_image_url(sku)
            item.setData(Qt.UserRole + 1, image_url)

        if image_url:
            pixmap = self._load_pixmap_from_path_or_url(image_url)
            if pixmap is not None:
                return pixmap

        return self._build_placeholder_pixmap(sku, product_name)

    def on_product_hover(self, item):
        self._current_hover_item = item
        pixmap = self._resolve_hover_pixmap(item)
        if pixmap is not None:
            self.image_preview.setPixmap(pixmap)
            self.image_preview.resize(pixmap.width() + 10, pixmap.height() + 10)
            self._move_preview_near_cursor()
            self.image_preview.show()
        else:
            self.image_preview.hide()

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
        if obj is self.product_list.viewport():
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

            filtered = [
                line for line in all_lines
                if any(token in line for token in ["محصول", "products", "sync_fullproduct", "A_Code"])
            ]
            self.log_view.setPlainText(format_log_lines_jalali(filtered[-50:]))
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
        except Exception as e:
            self.log_view.setPlainText(f"خطا در خواندن لاگ: {e}")

    def _filter_products(self, text):
        """فیلتر لیست محصولات بر اساس متن جستجو + وضعیت لینک فروشگاه + نوع محصول + گروه موجودی"""
        search = text.strip().lower()
        link_mode = self.product_link_filter.currentData() if hasattr(self, "product_link_filter") else "all"
        type_mode = self.product_type_filter.currentData() if hasattr(self, "product_type_filter") else "all"

        group_filter_sku = ""
        allowed_skus = None
        if hasattr(self, "stock_group_filter_input"):
            group_filter_sku = self.stock_group_filter_input.text().strip()
            if group_filter_sku:
                from sync_app.core.stock_group import get_secondaries_of
                secondaries = get_secondaries_of(self.config or {}, group_filter_sku)
                allowed_skus = {group_filter_sku, *secondaries}

        image_presence_mode = "all"
        if hasattr(self, "image_presence_filter"):
            image_presence_mode = self.image_presence_filter.currentData() or "all"

        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            sku = (item.data(Qt.UserRole) or "").lower()
            item_text = (item.data(Qt.UserRole + 6) or "").lower()
            text_match = not search or search in item_text or search in sku

            is_linked = bool(item.data(Qt.UserRole + 12))
            if link_mode == "linked":
                link_match = is_linked
            elif link_mode == "unlinked":
                link_match = not is_linked
            else:
                link_match = True

            is_variant = bool(item.data(Qt.UserRole + 13))
            if type_mode == "simple":
                type_match = not is_variant
            elif type_mode == "variant":
                type_match = is_variant
            else:
                type_match = True

            group_match = allowed_skus is None or (item.data(Qt.UserRole) or "") in allowed_skus

            if image_presence_mode == "all":
                image_match = True
            else:
                real_sku = item.data(Qt.UserRole) or ""
                has_db_image = int(item.data(Qt.UserRole + 15) or 0) > 0
                has_site_image = int(self._wc_image_count_cache.get(real_sku, 0) or 0) > 0
                if image_presence_mode == "db":
                    image_match = has_db_image
                elif image_presence_mode == "site":
                    image_match = has_site_image
                elif image_presence_mode == "both":
                    image_match = has_db_image and has_site_image
                elif image_presence_mode == "none":
                    image_match = not has_db_image and not has_site_image
                else:
                    image_match = True

            item.setHidden(not (text_match and link_match and type_match and group_match and image_match))

    def _set_all_products_checked(self, checked: bool):
        cfg = load_secure_config(None) or {}
        disabled = set(cfg.get("DISABLED_PRODUCT_SKUS", []) or [])
        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            sku = item.data(Qt.UserRole)
            if not sku or item.isHidden():
                continue
            row_widget = self.product_list.itemWidget(item)
            if row_widget is None:
                continue
            row_widget.checkbox.setChecked(checked)
            if checked:
                disabled.discard(sku)
            else:
                disabled.add(sku)
        cfg["DISABLED_PRODUCT_SKUS"] = sorted(disabled)
        from sync_app.core.secure_config_loader import save_secure_config
        save_secure_config(cfg)
        self.config = cfg
