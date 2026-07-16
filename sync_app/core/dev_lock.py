"""
قفل «ویرایش» برای تب‌های حساس (تنظیمات، فعال‌سازی، همگام‌سازی خودکار) —
این تب‌ها به‌طور پیش‌فرض فقط‌خواندنی هستن و فقط با یک رمز دوم (که فقط
توسعه‌دهنده می‌دونه) قابل ویرایش می‌شن. رمز به‌صورت هش‌شده (نه متن ساده)
داخل همون فایل تنظیمات رمزنگاری‌شده‌ی برنامه ذخیره می‌شه.
"""

from __future__ import annotations

import hashlib
import secrets

DEV_LOCK_HASH_KEY = "DEV_LOCK_PASSWORD_HASH"
DEV_LOCK_SALT_KEY = "DEV_LOCK_PASSWORD_SALT"


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def has_dev_password(config: dict | None = None) -> bool:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config if config is not None else (load_secure_config(None) or {})
    return bool(cfg.get(DEV_LOCK_HASH_KEY))


def set_dev_password(password: str) -> None:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    salt = secrets.token_hex(16)
    cfg[DEV_LOCK_SALT_KEY] = salt
    cfg[DEV_LOCK_HASH_KEY] = _hash_password(password, salt)
    save_secure_config(cfg)


def verify_dev_password(password: str, config: dict | None = None) -> bool:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config if config is not None else (load_secure_config(None) or {})
    salt = str(cfg.get(DEV_LOCK_SALT_KEY, ""))
    expected = str(cfg.get(DEV_LOCK_HASH_KEY, ""))
    if not expected or not password:
        return False
    return _hash_password(password, salt) == expected


def apply_lock_state(root_widget, locked: bool, exclude_names: set | None = None) -> None:
    """
    همه‌ی ویجت‌های قابل‌ویرایشِ زیرمجموعه‌ی root_widget رو قفل/باز می‌کنه.
    دکمه‌ی خودِ «ویرایش/قفل» باید با setObjectName مشخص و تو exclude_names
    باشه تا خودش غیرفعال نشه.
    """
    from PyQt5.QtWidgets import (
        QLineEdit, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
        QTextEdit, QPlainTextEdit, QPushButton, QListWidget, QRadioButton,
    )

    exclude_names = exclude_names or set()
    editable_types = (
        QLineEdit, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox,
        QTextEdit, QPlainTextEdit, QPushButton, QListWidget, QRadioButton,
    )
    for widget in root_widget.findChildren(editable_types):
        if widget.objectName() in exclude_names:
            continue
        widget.setEnabled(not locked)


def prompt_unlock(parent, config: dict | None = None) -> bool:
    """
    یه دیالوگ رمز نشون می‌ده. اگه رمز دومی هنوز تنظیم نشده، اول از کاربر
    (توسعه‌دهنده) می‌خواد یکی بسازه. رمز واقعی هیچ‌وقت لاگ/نمایش داده نمی‌شه.
    خروجی: True یعنی باز شد.
    """
    from PyQt5.QtWidgets import QInputDialog, QLineEdit, QMessageBox
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config if config is not None else (load_secure_config(None) or {})

    if not has_dev_password(cfg):
        pw1, ok1 = QInputDialog.getText(
            parent, "ساخت رمز دوم (اولین بار)",
            "رمز دومی برای ویرایش تنظیمات حساس تعریف نشده.\n"
            "یک رمز جدید بسازید (این رمز فقط پیش خودتان بماند):",
            QLineEdit.Password,
        )
        if not ok1 or not pw1.strip():
            return False
        pw2, ok2 = QInputDialog.getText(
            parent, "تکرار رمز", "رمز را دوباره وارد کنید:", QLineEdit.Password,
        )
        if not ok2 or pw2 != pw1:
            QMessageBox.warning(parent, "عدم تطابق", "رمزها یکسان نبودند. دوباره تلاش کنید.")
            return False
        set_dev_password(pw1)
        QMessageBox.information(
            parent, "رمز ساخته شد",
            "رمز دوم ساخته و ذخیره شد. این رمز را جایی امن یادداشت کنید — "
            "بدون آن، ویرایش این بخش‌ها ممکن نخواهد بود.",
        )
        return True

    pw, ok = QInputDialog.getText(
        parent, "ورود رمز دوم", "برای ویرایش، رمز دوم را وارد کنید:", QLineEdit.Password,
    )
    if not ok:
        return False
    if verify_dev_password(pw, cfg):
        return True
    QMessageBox.critical(parent, "رمز اشتباه", "رمز وارد شده درست نیست.")
    return False
