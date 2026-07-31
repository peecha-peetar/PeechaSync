"""لیستِ قیمتِ هر زیر-دسته — هر گروه/زیرگروهِ ERP (کدِ M_Groupcode+
S_Groupcode) می‌تونه لیستِ قیمتِ جداگانه‌ای (نسبت به پیش‌فرضِ سراسریِ
PRICE_LIST_INDEX) داشته باشه؛ می‌شه رویِ هر محصول هم جدا override کرد.
دقیقاً همون الگویِ stock_mode.py (اولویت: override محصول → تنظیمِ
دسته‌بندی → پیش‌فرضِ سراسری)."""

from __future__ import annotations

CATEGORY_PRICE_LIST_KEY = "CATEGORY_PRICE_LIST_INDEX"  # {group_code: index (0-based، مثلِ PRICE_LIST_INDEX)}
PRODUCT_PRICE_LIST_KEY = "PRODUCT_PRICE_LIST_INDEX"     # {sku: index} — فقط وقتی صریحاً override شده


def get_category_price_list_index(config: dict, group_code: str) -> int | None:
    """اولویت: تنظیمِ صریح رویِ خودِ زیر-دسته (group_code کامل) → تنظیمِ
    صریح رویِ دسته‌یِ اصلی (m_code، والدِ این زیر-دسته) → None (یعنی از
    پیش‌فرضِ سراسریِ PRICE_LIST_INDEX استفاده بشه)."""
    cfg = config or {}
    overrides = cfg.get(CATEGORY_PRICE_LIST_KEY) or {}
    gc = str(group_code).strip()

    idx = overrides.get(gc)
    if idx is not None:
        try:
            return int(idx)
        except (TypeError, ValueError):
            pass

    main_codes = [str(m).strip() for m in (cfg.get("SELECTED_CATEGORY_GROUPS") or []) if str(m).strip()]
    parent_code = max(
        (m for m in main_codes if m != gc and gc.startswith(m)),
        key=len,
        default="",
    )
    if parent_code:
        parent_idx = overrides.get(parent_code)
        if parent_idx is not None:
            try:
                return int(parent_idx)
            except (TypeError, ValueError):
                pass

    return None


def set_category_price_list_index(group_code: str, index: int | None) -> None:
    """index=None یعنی حذفِ override — دوباره از پیش‌فرضِ سراسری استفاده می‌شه."""
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    overrides = dict(cfg.get(CATEGORY_PRICE_LIST_KEY) or {})
    gc = str(group_code).strip()
    if index is None:
        overrides.pop(gc, None)
    else:
        overrides[gc] = int(index)
    cfg[CATEGORY_PRICE_LIST_KEY] = overrides
    save_secure_config(cfg)


def get_product_price_list_override(config: dict, sku: str) -> int | None:
    overrides = (config or {}).get(PRODUCT_PRICE_LIST_KEY) or {}
    idx = overrides.get(str(sku).strip())
    if idx is None:
        return None
    try:
        return int(idx)
    except (TypeError, ValueError):
        return None


def set_product_price_list_override(sku: str, index: int | None) -> None:
    """index=None یعنی حذفِ override — دوباره از دسته‌بندی/پیش‌فرض ارث می‌بره."""
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    overrides = dict(cfg.get(PRODUCT_PRICE_LIST_KEY) or {})
    sku = str(sku).strip()
    if index is None:
        overrides.pop(sku, None)
    else:
        overrides[sku] = int(index)
    cfg[PRODUCT_PRICE_LIST_KEY] = overrides
    save_secure_config(cfg)


def resolve_price_list_index(sku: str, group_code: str, config: dict) -> int:
    """اولویت: override رویِ خودِ محصول → دسته‌بندی/برندِ سایت (تبِ «دسته‌بندی
    و برند») → تنظیمِ دسته‌بندیِ ERP → پیش‌فرضِ سراسریِ PRICE_LIST_INDEX.
    خروجی همیشه 0-based (مثلِ خودِ PRICE_LIST_INDEX تویِ تنظیمات) هست."""
    override = get_product_price_list_override(config, sku)
    if override is not None:
        return override

    from sync_app.core.site_taxonomy_price_list import resolve_site_price_settings

    site_settings = resolve_site_price_settings(config, sku)
    if site_settings and site_settings.get("regular_index") is not None:
        return int(site_settings["regular_index"])

    cat_index = get_category_price_list_index(config, group_code)
    if cat_index is not None:
        return cat_index
    try:
        return int((config or {}).get("PRICE_LIST_INDEX", 0) or 0)
    except (TypeError, ValueError):
        return 0


def resolve_article_price_column(sku: str, group_code: str, config: dict) -> str:
    """نامِ ستونِ Article (Sel_Price..Sel_Price5) برایِ محصولاتِ ساده،
    بر اساسِ لیستِ قیمتِ resolve‌شده‌یِ این SKU/دسته."""
    from sync_app.core.article_price import price_list_column_for_index

    index = resolve_price_list_index(sku, group_code, config)
    return price_list_column_for_index(index)


def resolve_article_price_sc_id(sku: str, group_code: str, config: dict) -> int:
    """شناسه‌یِ SelID/ScID در جدولِ ArticlePrice برایِ محصولاتِ ترکیبی
    (واریانت)، بر اساسِ لیستِ قیمتِ resolve‌شده‌یِ این SKU/دسته (۱-based)."""
    index = resolve_price_list_index(sku, group_code, config)
    return index + 1
