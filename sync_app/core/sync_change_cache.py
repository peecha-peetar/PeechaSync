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

from sync_app.core.sync_utils import log, site_scoped_path


def _platform_suffix(config) -> str:
    try:
        from sync_app.core.integrations.commerce_provider import store_platform

        return store_platform(config)
    except Exception:
        return "woocommerce"


def _cache_path(name: str, config=None) -> str:
    # به‌ازایِ هر سایت جدا — قبلاً بینِ همه‌یِ سایت‌هایِ یک پلتفرم مشترک بود،
    # پس «این کالا عوض نشده» که برایِ سایتِ A ثبت شده بود، باعث می‌شد رویِ
    # سایتِ B (یا همون سایت بعد از ریست) اصلاً ارسال نشه. فایلِ قدیمیِ مشترک
    # با اولین دسترسی خودکار به سایتِ فعلی منتقل می‌شه (site_scoped_path).
    return site_scoped_path(f"sync_hash_cache_{name}_{_platform_suffix(config)}.json")


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


def clear_hash_cache_entry(name: str, sku: str, config=None) -> None:
    """پاک‌کردنِ هشِ کش‌شده‌یِ یک SKU — وقتی *target*ِ لینک عوض می‌شه (نه
    محتوایِ ERP)، مثلاً از طریقِ تبِ تطبیق یا تطبیقِ ساختاری، باید سینکِ
    بعدی حتماً دوباره ارسال کنه، حتی اگه محتوایِ ERP از آخرین‌بار عوض
    نشده باشه — وگرنه should_skip_unchanged با دیدنِ هشِ قدیمی (که برایِ
    یک هدفِ لینکِ دیگه، یا اصلاً بدونِ لینک، ثبت شده بود) این SKU رو
    «از قبل هماهنگ» تشخیص می‌ده و بی‌صدا رد می‌شه."""
    sku = str(sku or "").strip()
    if not sku:
        return
    cache = load_hash_cache(name, config)
    if sku in cache:
        cache.pop(sku, None)
        save_hash_cache(name, cache, config)


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
    sku: str, hash_payload: dict, cache: dict, has_existing, target_id=None
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
    # target_id: شناسه‌یِ محصولِ سایت که آخرین سینکِ موفق رویش نوشته شد.
    # اگه الان یک محصولِ دیگه (مثلاً بعد از حذف و ساختِ دوباره) هدفه، محتوا
    # حتماً باید دوباره ارسال بشه — حتی اگه دادهٔ ERP عوض نشده باشه.
    entry = {"parts": parts}
    if target_id:
        entry["pid"] = int(target_id)
        prev_pid = prev.get("pid") if isinstance(prev, dict) else None
        if prev_pid and int(prev_pid) != int(target_id) and "target" not in changed:
            changed.append("target")
            changed.sort()
    skip = bool(has_existing) and not changed
    return skip, entry, changed
