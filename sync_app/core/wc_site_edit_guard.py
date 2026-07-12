# هشدار قبل از بازنویسی پروفایل سایت ووکامرس

from __future__ import annotations

import copy

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from sync_app.core.wc_api_helper import wc_store_host
from sync_app.core.wc_site_profiles import site_display_label

ACTION_PROCEED = "proceed"
ACTION_NEW_SITE = "new_site"
ACTION_CANCEL = "cancel"

_COMPARE_FIELDS = (
    "url",
    "consumer_key",
    "consumer_secret",
    "wp_username",
    "wp_app_password",
    "currency_is_toman",
    "label",
)


def snapshot_wc_site(site: dict | None) -> dict:
    if not isinstance(site, dict):
        return {}
    out = {}
    for key in _COMPARE_FIELDS:
        val = site.get(key)
        if key == "currency_is_toman":
            out[key] = bool(val)
        else:
            out[key] = str(val or "").strip()
    return out


def wc_site_form_changed(baseline: dict, form: dict) -> bool:
    base = snapshot_wc_site(baseline)
    cur = snapshot_wc_site(form)
    return base != cur


def wc_site_credentials_changed(baseline: dict, form: dict) -> bool:
    """تغییرات مهم اتصال — بدون نام پروفایل."""
    base = snapshot_wc_site(baseline)
    cur = snapshot_wc_site(form)
    for key in (
        "url",
        "consumer_key",
        "consumer_secret",
        "wp_username",
        "wp_app_password",
        "currency_is_toman",
    ):
        if base.get(key) != cur.get(key):
            return True
    return False


def wc_site_is_saved_profile(baseline: dict) -> bool:
    """پروفایلی که قبلاً URL یا کلید API داشته «ذخیره‌شده» محسوب می‌شود."""
    base = snapshot_wc_site(baseline)
    return bool(base.get("url") or base.get("consumer_key") or base.get("consumer_secret"))


def wc_site_hosts_differ(baseline: dict, form: dict) -> bool:
    old_host = wc_store_host(url=snapshot_wc_site(baseline).get("url", "")).lower()
    new_host = wc_store_host(url=snapshot_wc_site(form).get("url", "")).lower()
    if not old_host or not new_host:
        return False
    return old_host != new_host


class _GuardActionCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, title: str, hint: str, *, primary: bool = False, danger: bool = False, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        if danger:
            self.setStyleSheet(
                "QFrame { background: #fff7ed; border: 1px solid #fdba74; border-radius: 10px; }"
                "QFrame:hover { background: #ffedd5; border-color: #fb923c; }"
            )
            title_color, hint_color = "#9a3412", "#c2410c"
        elif primary:
            self.setStyleSheet(
                "QFrame { background: #2563eb; border: none; border-radius: 10px; }"
                "QFrame:hover { background: #1d4ed8; }"
            )
            title_color, hint_color = "#ffffff", "#dbeafe"
        else:
            self.setStyleSheet(
                "QFrame { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; }"
                "QFrame:hover { background: #f1f5f9; border-color: #94a3b8; }"
            )
            title_color, hint_color = "#1e293b", "#64748b"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        t = QLabel(title)
        t.setWordWrap(True)
        t.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {title_color}; background: transparent; border: none;"
        )
        lay.addWidget(t)

        if hint:
            h = QLabel(hint)
            h.setWordWrap(True)
            h.setStyleSheet(
                f"font-size: 10px; font-weight: 500; color: {hint_color}; background: transparent; border: none;"
            )
            lay.addWidget(h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class WcSiteEditGuardDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        site_label: str = "",
        old_host: str = "",
        new_host: str = "",
        cross_site: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("ویرایش پروفایل سایت")
        self.setMinimumWidth(540)
        self.setMaximumWidth(680)
        self.setLayoutDirection(Qt.RightToLeft)
        self._action = ACTION_CANCEL

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        header = QHBoxLayout()
        icon = QLabel("!")
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background: #fef3c7; color: #b45309; border-radius: 22px; font-size: 24px; font-weight: 900;"
        )
        header.addWidget(icon)

        title_col = QVBoxLayout()
        title = QLabel("شما در حال ویرایش یک سایت ذخیره‌شده هستید")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 15px; font-weight: 800; color: #0f172a;")
        title_col.addWidget(title)

        profile = QLabel(f"پروفایل فعلی: «{site_label or '—'}»")
        profile.setStyleSheet("font-size: 12px; font-weight: 700; color: #475569;")
        title_col.addWidget(profile)
        header.addLayout(title_col, 1)
        root.addLayout(header)

        msg_parts = [
            "تغییراتی که اعمال کرده‌اید روی همین پروفایل ذخیره می‌شود "
            "و اطلاعات قبلی این سایت جایگزین خواهد شد.",
        ]
        if cross_site and old_host and new_host:
            msg_parts.append(
                f"\nبه نظر می‌رسد تنظیمات مربوط به سایت دیگری است:\n"
                f"• سایت ذخیره‌شده: {old_host}\n"
                f"• آدرس فعلی در فرم: {new_host}"
            )
            msg_parts.append(
                "\nاگر این فروشگاه جداست، حتماً «ذخیره به‌عنوان سایت جدید» را بزنید "
                "تا اطلاعات «" + (old_host or site_label) + "» از بین نرود."
            )
        else:
            msg_parts.append(
                "\nاگر این تغییرات مربوط به فروشگاه دیگری است، "
                "آن را به‌صورت «سایت جدید» ذخیره کنید."
            )

        body = QLabel("".join(msg_parts))
        body.setWordWrap(True)
        body.setStyleSheet(
            "color: #334155; font-size: 12px; line-height: 1.5;"
            " background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px;"
        )
        root.addWidget(body)

        actions_title = QLabel("چه کار کنید؟")
        actions_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #475569;")
        root.addWidget(actions_title)

        actions = QVBoxLayout()
        actions.setSpacing(8)

        new_card = _GuardActionCard(
            "➕  ذخیره به‌عنوان سایت جدید",
            "پروفایل فعلی دست‌نخورده می‌ماند — تنظیمات فرم در سایت جدید ذخیره می‌شود",
            primary=cross_site,
        )
        new_card.clicked.connect(lambda: self._finish(ACTION_NEW_SITE))
        actions.addWidget(new_card)

        proceed_card = _GuardActionCard(
            "✏️  بازنویسی همین پروفایل",
            f"تغییرات روی «{site_label or old_host or 'سایت فعلی'}» ذخیره می‌شود — دادهٔ قبلی از بین می‌رود",
            danger=True,
            primary=not cross_site,
        )
        proceed_card.clicked.connect(lambda: self._finish(ACTION_PROCEED))
        actions.addWidget(proceed_card)

        root.addLayout(actions)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton("انصراف — برگرداندن تغییرات")
        cancel_btn.setMinimumHeight(40)
        cancel_btn.setMinimumWidth(180)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            "QPushButton { background: #e2e8f0; color: #334155; border: none; border-radius: 10px;"
            " padding: 10px 18px; font-weight: 700; }"
            "QPushButton:hover { background: #cbd5e1; }"
        )
        cancel_btn.clicked.connect(lambda: self._finish(ACTION_CANCEL))
        footer.addWidget(cancel_btn)
        root.addLayout(footer)

        (new_card if cross_site else proceed_card).setFocus(Qt.OtherFocusReason)

    def _finish(self, action: str):
        self._action = action
        self.accept()

    @property
    def chosen_action(self) -> str:
        return self._action


def confirm_wc_site_edit(
    parent,
    *,
    baseline_site: dict,
    form_site: dict,
) -> str:
    """
    اگر ویرایش ریسک‌دار باشد دیالوگ نشان می‌دهد.
    برمی‌گرداند: proceed | new_site | cancel
    """
    baseline = snapshot_wc_site(baseline_site)
    if not wc_site_is_saved_profile(baseline):
        return ACTION_PROCEED
    if not wc_site_credentials_changed(baseline_site, form_site):
        return ACTION_PROCEED

    cross = wc_site_hosts_differ(baseline_site, form_site)
    old_host = wc_store_host(url=baseline.get("url", ""))
    new_host = wc_store_host(url=snapshot_wc_site(form_site).get("url", ""))
    label = str(baseline.get("label") or "").strip() or site_display_label(baseline_site)

    dlg = WcSiteEditGuardDialog(
        parent,
        site_label=label,
        old_host=old_host,
        new_host=new_host,
        cross_site=cross,
    )
    dlg.exec_()
    return dlg.chosen_action


def restore_site_in_list(sites: list[dict], site_id: str, baseline_site: dict) -> list[dict]:
    """بازگرداندن یک پروفایل از snapshot در لیست."""
    sid = (site_id or "").strip()
    restored = copy.deepcopy(baseline_site)
    out = []
    for site in sites or []:
        if str(site.get("id") or "") == sid:
            out.append(restored)
        else:
            out.append(copy.deepcopy(site))
    return out
