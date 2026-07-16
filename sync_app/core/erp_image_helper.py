"""استخراج تصویر از ERP (blob یا مسیر) برای آپلود به Woo."""

from __future__ import annotations

import os
import shutil

from sync_app.core.sync_utils import app_path


def _detect_ext(data: bytes) -> str:
    if not data:
        return ".jpg"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def resolve_erp_picture_path(picture_path: str, config: dict | None) -> str:
    """مسیر فایل تصویر روی دیسک — با ریشه تنظیمات یا مسیر مطلق."""
    raw = str(picture_path or "").strip()
    if not raw:
        return ""
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    root = str((config or {}).get("ERP_PICTURE_ROOT") or "").strip()
    if root:
        for candidate in (
            os.path.join(root, raw),
            os.path.join(root, os.path.basename(raw)),
        ):
            if os.path.isfile(candidate):
                return candidate
    if os.path.isfile(raw):
        return os.path.abspath(raw)
    return ""


def _transferred_images_filename(platform: str) -> str:
    # فایل جدا به‌ازای هر پلتفرم — چون «منتقل‌شده به ووکامرس» به این معنی
    # نیست که همون تصویر روی پرستاشاپ هم واقعاً آپلود شده (یا برعکس). قبلاً
    # یک فایل مشترک بود که باعث می‌شد بعد از سوییچ پلتفرم، انتقال تصویر
    # برای همیشه بی‌صدا رد بشه (چون hlo_id از سینک قبلیِ پلتفرم دیگه، از قبل
    # «منتقل‌شده» ثبت شده بود).
    return "transferred_erp_images_ps.json" if str(platform or "").strip().lower() == "prestashop" else "transferred_erp_images.json"


def load_transferred_image_ids(platform: str = "woocommerce") -> dict[str, list[int]]:
    """
    {کد_کالا: [شناسه‌های ردیف HLOpictures که قبلاً منتقل شدن]} — جدا برای هر پلتفرم.
    این فایل تنها منبع قابل‌اعتماد برای «این تصویر قبلاً رفته یا نه»ست —
    برخلاف شمارش ساده‌ی تعداد، اگه یکی از تصاویر قدیمی از ERP حذف بشه و
    یکی جدید اضافه بشه، تعداد کل ممکنه عوض نشه ولی این فایل درست تشخیص می‌ده.
    """
    import json
    from sync_app.core.sync_utils import app_path

    try:
        with open(app_path(_transferred_images_filename(platform)), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {
                    str(k).strip(): [int(i) for i in (v or []) if str(i).strip()]
                    for k, v in data.items()
                }
    except Exception:
        pass
    return {}


def save_transferred_image_ids(mapping: dict, platform: str = "woocommerce") -> None:
    import json
    from sync_app.core.sync_utils import app_path, log

    try:
        clean = {str(k).strip(): sorted({int(i) for i in (v or [])}) for k, v in (mapping or {}).items()}
        with open(app_path(_transferred_images_filename(platform)), "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        try:
            log.warning(f"⚠️ ذخیره {_transferred_images_filename(platform)}: {exc}")
        except Exception:
            pass


def mark_images_transferred(sku: str, hlo_ids: list[int], platform: str = "woocommerce") -> None:
    if not hlo_ids:
        return
    mapping = load_transferred_image_ids(platform)
    existing = set(mapping.get(str(sku).strip(), []))
    existing.update(int(i) for i in hlo_ids)
    mapping[str(sku).strip()] = sorted(existing)
    save_transferred_image_ids(mapping, platform)


def _stage_one(dst_dir: str, subdir: str, sku_key: str, name_hint: str, blob: bytes, path: str, config: dict | None) -> str:
    """یه تصویر (blob یا path) رو تو پوشه‌ی مقصد ذخیره می‌کنه، مسیر نسبی رو برمی‌گردونه (یا '' اگه چیزی نبود)."""
    blob = bytes(blob or b"")
    if len(blob) > 64:
        ext = _detect_ext(blob)
        dst_name = f"{name_hint}{ext}"
        dst_abs = os.path.join(dst_dir, dst_name)
        try:
            with open(dst_abs, "wb") as f:
                f.write(blob)
            return os.path.join(subdir, sku_key, dst_name).replace("\\", "/")
        except OSError:
            pass

    resolved = resolve_erp_picture_path(str(path or ""), config)
    if resolved:
        base = os.path.basename(resolved)
        dst_name = f"{name_hint}_{base}"
        dst_abs = os.path.join(dst_dir, dst_name)
        try:
            shutil.copy2(resolved, dst_abs)
            return os.path.join(subdir, sku_key, dst_name).replace("\\", "/")
        except OSError:
            pass
    return ""


def stage_erp_images(
    key: str,
    picture_blob: bytes | None,
    picture_path: str | None,
    config: dict | None,
    *,
    subdir: str = "product_images",
    extra_images: list[tuple[bytes, str]] | None = None,
) -> list[str]:
    """
    تصویر(های) ERP را در پوشه محلی ذخیره می‌کند.
    key = SKU محصول یا SKU واریانت
    extra_images: بقیه‌ی تصاویر همون کد کالا (از جدول HLOpictures) — یه
    محصول می‌تونه چند تصویر داشته باشه، همه‌شون باید منتقل بشن، نه فقط اولی.
    """
    sku_key = str(key or "").strip()
    if not sku_key:
        return []

    dst_dir = app_path(subdir, sku_key)
    os.makedirs(dst_dir, exist_ok=True)
    rel_paths: list[str] = []

    rel = _stage_one(dst_dir, subdir, sku_key, "erp_main", picture_blob, picture_path, config)
    if rel and rel not in rel_paths:
        rel_paths.append(rel)

    for idx, (extra_blob, extra_path) in enumerate(extra_images or []):
        rel = _stage_one(dst_dir, subdir, sku_key, f"erp_extra_{idx}", extra_blob, extra_path, config)
        if rel and rel not in rel_paths:
            rel_paths.append(rel)

    return rel_paths
