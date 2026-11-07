"""«ریستِ لینک‌هایِ این سایت» — برایِ وقتی خودِ سایت ریست/از نو نصب شده.

بعد از ریستِ وردپرس/پرستاشاپ، همه‌یِ شناسه‌هایِ ذخیره‌شده (محصول، دسته‌بندی،
ویژگی، واریانت، دستهٔ دستیِ محصول، لیستِ قیمتِ دسته‌ها و ...) به چیزهایِ دیگه‌ای
اشاره می‌کنن. سینک حالا قبل از هر نوشتن هویت رو چک می‌کنه، ولی برایِ یک شروعِ
کاملاً تمیز، این ابزار همه‌یِ این فایل‌ها رو (فقط برایِ سایتِ فعلی) به یک پوشه‌یِ
بکاپ منتقل می‌کنه — هیچ‌چیزی پاک نمی‌شه و قابلِ‌برگشته.

عمداً دست نمی‌خوره: دفترِ سفارش‌هایِ واردشده و نگاشتِ سفارش‌ها (وگرنه سفارش‌هایِ
قدیمی که هنوز رویِ سایت هستن دوباره فاکتور می‌شدن)، تصاویرِ دستیِ محلی،
لینکِ دستیِ مقادیرِ ویژگی (بر اساسِ نام‌اند، نه شناسه) و تاریخچهٔ همگام‌سازی.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import time

RESET_FILES = (
    "product_woo_map.json",
    "product_woo_map.platform",
    "product_woo_map_meta.json",
    "category_map.json",
    "attr_id_map.json",
    "sepidar_category_map.json",
    "sepidar_product_map.json",
    "sepidar_customer_map.json",
    "sku_as_site_variation.json",
    "force_simple_on_site.json",
    "product_category_override.json",
    "product_brand_override.json",
    "site_category_price_list.json",
    "site_brand_price_list.json",
    "bulk_image_import_uploaded.json",
    "transferred_erp_images.json",
    "transferred_erp_images_ps.json",
    "uploaded_media_ledger.json",
)
RESET_PATTERNS = ("sync_hash_cache_*.json",)
_CONFIG_CACHE_KEYS = ("WC_ATTR_CACHE", "WC_PRODUCT_ATTR_FP")


def current_site_dir() -> str:
    from sync_app.core.sync_utils import _site_scope_key, app_dir

    return os.path.join(app_dir(), "sites", _site_scope_key())


def list_resettable_files() -> list[str]:
    base = current_site_dir()
    try:
        names = os.listdir(base)
    except OSError:
        return []
    out = []
    for name in sorted(names):
        if not os.path.isfile(os.path.join(base, name)):
            continue
        if name in RESET_FILES or any(fnmatch.fnmatch(name, pat) for pat in RESET_PATTERNS):
            out.append(name)
    return out


def reset_site_links() -> dict:
    """فایل‌هایِ لینکِ سایتِ فعلی رو به sites/<scope>/_reset_backup_<زمان>/
    منتقل می‌کنه و کشِ ویژگی‌هایِ سایت رو از تنظیمات پاک می‌کنه.
    خروجی: {"moved": [...نام‌ها], "backup_dir": مسیر یا ""}."""
    base = current_site_dir()
    names = list_resettable_files()
    backup_dir = ""
    moved: list[str] = []
    if names:
        backup_dir = os.path.join(base, f"_reset_backup_{time.strftime('%Y%m%d-%H%M%S')}")
        os.makedirs(backup_dir, exist_ok=True)
        for name in names:
            shutil.move(os.path.join(base, name), os.path.join(backup_dir, name))
            moved.append(name)

    try:
        from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

        cfg = load_secure_config(None) or {}
        if any(key in cfg for key in _CONFIG_CACHE_KEYS):
            for key in _CONFIG_CACHE_KEYS:
                cfg.pop(key, None)
            save_secure_config(cfg)
    except Exception:
        pass

    try:
        from sync_app.core.sync_utils import log

        log.warning(
            f"🔄 لینک‌هایِ این سایت ریست شد — {len(moved)} فایل به بکاپ منتقل شد"
            + (f": {backup_dir}" if backup_dir else ".")
        )
    except Exception:
        pass
    return {"moved": moved, "backup_dir": backup_dir}
