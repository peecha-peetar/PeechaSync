# انتخاب login وردپرس از لیست کاربران سایت

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


def _role_label_fa(roles: list[str]) -> str:
    mapping = {
        "administrator": "مدیر",
        "shop_manager": "مدیر فروشگاه",
        "editor": "ویرایشگر",
        "author": "نویسنده",
        "contributor": "مشارکت‌کننده",
        "subscriber": "مشترک",
        "customer": "مشتری",
    }
    if not roles:
        return "نقش نامشخص"
    primary = str(roles[0] or "").lower()
    return mapping.get(primary, primary or "کاربر")


def _user_item_text(user: dict) -> str:
    username = str(user.get("username") or "").strip()
    name = str(user.get("name") or "").strip()
    role_txt = _role_label_fa(user.get("roles") or [])
    parts = [username]
    if name and name.lower() != username.lower():
        parts.append(f"({name})")
    parts.append(f"— {role_txt}")
    if user.get("verified_match"):
        parts.append("✓ رمز Application Password با این کاربر سازگار است")
    return " ".join(parts)


class WpUsernamePickerDialog(QDialog):
    def __init__(self, parent=None, *, users=None, title="", message="", current_username=""):
        super().__init__(parent)
        self.setWindowTitle(title or "انتخاب نام کاربری وردپرس")
        self.setMinimumSize(520, 420)
        self.setLayoutDirection(Qt.RightToLeft)
        self._selected_username = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        msg = QLabel(message or "یکی از نام‌های کاربری زیر را انتخاب کنید:")
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 13px; font-weight: 600; color: #1e293b;")
        root.addWidget(msg)

        hint = QLabel(
            "نام کاربری (Username) همان login است که در Users → All Users می‌بینید — "
            "نه نام نمایشی و نه عنوان Application Password."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        root.addWidget(hint)

        self._list = QListWidget()
        self._list.setLayoutDirection(Qt.LeftToRight)
        self._list.setMinimumHeight(220)
        root.addWidget(self._list, 1)

        current = (current_username or "").strip().lower()
        preselect_row = -1
        for idx, user in enumerate(users or []):
            username = str(user.get("username") or "").strip()
            if not username:
                continue
            item = QListWidgetItem(_user_item_text(user))
            item.setData(Qt.UserRole, username)
            if user.get("is_admin"):
                item.setToolTip("کاربر مدیر — برای آپلود تصویر توصیه می‌شود.")
            if user.get("verified_match"):
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._list.addItem(item)
            if current and username.lower() == current:
                preselect_row = self._list.count() - 1

        if self._list.count() == 0:
            empty = QLabel("کاربری از سایت دریافت نشد.")
            empty.setStyleSheet("color: #b91c1c; font-weight: 600;")
            root.addWidget(empty)
        elif preselect_row >= 0:
            self._list.setCurrentRow(preselect_row)
        else:
            self._list.setCurrentRow(0)

        self._list.itemDoubleClicked.connect(self._accept_selection)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("انصراف")
        cancel_btn.setMinimumHeight(38)
        cancel_btn.clicked.connect(self.reject)
        select_btn = QPushButton("انتخاب این نام کاربری")
        select_btn.setMinimumHeight(38)
        select_btn.setStyleSheet(
            "background-color: #2563eb; color: white; border-radius: 8px; "
            "padding: 8px 16px; font-weight: 700;"
        )
        select_btn.clicked.connect(self._accept_selection)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(select_btn)
        root.addLayout(btn_row)

    def _accept_selection(self):
        item = self._list.currentItem()
        if item is None:
            QMessageBox.warning(self, "انتخاب نشده", "لطفاً یک نام کاربری از لیست انتخاب کنید.")
            return
        self._selected_username = str(item.data(Qt.UserRole) or "").strip()
        if not self._selected_username:
            QMessageBox.warning(self, "نامعتبر", "نام کاربری انتخاب‌شده معتبر نیست.")
            return
        self.accept()

    @property
    def selected_username(self) -> str:
        return self._selected_username


def pick_wp_username(
    parent,
    users,
    *,
    title="",
    message="",
    current_username="",
) -> str | None:
    if not users:
        return None
    dlg = WpUsernamePickerDialog(
        parent,
        users=users,
        title=title,
        message=message,
        current_username=current_username,
    )
    if dlg.exec_() != QDialog.Accepted:
        return None
    return dlg.selected_username or None
