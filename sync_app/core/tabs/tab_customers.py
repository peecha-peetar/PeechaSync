import sys
import os
import time
from PyQt5.QtWidgets import (
    QMessageBox, QLabel, QListWidget, QPushButton, QListWidgetItem, QWidget,
    QLineEdit, QHBoxLayout, QVBoxLayout, QDialog, QComboBox, QTextEdit, QDialogButtonBox,
)
from sync_app.core.rtl_item_delegate import RightAlignedCheckableItemDelegate, make_rtl_item
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
from sync_app.core.selection_toggle_bar import attach_selection_toggle

# import customersync
from sync_app.core.scripts import customersync

# قالب‌هایِ آماده‌ی پیامکِ تبلیغاتی — مستقل از تقویمِ محتوایی (که برایِ
# پست‌هایِ محصولِ شبکه‌هایِ اجتماعیه، نه پیامک به مشتری).
SMS_TEMPLATES = [
    ("متنِ آزاد", ""),
    (
        "تخفیفِ ویژه",
        "🎉 تخفیفِ ویژه برایِ شما فعال شد! همین امروز از فروشگاهِ ما خرید کنید.\nلغوِ عضویت: reply STOP",
    ),
    (
        "محصولِ جدید",
        "📦 محصولاتِ جدید به فروشگاهِ ما اضافه شد — سری بزنید و ببینید چه چیزهایی منتظرتونه!\nلغوِ عضویت: reply STOP",
    ),
    (
        "یادآوریِ سبدِ خرید",
        "🛒 سبدِ خریدتون تویِ فروشگاهِ ما منتظرتونه — تکمیلش کنید تا از دستش ندید.\nلغوِ عضویت: reply STOP",
    ),
]


class CustomerTab(SitePreviewLoaderMixin, SyncTab):
    def __init__(self):
        super().__init__("customersync.py", "مشتریان")
        self._last_customers_refresh_at = 0.0
        self._seen_customer_ids = set()
        self._customers_baseline_ready = False
        self._initial_load_started = False
        self._customer_records: list[dict] = []
        self._customer_info_lines: list = []
        self._checked_customer_keys: set = set()

        self.customers_preview_label = QLabel("👥 مشتریان اخیر سایت:")
        self.customers_preview_label.setStyleSheet("font-weight: bold;")

        customer_search_row = QHBoxLayout()
        self.customer_search_input = QLineEdit()
        self.customer_search_input.setPlaceholderText("🔍 جستجو در نام، ایمیل یا موبایل...")
        self.customer_search_input.setLayoutDirection(Qt.RightToLeft)
        self.customer_search_input.setMinimumHeight(36)
        self.customer_search_input.textChanged.connect(lambda _=None: self._render_customers_list())
        customer_search_row.addWidget(self.customer_search_input, 1)
        self._customer_selection_toggle = attach_selection_toggle(
            customer_search_row,
            self,
            on_select_all=lambda: self._set_all_customers_checked(True),
            on_select_none=lambda: self._set_all_customers_checked(False),
        )
        self.customer_search_row_widget = QWidget()
        self.customer_search_row_widget.setLayout(customer_search_row)

        self.customers_list = QListWidget()
        self.customers_list.setLayoutDirection(Qt.RightToLeft)
        self.customers_list.setMinimumHeight(240)
        self.customers_list.setItemDelegate(RightAlignedCheckableItemDelegate(self.customers_list))
        self.customers_list.itemChanged.connect(self._on_customer_item_changed)
        self.customers_refresh_button = CompactCaptionButton("🔄 بازخوانی مشتریان سایت")
        self.wc_admin_button = make_wc_admin_open_button(
            self, "customers", button_factory=CompactCaptionButton
        )
        self.customers_sms_button = CompactCaptionButton("📱 پیامکِ گروهی به انتخاب‌شده‌ها")
        self.customers_sms_button.clicked.connect(self._open_bulk_sms_dialog)

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
        self.content_layout.insertWidget(4, self.customer_search_row_widget)
        self.content_layout.insertWidget(5, self.customers_list)
        self.content_layout.setStretchFactor(self.customers_list, 1)

        self.content_layout.addWidget(
            build_responsive_action_row(
                [self.customers_refresh_button, self.run_button, self.wc_admin_button, self.customers_sms_button],
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
            from sync_app.core.integrations.commerce_provider import store_platform_label

            cfg = load_secure_config(None) or {}
            platform_label = store_platform_label(cfg)
            mode = get_customer_mode(cfg)
            if mode == "fixed":
                from sync_app.core.integrations.erp_provider import erp_provider_label

                code = (cfg.get("DEFAULT_CUSTOMER_CODE") or "00005").strip()
                return {
                    "items": [f"حالت مشتری ثابت فعال است — کد {erp_provider_label(cfg)}: {code}"],
                    "ids": [], "records": [],
                }

            customersync.init_runtime_config()
            preview_timeout = site_preview_http_timeout(cfg)
            if mode == "all":
                customers = customersync.get_all_woo_customers(
                    max_customers=40,
                    timeout=preview_timeout,
                )
                mode_label = f"همه مشتریان {platform_label}"
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
                return {
                    "items": [f"ℹ️ در حالت «{mode_label}» هیچ مشتری‌ای یافت نشد."],
                    "ids": [], "records": [],
                }

            items = [f"نمایش بر اساس: {mode_label}"]
            ids = []
            records = []
            for customer in customers[:40]:
                cid = customer.get("id", "-")
                email = customer.get("email", "-")
                first = customer.get("first_name", "")
                last = customer.get("last_name", "")
                name = (f"{first} {last}").strip() or customer.get("username", "مشتری")
                guest_tag = " (مهمان)" if customer.get("_guest") else ""
                phone = str((customer.get("billing") or {}).get("phone") or "").strip()
                try:
                    ids.append(int(cid))
                except Exception:
                    pass
                display = f"{name}{guest_tag} | کد: #{cid} | ایمیل: {email}"
                items.append(display)
                records.append({
                    "id": cid, "name": name, "email": email, "phone": phone,
                    "guest": bool(customer.get("_guest")), "display": display,
                })

            if len(customers) > 40:
                items.append(f"... و {len(customers) - 40} مورد دیگر")

            return {"items": items, "ids": ids, "records": records}

        except Exception as e:
            cfg = load_secure_config(None) or {}
            raise Exception(format_network_error_message(e, cfg))

    def _apply_site_customers(self, payload, silent=False):
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

        records = payload.get("records") or []
        items = payload.get("items") or []
        self._customer_records = records
        # وقتی رکورد داریم، فقط خطِ اولِ items (توضیحِ حالت) به‌عنوانِ خطِ
        # اطلاعاتی بالایِ لیست می‌مونه — بقیه‌ی خط‌ها تکرارِ همون رکوردهاست
        # که حالا با آیتمِ قابلِ‌تیک‌زدن از self._customer_records ساخته می‌شن.
        self._customer_info_lines = items if not records else (items[:1] if items else [])
        self._render_customers_list()

        ids = payload.get("ids", [])
        if ids:
            self.set_status("success", f"✅ {len(ids)} مشتری از سایت دریافت شد")
            if not silent:
                log.info(f"📋 بازخوانی مشتریان سایت: {len(ids)} مورد")
        elif items:
            self.set_status("info", str(items[0])[:120])
            if not silent:
                log.info(f"📋 بازخوانی مشتریان سایت: {items[0][:120]}")

        self.refresh_logs()

    def _handle_site_customers_error(self, error, silent=False, show_error_dialog=True):
        self._customer_records = []
        message = f"❌ خطا در دریافت مشتریان سایت: {error}"
        self._customer_info_lines = [message]
        self._render_customers_list()
        self.set_status("error", message[:120])
        if show_error_dialog:
            QMessageBox.critical(self, "خطا", f"دریافت مشتریان سایت ناموفق بود:\n{error}")

    def _customer_key(self, record: dict) -> str:
        cid = record.get("id")
        if cid:
            return f"id:{cid}"
        return f"g:{record.get('email') or record.get('phone') or record.get('name') or ''}"

    def _render_customers_list(self):
        self.customers_list.blockSignals(True)
        try:
            self.customers_list.clear()
            for text in getattr(self, "_customer_info_lines", []):
                self.customers_list.addItem(make_rtl_item(text))

            search = (self.customer_search_input.text() or "").strip().lower()
            shown = 0
            for record in self._customer_records:
                haystack = f"{record.get('name', '')} {record.get('email', '')} {record.get('phone', '')}".lower()
                if search and search not in haystack:
                    continue
                item = make_rtl_item(record.get("display") or record.get("name") or "")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                key = self._customer_key(record)
                item.setCheckState(Qt.Checked if key in self._checked_customer_keys else Qt.Unchecked)
                item.setData(Qt.UserRole, record)
                self.customers_list.addItem(item)
                shown += 1

            if search and self._customer_records and shown == 0:
                self.customers_list.addItem(make_rtl_item("چیزی با این جستجو پیدا نشد."))
        finally:
            self.customers_list.blockSignals(False)

    def _on_customer_item_changed(self, item):
        record = item.data(Qt.UserRole)
        if not isinstance(record, dict):
            return
        key = self._customer_key(record)
        if item.checkState() == Qt.Checked:
            self._checked_customer_keys.add(key)
        else:
            self._checked_customer_keys.discard(key)

    def _set_all_customers_checked(self, checked: bool):
        self.customers_list.blockSignals(True)
        try:
            for i in range(self.customers_list.count()):
                item = self.customers_list.item(i)
                record = item.data(Qt.UserRole)
                if not isinstance(record, dict):
                    continue
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                key = self._customer_key(record)
                if checked:
                    self._checked_customer_keys.add(key)
                else:
                    self._checked_customer_keys.discard(key)
        finally:
            self.customers_list.blockSignals(False)

    def _selected_customer_records(self) -> list:
        keys = self._checked_customer_keys
        return [r for r in self._customer_records if self._customer_key(r) in keys]

    def _open_bulk_sms_dialog(self):
        from sync_app.core.sms_poster import is_configured as sms_is_configured

        cfg = load_secure_config(None) or {}
        if not sms_is_configured(cfg):
            QMessageBox.warning(
                self, "پیامک",
                "اول باید یوزرنیم/پسوردِ پیامک را در تنظیمات → «اعلان‌ها و هوش مصنوعی» وارد کنید.",
            )
            return

        selected = self._selected_customer_records()
        if not selected:
            QMessageBox.warning(
                self, "پیامک", "هیچ مشتری‌ای از لیست انتخاب نشده — تیک بزنید و دوباره امتحان کنید."
            )
            return

        with_phone = [r for r in selected if (r.get("phone") or "").strip()]
        without_phone = len(selected) - len(with_phone)
        if not with_phone:
            QMessageBox.warning(
                self, "پیامک", "هیچ‌کدام از مشتریانِ انتخاب‌شده شماره‌ی موبایلِ ثبت‌شده ندارند."
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("ارسالِ پیامکِ گروهی")
        dlg.setLayoutDirection(Qt.RightToLeft)
        dlg.resize(460, 420)
        layout = QVBoxLayout(dlg)

        info_text = f"📨 گیرنده: {len(with_phone)} نفر"
        if without_phone:
            info_text += f" — {without_phone} نفرِ دیگر بدونِ شماره‌ی موبایل نادیده گرفته می‌شن"
        info = QLabel(info_text)
        info.setWordWrap(True)
        layout.addWidget(info)

        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("قالبِ آماده:"))
        template_combo = QComboBox()
        for label, _text in SMS_TEMPLATES:
            template_combo.addItem(label)
        template_row.addWidget(template_combo, 1)
        layout.addLayout(template_row)

        text_edit = QTextEdit()
        text_edit.setPlaceholderText("متنِ پیامک را اینجا بنویسید یا از قالبِ بالا انتخاب کنید...")
        layout.addWidget(text_edit, 1)

        char_count_label = QLabel("۰ کاراکتر")
        char_count_label.setStyleSheet("color:#64748b; font-size:10px;")
        layout.addWidget(char_count_label)

        def _update_char_count():
            n = len(text_edit.toPlainText())
            parts = max(1, -(-n // 70)) if n else 0
            char_count_label.setText(f"{n} کاراکتر (~{parts} پیامک)")

        text_edit.textChanged.connect(_update_char_count)

        def _apply_template(idx):
            text = SMS_TEMPLATES[idx][1] if 0 <= idx < len(SMS_TEMPLATES) else ""
            if text:
                text_edit.setPlainText(text)

        template_combo.currentIndexChanged.connect(_apply_template)
        _update_char_count()

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Cancel).setText("انصراف")
        send_btn = buttons.addButton("📤 ارسال", QDialogButtonBox.AcceptRole)
        layout.addWidget(buttons)
        buttons.rejected.connect(dlg.reject)

        def _do_send():
            text = text_edit.toPlainText().strip()
            if not text:
                QMessageBox.warning(dlg, "پیامک", "متنِ پیامک خالی است.")
                return
            answer = QMessageBox.question(
                dlg, "تأییدِ ارسال",
                f"این پیامک به {len(with_phone)} شماره ارسال می‌شود و هزینه دارد. مطمئنید؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

            phones = [r["phone"] for r in with_phone]
            send_btn.setEnabled(False)
            send_btn.setText("در حال ارسال...")

            from sync_app.core.threading_helper import run_in_thread
            from sync_app.core.sms_poster import send_sms as sms_send

            def on_complete(result):
                ok, msg = result
                send_btn.setEnabled(True)
                send_btn.setText("📤 ارسال")
                if ok:
                    QMessageBox.information(dlg, "پیامک", f"ارسال شد.\n\n{msg}")
                    dlg.accept()
                else:
                    QMessageBox.critical(dlg, "پیامک", f"ارسال ناموفق بود:\n\n{msg}")

            def on_error(err):
                send_btn.setEnabled(True)
                send_btn.setText("📤 ارسال")
                QMessageBox.critical(dlg, "پیامک", f"خطا: {err}")

            run_in_thread(sms_send, cfg, phones, text, on_complete=on_complete, on_error=on_error)

        send_btn.clicked.connect(_do_send)
        dlg.exec_()
