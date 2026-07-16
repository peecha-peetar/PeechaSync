"""
حالت سراسری محصولات — «فقط ساده» یا «دارای ویژگی و متغیر». این تنظیم
تعیین می‌کنه که تب‌ها/بخش‌های مربوط به ویژگی و متغیر (که برای فروشگاه‌های
بدون محصول متغیر، فقط شلوغی اضافه‌ست) نشون داده بشن یا نه.

نکته‌ی مهم: این تنظیم روی «تب‌های ساخته‌شده» بلافاصله اثر نمی‌ذاره —
چون این تب‌ها (همگام‌سازی، تطبیق، همگام‌سازی خودکار، صفحه‌ی شروع) موقع
ساخته‌شدن این حالت رو می‌خونن. برای همینه که بعد از تغییرش، از کاربر
خواسته می‌شه برنامه رو ببنده و دوباره باز کنه.
"""

from __future__ import annotations

PRODUCT_MODE_KEY = "PRODUCT_MODE"
MODE_SIMPLE_ONLY = "simple_only"
MODE_WITH_VARIANTS = "with_variants"  # پیش‌فرض


def get_product_mode(config: dict | None = None) -> str:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config if config is not None else (load_secure_config(None) or {})
    mode = str(cfg.get(PRODUCT_MODE_KEY, MODE_WITH_VARIANTS)).strip()
    return mode if mode in (MODE_SIMPLE_ONLY, MODE_WITH_VARIANTS) else MODE_WITH_VARIANTS


def is_simple_only(config: dict | None = None) -> bool:
    return get_product_mode(config) == MODE_SIMPLE_ONLY


def set_product_mode(mode: str) -> None:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    if mode not in (MODE_SIMPLE_ONLY, MODE_WITH_VARIANTS):
        return
    cfg = load_secure_config(None) or {}
    cfg[PRODUCT_MODE_KEY] = mode
    save_secure_config(cfg)


def detect_product_mode_from_db(config: dict) -> tuple[str, dict]:
    """
    اتصال واقعی به SQL و بررسی این‌که تو گروه‌های انتخابی، اصلاً محصول
    متغیر (چند سایز/رنگ) وجود داره یا نه. خروجی: (حالت پیشنهادی, جزئیات).
    این فقط تشخیص می‌ده — ذخیره‌ی نهایی با خودِ کاربر (تأیید در UI) است.
    """
    from sync_app.core.sql_connection_helper import open_sql_connection
    from sync_app.core.variation_query import load_variable_a_codes

    selected_groups = [str(g).strip() for g in (config.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]

    conn, _, _ = open_sql_connection(config, timeout=10)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT A_Code FROM Article WHERE LEN(A_Code) >= 4")
        all_codes = [str(r[0]).strip() for r in cursor.fetchall()]
        if selected_groups:
            all_codes = [c for c in all_codes if any(c.startswith(g) for g in selected_groups)]

        variable_codes = load_variable_a_codes(cursor)
        variable_in_scope = [c for c in all_codes if c in variable_codes]

        total = len(all_codes)
        variable_count = len(variable_in_scope)
        mode = MODE_WITH_VARIANTS if variable_count > 0 else MODE_SIMPLE_ONLY
        return mode, {
            "total_products": total,
            "variable_products": variable_count,
            "simple_products": total - variable_count,
        }
    finally:
        conn.close()
