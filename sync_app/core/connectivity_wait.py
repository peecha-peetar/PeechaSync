"""منتظر ماندن برای اتصال — دیالوگ UI و حلقه worker."""

from __future__ import annotations

import html
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QEvent
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.app_theme import (
    build_connectivity_wait_stylesheet,
    get_active_theme_palette,
    resolve_user_font_pref,
)
from sync_app.core.connectivity_guard import find_peecha_launcher
from sync_app.core.message_boxes_fa import set_rtl_label_text
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.sync_cancel import check_cancelled


_UI_POLL_MS = 2000
_LOG_ACTIVITY_SEC = 5.0
_BADGE_HEIGHT = 46
WORKER_POLL_SEC = 2.5
_MAX_LOG_LINES = 48
_NUDGE_HEADER_SEC = 10.0
_ACTIVITY_PHRASES = (
    "در حال جستجوی راه اتصال",
    "بررسی مجدد وضعیت شبکه",
    "خواندن نتیجه از badge هدر",
    "منتظر پاسخ سرویس",
    "همچنان در تلاش برای اتصال",
)


def connectivity_ready(launcher, *, need_sql=True, need_wc=False) -> bool:
    if launcher is None:
        return True
    if need_sql and launcher.sql_connectivity_state() != "online":
        return False
    if need_wc and launcher.wc_connectivity_state() != "online":
        return False
    return True


def offline_labels(launcher, *, need_sql=True, need_wc=False) -> list[str]:
    names = []
    if launcher is None:
        return names
    if need_sql and launcher.sql_connectivity_state() != "online":
        names.append("SQL")
    if need_wc and launcher.wc_connectivity_state() != "online":
        names.append("WooCommerce")
    return names


def is_transient_connectivity_issue(err_text: str) -> bool:
    from sync_app.core.connectivity_service import classify_network_error

    text = (err_text or "").lower()
    if any(
        token in text
        for token in (
            "incorrect_password",
            "invalid_username",
            "application password",
            "احراز هویت",
            "forbidden",
            "rest_cannot",
        )
    ):
        return False
    if "اتصال قطع" in text or "connection refused" in text or "connection reset" in text:
        return True
    cat = classify_network_error(text)
    return cat in ("dns", "timeout", "refused", "ssl")


class ConnectivityWaitDialog(QDialog):
    """منتظر آنلاین شدن — وضعیت از همان badge هدر خوانده می‌شود."""

    def __init__(self, parent, *, need_sql=True, need_wc=False, operation_label=""):
        super().__init__(parent)
        self._need_sql = need_sql
        self._need_wc = need_wc
        self._operation_label = (operation_label or "").strip()
        self._log_lines: list[tuple[str, str, str]] = []
        self._last_log_key = ""
        self._poll_count = 0
        self._last_nudge_mono = 0.0
        self._last_activity_log_mono = 0.0
        self._log_pinned = False

        self.setWindowTitle("منتظر اتصال")
        self.setObjectName("connectivityWaitDialog")
        cfg = load_secure_config(None) or {}
        _, palette = get_active_theme_palette()
        font_size, is_bold = resolve_user_font_pref(cfg.get("APP_FONT_SIZE", 14))
        self.setStyleSheet(build_connectivity_wait_stylesheet(palette, font_size, is_bold))
        self.setModal(True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(780, 430)

        self._build_ui()
        self._pulse_anim = self._make_pulse(self._pulse_dot)
        self._append_log("پایش اتصال شروع شد — از وضعیت هدر برنامه می‌خوانیم.", "info")
        self._append_log("برنامه در پس‌زمینه اتصال را چک می‌کند.", "wait")

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(_UI_POLL_MS)
        self._tick()

    def _build_ui(self):
        card = QFrame(self)
        card.setObjectName("waitCard")

        split = QWidget()
        split.setLayoutDirection(Qt.LeftToRight)
        split_layout = QHBoxLayout(split)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(14)

        log_panel = QFrame()
        log_panel.setObjectName("waitLogPanel")
        log_panel.setFixedWidth(248)
        self._log_panel = log_panel
        log_panel.installEventFilter(self)
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(12, 12, 12, 10)
        log_layout.setSpacing(6)
        log_title = QLabel()
        log_title.setObjectName("waitLogTitle")
        set_rtl_label_text(log_title, "لاگ لحظه‌ای")
        self._log_view = QTextEdit()
        self._log_view.setObjectName("waitLog")
        self._log_view.setReadOnly(True)
        self._log_view.setLayoutDirection(Qt.LeftToRight)
        self._log_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._log_view.installEventFilter(self)
        self._log_view.viewport().installEventFilter(self)
        log_layout.addWidget(log_title)
        log_layout.addWidget(self._log_view, 1)

        content = QWidget()
        content.setLayoutDirection(Qt.RightToLeft)
        inner = QVBoxLayout(content)
        inner.setContentsMargins(4, 4, 8, 4)
        inner.setSpacing(12)

        title = QLabel()
        title.setObjectName("waitTitle")
        self._set_rtl_text(title, "◆ منتظر اتصال")

        title_rule = QFrame()
        title_rule.setObjectName("waitTitleRule")
        title_rule.setFrameShape(QFrame.HLine)

        self._subtitle = QLabel()
        self._subtitle.setObjectName("waitSubtitle")
        self._set_rtl_text(
            self._subtitle,
            self._operation_label or "عملیات در صف اجرا",
        )

        badge_caption = QLabel()
        badge_caption.setObjectName("waitBadgeCaption")
        self._set_rtl_text(badge_caption, "وضعیت لحظه‌ای — همان دکمه بالای برنامه")

        badges_row = QHBoxLayout()
        badges_row.setSpacing(12)
        badges_row.addStretch(1)
        self._sql_badge = None
        self._wc_badge = None
        if self._need_sql:
            self._sql_badge = self._make_badge_label()
            badges_row.addWidget(self._sql_badge)
        if self._need_wc:
            self._wc_badge = self._make_badge_label()
            badges_row.addWidget(self._wc_badge)
        badges_row.addStretch(1)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._pulse_dot = QLabel("●")
        self._pulse_dot.setObjectName("waitPulseDot")
        self._pulse_dot.setAlignment(Qt.AlignCenter)
        self._status_line = QLabel()
        self._status_line.setObjectName("waitStatusLine")
        self._set_rtl_text(self._status_line, "در حال بررسی...")
        status_row.addWidget(self._pulse_dot, 0, Qt.AlignRight | Qt.AlignTop)
        status_row.addWidget(self._status_line, 1)

        self._hint = QLabel()
        self._hint.setObjectName("waitHint")
        self._set_rtl_text(
            self._hint,
            "اتصال را برقرار کنید — به محض آنلاین شدن، کار خودکار ادامه می‌یابد.\n"
            "برای تنظیمات روی همان دکمه در بالای صفحه کلیک کنید.",
            multiline=True,
        )

        stop_btn = QPushButton("توقف")
        stop_btn.setObjectName("waitStopBtn")
        stop_btn.setCursor(Qt.PointingHandCursor)
        stop_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(stop_btn, 0, Qt.AlignCenter)
        btn_row.addStretch(1)

        inner.addWidget(title)
        inner.addWidget(title_rule)
        inner.addWidget(self._subtitle)
        inner.addSpacing(2)
        inner.addWidget(badge_caption)
        inner.addLayout(badges_row)
        inner.addSpacing(6)
        inner.addLayout(status_row)
        inner.addWidget(self._hint)
        inner.addSpacing(4)
        inner.addLayout(btn_row)

        split_layout.addWidget(log_panel, 0)
        split_layout.addWidget(content, 1)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 16)
        card_layout.addWidget(split)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(card)

    def eventFilter(self, obj, event):
        log_panel = getattr(self, "_log_panel", None)
        log_view = getattr(self, "_log_view", None)
        hover_targets = {log_panel, log_view}
        if log_view is not None:
            hover_targets.add(log_view.viewport())

        if obj in hover_targets:
            if event.type() == QEvent.Enter:
                self._log_pinned = True
            elif event.type() == QEvent.Leave:
                QTimer.singleShot(0, self._maybe_unpin_log)
        return super().eventFilter(obj, event)

    def _maybe_unpin_log(self) -> None:
        log_panel = getattr(self, "_log_panel", None)
        log_view = getattr(self, "_log_view", None)
        if log_panel is not None and log_panel.underMouse():
            return
        if log_view is not None and (
            log_view.underMouse() or log_view.viewport().underMouse()
        ):
            return
        if not self._log_pinned:
            return
        self._log_pinned = False
        self._scroll_log_to_end()

    def _scroll_log_to_end(self) -> None:
        bar = self._log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_rtl_text(self, label: QLabel, text: str, *, multiline: bool = False) -> None:
        set_rtl_label_text(label, text, multiline=multiline)

    def _append_log(self, text: str, level: str = "info") -> None:
        colors = {
            "info": "#86efac",
            "wait": "#93c5fd",
            "warn": "#fcd34d",
            "ok": "#4ade80",
        }
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_lines.append((ts, text, colors.get(level, colors["info"])))
        if len(self._log_lines) > _MAX_LOG_LINES:
            self._log_lines = self._log_lines[-_MAX_LOG_LINES:]
        parts = []
        for line_ts, line_text, color in self._log_lines:
            safe = html.escape(line_text)
            parts.append(
                f'<div style="color:{color}; margin: 3px 0; line-height: 1.35;">'
                f'<span style="color:#64748b;">[{line_ts}]</span> {safe}</div>'
            )
        bar = self._log_view.verticalScrollBar()
        pinned_scroll = bar.value() if self._log_pinned else None
        self._log_view.setHtml("".join(parts))
        if self._log_pinned and pinned_scroll is not None:
            bar.setValue(min(pinned_scroll, bar.maximum()))
        elif not self._log_pinned:
            self._scroll_log_to_end()

    def _raw_offline_msg(self, launcher, which: str) -> str:
        from sync_app.core.connectivity_service import load_connectivity_cache

        cache = load_connectivity_cache(load_secure_config(None))
        if which == "wc":
            raw = str(cache.get("wc_msg") or "")
            if launcher is not None:
                tip = (getattr(launcher, "_wc_tooltip", "") or "").strip()
                if tip and (not raw or len(tip) > len(raw)):
                    raw = tip
            return raw
        raw = str(cache.get("sql_msg") or "")
        if launcher is not None:
            tip = (getattr(launcher, "_sql_tooltip", "") or "").strip()
            if tip and (not raw or len(tip) > len(raw)):
                raw = tip
        return raw

    def _offline_reason_lines(self, launcher) -> list[tuple[str, str]]:
        from sync_app.core.connectivity_service import describe_offline_reason

        lines: list[tuple[str, str]] = []
        if launcher is None:
            lines.append(("warn", "علت: هدر برنامه در دسترس نیست"))
            return lines

        if self._need_wc:
            st = launcher.wc_connectivity_state()
            if st != "online":
                host = ""
                try:
                    host = launcher._wc_host_short() or ""
                except Exception:
                    pass
                raw = self._raw_offline_msg(launcher, "wc")
                reason = describe_offline_reason(raw, target="WooCommerce", host=host)
                level = "wait" if st == "pending" else "warn"
                lines.append((level, f"علت: {reason}"))

        if self._need_sql:
            st = launcher.sql_connectivity_state()
            if st != "online":
                db = (getattr(launcher, "_sql_db_name", "") or "").strip()
                raw = self._raw_offline_msg(launcher, "sql")
                reason = describe_offline_reason(raw, target="SQL Server", host=db)
                level = "wait" if st == "pending" else "warn"
                lines.append((level, f"علت: {reason}"))

        return lines

    def _connectivity_summary(self, launcher) -> str:
        labels = {"online": "آنلاین", "offline": "آفلاین", "pending": "در حال بررسی"}
        if launcher is None:
            return "هدر در دسترس نیست"

        parts: list[str] = []
        if self._need_wc:
            st = launcher.wc_connectivity_state()
            host = ""
            try:
                host = launcher._wc_host_short() or ""
            except Exception:
                pass
            bit = f"Woo {labels.get(st, st)}"
            if host:
                bit += f" ({host})"
            parts.append(bit)
        if self._need_sql:
            st = launcher.sql_connectivity_state()
            db = (getattr(launcher, "_sql_db_name", "") or "").strip()
            bit = f"SQL {labels.get(st, st)}"
            if db:
                bit += f" ({db})"
            parts.append(bit)
        return " — ".join(parts) if parts else "—"

    def _header_check_in_progress(self, launcher) -> bool:
        return getattr(launcher, "_header_check_thread", None) is not None

    def _maybe_nudge_header_check(self, launcher) -> None:
        if launcher is None:
            return
        now = time.monotonic()
        if now - self._last_nudge_mono < _NUDGE_HEADER_SEC:
            return
        self._last_nudge_mono = now
        if self._header_check_in_progress(launcher):
            self._append_log("بررسی اتصال در جریان است...", "wait")
            return
        try:
            launcher.refresh_header_connectivity()
            self._append_log("درخواست بررسی مجدد اتصال به سرویس", "info")
        except Exception:
            self._append_log("درخواست بررسی اتصال — خطا در فراخوانی هدر", "warn")

    def _log_connectivity_read(self, launcher) -> None:
        if connectivity_ready(launcher, need_sql=self._need_sql, need_wc=self._need_wc):
            if self._last_log_key != "__online__":
                self._last_log_key = "__online__"
                self._append_log("اتصال برقرار شد — ادامه کار", "ok")
            return

        results = self._offline_reason_lines(launcher)
        raw_key_parts = []
        if self._need_wc:
            st = launcher.wc_connectivity_state() if launcher else "offline"
            raw_key_parts.append(f"wc:{st}:{self._raw_offline_msg(launcher, 'wc')}")
        if self._need_sql:
            st = launcher.sql_connectivity_state() if launcher else "offline"
            raw_key_parts.append(f"sql:{st}:{self._raw_offline_msg(launcher, 'sql')}")
        key = "|".join(raw_key_parts)
        if key != self._last_log_key:
            self._last_log_key = key
            for level, msg in results:
                self._append_log(msg, level)

        now = time.monotonic()
        if now - self._last_activity_log_mono < _LOG_ACTIVITY_SEC:
            return
        self._last_activity_log_mono = now

        self._poll_count += 1
        phrase = _ACTIVITY_PHRASES[(self._poll_count - 1) % len(_ACTIVITY_PHRASES)]
        reason_hint = results[0][1].replace("علت: ", "") if results else self._connectivity_summary(launcher)
        self._append_log(f"تلاش {self._poll_count}: {phrase} — {reason_hint}", "wait")
        self._maybe_nudge_header_check(launcher)

    def _make_badge_label(self) -> QLabel:
        badge = QLabel()
        badge.setAlignment(Qt.AlignCenter)
        badge.setMinimumHeight(_BADGE_HEIGHT)
        badge.setMinimumWidth(128)
        return badge

    def _make_pulse(self, widget: QWidget) -> QPropertyAnimation:
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(1100)
        anim.setStartValue(0.35)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutSine)
        anim.setLoopCount(-1)
        anim.start()
        return anim

    def _refresh_badges(self, launcher) -> None:
        if launcher is None:
            return
        if self._sql_badge is not None:
            launcher.paint_connectivity_badge_clone(self._sql_badge, "sql")
        if self._wc_badge is not None:
            launcher.paint_connectivity_badge_clone(self._wc_badge, "wc")

    def _tick(self):
        launcher = find_peecha_launcher(self)
        self._refresh_badges(launcher)

        names = offline_labels(launcher, need_sql=self._need_sql, need_wc=self._need_wc)
        label = " و ".join(names) if names else "اتصال"
        pending = False
        if launcher is not None:
            if self._need_sql and launcher.sql_connectivity_state() == "pending":
                pending = True
            if self._need_wc and launcher.wc_connectivity_state() == "pending":
                pending = True

        self._log_connectivity_read(launcher)

        if connectivity_ready(launcher, need_sql=self._need_sql, need_wc=self._need_wc):
            self.accept()
            return

        if pending:
            self._set_rtl_text(self._status_line, f"در حال بررسی وضعیت {label}...")
            self._set_rtl_text(
                self._hint,
                "چند ثانیه صبر کنید — نتیجه همان دکمه بالای صفحه است.\n"
                "به محض سبز شدن، کار خودکار شروع می‌شود.",
                multiline=True,
            )
        else:
            self._set_rtl_text(self._status_line, f"{label} آفلاین است — منتظر برقراری اتصال")
            self._set_rtl_text(
                self._hint,
                "اتصال را برقرار کنید — به محض آنلاین شدن، کار خودکار ادامه می‌یابد.\n"
                "برای تنظیمات روی همان دکمه در بالای صفحه کلیک کنید.",
                multiline=True,
            )

    def closeEvent(self, event):
        self._timer.stop()
        if self._pulse_anim is not None:
            self._pulse_anim.stop()
        super().closeEvent(event)


def wait_for_connectivity_dialog(
    parent,
    *,
    need_sql=True,
    need_wc=False,
    operation_label="",
) -> bool:
    """True = اتصال برقرار شد؛ False = کاربر توقف زد."""
    launcher = find_peecha_launcher(parent)
    if connectivity_ready(launcher, need_sql=need_sql, need_wc=need_wc):
        return True
    dlg = ConnectivityWaitDialog(
        parent,
        need_sql=need_sql,
        need_wc=need_wc,
        operation_label=operation_label,
    )
    return dlg.exec_() == QDialog.Accepted


def wait_for_connectivity_blocking(
    config=None,
    *,
    need_sql=False,
    need_wc=True,
    log_waiting=True,
) -> None:
    """در thread پس‌زمینه — از همان cache هدر صبر کن (بدون پروب جدید)."""
    from sync_app.core.connectivity_service import load_connectivity_cache
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_utils import log

    announced = False
    last_log = 0.0

    while True:
        check_cancelled()
        cache = load_connectivity_cache(load_secure_config(None))
        sql_ok = not need_sql or bool(cache.get("sql_ok"))
        wc_ok = not need_wc or bool(cache.get("wc_ok"))
        if sql_ok and wc_ok:
            if announced:
                log.info("✅ اتصال برقرار شد — ادامه کار...")
            return

        if log_waiting and not announced:
            parts = []
            if need_wc and not wc_ok:
                parts.append("WooCommerce")
            if need_sql and not sql_ok:
                parts.append("SQL")
            label = " و ".join(parts) if parts else "شبکه"
            log.warning(
                f"⏸ اتصال {label} قطع است — منتظر برقراری مجدد...\n"
                "برای توقف دکمه «توقف» را بزنید."
            )
            announced = True
            last_log = time.monotonic()
        elif log_waiting and time.monotonic() - last_log >= 30:
            log.info("⏳ هنوز منتظر اتصال...")
            last_log = time.monotonic()

        time.sleep(WORKER_POLL_SEC)
