"""جست‌وجویِ خودکارِ قیمت در ترب (torob.com) بر اساسِ نامِ کالا — برایِ
جدولِ «مقایسه‌ی قیمت با ترب» داخلِ دستیارِ هوشمند.

⚠️ ترب هیچ API رسمیِ عمومی برایِ این کار نداره؛ این ماژول با خوندنِ
صفحه‌ی جستجویِ ترب و استخراجِ داده‌هایِ ساختاریافته‌ی schema.org
(که خیلی از سایت‌ها از جمله ترب برایِ سئو تویِ صفحاتشون می‌ذارن) کار
می‌کنه. اگه ترب ساختارِ صفحه‌شو عوض کنه یا دسترسیِ ربات‌ها رو محدودتر
کنه، ممکنه این قابلیت از کار بیفته یا نتایجش کم‌دقت بشه — در اون صورت
نیاز به به‌روزرسانیِ این فایل داره."""

from __future__ import annotations

import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape

from sync_app.core.sync_utils import site_scoped_path

TOROB_SEARCH_URL = "https://torob.com/search/?query={query}"
REQUEST_TIMEOUT = 12
DEFAULT_DELAY_SECONDS = 1.5
CACHE_FILE = "torob_price_cache.json"
_RETRY_BACKOFF_SECONDS = 4.0

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# یه cookie jar/opener مشترک برایِ کلِ اسکن — تا مثلِ یه مرورگرِ واقعی،
# کوکی‌هایِ سشن بینِ درخواست‌ها حفظ بشن (خیلی از سیستم‌هایِ ضدربات، درخواستِ
# بدونِ کوکیِ سشن رو مستقیم مسدود می‌کنن، حتی با هدرهایِ درست).
_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))
_warmed_up = False


def _request_headers() -> dict:
    return {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://torob.com/",
    }


def _ensure_warmed_up() -> None:
    """یه‌بار (در طولِ اجرایِ برنامه) اول صفحه‌ی اصلیِ ترب رو باز می‌کنه تا
    کوکیِ سشن گرفته بشه — قبلِ اینکه سراغِ جستجو/صفحه‌ی محصول بریم."""
    global _warmed_up
    if _warmed_up:
        return
    _warmed_up = True  # حتی اگه ناموفق بود، دوباره امتحان نکنیم (برایِ هر درخواست کند نشه)
    try:
        req = urllib.request.Request("https://torob.com/", headers=_request_headers())
        with _opener.open(req, timeout=REQUEST_TIMEOUT) as resp:
            resp.read()
    except Exception:
        pass


def _fetch_once(url: str) -> str:
    _ensure_warmed_up()
    req = urllib.request.Request(url, headers=_request_headers())
    with _opener.open(req, timeout=REQUEST_TIMEOUT) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def _fetch(url: str) -> str:
    """یه‌بار retry با تاخیر — چون خطاهایِ محدودیتِ ربات (403/429/490/503
    و مشابه، که کدشون بسته به تنظیماتِ ضدربات‌ِ سایت فرق می‌کنه) گاهی گذرا
    هستن، نه لزوماً مسدودشدنِ دائمی."""
    try:
        return _fetch_once(url)
    except urllib.error.HTTPError:
        time.sleep(_RETRY_BACKOFF_SECONDS)
        return _fetch_once(url)


def _extract_json_ld_entries(html: str) -> list[dict]:
    """آیتم‌هایِ schema.org (Product/ItemList/@graph) رو از تگ‌هایِ
    application/ld+json استخراج می‌کنه."""
    entries: list[dict] = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = unescape(m.group(1).strip())
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            entry = stack.pop()
            if not isinstance(entry, dict):
                continue
            graph = entry.get("@graph")
            if isinstance(graph, list):
                stack.extend(g for g in graph if isinstance(g, dict))
                continue
            item_list = entry.get("itemListElement")
            if isinstance(item_list, list):
                for li in item_list:
                    if isinstance(li, dict):
                        nested = li.get("item")
                        stack.append(nested if isinstance(nested, dict) else li)
            entries.append(entry)
    return entries


def _offer_matches_domain(offer: dict, domain: str) -> bool:
    """اگه پیشنهاد (offer) مالِ فروشنده‌ای باشه که دامنه‌ش با «domain» یکی
    باشه (مثلاً سایتِ خودِ ما)، True برمی‌گردونه — تا از حساب‌کردن جا بمونه."""
    if not domain:
        return False
    domain = domain.strip().lower()
    if not domain:
        return False
    candidates = [str(offer.get("url") or "")]
    seller = offer.get("seller")
    if isinstance(seller, dict):
        candidates.append(str(seller.get("name") or ""))
        candidates.append(str(seller.get("url") or ""))
    return any(domain in c.lower() for c in candidates if c)


def _entry_matches_domain(entry: dict, domain: str) -> bool:
    if not domain:
        return False
    domain = domain.strip().lower()
    if not domain:
        return False
    candidates = [str(entry.get("url") or "")]
    seller = entry.get("seller") or entry.get("brand")
    if isinstance(seller, dict):
        candidates.append(str(seller.get("name") or ""))
        candidates.append(str(seller.get("url") or ""))
    return any(domain in c.lower() for c in candidates if c)


def _lowest_price_from_offers(offers, exclude_domain: str | None = None) -> float | None:
    if offers is None:
        return None
    offers_list = offers if isinstance(offers, list) else [offers]
    prices = []
    for off in offers_list:
        if not isinstance(off, dict):
            continue
        if exclude_domain and _offer_matches_domain(off, exclude_domain):
            continue
        for key in ("lowPrice", "price"):
            v = off.get(key)
            if v is None:
                continue
            try:
                prices.append(float(str(v).replace(",", "")))
            except ValueError:
                pass
    return min(prices) if prices else None


def _extract_price_fallback(html: str) -> float | None:
    """اگه JSON-LD در دسترس نبود، تلاش برایِ پیداکردنِ کمترین قیمتِ محتمل
    از رویِ متنِ خامِ HTML (عددهایِ چندرقمیِ نزدیکِ کلمه‌یِ «تومان»)."""
    prices = []
    for m in re.finditer(r"([\d,]{4,})\s*(?:تومان|ریال)", html):
        digits = m.group(1).replace(",", "")
        if digits.isdigit():
            prices.append(int(digits))
    return float(min(prices)) if prices else None


def _lowest_from_html(html: str, page_url: str, exclude_domain: str | None) -> dict:
    entries = _extract_json_ld_entries(html)
    best_price = None
    best_title = None
    best_url = None
    for entry in entries:
        entry_type = entry.get("@type")
        types = entry_type if isinstance(entry_type, list) else [entry_type]
        if "Product" not in [t for t in types if t]:
            continue
        if exclude_domain and _entry_matches_domain(entry, exclude_domain):
            continue
        price = _lowest_price_from_offers(entry.get("offers"), exclude_domain)
        if price is None:
            continue
        if best_price is None or price < best_price:
            best_price = price
            best_title = entry.get("name")
            best_url = entry.get("url") or page_url

    if best_price is None:
        fallback_price = _extract_price_fallback(html)
        if fallback_price is not None:
            return {"found": True, "title": None, "price": fallback_price, "url": page_url, "error": None}
        return {"found": False, "title": None, "price": None, "url": page_url, "error": "قیمتی در نتایج پیدا نشد"}

    return {"found": True, "title": best_title, "price": best_price, "url": best_url, "error": None}


def lookup_lowest_price(product_name: str, exclude_domain: str | None = None) -> dict:
    """برایِ یک نامِ کالا، تویِ ترب جستجو می‌کنه و کمترین قیمتِ پیداشده
    رو برمی‌گردونه (پیشنهادهایِ فروشنده‌ای که دامنه‌ش با exclude_domain
    یکی باشه، در محاسبه‌ی کمترین قیمت نادیده گرفته می‌شه — مثلاً برایِ
    نادیده‌گرفتنِ خودِ سایتِ ما اگه تویِ نتایجِ ترب هم باشیم).

    خروجی: {"found": bool, "title": str|None, "price": float|None,
    "url": str, "error": str|None}
    """
    query = urllib.parse.quote((product_name or "").strip())
    url = TOROB_SEARCH_URL.format(query=query)
    if not query:
        return {"found": False, "title": None, "price": None, "url": url, "error": "نامِ کالا خالیه"}

    try:
        html = _fetch(url)
    except urllib.error.HTTPError as e:
        return {"found": False, "title": None, "price": None, "url": url, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"found": False, "title": None, "price": None, "url": url, "error": str(e)}

    return _lowest_from_html(html, url, exclude_domain)


def lookup_price_from_url(product_url: str, exclude_domain: str | None = None) -> dict:
    """وقتی کاربر لینکِ دقیقِ صفحه‌ی محصول تویِ ترب رو وارد کرده، به‌جایِ
    جستجویِ نامی، مستقیم همون صفحه رو می‌خونه — دقیق‌تر از جستجوی خودکاره."""
    product_url = (product_url or "").strip()
    if not product_url:
        return {"found": False, "title": None, "price": None, "url": "", "error": "لینک خالیه"}

    try:
        html = _fetch(product_url)
    except urllib.error.HTTPError as e:
        return {"found": False, "title": None, "price": None, "url": product_url, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"found": False, "title": None, "price": None, "url": product_url, "error": str(e)}

    return _lowest_from_html(html, product_url, exclude_domain)


def lookup_product(product_name: str, manual_url: str | None = None, exclude_domain: str | None = None) -> dict:
    """اگه لینکِ دستیِ ترب برایِ این کالا وارد شده باشه، مستقیم از رویِ
    همون لینک قیمت رو می‌خونه؛ وگرنه جستجویِ خودکار بر اساسِ نام."""
    manual_url = (manual_url or "").strip()
    if manual_url:
        return lookup_price_from_url(manual_url, exclude_domain)
    return lookup_lowest_price(product_name, exclude_domain)


def lookup_many(
    items,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    progress_cb=None,
    should_stop=None,
    exclude_domain: str | None = None,
):
    """items: لیستی از (sku, name, manual_url). برایِ کاهشِ ریسکِ مسدودشدن
    توسطِ ترب، بینِ هر درخواست یه مکثِ کوتاه می‌ذاره. should_stop() اگه
    True برگردونه، اسکن سریع متوقف می‌شه."""
    results = []
    total = len(items)
    for idx, item in enumerate(items):
        sku, name = item[0], item[1]
        manual_url = item[2] if len(item) > 2 else None
        if should_stop and should_stop():
            break
        try:
            info = lookup_product(name, manual_url, exclude_domain)
        except Exception as e:
            info = {"found": False, "title": None, "price": None, "url": None, "error": str(e)}
        results.append((sku, name, info))
        if progress_cb:
            progress_cb(idx + 1, total, sku)
        if delay_seconds and idx < total - 1 and not (should_stop and should_stop()):
            time.sleep(delay_seconds)
    return results


def _cache_path() -> str:
    return site_scoped_path(CACHE_FILE)


def load_cache() -> dict:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict) -> None:
    try:
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def update_cache_entry(cache: dict, sku: str, name: str, our_price: float, info: dict) -> None:
    cache[sku] = {
        "name": name,
        "our_price": our_price,
        "torob_price": info.get("price"),
        "torob_title": info.get("title"),
        "torob_url": info.get("url"),
        "found": bool(info.get("found")),
        "error": info.get("error"),
        "checked_at": time.time(),
    }


def suggest_new_price(our_price, torob_price, discount_mode: str, discount_value: float):
    """اگه قیمتِ ترب (بجزِ خودمون) از قیمتِ ما کمتر باشه، قیمتِ پیشنهادیِ
    جدید رو حساب می‌کنه: یا discount_value درصدِ کمتر از قیمتِ ترب، یا
    discount_value مبلغِ ثابت کمتر از قیمتِ ترب — تا از رقیب ارزون‌تر بشیم.
    اگه ترب گرون‌تر/مساوی بود یا نتیجه بی‌معنی (صفر/منفی) بشه، None."""
    if our_price is None or torob_price is None:
        return None
    try:
        our_price = float(our_price)
        torob_price = float(torob_price)
        discount_value = float(discount_value or 0)
    except (TypeError, ValueError):
        return None
    if torob_price >= our_price:
        return None
    if discount_mode == "amount":
        new_price = torob_price - max(0.0, discount_value)
    else:
        new_price = torob_price * (1 - max(0.0, discount_value) / 100.0)
    if new_price <= 0:
        return None
    return round(new_price)
