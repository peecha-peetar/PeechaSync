import sys
import os
import time
from PyQt5.QtWidgets import (
    QMessageBox, QLabel, QListWidget, QPushButton, QListWidgetItem,
    QDialog, QVBoxLayout, QScrollArea, QFrame, QWidget,
)
from sync_app.core.rtl_item_delegate import RightAlignedCheckableItemDelegate, make_rtl_item
from PyQt5.QtCore import QTimer, Qt

# مسیردهی پایه برای تب همگام‌سازی سفارشات
from sync_app.core.base_tabs.sync_tab import SyncTab
from sync_app.core.tabs.tab_license import LicenseTab
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.event_notifier import notify_and_log
from sync_app.core.sync_utils import log
from sync_app.core.store_setup_guard import ensure_store_pages_ready
from sync_app.core.site_preview_loader import SitePreviewLoaderMixin, site_preview_http_timeout
from sync_app.core.wc_admin_links import make_wc_admin_open_button
from sync_app.core.connectivity_service import format_network_error_message
from sync_app.core.wc_sync_helper import wc_rest_request, wc_http_error_message
from sync_app.core.responsive_action_bar import build_responsive_action_row
from sync_app.core.compact_icon_action_bar import CompactCaptionButton

# 📌 اجرای مستقیم اسکریپت سفارشات
from sync_app.core.scripts import ordersync

# وضعیت‌هایِ سفارشِ ووکامرس — کدهایِ انگلیسیِ خودِ WooCommerce، برایِ
# نمایش هم تویِ کمبویِ فیلتر و هم تویِ ردیفِ خودِ سفارش به فارسی ترجمه
# می‌شن (قبلاً ردیفِ سفارش وضعیت رو خامِ انگلیسی نشون می‌داد).
def _load_synced_order_ids(config: dict) -> set:
    """مجموعه‌یِ کدِ سفارش‌هایِ سایتی که از قبل به فاکتور/سفارشِ ERP
    تبدیل شده‌ن — برایِ نشونه‌گذاریِ «همگام‌شده» در پیش‌نمایشِ سفارشاتِ
    سایت. عیناً هم‌منطقِ چکِ RqIndex2 (دژاوو)/sepidar_order_map.json
    (سپیدار) که insert_order/insert_invoke هنگامِ سینکِ واقعی استفاده
    می‌کنن — این‌جا فقط برایِ نمایشه، بدونِ نوشتن."""
    from sync_app.core.scripts.sepidar.sepidar_common import is_sepidar_provider

    ids: set = set()
    if is_sepidar_provider(config):
        from sync_app.core.scripts.sepidar.sepidar_common import load_sepidar_map

        order_map = load_sepidar_map("sepidar_order_map.json")
        for k in order_map.keys():
            try:
                ids.add(int(k))
            except (TypeError, ValueError):
                continue
        return ids

    try:
        from sync_app.core.sql_connection_helper import open_sql_connection

        conn, _, _ = open_sql_connection(config, timeout=10)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT RqIndex2 FROM RqTitle WHERE RqIndex2 IS NOT NULL")
            for row in cursor.fetchall():
                try:
                    ids.add(int(row[0]))
                except (TypeError, ValueError):
                    continue
        finally:
            conn.close()
    except Exception:
        pass
    return ids


ORDER_STATUS_LABELS = {
    "any": "همه",
    "processing": "در حال انجام",
    "pending": "در انتظار پرداخت",
    "on-hold": "معلق",
    "completed": "تکمیل‌شده",
    "cancelled": "لغوشده",
    "refunded": "بازگشت‌وجه",
    "failed": "ناموفق",
    "draft": "پیش‌نویس",
    "trash": "حذف‌شده",
    "checkout-draft": "پیش‌نویسِ پرداخت",
}


def order_status_label(raw_status: str) -> str:
    key = str(raw_status or "").strip().lower()
    return ORDER_STATUS_LABELS.get(key, str(raw_status or "-"))


def _fmt_order_num(value):
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "—"


class OrderDetailsDialog(QDialog):
    """نمایشِ اقلامِ یک سفارشِ سایت — با دابل‌کلیک روی ردیفِ سفارش باز می‌شه."""

    def __init__(self, parent, order: dict):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        order_id = order.get("id", "—")
        self.setWindowTitle(f"اقلامِ سفارش #{order_id}")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.resize(560, 480)

        root = QVBoxLayout(self)

        billing = order.get("billing") or {}
        customer_name = (
            f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or "—"
        )
        header = QLabel(f"سفارش #{order_id}  |  مشتری: {customer_name}")
        header.setStyleSheet("font-weight: 800; font-size: 14px;")
        header.setAlignment(Qt.AlignRight)
        root.addWidget(header)

        body = QScrollArea()
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        vl = QVBoxLayout(host)
        vl.setSpacing(6)

        line_items = order.get("line_items") or []
        if not line_items:
            empty = QLabel("هیچ قلمی برای این سفارش یافت نشد.")
            empty.setAlignment(Qt.AlignRight)
            vl.addWidget(empty)
        for row_item in line_items:
            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; }"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 8, 10, 8)
            name = str(row_item.get("name") or "—")
            sku = str(row_item.get("sku") or "—")
            qty = _fmt_order_num(row_item.get("quantity"))
            price = _fmt_order_num(row_item.get("price"))
            total = _fmt_order_num(row_item.get("total", row_item.get("subtotal")))

            title_lbl = QLabel(f"{name}  (SKU: {sku})")
            title_lbl.setStyleSheet("font-weight: 700; color: #0f172a;")
            title_lbl.setAlignment(Qt.AlignRight)
            title_lbl.setWordWrap(True)
            cl.addWidget(title_lbl)

            detail_lbl = QLabel(f"تعداد: {qty}  |  قیمت واحد: {price}  |  جمع: {total}")
            detail_lbl.setAlignment(Qt.AlignRight)
            cl.addWidget(detail_lbl)

            vl.addWidget(card)

        vl.addStretch(1)
        body.setWidget(host)
        root.addWidget(body, 1)

        close_btn = QPushButton("بستن")
        close_btn.setMinimumHeight(36)
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn)


class OrderTab(SitePreviewLoaderMixin, SyncTab):
    def __init__(self):
        super().__init__("ordersync.py", "سفارشات")
        self._last_orders_refresh_at = 0.0
        self._seen_order_ids = set()
        self._orders_baseline_ready = False
        self._initial_load_started = False

        self.orders_preview_label = QLabel("📥 سفارشات اخیر سایت:")
        self.orders_preview_label.setStyleSheet("font-weight: bold;")

        from PyQt5.QtWidgets import QComboBox, QHBoxLayout
        from sync_app.core.jalali_date_widget import JalaliDateEdit

        # همه‌ی فیلترها (وضعیت + بازه‌ی تاریخ) تویِ یک ردیف — قبلاً دو ردیفِ
        # جدا بودن که هم فضایِ اضافه می‌گرفت هم لازم نبود.
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("وضعیت:"))
        self.order_status_filter = QComboBox()
        self.order_status_filter.setLayoutDirection(Qt.RightToLeft)
        for value in ("any", "processing", "pending", "on-hold", "completed", "cancelled", "refunded", "failed"):
            self.order_status_filter.addItem(ORDER_STATUS_LABELS[value], value)
        from sync_app.core.integrations.erp_provider import erp_provider_label
        from sync_app.core.secure_config_loader import load_secure_config

        self.order_status_filter.setToolTip(
            "این فیلتر فقط روی نمایش لیست همین‌جاست — منطق انتقال سفارش به "
            f"{erp_provider_label(load_secure_config(None))} (که فقط سفارش‌های «در حال انجام» رو می‌بره) تغییری نمی‌کنه."
        )
        self.order_status_filter.currentIndexChanged.connect(
            lambda: self.load_site_orders(silent=False, show_error_dialog=False)
        )
        filter_row.addWidget(self.order_status_filter)

        # فیلترِ بازه‌ی تاریخِ شمسی — پیش‌فرض از اولِ ماهِ جاری تا امروز؛
        # وگرنه این تب بدونِ هیچ فیلترِ اولیه‌ای همه‌ی سفارش‌ها (حتی خیلی
        # قدیمی) رو می‌آورد.
        filter_row.addWidget(QLabel("از تاریخ:"))
        self.order_date_from = JalaliDateEdit()
        self.order_date_from.set_start_of_month()
        filter_row.addWidget(self.order_date_from)
        filter_row.addWidget(QLabel("تا تاریخ:"))
        self.order_date_to = JalaliDateEdit()
        filter_row.addWidget(self.order_date_to)
        self.order_date_from.dateChanged.connect(
            lambda: self.load_site_orders(silent=False, show_error_dialog=False)
        )
        self.order_date_to.dateChanged.connect(
            lambda: self.load_site_orders(silent=False, show_error_dialog=False)
        )

        # انتخابِ دستیِ سفارش‌ها — پیش‌فرض همه تیک‌خورده (رفتارِ قبلی: ارسالِ
        # همه‌یِ سفارش‌هایِ در حالِ نمایش)، ولی کاربر می‌تونه با فیلترهایِ
        # بالا + این دو دکمه/تیکِ هر ردیف، فقط زیرمجموعه‌ای رو دستی بفرسته.
        self.orders_select_all_btn = CompactCaptionButton("☑️ انتخابِ همه")
        self.orders_select_all_btn.clicked.connect(self._select_all_orders)
        filter_row.addWidget(self.orders_select_all_btn)
        self.orders_select_none_btn = CompactCaptionButton("☐ هیچ‌کدام")
        self.orders_select_none_btn.clicked.connect(self._select_no_orders)
        filter_row.addWidget(self.orders_select_none_btn)

        filter_row.addStretch()

        self.orders_list = QListWidget()
        self.orders_list.setLayoutDirection(Qt.RightToLeft)
        self.orders_list.setMinimumHeight(240)
        self.orders_list.setItemDelegate(RightAlignedCheckableItemDelegate(self.orders_list))
        self.orders_list.setToolTip("برای دیدن اقلامِ سفارش، روی ردیف دابل‌کلیک کنید.")
        self.orders_list.itemDoubleClicked.connect(self._show_order_details)
        self.orders_refresh_button = CompactCaptionButton("🔄 بازخوانی سفارشات سایت")
        self.wc_admin_button = make_wc_admin_open_button(
            self, "orders", button_factory=CompactCaptionButton
        )

        self._init_site_preview_loader(
            entity_label="سفارشات",
            list_widget=self.orders_list,
            refresh_button=self.orders_refresh_button,
            run_button=self.run_button,
            content_layout=self.content_layout,
            insert_at=1,
            auto_fetch_config_key="AUTO_PREVIEW_ORDERS",
            manual_refresh_callable=lambda: self.load_site_orders(
                silent=False, show_error_dialog=True
            ),
        )

        self.content_layout.insertWidget(3, self.orders_preview_label)
        self.content_layout.insertLayout(4, filter_row)
        self.content_layout.insertWidget(5, self.orders_list)
        self.content_layout.setStretchFactor(self.orders_list, 1)

        self.content_layout.addWidget(
            build_responsive_action_row(
                [self.orders_refresh_button, self.run_button, self.wc_admin_button],
                parent=self,
            )
        )

        # تایمر برای بروزرسانی لاگ‌ها
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.auto_refresh_logic)
        self.refresh_timer.start(1500)

    def ensure_tab_data_loaded(self):
        if self._initial_load_started:
            return
        self._initial_load_started = True
        self._update_store_setup_status()
        QTimer.singleShot(
            0,
            lambda: self.load_site_orders(silent=False, show_error_dialog=False),
        )

    def _update_store_setup_status(self):
        from sync_app.core.integrations.commerce_provider import is_prestashop

        cfg = load_secure_config(None) or {}
        if is_prestashop(cfg):
            return
        from sync_app.core.scripts.woocommerce_store_setup import store_pages_ready
        if store_pages_ready(cfg):
            return
        self.set_status(
            "warning",
            "⚠️ Cart/Checkout راه‌اندازی نشده — از تب تنظیمات دکمه «راه‌اندازی Cart/Checkout» را بزنید",
        )

    def auto_refresh_logic(self):
        """بازخوانی لاگ‌ها برای نمایش زنده"""
        try:
            if self.isVisible() and hasattr(self, 'refresh_logs'):
                self.refresh_logs()
            if (
                hasattr(self, 'load_site_orders')
                and self.isVisible()
                and self._is_site_auto_fetch_enabled()
                and self._wc_badge_allows_fetch()
                and not self._site_fetch_in_flight
                and (time.monotonic() - self._last_orders_refresh_at) >= 8
            ):
                self.load_site_orders(silent=True)
        except Exception:
            pass

    def _select_all_orders(self):
        for i in range(self.orders_list.count()):
            item = self.orders_list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Checked)

    def _select_no_orders(self):
        for i in range(self.orders_list.count()):
            item = self.orders_list.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Unchecked)

    def _collect_checked_order_ids(self) -> set:
        ids = set()
        for i in range(self.orders_list.count()):
            item = self.orders_list.item(i)
            if not (item.flags() & Qt.ItemIsUserCheckable):
                continue
            if item.checkState() != Qt.Checked:
                continue
            order_id = item.data(Qt.UserRole)
            if order_id is not None:
                ids.add(int(order_id))
        return ids

    def _show_order_details(self, item):
        order_id = item.data(Qt.UserRole)
        if order_id is None:
            return
        self.set_status("info", f"⏳ در حال دریافت اقلام سفارش #{order_id}...")
        run_in_thread(
            lambda: self._fetch_order_details(int(order_id)),
            on_complete=self._display_order_details,
            on_error=self._handle_order_details_error,
        )

    def _fetch_order_details(self, order_id):
        cfg = load_secure_config(None) or {}
        timeout = site_preview_http_timeout(cfg)

        from sync_app.core.integrations.commerce_provider import is_prestashop
        if is_prestashop(cfg):
            from sync_app.core.ps_order_helper import ps_get_order
            order = ps_get_order(cfg, order_id, timeout=timeout)
            if not order:
                raise Exception(f"سفارش #{order_id} یافت نشد.")
            return order

        response = wc_rest_request(cfg, "GET", f"orders/{order_id}", timeout=timeout)
        if int(response.status_code or 0) >= 400:
            raise RuntimeError(
                wc_http_error_message(
                    response, cfg, prefix=f"دریافت اقلام سفارش #{order_id} ناموفق"
                )
            )
        data = response.json()
        line_items = [
            {
                "name": li.get("name"),
                "sku": li.get("sku"),
                "quantity": li.get("quantity"),
                "price": li.get("price"),
                "total": li.get("total"),
            }
            for li in (data.get("line_items") or [])
        ]
        return {
            "id": data.get("id"),
            "billing": data.get("billing") or {},
            "line_items": line_items,
        }

    def _display_order_details(self, order):
        self.set_status("success", f"✅ اقلام سفارش #{order.get('id', '—')} دریافت شد")
        dlg = OrderDetailsDialog(self, order)
        dlg.exec_()

    def _handle_order_details_error(self, error):
        message = f"❌ خطا در دریافت اقلام سفارش: {error}"
        self.set_status("error", message[:120])
        QMessageBox.critical(self, "خطا", f"دریافت اقلام سفارش ناموفق بود:\n{error}")

    def start_sync(self):
        """اجرای مستقیم اسکریپت سفارشات"""
        if not LicenseTab.is_license_valid():
            QMessageBox.critical(self, "خطا", "لایسنس معتبر نیست.")
            return

        if not ensure_store_pages_ready(self):
            self.set_status("warning", "⚠️ ابتدا Cart/Checkout را در تنظیمات راه‌اندازی کنید")
            return

        if self.orders_list.count() == 0:
            QMessageBox.information(
                self, "سفارشی نیست",
                "ابتدا «🔄 بازخوانی سفارشات سایت» را بزنید تا سفارش‌ها نمایش داده شوند.",
            )
            return

        checked_ids = self._collect_checked_order_ids()
        if not checked_ids:
            QMessageBox.information(
                self, "چیزی انتخاب نشده",
                "حداقل یک سفارش را تیک بزنید، یا «☑️ انتخاب همه» را بزنید.",
            )
            return

        from sync_app.core.scripts.sepidar.sepidar_common import is_sepidar_provider
        config = load_secure_config(None) or {}
        if is_sepidar_provider(config):
            from sync_app.core.scripts.sepidar import sepidar_ordersync
            sync_job = lambda: sepidar_ordersync.main(order_ids=checked_ids)
        else:
            sync_job = lambda: ordersync.main(order_ids=checked_ids)

        self.run_job_in_background(
            sync_job,
            busy_text="⏳ در حال پردازش سفارشات...",
            success_message="همگام‌سازی سفارشات با موفقیت انجام شد.",
        )
        self.load_site_orders(silent=True)

    def run_script(self):
        self.start_sync()

    def _orders_endpoint(self):
        cfg = load_secure_config(None) or {}
        wc_url = (cfg.get("WC_URL") or "").strip().rstrip("/")

        if "wp-json/wc/v3" in wc_url:
            return f"{wc_url}/orders", cfg
        return f"{wc_url}/wp-json/wc/v3/orders", cfg

    def load_site_orders(self, silent=False, show_error_dialog=None):
        if show_error_dialog is None:
            show_error_dialog = not silent
        if silent and not self._is_site_auto_fetch_enabled():
            return
        if not self._wc_badge_allows_fetch():
            if not silent:
                self._show_wc_not_ready_message()
            return
        if self._site_fetch_in_flight:
            if not silent:
                self.set_status("warning", "⏳ دریافت قبلی هنوز در جریان است...")
            return

        generation = self._next_site_fetch_generation()
        self._last_orders_refresh_at = time.monotonic()
        self._begin_site_fetch(silent=silent)

        # مقدار فیلترها رو همین‌جا (تو Thread اصلی UI) می‌خونیم — نه داخل
        # Thread پس‌زمینه‌ی fetch — چون خوندن ویجت Qt از یه Thread دیگه ایمن نیست.
        status_filter = "any"
        if hasattr(self, "order_status_filter"):
            status_filter = str(self.order_status_filter.currentData() or "any")

        date_from = date_to = None
        if hasattr(self, "order_date_from") and hasattr(self, "order_date_to"):
            date_from = self.order_date_from.get_gregorian_date()
            date_to = self.order_date_to.get_gregorian_date()
            if date_from > date_to:
                date_from, date_to = date_to, date_from

        on_complete, on_error = self._wrap_site_fetch_callbacks(
            generation,
            lambda payload: self._apply_site_orders(payload, silent),
            lambda error: self._handle_site_orders_error(
                error, silent, show_error_dialog=show_error_dialog
            ),
        )

        run_in_thread(
            lambda: self._fetch_site_orders(status_filter, date_from, date_to),
            on_complete=on_complete,
            on_error=on_error,
        )

    def _fetch_site_orders(self, status_filter="any", date_from=None, date_to=None):
        try:
            cfg = load_secure_config(None) or {}
            timeout = site_preview_http_timeout(cfg)

            from sync_app.core.integrations.commerce_provider import is_prestashop
            if is_prestashop(cfg):
                return self._fetch_site_orders_ps(cfg, timeout, date_from, date_to)

            ck = cfg.get("WC_CONSUMER_KEY")
            cs = cfg.get("WC_CONSUMER_SECRET")

            if not cfg.get("WC_URL") or not ck or not cs:
                return {"kind": "message", "items": ["⚠️ تنظیمات ووکامرس کامل نیست."]}

            params = {"per_page": 100, "orderby": "date", "order": "desc", "status": status_filter}
            if date_from is not None:
                params["after"] = f"{date_from.isoformat()}T00:00:00"
            if date_to is not None:
                from datetime import timedelta

                params["before"] = f"{(date_to + timedelta(days=1)).isoformat()}T00:00:00"

            response = wc_rest_request(
                cfg,
                "GET",
                "orders",
                params=params,
                timeout=timeout,
            )
            if int(response.status_code or 0) >= 400:
                raise RuntimeError(
                    wc_http_error_message(
                        response,
                        cfg,
                        prefix="دریافت سفارشات سایت ناموفق",
                    )
                )

            orders = response.json() if isinstance(response.json(), list) else []
            if not orders:
                return {"kind": "message", "items": ["ℹ️ سفارشی روی سایت یافت نشد."], "ids": []}

            synced_ids = _load_synced_order_ids(cfg)
            # وقتی سفارش مهمان/دستی بدونِ پرکردنِ فرمِ صورتحساب ثبت شده،
            # billing.first_name/last_name خالیه — ولی اگه به یک حسابِ
            # مشتریِ ثبت‌نام‌شده (customer_id) وصله، اسمِ همون حساب رو
            # به‌عنوانِ fallback می‌گیریم (با کشِ محلی، چون چند سفارش از
            # یک مشتریِ تکراری معمولاً پیش می‌آد).
            customer_name_cache: dict[int, str] = {}

            def _wc_customer_name(customer_id: int) -> str:
                if customer_id not in customer_name_cache:
                    resolved = ""
                    try:
                        resp = wc_rest_request(cfg, "GET", f"customers/{customer_id}", timeout=timeout)
                        if int(getattr(resp, "status_code", 0) or 0) < 400:
                            data = resp.json() or {}
                            billing_c = data.get("billing") or {}
                            first_c = str(data.get("first_name") or billing_c.get("first_name") or "").strip()
                            last_c = str(data.get("last_name") or billing_c.get("last_name") or "").strip()
                            resolved = f"{first_c} {last_c}".strip()
                    except Exception:
                        resolved = ""
                    customer_name_cache[customer_id] = resolved
                return customer_name_cache[customer_id]

            items = []
            ids = []
            for order in orders:
                order_id = order.get("id", "-")
                status = order_status_label(order.get("status", "-"))
                total = order.get("total", "0")
                currency = order.get("currency", "")
                billing = order.get("billing", {}) or {}
                name = (f"{billing.get('first_name', '')} {billing.get('last_name', '')}").strip()
                if not name:
                    customer_id = int(order.get("customer_id") or 0)
                    if customer_id:
                        name = _wc_customer_name(customer_id)
                name = name or "مشتری"
                try:
                    numeric_id = int(order_id)
                except Exception:
                    continue
                ids.append(numeric_id)
                sync_badge = "🔗 " if numeric_id in synced_ids else ""
                items.append(f"{sync_badge}{name} | کد سفارش: #{order_id} | وضعیت: {status} | مبلغ: {total} {currency}")

            return {"kind": "orders", "items": items, "ids": ids}
        except Exception as e:
            cfg = load_secure_config(None) or {}
            raise Exception(format_network_error_message(e, cfg))

    def _fetch_site_orders_ps(self, cfg, timeout, date_from=None, date_to=None):
        # پرستاشاپ برخلاف ووکامرس وضعیت سفارش رو با current_state (عدد
        # قابل‌تنظیم توسط فروشگاه) نشون می‌ده، نه یک رشته‌ی ثابت — این پیش‌نمایش
        # فیلتر وضعیت رو نادیده می‌گیره و «پرداخت‌شده/در انتظار» رو از روی
        # فیلد valid نشون می‌ده (همون فیلدی که ordersync.py هم برای انتخاب
        # سفارش‌های واقعی استفاده می‌کنه).
        # فیلترِ بازه‌ی تاریخ هم (برخلافِ ووکامرس که سمتِ سرور با after/before
        # انجام می‌شه) این‌جا سمتِ کلاینت روی date_add اعمال می‌شه — همون
        # الگویِ ps_list_orders_for_sales_report، چون سینتکسِ فیلترِ تاریخِ
        # Webserviceِ پرستاشاپ با اطمینان تأیید نشده.
        if not cfg.get("PS_URL") or not cfg.get("PS_API_KEY"):
            return {"kind": "message", "items": ["⚠️ تنظیمات پرستاشاپ کامل نیست."]}

        from sync_app.core.ps_order_helper import ps_list_recent_orders_preview

        try:
            orders = ps_list_recent_orders_preview(cfg, limit=100, timeout=timeout)
        except Exception as e:
            raise Exception(format_network_error_message(e, cfg))

        if date_from is not None or date_to is not None:
            from_str = date_from.isoformat() if date_from is not None else ""
            to_str = date_to.isoformat() if date_to is not None else "9999-99-99"
            orders = [
                o for o in orders
                if from_str <= str(o.get("date_add") or "")[:10] <= to_str
            ]

        if not orders:
            return {"kind": "message", "items": ["ℹ️ سفارشی روی سایت یافت نشد."], "ids": []}

        synced_ids = _load_synced_order_ids(cfg)
        items = []
        ids = []
        for order in orders:
            status_label = "پرداخت‌شده" if order.get("valid") else "در انتظار پرداخت"
            ids.append(order["id"])
            name = str(order.get("customer_name") or "").strip() or f"مشتری #{order.get('customer_id') or '-'}"
            sync_badge = "🔗 " if order["id"] in synced_ids else ""
            items.append(
                f"{sync_badge}{name} | کد سفارش: #{order['id']} | "
                f"وضعیت: {status_label} | مبلغ: {order.get('total_paid')}"
            )
        return {"kind": "orders", "items": items, "ids": ids}

    def _apply_site_orders(self, payload, silent=False):
        self.orders_list.clear()
        payload = payload or {}
        items = payload.get("items", []) or []
        order_ids_list = payload.get("ids", []) or []
        ids = set(order_ids_list)

        if self._orders_baseline_ready:
            new_ids = ids - self._seen_order_ids
            if new_ids:
                newest = max(new_ids)
                count_new = len(new_ids)
                message = f"{count_new} سفارش جدید ثبت شد. آخرین کد سفارش: #{newest}"
                notify_and_log("orders", "سفارش جدید", message)

        self._seen_order_ids = ids
        self._orders_baseline_ready = True

        if payload.get("kind") == "orders":
            # هر ردیف با تیکِ قابلِ‌انتخاب — پیش‌فرض تیک‌خورده، تا رفتارِ
            # فعلیِ «ارسالِ همه» برایِ کسی که کاری با تیک‌ها نداره حفظ بمونه.
            for text, order_id in zip(items, order_ids_list):
                item = make_rtl_item(text)
                item.setData(Qt.UserRole, order_id)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.orders_list.addItem(item)
        else:
            for text in items:
                self.orders_list.addItem(make_rtl_item(text))

        if payload.get("kind") == "orders":
            count = len(payload.get("ids", []))
            if count:
                self.set_status("success", f"✅ {count} سفارش از سایت دریافت شد")
                if not silent:
                    log.info(f"📋 بازخوانی سفارشات سایت: {count} مورد")
        elif payload.get("items"):
            self.set_status("info", str(payload["items"][0])[:120])
            if not silent:
                log.info(f"📋 بازخوانی سفارشات سایت: {payload['items'][0][:120]}")

        self.refresh_logs()

    def _handle_site_orders_error(self, error, silent=False, show_error_dialog=True):
        self.orders_list.clear()
        message = f"❌ خطا در دریافت سفارشات سایت: {error}"
        self.orders_list.addItem(make_rtl_item(message))
        self.set_status("error", message[:120])
        if show_error_dialog:
            QMessageBox.critical(self, "خطا", f"دریافت سفارشات سایت ناموفق بود:\n{error}")
