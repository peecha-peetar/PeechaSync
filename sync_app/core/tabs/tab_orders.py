import sys
import os
import time
from PyQt5.QtWidgets import QMessageBox, QLabel, QListWidget, QPushButton, QListWidgetItem
from sync_app.core.rtl_item_delegate import RightAlignedItemDelegate, make_rtl_item
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
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("فیلتر نمایش وضعیت:"))
        self.order_status_filter = QComboBox()
        self.order_status_filter.setLayoutDirection(Qt.RightToLeft)
        for value, label in (
            ("any", "همه"),
            ("processing", "در حال انجام"),
            ("pending", "در انتظار پرداخت"),
            ("on-hold", "معلق"),
            ("completed", "تکمیل‌شده"),
            ("cancelled", "لغوشده"),
            ("refunded", "بازگشت‌وجه"),
            ("failed", "ناموفق"),
        ):
            self.order_status_filter.addItem(label, value)
        self.order_status_filter.setToolTip(
            "این فیلتر فقط روی نمایش لیست همین‌جاست — منطق انتقال سفارش به "
            "ERP (که فقط سفارش‌های «در حال انجام» رو می‌بره) تغییری نمی‌کنه."
        )
        self.order_status_filter.currentIndexChanged.connect(
            lambda: self.load_site_orders(silent=False, show_error_dialog=False)
        )
        filter_row.addWidget(self.order_status_filter)
        filter_row.addStretch()

        self.orders_list = QListWidget()
        self.orders_list.setLayoutDirection(Qt.RightToLeft)
        self.orders_list.setMinimumHeight(240)
        self.orders_list.setItemDelegate(RightAlignedItemDelegate(self.orders_list))
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
        from sync_app.core.scripts.woocommerce_store_setup import store_pages_ready
        if store_pages_ready(load_secure_config(None)):
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

    def start_sync(self):
        """اجرای مستقیم اسکریپت سفارشات"""
        if not LicenseTab.is_license_valid():
            QMessageBox.critical(self, "خطا", "لایسنس معتبر نیست.")
            return

        if not ensure_store_pages_ready(self):
            self.set_status("warning", "⚠️ ابتدا Cart/Checkout را در تنظیمات راه‌اندازی کنید")
            return

        self.run_job_in_background(
            ordersync.main,
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

        # مقدار فیلتر رو همین‌جا (تو Thread اصلی UI) می‌خونیم — نه داخل
        # Thread پس‌زمینه‌ی fetch — چون خوندن ویجت Qt از یه Thread دیگه ایمن نیست.
        status_filter = "any"
        if hasattr(self, "order_status_filter"):
            status_filter = str(self.order_status_filter.currentData() or "any")

        on_complete, on_error = self._wrap_site_fetch_callbacks(
            generation,
            lambda payload: self._apply_site_orders(payload, silent),
            lambda error: self._handle_site_orders_error(
                error, silent, show_error_dialog=show_error_dialog
            ),
        )

        run_in_thread(
            lambda: self._fetch_site_orders(status_filter),
            on_complete=on_complete,
            on_error=on_error,
        )

    def _fetch_site_orders(self, status_filter="any"):
        try:
            cfg = load_secure_config(None) or {}
            ck = cfg.get("WC_CONSUMER_KEY")
            cs = cfg.get("WC_CONSUMER_SECRET")
            timeout = site_preview_http_timeout(cfg)

            if not cfg.get("WC_URL") or not ck or not cs:
                return {"kind": "message", "items": ["⚠️ تنظیمات ووکامرس کامل نیست."]}

            response = wc_rest_request(
                cfg,
                "GET",
                "orders",
                params={"per_page": 20, "orderby": "date", "order": "desc", "status": status_filter},
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

            items = []
            ids = []
            for order in orders:
                order_id = order.get("id", "-")
                status = order.get("status", "-")
                total = order.get("total", "0")
                currency = order.get("currency", "")
                billing = order.get("billing", {}) or {}
                name = (f"{billing.get('first_name', '')} {billing.get('last_name', '')}").strip() or "مشتری"
                try:
                    ids.append(int(order_id))
                except Exception:
                    pass
                items.append(f"{name} | کد سفارش: #{order_id} | وضعیت: {status} | مبلغ: {total} {currency}")

            return {"kind": "orders", "items": items, "ids": ids}
        except Exception as e:
            cfg = load_secure_config(None) or {}
            raise Exception(format_network_error_message(e, cfg))

    def _apply_site_orders(self, payload, silent=False):
        self.orders_list.clear()
        payload = payload or {}
        ids = set(payload.get("ids", []))

        if self._orders_baseline_ready:
            new_ids = ids - self._seen_order_ids
            if new_ids:
                newest = max(new_ids)
                count_new = len(new_ids)
                message = f"{count_new} سفارش جدید ثبت شد. آخرین کد سفارش: #{newest}"
                notify_and_log("orders", "سفارش جدید", message)

        self._seen_order_ids = ids
        self._orders_baseline_ready = True

        for item in payload.get("items", []):
            self.orders_list.addItem(make_rtl_item(item))

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
