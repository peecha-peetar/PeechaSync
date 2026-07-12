# دیالوگ خطای App Password وردپرس

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from sync_app.core.connectivity_guard import find_peecha_launcher
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.wc_site_profiles import ensure_wc_sites

_BTN_CLOSE = (
    "QPushButton {"
    "  background-color: #e2e8f0; color: #334155;"
    "  border: none; border-radius: 10px;"
    "  padding: 10px 28px; font-size: 12px; font-weight: 700;"
    "}"
    "QPushButton:hover { background-color: #cbd5e1; }"
)


class _ActionCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, title: str, hint: str, *, primary: bool = False, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        if primary:
            self.setStyleSheet(
                "QFrame { background: #2563eb; border: none; border-radius: 10px; }"
                "QFrame:hover { background: #1d4ed8; }"
            )
            title_color, hint_color = "#ffffff", "#dbeafe"
        else:
            self.setStyleSheet(
                "QFrame { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; }"
                "QFrame:hover { background: #eff6ff; border-color: #93c5fd; }"
            )
            title_color, hint_color = "#1e293b", "#64748b"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        t = QLabel(title)
        t.setWordWrap(True)
        t.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {title_color};"
            " background: transparent; border: none;"
        )
        lay.addWidget(t)

        if hint:
            h = QLabel(hint)
            h.setWordWrap(True)
            h.setStyleSheet(
                f"font-size: 10px; font-weight: 500; color: {hint_color};"
                " background: transparent; border: none;"
            )
            lay.addWidget(h)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
        super().keyPressEvent(event)


class WpAuthErrorDialog(QDialog):
    """دیالوگ خطای Application Password با دکمه‌های خوانا و چیدمان عمودی."""

    ACTION_SETTINGS = "settings"
    ACTION_PICK = "pick"
    ACTION_USERS = "users"
    ACTION_APP_PWD = "app_pwd"
    ACTION_CLOSE = "close"

    def __init__(
        self,
        parent=None,
        *,
        window_title: str = "خطای Application Password",
        headline: str = "",
        message: str = "",
        err_type: str = "generic",
        has_users: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setMinimumWidth(560)
        self.setMaximumWidth(720)
        self.setLayoutDirection(Qt.RightToLeft)
        self._action = self.ACTION_CLOSE

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel("✕")
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            "background: #fee2e2; color: #dc2626; border-radius: 22px;"
            "font-size: 22px; font-weight: 900;"
        )
        header.addWidget(icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        headline_lbl = QLabel(headline or "ورود وردپرس برای آپلود تصویر تأیید نشد")
        headline_lbl.setWordWrap(True)
        headline_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #0f172a;")
        title_col.addWidget(headline_lbl)

        subtitle = QLabel("راهنمای رفع مشکل Application Password")
        subtitle.setStyleSheet("font-size: 11px; color: #64748b; font-weight: 600;")
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)
        root.addLayout(header)

        msg_frame = QFrame()
        msg_frame.setStyleSheet(
            "QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; }"
        )
        msg_layout = QVBoxLayout(msg_frame)
        msg_layout.setContentsMargins(12, 10, 12, 10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(280)

        msg_body = QPlainTextEdit()
        msg_body.setPlainText(message or "")
        msg_body.setReadOnly(True)
        msg_body.setFrameShape(QFrame.NoFrame)
        msg_body.setLayoutDirection(Qt.RightToLeft)
        msg_body.setStyleSheet(
            "QPlainTextEdit { background: transparent; color: #334155;"
            " font-size: 12px; line-height: 1.5; border: none; }"
        )
        scroll.setWidget(msg_body)
        msg_layout.addWidget(scroll)
        root.addWidget(msg_frame)

        actions_title = QLabel("چه کاری انجام دهید؟")
        actions_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #475569;")
        root.addWidget(actions_title)

        actions = QVBoxLayout()
        actions.setSpacing(8)

        self._primary_card = None

        if has_users and err_type in ("invalid_username", "incorrect_password"):
            pick_card = self._make_card(
                "📋  انتخاب نام کاربری از سایت",
                "لیست کاربران وردپرس — مدیران در بالای لیست",
                primary=True,
                action=self.ACTION_PICK,
            )
            actions.addWidget(pick_card)
            self._primary_card = pick_card

        settings_card = self._make_card(
            "⚙️  رفتن به تنظیمات WP Username",
            "باز کردن تب تنظیمات و هایلایت فیلد نام کاربری",
            primary=not has_users,
            action=self.ACTION_SETTINGS,
        )
        actions.addWidget(settings_card)
        if self._primary_card is None:
            self._primary_card = settings_card

        users_card = self._make_card(
            "👥  Users در وردپرس",
            "باز کردن Users → All Users در wp-admin",
            action=self.ACTION_USERS,
        )
        actions.addWidget(users_card)

        if err_type == "incorrect_password":
            app_card = self._make_card(
                "🔑  ساخت Application Password جدید",
                "باز کردن Profile → Application Passwords",
                action=self.ACTION_APP_PWD,
            )
            actions.addWidget(app_card)

        root.addLayout(actions)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton("بستن")
        close_btn.setMinimumHeight(40)
        close_btn.setMinimumWidth(120)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(_BTN_CLOSE)
        close_btn.clicked.connect(lambda: self._finish(self.ACTION_CLOSE))
        footer.addWidget(close_btn)
        root.addLayout(footer)

        if self._primary_card is not None:
            self._primary_card.setFocus(Qt.OtherFocusReason)

    def _make_card(self, title: str, hint: str, *, primary: bool = False, action: str = "") -> _ActionCard:
        card = _ActionCard(title, hint, primary=primary, parent=self)
        card.setMinimumHeight(56)
        card.clicked.connect(lambda a=action: self._finish(a))
        return card

    def _finish(self, action: str):
        self._action = action
        self.accept()

    @property
    def chosen_action(self) -> str:
        return self._action


def _settings_tab(parent):
    launcher = find_peecha_launcher(parent)
    if launcher is None or not hasattr(launcher, "_go_to_config_tab"):
        return None
    return launcher._go_to_config_tab()


def navigate_to_wp_username_settings(parent) -> bool:
    """رفتن به تنظیمات WooCommerce و هایلایت فیلد WP Username."""
    launcher = find_peecha_launcher(parent)
    if launcher is not None and hasattr(launcher, "open_wp_username_settings"):
        launcher.open_wp_username_settings()
        return True

    settings = _settings_tab(parent)
    if settings is None:
        return False
    if launcher is not None and hasattr(launcher, "_open_settings_section"):
        launcher._open_settings_section("woo")
    focus = getattr(settings, "focus_wp_username_field", None) or getattr(
        settings, "_focus_wp_username_field", None
    )
    if callable(focus):
        focus()
        return True
    return False


def _open_wp_users_page(parent) -> None:
    settings = _settings_tab(parent)
    if settings is not None and hasattr(settings, "_open_wp_users_page"):
        settings._open_wp_users_page()
        return
    from sync_app.core.wc_sync_helper import open_external_url, wp_media_base_url

    cfg = ensure_wc_sites(load_secure_config(None) or {})
    base = wp_media_base_url(cfg)
    if base:
        open_external_url(parent, f"{base}/wp-admin/users.php")


def _open_wp_app_password_page(parent) -> None:
    settings = _settings_tab(parent)
    if settings is not None and hasattr(settings, "_open_wp_app_password_page"):
        settings._open_wp_app_password_page()
        return
    from sync_app.core.wc_sync_helper import open_external_url, wp_media_base_url

    cfg = ensure_wc_sites(load_secure_config(None) or {})
    base = wp_media_base_url(cfg)
    if base:
        open_external_url(parent, f"{base}/wp-admin/profile.php#application-passwords-section")


def _pick_username_on_settings(parent, *, probe_password: bool, offer_retest: bool, users=None, site_note=""):
    settings = _settings_tab(parent)
    if settings is None:
        QMessageBox.warning(
            parent,
            "تنظیمات",
            "برای انتخاب نام کاربری، از منو به تب «تنظیمات» بروید.",
        )
        return None

    if users:
        apply_pick = getattr(settings, "apply_wp_username_pick", None) or getattr(
            settings, "_apply_wp_username_pick", None
        )
        if callable(apply_pick):
            entered = ""
            if hasattr(settings, "wp_username_input"):
                entered = settings.wp_username_input.text().strip()
            return apply_pick(users, entered, site_note, offer_retest=offer_retest)

    pick_fn = getattr(settings, "pick_wp_username_from_site", None) or getattr(
        settings, "_pick_wp_username_from_site", None
    )
    if callable(pick_fn):
        return pick_fn(probe_password=probe_password, offer_retest=offer_retest)
    return None


def _handle_auth_dialog_action(
    parent,
    action: str,
    *,
    prefetched_users,
    site_note: str,
) -> None:
    if action == WpAuthErrorDialog.ACTION_SETTINGS:
        navigate_to_wp_username_settings(parent)
    elif action == WpAuthErrorDialog.ACTION_PICK:
        navigate_to_wp_username_settings(parent)
        _pick_username_on_settings(
            parent,
            probe_password=True,
            offer_retest=True,
            users=prefetched_users or None,
            site_note=site_note,
        )
    elif action == WpAuthErrorDialog.ACTION_USERS:
        _open_wp_users_page(parent)
        navigate_to_wp_username_settings(parent)
    elif action == WpAuthErrorDialog.ACTION_APP_PWD:
        _open_wp_app_password_page(parent)


def is_wp_media_auth_error(err_text: str) -> bool:
    from sync_app.core.wc_sync_helper import classify_wp_media_auth_error

    err_type = classify_wp_media_auth_error(err_text or "")
    return err_type in ("invalid_username", "incorrect_password", "permission", "generic") and bool(
        (err_text or "").strip()
    )


def show_wp_media_auth_error_dialog(
    parent,
    err: str,
    cfg: dict | None = None,
    *,
    context: str = "",
) -> None:
    """
    دیالوگ خطای Application Password با دکمه‌های راهنما.
    context: متن کوتاه مثل «ارسال تصاویر دسته‌بندی»
    """
    from sync_app.core.wc_sync_helper import (
        classify_wp_media_auth_error,
        fetch_wp_users_for_picker,
        format_wp_username_auth_error,
        get_wp_media_credentials,
        response_is_waf_block_from_text,
        wp_media_waf_user_message,
    )

    err_text = (err or "").strip()
    if not err_text:
        return

    if response_is_waf_block_from_text(err_text) or "فایروال" in err_text:
        QMessageBox.warning(
            parent,
            "مسدودیت هاست",
            wp_media_waf_user_message(err_text) if "ورود REST" not in err_text else err_text,
        )
        return

    cfg = ensure_wc_sites(cfg or load_secure_config(None) or {})
    err_type = classify_wp_media_auth_error(err_text)
    entered_user, _ = get_wp_media_credentials(cfg)

    if err_type in ("invalid_username", "incorrect_password", "permission"):
        main_text = format_wp_username_auth_error(
            err_type,
            entered_username=entered_user,
            detail=err_text,
        )
    else:
        main_text = err_text

    if context:
        main_text = f"{context}\n\n{main_text}"

    prefetched_users: list = []
    site_note = ""
    has_users = False
    if err_type in ("invalid_username", "incorrect_password"):
        QApplication.processEvents()
        prefetched_users, site_note = fetch_wp_users_for_picker(
            cfg,
            probe_password=True,
            entered_username=entered_user,
        )
        has_users = bool(prefetched_users)
        if prefetched_users:
            admin_names = ", ".join(
                str(u.get("username") or "")
                for u in prefetched_users
                if u.get("is_admin") and u.get("username")
            )[:120]
            if admin_names:
                main_text += f"\n\nکاربران مدیر در سایت: {admin_names}"
            names = [
                str(u.get("username") or "")
                for u in prefetched_users[:10]
                if u.get("username")
            ]
            if names:
                main_text += f"\n\nنام‌های کاربری یافت‌شده: {', '.join(names)}"
                if len(prefetched_users) > len(names):
                    main_text += f" (+{len(prefetched_users) - len(names)} مورد دیگر)"
            main_text += (
                f"\n\n{site_note}\n"
                "با دکمه «انتخاب نام کاربری از سایت» یکی را انتخاب کنید — مدیران بالای لیست هستند."
            )

    headline = context or "ورود وردپرس برای آپلود تصویر تأیید نشد"

    dlg = WpAuthErrorDialog(
        parent,
        headline=headline,
        message=main_text,
        err_type=err_type,
        has_users=has_users,
    )
    dlg.exec_()
    _handle_auth_dialog_action(
        parent,
        dlg.chosen_action,
        prefetched_users=prefetched_users,
        site_note=site_note,
    )


def show_wp_media_auth_error_if_applicable(
    parent,
    err: str,
    cfg: dict | None = None,
    *,
    context: str = "",
) -> bool:
    """اگر خطا مربوط به WP auth است دیالوگ راهنما نشان بده — True یعنی handle شد."""
    from sync_app.core.wc_sync_helper import classify_wp_media_auth_error, response_is_waf_block_from_text

    err_text = (err or "").strip()
    if not err_text:
        return False
    err_type = classify_wp_media_auth_error(err_text)
    if err_type in ("invalid_username", "incorrect_password", "permission"):
        show_wp_media_auth_error_dialog(parent, err_text, cfg, context=context)
        return True
    low = err_text.lower()
    if response_is_waf_block_from_text(err_text) or "application password" in low:
        show_wp_media_auth_error_dialog(parent, err_text, cfg, context=context)
        return True
    if "wp username" in low or "wp app password" in low or "جابه‌جا" in err_text:
        show_wp_media_auth_error_dialog(parent, err_text, cfg, context=context)
        return True
    return False
