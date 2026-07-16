"""پیام راهنمای تطبیق هنگام شروع برنامه."""

from __future__ import annotations

from dataclasses import dataclass

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

from sync_app.core.app_theme import build_last_tab_restore_stylesheet, get_active_theme_palette


@dataclass
class ReconciliationStartupChoice:
    go_to_reconciliation: bool = False
    skip_prompt_next_time: bool = False


class ReconciliationStartupDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("lastTabRestoreDialog")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("تطبیق کالاهای سایت")
        self.setModal(True)
        self.setMinimumWidth(500)
        self._choice = ReconciliationStartupChoice()
        _theme_name, palette = get_active_theme_palette()
        self.setStyleSheet(build_last_tab_restore_stylesheet(palette))
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        info_box = QFrame()
        info_box.setObjectName("lastTabRestoreInfo")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(8)

        title = QLabel("⚖️ ابتدا کالاهای سایت را تطبیق دهید")
        title.setObjectName("lastTabRestoreInfoTitle")
        info_layout.addWidget(title)

        from sync_app.core.integrations.erp_provider import erp_provider_label
        from sync_app.core.secure_config_loader import load_secure_config

        message = QLabel(
            "اگر در فروشگاه ووکامرس شما <b>کالاهایی از قبل</b> وجود دارد که "
            f"هنوز با {erp_provider_label(load_secure_config(None))} تطبیق داده نشده‌اند، ابتدا باید آن‌ها را در تب "
            "«<b>تطبیق</b>» جفت و ثبت کنید.\n\n"
            "در غیر این صورت همگام‌سازی محصولات و متغیرها ممکن است "
            "به محصول اشتباه برود یا داده‌ها overwrite شوند."
        )
        message.setWordWrap(True)
        message.setTextFormat(Qt.RichText)
        message.setObjectName("lastTabRestoreInfoMessage")
        info_layout.addWidget(message)
        root.addWidget(info_box)

        hint = QLabel(
            "اگر فروشگاه تازه است و کالایی ندارید، می‌توانید «بعداً» را بزنید."
        )
        hint.setWordWrap(True)
        hint.setObjectName("lastTabRestoreHint")
        root.addWidget(hint)

        self.skip_cb = QCheckBox("دیگر این پیام را نمایش نده")
        root.addWidget(self.skip_cb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        no_btn = QPushButton("بعداً")
        no_btn.setObjectName("lastTabRestoreNo")
        no_btn.clicked.connect(self._choose_later)

        yes_btn = QPushButton("بله — برو به تب تطبیق")
        yes_btn.setObjectName("lastTabRestoreYes")
        yes_btn.setDefault(True)
        yes_btn.clicked.connect(self._choose_go)

        btn_row.addWidget(no_btn)
        btn_row.addWidget(yes_btn)
        root.addLayout(btn_row)

    def _finalize(self):
        self._choice.skip_prompt_next_time = self.skip_cb.isChecked()
        self.accept()

    def _choose_later(self):
        self._choice.go_to_reconciliation = False
        self._finalize()

    def _choose_go(self):
        self._choice.go_to_reconciliation = True
        self._finalize()

    @staticmethod
    def ask(parent) -> ReconciliationStartupChoice:
        dialog = ReconciliationStartupDialog(parent)
        dialog.raise_()
        dialog.activateWindow()
        dialog.exec_()
        return dialog._choice


def ask_reconciliation_startup(parent) -> ReconciliationStartupChoice:
    return ReconciliationStartupDialog.ask(parent)
