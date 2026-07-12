# sync_app/core/base_tabs/sync_tab.py

import subprocess
import os
import sys
import time
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit, QHBoxLayout, QSplitter
from PyQt5.QtCore import Qt, QTimer
from sync_app.core.log_panel_ui import LogPanelController, VerticalTextButton, LogActionRail
from sync_app.core.compact_icon_action_bar import CompactCaptionButton
from sync_app.core.sync_job_runner import run_background_sync, cancel_background_sync
from sync_app.core.tab_action_controller import TabActionController, ActionSpec
from sync_app.core.jalali_log_formatter import format_log_lines_jalali
from sync_app.core.sync_utils import clear_filtered_logs, app_path


# ---------------------------------------------------------
# 🔧 تابع مسیر داینامیک برای EXE و حالت سورس
# ---------------------------------------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # حالت EXE
    except Exception:
        # حالت سورس → یک سطح بالاتر از base_tabs
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


# مسیر واحد فایل لاگ — همان مسیری که sync_utils و اسکریپت‌ها می‌نویسند
LOG_FILE_PATH = app_path("sync.log")

TAB_LOG_FILTERS = {
    "سفارشات": ["order", "ordersync", "سفارش", "[orders]"],
    "مشتریان": ["customer", "customersync", "مشتری", "[customers]"],
    "ویژگی‌ها": [
        "[ویژگی‌ها]",
        "Poshakproperties",
        "پایان ویژگی‌ها",
        "همگام‌سازی داینامیک ویژگی",
        "products/attributes",
        "مقدار اضافه شد",
    ],
}


BRAND_COLOR = "#1a2785"


class SyncTab(QWidget):
    def __init__(self, script_name, tab_title):
        super().__init__()
        self.script_name = script_name
        self.tab_title = tab_title
        self.setLayoutDirection(Qt.RightToLeft)
        self.init_ui()

    def init_ui(self):
        root_layout = QHBoxLayout()
        root_layout.setDirection(QHBoxLayout.LeftToRight)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setLayoutDirection(Qt.LeftToRight)
        self.splitter.setHandleWidth(6)

        # پنل لاگ - سمت چپ با استایل ترمینال
        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setReadOnly(True)
        self.log_view.setAlignment(Qt.AlignLeft)
        self.log_view.setMinimumWidth(260)
        self.splitter.addWidget(self.log_view)

        # پنل کنترل - سمت راست
        right_panel = QWidget()
        right_panel.setObjectName("syncRightPanel")
        right_panel.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(right_panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.content_layout = layout

        self.log_actions = LogActionRail(clear_text="حذف لاگ‌های همین تب", parent=self)

        # نشانگر وضعیت
        self.status_label = QLabel("● آماده")
        self.set_status("success", "● آماده")
        layout.addWidget(self.status_label)

        # دکمه شروع همگام‌سازی — در نوار پایین تب قرار می‌گیرد
        self._run_button_idle_text = f"▶  شروع همگام‌سازی {self.tab_title}"
        self.run_button = CompactCaptionButton(self._run_button_idle_text)

        self._sync_stop_style = (
            "QPushButton { background-color: #b91c1c; color: #ffffff; font-weight: bold; border-radius: 6px; }"
            "QPushButton:hover { background-color: #991b1b; }"
        )
        self._action_ops = TabActionController(self)
        self._action_ops.register(
            "sync",
            ActionSpec(
                button=self.run_button,
                idle_text=self._run_button_idle_text,
                stop_style=self._sync_stop_style,
                on_stop=self._stop_background_sync,
            ),
        )
        self.run_button.clicked.connect(self._on_run_button_clicked)

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

        root_layout.addWidget(self.splitter, 1)
        root_layout.addWidget(self.log_actions)

        self.setLayout(root_layout)
        self._live_log_hint = ""
        self._sync_started_at = 0.0
        self._log_live_timer = QTimer(self)
        self._log_live_timer.setInterval(1000)
        self._log_live_timer.timeout.connect(self.refresh_logs)
        self.refresh_logs()

    def _tab_log_filters(self):
        return TAB_LOG_FILTERS.get(self.tab_title, [])

    def _start_live_logs(self, hint=""):
        self._live_log_hint = hint or f"⏳ {self.tab_title} — عملیات شروع شد..."
        self._sync_started_at = time.monotonic()
        try:
            self.log_panel_controller.ensure_visible()
        except Exception:
            pass
        self.refresh_logs()
        self._log_live_timer.start()

    def _stop_live_logs(self):
        self._log_live_timer.stop()
        self._live_log_hint = ""
        self.refresh_logs()

    def set_status(self, level, text):
        self.status_label.setText(text)
        if level == "success":
            self.status_label.setProperty("role", "badge-success")
        elif level == "warning":
            self.status_label.setProperty("role", "badge-warning")
        elif level == "error":
            self.status_label.setProperty("role", "badge-error")
        else:
            self.status_label.setProperty("role", "badge-info")

        # اجبار رندر مجدد استایل بعد از تغییر property
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.update()

    def refresh_logs(self):
        """بازخوانی لاگ‌ها با مدیریت حالت نبود فایل"""
        try:
            if os.path.exists(LOG_FILE_PATH):
                with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                filters = self._tab_log_filters()
                selected_lines = lines
                if filters:
                    selected_lines = [line for line in lines if any(token in line for token in filters)]
                    if not selected_lines and self._log_live_timer.isActive():
                        # حین اجرا: اگر فیلتر تب چیزی نگرفت، آخرین خطوط کلی را نشان بده
                        selected_lines = lines[-30:]

                body = format_log_lines_jalali(selected_lines[-50:])
            else:
                body = "هنوز لاگی ایجاد نشده است.\nبرای ایجاد لاگ، یکی از عملیات‌های همگام‌سازی را اجرا کنید."

            if self._live_log_hint and self._log_live_timer.isActive():
                elapsed = int(time.monotonic() - self._sync_started_at)
                header = f"{self._live_log_hint}\n⏱️ {elapsed} ثانیه\n{'─' * 28}"
                body = f"{header}\n\n{body}" if body.strip() else header

            self.log_view.setPlainText(body)
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
        except Exception as e:
            self.log_view.setPlainText(f"خطا در خواندن لاگ: {e}")

    def run_script(self):
        """این متد توسط کلاس‌های فرزند Override می‌شود"""
        pass

    def _on_run_button_clicked(self):
        self._action_ops.handle_click("sync", self.run_script)

    def wire_refresh_action(self, button, start_fn, stop_fn, *, stop_text=""):
        """ثبت دکمه بازخوانی با قفل متقابل و حالت توقف."""
        op_id = f"refresh_{id(button)}"
        if not (button.toolTip() or "").strip():
            idle = (button.text() or "").strip()
            if idle:
                button.setToolTip(idle)
        self._action_ops.register(
            op_id,
            ActionSpec(
                button=button,
                idle_text=button.text(),
                stop_text=stop_text,
                on_stop=stop_fn,
            ),
        )
        try:
            button.clicked.disconnect()
        except Exception:
            pass
        button.setProperty("_action_op_id", op_id)
        button.clicked.connect(lambda: self._action_ops.handle_click(op_id, start_fn))

    def end_refresh_action(self, button):
        op_id = button.property("_action_op_id")
        if op_id and self._action_ops.active == op_id:
            self._action_ops.end()

    def _stop_background_sync(self):
        if cancel_background_sync(self):
            self._action_ops.set_stopping("sync")
            self.set_status("warning", "⏹ در حال توقف همگام‌سازی...")

    def clear_tab_logs(self):
        removed = clear_filtered_logs(self._tab_log_filters())
        self.refresh_logs()
        self.set_status("info", f"🧹 {removed} خط لاگ از تب {self.tab_title} پاک شد")

    def run_job_in_background(
        self,
        job_callable,
        *,
        busy_text="⏳ در حال اجرا...",
        done_text=None,
        success_message=None,
        need_sql=True,
        need_wc=True,
        loading_status=None,
        live_log_hint=None,
    ):
        """اجرای sync در پس‌زمینه با مدیریت دکمه و وضعیت."""
        if done_text is None:
            done_text = self.run_button.text()

        if self._action_ops.busy and self._action_ops.active != "sync":
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "در حال اجرا", "یک عملیات دیگر در این تب در جریان است.")
            return False

        if not run_background_sync(
            self,
            job_callable,
            on_success=lambda result: self._on_bg_sync_done(success_message, done_text, result),
            on_error=lambda msg: self._on_bg_sync_error(msg, done_text),
            need_sql=need_sql,
            need_wc=need_wc,
        ):
            thread = getattr(self, "_peecha_bg_sync_thread", None)
            if thread is not None and thread.isRunning():
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(self, "در حال اجرا", "یک عملیات همگام‌سازی دیگر هنوز در جریان است.")
            return False

        self._action_ops.begin("sync", working_text=busy_text)
        self.set_status("warning", loading_status or "⏳ همگام‌سازی در پس‌زمینه...")
        self._start_live_logs(live_log_hint)

        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
        return True

    def _on_bg_sync_done(self, success_message, done_text, result=None):
        self._stop_live_logs()
        if self._action_ops.active == "sync":
            self._action_ops.end()
        self.set_status("success", "✅ عملیات با موفقیت انجام شد")
        self.refresh_logs()
        if success_message:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, "موفق", success_message)

    def _on_bg_sync_error(self, message, done_text):
        self._stop_live_logs()
        if self._action_ops.active == "sync":
            self._action_ops.end()
        if "متوقف" in (message or ""):
            self.set_status("info", "⏹ عملیات متوقف شد")
        else:
            self.set_status("error", "❌ خطا در اجرا")
        self.refresh_logs()
        from PyQt5.QtWidgets import QMessageBox
        if "متوقف" in (message or ""):
            QMessageBox.information(self, "توقف", "همگام‌سازی متوقف شد.")
        else:
            QMessageBox.critical(self, "خطا", message)
