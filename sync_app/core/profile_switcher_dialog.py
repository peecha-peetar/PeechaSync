"""دیالوگِ تعویضِ پروفایل — هر پروفایل شاملِ دیتابیس، پلتفرمِ فروشگاه
(ووکامرس/پرستاشاپ)، تمِ ظاهری و همه‌ی تنظیماتِ دیگر به‌صورتِ کاملاً
جداست. تعویضِ پروفایل نیازمندِ راه‌اندازیِ مجددِ برنامه است چون کانکشن‌های
SQL، تایمرها و کش‌های در حالِ اجرا همه به پروفایلِ قبلی وابسته‌اند."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from sync_app.core.user_profile import (
    get_current_profile_id,
    list_profile_ids,
    sanitize_profile_id,
    save_last_profile_id,
)


class ProfileSwitcherDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تعویض پروفایل")
        self.setMinimumWidth(420)
        self.setLayoutDirection(Qt.RightToLeft)
        self.selected_profile_id: str | None = None

        layout = QVBoxLayout(self)

        info = QLabel(
            "هر پروفایل تنظیمات کاملاً جدایی دارد: دیتابیس، پلتفرم فروشگاه "
            "(ووکامرس/پرستاشاپ)، آدرس و کلید فروشگاه، تم و بقیه‌ی تنظیمات.\n"
            "با انتخاب یا ساخت یک پروفایل، برنامه بسته و دوباره با آن پروفایل باز می‌شود."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#475569; font-size:11px;")
        layout.addWidget(info)

        current_id = get_current_profile_id() or ""
        layout.addWidget(QLabel(f"پروفایل فعلی: {current_id or '—'}"))

        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(140)
        for pid in list_profile_ids():
            item = QListWidgetItem(pid)
            if pid == current_id:
                item.setText(f"{pid}  (فعلی)")
            self.list_widget.addItem(item)
            if pid == current_id:
                self.list_widget.setCurrentItem(item)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._confirm_selected())
        layout.addWidget(self.list_widget)

        new_row = QHBoxLayout()
        self.new_profile_input = QLineEdit()
        self.new_profile_input.setPlaceholderText("نام پروفایل جدید (مثلاً shop2)")
        self.new_profile_input.setLayoutDirection(Qt.LeftToRight)
        new_row.addWidget(self.new_profile_input, 1)
        new_btn = QPushButton("➕ ساخت و تعویض")
        new_btn.clicked.connect(self._confirm_new)
        new_row.addWidget(new_btn)
        layout.addLayout(new_row)

        actions_row = QHBoxLayout()
        actions_row.addStretch()
        cancel_btn = QPushButton("انصراف")
        cancel_btn.clicked.connect(self.reject)
        actions_row.addWidget(cancel_btn)
        switch_btn = QPushButton("تعویض به انتخاب‌شده")
        switch_btn.setDefault(True)
        switch_btn.clicked.connect(self._confirm_selected)
        actions_row.addWidget(switch_btn)
        layout.addLayout(actions_row)

    def _confirm_selected(self):
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.warning(self, "پروفایل", "یک پروفایل از لیست انتخاب کنید یا یک پروفایل جدید بسازید.")
            return
        pid = item.text().split("  (")[0].strip()
        self._switch_to(pid)

    def _confirm_new(self):
        raw = (self.new_profile_input.text() or "").strip()
        if not raw:
            QMessageBox.warning(self, "پروفایل", "نام پروفایل جدید را وارد کنید.")
            return
        self._switch_to(sanitize_profile_id(raw))

    def _switch_to(self, profile_id: str):
        current_id = get_current_profile_id() or ""
        if profile_id == current_id:
            QMessageBox.information(self, "پروفایل", "این همان پروفایل فعلی است.")
            return
        confirm = QMessageBox.question(
            self,
            "تعویض پروفایل",
            f"برنامه بسته و با پروفایل «{profile_id}» دوباره باز می‌شود. ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.selected_profile_id = profile_id
        save_last_profile_id(profile_id)
        self.accept()
