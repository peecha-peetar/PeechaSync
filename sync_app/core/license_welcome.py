"""صفحه خوش‌آمد و راهنمای دریافت لایسنس — فقط هنگام اولین اجرا."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.app_theme import (
    build_license_welcome_stylesheet,
    get_active_theme_palette,
    resolve_user_font_pref,
)
from sync_app.core.license_remote import license_server_url, license_support_url
from sync_app.core.message_boxes_fa import set_rtl_label_text
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.sync_utils import resource_path
from sync_app.core.tabs.tab_license import LicenseTab
from sync_app.core.wc_sync_helper import open_external_url


class LicenseWelcomeWindow(QWidget):
    """راهنمای ساده برای کاربر تازه — به‌جای تب فنی فعال‌سازی در شروع برنامه."""

    def __init__(self, on_activated=None):
        super().__init__()
        self._on_activated = on_activated
        self.hwid = LicenseTab.get_hwid()
        self._cfg = load_secure_config(None) or {}
        self._site_url = license_server_url(self._cfg)
        self._support_url = license_support_url(self._cfg)

        self.setObjectName("licenseWelcomeRoot")
        self.setLayoutDirection(Qt.RightToLeft)
        self._apply_theme()
        self._build_ui()
        self._apply_status_copy()
        QTimer.singleShot(600, self._try_refresh_existing_license)

    def _try_refresh_existing_license(self) -> None:
        key = LicenseTab._load_license_key()
        if not key:
            return
        from sync_app.core.license_remote import humanize_license_error, try_refresh_stale_denial

        ok, err = try_refresh_stale_denial()
        if ok and LicenseTab.is_license_valid_for_launch():
            if callable(self._on_activated):
                self._on_activated()
                self.close()
            return
        if err and err not in ("no_license_key", "timeout", "connection_error"):
            self._apply_status_copy()

    def _recheck_license(self) -> None:
        from sync_app.core.license_remote import humanize_license_error, try_refresh_stale_denial

        ok, err = try_refresh_stale_denial()
        if ok and LicenseTab.is_license_valid_for_launch():
            QMessageBox.information(self, "فعال شد", "لایسنس از سرور تأیید شد. برنامه آماده است.")
            if callable(self._on_activated):
                self._on_activated()
                self.close()
            return
        QMessageBox.warning(
            self,
            "هنوز فعال نشد",
            humanize_license_error(err) if err else "لایسنس هنوز در سرور تأیید نشد.",
        )
        self._apply_status_copy()

    def _apply_theme(self) -> None:
        _, palette = get_active_theme_palette()
        font_size, is_bold = resolve_user_font_pref(self._cfg.get("APP_FONT_SIZE", 14))
        self.setStyleSheet(build_license_welcome_stylesheet(palette, font_size, is_bold))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("licenseWelcomeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo.setObjectName("licenseWelcomeLogo")
        logo_path = resource_path("Peecha_logo.png")
        pix = QPixmap(logo_path) if logo_path else QPixmap()
        if not pix.isNull():
            logo.setPixmap(pix.scaled(52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header.addWidget(logo, 0, Qt.AlignRight)

        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        self.brand_title = QLabel("پیچا")
        self.brand_title.setObjectName("licenseWelcomeBrand")
        self.brand_subtitle = QLabel("همگام‌سازی ERP و ووکامرس")
        self.brand_subtitle.setObjectName("licenseWelcomeTagline")
        title_block.addWidget(self.brand_title)
        title_block.addWidget(self.brand_subtitle)
        header.addLayout(title_block, 1)
        layout.addLayout(header)

        hero = QFrame()
        hero.setObjectName("licenseWelcomeHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(8)

        self.hero_title = QLabel()
        self.hero_title.setObjectName("licenseWelcomeHeroTitle")
        self.hero_subtitle = QLabel()
        self.hero_subtitle.setObjectName("licenseWelcomeHeroSubtitle")
        self.hero_subtitle.setWordWrap(True)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_subtitle)
        layout.addWidget(hero)

        steps_card = QFrame()
        steps_card.setObjectName("licenseWelcomeSteps")
        steps_layout = QVBoxLayout(steps_card)
        steps_layout.setContentsMargins(20, 18, 20, 18)
        steps_layout.setSpacing(12)

        steps_title = QLabel("چطور لایسنس بگیرم؟")
        steps_title.setObjectName("licenseWelcomeSectionTitle")
        steps_layout.addWidget(steps_title)

        for num, text in (
            ("۱", "به سایت peecha.ir بروید."),
            ("۲", "از بخش تماس یا ثبت تیکت، درخواست لایسنس ثبت کنید."),
            ("۳", "شناسه دستگاه زیر را در تیکت بنویسید تا کلید برای همین رایانه صادر شود."),
            ("۴", "کلید دریافتی را پایین همین صفحه وارد کنید و فعال‌سازی را بزنید."),
        ):
            steps_layout.addWidget(self._make_step_row(num, text))
        layout.addWidget(steps_card)

        hwid_card = QFrame()
        hwid_card.setObjectName("licenseWelcomeHwidCard")
        hwid_layout = QVBoxLayout(hwid_card)
        hwid_layout.setContentsMargins(18, 16, 18, 16)
        hwid_layout.setSpacing(8)

        hwid_caption = QLabel("شناسه دستگاه (برای ثبت تیکت)")
        hwid_caption.setObjectName("licenseWelcomeCaption")
        hwid_layout.addWidget(hwid_caption)

        hwid_row = QHBoxLayout()
        self.hwid_display = QLineEdit(self.hwid)
        self.hwid_display.setObjectName("licenseWelcomeHwid")
        self.hwid_display.setReadOnly(True)
        hwid_row.addWidget(self.hwid_display, 1)

        copy_btn = QPushButton("کپی")
        copy_btn.setObjectName("licenseWelcomeCopyBtn")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_hwid)
        hwid_row.addWidget(copy_btn)
        hwid_layout.addLayout(hwid_row)
        layout.addWidget(hwid_card)

        self.btn_support = QPushButton("ثبت درخواست لایسنس — سایت پیچا")
        self.btn_support.setObjectName("licenseWelcomePrimaryBtn")
        self.btn_support.setMinimumHeight(48)
        self.btn_support.setCursor(Qt.PointingHandCursor)
        self.btn_support.clicked.connect(self._open_support)
        layout.addWidget(self.btn_support)

        self.btn_recheck = QPushButton("بررسی مجدد لایسنس از سرور")
        self.btn_recheck.setObjectName("licenseWelcomeSecondaryBtn")
        self.btn_recheck.setMinimumHeight(42)
        self.btn_recheck.setCursor(Qt.PointingHandCursor)
        self.btn_recheck.clicked.connect(self._recheck_license)
        layout.addWidget(self.btn_recheck)

        self.btn_site = QPushButton("ورود به سایت peecha.ir")
        self.btn_site.setObjectName("licenseWelcomeSecondaryBtn")
        self.btn_site.setMinimumHeight(42)
        self.btn_site.setCursor(Qt.PointingHandCursor)
        self.btn_site.clicked.connect(self._open_site)
        layout.addWidget(self.btn_site)

        activate_card = QFrame()
        activate_card.setObjectName("licenseWelcomeActivateCard")
        act_layout = QVBoxLayout(activate_card)
        act_layout.setContentsMargins(20, 18, 20, 18)
        act_layout.setSpacing(10)

        act_title = QLabel("کلید لایسنس دارم")
        act_title.setObjectName("licenseWelcomeSectionTitle")
        act_layout.addWidget(act_title)

        act_hint = QLabel("اگر کلید را از پشتیبانی پیچا دریافت کرده‌اید، اینجا وارد کنید.")
        act_hint.setObjectName("licenseWelcomeCaption")
        act_hint.setWordWrap(True)
        set_rtl_label_text(act_hint, act_hint.text(), multiline=True)
        act_layout.addWidget(act_hint)

        self.license_input = QLineEdit()
        self.license_input.setObjectName("licenseWelcomeKeyInput")
        self.license_input.setPlaceholderText("کلید لایسنس را اینجا بچسبانید…")
        existing_key = LicenseTab._load_license_key()
        if existing_key:
            self.license_input.setText(existing_key)
        act_layout.addWidget(self.license_input)

        self.btn_activate = QPushButton("فعال‌سازی و ورود به برنامه")
        self.btn_activate.setObjectName("licenseWelcomeActivateBtn")
        self.btn_activate.setMinimumHeight(46)
        self.btn_activate.setCursor(Qt.PointingHandCursor)
        self.btn_activate.clicked.connect(self._activate)
        act_layout.addWidget(self.btn_activate)
        layout.addWidget(activate_card)

        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)

    def _make_step_row(self, number: str, text: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        badge = QLabel(number)
        badge.setObjectName("licenseWelcomeStepBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(30, 30)

        label = QLabel(text)
        label.setObjectName("licenseWelcomeStepText")
        label.setWordWrap(True)
        set_rtl_label_text(label, text, multiline=True)

        row_layout.addWidget(badge, 0, Qt.AlignTop)
        row_layout.addWidget(label, 1)
        return row

    def _apply_status_copy(self) -> None:
        details = LicenseTab.get_license_details(self.hwid)
        status = details.get("status") or "missing"
        hero = self.findChild(QFrame, "licenseWelcomeHero")

        if status == "expired":
            title = "اعتبار لایسنس تمام شده"
            subtitle = (
                "اگر تمدید کرده‌اید، «بررسی مجدد لایسنس از سرور» را بزنید.\n"
                "یا از سایت پیچا درخواست ثبت کنید — شناسه دستگاه را در تیکت بفرستید."
            )
            tone = "expired"
        elif status == "revoked":
            title = "لایسنس باطل شده"
            subtitle = (
                "با peecha.ir تماس بگیرید.\n"
                "اگر دوباره فعال شد، «بررسی مجدد لایسنس از سرور» را بزنید."
            )
            tone = "expired"
        elif status == "invalid":
            title = details.get("hero_title") or "لایسنس قابل استفاده نیست"
            subtitle = (
                f"{details.get('hero_subtitle') or ''}\n\n"
                "برای صدور مجدد کلید، از سایت پیچا تیکت ثبت کنید."
            ).strip()
            tone = "invalid"
        else:
            title = "خوش آمدید"
            subtitle = (
                "برای شروع کار به لایسنس نیاز دارید.\n"
                "از طریق سایت پیچا درخواست دهید — معمولاً همان روز کلید صادر می‌شود."
            )
            tone = "missing"

        set_rtl_label_text(self.hero_title, title)
        set_rtl_label_text(self.hero_subtitle, subtitle, multiline=True)

        if hero is not None:
            hero.setProperty("licenseStatus", tone)
            hero.style().unpolish(hero)
            hero.style().polish(hero)

    def _copy_hwid(self) -> None:
        QApplication.clipboard().setText(self.hwid)
        QMessageBox.information(self, "کپی شد", "شناسه دستگاه در کلیپ‌بورد کپی شد.\nمی‌توانید در تیکت سایت پیچا بچسبانید.")

    def _open_site(self) -> None:
        open_external_url(self, self._site_url, "آدرس سایت پیچا در تنظیمات نیست.")

    def _open_support(self) -> None:
        open_external_url(
            self,
            self._support_url,
            "آدرس صفحه پشتیبانی در تنظیمات نیست.",
        )

    def _activate(self) -> None:
        key = self.license_input.text().strip()
        if not key:
            QMessageBox.warning(self, "کلید لایسنس", "کلید را وارد کنید یا ابتدا از سایت پیچا درخواست دهید.")
            return

        from sync_app.core.license_remote import merge_remote_cache, try_online_validate
        from sync_app.core.tabs.tab_license import license_file_path

        ok_remote, lic, err_remote = try_online_validate(key, self.hwid, activate=True)
        if ok_remote:
            merge_remote_cache(key, lic, self.hwid)
            QMessageBox.information(self, "فعال شد", "لایسنس فعال شد. برنامه آماده است.")
            if callable(self._on_activated):
                self._on_activated()
                self.close()
            return

        try:
            if LicenseTab.validate_key(key, self.hwid):
                import json

                with open(license_file_path(), "w", encoding="utf-8") as f:
                    json.dump({"license_key": key}, f)
                hint = ""
                if err_remote:
                    hint = f"\n\nاتصال به سرور برقرار نشد ({err_remote})؛ اعتبارسنجی آفلاین انجام شد."
                QMessageBox.information(self, "فعال شد", f"برنامه فعال شد.{hint}")
                if callable(self._on_activated):
                    self._on_activated()
                    self.close()
            else:
                detail = f"\n\nسرور: {err_remote}" if err_remote else ""
                QMessageBox.critical(
                    self,
                    "فعال‌سازی ناموفق",
                    f"این کلید برای این دستگاه معتبر نیست.{detail}\n\n"
                    "شناسه دستگاه را در تیکت سایت پیچا بفرستید.",
                )
        except Exception:
            QMessageBox.critical(self, "خطا", "فرمت کلید لایسنس اشتباه است.")
