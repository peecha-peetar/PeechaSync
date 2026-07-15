"""کشِ سبکِ محلی برای «هش»ِ آخرین محتوایی که واقعاً برای یک SKU به فروشگاه
فرستاده شده — تا سینکِ بعدی فقط محصولاتی که واقعاً تو دیتابیس عوض شدن رو
دوباره بفرسته، نه همه‌ی محصولات رو از اول (که کند و بی‌فایده‌ست).

هش شاملِ خودِ payload (که هر تغییری تو نام/قیمت/توضیحات/موجودی/دسته/
تصاویر خودکار توش منعکس می‌شه) + یه «اثرانگشت» از وضعیتِ چک‌باکس‌های
همگام‌سازیه — پس اگه کاربر یه فیلد رو در تنظیمات فعال/غیرفعال کنه، هشِ
همه‌ی محصولات فرق می‌کنه و دورِ بعدی هیچ‌کدوم skip نمی‌شن (یه‌بار کامل
دوباره ارسال می‌شه، بعد دوباره پایدار می‌شه)."""
import hashlib
import json

from sync_app.core.sync_utils import app_path, log


def _cache_path(name: str) -> str:
    return app_path(f"sync_hash_cache_{name}.json")


def load_hash_cache(name: str) -> dict[str, str]:
    try:
        with open(_cache_path(name), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_hash_cache(name: str, cache: dict[str, str]) -> None:
    try:
        with open(_cache_path(name), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as exc:
        log.warning(f"⚠️ ذخیره‌ی کشِ تشخیصِ تغییرات ({name}) ناموفق بود: {exc}")


def compute_hash(payload) -> str:
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def should_skip_unchanged(sku: str, hash_payload, cache: dict[str, str], has_existing) -> tuple[bool, str]:
    """آیا این SKU رو می‌شه رد کرد؟ فقط وقتی از قبل روی فروشگاه ساخته شده
    (has_existing) و هشِ payload دقیقاً با آخرین سینکِ موفقش یکیه — وگرنه
    (چه اولین‌باره، چه چیزی عوض شده) باید عادی سینک بشه.
    برمی‌گردونه: (skip؟, هشِ محاسبه‌شده — برای ذخیره تو کش بعد از سینکِ موفق)."""
    new_hash = compute_hash(hash_payload)
    skip = bool(has_existing) and cache.get(sku) == new_hash
    return skip, new_hash
