"""لیستِ قیمت/مارک‌آپِ مخصوصِ دسته‌بندی یا برندِ سایت — دقیقاً هم‌الگویِ
category_price_list.py (که رویِ کدِ دژاوو/ERP کار می‌کنه)، ولی این‌جا کلید
idِ دسته‌بندی/برندِ واقعیِ سایته که از تبِ «دسته‌بندی و برند» انتخاب می‌شه.

هر رکورد:
{"regular_index": int|None, "regular_markup_percent": float, "regular_markup_amount": float,
 "sale_enabled": bool, "sale_index": int|None,
 "sale_markup_percent": float, "sale_markup_amount": float}
دقیقاً مثلِ سراسری (PRICE_MARKUP_PERCENT/SALE_PRICE_MARKUP_PERCENT تویِ تبِ
تنظیمات)، درصد/مبلغِ عادی و ویژه جدا از همن — هر فیلد که None/خالی باشه
یعنی «از سطحِ بعدی ارث ببر».

اولویتِ resolve: برندِ دستیِ سایتِ SKU → دسته‌بندیِ دستیِ سایتِ SKU → None
(یعنی از سطحِ بعدی — دسته‌بندیِ ERP/پیش‌فرضِ سراسری — استفاده بشه). برند
بالاتر از دسته‌بندیه چون معمولاً مشخص‌تر/خاص‌تره."""

from __future__ import annotations

SITE_CATEGORY_PRICE_KEY = "SITE_CATEGORY_PRICE_LIST"  # {str(category_id): record}
SITE_BRAND_PRICE_KEY = "SITE_BRAND_PRICE_LIST"  # {str(brand_id): record}

_INDEX_FIELDS = ("regular_index", "sale_index")
_MARKUP_FIELDS = (
    "regular_markup_percent", "regular_markup_amount",
    "sale_markup_percent", "sale_markup_amount",
)


def _clean_record(record: dict | None) -> dict:
    record = record or {}
    out: dict = {}
    for key in _INDEX_FIELDS:
        val = record.get(key)
        if val is not None and str(val).strip() != "":
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                pass
    out["sale_enabled"] = bool(record.get("sale_enabled"))
    for key in _MARKUP_FIELDS:
        val = record.get(key)
        if val is not None and str(val).strip() != "":
            try:
                f = float(val)
                if f:
                    out[key] = f
            except (TypeError, ValueError):
                pass
    return out


def _get_record(config: dict, storage_key: str, entity_id) -> dict | None:
    table = (config or {}).get(storage_key) or {}
    record = table.get(str(entity_id))
    if not record:
        return None
    cleaned = _clean_record(record)
    return cleaned or None


def _set_record(storage_key: str, entity_id, record: dict | None) -> None:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    table = dict(cfg.get(storage_key) or {})
    key = str(entity_id).strip()
    if not key:
        return
    cleaned = _clean_record(record) if record else {}
    if cleaned:
        table[key] = cleaned
    else:
        table.pop(key, None)
    cfg[storage_key] = table
    save_secure_config(cfg)


def _delete_record(storage_key: str, entity_id) -> None:
    _set_record(storage_key, entity_id, None)


def list_category_price_settings(config: dict) -> dict[str, dict]:
    table = (config or {}).get(SITE_CATEGORY_PRICE_KEY) or {}
    return {k: _clean_record(v) for k, v in table.items() if _clean_record(v)}


def list_brand_price_settings(config: dict) -> dict[str, dict]:
    table = (config or {}).get(SITE_BRAND_PRICE_KEY) or {}
    return {k: _clean_record(v) for k, v in table.items() if _clean_record(v)}


def get_category_price_settings(config: dict, category_id) -> dict | None:
    return _get_record(config, SITE_CATEGORY_PRICE_KEY, category_id)


def set_category_price_settings(category_id, record: dict | None) -> None:
    _set_record(SITE_CATEGORY_PRICE_KEY, category_id, record)


def delete_category_price_settings(category_id) -> None:
    _delete_record(SITE_CATEGORY_PRICE_KEY, category_id)


def get_brand_price_settings(config: dict, brand_id) -> dict | None:
    return _get_record(config, SITE_BRAND_PRICE_KEY, brand_id)


def set_brand_price_settings(brand_id, record: dict | None) -> None:
    _set_record(SITE_BRAND_PRICE_KEY, brand_id, record)


def delete_brand_price_settings(brand_id) -> None:
    _delete_record(SITE_BRAND_PRICE_KEY, brand_id)


def resolve_site_price_settings(config: dict, sku: str) -> dict | None:
    """اولویت: برندِ دستیِ سایتِ این SKU → دسته‌بندیِ دستیِ سایتِ این SKU
    (اولین idی که override داره) → None (یعنی از سطحِ بعدی — دسته‌بندیِ
    ERP/پیش‌فرضِ سراسری — استفاده بشه)."""
    from sync_app.core.product_brand_override import get_manual_brand_id

    brand_id = get_manual_brand_id(sku)
    if brand_id:
        settings = get_brand_price_settings(config, brand_id)
        if settings:
            return settings

    from sync_app.core.product_category_override import get_manual_category_ids

    cat_ids = get_manual_category_ids(sku) or []
    for cid in cat_ids:
        settings = get_category_price_settings(config, cid)
        if settings:
            return settings

    return None
