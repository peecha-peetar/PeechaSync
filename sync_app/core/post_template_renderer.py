"""ساختِ متنِ پست از روی یک «قالبِ متنی» قابل‌تنظیم — بدونِ عکسِ کارتِ
جداگانه (طبق نظرِ کاربر: عکسِ اصلیِ سایت باید دست‌نخورده بمونه؛ «قالب»
فقط ساختارِ متنِ همراهِ پست رو تعیین می‌کنه، نه ظاهرِ عکس).

هر فیلد (نامِ محصول/قیمت/توضیح/لینک/آدرسِ سایت/تلفن/شبکه‌های اجتماعی/
متنِ دلخواه) می‌تونه Bold/Italic باشه و قبلش یک خطِ خالی داشته باشه.
چون تلگرام/بله رنگ و اندازه‌فونتِ دلخواه رو توی متن/کپشن پشتیبانی
نمی‌کنن، خروجی یک متنِ HTMLِ ساده (فقط <b>/<i>/<a>، سازگار با
parse_mode=HTML) است — همونی که واقعاً در پیام دیده می‌شه."""

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

DEFAULT_FIELD = {
    "type": "custom_text",
    "text": "",
    "bold": False,
    "italic": False,
    "blank_line_before": False,
}

DEFAULT_TEMPLATE = {
    "id": "",
    "title": "پیش‌فرض",
    "fields": [
        {"type": "product_name", "bold": True, "italic": False, "blank_line_before": False},
        {"type": "price", "bold": True, "italic": False, "blank_line_before": False},
        {"type": "description", "bold": False, "italic": False, "blank_line_before": True},
        {"type": "link", "bold": False, "italic": False, "blank_line_before": True},
    ],
}


def normalize_field(raw: dict | None) -> dict:
    """ادغامِ یک فیلدِ ناقص/قدیمی با مقادیرِ پیش‌فرض."""
    merged = dict(DEFAULT_FIELD)
    merged.update({k: v for k, v in (raw or {}).items() if v is not None})
    if merged.get("type") not in FIELD_TYPE_LABELS:
        merged["type"] = "custom_text"
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
    ftype = field.get("type")
    if ftype == "custom_text":
        return str(field.get("text") or "").strip()
    if ftype == "product_name":
        return str(context.get("name") or "").strip()
    if ftype == "price":
        price = context.get("price")
        if price in (None, "", 0):
            return ""
        return f"{_fmt_price(price)} تومان"
    if ftype == "description":
        return str(context.get("description") or "").strip()
    if ftype == "link":
        return str(context.get("permalink") or context.get("link") or "").strip()
    if ftype == "site_address":
        return str(context.get("site_address") or "").strip()
    if ftype == "phone":
        return str(context.get("phone") or "").strip()
    if ftype == "social_instagram":
        v = str(context.get("social_instagram") or "").strip()
        return f"اینستاگرام: {v}" if v else ""
    if ftype == "social_telegram":
        v = str(context.get("social_telegram") or "").strip()
        return f"تلگرام: {v}" if v else ""
    if ftype == "social_whatsapp":
        v = str(context.get("social_whatsapp") or "").strip()
        return f"واتساپ: {v}" if v else ""
    return ""


def render_post_text(context: dict, template: dict) -> str:
    """خروجی: متنِ HTMLِ ساده (سازگار با parse_mode=HTML تلگرام/بله) —
    آماده برای ارسالِ مستقیم به‌عنوانِ متن/کپشنِ پست. context شاملِ
    name/price/description/permalink/site_address/phone/social_instagram/
    social_telegram/social_whatsapp می‌شه."""
    tpl = normalize_template(template)
    lines: list[str] = []
    for field in tpl["fields"]:
        value = _field_value(field, context)
        if not value:
            continue
        if field.get("blank_line_before") and lines:
            lines.append("")
        if field.get("type") == "link":
            escaped_url = _html.escape(value, quote=True)
            text = f'<a href="{escaped_url}">{_html.escape(value)}</a>'
        else:
            text = _html.escape(value)
        if field.get("bold"):
            text = f"<b>{text}</b>"
        if field.get("italic"):
            text = f"<i>{text}</i>"
        lines.append(text)
    return "\n".join(lines)
