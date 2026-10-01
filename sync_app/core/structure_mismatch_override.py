"""تطبیقِ دستی برایِ وقتی ساختارِ محصول در دیتابیس (ERP) با ساختارِ همون
محصول رویِ سایت یکی نیست — دو حالت:

۱) سایت محصولِ متغیر داره (چند واریانت)، ولی در دیتابیس هر واریانت یک
   کالایِ ساده‌یِ مستقل تعریف شده (SKU_AS_SITE_VARIATION): این‌جا باید
   بگیم فلان SKUِ ساده در واقع واریانتِ فلان محصول/فلان واریانتِ سایته —
   نه یک محصولِ مستقل. با این override، به‌جایِ ساختن/به‌روزرسانیِ یک
   محصولِ جدا، فقط قیمت/موجودیِ همون واریانتِ سایت آپدیت می‌شه.

۲) دیتابیس محصول رو متغیر (چند زیرواریانت) می‌بینه، ولی رویِ سایت این
   یک محصولِ ساده‌ست (FORCE_SIMPLE_ON_SITE): این‌جا باید بگیم کدوم
   زیرواریانتِ ERP به‌عنوانِ منبعِ قیمت/موجودیِ اون محصولِ سادهٔ سایت
   استفاده بشه — بقیه‌ی زیرواریانت‌ها نادیده گرفته می‌شن و محصول به‌عنوانِ
   محصولِ متغیر ساخته/سینک نمی‌شه.

هر دو فایل site-scoped ذخیره می‌شن (نه فقط per-profile) — دقیقاً مثلِ
product_category_override.py — چون idِ محصول/واریانتِ سایت مالِ یک سایتِ
مشخصه. کش با mtime معتبرسنجی می‌شه (مثلِ product_brand_override.py) —
چون در سینکِ کاملِ چند هزار محصولی این فایل به‌ازایِ هر محصول خونده می‌شه."""

from __future__ import annotations

import json
import os

SITE_VARIATION_TARGET_FILE = "sku_as_site_variation.json"  # {erp_sku: {"parent_product_id": int, "variation_id": int, "label": str, "erp_label": str}}
FORCE_SIMPLE_SOURCE_FILE = "force_simple_on_site.json"  # {erp_parent_sku: {"source_variation_sku": str, "erp_label": str, "site_label": str}}


def _path(filename: str) -> str:
    from sync_app.core.sync_utils import site_scoped_path

    return site_scoped_path(filename)


class _CachedJsonTable:
    """کش با اعتبارسنجیِ mtime — بینِ صداهایِ پی‌درپی بازخوانیِ اضافه‌یِ
    فایل رو حذف می‌کنه، ولی هر تغییرِ رویِ دیسک (چه از همین برنامه چه
    بیرونی) بلافاصله دیده می‌شه. الگو دقیقاً هم‌شکلِ product_brand_override.py."""

    def __init__(self, filename: str):
        self._filename = filename
        self._cache_path: str | None = None
        self._cache_mtime: float | None = None
        self._cache_data: dict | None = None

    def load(self) -> dict:
        path = _path(self._filename)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if self._cache_data is not None and self._cache_path == path and self._cache_mtime == mtime:
            return self._cache_data

        data: dict = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
        except Exception:
            pass
        self._cache_path, self._cache_mtime, self._cache_data = path, mtime, data
        return data

    def save(self, data: dict) -> None:
        path = _path(self._filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = None
            self._cache_path, self._cache_mtime, self._cache_data = path, mtime, data
        except Exception as exc:
            try:
                from sync_app.core.sync_utils import log

                log.warning(f"⚠️ ذخیره {self._filename}: {exc}")
            except Exception:
                pass


_site_variation_table = _CachedJsonTable(SITE_VARIATION_TARGET_FILE)
_force_simple_table = _CachedJsonTable(FORCE_SIMPLE_SOURCE_FILE)


# ----------------------------------------------------------------------
# حالتِ ۱: این SKUِ ساده در واقع واریانتِ یک محصولِ متغیرِ سایته
# ----------------------------------------------------------------------
def list_site_variation_targets() -> dict[str, dict]:
    return dict(_site_variation_table.load())


def get_site_variation_target(sku: str) -> dict | None:
    sku = str(sku or "").strip()
    if not sku:
        return None
    entry = _site_variation_table.load().get(sku)
    if not isinstance(entry, dict):
        return None
    try:
        parent_id = int(entry.get("parent_product_id") or 0)
        variation_id = int(entry.get("variation_id") or 0)
    except (TypeError, ValueError):
        return None
    if not parent_id or not variation_id:
        return None
    return {"parent_product_id": parent_id, "variation_id": variation_id}


def find_erp_sku_for_site_variation(parent_product_id, variation_id, *, exclude_sku: str = "") -> str | None:
    """برعکسِ get_site_variation_target — از رویِ شناسه‌ی محصول/واریانتِ سایت
    (که رویِ یک خطِ سفارش می‌شینه)، SKUِ سادهٔ ERPِ متناظرش رو پیدا می‌کنه.
    برایِ اینه که سفارش‌هایِ ثبت‌شده رویِ این واریانتِ سایت، به کدِ درستِ ERP
    نسبت داده بشن — وگرنه ordersync فقط SKUِ خودِ واریانتِ سایت (که با
    کدِ ERP فرقی می‌کنه) رو می‌بینه و نمی‌تونه کالا رو در ERP پیدا کنه.

    exclude_sku: برایِ تشخیصِ تعارض قبلِ ذخیره‌یِ یک لینکِ تازه — یعنی
    «آیا SKUِ دیگری (غیر از این یکی) از قبل همین واریانتِ سایت رو گرفته؟»"""
    try:
        parent_product_id = int(parent_product_id or 0)
        variation_id = int(variation_id or 0)
    except (TypeError, ValueError):
        return None
    if not parent_product_id or not variation_id:
        return None
    exclude_sku = str(exclude_sku or "").strip()
    for sku, entry in _site_variation_table.load().items():
        if not isinstance(entry, dict):
            continue
        sku = str(sku or "").strip()
        if exclude_sku and sku == exclude_sku:
            continue
        try:
            entry_parent = int(entry.get("parent_product_id") or 0)
            entry_variation = int(entry.get("variation_id") or 0)
        except (TypeError, ValueError):
            continue
        if entry_parent == parent_product_id and entry_variation == variation_id:
            return sku or None
    return None


def set_site_variation_target(
    sku: str, parent_product_id: int, variation_id: int, *, label: str = "", erp_label: str = "",
) -> None:
    sku = str(sku or "").strip()
    if not sku or not parent_product_id or not variation_id:
        return
    table = dict(_site_variation_table.load())
    table[sku] = {
        "parent_product_id": int(parent_product_id),
        "variation_id": int(variation_id),
        "label": str(label or "").strip(),
        "erp_label": str(erp_label or "").strip(),
    }
    _site_variation_table.save(table)


def clear_site_variation_target(sku: str) -> None:
    sku = str(sku or "").strip()
    if not sku:
        return
    table = dict(_site_variation_table.load())
    if sku in table:
        table.pop(sku)
        _site_variation_table.save(table)


# ----------------------------------------------------------------------
# حالتِ ۲: این محصولِ متغیرِ ERP رویِ سایت محصولِ ساده‌ست
# ----------------------------------------------------------------------
def list_force_simple_sources() -> dict[str, dict]:
    return dict(_force_simple_table.load())


def get_force_simple_source(sku: str) -> str | None:
    sku = str(sku or "").strip()
    if not sku:
        return None
    entry = _force_simple_table.load().get(sku)
    if not isinstance(entry, dict):
        return None
    source = str(entry.get("source_variation_sku") or "").strip()
    return source or None


def find_force_simple_parent_sku_for_site_product(site_product_id) -> str | None:
    """برعکسِ get_force_simple_source — از رویِ idِ محصولِ سایت (همونی که رویِ
    یک خطِ سفارش می‌شینه)، SKUِ والدِ ERPِ متناظرش رو پیدا می‌کنه — حتی وقتی
    SKUِ خودِ محصولِ سایت اصلاً با کدِ ERP یکی نیست (دقیقاً همون سناریویی که
    این قابلیت براش ساخته شده: «سایت از قبل این رو به‌عنوانِ یک محصولِ ساده
    با SKUِ خودش داره»). رفعِ باگ: قبلاً تشخیصِ سفارش فقط از رویِ تطبیقِ
    متنیِ SKU انجام می‌شد (get_force_simple_source(a_code) که a_code از
    پارسِ SKUِ خودِ سایت می‌اومد) — اگه SKUِ سایت با کدِ ERP فرق داشت، این
    تطبیق هیچ‌وقت برقرار نمی‌شد و سفارش یا با یک ردیفِ نامعتبر ثبت می‌شد یا
    (بدتر) اگه SKUِ سایت تصادفاً با یک کدِ واقعیِ دیگه در ERP یکی بود، فروش
    به کالایِ اشتباه نسبت داده می‌شد. حالا از idِ محصولِ سایت استفاده
    می‌کنیم (مثلِ find_erp_sku_for_site_variation) — چون _fs_apply_match
    همیشه product_woo_map[parent_sku] رو هم به همین id ست می‌کنه."""
    try:
        site_product_id = int(site_product_id or 0)
    except (TypeError, ValueError):
        return None
    if not site_product_id:
        return None
    sources = _force_simple_table.load()
    if not sources:
        return None

    from sync_app.core.product_woo_map_helper import load_product_woo_map

    product_map = load_product_woo_map()
    for parent_sku in sources.keys():
        parent_sku = str(parent_sku or "").strip()
        if not parent_sku:
            continue
        mapped_id = product_map.get(parent_sku)
        try:
            if mapped_id is not None and int(mapped_id) == site_product_id:
                return parent_sku
        except (TypeError, ValueError):
            continue
    return None


def set_force_simple_source(
    sku: str, source_variation_sku: str, *, erp_label: str = "", site_label: str = "",
) -> None:
    sku = str(sku or "").strip()
    source_variation_sku = str(source_variation_sku or "").strip()
    if not sku or not source_variation_sku:
        return
    table = dict(_force_simple_table.load())
    table[sku] = {
        "source_variation_sku": source_variation_sku,
        "erp_label": str(erp_label or "").strip(),
        "site_label": str(site_label or "").strip(),
    }
    _force_simple_table.save(table)


def clear_force_simple_source(sku: str) -> None:
    sku = str(sku or "").strip()
    if not sku:
        return
    table = dict(_force_simple_table.load())
    if sku in table:
        table.pop(sku)
        _force_simple_table.save(table)
