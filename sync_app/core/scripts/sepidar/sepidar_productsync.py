"""POS.Item + ItemOpening + ItemGroupItem + ItemSalePrice — کالایِ سادهٔ
سپیدار/دشت (سپیدار ویژگی/متغیر نداره).

جهتِ سینک: ERP → سایت — دقیقاً مثلِ sync_fullproduct.py دژاوو. POS.Item
(+ POS.ItemSalePrice برایِ قیمت، POS.ItemOpening برایِ موجودی،
POS.ItemGroupItem برایِ دسته‌بندی) خونده می‌شه و به‌عنوانِ محصولِ
ووکامرس/پرستاشاپ ساخته/به‌روزرسانی می‌شه."""

from __future__ import annotations

from sync_app.core.scripts.sepidar.sepidar_common import get_sepidar_connection, load_sepidar_map, save_sepidar_map

_MAP_FILE = "sepidar_product_map.json"
_CATEGORY_MAP_FILE = "sepidar_category_map.json"


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


def _expand_sepidar_groups_with_descendants(selected_ids, groups: list[dict]) -> set[str]:
    """برخلافِ فازِ ۱ (که برایِ پوشِ دسته‌بندی والدها رو بالا می‌رفت)، این‌جا
    برعکسه — اگه کاربر یک گروهِ بالادستی رو تیک بزنه، همه‌یِ زیرگروه‌هاش
    هم باید شاملِ محصولات بشن (مثلِ A_Code LIKE 'group%'ِ دژاوو که همه‌یِ
    زیرکدها رو خودکار می‌گیره). گاردِ چرخه: با مجموعه‌یِ نتیجه."""
    by_id = {str(g["id"]): g for g in groups}
    children_map: dict[str, list[str]] = {}
    for gid, g in by_id.items():
        parent_ref = g.get("parent_ref")
        parent_key = str(parent_ref) if parent_ref is not None else None
        if parent_key and parent_key in by_id and parent_key != gid:
            children_map.setdefault(parent_key, []).append(gid)

    result: set[str] = set()
    stack = [str(s).strip() for s in selected_ids if str(s).strip() in by_id]
    while stack:
        gid = stack.pop()
        if gid in result:
            continue
        result.add(gid)
        stack.extend(children_map.get(gid, []))
    return result


def fetch_sepidar_products_for_sync(config: dict | None = None, selected_group_ids=None) -> list[dict]:
    """آیتم‌هایِ POS.Item (+ قیمت/موجودی/گروه) — معادلِ
    `_fetch_products_from_sql`ِ دژاوو، برایِ نمایش/ارسالِ سپیدار. اگه
    `selected_group_ids` داده بشه (بعدِ `_expand_sepidar_groups_with_descendants`)،
    فقط آیتم‌هایی که `ItemGroupRef`شون تو اون مجموعه‌ست برمی‌گردن."""
    conn = get_sepidar_connection(config or {})
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT i.ItemID, i.Code, i.Title, sp.DefaultPrice "
            "FROM POS.Item i LEFT JOIN POS.ItemSalePrice sp ON sp.ItemRef = i.ItemID"
        )
        item_rows = cursor.fetchall()

        # چند ردیف به‌ازایِ هر کالا ممکنه (چند انبار/دوره‌یِ مالی) — باید جمع بشه
        cursor.execute(
            "SELECT ItemRef, SUM(CAST(ISNULL(Quantity, 0) AS BIGINT)) FROM POS.ItemOpening GROUP BY ItemRef"
        )
        stock_by_item = {int(r[0]): int(r[1] or 0) for r in cursor.fetchall()}

        # اولین SELECT از این جدول — تا حالا فقط INSERT داشت
        cursor.execute("SELECT ItemRef, ItemGroupRef FROM POS.ItemGroupItem")
        group_by_item: dict[int, int] = {}
        for r in cursor.fetchall():
            if r[0] is not None and r[1] is not None:
                group_by_item[int(r[0])] = int(r[1])
    finally:
        conn.close()

    rows: list[dict] = []
    for r in item_rows:
        item_id = int(r[0])
        item_group_id = group_by_item.get(item_id)
        if selected_group_ids is not None:
            if item_group_id is None or str(item_group_id) not in selected_group_ids:
                continue
        rows.append({
            "sku": str(r[1] or "").strip(),
            "name": str(r[2] or "").strip(),
            "price": float(r[3]) if r[3] is not None else 0.0,
            "stock": stock_by_item.get(item_id, 0),
            "picture_blob": b"",
            "picture_path": "",
            "erp_images": [],
            "erp_image_count": 0,
            "is_variant": False,
            "_item_id": item_id,
            "_item_group_id": item_group_id,
        })
    return rows


def _resolve_existing_sepidar_product_id(wcapi, sku: str, product_map: dict):
    """معادلِ محلیِ resolve_existing_product_id دژاوو — عمداً reuse نشده،
    چون اون تابع داخلش چندجا save_product_woo_map (فایلِ دژاوو) رو هاردکد
    صدا می‌زنه، حتی وقتی یک product_map دلخواه بهش پاس بدیم؛ اگه با
    نگاشتِ سپیدار صداش بزنیم، بی‌سروصدا رویِ product_woo_map.jsonِ دژاوو
    می‌نوشت. این‌جا فقط توابعِ خواندنیِ بی‌اثرش (fetch_product_by_id/
    find_product_by_sku/_is_active_wc_product) reuse می‌شن؛ ذخیره‌سازی
    فقط یک‌بار توسطِ خودِ صداکننده (رویِ sepidar_product_map.json) انجام
    می‌شه."""
    from sync_app.core.product_woo_map_helper import fetch_product_by_id, find_product_by_sku, _is_active_wc_product

    sku = str(sku or "").strip()
    if not sku:
        return None, product_map

    cached = product_map.get(sku)
    if cached:
        info = fetch_product_by_id(wcapi, int(cached))
        if info and _is_active_wc_product(info):
            return int(info["id"]), product_map
        product_map.pop(sku, None)

    hit = find_product_by_sku(wcapi, sku)
    if hit and hit.get("id") and _is_active_wc_product(hit):
        pid = int(hit["id"])
        product_map[sku] = pid
        return pid, product_map

    return None, product_map


def _resolve_sepidar_product_category(item_group_id, groups_by_id: dict, erp_to_wc_category: dict):
    """نزدیک‌ترین دسته‌بندیِ سینک‌شده برایِ گروهِ کالا — اگه خودِ گروه هنوز
    به سایت سینک نشده، زنجیره‌یِ والدها رو بالا می‌ره (رویِ نگاشتِ
    erp_to_wcِ فازِ ۱، سپیدار→سایت)."""
    from sync_app.core.scripts.sepidar.sepidar_categorysync import _ROOT_PARENT_REF

    if item_group_id is None:
        return None
    cur = str(item_group_id)
    seen: set[str] = set()
    depth = 0
    while cur in groups_by_id and cur not in seen and depth < 20:
        seen.add(cur)
        try:
            if int(cur) in erp_to_wc_category:
                return erp_to_wc_category[int(cur)]
        except (TypeError, ValueError):
            pass
        parent_ref = groups_by_id[cur].get("parent_ref")
        parent_key = str(parent_ref) if parent_ref is not None else None
        if parent_key is None or parent_key == str(_ROOT_PARENT_REF):
            break
        cur = parent_key
        depth += 1
    return None


def build_sepidar_products_sync_preview(config: dict | None = None) -> list:
    """معادلِ build_products_sync_previewِ دژاوو (product_sync_guard.py) —
    قبل از ارسالِ واقعی، به کاربر نشون می‌ده چی قراره سینک بشه."""
    from sync_app.core.product_sync_guard import ProductSyncPreviewRow
    from sync_app.core.scripts.sepidar.sepidar_categorysync import (
        fetch_sepidar_item_groups,
        _reconcile_sepidar_category_map,
    )

    config = config or {}
    selected = [str(g).strip() for g in config.get("SEPIDAR_SELECTED_GROUPS", []) if str(g).strip()]
    if not selected:
        return []

    groups = fetch_sepidar_item_groups(config)
    scope_ids = _expand_sepidar_groups_with_descendants(selected, groups)
    items = fetch_sepidar_products_for_sync(config, selected_group_ids=scope_ids)
    if not items:
        return []

    groups_by_id = {str(g["id"]): g for g in groups}
    erp_to_wc_category = _reconcile_sepidar_category_map(config)
    product_map = load_sepidar_map(_MAP_FILE)

    previews = []
    for item in items:
        sku = item["sku"]
        if not sku:
            continue
        wc_id = int(product_map.get(sku) or 0) or None
        wc_cat_id = _resolve_sepidar_product_category(item.get("_item_group_id"), groups_by_id, erp_to_wc_category)
        notes = []
        if not wc_id:
            notes.append("هنوز در نگاشتِ سپیدار ثبت نشده — ممکن است با SKU در سایت پیدا شود یا محصول جدید ساخته شود")
        previews.append(
            ProductSyncPreviewRow(
                erp_sku=sku,
                erp_name=item["name"] or sku,
                price=str(int(item["price"])) if item["price"] else "0",
                stock=item["stock"],
                category_label=str(wc_cat_id) if wc_cat_id else "—",
                wc_id=wc_id,
                wc_label=f"Woo #{wc_id}" if wc_id else "",
                manual_link=False,
                notes=notes,
            )
        )
    return previews


def sync_products_from_erp(config: dict | None = None) -> dict:
    """POS.Item → محصولِ سایت. جهتِ درستِ ERP→سایت (مثلِ
    sync_fullproduct.mainِ دژاوو). خروجی: {"ok","failed","failed_skus",
    "total"} — سازگار با tab_products.py’s _products_sync_done بدونِ
    تغییر. بدونِ ThreadPoolExecutor/کشِ hashِ دژاوو (سادگیِ فازِ ۲؛
    می‌تونه فازِ بعدی بهینه بشه)."""
    from sync_app.core.integrations.commerce_provider import build_store_api
    from sync_app.core.scripts.sepidar.sepidar_categorysync import (
        fetch_sepidar_item_groups,
        _reconcile_sepidar_category_map,
    )
    from sync_app.core.sync_utils import log

    config = config or {}
    selected = [str(g).strip() for g in config.get("SEPIDAR_SELECTED_GROUPS", []) if str(g).strip()]
    if not selected:
        return {"ok": 0, "failed": 0, "failed_skus": [], "total": 0}

    groups = fetch_sepidar_item_groups(config)
    scope_ids = _expand_sepidar_groups_with_descendants(selected, groups)
    items = fetch_sepidar_products_for_sync(config, selected_group_ids=scope_ids)
    if not items:
        log.info("ℹ️ هیچ کالایی در گروه‌هایِ انتخاب‌شده‌یِ سپیدار یافت نشد.")
        return {"ok": 0, "failed": 0, "failed_skus": [], "total": 0}

    groups_by_id = {str(g["id"]): g for g in groups}
    erp_to_wc_category = _reconcile_sepidar_category_map(config)
    product_map = load_sepidar_map(_MAP_FILE)
    wcapi = build_store_api(config)

    from sync_app.core.article_price import apply_price_markup
    from sync_app.core.stock_mode import resolve_stock_mode, apply_stock_mode_to_payload

    ok = 0
    failed_skus: list[str] = []

    for item in items:
        sku = item["sku"]
        if not sku:
            continue
        try:
            existing_id, product_map = _resolve_existing_sepidar_product_id(wcapi, sku, product_map)
            wc_cat_id = _resolve_sepidar_product_category(item.get("_item_group_id"), groups_by_id, erp_to_wc_category)
            group_code = str(item.get("_item_group_id") or "")
            price = apply_price_markup(item["price"], config, is_sale=False, sku=sku)
            payload = {
                "name": item["name"] or sku,
                "sku": sku,
                "regular_price": str(int(price)) if price else "0",
                "status": "publish",
            }
            stock_mode = resolve_stock_mode(sku, group_code, config)
            apply_stock_mode_to_payload(payload, stock_mode, int(item["stock"]))
            if wc_cat_id:
                payload["categories"] = [{"id": int(wc_cat_id)}]

            if existing_id:
                wcapi.put(f"products/{existing_id}", payload)
                new_id = existing_id
            else:
                resp = wcapi.post("products", payload)
                data = resp.json() if hasattr(resp, "json") else None
                new_id = data.get("id") if isinstance(data, dict) else None
                if not new_id:
                    raise RuntimeError(f"ایجادِ محصول ناموفق: {data}")

            product_map[sku] = int(new_id)
            ok += 1
        except Exception as exc:
            log.error(f"❌ خطا در سینکِ محصولِ '{sku}': {exc}")
            failed_skus.append(sku)

    save_sepidar_map(_MAP_FILE, product_map)
    log.info(f"✅ محصولِ سپیدار (ERP→سایت): {ok} از {len(items)} سینک شد.")
    return {"ok": ok, "failed": len(failed_skus), "failed_skus": failed_skus, "total": len(items)}


def main(config: dict | None = None) -> dict:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config or load_secure_config(None) or {}
    return sync_products_from_erp(cfg)


if __name__ == "__main__":
    main()
