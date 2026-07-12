"""پرسش سبک برای ادامه از آخرین تب هنگام باز شدن برنامه."""

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
class LastTabRestoreChoice:
    go_to_last_tab: bool = False
    skip_prompt_next_time: bool = False


class LastTabRestoreDialog(QDialog):
    def __init__(self, parent, tab_label: str):
        super().__init__(parent)
        self.setObjectName("lastTabRestoreDialog")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("ادامه از آخرین تب")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._choice = LastTabRestoreChoice()
        _theme_name, palette = get_active_theme_palette()
        self.setStyleSheet(build_last_tab_restore_stylesheet(palette))
        self._build_ui(tab_label)

    def _build_ui(self, tab_label: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        info_box = QFrame()
        info_box.setObjectName("lastTabRestoreInfo")
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.setSpacing(8)

        title = QLabel("ℹ️ آخرین جایگاه کاری شما")
        title.setObjectName("lastTabRestoreInfoTitle")
        info_layout.addWidget(title)

        message = QLabel(
            f"آخرین بار در تب <b>{tab_label}</b> بودید.\n"
            "آیا می‌خواهید از همان تب ادامه دهید؟"
        )
        message.setWordWrap(True)
        message.setTextFormat(Qt.RichText)
        message.setObjectName("lastTabRestoreInfoMessage")
        info_layout.addWidget(message)
        root.addWidget(info_box)

        hint = QLabel(
            "در صورت «خیر»، در تب «شروع» می‌مانید و می‌توانید از مسیر استاندارد پیش بروید."
        )
        hint.setWordWrap(True)
        hint.setObjectName("lastTabRestoreHint")
        root.addWidget(hint)

        self.skip_cb = QCheckBox("دیگر نپرس — همیشه آخرین تب را مستقیم باز کن")
        root.addWidget(self.skip_cb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        no_btn = QPushButton("خیر — بمان در «شروع»")
        no_btn.setObjectName("lastTabRestoreNo")
        no_btn.clicked.connect(self._choose_stay)

        yes_btn = QPushButton("بله — برو به همان تب")
        yes_btn.setObjectName("lastTabRestoreYes")
        yes_btn.setDefault(True)
        yes_btn.clicked.connect(self._choose_go)

        btn_row.addWidget(no_btn)
        btn_row.addWidget(yes_btn)
        root.addLayout(btn_row)

    def _finalize(self):
        self._choice.skip_prompt_next_time = self.skip_cb.isChecked()
        self.accept()

    def _choose_stay(self):
        self._choice.go_to_last_tab = False
        self._finalize()

    def _choose_go(self):
        self._choice.go_to_last_tab = True
        self._finalize()

    @staticmethod
    def ask(parent, tab_label: str) -> LastTabRestoreChoice:
        dialog = LastTabRestoreDialog(parent, tab_label)
        dialog.exec_()
        return dialog._choice


def ask_restore_last_tab(parent, tab_label: str) -> LastTabRestoreChoice:
    return LastTabRestoreDialog.ask(parent, tab_label)
