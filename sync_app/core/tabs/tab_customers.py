import sys
import os
import time
from PyQt5.QtWidgets import QMessageBox, QLabel, QListWidget, QPushButton, QListWidgetItem
from sync_app.core.rtl_item_delegate import RightAlignedItemDelegate, make_rtl_item
from PyQt5.QtCore import QTimer, Qt

# tab base
from sync_app.core.base_tabs.sync_tab import SyncTab
from sync_app.core.tabs.tab_license import LicenseTab
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.customer_context import get_customer_mode
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.event_notifier import notify_and_log
from sync_app.core.sync_utils import log
from sync_app.core.site_preview_loader import SitePreviewLoaderMixin, site_preview_http_timeout
from sync_app.core.wc_admin_links import make_wc_admin_open_button
from sync_app.core.connectivity_service import classify_network_error, format_network_error_message
from sync_app.core.responsive_action_bar import build_responsive_action_row
from sync_app.core.compact_icon_action_bar import CompactCaptionButton

# import customersync
from sync_app.core.scripts import customersync


class CustomerTab(SitePreviewLoaderMixin, SyncTab):
    def __init__(self):
        super().__init__("customersync.py", "مشتریان")
        self._last_customers_refresh_at = 0.0
        self._seen_customer_ids = set()
        self._customers_baseline_ready = False
        self._initial_load_started = False

        self.customers_preview_label = QLabel("👥 مشتریان اخیر سایت:")
        self.customers_preview_label.setStyleSheet("font-weight: bold;")
        self.customers_list = QListWidget()
        self.customers_list.setLayoutDirection(Qt.RightToLeft)
        self.customers_list.setMinimumHeight(240)
        self.customers_list.setItemDelegate(RightAlignedItemDelegate(self.customers_list))
        self.customers_refresh_button = CompactCaptionButton("🔄 بازخوانی مشتریان سایت")
        self.wc_admin_button = make_wc_admin_open_button(
            self, "customers", button_factory=CompactCaptionButton
        )

        self._init_site_preview_loader(
            entity_label="مشتریان",
            list_widget=self.customers_list,
            refresh_button=self.customers_refresh_button,
            run_button=self.run_button,
            content_layout=self.content_layout,
            insert_at=1,
            auto_fetch_config_key="AUTO_PREVIEW_CUSTOMERS",
            manual_refresh_callable=lambda: self.load_site_customers(
                silent=False, show_error_dialog=True
            ),
        )

        self.content_layout.insertWidget(3, self.customers_preview_label)
        self.content_layout.insertWidget(4, self.customers_list)
        self.content_layout.setStretchFactor(self.customers_list, 1)

        self.content_layout.addWidget(
            build_responsive_action_row(
                [self.customers_refresh_button, self.run_button, self.wc_admin_button],
                parent=self,
            )
        )

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._preview_timer_tick)
        self.preview_timer.start(10000)

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(lambda: self.refresh_logs() if self.isVisible() else None)
        self.log_timer.start(2000)

    def run_script(self):
        self.start_sync()

    def _preview_timer_tick(self):
        if (
            self.isVisible()
            and self._is_site_auto_fetch_enabled()
            and self._wc_badge_allows_fetch()
            and not self._site_fetch_in_flight
            and (time.monotonic() - self._last_customers_refresh_at) >= 10
        ):
            self.load_site_customers(silent=True)

    def ensure_tab_data_loaded(self):
        if self._initial_load_started:
            return
        self._initial_load_started = True
        QTimer.singleShot(
            0,
            lambda: self.load_site_customers(silent=False, show_error_dialog=False),
        )

    def start_sync(self):
        """ run customersync """
        if not LicenseTab.is_license_valid():
            QMessageBox.critical(self, "خطا", "لایسنس معتبر نیست.")
            return

        if self.run_job_in_background(
            customersync.main,
            busy_text="⏳ در حال اجرا...",
            success_message="همگام‌سازی مشتریان با موفقیت انجام شد.",
        ):
            QTimer.singleShot(800, lambda: self.load_site_customers(silent=True))

    def load_site_customers(self, silent=False, show_error_dialog=None):
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
        self._last_customers_refresh_at = time.monotonic()
        self._begin_site_fetch(silent=silent)

        on_complete, on_error = self._wrap_site_fetch_callbacks(
            generation,
            lambda payload: self._apply_site_customers(payload, silent),
            lambda error: self._handle_site_customers_error(
                error, silent, show_error_dialog=show_error_dialog
            ),
        )

        run_in_thread(
            self._fetch_site_customers,
            on_complete=on_complete,
            on_error=on_error,
        )

    def _fetch_site_customers(self):
        try:
            cfg = load_secure_config(None) or {}
            mode = get_customer_mode(cfg)
            if mode == "fixed":
                code = (cfg.get("DEFAULT_CUSTOMER_CODE") or "00005").strip()
                return {
                    "items": [f"حالت مشتری ثابت فعال است — کد ERP: {code}"],
                    "ids": [],
                }

            customersync.init_runtime_config()
            preview_timeout = site_preview_http_timeout(cfg)
            if mode == "all":
                customers = customersync.get_all_woo_customers(
                    max_customers=40,
                    timeout=preview_timeout,
                )
                mode_label = "همه مشتریان ووکامرس"
            else:
                try:
                    customers = customersync.get_buyers_preview_from_orders(
                        max_orders=50,
                        max_customer_lookups=30,
                        timeout=preview_timeout,
                    )
                    mode_label = "خریداران دارای سفارش (سایت)"
                except Exception as orders_err:
                    if classify_network_error(str(orders_err)) == "forbidden":
                        customers = customersync.get_all_woo_customers(
                            max_customers=40,
                            timeout=preview_timeout,
                        )
                        mode_label = (
                            "مشتریان ثبت‌نام‌شده "
                            "(API سفارشات توسط سرور مسدود است — خریدار مهمان نمایش داده نمی‌شود)"
                        )
                    else:
                        raise

            if not customers:
                return {"items": [f"ℹ️ در حالت «{mode_label}» هیچ مشتری‌ای یافت نشد."], "ids": []}

            items = [f"نمایش بر اساس: {mode_label}"]
            ids = []
            for customer in customers[:40]:
                cid = customer.get("id", "-")
                email = customer.get("email", "-")
                first = customer.get("first_name", "")
                last = customer.get("last_name", "")
                name = (f"{first} {last}").strip() or customer.get("username", "مشتری")
                guest_tag = " (مهمان)" if customer.get("_guest") else ""
                try:
                    ids.append(int(cid))
                except Exception:
                    pass
                items.append(f"{name}{guest_tag} | کد WC: #{cid} | ایمیل: {email}")

            if len(customers) > 40:
                items.append(f"... و {len(customers) - 40} مورد دیگر")

            return {"items": items, "ids": ids}

        except Exception as e:
            cfg = load_secure_config(None) or {}
            raise Exception(format_network_error_message(e, cfg))

    def _apply_site_customers(self, payload, silent=False):
        self.customers_list.clear()
        payload = payload or {}
        ids = set(payload.get("ids", []))

        if self._customers_baseline_ready:
            new_ids = ids - self._seen_customer_ids
            if new_ids:
                newest = max(new_ids)
                count_new = len(new_ids)
                message = f"{count_new} مشتری جدید ثبت شد. آخرین کد مشتری: #{newest}"
                notify_and_log("customers", "مشتری جدید", message)

        self._seen_customer_ids = ids
        self._customers_baseline_ready = True

        for item in payload.get("items", []):
            self.customers_list.addItem(make_rtl_item(item))

        ids = payload.get("ids", [])
        if ids:
            self.set_status("success", f"✅ {len(ids)} مشتری از سایت دریافت شد")
            if not silent:
                log.info(f"📋 بازخوانی مشتریان سایت: {len(ids)} مورد")
        elif payload.get("items"):
            self.set_status("info", str(payload["items"][0])[:120])
            if not silent:
                log.info(f"📋 بازخوانی مشتریان سایت: {payload['items'][0][:120]}")

        self.refresh_logs()

    def _handle_site_customers_error(self, error, silent=False, show_error_dialog=True):
        self.customers_list.clear()
        message = f"❌ خطا در دریافت مشتریان سایت: {error}"
        self.customers_list.addItem(make_rtl_item(message))
        self.set_status("error", message[:120])
        if show_error_dialog:
            QMessageBox.critical(self, "خطا", f"دریافت مشتریان سایت ناموفق بود:\n{error}")
