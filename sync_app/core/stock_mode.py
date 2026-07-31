"""
حالت موجودی محصول — چهار حالت:
  db       : مدیریت موجودی از دیتابیس ERP (manage_stock=True, تعداد واقعی)
  always   : همیشه موجود (manage_stock=False, stock_status=instock)
  download : دانلودی/بدون نیاز به موجودی فیزیکی (مثل always رفتار می‌کنه
             سمت ووکامرس، چون ووکامرس ساده فیلد «دانلودی مستقل» نداره —
             manage_stock=False و stock_status=instock)
  outofstock: ناموجود — صریحاً غیرقابل‌سفارش، صرف‌نظر از موجودیِ دیتابیس
             (manage_stock=False, stock_status=outofstock)

پیش‌فرض هر محصول از دسته‌بندیش ارث می‌بره؛ می‌شه روی هر محصول هم جدا
override کرد. یه لایه‌ی دیگه هم بینِ override محصول و دسته‌بندیِ ERP هست:
اگه دسته‌بندی/برندِ سایتِ محصول (تبِ «لیستِ قیمت») حالتِ موجودیِ مخصوصِ
خودش رو ست کرده باشه، همون استفاده می‌شه — برند اول، بعد دسته‌بندی (دقیقاً
همون اولویتِ لیستِ قیمت).
"""

from __future__ import annotations

STOCK_MODE_DB = "db"
STOCK_MODE_ALWAYS = "always"
STOCK_MODE_DOWNLOAD = "download"
STOCK_MODE_OUT_OF_STOCK = "outofstock"

STOCK_MODE_LABELS = {
    STOCK_MODE_DB: "بر اساس موجودی دیتابیس",
    STOCK_MODE_ALWAYS: "همیشه موجود",
    STOCK_MODE_DOWNLOAD: "دانلودی (بدون نیاز به موجودی)",
    STOCK_MODE_OUT_OF_STOCK: "ناموجود",
}

CATEGORY_STOCK_MODE_KEY = "CATEGORY_STOCK_MODE"   # {group_code: mode}
PRODUCT_STOCK_MODE_KEY = "PRODUCT_STOCK_MODE"     # {sku: mode} — فقط وقتی صریحاً override شده


def get_category_stock_mode(config: dict, group_code: str) -> str:
    """
    اولویت: تنظیم صریح روی خودِ زیر-دسته (group_code کامل) → تنظیم صریح روی
    دسته‌ی اصلی (m_code، والدِ این زیر-دسته) → پیش‌فرض «db».

    زیر-دسته‌ها (full_code = m_code + s_code) هر کدوم می‌تونن جدا override
    بشن، ولی اگه هیچ‌کدوم override نشده باشن، تنظیمِ دسته‌ی اصلی (که با
    SELECTED_CATEGORY_GROUPS مشخص می‌شه) روی همه‌ی زیرمجموعه‌هاش اعمال می‌شه.
    """
    cfg = config or {}
    modes = cfg.get(CATEGORY_STOCK_MODE_KEY) or {}
    gc = str(group_code).strip()

    mode = modes.get(gc)
    if mode in STOCK_MODE_LABELS:
        return mode

    main_codes = [str(m).strip() for m in (cfg.get("SELECTED_CATEGORY_GROUPS") or []) if str(m).strip()]
    parent_code = max(
        (m for m in main_codes if m != gc and gc.startswith(m)),
        key=len,
        default="",
    )
    if parent_code:
        parent_mode = modes.get(parent_code)
        if parent_mode in STOCK_MODE_LABELS:
            return parent_mode

    return STOCK_MODE_DB


def set_category_stock_mode(group_code: str, mode: str) -> None:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    if mode not in STOCK_MODE_LABELS:
        return
    cfg = load_secure_config(None) or {}
    modes = dict(cfg.get(CATEGORY_STOCK_MODE_KEY) or {})
    modes[str(group_code).strip()] = mode
    cfg[CATEGORY_STOCK_MODE_KEY] = modes
    save_secure_config(cfg)


def get_product_stock_mode_override(config: dict, sku: str) -> str | None:
    overrides = (config or {}).get(PRODUCT_STOCK_MODE_KEY) or {}
    mode = overrides.get(str(sku).strip())
    return mode if mode in STOCK_MODE_LABELS else None


def set_product_stock_mode_override(sku: str, mode: str | None) -> None:
    """mode=None یعنی حذف override — دوباره از دسته‌بندی ارث می‌بره."""
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    overrides = dict(cfg.get(PRODUCT_STOCK_MODE_KEY) or {})
    sku = str(sku).strip()
    if mode in STOCK_MODE_LABELS:
        overrides[sku] = mode
    else:
        overrides.pop(sku, None)
    cfg[PRODUCT_STOCK_MODE_KEY] = overrides
    save_secure_config(cfg)


VARIATION_STOCK_MODE_KEY = "VARIATION_STOCK_MODE"  # {variation_sku: mode}


def get_variation_stock_mode_override(config: dict, variation_sku: str) -> str | None:
    overrides = (config or {}).get(VARIATION_STOCK_MODE_KEY) or {}
    mode = overrides.get(str(variation_sku).strip())
    return mode if mode in STOCK_MODE_LABELS else None


def set_variation_stock_mode_override(variation_sku: str, mode: str | None) -> None:
    """mode=None یعنی حذف override — دوباره از محصول (و از اون، دسته‌بندی) ارث می‌بره."""
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    overrides = dict(cfg.get(VARIATION_STOCK_MODE_KEY) or {})
    variation_sku = str(variation_sku).strip()
    if mode in STOCK_MODE_LABELS:
        overrides[variation_sku] = mode
    else:
        overrides.pop(variation_sku, None)
    cfg[VARIATION_STOCK_MODE_KEY] = overrides
    save_secure_config(cfg)


def resolve_variation_stock_mode(variation_sku: str, parent_sku: str, group_code: str, config: dict) -> str:
    """
    اولویت: override روی خودِ متغیر → override روی محصول والد →
    تنظیم دسته‌بندی → پیش‌فرض «db».
    """
    v_override = get_variation_stock_mode_override(config, variation_sku)
    if v_override:
        return v_override
    return resolve_stock_mode(parent_sku, group_code, config)


def _site_taxonomy_stock_mode(config: dict, sku: str) -> str | None:
    """حالتِ موجودیِ ست‌شده رویِ دسته‌بندی/برندِ سایتِ این SKU (تبِ «لیستِ
    قیمت») — برند اول، بعد دسته‌بندی؛ اگه چیزی ست نشده باشه None."""
    if not sku:
        return None
    try:
        from sync_app.core.site_taxonomy_price_list import resolve_site_price_settings

        settings = resolve_site_price_settings(config, sku)
    except Exception:
        return None
    if not settings:
        return None
    mode = settings.get("stock_mode")
    return mode if mode in STOCK_MODE_LABELS else None


def resolve_stock_mode(sku: str, group_code: str, config: dict) -> str:
    """
    اولویت: override روی خودِ محصول → حالتِ ست‌شده رویِ دسته‌بندی/برندِ سایت
    (تبِ «لیستِ قیمت»، برند اول) → تنظیمِ دسته‌بندیِ ERP → پیش‌فرض «db».
    """
    override = get_product_stock_mode_override(config, sku)
    if override:
        return override
    site_mode = _site_taxonomy_stock_mode(config, sku)
    if site_mode:
        return site_mode
    return get_category_stock_mode(config, group_code)


def apply_stock_mode_to_payload(payload: dict, mode: str, stock_quantity: int) -> dict:
    """
    payload رو طبق حالت موجودی اصلاح می‌کنه — این دقیقاً همون فیلدهاییه که
    روی ووکامرس اعمال می‌شه (manage_stock/stock_quantity/stock_status).
    """
    if mode == STOCK_MODE_OUT_OF_STOCK:
        payload["manage_stock"] = False
        payload["stock_status"] = "outofstock"
        payload.pop("stock_quantity", None)
    elif mode in (STOCK_MODE_ALWAYS, STOCK_MODE_DOWNLOAD):
        payload["manage_stock"] = False
        payload["stock_status"] = "instock"
        payload.pop("stock_quantity", None)
    else:  # STOCK_MODE_DB
        payload["manage_stock"] = True
        payload["stock_quantity"] = max(0, int(stock_quantity or 0))
    return payload
