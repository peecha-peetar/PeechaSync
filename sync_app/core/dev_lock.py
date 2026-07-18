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


def clear_dev_password() -> None:
    """پاک‌کردنِ کاملِ رمزِ دوم — دفعه‌ی بعد که ویرایش زده بشه، دوباره از
    کاربر یه رمزِ دومِ تازه خواسته می‌شه (همون مسیرِ اولین‌بار در
    prompt_unlock)."""
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    cfg.pop(DEV_LOCK_HASH_KEY, None)
    cfg.pop(DEV_LOCK_SALT_KEY, None)
    save_secure_config(cfg)


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


def prompt_change_password(parent, config: dict | None = None) -> bool:
    """رمزِ دومِ فعلی رو تأیید می‌کنه، بعد رمزِ جدید رو دوبار می‌گیره و
    جایگزین می‌کنه. خروجی: True یعنی با موفقیت عوض شد."""
    from PyQt5.QtWidgets import QInputDialog, QLineEdit, QMessageBox
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config if config is not None else (load_secure_config(None) or {})
    if not has_dev_password(cfg):
        QMessageBox.information(
            parent, "رمزی تنظیم نشده",
            "هنوز رمزِ دومی تعریف نشده — اول از دکمه‌ی «ویرایش» برایِ "
            "ساختنِ اولین رمز استفاده کنید.",
        )
        return False

    old_pw, ok0 = QInputDialog.getText(
        parent, "تأییدِ رمزِ فعلی", "رمزِ دومِ فعلیِ خود را وارد کنید:", QLineEdit.Password,
    )
    if not ok0:
        return False
    if not verify_dev_password(old_pw, cfg):
        QMessageBox.critical(parent, "رمز اشتباه", "رمزِ فعلی درست نیست.")
        return False

    pw1, ok1 = QInputDialog.getText(
        parent, "رمزِ دومِ جدید", "رمزِ دومِ جدید را وارد کنید:", QLineEdit.Password,
    )
    if not ok1 or not pw1.strip():
        return False
    pw2, ok2 = QInputDialog.getText(
        parent, "تکرارِ رمزِ جدید", "رمزِ جدید را دوباره وارد کنید:", QLineEdit.Password,
    )
    if not ok2 or pw2 != pw1:
        QMessageBox.warning(parent, "عدم تطابق", "رمزها یکسان نبودند. دوباره تلاش کنید.")
        return False

    set_dev_password(pw1)
    QMessageBox.information(parent, "رمز عوض شد", "رمزِ دوم با موفقیت تغییر کرد.")
    return True


def prompt_emergency_reset(parent) -> bool:
    """بازنشانیِ اضطراریِ رمزِ دوم — با کلیدِ ترکیبی صدا زده می‌شه، برایِ
    وقتی که رمزِ دوم فراموش شده. رمزِ فعلی رو کاملاً پاک می‌کنه؛ دفعه‌ی
    بعد که ویرایش زده بشه، از کاربر یه رمزِ دومِ تازه خواسته می‌شه.
    خروجی: True یعنی بازنشانی شد."""
    from PyQt5.QtWidgets import QMessageBox

    if not has_dev_password():
        QMessageBox.information(
            parent, "رمزی تنظیم نشده", "هنوز رمزِ دومی تعریف نشده — چیزی برای بازنشانی نیست.",
        )
        return False

    confirm = QMessageBox.question(
        parent,
        "بازنشانیِ اضطراریِ رمزِ دوم",
        "آیا مطمئنید می‌خواهید رمزِ دومِ فعلی (برایِ ویرایشِ تنظیماتِ حساس) "
        "کاملاً پاک شود؟\n\nدفعه‌ی بعد که خواستید ویرایش کنید، باید یک "
        "رمزِ دومِ تازه بسازید.",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if confirm != QMessageBox.Yes:
        return False

    clear_dev_password()
    QMessageBox.information(
        parent, "بازنشانی شد",
        "رمزِ دوم پاک شد. دفعه‌ی بعد که دکمه‌ی «ویرایش» را بزنید، یک "
        "رمزِ دومِ تازه خواهید ساخت.",
    )
    return True
