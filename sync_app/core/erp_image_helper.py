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
    from sync_app.core.sync_utils import site_scoped_path

    try:
        with open(site_scoped_path(_transferred_images_filename(platform)), "r", encoding="utf-8") as f:
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
    from sync_app.core.sync_utils import site_scoped_path, log

    try:
        clean = {str(k).strip(): sorted({int(i) for i in (v or [])}) for k, v in (mapping or {}).items()}
        with open(site_scoped_path(_transferred_images_filename(platform)), "w", encoding="utf-8") as f:
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


def forget_transferred_images(sku: str, platform: str = "woocommerce") -> None:
    """سابقه‌یِ «تصاویرِ این کالا قبلاً منتقل شده» به محصولِ *قبلیِ* سایت
    مربوط بود — وقتی اون محصول حذف/جایگزین می‌شه (یا شناسه‌اش دیگه مالِ این
    کالا نیست)، باید پاک بشه، وگرنه محصولِ تازه برایِ همیشه بدونِ عکس می‌مونه."""
    key = str(sku or "").strip()
    if not key:
        return
    mapping = load_transferred_image_ids(platform)
    if key in mapping:
        mapping.pop(key, None)
        save_transferred_image_ids(mapping, platform)


def product_image_filename(code: str, index: int, ext: str) -> str:
    """عکس اول: کد کالا. عکس‌های بعدی: کد$۱ و کد$۲."""
    safe = "".join(ch for ch in str(code or "").strip() if ch not in '\\/:*?"<>|$').strip() or "product"
    ext = str(ext or ".jpg")
    if not ext.startswith("."):
        ext = f".{ext}"
    ext = ext.lower()
    if int(index or 0) <= 0:
        return f"{safe}{ext}"
    return f"{safe}${int(index)}{ext}"


def next_image_index(code: str) -> int:
    """اولین شمارهٔ خالی. صفر یعنی خودِ کد کالا، بعد از آن $۱ و $۲."""
    folder = app_path("product_images")
    if not os.path.isdir(folder):
        return 0
    target = str(code or "").strip().casefold()
    found: set[int] = set()
    for name in os.listdir(folder):
        stem, _ext = os.path.splitext(name)
        if "$" in stem:
            code_part, _, idx_part = stem.partition("$")
            if code_part.strip().casefold() == target and idx_part.strip().isdigit():
                found.add(int(idx_part.strip()))
        elif stem.strip().casefold() == target:
            found.add(0)
    if 0 not in found:
        return 0
    return max(found) + 1 if found else 0


def discard_legacy_image_files(code: str) -> None:
    """فایل‌های میانی و اسم‌های قدیمیِ همین کالا را از پوشهٔ تصاویر پاک می‌کند."""
    folder = app_path("product_images")
    prefix = str(code or "").strip()
    if not prefix or not os.path.isdir(folder):
        return
    needle = prefix.casefold() + "_"
    tokens = ("_hlo", "_erp_main", "_erp_extra", "_final", "_resized", "_wm", "_txt", "_qr")
    for name in os.listdir(folder):
        lower = name.casefold()
        if not lower.startswith(needle):
            continue
        if not any(token in lower for token in tokens):
            continue
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def publish_product_image(
    src_path: str,
    config: dict | None,
    code: str,
    index: int,
    product_url: str = "",
    *,
    run_pipeline: bool = True,
) -> str:
    """فقط فایل نهایی را با کد کالا نگه می‌دارد و فایل میانی را پاک می‌کند."""
    if not src_path or not os.path.isfile(src_path):
        return src_path
    folder = app_path("product_images")
    os.makedirs(folder, exist_ok=True)
    src_abs = os.path.abspath(src_path)
    src_ext = os.path.splitext(src_abs)[1] or ".jpg"
    raw_dest = os.path.join(folder, product_image_filename(code, index, src_ext))
    generated_sidecar = "_final" in os.path.basename(src_abs).lower()
    if src_abs != os.path.abspath(raw_dest):
        if os.path.isfile(raw_dest):
            os.remove(raw_dest)
        if src_abs.startswith(os.path.abspath(folder) + os.sep):
            shutil.move(src_abs, raw_dest)
        else:
            shutil.copy2(src_abs, raw_dest)
            if generated_sidecar and os.path.isfile(src_abs):
                os.remove(src_abs)
    else:
        raw_dest = src_abs

    processed = raw_dest
    if run_pipeline:
        from sync_app.core.smart_publish import apply_default_pipeline

        processed = apply_default_pipeline(raw_dest, config or {}, code=code, product_url=product_url)

    final_ext = os.path.splitext(processed)[1] or src_ext
    final_dest = os.path.join(folder, product_image_filename(code, index, final_ext))
    if os.path.abspath(processed) != os.path.abspath(final_dest):
        if os.path.isfile(final_dest):
            os.remove(final_dest)
        shutil.move(processed, final_dest)
    if os.path.abspath(raw_dest) != os.path.abspath(final_dest) and os.path.isfile(raw_dest):
        os.remove(raw_dest)
    discard_legacy_image_files(code)
    return final_dest


def _stage_one(dst_dir: str, subdir: str, sku_key: str, name_hint: str, blob: bytes, path: str, config: dict | None) -> str:
    """یه تصویر (blob یا path) رو تو پوشه‌ی مقصدِ مشترک (بدون زیرپوشه‌ی
    جداگانه به‌ازایِ هر SKU) ذخیره می‌کنه — نامِ فایل با sku_key شروع
    می‌شه تا بینِ محصولاتِ مختلف تداخل نداشته باشه. مسیر نسبی رو
    برمی‌گردونه (یا '' اگه چیزی نبود)."""
    blob = bytes(blob or b"")
    if len(blob) > 64:
        ext = _detect_ext(blob)
        dst_name = f"{sku_key}_{name_hint}{ext}"
        dst_abs = os.path.join(dst_dir, dst_name)
        try:
            with open(dst_abs, "wb") as f:
                f.write(blob)
            return os.path.join(subdir, dst_name).replace("\\", "/")
        except OSError:
            pass

    resolved = resolve_erp_picture_path(str(path or ""), config)
    if resolved:
        base = os.path.basename(resolved)
        dst_name = f"{sku_key}_{name_hint}_{base}"
        dst_abs = os.path.join(dst_dir, dst_name)
        try:
            shutil.copy2(resolved, dst_abs)
            return os.path.join(subdir, dst_name).replace("\\", "/")
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
    تصویر(های) ERP را در یک پوشه‌ی مشترک (بدون زیرپوشه‌ی جداگانه به‌ازایِ
    هر تصویر/SKU) ذخیره می‌کند.
    key = SKU محصول یا SKU واریانت
    extra_images: بقیه‌ی تصاویر همون کد کالا (از جدول HLOpictures) — یه
    محصول می‌تونه چند تصویر داشته باشه، همه‌شون باید منتقل بشن، نه فقط اولی.
    """
    sku_key = str(key or "").strip()
    if not sku_key:
        return []

    dst_dir = app_path(subdir)
    os.makedirs(dst_dir, exist_ok=True)
    rel_paths: list[str] = []

    rel = _stage_named(dst_dir, subdir, sku_key, 0, picture_blob, picture_path, config)
    if rel and rel not in rel_paths:
        rel_paths.append(rel)

    for idx, (extra_blob, extra_path) in enumerate(extra_images or [], start=1):
        rel = _stage_named(dst_dir, subdir, sku_key, idx, extra_blob, extra_path, config)
        if rel and rel not in rel_paths:
            rel_paths.append(rel)

    if rel_paths:
        discard_legacy_image_files(sku_key)
    return rel_paths


def _stage_named(dst_dir: str, subdir: str, code: str, index: int, blob: bytes, path: str, config: dict | None) -> str:
    """ذخیره با نام کد کالا یا کد$شماره. مسیر نسبی را برمی‌گرداند."""
    blob = bytes(blob or b"")
    if len(blob) > 64:
        dst_name = product_image_filename(code, index, _detect_ext(blob))
        dst_abs = os.path.join(dst_dir, dst_name)
        try:
            with open(dst_abs, "wb") as f:
                f.write(blob)
            return os.path.join(subdir, dst_name).replace("\\", "/")
        except OSError:
            pass

    resolved = resolve_erp_picture_path(str(path or ""), config)
    if resolved:
        ext = os.path.splitext(resolved)[1] or ".jpg"
        dst_name = product_image_filename(code, index, ext)
        dst_abs = os.path.join(dst_dir, dst_name)
        try:
            shutil.copy2(resolved, dst_abs)
            return os.path.join(subdir, dst_name).replace("\\", "/")
        except OSError:
            pass
    return ""
