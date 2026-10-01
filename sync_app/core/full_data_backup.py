"""خروجی/بازگردانیِ کاملِ پوشهٔ دادهٔ برنامه (تنظیمات رمزنگاری‌شده + کلیدِ
رمزگشایی + همهٔ فایل‌هایِ لینکِ تطبیقِ همهٔ سایت‌ها/پروفایل‌ها).

بکاپِ موجودِ تنظیمات (secure_config_loader.py) و بازیابیِ scope سایت
(site_scope_recovery.py) هر دو فقط **داخلِ همین پوشه‌یِ دادهٔ برنامه**
کار می‌کنن — یعنی اگه کلِ این پوشه (نه فقط برنامه) پاک بشه (فرمت/ریستِ
ویندوز، تعویضِ سیستم، حذفِ کاملِ AppData)، هیچ‌کدومشون کمکی نمی‌کنن،
چون خودشون هم همون‌جا بودن.

این ماژول کلِ پوشه رو در یک فایلِ zip می‌ریزه که کاربر خودش بیرون از
سیستم (فلش/ابر) نگه می‌داره، و یک مسیرِ بازگردانی هم داره.

⚠️ فایلِ خروجی شاملِ sync_key.key است — یعنی هرکسی این فایل رو داشته
باشه می‌تونه secure_config.bin (رمزِ دیتابیس، کلیدهایِ API فروشگاه،
کلیدِ لایسنس) رو رمزگشایی کنه. این فایل هیچ‌وقت نباید جایِ عمومی/غیرِامن
آپلود بشه."""

from __future__ import annotations

import os
import shutil
import time
import zipfile

_EXCLUDED_SUFFIXES = (".log",)
_EXCLUDED_DIR_NAMES = {"__pycache__"}
_EXCLUDED_PREFIX = "_pre_restore_backup_"


def _data_root() -> str:
    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(local, "PeechaSync")


def export_full_backup(dest_zip_path: str) -> dict:
    """کلِ پوشهٔ دادهٔ برنامه (همهٔ پروفایل‌ها/سایت‌ها) رو در یک zip می‌ریزه."""
    root = _data_root()
    if not os.path.isdir(root):
        raise RuntimeError("پوشهٔ دادهٔ برنامه پیدا نشد.")

    file_count = 0
    total_size = 0
    with zipfile.ZipFile(dest_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in _EXCLUDED_DIR_NAMES and not d.startswith(_EXCLUDED_PREFIX)
            ]
            for fn in filenames:
                if fn.lower().endswith(_EXCLUDED_SUFFIXES):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                try:
                    zf.write(full, rel)
                    file_count += 1
                    total_size += os.path.getsize(full)
                except OSError:
                    continue

    return {"file_count": file_count, "total_size": total_size, "path": dest_zip_path}


def _safe_extract_path(root: str, member_name: str) -> str | None:
    """گاردِ zip-slip — مسیری که بعدِ join از زیرِ root بیرون بزنه رد می‌شه."""
    if not member_name:
        return None
    target = os.path.normpath(os.path.join(root, member_name))
    root_norm = os.path.normpath(root)
    if target != root_norm and not target.startswith(root_norm + os.sep):
        return None
    return target


def import_full_backup(src_zip_path: str) -> dict:
    """محتوایِ zip رو رویِ پوشهٔ دادهٔ فعلی اکسترکت می‌کنه (رونویسی) —
    قبلش از هر چیزی که الان هست یک بکاپِ کامل می‌گیره."""
    root = _data_root()
    os.makedirs(root, exist_ok=True)

    existing_files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(_EXCLUDED_PREFIX)]
        for fn in filenames:
            existing_files.append(os.path.join(dirpath, fn))

    backup_dir = None
    if existing_files:
        backup_dir = os.path.join(root, f"{_EXCLUDED_PREFIX}{int(time.time())}")
        for full in existing_files:
            rel = os.path.relpath(full, root)
            dest = os.path.join(backup_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                shutil.copy2(full, dest)
            except OSError:
                continue

    extracted = 0
    with zipfile.ZipFile(src_zip_path, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            target = _safe_extract_path(root, member.filename)
            if not target:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted += 1

    return {"extracted": extracted, "backup_dir": backup_dir, "root": root}
