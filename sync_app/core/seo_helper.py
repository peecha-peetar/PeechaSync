"""
ابزارهای سئوی محصول — بدون نیاز به هوش مصنوعی/API خارجی.
تولید Alt، توضیح کوتاه، متا دیسکریپشن، متا کیورد، عنوان سئو، و پیشنهاد
کلمات کلیدی از روی داده‌ی موجود محصول (نام، دسته‌بندی، توضیحات) + امتیازدهی.

نکته‌ی صادقانه: هیچ‌کدام از «متا دیسکریپشن»، «متا کیورد» و «عنوان سئو» فیلد
استاندارد وردپرس/ووکامرس نیستند — افزونه‌های سئو (Yoast، Rank Math) آن‌ها را
در متادیتای جدا نگه می‌دارند. این ماژول تلاش می‌کند کلیدهای رایج هر دو
افزونه را بنویسد؛ اگر از افزونه‌ی دیگری استفاده می‌کنید یا هیچ‌کدام نصب
نیست، فقط بی‌اثر می‌ماند (خطا نمی‌دهد).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

YOAST_META_DESC_KEY = "_yoast_wpseo_metadesc"
RANKMATH_META_DESC_KEY = "rank_math_description"
YOAST_TITLE_KEY = "_yoast_wpseo_title"
RANKMATH_TITLE_KEY = "rank_math_title"
YOAST_FOCUS_KW_KEY = "_yoast_wpseo_focuskw"
RANKMATH_FOCUS_KW_KEY = "rank_math_focus_keyword"

MIN_TITLE_LEN = 10
MAX_TITLE_LEN = 70
MIN_DESC_LEN = 40
META_DESC_MAX_LEN = 155
MAX_SEO_TITLE_LEN = 60

# کلمات پرکاربرد فارسی که برای «کلمه‌ی کلیدی» معنا ندارند
_STOPWORDS = {
    "با", "برای", "از", "در", "به", "را", "و", "یا", "این", "آن", "های",
    "ها", "که", "تا", "هم", "می", "شد", "شده", "است", "بود", "یک", "دو",
    "سه", "بر", "روی", "زیر", "کنار", "نو", "مدل", "سایز", "رنگ", "طرح",
}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def generate_alt_text(product: dict) -> str:
    """Alt تصویر — نام محصول + دسته‌بندی (اگر باشد)."""
    name = _clean(product.get("name"))
    category = _clean(product.get("category"))
    if category and category not in name:
        return f"{name} - {category}"
    return name


def generate_short_description(product: dict, *, max_len: int = 200) -> str:
    """
    توضیح کوتاه — از روی توضیحات بلند موجود (خلاصه‌شده) یا اگر خالی بود،
    یک جمله‌ی ساده از نام+دسته‌بندی می‌سازد.
    """
    desc = _clean(product.get("description"))
    if desc:
        if len(desc) <= max_len:
            return desc
        cut = desc[:max_len]
        last_space = cut.rfind(" ")
        return (cut[:last_space] if last_space > 40 else cut).strip() + "…"

    name = _clean(product.get("name"))
    category = _clean(product.get("category"))
    parts = [name]
    if category:
        parts.append(f"از دسته {category}")
    return " ".join(parts).strip()


def generate_meta_description(product: dict, *, max_len: int = META_DESC_MAX_LEN) -> str:
    """متا دیسکریپشن — خلاصه‌ی کوتاه‌تر برای نتایج گوگل (حداکثر ~۱۵۵ کاراکتر)."""
    base = generate_short_description(product, max_len=max_len)
    if len(base) <= max_len:
        return base
    cut = base[:max_len]
    last_space = cut.rfind(" ")
    return (cut[:last_space] if last_space > 40 else cut).strip() + "…"


def generate_seo_title(product: dict, *, max_len: int = MAX_SEO_TITLE_LEN) -> str:
    """
    عنوان سئو — معمولاً همون نام محصوله، با دسته‌بندی تکمیل می‌شه اگه جا باشه
    و از قبل توی نام نیومده باشه (کمک به رتبه‌ی جستجوی دسته‌بندی هم).
    """
    name = _clean(product.get("name"))
    category = _clean(product.get("category"))
    title = name
    if category and category not in name:
        candidate = f"{name} | {category}"
        if len(candidate) <= max_len:
            title = candidate
    if len(title) > max_len:
        cut = title[:max_len]
        last_space = cut.rfind(" ")
        title = (cut[:last_space] if last_space > 20 else cut).strip()
    return title


def generate_keywords(product: dict, *, max_keywords: int = 8) -> list[str]:
    """
    پیشنهاد/تولید کلمات کلیدی — از روی کلمات معنادار نام و دسته‌بندی
    (بدون کلمات رایج بی‌اثر مثل «با»/«برای»/«مدل»). ترتیب حفظ می‌شود،
    تکراری‌ها حذف می‌شوند.
    """
    name = _clean(product.get("name"))
    category = _clean(product.get("category"))
    text = f"{category} {name}".strip()  # دسته‌بندی معمولاً کلی‌تره، اول بیاد بهتره
    raw_words = re.split(r"[\s\-_,،/]+", text)

    seen = set()
    keywords: list[str] = []
    for w in raw_words:
        w = w.strip()
        if not w or len(w) < 2:
            continue
        if w in _STOPWORDS:
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(w)
        if len(keywords) >= max_keywords:
            break

    # کلمه‌ی کامل دسته‌بندی و نام هم به‌عنوان عبارت کلیدی ترکیبی اضافه شود (اگر جا هست)
    if category and category not in keywords and len(keywords) < max_keywords:
        keywords.append(category)

    return keywords


def meta_description_payload(text: str) -> list[dict]:
    """meta_data برای ارسال هم‌زمان به Yoast و Rank Math — هرکدام نصب نباشد بی‌اثر می‌ماند."""
    return [
        {"key": YOAST_META_DESC_KEY, "value": text},
        {"key": RANKMATH_META_DESC_KEY, "value": text},
    ]


def seo_title_payload(text: str) -> list[dict]:
    return [
        {"key": YOAST_TITLE_KEY, "value": text},
        {"key": RANKMATH_TITLE_KEY, "value": text},
    ]


def keywords_payload(keywords: list[str]) -> list[dict]:
    joined = ", ".join(keywords)
    return [
        {"key": YOAST_FOCUS_KW_KEY, "value": keywords[0] if keywords else ""},
        {"key": RANKMATH_FOCUS_KW_KEY, "value": joined},
    ]


@dataclass
class SeoCheck:
    label: str
    ok: bool
    hint: str = ""
    missing_label: str = ""

    def __post_init__(self):
        if not self.missing_label:
            self.missing_label = self.label


@dataclass
class SeoResult:
    checks: list[SeoCheck] = field(default_factory=list)

    @property
    def score(self) -> int:
        if not self.checks:
            return 0
        passed = sum(1 for c in self.checks if c.ok)
        return round(passed / len(self.checks) * 100)


def score_product_seo(product: dict) -> SeoResult:
    """
    امتیاز سئوی ساده (heuristic) — نه یک ابزار حرفه‌ای سئو، فقط یک راهنمای سریع.
    product می‌تواند شامل: name, description, short_description, alt_text,
    meta_description, meta_keywords, seo_title, has_category باشد.
    """
    p = product or {}
    name = _clean(p.get("name"))
    desc = _clean(p.get("description"))

    title_ok = MIN_TITLE_LEN <= len(name) <= MAX_TITLE_LEN
    checks = [
        SeoCheck(
            "طول عنوان مناسب", title_ok,
            f"عنوان {len(name)} کاراکتر — بازه‌ی پیشنهادی {MIN_TITLE_LEN} تا {MAX_TITLE_LEN}",
            missing_label="طول عنوان نامناسب",
        ),
        SeoCheck("توضیحات کافی دارد", len(desc) >= MIN_DESC_LEN, missing_label="توضیحات ناکافی"),
        SeoCheck("توضیح کوتاه دارد", bool(_clean(p.get("short_description"))), missing_label="بدون توضیح کوتاه"),
        SeoCheck("Alt تصویر دارد", bool(_clean(p.get("alt_text"))), missing_label="بدون Alt تصویر"),
        SeoCheck("متا دیسکریپشن دارد", bool(_clean(p.get("meta_description"))), missing_label="بدون متا دیسکریپشن"),
        SeoCheck("عنوان سئو دارد", bool(_clean(p.get("seo_title"))), missing_label="بدون عنوان سئو"),
        SeoCheck("کلمات کلیدی دارد", bool(_clean(p.get("meta_keywords"))), missing_label="بدون کلمات کلیدی"),
        SeoCheck("دسته‌بندی دارد", bool(p.get("has_category")), missing_label="بدون دسته‌بندی"),
    ]
    return SeoResult(checks=checks)


def analyze_product_seo_live(live: dict, *, fallback_name: str = "", fallback_desc: str = "") -> dict:
    """
    تحلیل واقعی سئوی یک محصول از روی پاسخ زنده‌ی ووکامرس (نه فرض محلی).
    live باید شامل این فیلدها باشد: name, short_description, description,
    categories, images, meta_data (خروجی GET products/{id} با _fields مناسب).

    نکته‌ی مهم: چک‌های متا (دیسکریپشن/عنوان/کلمات کلیدی) فقط زمانی درست کار
    می‌کنند که افزونه‌ی سئوی سایت (Yoast/Rank Math) آن فیلد را در REST API
    عمومی expose کرده باشد؛ در غیر این صورت حتی اگر مقدار واقعی روی سایت
    باشد، این چک‌ها به‌اشتباه «ندارد» نشان می‌دهند.
    """
    name = str(live.get("name") or fallback_name or "").strip()
    description = str(live.get("description") or fallback_desc or "")
    short_description = str(live.get("short_description") or "").strip()
    categories = live.get("categories") or []
    category_name = str(categories[0].get("name") or "").strip() if categories and isinstance(categories[0], dict) else ""
    images = live.get("images") or []
    alt_text = str(images[0].get("alt") or "").strip() if images and isinstance(images[0], dict) else ""
    image_id = images[0].get("id") if images and isinstance(images[0], dict) else None
    # همه‌ی تصاویر گالری (نه فقط تصویر اصلی) که Alt ندارن — برای اینکه دکمه‌ی
    # «رفع» فقط تصویر اول رو درست نکنه و بقیه‌ی گالری بدون Alt نمونه.
    missing_alt_image_ids = [
        img.get("id") for img in images
        if isinstance(img, dict) and img.get("id") and not str(img.get("alt") or "").strip()
    ]

    meta_map = {}
    for m in live.get("meta_data") or []:
        if isinstance(m, dict) and m.get("key"):
            meta_map[m["key"]] = m.get("value")

    meta_desc = str(meta_map.get(YOAST_META_DESC_KEY) or meta_map.get(RANKMATH_META_DESC_KEY) or "")
    seo_title = str(meta_map.get(YOAST_TITLE_KEY) or meta_map.get(RANKMATH_TITLE_KEY) or "")
    meta_keywords = str(meta_map.get(RANKMATH_FOCUS_KW_KEY) or meta_map.get(YOAST_FOCUS_KW_KEY) or "")

    seo_input = {
        "name": name,
        "description": description,
        "short_description": short_description,
        "alt_text": alt_text,
        "meta_description": meta_desc,
        "seo_title": seo_title,
        "meta_keywords": meta_keywords,
        "has_category": bool(categories),
    }
    current = score_product_seo(seo_input)

    gen_input = {"name": name, "description": description, "category": category_name}
    suggestions = {}
    if len(description.strip()) < MIN_DESC_LEN:
        # برخلاف بقیه‌ی فیلدها، توضیحات بلند رو خودکار تولید نمی‌کنیم (چون
        # محتوای اصلی محصوله) — فقط یه کادر خالی/قابل‌پیست در دیالوگ می‌ذاریم
        # که کاربر خودش بنویسه یا پیست کنه.
        suggestions["description"] = description.strip()
    if not short_description:
        suggestions["short_description"] = generate_short_description(gen_input)
    if not alt_text:
        suggestions["alt_text"] = generate_alt_text(gen_input)
    if not meta_desc:
        suggestions["meta_description"] = generate_meta_description(gen_input)
    if not seo_title:
        suggestions["seo_title"] = generate_seo_title(gen_input)
    if not meta_keywords:
        suggestions["meta_keywords"] = "، ".join(generate_keywords(gen_input))

    return {
        "name": name,
        "current_score": current.score,
        "checks": current.checks,
        "image_id": image_id,
        "missing_alt_image_ids": missing_alt_image_ids,
        "has_image": bool(images),
        "suggestions": suggestions,
    }


def apply_seo_fixes(wcapi, config: dict, wc_id: int, to_send: dict, image_id, extra_image_ids: list | None = None) -> None:
    """
    ارسال فیلدهای انتخاب‌شده (short_description/meta_description/seo_title/meta_keywords/alt_text).
    نکته‌ی مهم: alt_text از طریق wcapi (کلید API ووکامرس) قابل‌ارسال نیست —
    چون رسانه‌ها (media) توی فضای نام wp/v2 وردپرس هستن، نه wc/v3 ووکامرس.
    برای همین از update_wp_media_alt_text (با WP Application Password، همون
    مکانیزم آپلود تصویر) استفاده می‌شود.

    نکته‌ی دوم (رفع باگ قبلی): اگه محصول چند تصویر (گالری) داشته باشه و
    alt_text تیک خورده باشه، این alt روی «همه‌ی» تصاویر گالری که Alt ندارن
    اعمال می‌شه، نه فقط تصویر اصلی — چون قبلاً فقط تصویر اول درست می‌شد.
    """
    from sync_app.core.wc_sync_helper import update_wp_media_alt_text

    product_payload = {}
    meta_data = []
    if "description" in to_send:
        product_payload["description"] = to_send["description"]
    if "short_description" in to_send:
        product_payload["short_description"] = to_send["short_description"]
    if "meta_description" in to_send:
        meta_data.extend(meta_description_payload(to_send["meta_description"]))
    if "seo_title" in to_send:
        meta_data.extend(seo_title_payload(to_send["seo_title"]))
    if "meta_keywords" in to_send:
        kw_list = [k.strip() for k in re.split(r"[،,]", to_send["meta_keywords"]) if k.strip()]
        meta_data.extend(keywords_payload(kw_list))
    if meta_data:
        product_payload["meta_data"] = meta_data
    if product_payload:
        resp = wcapi.put(f"products/{int(wc_id)}", product_payload)
        resp.json()
    if "alt_text" in to_send:
        all_image_ids = list(dict.fromkeys(
            ([image_id] if image_id else []) + list(extra_image_ids or [])
        ))
        errors = []
        for img_id in all_image_ids:
            ok, err = update_wp_media_alt_text(config, img_id, to_send["alt_text"])
            if not ok:
                errors.append(f"تصویر {img_id}: {err}")
        if errors:
            raise RuntimeError("آپدیت Alt بعضی تصاویر ناموفق بود:\n" + "\n".join(errors))
