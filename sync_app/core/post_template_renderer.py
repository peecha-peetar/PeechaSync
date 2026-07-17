"""ساختِ متنِ پست از روی یک «قالبِ متنی» قابل‌تنظیم — بدونِ عکسِ کارتِ
جداگانه (طبق نظرِ کاربر: عکسِ اصلیِ سایت باید دست‌نخورده بمونه؛ «قالب»
فقط ساختارِ متنِ همراهِ پست رو تعیین می‌کنه، نه ظاهرِ عکس).

هر فیلد (نامِ محصول/قیمت/توضیح/لینک/آدرسِ سایت/تلفن/شبکه‌های اجتماعی/
متنِ دلخواه) می‌تونه Bold/Italic باشه، چیدمانِ راست/وسط/چپ داشته باشه،
و قبلش یک خطِ خالی بیاد.

⚠️ نکته‌ی مهم: تلگرام از parse_mode=HTML پشتیبانی می‌کنه، ولی بله این
کار رو نمی‌کنه — تگ‌های HTML رو به‌جای رندر کردن، عیناً به‌صورتِ متنِ خام
نشون می‌ده (تأییدشده با تستِ واقعی). برای همین render_post_text با آرگومانِ
as_html مشخص می‌کنه خروجی HTMLِ ساده (تلگرام) باشه یا متنِ کاملاً ساده
(بله) — در حالتِ متنِ ساده نه تگی اضافه می‌شه و نه escape انجام می‌شه.

برای چیدمان: «راست»/«چپ» با نشانه‌های جهتِ یونیکد (RLM/LRM) واقعاً جهتِ
خواندنِ متن رو کنترل می‌کنن (مفید برای مخلوطِ فارسی/لینک/شماره)، ولی
«وسط» در هیچ اپِ پیام‌رسانی (نه تلگرام، نه بله) واقعاً پشتیبانی نمی‌شه —
اینجا فقط یک تلاشِ نرم (padding) برای نزدیک‌شدنه، نه وسط‌چینیِ واقعی."""

from __future__ import annotations

import html as _html

from sync_app.core.content_studio_helper import _fmt_price

FIELD_TYPE_LABELS = {
    "product_name": "نامِ محصول",
    "price": "قیمت",
    "description": "توضیح",
    "link": "لینکِ محصول",
    "site_address": "آدرسِ سایت",
    "phone": "شماره تماس",
    "social_instagram": "اینستاگرام",
    "social_telegram": "تلگرام",
    "social_whatsapp": "واتساپ",
    "custom_text": "متنِ دلخواه",
}

TEXT_ALIGN_LABELS = {"right": "راست", "center": "وسط (تقریبی)", "left": "چپ"}

_RLM = "‏"  # Right-to-Left Mark
_LRM = "‎"  # Left-to-Right Mark
_CENTER_PAD = "    "  # فاصله‌ی رقمی — تلاشِ نرم برای نزدیک‌شدن به وسط

DEFAULT_FIELD = {
    "type": "custom_text",
    "text": "",
    "bold": False,
    "italic": False,
    "align": "right",
    "blank_line_before": False,
}

DEFAULT_TEMPLATE = {
    "id": "",
    "title": "پیش‌فرض",
    "fields": [
        {"type": "product_name", "bold": True, "italic": False, "align": "right", "blank_line_before": False},
        {"type": "price", "bold": True, "italic": False, "align": "right", "blank_line_before": False},
        {"type": "description", "bold": False, "italic": False, "align": "right", "blank_line_before": True},
        {"type": "link", "bold": False, "italic": False, "align": "left", "blank_line_before": True},
    ],
}


def normalize_field(raw: dict | None) -> dict:
    """ادغامِ یک فیلدِ ناقص/قدیمی با مقادیرِ پیش‌فرض."""
    merged = dict(DEFAULT_FIELD)
    merged.update({k: v for k, v in (raw or {}).items() if v is not None})
    if merged.get("type") not in FIELD_TYPE_LABELS:
        merged["type"] = "custom_text"
    if merged.get("align") not in TEXT_ALIGN_LABELS:
        merged["align"] = "right"
    return merged


def normalize_template(raw: dict | None) -> dict:
    """ادغامِ یک قالبِ ناقص/قدیمی با مقادیرِ پیش‌فرض — تا افزودنِ فیلدِ جدید
    در آینده، قالب‌های ذخیره‌شده‌ی قدیمی رو خراب نکنه."""
    merged = dict(DEFAULT_TEMPLATE)
    merged.update({k: v for k, v in (raw or {}).items() if v is not None})
    fields = merged.get("fields")
    if not isinstance(fields, list) or not fields:
        fields = DEFAULT_TEMPLATE["fields"]
    normalized_fields = [normalize_field(f) for f in fields if isinstance(f, dict)]
    merged["fields"] = normalized_fields or [normalize_field(f) for f in DEFAULT_TEMPLATE["fields"]]
    return merged


def _field_value(field: dict, context: dict) -> str:
    """مقدارِ نهاییِ فیلد. برای هر نوعی به‌جز نام/قیمتِ محصول (که همیشه باید
    از خودِ محصول باشن)، اگه کاربر توی جعبه‌ی «متن» چیزی نوشته باشه، همون
    override به‌جایِ مقدارِ خودکار (از تنظیمات/سایت) استفاده می‌شه — تا
    بدونِ نیاز به پرکردنِ تنظیماتِ سراسری هم بشه فیلدها رو پر کرد."""
    ftype = field.get("type")
    override = str(field.get("text") or "").strip()
    if ftype == "custom_text":
        return override
    if ftype == "product_name":
        return str(context.get("name") or "").strip()
    if ftype == "price":
        price = context.get("price")
        if price in (None, "", 0):
            return ""
        return f"{_fmt_price(price)} تومان"
    if ftype == "description":
        return override or str(context.get("description") or "").strip()
    if ftype == "link":
        # override برای لینک معنیِ متفاوتی داره: نه جایگزینیِ خودِ URL،
        # بلکه برچسبِ نمایشی (در render_post_text مدیریت می‌شه) — پس اینجا
        # همیشه لینکِ واقعیِ محصول برمی‌گرده، نه override
        return str(context.get("permalink") or context.get("link") or "").strip()
    if ftype == "site_address":
        return override or str(context.get("site_address") or "").strip()
    if ftype == "phone":
        return override or str(context.get("phone") or "").strip()
    if ftype == "social_instagram":
        v = override or str(context.get("social_instagram") or "").strip()
        return f"اینستاگرام: {v}" if v else ""
    if ftype == "social_telegram":
        v = override or str(context.get("social_telegram") or "").strip()
        return f"تلگرام: {v}" if v else ""
    if ftype == "social_whatsapp":
        v = override or str(context.get("social_whatsapp") or "").strip()
        return f"واتساپ: {v}" if v else ""
    return ""


def _apply_align(text: str, align: str) -> str:
    if align == "left":
        return _LRM + text
    if align == "center":
        return _CENTER_PAD + text
    return _RLM + text  # right (پیش‌فرض)


def render_post_text(context: dict, template: dict, *, as_html: bool = True) -> str:
    """خروجی: متنِ آماده برای ارسال به‌عنوانِ متن/کپشنِ پست.

    as_html=True: متنِ HTMLِ ساده (فقط <b>/<i>/<a>) — فقط برای پلتفرم‌هایی
    که parse_mode=HTML رو واقعاً رندر می‌کنن (تلگرام). as_html=False:
    متنِ کاملاً ساده، بدونِ هیچ تگ یا escape (لازم برای بله، چون HTML رو
    رندر نمی‌کنه و اگه تگ بفرستیم عیناً به‌صورتِ متنِ خام دیده می‌شه).

    context شاملِ name/price/description/permalink/site_address/phone/
    social_instagram/social_telegram/social_whatsapp می‌شه."""
    tpl = normalize_template(template)
    lines: list[str] = []
    for field in tpl["fields"]:
        value = _field_value(field, context)
        if not value:
            continue
        if field.get("blank_line_before") and lines:
            lines.append("")

        is_link = field.get("type") == "link"
        link_label = str(field.get("text") or "").strip() if is_link else ""

        if as_html:
            if is_link:
                escaped_url = _html.escape(value, quote=True)
                display = _html.escape(link_label) if link_label else _html.escape(value)
                text = f'<a href="{escaped_url}">{display}</a>'
            else:
                text = _html.escape(value)
            if field.get("bold"):
                text = f"<b>{text}</b>"
            if field.get("italic"):
                text = f"<i>{text}</i>"
        else:
            # متنِ ساده (بله): چون بدونِ HTML نمی‌شه یک برچسب رو به‌جایِ خودِ
            # لینک کلیک‌پذیر کرد، برچسب (اگه باشه) قبل از خودِ URL میاد،
            # نه به‌جاش — وگرنه لینک اصلاً قابلِ‌استفاده نمی‌مونه
            text = f"{link_label}: {value}" if (is_link and link_label) else value

        text = _apply_align(text, field.get("align", "right"))
        lines.append(text)
    return "\n".join(lines)
