"""
مرکز رسانه — فاز ۱ (محلی، رایگان، بدون نیاز به API خارجی)
شامل: تبدیل به WebP، تغییر سایز گروهی، تشخیص تصویر تکراری،
نام‌گذاری سئوشده‌ی فایل، و امتیاز آمادگی انتشار محصول.
"""

from __future__ import annotations

import os
import re
import threading
import importlib.util
from dataclasses import dataclass, field

from PIL import Image


def _is_installed_safe(module_name: str) -> bool:
    """
    فقط چک می‌کند پکیج نصب است یا نه — بدون اجرای کد پکیج (پس هیچ ریسک
    کرش نیتیوی ندارد). برای نمایش صحیح در UI بدون فعال‌سازی import واقعی.
    """
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def heic_available_for_ui() -> bool:
    return _is_installed_safe("pillow_heif")


# نکته‌ی مهم امنیتی/پایداری: pillow_heif و imagehash عمداً اینجا
# import نمی‌شوند (eager) — چون اگر روی سیستم کاربر (مخصوصاً ویندوز) این
# کتابخانه‌ها با DLL ناسازگار مواجه بشوند، ممکن است کرش سطح پایین (نه یک
# Exception پایتونی قابل‌گرفتن) بدهند. اگر این import در بالای فایل بود،
# همین باز شدن تب محصولات/رسانه (که این ماژول را import می‌کنند) کرش می‌کرد.
# با lazy-import، فقط دکمه‌ی مربوطه (HEIC / تشخیص تکراری) در معرض این
# ریسک است، نه کل تب.

_heic_checked = False
HEIC_SUPPORTED = False
_heic_lock = threading.Lock()


def _ensure_heic_checked() -> bool:
    global _heic_checked, HEIC_SUPPORTED
    with _heic_lock:
        if not _heic_checked:
            _heic_checked = True
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
                HEIC_SUPPORTED = True
            except Exception:
                HEIC_SUPPORTED = False
        return HEIC_SUPPORTED


_hash_checked = False
HASH_SUPPORTED = False
_hash_lock = threading.Lock()


def _ensure_imagehash():
    """imagehash را فقط هنگام نیاز واقعی (تشخیص تکراری) import می‌کند."""
    global _hash_checked, HASH_SUPPORTED
    with _hash_lock:
        if not _hash_checked:
            _hash_checked = True
            try:
                import imagehash as _imagehash_mod
                HASH_SUPPORTED = True
                return _imagehash_mod
            except Exception:
                HASH_SUPPORTED = False
                return None
        if HASH_SUPPORTED:
            import imagehash as _imagehash_mod
            return _imagehash_mod
        return None


SUPPORTED_INPUT_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
HEIC_EXT = {".heic", ".heif"}


def is_valid_image_data(data: bytes, *, min_bytes: int = 800) -> bool:
    """
    تأیید واقعی اینکه این داده‌ی باینری واقعاً یک عکس معتبر و قابل‌بازشدن است —
    نه فقط اینکه ستون خالی نیست. خیلی از ERPها یک مقدار جای‌گذار کوچک
    (چند بایت) در ستون Picture می‌گذارند که با چک صرفِ «خالی نیست» اشتباهی
    «دارد» تشخیص داده می‌شد.
    """
    if not data or len(data) < min_bytes:
        return False
    try:
        import io
        with Image.open(io.BytesIO(bytes(data))) as img:
            img.verify()
        return True
    except Exception:
        return False


def is_valid_image_file(path: str, *, min_bytes: int = 800) -> bool:
    """همان تأیید بالا، برای فایل روی دیسک (PicturePath یا تصاویر دستی آپلودشده)."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < min_bytes:
            return False
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False



def is_supported_image(path: str) -> bool:
    ext = os.path.splitext(path or "")[1].lower()
    if ext in SUPPORTED_INPUT_EXT:
        return True
    if ext in HEIC_EXT:
        return _ensure_heic_checked()
    return False


@dataclass
class ConvertResult:
    src_path: str
    dst_path: str = ""
    ok: bool = False
    error: str = ""
    size_before: int = 0
    size_after: int = 0

    @property
    def saved_percent(self) -> float:
        if self.size_before <= 0:
            return 0.0
        return max(0.0, (1 - (self.size_after / self.size_before)) * 100)


def convert_to_webp(
    src_path: str,
    dst_path: str | None = None,
    *,
    quality: int = 82,
    max_width: int | None = None,
    max_height: int | None = None,
) -> ConvertResult:
    """
    یک تصویر را به WebP تبدیل می‌کند (اختیاری: هم‌زمان تغییر سایز).
    اگر max_width/max_height داده شود، فقط در صورت بزرگ‌تر بودن کوچک می‌شود (بدون کِش رفتن).
    """
    result = ConvertResult(src_path=src_path)
    if not os.path.isfile(src_path):
        result.error = "فایل مبدا یافت نشد."
        return result
    if not is_supported_image(src_path):
        result.error = "فرمت پشتیبانی نمی‌شود."
        return result

    try:
        result.size_before = os.path.getsize(src_path)
        with Image.open(src_path) as img:
            img = img.convert("RGBA") if img.mode in ("P", "LA") else img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
            if max_width or max_height:
                img = _resize_within(img, max_width, max_height)

            if not dst_path:
                stem, _ = os.path.splitext(src_path)
                dst_path = stem + ".webp"

            os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
            img.save(dst_path, "WEBP", quality=quality, method=6)

        result.dst_path = dst_path
        result.size_after = os.path.getsize(dst_path)
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    return result


def _resize_within(img: Image.Image, max_width: int | None, max_height: int | None) -> Image.Image:
    """کوچک کردن تصویر در چارچوب max_width×max_height — فقط اگر بزرگ‌تر باشد (بدون کش رفتن)."""
    w, h = img.size
    mw = max_width or w
    mh = max_height or h
    if w <= mw and h <= mh:
        return img
    ratio = min(mw / w, mh / h)
    new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def bulk_resize(
    src_paths: list[str],
    out_dir: str,
    *,
    max_width: int = 1200,
    max_height: int = 1200,
    to_webp: bool = False,
    quality: int = 85,
) -> list[ConvertResult]:
    """تغییر سایز گروهی — خروجی در out_dir با همان نام (یا .webp اگر to_webp)."""
    results: list[ConvertResult] = []
    os.makedirs(out_dir, exist_ok=True)
    for src in src_paths:
        name = os.path.basename(src)
        stem, ext = os.path.splitext(name)
        dst_ext = ".webp" if to_webp else ext
        dst = os.path.join(out_dir, f"{stem}{dst_ext}")
        if to_webp:
            results.append(
                convert_to_webp(src, dst, quality=quality, max_width=max_width, max_height=max_height)
            )
            continue

        result = ConvertResult(src_path=src)
        if not os.path.isfile(src) or not is_supported_image(src):
            result.error = "فایل نامعتبر یا فرمت پشتیبانی‌نشده."
            results.append(result)
            continue
        try:
            result.size_before = os.path.getsize(src)
            with Image.open(src) as img:
                img = _resize_within(img, max_width, max_height)
                img.save(dst)
            result.dst_path = dst
            result.size_after = os.path.getsize(dst)
            result.ok = True
        except Exception as exc:
            result.error = str(exc)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# تشخیص تصویر تکراری
# ---------------------------------------------------------------------------

def image_phash(path: str):
    """هش ادراکی تصویر — برای تشخیص شباهت (نه فقط یکسان بودن بایت‌به‌بایت)."""
    imagehash_mod = _ensure_imagehash()
    if imagehash_mod is None:
        raise RuntimeError("کتابخانه imagehash نصب نیست یا بارگذاری آن ناموفق بود.")
    with Image.open(path) as img:
        return imagehash_mod.phash(img)


def find_duplicate_groups(image_paths: list[str], *, max_distance: int = 10) -> list[list[str]]:
    """
    گروه‌بندی تصاویر مشابه/تکراری بر اساس هش ادراکی.
    max_distance: فاصله‌ی همینگ مجاز بین دو هش برای «تکراری» محسوب شدن
    (۰ = کاملاً یکسان بایت‌به‌بایت از نظر محتوا. ۸ تا ۱۲ برای همون عکس با
    سایز/فشرده‌سازی کمی متفاوت. بالاتر از ۱۵ ریسک تشخیص اشتباه دو عکس متفاوت
    به‌عنوان تکراری را افزایش می‌دهد — قابل تنظیم در تنظیمات مرکز رسانه.)
    خروجی: فقط گروه‌هایی با بیش از یک عضو.
    """
    hashes: dict[str, object] = {}
    for path in image_paths:
        if not os.path.isfile(path) or not is_supported_image(path):
            continue
        try:
            hashes[path] = image_phash(path)
        except Exception:
            continue

    paths = list(hashes.keys())
    visited: set[str] = set()
    groups: list[list[str]] = []
    for i, p1 in enumerate(paths):
        if p1 in visited:
            continue
        group = [p1]
        for p2 in paths[i + 1:]:
            if p2 in visited:
                continue
            if hashes[p1] - hashes[p2] <= max_distance:
                group.append(p2)
                visited.add(p2)
        if len(group) > 1:
            visited.add(p1)
            groups.append(group)
    return groups



# ---------------------------------------------------------------------------
# فشرده‌سازی بدون تغییر فرمت
# ---------------------------------------------------------------------------

def compress_image(src_path: str, dst_path: str | None = None, *, quality: int = 85) -> ConvertResult:
    """فشرده‌سازی تصویر با همون فرمت فعلی (نه WebP) — برای وقتی فقط حجم مهمه نه فرمت."""
    result = ConvertResult(src_path=src_path)
    if not os.path.isfile(src_path):
        result.error = "فایل مبدا یافت نشد."
        return result
    if not is_supported_image(src_path):
        result.error = "فرمت پشتیبانی نمی‌شود."
        return result

    dst_path = dst_path or src_path
    try:
        result.size_before = os.path.getsize(src_path)
        with Image.open(src_path) as img:
            ext = os.path.splitext(dst_path)[1].lower()
            os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
            if ext in (".jpg", ".jpeg"):
                img = img.convert("RGB")
                img.save(dst_path, "JPEG", quality=quality, optimize=True)
            elif ext == ".png":
                img.save(dst_path, "PNG", optimize=True)
            else:
                img.save(dst_path, optimize=True)
        result.dst_path = dst_path
        result.size_after = os.path.getsize(dst_path)
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    return result


# ---------------------------------------------------------------------------
# واترمارک
# ---------------------------------------------------------------------------

def apply_watermark(
    image_path: str,
    watermark_path: str,
    dst_path: str | None = None,
    *,
    opacity: float = 0.55,
    scale: float = 0.18,
    margin_percent: float = 0.03,
    position: str = "bottom-right",
) -> ConvertResult:
    """
    چسباندن لوگو/واترمارک روی یک تصویر.
    scale: عرض واترمارک نسبت به عرض تصویر اصلی (۰.۱۸ یعنی ۱۸٪ عرض تصویر).
    position: bottom-right | bottom-left | top-right | top-left | center
    """
    result = ConvertResult(src_path=image_path)
    if not os.path.isfile(image_path):
        result.error = "تصویر مبدا یافت نشد."
        return result
    if not os.path.isfile(watermark_path):
        result.error = "فایل واترمارک/لوگو یافت نشد — در تنظیمات انتخاب کنید."
        return result

    try:
        result.size_before = os.path.getsize(image_path)
        with Image.open(image_path) as base, Image.open(watermark_path) as mark:
            base = base.convert("RGBA")
            mark = mark.convert("RGBA")

            target_w = max(1, int(base.width * scale))
            ratio = target_w / mark.width
            target_h = max(1, int(mark.height * ratio))
            mark = mark.resize((target_w, target_h), Image.LANCZOS)

            if opacity < 1.0:
                alpha = mark.split()[3].point(lambda p: int(p * opacity))
                mark.putalpha(alpha)

            margin_x = int(base.width * margin_percent)
            margin_y = int(base.height * margin_percent)
            positions = {
                "bottom-right": (base.width - target_w - margin_x, base.height - target_h - margin_y),
                "bottom-left": (margin_x, base.height - target_h - margin_y),
                "top-right": (base.width - target_w - margin_x, margin_y),
                "top-left": (margin_x, margin_y),
                "center": ((base.width - target_w) // 2, (base.height - target_h) // 2),
            }
            pos = positions.get(position, positions["bottom-right"])

            composed = Image.new("RGBA", base.size)
            composed.paste(base, (0, 0))
            composed.paste(mark, pos, mark)

            if not dst_path:
                stem, ext = os.path.splitext(image_path)
                dst_path = f"{stem}_wm{ext}"

            os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
            out_ext = os.path.splitext(dst_path)[1].lower()
            if out_ext in (".jpg", ".jpeg"):
                # ترکیب درست روی پس‌زمینه‌ی سفید قبل از تبدیل به RGB — وگرنه
                # اگه تصویر اصلی خودش PNG شفاف بود، حاشیه‌ها مشکی ذخیره می‌شدن.
                flat = Image.new("RGBA", composed.size, (255, 255, 255, 255))
                flat.alpha_composite(composed)
                composed = flat.convert("RGB")
                composed.save(dst_path, "JPEG", quality=92)
            else:
                composed.save(dst_path)

        result.dst_path = dst_path
        result.size_after = os.path.getsize(dst_path)
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    return result


# ---------------------------------------------------------------------------
# پروفایل‌های خروجی تصویر (Image Profiles) — ووکامرس/اینستاگرام/استوری/تلگرام/تامبنیل
# ---------------------------------------------------------------------------

IMAGE_PROFILES_KEY = "IMAGE_SIZE_PROFILES"

# هر پروفایل: عرض/ارتفاع، کیفیت فشرده‌سازی جدا، و پسوند نام فایل جدا از نام نمایشی پروفایل
DEFAULT_IMAGE_PROFILES = {
    "ووکامرس": {"w": 1200, "h": 1200, "quality": 85, "suffix": "woocommerce", "margin": 0},
    "اینستاگرام": {"w": 1080, "h": 1080, "quality": 85, "suffix": "instagram", "margin": 0},
    "استوری": {"w": 1080, "h": 1920, "quality": 85, "suffix": "story", "margin": 0},
    "تلگرام": {"w": 1280, "h": 720, "quality": 85, "suffix": "telegram", "margin": 0},
    "تامبنیل": {"w": 300, "h": 300, "quality": 80, "suffix": "thumb", "margin": 0},
}


def load_image_profiles(config: dict) -> dict:
    raw = (config or {}).get(IMAGE_PROFILES_KEY)
    if isinstance(raw, dict) and raw:
        # سازگاری با نسخه‌ی قبلی‌تر که quality/suffix/margin نداشت
        fixed = {}
        for name, dims in raw.items():
            fixed[name] = {
                "w": int(dims.get("w", 1000)),
                "h": int(dims.get("h", 1000)),
                "quality": int(dims.get("quality", 85)),
                # پسوند اختیاریه — دیگه به‌زور روی نام پروفایل ست نمی‌شه
                "suffix": str(dims.get("suffix", "")).strip(),
                "margin": int(dims.get("margin", 0)),  # درصد حاشیه‌ی خالی دور تصویر
            }
        return fixed
    return dict(DEFAULT_IMAGE_PROFILES)


def generate_profile_outputs(
    src_path: str,
    out_dir: str,
    profile_names: list[str],
    profiles: dict,
    *,
    to_webp: bool = True,
    watermark: dict | None = None,
) -> list["ConvertResult"]:
    """
    از یک تصویر مبدا، به‌ازای هر پروفایل انتخابی یک خروجی جدا می‌سازد.
    کیفیت فشرده‌سازی از خودِ تنظیمات همان پروفایل خوانده می‌شود.
    نام فایل خروجی: {نام فایل ورودی}${پسوند پروفایل} — اگر پروفایل پسوند
    نداشت (خالی)، همون نام فایل ورودی (بدون هیچ اضافه‌ای) استفاده می‌شود.

    watermark (اختیاری): دیکشنری تنظیمات واترمارک (همون خروجی
    smart_publish.load_watermark_settings) — اگه داده بشه و path معتبر
    داشته باشه، بعد از Resize روی همون فایل خروجی اعمال می‌شه (دقیقاً با
    همون منطق/کیفیتی که «انتشار هوشمند» استفاده می‌کنه).
    """
    results: list[ConvertResult] = []
    stem = os.path.splitext(os.path.basename(src_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    watermark_path = str((watermark or {}).get("path") or "").strip()

    for profile_name in profile_names:
        dims = profiles.get(profile_name)
        if not dims:
            continue
        quality = int(dims.get("quality", 85))
        suffix = str(dims.get("suffix") or "").strip()
        margin = int(dims.get("margin", 0))
        result = ConvertResult(src_path=src_path)
        try:
            result.size_before = os.path.getsize(src_path)
            with Image.open(src_path) as img:
                if img.mode in ("P", "LA"):
                    img = img.convert("RGBA")
                elif img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                fitted = _fit_to_size_with_padding(img, dims["w"], dims["h"], margin_percent=margin)
                ext = ".webp" if to_webp else (os.path.splitext(src_path)[1].lower() or ".jpg")
                out_name = f"{stem}${suffix}{ext}" if suffix else f"{stem}{ext}"
                dst = os.path.join(out_dir, out_name)
                if to_webp:
                    fitted.save(dst, "WEBP", quality=quality, method=6)
                elif ext in (".jpg", ".jpeg"):
                    fitted.convert("RGB").save(dst, "JPEG", quality=quality)
                else:
                    fitted.save(dst)

            if watermark_path and os.path.isfile(watermark_path):
                wm_result = apply_watermark(
                    dst, watermark_path, dst,
                    opacity=float((watermark or {}).get("opacity", 0.55)),
                    scale=float((watermark or {}).get("scale", 0.18)),
                    margin_percent=float((watermark or {}).get("margin", 0.03)),
                    position=str((watermark or {}).get("position", "bottom-right")),
                )
                if not wm_result.ok:
                    raise RuntimeError(f"واترمارک اعمال نشد: {wm_result.error}")

            result.dst_path = dst
            result.size_after = os.path.getsize(dst)
            result.ok = True
        except Exception as exc:
            result.error = str(exc)
        results.append(result)
    return results


def _fit_to_size_with_padding(
    img: "Image.Image",
    target_w: int,
    target_h: int,
    *,
    bg_color: tuple[int, int, int] = (255, 255, 255),
    max_upscale: float = 1.15,
    margin_percent: int = 0,
) -> "Image.Image":
    """
    تصویر را بدون هیچ برشی (بدون از‌دست‌رفتن حتی یک پیکسل از سوژه) داخل
    قاب target_w×target_h جا می‌دهد — نسبت تصویر همیشه حفظ می‌شود؛ هر فضای
    خالی که باقی بماند (چون نسبت تصویر با نسبت پروفایل یکی نیست) با رنگ
    پس‌زمینه (پیش‌فرض سفید) پر می‌شود، نه با برش زدن از تصویر.
    بزرگ‌نمایی هم حداکثر تا max_upscale مجاز است تا حجم/کیفیت خراب نشود.
    margin_percent: حاشیه‌ی خالی اضافه دور تصویر (۰ تا ~۴۰) — مثلاً ۱۰ یعنی
    ۱۰٪ از هر طرف قاب، خالی (پس‌زمینه) باقی بماند و تصویر داخل فضای باقی‌مانده جا شود.
    """
    margin_percent = max(0, min(45, margin_percent))
    effective_w = max(1, round(target_w * (1 - margin_percent / 100)))
    effective_h = max(1, round(target_h * (1 - margin_percent / 100)))

    src_ratio = img.width / img.height
    target_ratio = effective_w / effective_h

    if src_ratio > target_ratio:
        new_w = effective_w
        new_h = max(1, round(new_w / src_ratio))
    else:
        new_h = effective_h
        new_w = max(1, round(new_h * src_ratio))

    scale = new_w / img.width
    scale = min(scale, max_upscale)
    new_w = max(1, round(img.width * scale))
    new_h = max(1, round(img.height * scale))
    # اگر بعد از سقف upscale هنوز بزرگ‌تر از فضای مؤثر (با احتساب حاشیه) بود، محدودش کن
    if new_w > effective_w or new_h > effective_h:
        shrink = min(effective_w / new_w, effective_h / new_h)
        new_w = max(1, round(new_w * shrink))
        new_h = max(1, round(new_h * shrink))

    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # نکته‌ی مهم: تبدیل مستقیم RGBA→RGB مقادیر پیکسل‌های شفاف رو همون‌طور که
    # ذخیره شده (اغلب مشکی) نگه می‌داره، نه سفید. باید اول درست روی پس‌زمینه
    # ترکیب (composite) بشه، بعد به RGB تبدیل بشه — وگرنه PNGهای شفاف با
    # حاشیه‌ی مشکی ذخیره می‌شن.
    if resized.mode in ("RGBA", "LA") or (resized.mode == "P" and "transparency" in resized.info):
        resized = resized.convert("RGBA")
        flat = Image.new("RGBA", resized.size, bg_color + (255,))
        flat.alpha_composite(resized)
        resized = flat.convert("RGB")
    else:
        resized = resized.convert("RGB")

    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    paste_x = (target_w - new_w) // 2
    paste_y = (target_h - new_h) // 2
    canvas.paste(resized, (paste_x, paste_y))
    return canvas



# ---------------------------------------------------------------------------
# تشخیص تصاویر بی‌کیفیت (رزولوشن پایین / تار)
# ---------------------------------------------------------------------------

def detect_low_quality(path: str, *, min_dimension: int = 500, blur_threshold: float = 350.0):
    """
    بررسی سریع کیفیت تصویر — بدون کتابخانه‌ی سنگین (فقط PIL):
    ۱) رزولوشن خیلی پایین (کوچک‌تر از min_dimension در هر بعد)
    ۲) تاری بالا (واریانس پایین در فیلتر لبه‌یاب — شاخصی ساده برای Blur Detection)
    خروجی: (is_low_quality: bool, reasons: list[str])
    نکته: blur_threshold یک آستانه‌ی تجربی است (نه استاندارد علمی دقیق) —
    اگر روی تصاویر واقعی فروشگاه شما پرچم اشتباه زیاد زد، از تنظیمات قابل تغییر است.
    """
    from PIL import ImageFilter, ImageStat

    reasons = []
    try:
        with Image.open(path) as img:
            w, h = img.size
            if w < min_dimension or h < min_dimension:
                reasons.append(f"رزولوشن پایین ({w}×{h})")

            gray = img.convert("L")
            edges = gray.filter(ImageFilter.FIND_EDGES)
            variance = ImageStat.Stat(edges).var[0]
            if variance < blur_threshold:
                reasons.append(f"احتمال تاری تصویر (شاخص وضوح: {variance:.1f})")
    except Exception as exc:
        reasons.append(f"خطا در بررسی: {exc}")

    return bool(reasons), reasons


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# نام فایل سئوشده
# ---------------------------------------------------------------------------

def seo_slug(text: str, *, max_words: int = 6) -> str:
    """
    نام محصول -> نام فایل سئوشده (لاتین/عددی، با خط تیره).
    اگر متن غیرلاتین (مثلاً فارسی) باشد و بعد از تمیزکاری چیزی نماند،
    از خودِ متن به‌صورت خام (بدون کاراکترهای غیرمجاز فایل) استفاده می‌شود.
    """
    raw = str(text or "").strip()
    if not raw:
        return "product"

    ascii_only = re.sub(r"[^a-zA-Z0-9\s-]", " ", raw)
    words = [w.lower() for w in ascii_only.split() if w]
    if words:
        slug = "-".join(words[:max_words])
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        if slug:
            return slug

    # fallback برای متن غیرلاتین (فارسی و غیره) — کاراکترهای ناسازگار با نام فایل حذف شود
    safe = re.sub(r'[\\/:*?"<>|]', "", raw)
    safe = re.sub(r"\s+", "-", safe).strip("-")
    return safe or "product"


def seo_filename(product_name: str, original_filename: str, *, suffix: str = "") -> str:
    """
    مثال: IMG_8451.jpg + نام محصول "کفش نایک Air Max مشکی" -> nike-air-max-black.webp
    اگر suffix داده شود (مثل شماره‌ی تصویر دوم/سوم محصول) به انتها اضافه می‌شود.
    """
    ext = os.path.splitext(original_filename or "")[1].lower() or ".webp"
    slug = seo_slug(product_name)
    if suffix:
        slug = f"{slug}-{suffix}"
    return f"{slug}{ext}"


# ---------------------------------------------------------------------------
# وارد کردن گروهی تصاویر بر اساس نام فایل (کد کالا)
# قرارداد نام‌گذاری: 1001.jpg = عکس اصلی کالای 1001
#                    1001$1.jpg، 1001$2.jpg = عکس‌های بعدی همان کالا
# ---------------------------------------------------------------------------

def parse_image_filename(filename: str) -> tuple[str, int]:
    """
    نام فایل -> (کد کالا, شماره‌ترتیب). شماره‌ی ۰ یعنی عکس اصلی.
    مثال‌ها: '1001.jpg' -> ('1001', 0) | '1001$1.jpg' -> ('1001', 1)
    """
    stem = os.path.splitext(os.path.basename(filename))[0].strip()
    if "$" in stem:
        code_part, _, idx_part = stem.partition("$")
        code_part = code_part.strip()
        idx_part = idx_part.strip()
        idx = int(idx_part) if idx_part.isdigit() else 999
        return code_part, idx
    return stem, 0


def scan_product_image_folder(folder: str) -> dict[str, list[tuple[int, str]]]:
    """
    پوشه را می‌خواند و بر اساس کد کالای استخراج‌شده از نام فایل گروه‌بندی می‌کند.
    خروجی: {کد_کالا: [(شماره‌ترتیب, مسیر_فایل), ...]} — مرتب‌شده بر اساس شماره‌ترتیب.
    """
    groups: dict[str, list[tuple[int, str]]] = {}
    if not os.path.isdir(folder):
        return groups
    for fname in os.listdir(folder):
        fpath = os.path.join(folder, fname)
        if not os.path.isfile(fpath) or not is_supported_image(fpath):
            continue
        code, idx = parse_image_filename(fname)
        if not code:
            continue
        groups.setdefault(code, []).append((idx, fpath))
    for code in groups:
        groups[code].sort(key=lambda pair: pair[0])
    return groups


@dataclass
class ProductCodeLookup:
    """نگاشت کد اتوماتیک/دستی -> کد اصلی ERP (A_Code) — برای تطبیق نام فایل با کالا."""
    code_to_a_code: dict = field(default_factory=dict)

    def resolve(self, code: str) -> str | None:
        return self.code_to_a_code.get(str(code).strip())


def build_product_code_lookup(rows: list[tuple[str, str]]) -> ProductCodeLookup:
    """
    rows: لیست (A_Code, A_Code_C) از دیتابیس.
    هم کد اتوماتیک هم کد دستی هر دو به همان A_Code نگاشت می‌شوند.
    """
    lookup = ProductCodeLookup()
    for a_code, a_code_c in rows:
        a_code = str(a_code or "").strip()
        a_code_c = str(a_code_c or "").strip()
        if a_code:
            lookup.code_to_a_code[a_code] = a_code
        if a_code_c:
            lookup.code_to_a_code[a_code_c] = a_code
    return lookup


# ---------------------------------------------------------------------------
# امتیاز آمادگی انتشار محصول
# ---------------------------------------------------------------------------

@dataclass
class ReadinessCheck:
    label: str
    ok: bool
    missing_label: str = ""  # متن مخصوص وقتی این مورد ناقص است (واضح، نه مبهم)

    def __post_init__(self):
        if not self.missing_label:
            self.missing_label = self.label


@dataclass
class ReadinessResult:
    checks: list[ReadinessCheck] = field(default_factory=list)

    @property
    def score(self) -> int:
        if not self.checks:
            return 0
        passed = sum(1 for c in self.checks if c.ok)
        return round(passed / len(self.checks) * 100)


def product_readiness(product: dict) -> ReadinessResult:
    """
    چک‌لیست آمادگی انتشار — بر اساس داده‌های واقعی موجود در پیچا
    (بدون فیلدهایی مثل «متا سئو» که این نسخه اصلاً پیگیری‌شان نمی‌کند).
    """
    p = product or {}
    checks = [
        ReadinessCheck("عکس دارد", bool(p.get("has_image")), missing_label="بدون عکس"),
        ReadinessCheck("دسته‌بندی دارد", bool(p.get("has_category")), missing_label="بدون دسته‌بندی"),
        ReadinessCheck("قیمت دارد", float(p.get("price") or 0) > 0, missing_label="بدون قیمت"),
        ReadinessCheck("موجودی دارد", int(p.get("stock") or 0) > 0, missing_label="بدون موجودی"),
        ReadinessCheck("توضیحات دارد", bool(str(p.get("description") or "").strip()), missing_label="بدون توضیحات"),
        ReadinessCheck("با ووکامرس همگام شده", bool(p.get("synced_to_woo")), missing_label="با ووکامرس همگام نشده"),
    ]
    return ReadinessResult(checks=checks)


# ---------------------------------------------------------------------------
# حکاکی متن دلخواه (کد کالا/نام) + QR کد لینک محصول روی تصویر — جدا از
# واترمارک لوگو (که همه‌ی تصاویر رو یکسان می‌کنه)، این دوتا برای هر محصول
# فرق دارن.
# ---------------------------------------------------------------------------

def engrave_text_on_image(
    src_path: str,
    text: str,
    dst_path: str,
    *,
    font_size: int = 22,
    position: str = "bottom-center",
    text_color=(255, 255, 255),
    outline_color=(0, 0, 0),
    margin_percent: float = 0.03,
) -> "ConvertResult":
    """
    از فونت وزیر (که مخصوص همین قابلیت اضافه شده — جدا از IRANSans که برای
    بقیه‌ی برنامه استفاده می‌شه) با یه حاشیه‌ی تیره‌ی نازک دور حروف تا روی
    هر پس‌زمینه‌ای (روشن یا تیره) خوانا بمونه.
    """
    from sync_app.core.content_studio_helper import shape_persian_text
    from sync_app.core.sync_utils import resource_path
    from PIL import ImageFont, ImageDraw

    VAZIR_FONT_PATH = resource_path("Vazirmatn-Bold.ttf")

    result = ConvertResult(src_path=src_path)
    if not os.path.isfile(src_path):
        result.error = "فایل مبدا یافت نشد."
        return result
    text = str(text or "").strip()
    if not text:
        result.error = "متنی برای حک کردن داده نشده."
        return result

    try:
        result.size_before = os.path.getsize(src_path)
        with Image.open(src_path) as img:
            base = img.convert("RGBA")
            w, h = base.size
            draw = ImageDraw.Draw(base)
            try:
                font = ImageFont.truetype(VAZIR_FONT_PATH, font_size)
            except Exception:
                font = ImageFont.load_default()
            shaped = shape_persian_text(text)
            bbox = draw.textbbox((0, 0), shaped, font=font)
            text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            margin = int(min(w, h) * margin_percent)

            if position == "bottom-center":
                x, y = (w - text_w) // 2, h - text_h - margin
            elif position == "bottom-left":
                x, y = margin, h - text_h - margin
            elif position == "bottom-right":
                x, y = w - text_w - margin, h - text_h - margin
            elif position == "top-center":
                x, y = (w - text_w) // 2, margin
            else:
                x, y = (w - text_w) // 2, h - text_h - margin

            # حاشیه‌ی نازک تیره دور متن (برای خوانایی روی هر پس‌زمینه‌ای)
            for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
                draw.text((x + dx, y + dy), shaped, font=font, fill=outline_color)
            draw.text((x, y), shaped, font=font, fill=text_color)

            out_ext = os.path.splitext(dst_path)[1].lower()
            if out_ext in (".jpg", ".jpeg"):
                base.convert("RGB").save(dst_path, "JPEG", quality=92)
            else:
                base.save(dst_path)

        result.dst_path = dst_path
        result.size_after = os.path.getsize(dst_path)
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    return result


def add_qr_code_overlay(
    src_path: str,
    url: str,
    dst_path: str,
    *,
    size_ratio: float = 0.14,
    position: str = "bottom-left",
    margin_percent: float = 0.03,
) -> "ConvertResult":
    """
    یه QR کد از لینک محصول می‌سازه و گوشه‌ی تصویر می‌چسبونه — معمولاً کنار
    لوگوی واترمارک (که خودش گوشه‌ی دیگه‌ست) تا با هم تداخل نکنن.
    نیاز به کتابخانه‌ی qrcode داره — اگه نصب نبود، خطای واضح می‌ده.
    """
    result = ConvertResult(src_path=src_path)
    if not os.path.isfile(src_path):
        result.error = "فایل مبدا یافت نشد."
        return result
    url = str(url or "").strip()
    if not url:
        result.error = "لینکی برای ساخت QR کد داده نشده."
        return result

    try:
        import qrcode
    except ImportError:
        result.error = "کتابخانه‌ی qrcode نصب نیست."
        return result

    try:
        result.size_before = os.path.getsize(src_path)
        with Image.open(src_path) as img:
            base = img.convert("RGBA")
            w, h = base.size
            qr_size = int(min(w, h) * size_ratio)
            margin = int(min(w, h) * margin_percent)

            qr_img = qrcode.make(url).convert("RGBA").resize((qr_size, qr_size))
            # یه حاشیه‌ی سفید نازک دور QR تا روی عکس‌های تیره هم خوانا/اسکن‌پذیر بمونه
            pad = max(4, qr_size // 20)
            framed = Image.new("RGBA", (qr_size + pad * 2, qr_size + pad * 2), (255, 255, 255, 255))
            framed.paste(qr_img, (pad, pad))

            if position == "bottom-right":
                x, y = w - framed.width - margin, h - framed.height - margin
            elif position == "top-left":
                x, y = margin, margin
            elif position == "top-right":
                x, y = w - framed.width - margin, margin
            else:  # bottom-left (پیش‌فرض)
                x, y = margin, h - framed.height - margin

            base.alpha_composite(framed, (x, y))

            out_ext = os.path.splitext(dst_path)[1].lower()
            if out_ext in (".jpg", ".jpeg"):
                base.convert("RGB").save(dst_path, "JPEG", quality=92)
            else:
                base.save(dst_path)

        result.dst_path = dst_path
        result.size_after = os.path.getsize(dst_path)
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    return result
