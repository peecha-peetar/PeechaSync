import os
import time
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QLabel, QListWidget, QPushButton
from PyQt5.QtCore import Qt, QTimer

# مسیر پکیجی برای کلاس والد
from sync_app.core.base_tabs.sync_tab import SyncTab
from sync_app.core.rtl_item_delegate import RightAlignedItemDelegate, make_rtl_item
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.sql_connection_helper import open_sql_connection, format_db_error
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.sync_utils import app_path, clear_filtered_logs, log
from sync_app.core.jalali_log_formatter import format_log_lines_jalali
from sync_app.core.wc_admin_links import make_wc_admin_open_button
from sync_app.core.responsive_action_bar import build_responsive_action_row
from sync_app.core.compact_icon_action_bar import CompactCaptionButton

# اجرای مستقیم اسکریپت ویژگی‌ها
from sync_app.core.scripts import Poshakproperties

PROPERTIES_LOG_MARKER = "[ویژگی‌ها] ───"
PROPERTIES_LOG_TOKENS = (
    "[ویژگی‌ها]",
    "Poshakproperties",
    "همگام‌سازی داینامیک ویژگی",
    "پایان ویژگی‌ها",
    "products/attributes",
    "دریافت attributes",
    "دریافت terms",
    "مقدار اضافه شد",
    "مقدار از قبل موجود",
    "ساخت term",
    "ساخت attribute",
    "ویژگی global",
)


def _filter_properties_log_lines(lines):
    """فقط لاگ‌های مربوط به تب ویژگی‌ها — آخرین جلسه اولویت دارد."""
    if not lines:
        return []
    tokens = [t.lower() for t in PROPERTIES_LOG_TOKENS]
    start = 0
    for i, line in enumerate(lines):
        low = line.lower()
        if PROPERTIES_LOG_MARKER.lower() in low or "[ویژگی‌ها] 🚀" in line:
            start = i
    session = lines[start:]
    matched = [ln for ln in session if any(tok in ln.lower() for tok in tokens)]
    if matched:
        return matched
    return [ln for ln in lines if any(tok in ln.lower() for tok in tokens)]


class PropertiesTab(SyncTab):
    def __init__(self):
        super().__init__("Poshakproperties.py", "ویژگی‌ها")
        self._initial_load_started = False
        self._loading_properties = False
        self._properties_load_generation = 0

    def _tab_log_filters(self):
        return list(PROPERTIES_LOG_TOKENS)

    def init_ui(self):
        super().init_ui()

        self._log_poll_timer = QTimer(self)
        self._log_poll_timer.setInterval(1500)
        self._log_poll_timer.timeout.connect(
            lambda: self.refresh_logs() if self.isVisible() else None
        )
        self._log_poll_timer.start()

        self.properties_preview_label = QLabel("🧩 تعاریف سطح بالای ویژگی‌ها در دژاوو:")
        self.properties_preview_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.properties_preview_label.setLayoutDirection(Qt.RightToLeft)
        self.properties_preview_label.setStyleSheet("font-weight: 700;")

        self.properties_list = QListWidget()
        self.properties_list.setLayoutDirection(Qt.RightToLeft)
        self.properties_list.setMinimumHeight(240)
        self.properties_list.setItemDelegate(RightAlignedItemDelegate(self.properties_list))

        self.properties_refresh_btn = CompactCaptionButton("🔄 بازخوانی تعاریف ویژگی‌ها")
        self.properties_refresh_btn.setToolTip("بازخوانی تعاریف ویژگی‌ها از SQL")
        self.wc_admin_button = make_wc_admin_open_button(
            self, "attributes", button_factory=CompactCaptionButton
        )
        self.wire_refresh_action(
            self.properties_refresh_btn,
            lambda: self.load_properties_preview(manual=True),
            self._stop_properties_load,
            stop_text="⏹ توقف بارگذاری",
        )

        # ترتیب: عنوان، لیست، دکمه‌ها کنار هم
        self.content_layout.insertWidget(1, self.properties_preview_label)
        self.content_layout.insertWidget(2, self.properties_list)
        self.content_layout.setStretchFactor(self.properties_list, 1)

        self.content_layout.addWidget(
            build_responsive_action_row(
                [self.properties_refresh_btn, self.run_button, self.wc_admin_button],
                parent=self,
            )
        )

    def ensure_tab_data_loaded(self):
        from sync_app.core.tab_operation_guard import consume_pending_sql_reload

        consume_pending_sql_reload(self, lambda: self.load_properties_preview(manual=False))

    def _fetch_properties_from_sql(self, cfg):
        conn, _, _ = open_sql_connection(cfg, timeout=3)
        cur = conn.cursor()
        cur.execute("""
            SELECT
                P.ID AS AttrID,
                P.Name AS AttrName,
                C.Name AS TermName
            FROM PoshakProperties AS P
            LEFT JOIN PoshakProperties AS C ON C.ParentID = P.ID
            WHERE P.ParentID = 0
            ORDER BY P.ID, C.ID
        """)
        grouped = {}
        for row in cur.fetchall():
            attr_id = int(row[0] or 0)
            attr_name = str(row[1] or "").strip()
            term_name = str(row[2] or "").strip() if row[2] is not None else ""
            if not attr_name:
                continue
            key = (attr_id, attr_name)
            if key not in grouped:
                grouped[key] = []
            if term_name:
                grouped[key].append(term_name)
        conn.close()
        return grouped

    def load_properties_preview(self, manual=False):
        if self._loading_properties:
            if manual:
                QMessageBox.information(
                    self,
                    "در حال بارگذاری",
                    "بارگذاری تعاریف ویژگی‌ها هنوز تمام نشده.\nچند ثانیه صبر کنید.",
                )
            return

        self._properties_load_generation += 1
        generation = self._properties_load_generation
        self._loading_properties = True
        op_id = self.properties_refresh_btn.property("_action_op_id")
        if op_id:
            self._action_ops.begin(op_id, lock_tabs=False)
        self.properties_list.clear()
        cfg = load_secure_config(None) or {}

        if not (cfg.get("SQL_SERVER") and cfg.get("SQL_DATABASE")) and not cfg.get("SQL_CONN_STRING"):
            self.properties_list.addItem(make_rtl_item("⚠️ تنظیمات SQL ناقص است."))
            self._end_properties_load()
            if manual:
                QMessageBox.warning(self, "خطا", "تنظیمات SQL ناقص است.")
            return

        self.properties_list.addItem(make_rtl_item("⏳ در حال بارگذاری ویژگی‌ها..."))
        self.set_status("loading", "⏳ در حال دریافت تعاریف ویژگی‌ها از SQL...")

        def _worker():
            return self._fetch_properties_from_sql(cfg)

        def _done(grouped):
            if generation != self._properties_load_generation:
                return
            self._apply_properties_grouped(grouped, manual=manual)

        def _fail(error_msg):
            if generation != self._properties_load_generation:
                return
            self._properties_load_failed(error_msg, manual=manual)

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _stop_properties_load(self):
        self._properties_load_generation += 1
        self._loading_properties = False
        self.end_refresh_action(self.properties_refresh_btn)
        self.set_status("warning", "⏹ بارگذاری ویژگی‌ها متوقف شد.")

    def _end_properties_load(self):
        self._loading_properties = False
        self.end_refresh_action(self.properties_refresh_btn)

    def _properties_load_failed(self, error_msg, manual=False):
        self._end_properties_load()
        self.properties_list.clear()
        err = format_db_error(Exception(str(error_msg)))[:300]
        self.properties_list.addItem(make_rtl_item(f"❌ خطا در خواندن ویژگی‌ها: {err}"))
        self.set_status("error", f"❌ خطا در بارگذاری ویژگی‌ها: {err[:120]}")
        if manual:
            QMessageBox.critical(self, "خطای دیتابیس", f"بارگذاری ویژگی‌ها ناموفق بود:\n{err}")

    def _apply_properties_grouped(self, grouped, manual=False):
        self._end_properties_load()
        self.properties_list.clear()
        grouped = grouped or {}

        if not grouped:
            self.properties_list.addItem(make_rtl_item("ℹ️ تعریف سطح بالایی یافت نشد."))
            self.set_status("info", "ℹ️ تعریف ویژگی‌ای در SQL یافت نشد.")
            if manual:
                QMessageBox.information(self, "نتیجه", "تعریف ویژگی‌ای در دیتابیس یافت نشد.")
            return

        for (attr_id, attr_name), terms in grouped.items():
            unique_terms = sorted(set(terms))
            if unique_terms:
                preview = "، ".join(unique_terms[:8])
                suffix = " ..." if len(unique_terms) > 8 else ""
                line = f"#{attr_id} | {attr_name} | {len(unique_terms)} مقدار: {preview}{suffix}"
            else:
                line = f"#{attr_id} | {attr_name} | بدون مقدار فرزند"
            self.properties_list.addItem(make_rtl_item(line))

        count = len(grouped)
        self.set_status("success", f"✅ {count} تعریف ویژگی از SQL بارگذاری شد.")
        if manual:
            QMessageBox.information(
                self,
                "بروزرسانی موفق",
                f"{count} تعریف ویژگی از SQL بارگذاری شد.",
            )

    def run_script(self):
        """همگام‌سازی ویژگی‌ها در پس‌زمینه"""
        from sync_app.core.integrations.commerce_provider import store_platform_label

        platform_label = store_platform_label(load_secure_config(None) or {})
        log.info(f"{PROPERTIES_LOG_MARKER} شروع همگام‌سازی ───")
        self.refresh_logs()
        if not self.run_job_in_background(
            Poshakproperties.main,
            busy_text=f"⏳ در حال همگام‌سازی با {platform_label}...",
            success_message=None,
            loading_status=f"⏳ همگام‌سازی ویژگی‌ها با {platform_label}...",
            live_log_hint=f"⏳ همگام‌سازی ویژگی‌ها با {platform_label}...",
        ):
            return

    def refresh_logs(self):
        """بازخوانی لاگ اختصاصی تب ویژگی‌ها."""
        try:
            log_path = app_path("sync.log")
            if not os.path.exists(log_path):
                self.log_view.setPlainText(
                    "هنوز لاگی ایجاد نشده است.\n"
                    "دکمه «شروع همگام‌سازی ویژگی‌ها» را بزنید."
                )
                return

            with open(log_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()

            filtered = _filter_properties_log_lines(all_lines)
            if filtered:
                body = format_log_lines_jalali(filtered[-60:])
            elif self._log_live_timer.isActive():
                body = format_log_lines_jalali(all_lines[-25:])
            else:
                body = (
                    "لاگ تب ویژگی‌ها خالی است.\n"
                    "دکمه «شروع همگام‌سازی ویژگی‌ها» را بزنید."
                )

            if self._live_log_hint and self._log_live_timer.isActive():
                elapsed = int(time.monotonic() - self._sync_started_at)
                header = f"{self._live_log_hint}\n⏱️ {elapsed} ثانیه\n{'─' * 28}"
                body = f"{header}\n\n{body}" if body.strip() else header

            self.log_view.setPlainText(body)
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum()
            )
        except Exception as exc:
            self.log_view.setPlainText(f"خطا در خواندن لاگ: {exc}")

    def clear_tab_logs(self):
        removed = clear_filtered_logs(list(PROPERTIES_LOG_TOKENS))
        self.refresh_logs()
        self.set_status("info", f"🧹 {removed} خط لاگ ویژگی‌ها پاک شد")

    def _on_bg_sync_done(self, success_message, done_text, result=None):
        self._stop_live_logs()
        if self._action_ops.active == "sync":
            self._action_ops.end()
        self.refresh_logs()

        stats = result if isinstance(result, dict) else {}
        attrs_created = int(stats.get("attrs_created") or 0)
        terms_created = int(stats.get("terms_created") or 0)
        attrs_ok = int(stats.get("attrs_already_ok") or 0)
        errors = stats.get("errors") or []

        if errors:
            self.set_status("warning", "⚠️ همگام‌سازی ویژگی‌ها ناقص بود")
            sample = "؛ ".join(str(x) for x in errors[:3])
            QMessageBox.warning(
                self,
                "همگام‌سازی ناقص",
                f"برخی ویژگی‌ها کامل نشد.\n{sample}",
            )
        elif attrs_created or terms_created:
            self.set_status("success", "✅ ویژگی‌های جدید روی Woo ساخته شد")
            QMessageBox.information(
                self,
                "موفق",
                f"همگام‌سازی ویژگی‌ها انجام شد.\n"
                f"جدید: {attrs_created} ویژگی، {terms_created} term.",
            )
        elif attrs_ok:
            self.set_status("info", "ℹ️ همه ویژگی‌ها از قبل روی Woo بودند")
            QMessageBox.information(
                self,
                "پایان",
                f"ℹ️ {attrs_ok} ویژگی روی Woo بررسی شد؛ چیز جدیدی ساخته نشد.\n"
                "اگر در پنل Woo نمی‌بینید: Products -> Attributes را باز کنید "
                "یا صفحه را رفرش کنید.",
            )
        else:
            self.set_status("success", "✅ عملیات با موفقیت انجام شد")

        QTimer.singleShot(400, self.refresh_logs)
        QTimer.singleShot(600, self.load_properties_preview)

    def _on_bg_sync_error(self, message, done_text):
        super()._on_bg_sync_error(message, done_text)
        QTimer.singleShot(400, self.refresh_logs)
