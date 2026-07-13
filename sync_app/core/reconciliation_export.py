"""
خروجی اکسل از محصولات/متغیرهای «سمت سایت» که در تب تطبیق بارگذاری شده‌اند.
فقط خواندنی — هیچ تغییری در منطق تطبیق/سینک اعمال نمی‌کند؛ فقط از همان
تابع WC API موجود (_wc_get_paginated) برای خواندن جزئیات بیشتر استفاده می‌کند.
"""

from __future__ import annotations

import re
from typing import Callable

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from sync_app.core.integrations.commerce_provider import is_prestashop
from sync_app.core.reconciliation_service import _wc_get_paginated

PRODUCT_FIELDS = (
    "id,sku,name,regular_price,sale_price,description,short_description,"
    "categories,attributes,type,variations,status"
)
VARIATION_FIELDS = "id,sku,regular_price,sale_price,attributes,description"


def _strip_html(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _find_brand(attributes: list) -> str:
    """اگه محصول یه ویژگی با اسم شامل «برند»/brand داشته باشه، مقدارش رو برمی‌گردونه."""
    for attr in attributes or []:
        if not isinstance(attr, dict):
            continue
        name = str(attr.get("name") or "").strip().lower()
        if "برند" in name or "brand" in name:
            options = attr.get("options") or []
            if options:
                return "، ".join(str(o) for o in options)
    return ""


def _category_levels(categories: list, cat_by_id: dict) -> tuple[str, str]:
    """دسته‌بندی سطح ۱ (والد) و سطح ۲ (خودِ دسته‌ی اختصاص‌داده‌شده) را برمی‌گرداند."""
    if not categories:
        return "", ""
    first = categories[0]
    cid = int(first.get("id") or 0) if isinstance(first, dict) else 0
    cat = cat_by_id.get(cid, first if isinstance(first, dict) else {})
    name = str(cat.get("name") or "").strip()
    parent_id = int(cat.get("parent") or 0)
    if parent_id and parent_id in cat_by_id:
        parent_name = str(cat_by_id[parent_id].get("name") or "").strip()
        return parent_name, name
    return name, ""


def _chunked(items: list, size: int = 60):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _fetch_ps_products_for_export(
    config: dict,
    ps_ids: list[int],
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """معادل fetch_products_for_export برای پرستاشاپ.

    ⚠️ دو محدودیتِ ذاتی پرستاشاپ نسبت به ووکامرس: «قیمت ویژه» (sale_price)
    و «برند» معادل مستقیم در Webservice ندارند — این دو ستون همیشه خالی
    می‌مونن، حدس زده نمی‌شن.
    """
    from sync_app.core.reconciliation_service import _check_recon_cancel, _recon_http_timeout
    from sync_app.core.ps_sync_helper import ps_get_product, ps_list_categories
    from sync_app.core.ps_variation_helper import (
        ps_list_attribute_groups,
        ps_list_attribute_values,
        ps_list_combinations,
    )

    if not ps_ids:
        return []

    timeout = _recon_http_timeout(config)
    _check_recon_cancel(cancel_check)
    categories = ps_list_categories(config, timeout=timeout)
    cat_by_id = {int(c["id"]): c for c in categories if isinstance(c, dict) and c.get("id")}

    value_names: dict[int, str] = {}
    try:
        for group in ps_list_attribute_groups(config, timeout=timeout):
            _check_recon_cancel(cancel_check)
            for value in ps_list_attribute_values(config, group["id"], timeout=timeout):
                value_names[int(value["id"])] = str(value.get("name") or "").strip()
    except Exception:
        pass

    results: list[dict] = []
    unique_ids = [int(i) for i in ps_ids if i]
    for done, pid in enumerate(unique_ids, start=1):
        _check_recon_cancel(cancel_check)
        p = ps_get_product(config, pid, timeout=timeout)
        if not p:
            if progress_cb:
                progress_cb(done, len(unique_ids))
            continue
        level1, level2 = _category_levels(p.get("categories") or [], cat_by_id)
        base_price = float(p.get("regular_price") or 0)
        try:
            combos = ps_list_combinations(config, pid, timeout=timeout)
        except Exception:
            combos = []
        row = {
            "wc_id": int(p.get("id") or 0),
            "sku": str(p.get("sku") or "").strip(),
            "name": str(p.get("name") or "").strip(),
            "category_l1": level1,
            "category_l2": level2,
            "regular_price": str(p.get("regular_price") or "").strip(),
            "sale_price": "",
            "description": _strip_html(p.get("description") or ""),
            "brand": "",
            "type": "variable" if combos else "simple",
            "variation_ids": [int(c["id"]) for c in combos],
            "variations": [],
        }
        for combo in combos:
            option_ids = combo.get("option_value_ids") or []
            attr_text = " / ".join(
                value_names[int(oid)] for oid in option_ids if int(oid) in value_names
            )
            row["variations"].append({
                "wc_id": int(combo.get("id") or 0),
                "sku": str(combo.get("reference") or "").strip(),
                "attributes": attr_text,
                "regular_price": f"{base_price + float(combo.get('price_impact') or 0):.6f}",
                "sale_price": "",
            })
        results.append(row)
        if progress_cb:
            progress_cb(done, len(unique_ids))
    return results


def fetch_products_for_export(
    config: dict,
    wc_ids: list[int],
    *,
    cancel_check: Callable[[], bool] | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    برای شناسه‌های ووکامرس داده‌شده، جزئیات کامل (قیمت/دسته/توضیحات/برند/
    لیست متغیرها) رو می‌خونه. فقط خواندنی — چیزی روی سایت تغییر نمی‌کنه.
    """
    if not wc_ids:
        return []

    if is_prestashop(config):
        return _fetch_ps_products_for_export(
            config, wc_ids, cancel_check=cancel_check, progress_cb=progress_cb
        )

    categories = _wc_get_paginated(
        config, "products/categories",
        params={"_fields": "id,name,parent", "per_page": 100},
        cancel_check=cancel_check,
    )
    cat_by_id = {
        int(c["id"]): c for c in categories if isinstance(c, dict) and c.get("id")
    }

    results: list[dict] = []
    unique_ids = [int(i) for i in wc_ids if i]
    done = 0
    for batch in _chunked(unique_ids):
        products = _wc_get_paginated(
            config, "products",
            params={"include": ",".join(str(i) for i in batch), "_fields": PRODUCT_FIELDS, "per_page": 100},
            cancel_check=cancel_check,
        )
        for p in products:
            if not isinstance(p, dict):
                continue
            level1, level2 = _category_levels(p.get("categories") or [], cat_by_id)
            row = {
                "wc_id": int(p.get("id") or 0),
                "sku": str(p.get("sku") or "").strip(),
                "name": str(p.get("name") or "").strip(),
                "category_l1": level1,
                "category_l2": level2,
                "regular_price": str(p.get("regular_price") or "").strip(),
                "sale_price": str(p.get("sale_price") or "").strip(),
                "description": _strip_html(p.get("description") or p.get("short_description") or ""),
                "brand": _find_brand(p.get("attributes") or []),
                "type": str(p.get("type") or "simple"),
                "variation_ids": list(p.get("variations") or []),
                "variations": [],
            }

            if row["type"] == "variable" and row["variation_ids"]:
                variations = _wc_get_paginated(
                    config, f"products/{row['wc_id']}/variations",
                    params={"_fields": VARIATION_FIELDS, "per_page": 100},
                    cancel_check=cancel_check,
                )
                for v in variations:
                    if not isinstance(v, dict):
                        continue
                    attrs = v.get("attributes") or []
                    attr_text = " / ".join(
                        str(a.get("option") or "").strip() for a in attrs
                        if isinstance(a, dict) and a.get("option")
                    )
                    row["variations"].append({
                        "wc_id": int(v.get("id") or 0),
                        "sku": str(v.get("sku") or "").strip(),
                        "attributes": attr_text,
                        "regular_price": str(v.get("regular_price") or "").strip(),
                        "sale_price": str(v.get("sale_price") or "").strip(),
                    })
            results.append(row)
            done += 1
            if progress_cb:
                progress_cb(done, len(unique_ids))
    return results


_HEADER_FILL = PatternFill("solid", start_color="1D4ED8", end_color="1D4ED8")
_HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
_BODY_FONT = Font(name="Arial", size=10)


def _write_sheet(ws, headers: list[str], rows: list[list]):
    ws.sheet_view.rightToLeft = True
    for col_idx, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=title)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r_idx, row_vals in enumerate(rows, start=2):
        for c_idx, val in enumerate(row_vals, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = _BODY_FONT
            cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 22
    ws.freeze_panes = "A2"


def export_products_to_excel(rows: list[dict], out_path: str) -> int:
    """
    خروجی اصلی محصولات — یک ردیف به‌ازای هر محصول. ستون «متغیرها» فقط
    خلاصه‌ی متن (اسم‌ها/قیمت‌ها) رو نشون می‌ده؛ برای جزئیات کامل هر متغیر،
    از دکمه‌ی جدای «خروجی اکسل متغیرها» استفاده کنید.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "محصولات سایت"
    headers = [
        "کد کالا (شناسه فروشگاه)", "نام کالا", "SKU", "دسته‌بندی سطح ۱", "دسته‌بندی سطح ۲",
        "قیمت عادی", "قیمت ویژه", "متغیرها", "توضیحات محصول", "برند",
    ]
    body = []
    for r in rows:
        var_summary = " | ".join(
            f"{v['attributes']} ({v['sku'] or '—'})" for v in r["variations"]
        ) if r["variations"] else ""
        body.append([
            r["wc_id"], r["name"], r["sku"], r["category_l1"], r["category_l2"],
            r["regular_price"], r["sale_price"], var_summary, r["description"], r["brand"],
        ])
    _write_sheet(ws, headers, body)
    wb.save(out_path)
    return len(body)


def export_variations_to_excel(rows: list[dict], out_path: str) -> int:
    """خروجی جدا برای متغیرها — یک ردیف به‌ازای هر متغیر (نه هر محصول)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "متغیرهای سایت"
    headers = [
        "کد محصول والد", "نام محصول والد", "SKU متغیر", "ویژگی‌های متغیر",
        "قیمت عادی", "قیمت ویژه",
    ]
    body = []
    for r in rows:
        for v in r["variations"]:
            body.append([
                r["wc_id"], r["name"], v["sku"], v["attributes"],
                v["regular_price"], v["sale_price"],
            ])
    _write_sheet(ws, headers, body)
    wb.save(out_path)
    return len(body)
