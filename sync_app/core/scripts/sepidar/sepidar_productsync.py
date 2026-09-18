"""POS.Item + ItemOpening + ItemGroupItem + ItemSalePrice — محصولِ سادهٔ
سپیدار/دشت، از محصولِ سایت (فقط محصولِ ساده — سپیدار ویژگی/متغیر نداره).

INSERT دقیقاً مطابقِ ترِیسِ واقعیِ سپیدار (Article.txt): پنج ردیف برایِ
هر کالایِ جدید، به همون ترتیب (ItemImage اختیاری/کم‌اهمیت، در v1 پیاده
نشده). قیمتِ فروش فقط در ستونِ DefaultPrice نوشته می‌شه (Price1..10 خالی
می‌مونن) — طبقِ تصمیمِ کاربر."""

from __future__ import annotations

from sync_app.core.scripts.sepidar.sepidar_categorysync import (
    fetch_site_categories,
    resolve_mapped_item_group_from_index,
)
from sync_app.core.scripts.sepidar.sepidar_common import (
    get_fiscal_period_ref,
    get_sepidar_connection,
    get_stock_ref,
    load_sepidar_map,
    next_int_code,
    next_padded_code,
    save_sepidar_map,
    sepidar_apply_lock,
)

_MAP_FILE = "sepidar_product_map.json"
_CATEGORY_MAP_FILE = "sepidar_category_map.json"
_ITEM_CODE_SUFFIX_WIDTH = 4


def fetch_site_products(config: dict | None = None) -> list[dict]:
    """[{id, sku, name, regular_price, categories:[{id}], type, status}]."""
    from sync_app.core.integrations.commerce_provider import is_prestashop

    config = config or {}
    if is_prestashop(config):
        from sync_app.core.ps_sync_helper import ps_list_products

        return ps_list_products(config)

    from sync_app.core.integrations.commerce_provider import build_store_api
    from sync_app.core.wc_sync_helper import wc_parse_json

    wcapi = build_store_api(config)
    out: list[dict] = []
    page = 1
    while True:
        resp = wcapi.get(
            "products",
            params={
                "status": "publish", "per_page": 100, "page": page,
                "_fields": (
                    "id,sku,name,regular_price,price,categories,type,status,stock_quantity,"
                    "images,description,short_description"
                ),
            },
        )
        data = wc_parse_json(resp, "دریافتِ محصولاتِ سایت (سپیدار)")
        if not isinstance(data, list) or not data:
            break
        out.extend([r for r in data if isinstance(r, dict) and r.get("id")])
        if len(data) < 100:
            break
        page += 1
    return out


def _extract_price(row: dict) -> float:
    for key in ("regular_price", "price"):
        raw = row.get(key)
        try:
            if raw not in (None, ""):
                return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def fetch_products_for_display(config: dict | None = None) -> list[dict]:
    """لیستِ محصولاتِ سایت به‌شکلِ ردیف‌هایِ موردِ انتظارِ تبِ محصولات
    (`tab_products.py`’s `_apply_products_rows`) — برایِ سپیدار/دشت، جهتِ
    نمایش برعکسِ دژاووعه: محصولاتِ سایت خونده می‌شن (نه Article)، و وضعیتِ
    لینک یعنی «این SKU از قبل در سپیدار به‌عنوانِ Item ساخته شده یا نه»
    (از `sepidar_product_map.json`، نه product_woo_map.json)."""
    from sync_app.core.currency_helper import wc_total_to_erp_amount

    config = config or {}
    site_products = fetch_site_products(config)
    rows: list[dict] = []
    for row in site_products:
        if str(row.get("type") or "simple") != "simple":
            continue
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        stock_raw = row.get("stock_quantity")
        try:
            stock = int(stock_raw) if stock_raw is not None else 0
        except (TypeError, ValueError):
            stock = 0
        # tab_products.py’s _apply_products_rows همیشه انتظار داره price در
        # واحدِ ریال/ERP باشه (بعداً خودش موقعِ نمایش، اگه پرچمِ تومان روشن
        # باشه، تقسیم بر ۱۰ می‌کنه) — چون این‌جا قیمت مستقیماً از سایت
        # میاد (نه از ERP)، با wc_total_to_erp_amount به همون قرارداد
        # تبدیلش می‌کنیم تا نمایشِ نهایی درست بمونه.
        rows.append({
            "sku": sku,
            "name": str(row.get("name") or sku).strip(),
            "price": wc_total_to_erp_amount(_extract_price(row), config),
            "stock": stock,
            "picture_blob": b"",
            "picture_path": "",
            "erp_images": [],
            "erp_image_count": 0,
            "is_variant": False,
        })
    return rows


def fetch_readiness_rows(config: dict | None = None) -> list[tuple]:
    """ردیف‌هایِ «آمادگیِ انتشار محصول» برایِ سپیدار/دشت (`tab_media_center.py`’s
    بخشِ ۵ و `tab_peecha_advisor.py`’s `_readiness_summary`) — برخلافِ دژاوو،
    منبعِ عکس/دسته‌بندی/توضیحات مستقیماً خودِ محصولِ سایته (چون سپیدار اصلاً
    عکس/توضیحات ذخیره نمی‌کنه)، و «همگام با ووکامرس» یعنی این SKU از قبل
    به‌عنوانِ POS.Item در سپیدار ساخته شده (`sepidar_product_map.json`)."""
    from sync_app.core.media_center import product_readiness

    config = config or {}
    product_map = load_sepidar_map(_MAP_FILE)
    site_products = fetch_site_products(config)

    rows: list[tuple] = []
    for row in site_products:
        if str(row.get("type") or "simple") != "simple":
            continue
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        name = str(row.get("name") or sku).strip()
        stock_raw = row.get("stock_quantity")
        try:
            stock = int(stock_raw) if stock_raw is not None else 0
        except (TypeError, ValueError):
            stock = 0
        description = str(row.get("description") or row.get("short_description") or "").strip()

        product = {
            "has_image": bool(row.get("images")),
            "has_category": bool(row.get("categories")),
            "price": _extract_price(row),
            "stock": stock,
            "description": description,
            "synced_to_woo": sku in product_map,
        }
        result = product_readiness(product)
        missing = [c.missing_label for c in result.checks if not c.ok]
        rows.append((sku, name, result.score, missing))
    rows.sort(key=lambda r: r[2])
    return rows


def _item_group_hierarchy_code(cursor, item_group_id: int) -> str:
    cursor.execute("SELECT HierarchyCode FROM POS.vwItemGroup WHERE ItemGroupID = ?", (item_group_id,))
    row = cursor.fetchone()
    code = str(row[0]).strip() if row and row[0] else ""
    return code or "00"


def _next_item_code(cursor, group_hierarchy_code: str) -> str:
    """<HierarchyCodeِ گروه/زیرگروه> + دنبالهٔ ۴رقمی، مطابقِ Article.txt (@Code=N'01020001')."""
    seq = next_padded_code(
        cursor, "POS.Item", "RIGHT(Code, 4)", _ITEM_CODE_SUFFIX_WIDTH,
        where_sql="LEN(Code) >= 4 AND LEFT(Code, LEN(Code) - 4) = ?",
        params=(group_hierarchy_code,),
    )
    return f"{group_hierarchy_code}{seq}"


def _create_item(cursor, config, sku: str, title: str, item_group_id: int, group_hierarchy_code: str, price: float) -> int:
    item_id = next_int_code(cursor, "POS.Item", "ItemID")
    code = _next_item_code(cursor, group_hierarchy_code)

    cursor.execute(
        """
        INSERT INTO POS.[Item]
            ([Description], [MinimumAmount], [MaximumAmount], [ReadFromScale], [ItemCategoryForTax96],
             [HasSerial], [ItemOpeningVoucherRef], [IsApiEnabled], [ItemID], [Type], [Code], [Title],
             [BarCode], [IranCode], [UnitRef], [IsActive], [TaxPercent], [DutyPercent],
             [TracingOnPurchasePrice], [Creator], [SalePriceHasTaxAndDuty], [CreationDate],
             [SaleTaxExempt], [LastModifier], [PurchaseTaxExempt], [LastModificationDate], [Version],
             [CompoundBarcodeRef])
        VALUES
            (NULL, NULL, NULL, 0, 12, 0, NULL, 0, ?, 1, ?, ?, NULL, NULL, 1, 1, 0, 0, 0, ?, 0, GETDATE(),
             0, ?, 0, GETDATE(), 1, NULL)
        """,
        (item_id, code, title or sku, 1, 1),
    )

    stock_ref = get_stock_ref(config)
    fiscal_period_ref = get_fiscal_period_ref(config)
    cursor.execute(
        """
        INSERT INTO POS.[ItemOpening]
            ([ChangedByUser], [ItemOpeningID], [StockRef], [ItemRef], [PurchasePrice], [Quantity],
             [FiscalPeriodRef], [Creator], [CreationDate], [LastModifier], [LastModificationDate], [Version])
        VALUES (0, ?, ?, ?, NULL, 0, ?, ?, GETDATE(), ?, GETDATE(), 1)
        """,
        (item_id, stock_ref, item_id, fiscal_period_ref, 1, 1),
    )

    item_group_item_id = next_int_code(cursor, "POS.ItemGroupItem", "ItemGroupItemID")
    cursor.execute(
        "INSERT INTO POS.[ItemGroupItem] ([ItemGroupItemID], [ItemGroupRef], [ItemRef]) VALUES (?, ?, ?)",
        (item_group_item_id, item_group_id, item_id),
    )

    item_sale_price_id = next_int_code(cursor, "POS.ItemSalePrice", "ItemSalePriceID")
    cursor.execute(
        """
        INSERT INTO POS.[ItemSalePrice]
            ([SalePriceMargin], [DiscountMargin], [ItemSalePriceID], [ItemRef], [PurchasePrice],
             [DefaultPrice], [Price1], [Price2], [Price3], [Price4], [Price5], [Price6], [Price7],
             [Price8], [Price9], [Price10], [Creator], [CreationDate], [LastModifier],
             [LastModificationDate], [Version], [ItemSubUnitRef])
        VALUES (NULL, NULL, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                ?, GETDATE(), ?, GETDATE(), 1, NULL)
        """,
        (item_sale_price_id, item_id, price, 1, 1),
    )
    return item_id


def sync_products(config: dict | None = None) -> dict:
    from sync_app.core.sync_utils import log

    config = config or {}
    site_products = fetch_site_products(config)
    if not site_products:
        log.info("ℹ️ هیچ محصولی در سایت یافت نشد.")
        return {"created": 0, "skipped": 0, "total": 0}

    product_map = load_sepidar_map(_MAP_FILE)
    category_map = load_sepidar_map(_CATEGORY_MAP_FILE)
    site_categories = fetch_site_categories(config)
    by_id = {c["id"]: c for c in site_categories}

    created = 0
    skipped: list[str] = []

    conn = get_sepidar_connection(config)
    try:
        cursor = conn.cursor()
        sepidar_apply_lock(cursor, "Item")

        for row in site_products:
            sku = str(row.get("sku") or "").strip()
            if not sku or sku in product_map:
                continue
            if str(row.get("type") or "simple") != "simple":
                skipped.append(sku)
                log.warning(f"⚠️ [{sku}] محصولِ متغیر/غیرساده — سپیدار فقط کالایِ ساده می‌پذیره، رد شد.")
                continue

            category_ids = [
                int(c["id"]) for c in (row.get("categories") or [])
                if isinstance(c, dict) and c.get("id")
            ]
            item_group_id = resolve_mapped_item_group_from_index(category_ids, category_map, by_id)
            if item_group_id is None:
                skipped.append(sku)
                log.warning(f"⚠️ [{sku}] گروهِ کالا در سپیدار سینک نشده — این محصول رد شد.")
                continue

            group_hierarchy_code = _item_group_hierarchy_code(cursor, item_group_id)
            price = _extract_price(row)
            title = str(row.get("name") or sku).strip()
            item_id = _create_item(cursor, config, sku, title, item_group_id, group_hierarchy_code, price)
            product_map[sku] = item_id
            created += 1

        # تطبیقِ ساختاری («سایت متغیر / سپیدار ساده») — واریانت‌هایی که
        # کاربر از تبِ «تطبیقِ ساختاری» دستی به یک SKU لینک کرده، اینجا هم
        # مثلِ محصولِ ساده به سپیدار سینک می‌شن (فقط منبعِ sku/price از خودِ
        # واریانت میاد، نه از محصولِ چندگانه‌ی سایت که در حلقه‌ی بالا رد شد).
        from sync_app.core.structure_mismatch_override import list_site_variation_targets

        overrides = list_site_variation_targets()
        if overrides:
            from sync_app.core.tabs.tab_structure_reconciliation import _list_site_variations_for_product

            products_by_id = {int(p["id"]): p for p in site_products if p.get("id")}
            for sku, target in overrides.items():
                sku = str(sku or "").strip()
                if not sku or sku in product_map:
                    continue
                parent_id = int(target.get("parent_product_id") or 0)
                variation_id = int(target.get("variation_id") or 0)
                if not parent_id or not variation_id:
                    continue
                parent_row = products_by_id.get(parent_id)
                if parent_row is None:
                    skipped.append(sku)
                    log.warning(f"⚠️ [{sku}] محصولِ والدِ این تطبیقِ ساختاری در سایت پیدا نشد — رد شد.")
                    continue
                category_ids = [
                    int(c["id"]) for c in (parent_row.get("categories") or [])
                    if isinstance(c, dict) and c.get("id")
                ]
                item_group_id = resolve_mapped_item_group_from_index(category_ids, category_map, by_id)
                if item_group_id is None:
                    skipped.append(sku)
                    log.warning(f"⚠️ [{sku}] گروهِ کالایِ محصولِ والد در سپیدار سینک نشده — این تطبیقِ ساختاری رد شد.")
                    continue
                try:
                    variations = _list_site_variations_for_product(config, {"id": parent_id})
                except Exception as exc:
                    skipped.append(sku)
                    log.warning(f"⚠️ [{sku}] دریافتِ واریانت‌هایِ سایت ناموفق بود: {exc}")
                    continue
                variation = next((v for v in variations if int(v.get("id") or 0) == variation_id), None)
                if variation is None:
                    skipped.append(sku)
                    log.warning(f"⚠️ [{sku}] واریانتِ تطبیق‌شده دیگه در سایت پیدا نشد — رد شد.")
                    continue

                group_hierarchy_code = _item_group_hierarchy_code(cursor, item_group_id)
                price = _extract_price({"price": variation.get("price")})
                title = str(parent_row.get("name") or sku).strip()
                item_id = _create_item(cursor, config, sku, title, item_group_id, group_hierarchy_code, price)
                product_map[sku] = item_id
                created += 1

        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error(f"❌ خطا در سینکِ کالایِ سپیدار: {exc}")
        raise
    finally:
        conn.close()

    save_sepidar_map(_MAP_FILE, product_map)
    log.info(f"✅ کالایِ سپیدار: {created} کالایِ جدید ساخته شد.")
    if skipped:
        log.warning(f"⚠️ محصولاتِ ردشده: {', '.join(skipped)}")
    return {"created": created, "skipped": len(skipped), "total": len(product_map)}


def fetch_sepidar_items(config: dict | None = None) -> list[dict]:
    """[{id, code, title, price}] — کالاهایِ موجود در POS.Item (+ DefaultPrice
    از POS.ItemSalePrice) — برایِ نمایشِ سمتِ سپیدار در تبِ «تطبیق»."""
    conn = get_sepidar_connection(config or {})
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT i.ItemID, i.Code, i.Title, sp.DefaultPrice "
            "FROM POS.Item i LEFT JOIN POS.ItemSalePrice sp ON sp.ItemRef = i.ItemID"
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": int(r[0]),
            "code": str(r[1] or "").strip(),
            "title": str(r[2] or "").strip(),
            "price": float(r[3]) if r[3] is not None else 0.0,
        }
        for r in rows
    ]


def main(config: dict | None = None) -> dict:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config or load_secure_config(None) or {}
    return sync_products(cfg)


if __name__ == "__main__":
    main()
