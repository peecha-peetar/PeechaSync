"""ابزارهایِ مشترکِ سپیدار/دشت — اتصال، قفل، تولیدِ کد، نگاشتِ SKU/مشتری/سفارش.

طبقِ بررسیِ ۵ فایلِ Profiler واقعیِ کاربر (ایجادِ گروه/زیرگروهِ کالا، تعریفِ
کالا، تعریفِ طرف‌حساب+آدرس، فاکتورِ فروش)، سپیدار/دشت:
  - کلیدهایِ اصلیِ خیلی از جدول‌ها (ItemGroupID/PartyId/ItemID/SaleInvoiceID)
    client-assigned هستن، نه identity — پس این ماژول کدِ بعدی رو با
    MAX(...)+1 حساب می‌کنه (دقیقاً همون سبکی که خودِ کاربر برایِ روشِ
    مشتریِ دژاوو هم تایید کرده بود).
  - برایِ Party، خودِ سپیدار قبل از تولیدِ کد یک قفلِ نام‌دار می‌گیره
    (`Exec FMK.spGetLock 'PartyRow'`) — همون رو عیناً تکرار می‌کنیم.
  - برایِ بقیهٔ موجودیت‌ها (Item/ItemGroup/SaleInvoice) نامِ دقیقِ قفلِ
    سپیدار در ترِیس‌ها دیده نشد؛ به‌جایِ حدس‌زدن، از sp_getapplock بومیِ
    SQL Server استفاده می‌کنیم که کاملاً مستقل از schema سپیداره و امنه.
"""

from __future__ import annotations

import json

_SEPIDAR_PROVIDER_KEYS = ("sepidar", "dasht")


def is_sepidar_provider(config: dict | None) -> bool:
    from sync_app.core.integrations.erp_provider import normalize_erp_provider_key

    key = normalize_erp_provider_key((config or {}).get("ERP_PROVIDER"))
    return key in _SEPIDAR_PROVIDER_KEYS


def get_sepidar_connection(config, timeout: int = 15):
    """اتصالِ SQL Server عمومی و provider-agnostic — بدونِ هیچ تغییری در
    sql_connection_helper.py، همون هلپرِ موجود برایِ دژاوو رو صدا می‌زنیم."""
    from sync_app.core.sql_connection_helper import open_sql_connection

    conn, _auth_mode, _conn_str = open_sql_connection(config, timeout=timeout)
    return conn


def sepidar_health_check(config) -> tuple[bool, str]:
    try:
        conn = get_sepidar_connection(config, timeout=6)
        conn.close()
        return True, "اتصال به دیتابیس سپیدار/دشت برقرار است."
    except Exception as exc:
        return False, f"اتصال به دیتابیس سپیدار/دشت ناموفق بود: {exc}"


def get_stock_ref(config) -> int:
    raw = str((config or {}).get("SEPIDAR_STOCK_REF") or "1").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def get_fiscal_period_ref(config) -> int:
    raw = str((config or {}).get("SEPIDAR_FISCAL_PERIOD_REF") or "1").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def get_default_location_ref(config) -> int | None:
    raw = str((config or {}).get("SEPIDAR_DEFAULT_LOCATION_REF") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def sepidar_apply_lock(cursor, resource: str, timeout_ms: int = 5000) -> None:
    """قفلِ برنامه‌ایِ عمومیِ SQL Server — برایِ جلوگیریِ از تصادمِ تولیدِ
    کدِ همزمان (Item/ItemGroup/SaleInvoice). مستقل از schema سپیداره."""
    cursor.execute(
        "DECLARE @rc INT; "
        "EXEC @rc = sp_getapplock @Resource = ?, @LockMode = 'Exclusive', "
        "@LockOwner = 'Transaction', @LockTimeout = ?; "
        "SELECT @rc AS rc",
        (f"Sepidar_{resource}", int(timeout_ms)),
    )
    row = cursor.fetchone()
    rc = int(row[0]) if row and row[0] is not None else -999
    if rc < 0:
        raise RuntimeError(f"قفل‌گیریِ Sepidar_{resource} ناموفق بود (کد {rc}).")


def sepidar_party_row_lock(cursor) -> None:
    """دقیقاً مطابقِ ترِیسِ واقعیِ سپیدار برایِ ثبتِ طرف‌حساب."""
    cursor.execute("Exec FMK.spGetLock 'PartyRow'")


def next_int_code(cursor, table: str, id_column: str, where_sql: str = "", params: tuple = ()) -> int:
    """SELECT ISNULL(MAX(id_column),0)+1 FROM table [WHERE ...] — برایِ
    کلیدهایِ client-assigned مثلِ ItemID/PartyId/SaleInvoiceID/ItemGroupID."""
    sql = f"SELECT ISNULL(MAX({id_column}), 0) + 1 FROM {table}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    cursor.execute(sql, params)
    row = cursor.fetchone()
    try:
        return int(row[0]) if row and row[0] is not None else 1
    except (TypeError, ValueError):
        return 1


def next_padded_code(cursor, table: str, code_column: str, width: int, where_sql: str = "", params: tuple = ()) -> str:
    """مشابهِ next_int_code ولی برایِ فیلدهایِ متنیِ Code (مثلِ کدِ ۲رقمیِ
    ItemGroup/Party)."""
    sql = f"SELECT MAX(CAST({code_column} AS INT)) FROM {table}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    cursor.execute(sql, params)
    row = cursor.fetchone()
    try:
        max_val = int(row[0]) if row and row[0] is not None else 0
    except (TypeError, ValueError):
        max_val = 0
    return str(max_val + 1).zfill(width)


def _sepidar_map_path(filename: str) -> str:
    from sync_app.core.sync_utils import site_scoped_path

    return site_scoped_path(filename)


def load_sepidar_map(filename: str) -> dict:
    try:
        with open(_sepidar_map_path(filename), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_sepidar_map(filename: str, data: dict) -> None:
    try:
        with open(_sepidar_map_path(filename), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        from sync_app.core.sync_utils import log

        log.warning(f"⚠️ ذخیره {filename}: {exc}")


def compute_sepidar_unlinked_counts(config: dict) -> dict:
    """معادلِ auto_sync_scope.compute_unlinked_counts برایِ سپیدار/دشت —
    چون آن تابع به SELECTED_SUB_GROUPS وابسته‌ست (مفهومی که سپیدار اصلاً
    نداره)، این‌جا کلِ دسته‌بندی/محصولِ سایت رو مستقیم با نگاشتِ
    sepidar_*_map.json مقایسه می‌کنه."""
    from sync_app.core.scripts.sepidar.sepidar_categorysync import fetch_site_categories
    from sync_app.core.scripts.sepidar.sepidar_productsync import fetch_site_products

    category_map = load_sepidar_map("sepidar_category_map.json")
    categories = fetch_site_categories(config)
    categories_unlinked = sum(1 for c in categories if str(c["id"]) not in category_map)

    product_map = load_sepidar_map("sepidar_product_map.json")
    products = fetch_site_products(config)
    products_unlinked = sum(
        1 for p in products
        if str(p.get("type") or "simple") == "simple" and str(p.get("sku") or "").strip() not in product_map
    )
    return {"products": products_unlinked, "categories": categories_unlinked}
