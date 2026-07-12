"""دیالوگ‌های استاندارد با چیدمان RTL و برچسب فارسی."""

from __future__ import annotations

import html

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


def rtl_html(text: str) -> str:
    """راست‌چین واقعی QLabel — align=right + dir=rtl."""
    body = html.escape(text or "").replace("\n", "<br>")
    return f'<div align="right" dir="rtl">{body}</div>'


def set_rtl_label_text(label: QLabel, text: str, *, multiline: bool = False) -> None:
    from PyQt5.QtWidgets import QSizePolicy

    label.setTextFormat(Qt.RichText)
    label.setText(rtl_html(text))
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    if multiline:
        label.setWordWrap(True)


class FaYesNoDialog(QDialog):
    """دیالوگ بله/خیر با چیدمان راست‌به‌چپ واقعی."""

    def __init__(
        self,
        parent,
        title: str,
        text: str,
        *,
        tone: str = "question",
        default_yes: bool = False,
    ):
        super().__init__(parent)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self._confirmed = False
        self._build_ui(text, tone=tone, default_yes=default_yes)

    def _build_ui(self, text: str, *, tone: str, default_yes: bool):
        self.setStyleSheet("QDialog { background-color: #f8fafc; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        banner_styles = {
            "question": ("#eff6ff", "#93c5fd", "#1d4ed8", "#1e3a8a", "❓"),
            "warning": ("#fffbeb", "#fcd34d", "#b45309", "#92400e", "⚠️"),
        }
        bg, border, title_color, body_color, icon = banner_styles.get(
            tone, banner_styles["question"]
        )

        box = QFrame()
        box.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {border}; "
            "border-radius: 10px; }"
        )
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(14, 12, 14, 12)
        box_layout.setSpacing(12)

        icon_label = QLabel(icon)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(
            f"color: {title_color}; font-size: 28px; background: transparent;"
        )
        box_layout.addWidget(icon_label)

        message = QLabel(text.replace("\n", "<br>"))
        message.setWordWrap(True)
        message.setTextFormat(Qt.RichText)
        message.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        message.setStyleSheet(
            f"color: {body_color}; font-size: 13px; background: transparent;"
        )
        box_layout.addWidget(message, 1)
        root.addWidget(box)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        yes_btn = QPushButton("بله")
        yes_btn.setMinimumHeight(40)
        yes_btn.setMinimumWidth(96)
        yes_btn.setDefault(default_yes)
        yes_btn.setStyleSheet(
            "QPushButton { background-color: #1a2785; color: #ffffff; border-radius: 8px; "
            "font-weight: 700; padding: 8px 14px; }"
            "QPushButton:hover { background-color: #243399; }"
        )
        yes_btn.clicked.connect(self._accept_yes)

        no_btn = QPushButton("خیر")
        no_btn.setMinimumHeight(40)
        no_btn.setMinimumWidth(96)
        no_btn.setDefault(not default_yes)
        no_btn.setStyleSheet(
            "QPushButton { background-color: #e2e8f0; color: #0f172a; border-radius: 8px; "
            "font-weight: 700; padding: 8px 14px; }"
            "QPushButton:hover { background-color: #cbd5e1; }"
        )
        no_btn.clicked.connect(self.reject)

        btn_row.addWidget(yes_btn)
        btn_row.addWidget(no_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

    def _accept_yes(self):
        self._confirmed = True
        self.accept()

    @staticmethod
    def ask(
        parent,
        title: str,
        text: str,
        *,
        tone: str = "question",
        default_yes: bool = False,
    ) -> bool:
        dialog = FaYesNoDialog(
            parent,
            title,
            text,
            tone=tone,
            default_yes=default_yes,
        )
        dialog.exec_()
        return dialog._confirmed


def ask_yes_no(
    parent,
    title: str,
    text: str,
    *,
    icon=QMessageBox.Question,
    tone: str | None = None,
    default_yes: bool = False,
) -> bool:
    """سؤال بله/خیر با دیالوگ RTL."""
    if tone is None:
        tone = "warning" if icon in (QMessageBox.Warning, QMessageBox.Critical) else "question"
    return FaYesNoDialog.ask(
        parent,
        title,
        text,
        tone=tone,
        default_yes=default_yes,
    )


_BUTTON_LABELS = {
    QMessageBox.Yes: "بله",
    QMessageBox.No: "خیر",
    QMessageBox.Ok: "تأیید",
    QMessageBox.Cancel: "لغو",
    QMessageBox.Close: "بستن",
    QMessageBox.Abort: "قطع",
    QMessageBox.Retry: "تلاش مجدد",
    QMessageBox.Ignore: "نادیده",
}


def localize_message_box_buttons(box: QMessageBox) -> None:
    for role, label in _BUTTON_LABELS.items():
        btn = box.button(role)
        if btn is not None:
            btn.setText(label)


def _exec_standard_box(parent, title, text, icon, buttons, default_button):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)
    box.setStandardButtons(buttons)
    if default_button != QMessageBox.NoButton:
        box.setDefaultButton(default_button)
    localize_message_box_buttons(box)
    return box.exec_()


def install_persian_message_boxes() -> None:
    """برچسب فارسی برای همه QMessageBoxهای استاندارد."""
    if getattr(QMessageBox, "_peecha_fa_installed", False):
        return

    @staticmethod
    def question(parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No, defaultButton=QMessageBox.No):
        return _exec_standard_box(parent, title, text, QMessageBox.Question, buttons, defaultButton)

    @staticmethod
    def information(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        return _exec_standard_box(parent, title, text, QMessageBox.Information, buttons, defaultButton)

    @staticmethod
    def warning(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        return _exec_standard_box(parent, title, text, QMessageBox.Warning, buttons, defaultButton)

    @staticmethod
    def critical(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):
        return _exec_standard_box(parent, title, text, QMessageBox.Critical, buttons, defaultButton)

    QMessageBox.question = question
    QMessageBox.information = information
    QMessageBox.warning = warning
    QMessageBox.critical = critical

    _orig_exec = QMessageBox.exec_

    def exec_fa(self, *args, **kwargs):
        localize_message_box_buttons(self)
        return _orig_exec(self, *args, **kwargs)

    QMessageBox.exec_ = exec_fa
    QMessageBox._peecha_fa_installed = True
