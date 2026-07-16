"""
AI Content Studio — تولید محتوای تبلیغاتی محصول.
همه‌ی متن‌ها قالب‌محورند (بدون هوش مصنوعی واقعی، چون API نداریم).
بنرها/پست/استوری با PIL ساخته می‌شوند؛ برای نمایش درست حروف فارسی از
arabic_reshaper + python-bidi استفاده می‌شود (بدون این دو، حروف فارسی
روی تصویر بریده/نامتصل نمایش داده می‌شوند).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from sync_app.core.media_center import ConvertResult, _fit_to_size_with_padding
from sync_app.core.seo_helper import generate_keywords
from sync_app.core.sync_utils import resource_path

FONT_PATH = resource_path("IRANSans.ttf")

_shaping_checked = False
_SHAPING_SUPPORTED = False


def _ensure_text_shaping():
    """arabic_reshaper/python-bidi را فقط هنگام نیاز واقعی import می‌کند (lazy، طبق تجربه‌ی قبلی پروژه)."""
    global _shaping_checked, _SHAPING_SUPPORTED
    if not _shaping_checked:
        _shaping_checked = True
        try:
            import arabic_reshaper  # noqa
            from bidi.algorithm import get_display  # noqa
            _SHAPING_SUPPORTED = True
        except Exception:
            _SHAPING_SUPPORTED = False
    return _SHAPING_SUPPORTED


def shape_persian_text(text: str) -> str:
    """متن فارسی را برای نمایش صحیح (حروف متصل + راست‌به‌چپ) روی تصویر آماده می‌کند."""
    if not _ensure_text_shaping():
        return text
    import arabic_reshaper
    from bidi.algorithm import get_display

    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


# ---------------------------------------------------------------------------
# تولید متن (کپشن/پیام/هشتگ/CTA) — قالب‌محور
# ---------------------------------------------------------------------------

CTA_TEMPLATES = [
    "همین حالا سفارش دهید!",
    "تا پایان موجودی فرصت دارید!",
    "برای خرید کلیک کنید.",
    "امروز سفارش دهید، فردا دستتونه!",
]


def generate_hashtags(product: dict, *, max_tags: int = 6) -> list[str]:
    keywords = generate_keywords(product, max_keywords=max_tags)
    return ["#" + k.replace(" ", "_") for k in keywords]


def generate_cta(index: int = 0) -> str:
    return CTA_TEMPLATES[index % len(CTA_TEMPLATES)]


def _fmt_price(price) -> str:
    try:
        return f"{float(price):,.0f}"
    except (TypeError, ValueError):
        return str(price or "")


def generate_instagram_caption(product: dict) -> str:
    name = product.get("name", "")
    price = _fmt_price(product.get("price"))
    desc = product.get("description", "")
    hashtags = " ".join(generate_hashtags(product))
    lines = [f"✨ {name}", f"💰 قیمت: {price} تومان"]
    if desc:
        lines.append(desc[:150])
    lines.append(generate_cta())
    lines.append(hashtags)
    return "\n\n".join(lines)


def generate_telegram_text(product: dict) -> str:
    name = product.get("name", "")
    price = _fmt_price(product.get("price"))
    desc = product.get("description", "")
    lines = [f"🔥 {name}", f"قیمت: {price} تومان"]
    if desc:
        lines.append(desc[:200])
    lines.append(generate_cta())
    return "\n".join(lines)


def generate_whatsapp_text(product: dict) -> str:
    name = product.get("name", "")
    price = _fmt_price(product.get("price"))
    return f"*{name}*\nقیمت: {price} تومان\n{generate_cta()}"


def generate_sms_text(product: dict, *, max_len: int = 140) -> str:
    """پیامک تبلیغاتی — کوتاه، چون پیامک فارسی محدودیت کاراکتر داره."""
    name = product.get("name", "")
    price = _fmt_price(product.get("price"))
    text = f"{name} فقط {price} تومان! {generate_cta()}"
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


# ---------------------------------------------------------------------------
# تولید بنر/پست/استوری (قالب‌محور — ترکیب عکس محصول + متن روی آن)
# ---------------------------------------------------------------------------

BANNER_SIZES = {
    "instagram_post": (1080, 1080),
    "instagram_story": (1080, 1920),
    "discount_banner": (1080, 1080),
    "seasonal_banner": (1080, 1080),
}


def _get_font(size: int) -> "ImageFont.FreeTypeFont":
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def _draw_text_box(draw: "ImageDraw.ImageDraw", box_xy, text: str, *, font_size: int, fill=(255, 255, 255), align_right_x=None, y=None):
    font = _get_font(font_size)
    shaped = shape_persian_text(text)
    x = align_right_x if align_right_x is not None else box_xy[0]
    yy = y if y is not None else box_xy[1]
    draw.text((x, yy), shaped, font=font, fill=fill, anchor="ra")


def create_promo_image(
    product_image_path: str,
    product: dict,
    dst_path: str,
    *,
    kind: str = "instagram_post",
    discount_percent: int | None = None,
    seasonal_text: str | None = None,
) -> ConvertResult:
    """
    ساخت بنر/پست/استوری تبلیغاتی — عکس محصول + نوار متنی پایین تصویر
    (نام، قیمت، و برچسب تخفیف/مناسبتی در صورت درخواست).
    """
    result = ConvertResult(src_path=product_image_path)
    target_w, target_h = BANNER_SIZES.get(kind, (1080, 1080))

    if not os.path.isfile(product_image_path):
        result.error = "تصویر محصول یافت نشد."
        return result

    try:
        result.size_before = os.path.getsize(product_image_path)
        with Image.open(product_image_path) as img:
            if img.mode in ("P", "LA"):
                img = img.convert("RGBA")
            elif img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            base = _fit_to_size_with_padding(img, target_w, target_h, bg_color=(250, 250, 250))

        canvas = base.convert("RGBA")
        draw = ImageDraw.Draw(canvas, "RGBA")

        # نوار نیمه‌شفاف پایین تصویر برای خوانا بودن متن
        band_h = int(target_h * 0.22)
        draw.rectangle(
            [0, target_h - band_h, target_w, target_h],
            fill=(0, 0, 0, 160),
        )

        name = str(product.get("name") or "").strip()
        price = _fmt_price(product.get("price"))
        margin = int(target_w * 0.05)

        _draw_text_box(
            draw, None, name, font_size=int(target_w * 0.045),
            align_right_x=target_w - margin, y=target_h - band_h + int(band_h * 0.15),
        )
        _draw_text_box(
            draw, None, f"{price} تومان", font_size=int(target_w * 0.055), fill=(255, 210, 60),
            align_right_x=target_w - margin, y=target_h - band_h + int(band_h * 0.5),
        )

        if discount_percent:
            badge_text = shape_persian_text(f"{discount_percent}٪ تخفیف")
            font = _get_font(int(target_w * 0.06))
            draw.ellipse(
                [margin, margin, margin + int(target_w * 0.22), margin + int(target_w * 0.22)],
                fill=(220, 38, 38, 230),
            )
            draw.text(
                (margin + int(target_w * 0.11), margin + int(target_w * 0.11)),
                badge_text, font=font, fill=(255, 255, 255), anchor="mm",
            )

        if seasonal_text:
            shaped = shape_persian_text(seasonal_text)
            font = _get_font(int(target_w * 0.05))
            draw.text(
                (target_w // 2, margin + int(target_w * 0.03)),
                shaped, font=font, fill=(255, 255, 255), anchor="ma",
                stroke_width=2, stroke_fill=(0, 0, 0),
            )

        os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
        canvas = canvas.convert("RGB")
        canvas.save(dst_path, quality=92)
        result.dst_path = dst_path
        result.size_after = os.path.getsize(dst_path)
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    return result
