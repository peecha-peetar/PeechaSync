"""پروفایل کاربر — تنظیمات و فایل‌های داده هر کاربر جدا ذخیره می‌شوند."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys

_current_profile_id: str | None = None

APP_STATE_FILE_NAME = "app_state.json"
PROFILE_CONFIG_NAME = "secure_config.bin"
PROFILE_KEY_NAME = "sync_key.key"

USER_DATA_FILES = (
    "product_woo_map.json",
    "product_woo_map_meta.json",
    "category_map.json",
    "category_images_map.json",
    "product_images_map.json",
    "sync.log",
)


def profiles_root() -> str:
    env_path = (os.getenv("PEECHA_PROFILES_DIR") or "").strip()
    if env_path:
        return os.path.normpath(env_path)
    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(local, "PeechaSync", "profiles")


def app_state_path() -> str:
    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(local, "PeechaSync", APP_STATE_FILE_NAME)


def sanitize_profile_id(username: str) -> str:
    name = (username or "").strip().lower()
    name = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE)
    name = name.strip("_")
    return name or "default"


def get_current_profile_id() -> str | None:
    return _current_profile_id


def get_current_profile_display_name() -> str:
    return _current_profile_id or ""


def profile_dir(profile_id: str | None = None) -> str:
    pid = sanitize_profile_id(profile_id or _current_profile_id or "default")
    return os.path.join(profiles_root(), pid)


def ensure_profile_dir(profile_id: str | None = None) -> str:
    path = profile_dir(profile_id)
    os.makedirs(path, exist_ok=True)
    return path


def profile_data_path(*parts, profile_id: str | None = None) -> str:
    return os.path.join(ensure_profile_dir(profile_id), *parts)


def activate_profile(profile_id: str) -> str:
    """پروفایل فعال را تنظیم می‌کند (بعد از ورود موفق)."""
    global _current_profile_id
    pid = sanitize_profile_id(profile_id)
    _current_profile_id = pid
    ensure_profile_dir(pid)
    try:
        from sync_app.core.sync_utils import reconfigure_app_logging

        reconfigure_app_logging()
    except Exception:
        pass
    return pid


def load_app_state() -> dict:
    path = app_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_app_state(state: dict) -> None:
    path = app_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state or {}, f, indent=2, ensure_ascii=False)


def save_last_profile_id(profile_id: str) -> None:
    state = load_app_state()
    state["last_profile"] = sanitize_profile_id(profile_id)
    save_app_state(state)


def load_last_profile_id() -> str:
    state = load_app_state()
    return sanitize_profile_id(str(state.get("last_profile") or "")) if state.get("last_profile") else ""


def list_profile_ids() -> list[str]:
    root = profiles_root()
    if not os.path.isdir(root):
        return []
    ids = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            ids.append(name)
    return sorted(ids)


def _legacy_base_paths() -> list[str]:
    paths: list[str] = []
    env_path = (os.getenv("PEECHA_CONFIG_DIR") or "").strip()
    if env_path:
        paths.append(env_path)
    if getattr(sys, "frozen", False):
        paths.append(os.path.dirname(sys.executable))
    paths.append(os.path.dirname(os.path.abspath(__file__)))
    paths.append(os.getcwd())
    unique: list[str] = []
    seen = set()
    for p in paths:
        np = os.path.normpath(p)
        if np not in seen:
            seen.add(np)
            unique.append(np)
    return unique


def _legacy_writable_dirs() -> list[str]:
    dirs = _legacy_base_paths()
    if getattr(sys, "frozen", False):
        dirs.insert(0, os.path.dirname(sys.executable))
    else:
        dirs.insert(0, os.getcwd())
    unique: list[str] = []
    seen = set()
    for d in dirs:
        nd = os.path.normpath(d)
        if nd not in seen:
            seen.add(nd)
            unique.append(nd)
    return unique


def _copy_if_exists(src: str, dest: str) -> bool:
    if not src or not os.path.exists(src):
        return False
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isdir(src):
        if os.path.exists(dest):
            return False
        shutil.copytree(src, dest)
        return True
    if os.path.exists(dest):
        return False
    shutil.copy2(src, dest)
    return True


def migrate_legacy_profiles(log=None) -> str | None:
    """
    اولین اجرا: تنظیمات و mapهای قدیمی را به پروفایل کاربر قبلی منتقل می‌کند.
    """
    if list_profile_ids():
        return load_last_profile_id() or None

    legacy_config_path = None
    legacy_key_path = None
    legacy_username = "default"

    for base in _legacy_base_paths():
        config_file = os.path.join(base, PROFILE_CONFIG_NAME)
        key_file = os.path.join(base, PROFILE_KEY_NAME)
        if not os.path.exists(config_file):
            continue
        legacy_config_path = config_file
        legacy_key_path = key_file if os.path.exists(key_file) else None
        try:
            from sync_app.core.secure_config_loader import load_secure_config

            old_cfg = load_secure_config(log)
            if old_cfg:
                legacy_username = sanitize_profile_id(
                    str(old_cfg.get("APP_LOGIN_USERNAME") or "default")
                )
        except Exception:
            pass
        break

    if not legacy_config_path:
        return None

    profile_id = legacy_username or "default"
    dest = ensure_profile_dir(profile_id)

    _copy_if_exists(legacy_config_path, os.path.join(dest, PROFILE_CONFIG_NAME))
    if legacy_key_path:
        _copy_if_exists(legacy_key_path, os.path.join(dest, PROFILE_KEY_NAME))

    for legacy_dir in _legacy_writable_dirs():
        for filename in USER_DATA_FILES:
            _copy_if_exists(
                os.path.join(legacy_dir, filename),
                os.path.join(dest, filename),
            )

    save_last_profile_id(profile_id)
    if log:
        log.info(f"📁 پروفایل کاربر «{profile_id}» از تنظیمات قبلی ساخته شد.")
    return profile_id


def initialize_new_profile_config(username: str, password: str) -> dict:
    """تنظیمات اولیه برای کاربر تازه."""
    user = (username or "").strip() or "admin"
    cfg = {
        "APP_LOGIN_USERNAME": user,
        "APP_LOGIN_PASSWORD": password or "123456",
        "APP_SHOW_LOGIN_SCREEN": True,
        "APP_THEME": "navy",
        "APP_FONT_SIZE": 14,
    }
    from sync_app.core.secure_config_loader import save_secure_config

    save_secure_config(cfg)
    return load_secure_config_after_profile(log=None) or cfg


def load_secure_config_after_profile(log=None):
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.wc_site_profiles import ensure_wc_sites
    from sync_app.core.ps_site_profiles import ensure_ps_sites

    cfg = load_secure_config(log) or {}
    if cfg:
        cfg = ensure_wc_sites(cfg)
        cfg = ensure_ps_sites(cfg)
        return cfg
    return cfg
