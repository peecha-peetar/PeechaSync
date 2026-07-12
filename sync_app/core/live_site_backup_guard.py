"""هشدار بکاپ قبل از عملیات روی سایت واقعی."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from sync_app.core.app_theme import build_live_site_backup_stylesheet, get_active_theme_palette


class LiveSiteBackupDialog(QDialog):
    """دیالوگ هشدار — ادامه فقط پس از تیک تأیید بکاپ؛ تم برنامه + لایه هشدار جدی."""

    def __init__(self, parent, action_label: str):
        super().__init__(parent)
        self.setObjectName("liveSiteBackupDialog")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("⛔ هشدار جدی — بکاپ الزامی")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._confirmed = False
        _theme_name, palette = get_active_theme_palette()
        self.setStyleSheet(build_live_site_backup_stylesheet(palette))
        self._build_ui(action_label)

    def _build_ui(self, action_label: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        danger_strip = QFrame()
        danger_strip.setObjectName("liveSiteBackupDangerStrip")
        root.addWidget(danger_strip)

        banner = QFrame()
        banner.setObjectName("liveSiteBackupBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(14, 12, 14, 12)
        banner_layout.setSpacing(12)

        icon_badge = QLabel("⛔")
        icon_badge.setObjectName("liveSiteBackupIconBadge")
        icon_badge.setAlignment(Qt.AlignCenter)
        banner_layout.addWidget(icon_badge)

        banner_text = QVBoxLayout()
        banner_text.setSpacing(4)

        banner_title = QLabel("هشدار جدی — قبل از ادامه، بکاپ بگیرید")
        banner_title.setObjectName("liveSiteBackupBannerTitle")
        banner_title.setWordWrap(True)
        banner_text.addWidget(banner_title)

        banner_sub = QLabel(
            "سایت واقعی است — بدون بکاپ، داده‌های فروشگاه ممکن است برای همیشه از بین برود."
        )
        banner_sub.setObjectName("liveSiteBackupBannerSub")
        banner_sub.setWordWrap(True)
        banner_text.addWidget(banner_sub)
        banner_layout.addLayout(banner_text, 1)
        root.addWidget(banner)

        risk_callout = QFrame()
        risk_callout.setObjectName("liveSiteBackupRiskCallout")
        risk_layout = QVBoxLayout(risk_callout)
        risk_layout.setContentsMargins(12, 10, 12, 10)
        risk_text = QLabel(
            "🚨 این عملیات روی فروشگاه زنده است — در صورت اشتباه، "
            "بازگردانی فقط با بکاپ معتبر ممکن است."
        )
        risk_text.setObjectName("liveSiteBackupRiskText")
        risk_text.setWordWrap(True)
        risk_layout.addWidget(risk_text)
        root.addWidget(risk_callout)

        info_box = QFrame()
        info_box.setObjectName("liveSiteBackupInfo")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(10)

        lead = QLabel(
            "سایت شما <b>داده واقعی</b> دارد. قبل از هرگونه تغییر در فروشگاه، "
            "حتماً از موارد زیر بکاپ بگیرید:"
        )
        lead.setWordWrap(True)
        lead.setTextFormat(Qt.RichText)
        lead.setObjectName("liveSiteBackupLead")
        info_layout.addWidget(lead)

        checklist = QFrame()
        checklist.setObjectName("liveSiteBackupChecklist")
        checklist_layout = QVBoxLayout(checklist)
        checklist_layout.setContentsMargins(12, 10, 12, 10)
        checklist_layout.setSpacing(6)

        for line in (
            "۱) دیتابیس وردپرس / ووکامرس",
            "۲) فایل‌های سایت (wp-content)",
            "۳) در صورت نیاز: دیتابیس ERP (SQL Server)",
        ):
            item = QLabel(f"• {line}")
            item.setObjectName("liveSiteBackupCheckItem")
            checklist_layout.addWidget(item)
        info_layout.addWidget(checklist)
        root.addWidget(info_box)

        action_box = QFrame()
        action_box.setObjectName("liveSiteBackupActionBox")
        action_layout = QVBoxLayout(action_box)
        action_layout.setContentsMargins(12, 10, 12, 10)
        action_hint = QLabel(f"⚠️ عملیات درخواستی: <b>{action_label}</b>")
        action_hint.setWordWrap(True)
        action_hint.setTextFormat(Qt.RichText)
        action_hint.setObjectName("liveSiteBackupAction")
        action_layout.addWidget(action_hint)
        root.addWidget(action_box)

        self.confirm_cb = QCheckBox("بکاپ کامل گرفته‌ام و مسئولیت ادامه را می‌پذیرم")
        self.confirm_cb.toggled.connect(self._sync_continue_enabled)
        root.addWidget(self.confirm_cb)

        warn_footer = QLabel(
            "تا زمانی که بکاپ نگرفته‌اید، «انصراف» را بزنید و ابتدا از هاست یا پلاگین backup اقدام کنید."
        )
        warn_footer.setWordWrap(True)
        warn_footer.setObjectName("liveSiteBackupHint")
        root.addWidget(warn_footer)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.cancel_btn = QPushButton("انصراف — فعلاً انجام نده")
        self.cancel_btn.setObjectName("liveSiteBackupCancel")
        self.cancel_btn.setMinimumHeight(44)
        self.cancel_btn.setDefault(True)
        self.cancel_btn.clicked.connect(self.reject)

        self.continue_btn = QPushButton("بکاپ گرفتم — ادامه عملیات")
        self.continue_btn.setObjectName("liveSiteBackupContinue")
        self.continue_btn.setMinimumHeight(44)
        self.continue_btn.setEnabled(False)
        self.continue_btn.clicked.connect(self._accept_confirmed)

        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.continue_btn)
        root.addLayout(btn_row)

    def _sync_continue_enabled(self, checked: bool):
        self.continue_btn.setEnabled(bool(checked))

    def _accept_confirmed(self):
        if not self.confirm_cb.isChecked():
            return
        self._confirmed = True
        self.accept()

    @staticmethod
    def ask(parent, action_label: str) -> bool:
        dialog = LiveSiteBackupDialog(parent, action_label)
        dialog.exec_()
        return dialog._confirmed


def confirm_live_site_backup(parent, action_label: str) -> bool:
    """
    قبل از نگاشت یا ارسال به فروشگاه live، از کاربر تأیید بکاپ می‌گیرد.

    action_label: عنوان عملیات در متن پیام (مثلاً «ثبت تطبیق انتخاب‌ها»)
    """
    return LiveSiteBackupDialog.ask(parent, action_label)
