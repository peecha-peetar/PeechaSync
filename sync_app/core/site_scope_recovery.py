"""بازیابیِ لینک‌هایِ تطبیقِ یک سایتِ قدیمی — برایِ وقتی تنظیماتِ برنامه
(آدرسِ سایت/ERP/پروفایل) به هر دلیلی عوض شده و scope keyِ فعلی دیگه به
پوشه‌یِ قدیمیِ حاویِ نگاشت‌هایِ واقعی (product_woo_map.json و مشابه)
اشاره نمی‌کنه — داده گم نشده، فقط در یک پوشه‌یِ «یتیم»ِ دیگه زیرِ
sites/ جا مونده. این ماژول همه‌یِ پوشه‌هایِ sites/<hash> رو لیست
می‌کنه (با مارکرِ scope.json اگه موجود باشه) و امکانِ «بازیابی به‌عنوانِ
سایتِ فعلی» (کپیِ فایل‌ها به پوشه‌یِ فعلی، با بکاپِ خودکارِ محتوایِ
فعلی) رو می‌ده — بدونِ نیازِ کاربر به گشتن دستی در AppData."""

from __future__ import annotations

import json
import os
import shutil
import time

from sync_app.core.sync_utils import app_dir, _site_scope_key

_SITE_SCOPE_FILES = (
    "product_woo_map.json",
    "product_woo_map_meta.json",
    "category_map.json",
    "category_images_map.json",
    "product_images_map.json",
    "variation_images_map.json",
    "attr_id_map.json",
    "sepidar_category_map.json",
    "sepidar_product_map.json",
    "sepidar_customer_map.json",
    "sepidar_order_map.json",
    "sku_as_site_variation.json",
    "force_simple_on_site.json",
    "product_category_override.json",
    "product_brand_override.json",
    "bulk_image_import_uploaded.json",
    "site_category_price_list.json",
    "site_brand_price_list.json",
)


def _sites_root() -> str:
    return os.path.join(app_dir(), "sites")


def _read_marker(scope_dir: str) -> dict:
    try:
        with open(os.path.join(scope_dir, "scope.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def describe_candidate(marker: dict) -> str:
    if not marker:
        return "نامشخص (این پوشه هنوز مارکر نداره — احتمالاً از قبلِ این نسخه مونده)"
    platform_fa = {"woocommerce": "ووکامرس", "prestashop": "پرستاشاپ"}.get(marker.get("platform") or "", marker.get("platform") or "؟")
    erp_fa = {"dejavu": "دژاوو/هلو", "sepidar": "سپیدار/دشت"}.get(marker.get("erp_family") or "", marker.get("erp_family") or "؟")
    url = marker.get("url") or "—"
    return f"{platform_fa} | {url} | ERP: {erp_fa}"


def list_site_scope_candidates(*, exclude_current: bool = True) -> list[dict]:
    """همه‌یِ پوشه‌هایِ sites/<hash>ِ غیرِخالی — مرتب‌شده بر اساسِ
    جدیدترین تغییر. خروجی: [{"hash", "dir", "file_count", "total_size",
    "newest_mtime", "marker", "label"}, ...]."""
    root = _sites_root()
    current = _site_scope_key() if exclude_current else None
    out: list[dict] = []
    try:
        entries = os.listdir(root)
    except OSError:
        return out

    for name in entries:
        scope_dir = os.path.join(root, name)
        if not os.path.isdir(scope_dir) or (exclude_current and name == current):
            continue
        files: list[str] = []
        total_size = 0
        newest_mtime = 0.0
        try:
            for fn in os.listdir(scope_dir):
                if fn == "scope.json" or fn.endswith((".pre_site_scope_backup", ".pre_erp_family_scope_backup")):
                    continue
                fp = os.path.join(scope_dir, fn)
                if not os.path.isfile(fp):
                    continue
                st = os.stat(fp)
                files.append(fn)
                total_size += st.st_size
                newest_mtime = max(newest_mtime, st.st_mtime)
        except OSError:
            continue
        if not files:
            continue
        marker = _read_marker(scope_dir)
        out.append({
            "hash": name,
            "dir": scope_dir,
            "file_count": len(files),
            "total_size": total_size,
            "newest_mtime": newest_mtime,
            "marker": marker,
            "label": describe_candidate(marker),
        })

    out.sort(key=lambda c: c["newest_mtime"], reverse=True)
    return out


def adopt_site_scope(candidate_dir: str) -> dict:
    """فایل‌هایِ پوشه‌یِ انتخاب‌شده رو رویِ پوشه‌یِ سایتِ فعلی کپی می‌کنه.
    اول یک بکاپِ کاملِ محتوایِ فعلیِ پوشه (اگه چیزی توش بود) می‌گیره —
    تا هیچ‌وقت دیتایِ فعلی بدونِ بکاپ رونویسی نشه. پوشه‌یِ مبدأ دست‌نخورده
    می‌مونه (copy نه move) — برایِ ایمنیِ بیشتر، چون ممکنه کاربر بعداً
    بخواد دوباره امتحان کنه یا مقایسه کنه."""
    current_dir = os.path.join(_sites_root(), _site_scope_key())
    os.makedirs(current_dir, exist_ok=True)

    existing = [
        fn for fn in os.listdir(current_dir)
        if os.path.isfile(os.path.join(current_dir, fn)) and fn != "scope.json"
    ]
    backup_dir = None
    if existing:
        backup_dir = os.path.join(_sites_root(), f"backup_before_adopt_{int(time.time())}")
        os.makedirs(backup_dir, exist_ok=True)
        for fn in existing:
            shutil.copy2(os.path.join(current_dir, fn), os.path.join(backup_dir, fn))

    copied: list[str] = []
    for fn in os.listdir(candidate_dir):
        if fn == "scope.json":
            continue
        fp = os.path.join(candidate_dir, fn)
        if os.path.isfile(fp):
            shutil.copy2(fp, os.path.join(current_dir, fn))
            copied.append(fn)

    return {"copied": copied, "backup_dir": backup_dir, "current_dir": current_dir}
