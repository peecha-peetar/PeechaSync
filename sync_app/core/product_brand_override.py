"""برندِ دستیِ per-SKU — وقتی از تبِ «دسته‌بندی و برند» یه برندِ سایت به یه
محصول الصاق می‌شه، علاوه بر ارسالِ مستقیم به سایت، همین‌جا هم (site-scoped،
مثلِ product_category_override) نگه داشته می‌شه — چون خودِ سایت (WC/PS) هیچ
API‌ای برای «برندِ فعلیِ این SKU» به‌صورتِ محلی و سریع نداره، و بدونِ این
رکوردِ محلی، محاسبه‌ی لیستِ قیمتِ مخصوصِ برند (site_taxonomy_price_list)
موقعِ سینکِ عادی امکان‌پذیر نیست."""

from __future__ import annotations

import json

OVERRIDE_FILE = "product_brand_override.json"


def _path() -> str:
    from sync_app.core.sync_utils import site_scoped_path

    return site_scoped_path(OVERRIDE_FILE)


def load_brand_overrides() -> dict[str, int]:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {str(k).strip(): int(v) for k, v in data.items() if str(v).strip()}
    except Exception:
        pass
    return {}


def save_brand_overrides(overrides: dict) -> None:
    try:
        clean = {
            str(k).strip(): int(v)
            for k, v in (overrides or {}).items()
            if str(k).strip() and int(v or 0) > 0
        }
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        try:
            from sync_app.core.sync_utils import log

            log.warning(f"⚠️ ذخیره {OVERRIDE_FILE}: {exc}")
        except Exception:
            pass


def get_manual_brand_id(sku: str) -> int | None:
    sku = str(sku or "").strip()
    if not sku:
        return None
    return load_brand_overrides().get(sku)


def set_manual_brand_id(sku: str, brand_id: int | None) -> None:
    sku = str(sku or "").strip()
    if not sku:
        return
    overrides = load_brand_overrides()
    if brand_id:
        overrides[sku] = int(brand_id)
    else:
        overrides.pop(sku, None)
    save_brand_overrides(overrides)
