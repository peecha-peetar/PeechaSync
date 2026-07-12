""" پیش‌نمایش ووکامرس """

from __future__ import annotations

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.rtl_item_delegate import make_rtl_item
from sync_app.core.tab_action_controller import make_stop_text


def site_preview_http_timeout(cfg) -> int:
    """مهلت کوتاه برای پیش‌نمایش تب — جدا از WC_TIMEOUT همگام‌سازی."""
    try:
        from sync_app.core.wc_sync_helper import wc_timeout_pair

        _connect, read = wc_timeout_pair(cfg or {})
        return min(int(read or 20), 20)
    except Exception:
        return 18


class SitePreviewLoaderMixin:
    """ mixin تب مشتری/سفارش برای fetch از سایت """

    def _init_site_preview_loader(
        self,
        *,
        entity_label: str,
        list_widget,
        refresh_button,
        run_button,
        content_layout,
        insert_at: int = 1,
        auto_fetch_config_key: str = "",
        manual_refresh_callable=None,
    ):
        self._site_entity_label = entity_label
        self._site_auto_config_key = auto_fetch_config_key or f"AUTO_PREVIEW_{entity_label}"
        self._site_list = list_widget
        self._site_refresh_btn = refresh_button
        self._site_run_btn = run_button
        self._site_fetch_generation = 0
        self._site_fetch_started_at = 0.0
        self._site_fetch_in_flight = False
        self._site_fetch_silent = False

        self._site_fetch_panel = QWidget()
        panel_layout = QVBoxLayout(self._site_fetch_panel)
        panel_layout.setContentsMargins(0, 0, 0, 4)
        panel_layout.setSpacing(4)

        self._site_progress_bar = QProgressBar()
        self._site_progress_bar.setRange(0, 0)
        self._site_progress_bar.setTextVisible(False)
        self._site_progress_bar.setFixedHeight(8)
        self._site_progress_bar.setObjectName("siteFetchProgress")

        hint_row = QHBoxLayout()
        hint_row.setSpacing(8)
        self._site_fetch_hint = QLabel("")
        self._site_fetch_hint.setObjectName("siteFetchHint")
        self._site_fetch_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._site_stop_button = QPushButton("⏹ توقف دریافت")
        self._site_stop_button.setObjectName("siteFetchStop")
        self._site_stop_button.setMinimumHeight(34)
        self._site_stop_button.setCursor(Qt.PointingHandCursor)
        self._site_stop_button.clicked.connect(self._cancel_site_fetch)
        hint_row.addWidget(self._site_fetch_hint, 1)
        hint_row.addWidget(self._site_stop_button, 0)

        panel_layout.addWidget(self._site_progress_bar)
        panel_layout.addLayout(hint_row)
        self._site_fetch_panel.setVisible(False)
        content_layout.insertWidget(insert_at, self._site_fetch_panel)

        # تیک دریافت خودکار
        self._site_auto_fetch_checkbox = QCheckBox(f"دریافت خودکار {entity_label} از سایت")
        self._site_auto_fetch_checkbox.setObjectName("siteAutoFetchCheckbox")
        self._site_auto_fetch_checkbox.setLayoutDirection(Qt.RightToLeft)
        self._site_auto_fetch_checkbox.setChecked(self._load_site_auto_fetch_enabled())
        self._site_auto_fetch_checkbox.toggled.connect(self._on_site_auto_fetch_toggled)
        auto_row = QWidget()
        auto_row_layout = QHBoxLayout(auto_row)
        auto_row_layout.setContentsMargins(0, 0, 0, 0)
        auto_row_layout.addStretch(1)
        auto_row_layout.addWidget(self._site_auto_fetch_checkbox, 0)
        content_layout.insertWidget(insert_at + 1, auto_row)

        self._site_elapsed_timer = QTimer(self)
        self._site_elapsed_timer.setInterval(400)
        self._site_elapsed_timer.timeout.connect(self._tick_site_fetch_status)

        self._site_dots_timer = QTimer(self)
        self._site_dots_timer.setInterval(450)
        self._site_dots_phase = 0
        self._site_dots_timer.timeout.connect(self._tick_site_fetch_dots)

        self._site_refresh_idle_text = refresh_button.text()
        self._site_manual_refresh_callable = manual_refresh_callable

        def _start_manual_refresh():
            fn = getattr(self, "_site_manual_refresh_callable", None)
            if callable(fn):
                fn()

        if hasattr(self, "wire_refresh_action"):
            self.wire_refresh_action(
                refresh_button,
                _start_manual_refresh,
                self._cancel_site_fetch,
            )
        elif manual_refresh_callable is not None:
            try:
                refresh_button.clicked.disconnect()
            except Exception:
                pass
            refresh_button.clicked.connect(_start_manual_refresh)

    def _load_site_auto_fetch_enabled(self) -> bool:
        try:
            from sync_app.core.secure_config_loader import load_secure_config
            cfg = load_secure_config(None) or {}
            return bool(cfg.get(self._site_auto_config_key, False))
        except Exception:
            return False

    def _wc_badge_allows_fetch(self) -> bool:
        from sync_app.core.connectivity_guard import find_peecha_launcher

        launcher = find_peecha_launcher(self)
        if launcher is None:
            return True
        return launcher.wc_connectivity_state() == "online"

    def _wc_badge_state(self) -> str:
        from sync_app.core.connectivity_guard import find_peecha_launcher

        launcher = find_peecha_launcher(self)
        if launcher is None:
            return "unknown"
        return launcher.wc_connectivity_state()

    def _show_wc_not_ready_message(self):
        state = self._wc_badge_state()
        if state == "pending":
            msg = (
                "⏳ وضعیت ووکامرس هنوز مشخص نشده — "
                "چند ثانیه صبر کنید یا دکمه «بازخوانی» را بزنید."
            )
        else:
            msg = (
                "⚠️ ووکامرس آفلاین است — اتصال را در هدر برنامه برقرار کنید "
                "سپس «بازخوانی» را بزنید."
            )
        self._site_list.clear()
        self._site_list.addItem(make_rtl_item(msg))
        self.set_status("warning", msg[:120])

    def _is_site_auto_fetch_enabled(self) -> bool:
        return self._site_auto_fetch_checkbox.isChecked()

    def _on_site_auto_fetch_toggled(self, checked: bool):
        try:
            from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
            cfg = load_secure_config(None) or {}
            cfg[self._site_auto_config_key] = bool(checked)
            save_secure_config(cfg)
        except Exception:
            pass

        if not checked:
            if self._site_fetch_in_flight and self._site_fetch_silent:
                self._cancel_site_fetch()
            elif not self._site_fetch_in_flight:
                self.set_status("info", f"دریافت خودکار {self._site_entity_label} غیرفعال است")

    def _begin_site_fetch(self, silent: bool = False):
        self._site_fetch_silent = bool(silent)
        self._site_fetch_in_flight = True
        self._site_fetch_started_at = time.monotonic()

        op_id = self._site_refresh_btn.property("_action_op_id")
        if not silent:
            if op_id and hasattr(self, "_action_ops"):
                if not self._action_ops.busy:
                    self._action_ops.begin(
                        op_id,
                        working_text=make_stop_text(self._site_refresh_idle_text),
                    )
            else:
                self._site_refresh_btn.setEnabled(True)
                self._site_refresh_btn.setText(make_stop_text(self._site_refresh_idle_text))
            self._site_run_btn.setEnabled(False)
            self._site_fetch_panel.setVisible(True)
            self._site_stop_button.setEnabled(True)
            self._site_stop_button.setVisible(True)
            self._site_list.clear()
            self._site_list.addItem(make_rtl_item("⏳ در حال اتصال به سایت و دریافت اطلاعات..."))
            self.set_status("warning", f"⏳ در حال دریافت {self._site_entity_label} از سایت...")
        else:
            self._site_refresh_btn.setEnabled(False)
            self.set_status("warning", f"🔄 بروزرسانی خودکار {self._site_entity_label}...")

        self._site_dots_phase = 0
        self._site_elapsed_timer.start()
        self._site_dots_timer.start()
        self._tick_site_fetch_status()

    def _end_site_fetch(self, *, cancelled: bool = False):
        self._site_fetch_in_flight = False
        self._site_elapsed_timer.stop()
        self._site_dots_timer.stop()
        self._site_fetch_panel.setVisible(False)
        op_id = self._site_refresh_btn.property("_action_op_id")
        if op_id and hasattr(self, "end_refresh_action"):
            self.end_refresh_action(self._site_refresh_btn)
        else:
            self._site_refresh_btn.setEnabled(True)
            self._site_refresh_btn.setText(self._site_refresh_idle_text)
        self._site_run_btn.setEnabled(True)
        self._site_stop_button.setEnabled(True)
        if cancelled:
            self._site_list.clear()
            self._site_list.addItem(make_rtl_item("⏹ دریافت اطلاعات متوقف شد."))

    def _cancel_site_fetch(self):
        if not self._site_fetch_in_flight:
            return
        self._site_fetch_generation += 1
        self._end_site_fetch(cancelled=True)
        self.set_status("info", f"⏹ دریافت {self._site_entity_label} از سایت متوقف شد.")

    def _is_site_fetch_current(self, generation: int) -> bool:
        return generation == self._site_fetch_generation

    def _next_site_fetch_generation(self) -> int:
        self._site_fetch_generation += 1
        return self._site_fetch_generation

    def _tick_site_fetch_status(self):
        if not self._site_fetch_in_flight:
            return
        elapsed = int(time.monotonic() - self._site_fetch_started_at)
        dots = "." * ((self._site_dots_phase % 3) + 1)
        hint = f"در حال دریافت {self._site_entity_label} از سایت{dots}  ({elapsed} ثانیه)"
        self._site_fetch_hint.setText(hint)
        if not self._site_fetch_silent:
            self.set_status("warning", f"⏳ {hint}")

    def _tick_site_fetch_dots(self):
        if not self._site_fetch_in_flight:
            return
        self._site_dots_phase += 1
        self._tick_site_fetch_status()

    def _wrap_site_fetch_callbacks(self, generation: int, on_complete, on_error):
        def complete(payload):
            if not self._is_site_fetch_current(generation):
                return
            self._end_site_fetch()
            on_complete(payload)

        def error(msg):
            if not self._is_site_fetch_current(generation):
                return
            self._end_site_fetch()
            on_error(msg)

        return complete, error
