"""برندِ دستیِ per-SKU — وقتی از تبِ «دسته‌بندی و برند» یه برندِ سایت به یه
محصول الصاق می‌شه، علاوه بر ارسالِ مستقیم به سایت، همین‌جا هم (site-scoped،
مثلِ product_category_override) نگه داشته می‌شه — چون خودِ سایت (WC/PS) هیچ
API‌ای برای «برندِ فعلیِ این SKU» به‌صورتِ محلی و سریع نداره، و بدونِ این
رکوردِ محلی، محاسبه‌ی لیستِ قیمتِ مخصوصِ برند (site_taxonomy_price_list)
موقعِ سینکِ عادی امکان‌پذیر نیست."""

from __future__ import annotations

import json
import os

OVERRIDE_FILE = "product_brand_override.json"

# محاسبه‌ی resolve_site_price_settings برایِ هر محصول این فایل رو چندین‌بار
# (یه‌بار برایِ قیمتِ عادی، یه‌بار ویژه، یه‌بار مارک‌آپ، یه‌بار نوعِ موجودی)
# صدا می‌زنه؛ در سینکِ کاملِ چند هزار محصولی، بدونِ کش این یعنی چندین‌هزار
# بارِ اضافیِ باز کردن/parseِ همین فایل. کش با mtime معتبرسنجی می‌شه — یعنی
# اگه فایل رویِ دیسک عوض بشه (چه با save_brand_overrides چه با ویرایشِ
# دستی)، خودکار re-load می‌شه، بدونِ نیاز به invalidation صریح.
_cache_path: str | None = None
_cache_mtime: float | None = None
_cache_data: dict[str, int] | None = None


def _path() -> str:
    from sync_app.core.sync_utils import site_scoped_path

    return site_scoped_path(OVERRIDE_FILE)


def load_brand_overrides() -> dict[str, int]:
    global _cache_path, _cache_mtime, _cache_data
    path = _path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    if _cache_data is not None and _cache_path == path and _cache_mtime == mtime:
        return _cache_data

    data: dict[str, int] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                data = {str(k).strip(): int(v) for k, v in raw.items() if str(v).strip()}
    except Exception:
        pass
    _cache_path, _cache_mtime, _cache_data = path, mtime, data
    return data


def save_brand_overrides(overrides: dict) -> None:
    global _cache_path, _cache_mtime, _cache_data
    try:
        clean = {
            str(k).strip(): int(v)
            for k, v in (overrides or {}).items()
            if str(k).strip() and int(v or 0) > 0
        }
        path = _path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        _cache_path, _cache_mtime, _cache_data = path, mtime, clean
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
