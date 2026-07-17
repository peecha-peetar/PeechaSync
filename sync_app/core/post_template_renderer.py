"""رندرِ «کارتِ متنیِ پست» — یک تصویرِ کاملاً متنی (بدونِ عکسِ محصول داخلِ
خودش) که به‌همراهِ عکسِ اصلیِ سایت (کاملاً دست‌نخورده) در یک آلبوم ارسال
می‌شه؛ چون تلگرام/بله رنگ و اندازه‌فونتِ دلخواه رو توی کپشن پشتیبانی
نمی‌کنن، تنها راهِ داشتنِ فیلدهای رنگی/فونت‌دار همینه.

هر فیلد (نامِ محصول/قیمت/توضیح/لینک/آدرسِ سایت/تلفن/شبکه‌های اجتماعی/
متنِ دلخواه) اندازه‌فونت، رنگ، ضخامت، چیدمان و فاصله‌ی قبل از خودش رو
جداگانه داره؛ ارتفاعِ کارت بر اساسِ محتوای واقعی خودکار محاسبه می‌شه."""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from sync_app.core.content_studio_helper import _fmt_price, _get_font, shape_persian_text
from sync_app.core.media_center import ConvertResult
from sync_app.core.sync_utils import resource_path

CARD_WIDTH = 1080

_BOLD_FONT_PATH = resource_path("Vazirmatn-Bold.ttf")


def _get_bold_font(size: int):
    try:
        return ImageFont.truetype(_BOLD_FONT_PATH, size)
    except Exception:
        return _get_font(size)


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

TEXT_ALIGN_LABELS = {"right": "راست", "center": "وسط", "left": "چپ"}

DEFAULT_FIELD = {
    "type": "custom_text",
    "text": "",
    "font_size_pct": 0.045,
    "color": [30, 30, 30],
    "bold": False,
    "align": "right",
    "spacing_before_pct": 0.025,
}

DEFAULT_TEMPLATE = {
    "id": "",
    "title": "پیش‌فرض",
    "bg_color": [255, 255, 255],
    "margin_pct": 0.06,
    "fields": [
        {"type": "product_name", "text": "", "font_size_pct": 0.065, "color": [17, 24, 39],
         "bold": True, "align": "right", "spacing_before_pct": 0.0},
        {"type": "price", "text": "", "font_size_pct": 0.05, "color": [180, 83, 9],
         "bold": True, "align": "right", "spacing_before_pct": 0.03},
        {"type": "description", "text": "", "font_size_pct": 0.035, "color": [71, 85, 105],
         "bold": False, "align": "right", "spacing_before_pct": 0.035},
        {"type": "link", "text": "", "font_size_pct": 0.032, "color": [37, 99, 235],
         "bold": False, "align": "right", "spacing_before_pct": 0.04},
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


def _align_anchor(align: str) -> str:
    if align == "center":
        return "ma"
    if align == "left":
        return "la"
    return "ra"


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


def _wrap_text_lines(text: str, font, max_width: float) -> list[str]:
    """می‌شکنه به چند خط بر اساسِ عرضِ واقعیِ متنِ شکل‌گرفته‌ی فارسی."""
    words = text.split()
    if not words:
        return []
    raw_lines = []
    current: list[str] = []
    for word in words:
        trial = current + [word]
        shaped_trial = shape_persian_text(" ".join(trial))
        width = font.getlength(shaped_trial) if hasattr(font, "getlength") else font.getsize(shaped_trial)[0]
        if width <= max_width or not current:
            current = trial
        else:
            raw_lines.append(" ".join(current))
            current = [word]
    if current:
        raw_lines.append(" ".join(current))
    return [shape_persian_text(line) for line in raw_lines]


def render_post_template(dst_path: str, context: dict, template: dict) -> ConvertResult:
    """رندرِ کارتِ متنی — بدونِ عکسِ محصول؛ فقط زمینه + فیلدهای متنیِ قالب.
    context شاملِ name/price/description/permalink/site_address/phone/
    social_instagram/social_telegram/social_whatsapp می‌شه."""
    tpl = normalize_template(template)
    result = ConvertResult(src_path="")
    margin = int(CARD_WIDTH * float(tpl.get("margin_pct", 0.06)))
    max_text_width = CARD_WIDTH - 2 * margin

    try:
        prepared = []
        for field in tpl["fields"]:
            value = _field_value(field, context)
            if not value:
                continue
            font_size = max(10, int(CARD_WIDTH * float(field.get("font_size_pct", 0.04))))
            font = _get_bold_font(font_size) if field.get("bold") else _get_font(font_size)
            lines = _wrap_text_lines(value, font, max_text_width)
            if not lines:
                continue
            align = field.get("align", "right")
            if align == "right":
                x = CARD_WIDTH - margin
            elif align == "left":
                x = margin
            else:
                x = CARD_WIDTH // 2
            prepared.append({
                "lines": lines,
                "font": font,
                "color": tuple(int(c) for c in (field.get("color") or [30, 30, 30])),
                "x": x,
                "anchor": _align_anchor(align),
                "line_height": int(font_size * 1.45),
                "spacing_before": int(CARD_WIDTH * float(field.get("spacing_before_pct", 0.02))),
            })

        if not prepared:
            result.error = "هیچ فیلدی برای نمایش نداره (همه‌ی فیلدها خالی‌ان)."
            return result

        total_h = margin
        for item in prepared:
            total_h += item["spacing_before"] + item["line_height"] * len(item["lines"])
        total_h += margin

        bg = tuple(int(c) for c in (tpl.get("bg_color") or [255, 255, 255]))
        canvas = Image.new("RGB", (CARD_WIDTH, total_h), color=bg)
        draw = ImageDraw.Draw(canvas)

        y = margin
        for item in prepared:
            y += item["spacing_before"]
            for line in item["lines"]:
                draw.text((item["x"], y), line, font=item["font"], fill=item["color"], anchor=item["anchor"])
                y += item["line_height"]

        os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
        canvas.save(dst_path, quality=92)
        result.dst_path = dst_path
        result.size_after = os.path.getsize(dst_path)
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    return result
