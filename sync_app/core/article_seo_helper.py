"""تحلیلِ سئویِ مقاله (heuristic ساده — نه یک ابزارِ حرفه‌ای سئو) + پیشنهادِ
اصلاح. از همون SeoCheck/SeoResult ماژولِ seo_helper.py (که برایِ محصولات
استفاده می‌شه) دوباره‌استفاده می‌کنه تا رفتار/امتیازدهی یکسان بمونه."""

from __future__ import annotations

import re

from sync_app.core.seo_helper import SeoCheck, SeoResult, _STOPWORDS, _clean

MIN_TITLE_LEN = 20
MAX_TITLE_LEN = 70
MIN_EXCERPT_LEN = 50
MAX_EXCERPT_LEN = 160
MIN_WORD_COUNT = 300
MAX_PARAGRAPH_LEN = 700
FOCUS_KEYWORD_WINDOW_WORDS = 60


def _word_count(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html or "")
    words = re.findall(r"\S+", text)
    return len(words)


def _has_heading(html: str) -> bool:
    return bool(re.search(r"<h[23][ >]", html or "", re.IGNORECASE))


def _images_without_alt(html: str) -> int:
    imgs = re.findall(r"<img\b[^>]*>", html or "", re.IGNORECASE)
    missing = 0
    for tag in imgs:
        m = re.search(r'alt\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
        if not m or not m.group(1).strip():
            missing += 1
    return missing


def _plain_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _focus_keyword(title: str) -> str:
    """طولانی‌ترین کلمه‌ی معنادار (غیرِ حرفِ‌اضافه) تویِ عنوان — به‌عنوانِ
    کلمه‌ی کلیدیِ محتمل برایِ چک‌کردنِ حضورش تویِ متن."""
    words = [w.strip(".,،؛:!؟\"'()") for w in (title or "").split()]
    candidates = [w for w in words if w and w not in _STOPWORDS and len(w) > 2]
    if not candidates:
        return ""
    return max(candidates, key=len)


def _keyword_near_start(content: str, keyword: str, *, window_words: int = FOCUS_KEYWORD_WINDOW_WORDS) -> bool:
    if not keyword:
        return True
    plain = _plain_text(content)
    first_words = " ".join(plain.split()[:window_words])
    return keyword in first_words


def _long_paragraph_count(html: str, *, limit: int = MAX_PARAGRAPH_LEN) -> int:
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html or "", re.IGNORECASE | re.DOTALL)
    return sum(1 for p in paragraphs if len(_plain_text(p)) > limit)


def _has_link(html: str) -> bool:
    return bool(re.search(r"<a\b[^>]*href\s*=", html or "", re.IGNORECASE))


def score_article_seo(article: dict, *, supports_featured_image: bool = True) -> SeoResult:
    title = _clean(article.get("title"))
    content = article.get("content_html") or ""
    excerpt = _clean(article.get("excerpt"))
    word_count = _word_count(content)
    images_missing_alt = _images_without_alt(content)
    has_images = bool(re.search(r"<img\b", content, re.IGNORECASE))
    focus_keyword = _focus_keyword(title)
    long_paragraphs = _long_paragraph_count(content)

    title_ok = MIN_TITLE_LEN <= len(title) <= MAX_TITLE_LEN
    excerpt_ok = MIN_EXCERPT_LEN <= len(excerpt) <= MAX_EXCERPT_LEN

    checks = [
        SeoCheck(
            "طول عنوان مناسب", title_ok,
            f"عنوان {len(title)} کاراکتر — بازه‌ی پیشنهادی {MIN_TITLE_LEN} تا {MAX_TITLE_LEN}",
            missing_label="طول عنوان نامناسب",
        ),
        SeoCheck(
            "محتوایِ کافی دارد", word_count >= MIN_WORD_COUNT,
            f"{word_count} کلمه — حداقلِ پیشنهادی {MIN_WORD_COUNT} کلمه",
            missing_label="محتوا کوتاهه",
        ),
        SeoCheck(
            "متا-دیسکریپشن/خلاصه دارد", excerpt_ok,
            f"{len(excerpt)} کاراکتر — بازه‌ی پیشنهادی {MIN_EXCERPT_LEN} تا {MAX_EXCERPT_LEN}",
            missing_label="بدونِ متا-دیسکریپشن/خلاصه‌یِ مناسب",
        ),
        SeoCheck("دسته‌بندی دارد", bool(article.get("category_ids")), missing_label="بدونِ دسته‌بندی"),
        SeoCheck(
            "زیرعنوان (H2/H3) دارد", _has_heading(content),
            missing_label="بدونِ زیرعنوان — خوانایی/سئو رو ضعیف می‌کنه",
        ),
        SeoCheck(
            "پاراگراف‌ها طولانی نیستن", long_paragraphs == 0,
            f"{long_paragraphs} پاراگراف بیش از {MAX_PARAGRAPH_LEN} کاراکتر",
            missing_label="بعضی پاراگراف‌ها خیلی طولانی‌ان — خوانایی رو کم می‌کنه",
        ),
        SeoCheck(
            "لینک (داخلی/خارجی) داره", _has_link(content),
            missing_label="محتوا هیچ لینکی نداره — لینک‌دهی به منابعِ مرتبط سئو رو تقویت می‌کنه",
        ),
    ]
    if focus_keyword:
        checks.append(
            SeoCheck(
                "کلمه‌ی کلیدیِ عنوان در ابتدایِ متن هست", _keyword_near_start(content, focus_keyword),
                f"کلمه‌یِ «{focus_keyword}» (از عنوان) باید تویِ همون {FOCUS_KEYWORD_WINDOW_WORDS} کلمه‌ی اول باشه",
                missing_label=f"کلمه‌ی «{focus_keyword}» تویِ ابتدایِ متن نیست",
            )
        )
    if supports_featured_image:
        checks.append(
            SeoCheck("تصویرِ شاخص دارد", bool(article.get("featured_image_url")), missing_label="بدونِ تصویرِ شاخص")
        )
    if has_images:
        checks.append(
            SeoCheck(
                "Alt همه‌ی تصاویرِ داخلِ محتوا پر شده", images_missing_alt == 0,
                f"{images_missing_alt} تصویر بدونِ Alt",
                missing_label="بعضی تصاویر Alt ندارن",
            )
        )
    return SeoResult(checks=checks)


def suggest_article_fixes(article: dict) -> dict:
    """پیشنهادهایِ ساده برایِ فیلدهایِ خالی/ناقص — کاربر می‌تونه دستی
    اصلاح/جایگزین کنه."""
    title = _clean(article.get("title"))
    excerpt = _clean(article.get("excerpt"))
    content = article.get("content_html") or ""
    word_count = _word_count(content)

    suggestions = {}
    if not (MIN_TITLE_LEN <= len(title) <= MAX_TITLE_LEN):
        if len(title) < MIN_TITLE_LEN:
            suggestions["title"] = f"عنوان خیلی کوتاهه ({len(title)} کاراکتر) — حداقل {MIN_TITLE_LEN} کاراکتر پیشنهاد می‌شه."
        else:
            suggestions["title"] = f"عنوان خیلی بلنده ({len(title)} کاراکتر) — حداکثر {MAX_TITLE_LEN} کاراکتر پیشنهاد می‌شه."
    if not excerpt:
        plain = re.sub(r"<[^>]+>", " ", content)
        plain = re.sub(r"\s+", " ", plain).strip()
        suggestions["excerpt"] = plain[:MAX_EXCERPT_LEN]
    elif not (MIN_EXCERPT_LEN <= len(excerpt) <= MAX_EXCERPT_LEN):
        suggestions["excerpt"] = f"طولِ خلاصه {len(excerpt)} کاراکتره — بازه‌ی پیشنهادی {MIN_EXCERPT_LEN}-{MAX_EXCERPT_LEN}."
    if word_count < MIN_WORD_COUNT:
        suggestions["content"] = f"محتوا فقط {word_count} کلمه‌ست — برایِ سئویِ بهتر حداقل {MIN_WORD_COUNT} کلمه پیشنهاد می‌شه."
    if not _has_heading(content):
        suggestions["heading"] = "حداقل یه زیرعنوان (H2) به محتوا اضافه کنید تا خواناتر/سئوپسندتر بشه."
    if not article.get("category_ids"):
        suggestions["category"] = "این مقاله هیچ دسته‌بندی‌ای نداره — یه دسته انتخاب کنید."

    long_paragraphs = _long_paragraph_count(content)
    if long_paragraphs:
        suggestions["paragraphs"] = f"{long_paragraphs} پاراگراف بیش از {MAX_PARAGRAPH_LEN} کاراکتره — به پاراگراف‌هایِ کوتاه‌تر تقسیم کنید."
    if not _has_link(content):
        suggestions["link"] = "محتوا هیچ لینکی نداره — یه لینکِ داخلی (به مقاله/محصولِ مرتبط) یا خارجی (به منبعِ معتبر) اضافه کنید."
    focus_keyword = _focus_keyword(title)
    if focus_keyword and not _keyword_near_start(content, focus_keyword):
        suggestions["focus_keyword"] = f"کلمه‌ی «{focus_keyword}» (از عنوان) تویِ {FOCUS_KEYWORD_WINDOW_WORDS} کلمه‌ی اولِ متن نیست — همون ابتدا یه‌بار ازش استفاده کنید."
    return suggestions
