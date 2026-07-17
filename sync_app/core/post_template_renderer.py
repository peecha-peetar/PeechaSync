"""رندرِ پستِ تصویری بر اساسِ یک «قالب» قابل‌تنظیم (رنگ، چیدمان، سایزِ
متن) — برخلافِ create_promo_image در content_studio_helper.py (که چند
کیندِ ثابت داره)، اینجا همه‌چیز از روی دیکشنریِ template پارامتری می‌شه،
تا کاربر بتونه از «طراحِ قالب» (post_template_designer.py) قالبِ دلخواهِ
خودش رو بسازه و روی محصولاتِ مختلف دوباره استفاده کنه."""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

from sync_app.core.content_studio_helper import _fmt_price, _get_font, shape_persian_text
from sync_app.core.media_center import ConvertResult, _fit_to_size_with_padding

CANVAS_SIZES = {
    "square": (1080, 1080),
    "story": (1080, 1920),
}

CANVAS_LABELS = {
    "square": "مربعی (پست — ۱۰۸۰×۱۰۸۰)",
    "story": "استوری (۱۰۸۰×۱۹۲۰)",
}

TEXT_ALIGN_LABELS = {
    "right": "راست",
    "center": "وسط",
    "left": "چپ",
}

DEFAULT_TEMPLATE = {
    "id": "",
    "title": "پیش‌فرض",
    "canvas": "square",
    "band_color": [0, 0, 0],
    "band_opacity": 160,
    "band_height_pct": 0.22,
    "name_color": [255, 255, 255],
    "name_size_pct": 0.045,
    "price_color": [255, 210, 60],
    "price_size_pct": 0.055,
    "text_align": "right",
    "margin_pct": 0.05,
    "show_badge": False,
    "badge_text": "پیشنهاد ویژه",
    "badge_color": [220, 38, 38],
}


def normalize_template(raw: dict | None) -> dict:
    """ادغامِ یک قالبِ ناقص/قدیمی با مقادیرِ پیش‌فرض — تا افزودنِ فیلدِ جدید
    در آینده، قالب‌های ذخیره‌شده‌ی قدیمی رو خراب نکنه."""
    merged = dict(DEFAULT_TEMPLATE)
    merged.update({k: v for k, v in (raw or {}).items() if v is not None})
    if merged.get("canvas") not in CANVAS_SIZES:
        merged["canvas"] = "square"
    if merged.get("text_align") not in TEXT_ALIGN_LABELS:
        merged["text_align"] = "right"
    return merged


def _align_anchor(align: str) -> tuple[str, str]:
    """(anchor, x-position-kind) برای PIL draw.text — 'l'/'m'/'r' + a برای align عمودی‌ثابت."""
    if align == "center":
        return "ma", "center"
    if align == "left":
        return "la", "left"
    return "ra", "right"


def render_post_template(
    product_image_path: str,
    product: dict,
    dst_path: str,
    template: dict,
) -> ConvertResult:
    tpl = normalize_template(template)
    result = ConvertResult(src_path=product_image_path)
    target_w, target_h = CANVAS_SIZES.get(tpl["canvas"], CANVAS_SIZES["square"])

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

        band_h = int(target_h * float(tpl["band_height_pct"]))
        band_rgb = tuple(int(c) for c in tpl["band_color"])
        band_alpha = max(0, min(255, int(tpl["band_opacity"])))
        draw.rectangle(
            [0, target_h - band_h, target_w, target_h],
            fill=(*band_rgb, band_alpha),
        )

        margin = int(target_w * float(tpl["margin_pct"]))
        anchor, align_kind = _align_anchor(tpl["text_align"])
        if align_kind == "right":
            x = target_w - margin
        elif align_kind == "left":
            x = margin
        else:
            x = target_w // 2

        name = str(product.get("name") or "").strip()
        price = _fmt_price(product.get("price"))

        name_font = _get_font(int(target_w * float(tpl["name_size_pct"])))
        draw.text(
            (x, target_h - band_h + int(band_h * 0.15)),
            shape_persian_text(name), font=name_font,
            fill=tuple(int(c) for c in tpl["name_color"]), anchor=anchor,
        )

        price_font = _get_font(int(target_w * float(tpl["price_size_pct"])))
        draw.text(
            (x, target_h - band_h + int(band_h * 0.5)),
            shape_persian_text(f"{price} تومان"), font=price_font,
            fill=tuple(int(c) for c in tpl["price_color"]), anchor=anchor,
        )

        if tpl.get("show_badge"):
            badge_text = shape_persian_text(str(tpl.get("badge_text") or "").strip())
            badge_font = _get_font(int(target_w * 0.045))
            badge_r = int(target_w * 0.11)
            badge_color = tuple(int(c) for c in tpl["badge_color"])
            draw.ellipse(
                [margin, margin, margin + badge_r * 2, margin + badge_r * 2],
                fill=(*badge_color, 230),
            )
            draw.text(
                (margin + badge_r, margin + badge_r),
                badge_text, font=badge_font, fill=(255, 255, 255), anchor="mm",
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
