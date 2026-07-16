"""
مدیریت تم مدرن — بارگذاری فونت Vazirmatn، ساخت و اعمال QSS، و ذخیره‌ی
ترجیح کاربر. مستقل از سیستم قدیمی رنگ‌های لهجه‌ای (navy/red/green).
پیش‌فرض: تم روشن فعال (طبق آخرین درخواست).
"""

from __future__ import annotations

import os

from PyQt5.QtGui import QFontDatabase

from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.theme.qss_builder import build_modern_stylesheet
from sync_app.core.theme.icon_provider import clear_icon_cache

MODERN_THEME_ENABLED_KEY = "UI_MODERN_THEME_ENABLED"
MODERN_THEME_MODE_KEY = "UI_MODERN_THEME_MODE"  # "light" | "dark"

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_fonts_loaded = False


def ensure_fonts_loaded() -> None:
    global _fonts_loaded
    if _fonts_loaded:
        return
    _fonts_loaded = True
    if not os.path.isdir(_FONTS_DIR):
        return
    for fname in os.listdir(_FONTS_DIR):
        if fname.lower().endswith(".ttf"):
            QFontDatabase.addApplicationFont(os.path.join(_FONTS_DIR, fname))


def is_modern_theme_enabled(config: dict | None = None) -> bool:
    cfg = config if config is not None else (load_secure_config(None) or {})
    return bool(cfg.get(MODERN_THEME_ENABLED_KEY, True))


def get_modern_theme_mode(config: dict | None = None) -> str:
    cfg = config if config is not None else (load_secure_config(None) or {})
    mode = str(cfg.get(MODERN_THEME_MODE_KEY, "light")).strip().lower()
    return mode if mode in ("dark", "light") else "light"


def set_modern_theme_mode(mode: str) -> None:
    cfg = load_secure_config(None) or {}
    cfg[MODERN_THEME_MODE_KEY] = "dark" if mode == "dark" else "light"
    save_secure_config(cfg)


def set_modern_theme_enabled(enabled: bool) -> None:
    cfg = load_secure_config(None) or {}
    cfg[MODERN_THEME_ENABLED_KEY] = bool(enabled)
    # APP_THEME هم هماهنگ می‌شود — چون اجزای قدیمی (مثل Dashboard) مستقیم
    # از این کلید رنگ می‌خوانند، نه از QSS سراسری. با ست کردن «modern»،
    # آن‌ها هم بدون هیچ تغییر منطقی خودکار هماهنگ می‌شوند.
    cfg["APP_THEME"] = "modern" if enabled else "navy"
    save_secure_config(cfg)


def ensure_app_theme_synced(cfg: dict) -> None:
    """
    اگر طراحی جدید فعال است (پیش‌فرض: بله) ولی APP_THEME هنوز روی «modern»
    نیست (مثلاً اولین اجرا، قبل از اینکه کاربر دکمه‌ای بزند)، آن را ست می‌کند
    تا اجزای قدیمی (Dashboard و...) هم از همان اول رنگ درست را بگیرند.
    """
    if not is_modern_theme_enabled(cfg):
        return
    if cfg.get("APP_THEME") == "modern":
        return
    fresh_cfg = load_secure_config(None) or {}
    fresh_cfg["APP_THEME"] = "modern"
    save_secure_config(fresh_cfg)
    cfg["APP_THEME"] = "modern"


def apply_modern_theme(app, *, mode: str | None = None, font_size: int = 14) -> None:
    ensure_fonts_loaded()
    effective_mode = mode or get_modern_theme_mode()
    app.setStyleSheet(build_modern_stylesheet(effective_mode, font_size=font_size))
    clear_icon_cache()


def toggle_modern_theme_mode(app) -> str:
    current = get_modern_theme_mode()
    new_mode = "dark" if current == "light" else "light"
    set_modern_theme_mode(new_mode)
    apply_modern_theme(app, mode=new_mode)
    return new_mode
