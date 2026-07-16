"""کشِ سبکِ محلی برای «هش»ِ آخرین محتوایی که واقعاً برای یک SKU به فروشگاه
فرستاده شده — تا سینکِ بعدی فقط محصولاتی که واقعاً تو دیتابیس عوض شدن رو
دوباره بفرسته، نه همه‌ی محصولات رو از اول (که کند و بی‌فایده‌ست).

هر ورودیِ payload باید یه دیکشنریِ چند-بخشی باشه (مثلاً {"p_data":...,
"categories":..., "variants":...}) — نه یه بلوبِ یک‌تکه. برای هر بخش
جدا هش گرفته می‌شه؛ این‌طوری وقتی سینکِ دوباره لازمه، دقیقاً می‌شه لاگ
کرد کدوم بخش عوض شده (تشخیص/دیباگِ راحت‌تر برای اینکه چرا رد نشد).

فایل کش به‌ازای هر پلتفرم (ووکامرس/پرستاشاپ) جداست — کسی که هر دو رو
دارد و بینشون سوییچ می‌کند، کشِ یکی باعث رد نشدنِ اشتباهِ چیزی رو دیگری
نمی‌شه."""
import hashlib
import json

from sync_app.core.sync_utils import app_path, log


def _platform_suffix(config) -> str:
    try:
        from sync_app.core.integrations.commerce_provider import store_platform

        return store_platform(config)
    except Exception:
        return "woocommerce"


def _cache_path(name: str, config=None) -> str:
    return app_path(f"sync_hash_cache_{name}_{_platform_suffix(config)}.json")


def load_hash_cache(name: str, config=None) -> dict:
    try:
        with open(_cache_path(name, config), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_hash_cache(name: str, cache: dict, config=None) -> None:
    try:
        with open(_cache_path(name, config), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as exc:
        log.warning(f"⚠️ ذخیره‌ی کشِ تشخیصِ تغییرات ({name}) ناموفق بود: {exc}")


def _canonicalize(obj):
    """لیست‌ها (مثلاً ردیف‌های واریانت از SQL، یا مقادیرِ یک ویژگی) لزوماً
    ترتیبِ پایداری بینِ دو اجرای مختلف ندارن — چه به‌خاطرِ نبودِ ORDER BY تو
    یه کوئریِ میانی، چه به‌خاطرِ hash randomization پایتون روی iteration
    مجموعه‌ها. برای هش، فقط «مجموعه‌ی محتوا» مهمه نه ترتیب، پس لیست‌ها رو
    بر اساسِ نمایشِ متنیِ خودشون مرتب می‌کنیم."""
    if isinstance(obj, dict):
        return {k: _canonicalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        items = [_canonicalize(v) for v in obj]
        try:
            items.sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False, default=str))
        except Exception:
            pass
        return items
    return obj


def compute_hash(payload) -> str:
    canonical = _canonicalize(payload)
    normalized = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _part_hashes(hash_payload: dict) -> dict[str, str]:
    return {str(k): compute_hash(v) for k, v in (hash_payload or {}).items()}


def should_skip_unchanged(
    sku: str, hash_payload: dict, cache: dict, has_existing
) -> tuple[bool, dict, list[str]]:
    """hash_payload یه دیکشنریِ چند-بخشیه (مثلاً p_data/categories/variants/
    attr_map/settings) — هر بخش جدا هش می‌شه تا اگه سینکِ دوباره لازم شد،
    دقیقاً معلوم باشه کدوم بخش عوض کرده.

    برمی‌گردونه:
      skip؟ — فقط وقتی از قبل روی فروشگاه ساخته شده (has_existing) و
              هیچ‌کدوم از بخش‌ها با آخرین سینکِ موفق فرق نداره.
      new_entry — برای ذخیره تو کش بعد از سینکِ موفق.
      changed — لیستِ نام‌ِ بخش‌هایی که عوض شدن (برای لاگِ تشخیصی)؛ اگه
                SKU کلاً تو کش نبود، همه‌ی بخش‌ها «تغییر»یافته حساب می‌شن.
    """
    parts = _part_hashes(hash_payload)
    prev = cache.get(sku)
    prev_parts = prev.get("parts") if isinstance(prev, dict) else None
    changed: list[str] = []
    if not isinstance(prev_parts, dict):
        changed = sorted(parts.keys())
    else:
        for key, value in parts.items():
            if prev_parts.get(key) != value:
                changed.append(key)
        for key in prev_parts:
            if key not in parts and key not in changed:
                changed.append(key)
        changed.sort()
    skip = bool(has_existing) and not changed
    return skip, {"parts": parts}, changed
