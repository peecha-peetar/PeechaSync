"""
Smart Publish — بهینه‌سازی خودکار/دستی تصویر محصول هنگام ارسال.
ترتیب روش پردازش تصویر ثابت و فنی-درست است (نه قابل جابه‌جایی آزاد):
Resize (با پروفایل) ← Remove Background ← Shadow ← Watermark ← Compress/WebP
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

from sync_app.core.media_center import (
    ConvertResult,
    apply_watermark,
    compress_image,
    convert_to_webp,
    _fit_to_size_with_padding,
)
from PIL import Image

WATERMARK_PATH_KEY = "SP_WATERMARK_PATH"
WATERMARK_OPACITY_KEY = "SP_WATERMARK_OPACITY"
WATERMARK_SCALE_KEY = "SP_WATERMARK_SCALE"
WATERMARK_POSITION_KEY = "SP_WATERMARK_POSITION"
WATERMARK_MARGIN_KEY = "SP_WATERMARK_MARGIN"
PIPELINES_KEY = "SP_PIPELINES"
AUTO_RUN_KEY = "SP_AUTO_RUN_ON_SEND"
AUTO_PIPELINE_KEY = "SP_AUTO_PIPELINE_NAME"
AI_STUDIO_BG_COLOR_KEY = "SP_AI_STUDIO_BG_COLOR"
AI_STUDIO_BG_IMAGE_KEY = "SP_AI_STUDIO_BG_IMAGE"

STEP_LABELS = {
    "resize": "Resize (با پروفایل انتخابی)",
    "watermark": "Watermark",
    "text_engrave": "حک متن (کد/نام کالا)",
    "qr_code": "QR کد لینک محصول",
    "compress": "Compress",
    "webp": "WebP",
}
STEP_ORDER = ["resize", "watermark", "text_engrave", "qr_code", "compress", "webp"]

TEXT_ENGRAVE_SOURCE_KEY = "SP_TEXT_ENGRAVE_SOURCE"
TEXT_ENGRAVE_FONT_SIZE_KEY = "SP_TEXT_ENGRAVE_FONT_SIZE"
TEXT_ENGRAVE_POSITION_KEY = "SP_TEXT_ENGRAVE_POSITION"
QR_CODE_POSITION_KEY = "SP_QR_CODE_POSITION"

TEXT_SOURCE_LABELS = {
    "auto_code": "کد کالا اتوماتیک",
    "manual_code": "کد کالا دستی",
    "name": "نام کالا",
}


def load_text_engrave_settings(config: dict) -> dict:
    cfg = config or {}
    return {
        "source": str(cfg.get(TEXT_ENGRAVE_SOURCE_KEY) or "auto_code"),
        "font_size": int(cfg.get(TEXT_ENGRAVE_FONT_SIZE_KEY, 22)),
        "position": str(cfg.get(TEXT_ENGRAVE_POSITION_KEY) or "bottom-center"),
    }


def load_qr_code_settings(config: dict) -> dict:
    cfg = config or {}
    return {
        "position": str(cfg.get(QR_CODE_POSITION_KEY) or "bottom-left"),
    }


def resolve_engrave_text(product_info: dict, source: str) -> str:
    """بر اساس نوع انتخاب‌شده، متن واقعی که باید حک بشه رو برمی‌گردونه."""
    info = product_info or {}
    if source == "manual_code":
        return str(info.get("a_code_c") or info.get("a_code") or "").strip()
    if source == "name":
        return str(info.get("name") or "").strip()
    return str(info.get("a_code") or "").strip()  # auto_code (پیش‌فرض)

POSITION_LABELS = {
    "bottom-right": "پایین راست",
    "bottom-left": "پایین چپ",
    "top-right": "بالا راست",
    "top-left": "بالا چپ",
    "center": "وسط",
}


WATERMARK_PROFILES_KEY = "WATERMARK_PROFILES"
WATERMARK_ACTIVE_PROFILE_KEY = "WATERMARK_ACTIVE_PROFILE"
DEFAULT_WATERMARK_PROFILE_NAME = "پیش‌فرض"


def _default_watermark_profile_from_legacy(cfg: dict) -> dict:
    """قبل از سیستم پروفایل، فقط یه واترمارک تکی داشتیم — همون رو به‌عنوان
    اولین پروفایل («پیش‌فرض») نگه می‌داریم تا کاربرهای قدیمی چیزی از دست ندن."""
    return {
        "path": str(cfg.get(WATERMARK_PATH_KEY) or "").strip(),
        "opacity": float(cfg.get(WATERMARK_OPACITY_KEY, 0.55)),
        "scale": float(cfg.get(WATERMARK_SCALE_KEY, 0.18)),
        "position": str(cfg.get(WATERMARK_POSITION_KEY, "bottom-right")),
        "margin": float(cfg.get(WATERMARK_MARGIN_KEY, 0.03)),
    }


def load_watermark_profiles(config: dict) -> dict:
    """همه‌ی پروفایل‌های ذخیره‌شده‌ی واترمارک. اگه هیچ‌کدوم نباشه، تنظیم
    قدیمیِ تکی رو به‌عنوان پروفایل «پیش‌فرض» برمی‌گردونه (نه ذخیره — فقط
    نمایش — تا وقتی کاربر واقعاً ذخیره کنه، فایل واقعی تغییر نکنه)."""
    cfg = config or {}
    profiles = cfg.get(WATERMARK_PROFILES_KEY)
    if isinstance(profiles, dict) and profiles:
        return profiles
    return {DEFAULT_WATERMARK_PROFILE_NAME: _default_watermark_profile_from_legacy(cfg)}


def save_watermark_profile(name: str, settings: dict) -> None:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    name = (name or "").strip()
    if not name:
        return
    cfg = load_secure_config(None) or {}
    profiles = dict(cfg.get(WATERMARK_PROFILES_KEY) or {})
    if not profiles:
        # اولین‌باره که پروفایل واقعی ذخیره می‌شه — تنظیم قدیمی رو هم به‌عنوان
        # «پیش‌فرض» منتقل می‌کنیم تا گم نشه.
        profiles[DEFAULT_WATERMARK_PROFILE_NAME] = _default_watermark_profile_from_legacy(cfg)
    profiles[name] = dict(settings)
    cfg[WATERMARK_PROFILES_KEY] = profiles
    if not cfg.get(WATERMARK_ACTIVE_PROFILE_KEY):
        cfg[WATERMARK_ACTIVE_PROFILE_KEY] = name
    save_secure_config(cfg)


def delete_watermark_profile(name: str) -> None:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    profiles = dict(cfg.get(WATERMARK_PROFILES_KEY) or {})
    profiles.pop(name, None)
    cfg[WATERMARK_PROFILES_KEY] = profiles
    if cfg.get(WATERMARK_ACTIVE_PROFILE_KEY) == name:
        cfg[WATERMARK_ACTIVE_PROFILE_KEY] = next(iter(profiles), "")
    save_secure_config(cfg)


def load_watermark_settings(config: dict, profile_name: str | None = None) -> dict:
    """
    تنظیمات یک پروفایل مشخص از واترمارک رو برمی‌گردونه. اگه profile_name
    داده نشه، از پروفایل «فعال» (یا اولین پروفایل موجود) استفاده می‌شه —
    برای سازگاری کامل با کدهای قدیمی که فقط load_watermark_settings(config)
    صدا می‌زنن.
    """
    cfg = config or {}
    profiles = load_watermark_profiles(cfg)
    if not profile_name:
        profile_name = str(cfg.get(WATERMARK_ACTIVE_PROFILE_KEY) or "").strip()
    chosen = profiles.get(profile_name) if profile_name else None
    if not chosen:
        chosen = next(iter(profiles.values()), {})
    return {
        "path": str(chosen.get("path") or "").strip(),
        "opacity": float(chosen.get("opacity", 0.55)),
        "scale": float(chosen.get("scale", 0.18)),
        "position": str(chosen.get("position", "bottom-right")),
        "margin": float(chosen.get("margin", 0.03)),
    }


def load_ai_studio_settings(config: dict) -> dict:
    cfg = config or {}
    color_hex = str(cfg.get(AI_STUDIO_BG_COLOR_KEY) or "#FFFFFF").lstrip("#")
    try:
        bg_color = tuple(int(color_hex[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        bg_color = (255, 255, 255)
    return {
        "bg_color": bg_color,
        "bg_image_path": str(cfg.get(AI_STUDIO_BG_IMAGE_KEY) or "").strip() or None,
    }


def load_pipelines(config: dict) -> dict:
    raw = (config or {}).get(PIPELINES_KEY)
    return raw if isinstance(raw, dict) else {}


def pipeline_summary(steps: list[str]) -> str:
    return " ← ".join(STEP_LABELS.get(s, s) for s in steps)


@dataclass
class PipelineResult:
    ok: bool = False
    dst_path: str = ""
    error: str = ""
    size_before: int = 0
    size_after: int = 0


def run_pipeline(
    src_path: str,
    steps: list[str],
    *,
    out_dir: str,
    profile: dict | None = None,
    watermark: dict | None = None,
    ai_studio: dict | None = None,
    webp_quality: int = 85,
    product_info: dict | None = None,
    text_engrave: dict | None = None,
    qr_code: dict | None = None,
) -> PipelineResult:
    """
    اجرای روش پردازش تصویر روی یک تصویر — ترتیب همیشه:
    Resize ← Watermark ← حک متن ← QR کد ← Compress/WebP
    (بدون توجه به ترتیب آیتم‌های لیست steps، چون این ترتیب همیشه فنی-درسته).

    فایل‌هایِ میانیِ هر مرحله رو تویِ یه پوشه‌ی موقتِ سیستمی می‌سازه (نه
    داخلِ out_dir) و در پایان فقط تصویرِ نهاییِ آخرین مرحله رو به out_dir
    منتقل می‌کنه — تا به‌ازایِ هر عکس فقط یک فایل رویِ دیسک بمونه، نه یک
    فایل به‌ازایِ هر مرحله.

    product_info (فقط برای مراحل «حک متن»/«QR کد» لازمه): دیکشنری شامل
    a_code (کد اتوماتیک)، a_code_c (کد دستی)، name (نام کالا)، product_url
    (لینک محصول در سایت — برای QR).
    """
    result = PipelineResult()
    if not os.path.isfile(src_path):
        result.error = "فایل مبدا یافت نشد."
        return result

    work_dir = tempfile.mkdtemp(prefix="peecha_sp_")
    try:
        result.size_before = os.path.getsize(src_path)
        current = src_path
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(src_path))[0]

        if "resize" in steps:
            if not profile:
                raise RuntimeError("برای مرحله‌ی Resize باید یک پروفایل انتخاب شود.")
            with Image.open(current) as img:
                if img.mode in ("P", "LA"):
                    img = img.convert("RGBA")
                elif img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                fitted = _fit_to_size_with_padding(
                    img, profile["w"], profile["h"], margin_percent=int(profile.get("margin", 0))
                )
                resized_path = os.path.join(work_dir, f"{stem}_resized.png")
                fitted.save(resized_path)
                current = resized_path

        if "watermark" in steps:
            if not watermark or not watermark.get("path"):
                raise RuntimeError("برای مرحله‌ی Watermark باید فایل لوگو در تنظیمات انتخاب شود.")
            wm_dst = os.path.join(work_dir, f"{stem}_wm.png")
            r = apply_watermark(
                current, watermark["path"], wm_dst,
                opacity=watermark.get("opacity", 0.55),
                scale=watermark.get("scale", 0.18),
                margin_percent=watermark.get("margin", 0.03),
                position=watermark.get("position", "bottom-right"),
            )
            if not r.ok:
                raise RuntimeError(f"واترمارک ناموفق بود: {r.error}")
            current = r.dst_path

        if "text_engrave" in steps:
            from sync_app.core.media_center import engrave_text_on_image

            text_cfg = text_engrave or load_text_engrave_settings({})
            text_to_engrave = resolve_engrave_text(product_info or {}, text_cfg.get("source", "auto_code"))
            if text_to_engrave:
                dst = os.path.join(work_dir, f"{stem}_txt.png")
                r = engrave_text_on_image(
                    current, text_to_engrave, dst,
                    font_size=int(text_cfg.get("font_size", 22)),
                    position=text_cfg.get("position", "bottom-center"),
                )
                if not r.ok:
                    raise RuntimeError(f"حک متن ناموفق بود: {r.error}")
                current = r.dst_path

        if "qr_code" in steps:
            from sync_app.core.media_center import add_qr_code_overlay

            product_url = str((product_info or {}).get("product_url") or "").strip()
            if product_url:
                qr_cfg = qr_code or load_qr_code_settings({})
                dst = os.path.join(work_dir, f"{stem}_qr.png")
                r = add_qr_code_overlay(
                    current, product_url, dst,
                    position=qr_cfg.get("position", "bottom-left"),
                )
                if not r.ok:
                    raise RuntimeError(f"افزودن QR کد ناموفق بود: {r.error}")
                current = r.dst_path

        do_webp = "webp" in steps
        do_compress = "compress" in steps
        if do_webp:
            dst = os.path.join(work_dir, f"{stem}_final.webp")
            r = convert_to_webp(current, dst, quality=webp_quality)
            if not r.ok:
                raise RuntimeError(f"تبدیل WebP ناموفق بود: {r.error}")
            current = r.dst_path
        elif do_compress:
            dst = os.path.join(work_dir, f"{stem}_final{os.path.splitext(current)[1]}")
            r = compress_image(current, dst)
            if not r.ok:
                raise RuntimeError(f"فشرده‌سازی ناموفق بود: {r.error}")
            current = r.dst_path

        # فقط همینِ آخری (نتیجه‌ی آخرین مرحله‌ای که واقعاً اجرا شده) به
        # out_dir واقعی منتقل می‌شه — بقیه‌ی فایل‌هایِ میانی با حذفِ
        # work_dir (در finally) از بین می‌رن.
        final_name = f"{stem}_final{os.path.splitext(current)[1]}"
        final_dst = os.path.join(out_dir, final_name)
        if os.path.abspath(current) == os.path.abspath(src_path):
            shutil.copy2(current, final_dst)
        else:
            shutil.move(current, final_dst)
        current = final_dst

        result.dst_path = current
        result.size_after = os.path.getsize(current)
        result.ok = True
    except Exception as exc:
        result.error = str(exc)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return result


def apply_default_pipeline(
    abs_path: str,
    config: dict,
    *,
    code: str,
    name: str = "",
    product_url: str = "",
) -> str:
    """اگه یه «روشِ پردازشِ تصویر» به‌عنوانِ پیش‌فرضِ اجرایِ خودکار (تبِ
    تنظیماتِ Smart Publish → AUTO_RUN_KEY/AUTO_PIPELINE_KEY) انتخاب شده
    باشه، تصویر رو از همون پایپ‌لاین رد می‌کنه و مسیرِ فایلِ نهایی
    (پردازش‌شده) رو برمی‌گردونه؛ وگرنه — یا اگه پردازش با خطا مواجه بشه —
    همون مسیرِ اصلی/خام رو بدونِ تغییر برمی‌گردونه.

    این تنها نقطه‌ی مشترکیه که همه‌ی روش‌هایِ انتقالِ تصویر (سینکِ کاملِ
    محصولات از دیتابیس، ارسالِ دستی/گروهیِ تصویرِ محصول از تبِ محصولات،
    ارسالِ تصویرِ دسته‌بندی، Media Center) باید صداش بزنن — تا فرقی نکنه
    تصویر از کجا/کدوم مسیر داره می‌ره، همیشه از یه پایپ‌لاینِ یکسان رد بشه."""
    if not os.path.isfile(abs_path):
        return abs_path
    cfg = config or {}
    if not bool(cfg.get(AUTO_RUN_KEY, False)):
        return abs_path
    pipeline_name = cfg.get(AUTO_PIPELINE_KEY)
    if not pipeline_name:
        return abs_path
    pipeline = load_pipelines(cfg).get(pipeline_name)
    if not pipeline:
        return abs_path
    steps = pipeline.get("steps") or []
    if not steps:
        return abs_path
    try:
        from sync_app.core.media_center import load_image_profiles

        profiles = load_image_profiles(cfg)
        profile_name = pipeline.get("profile")
        # همون پوشه‌ی خودِ تصویرِ خام (product_images/) — بدونِ زیرپوشه‌ی
        # جداگانه؛ run_pipeline خودش فایل‌هایِ میانی رو تویِ یه پوشه‌ی
        # موقتِ سیستمی می‌سازه و پاک می‌کنه، فقط نتیجه‌ی نهایی این‌جا می‌شینه.
        out_dir = os.path.dirname(abs_path)
        result = run_pipeline(
            abs_path, steps, out_dir=out_dir,
            profile=profiles.get(profile_name) if profile_name else None,
            watermark=load_watermark_settings(cfg),
            ai_studio=load_ai_studio_settings(cfg),
            text_engrave=load_text_engrave_settings(cfg),
            qr_code=load_qr_code_settings(cfg),
            product_info={"a_code": code, "a_code_c": code, "name": name or code, "product_url": product_url},
        )
        if result.ok and result.dst_path and os.path.isfile(result.dst_path):
            from sync_app.core.sync_utils import log

            log.info(
                f"🖼️ روشِ پردازشِ تصویرِ «{pipeline_name}» ({', '.join(steps)}) رویِ {code} اجرا شد."
            )
            return result.dst_path
        # run_pipeline خودش استثنا پرت نمی‌کنه — شکستِ هر مرحله رو تویِ
        # result.error برمی‌گردونه. قبلاً این حالت کاملاً بی‌صدا رد می‌شد
        # (نه لاگ، نه هیچ نشونه‌ای) و تصویرِ خام آپلود می‌شد — یعنی مثلاً
        # یک واترمارکِ ناموفق هیچ‌وقت به چشمِ کسی نمی‌رسید.
        from sync_app.core.sync_utils import log

        log.warning(
            f"⚠️ روشِ پردازشِ تصویر رویِ {code} ناموفق بود ({result.error or 'نامشخص'}) — "
            "تصویرِ خام آپلود می‌شه."
        )
    except Exception as exc:
        from sync_app.core.sync_utils import log

        log.warning(f"⚠️ روشِ پردازشِ تصویر رویِ {code} اجرا نشد، تصویرِ خام آپلود می‌شه: {exc}")
    return abs_path
