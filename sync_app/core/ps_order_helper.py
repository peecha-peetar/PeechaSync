"""
سفارشات پرداخت‌شده‌ی پرستاشاپ — نگاشت به همون شکل order (billing +
line_items) که ordersync.py برای ووکامرس انتظار داره، تا منطق تطبیق
واریانت/درج فاکتور در ERP بین دو پلتفرم مشترک بمونه.

فقط سفارش‌های valid=1 (پرداخت انجام‌شده) خونده می‌شن — طبق تصمیم کاربر،
چون current_state روی پرستاشاپ برخلاف status ووکامرس یک عدد قابل‌تنظیم
توسط خودِ فروشگاهه و معادل ثابتی نداره.
"""

from __future__ import annotations

from sync_app.core.ps_sync_helper import (
    _response_json,
    _unwrap_dict,
    _unwrap_list,
    ps_call,
    ps_rest_request,
)

_PAGE_SIZE = 100


def _order_rows(entry: dict) -> list[dict]:
    assoc = entry.get("associations") or {}
    rows = assoc.get("order_rows") or []
    return [r for r in rows if isinstance(r, dict)]


def _order_row_to_line_item(row: dict) -> dict:
    try:
        qty = float(row.get("product_quantity") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    try:
        unit_price = float(row.get("unit_price_tax_excl") or 0)
    except (TypeError, ValueError):
        unit_price = 0.0
    try:
        product_id = int(row.get("product_id") or 0)
    except (TypeError, ValueError):
        product_id = 0
    try:
        variation_id = int(row.get("product_attribute_id") or 0)
    except (TypeError, ValueError):
        variation_id = 0
    return {
        "sku": str(row.get("product_reference") or "").strip(),
        "name": str(row.get("product_name") or "").strip(),
        "quantity": qty,
        "price": unit_price,
        "subtotal": unit_price * qty,
        "meta_data": [],
        # هم‌شکلِ خطِ سفارشِ ووکامرس (product_id/variation_id) — برایِ
        # تطبیقِ ساختاریِ «سایت متغیر/ERP ساده» در ordersync.py.
        "product_id": product_id,
        "variation_id": variation_id,
    }


def ps_get_order(config, order_id: int, *, timeout=None) -> dict | None:
    """سفارش کامل با خطوط — شکل {id, customer_id, billing, line_items}."""
    from sync_app.core.ps_customer_helper import ps_get_customer

    cfg = config or {}
    resp = ps_call(
        f"دریافت سفارش #{order_id}",
        lambda: ps_rest_request(
            cfg, "GET", f"orders/{int(order_id)}",
            params={"display": "full"},
            timeout=timeout,
        ),
    )
    if getattr(resp, "status_code", 0) == 404:
        return None
    data = _response_json(resp, f"دریافت سفارش #{order_id}")
    entry = _unwrap_dict(data, "order")
    if not entry.get("id"):
        return None

    customer_id = int(entry.get("id_customer") or 0)
    billing = {}
    if customer_id:
        try:
            customer = ps_get_customer(cfg, customer_id, timeout=timeout)
            if customer:
                billing = dict(customer.get("billing") or {})
        except Exception:
            billing = {}

    return {
        "id": int(entry.get("id") or 0),
        "customer_id": customer_id,
        "billing": billing,
        "line_items": [_order_row_to_line_item(row) for row in _order_rows(entry)],
    }


def ps_list_paid_order_ids(config, *, timeout=None) -> list[int]:
    """id سفارش‌های valid=1 — بدون واکشی جزئیات (سبک، برای لیست/شمارش)."""
    cfg = config or {}
    out: list[int] = []
    offset = 0
    while True:
        resp = ps_call(
            f"دریافت سفارش‌های پرداخت‌شده offset={offset}",
            lambda o=offset: ps_rest_request(
                cfg, "GET", "orders",
                params={"filter[valid]": "[1]", "limit": f"{o},{_PAGE_SIZE}"},
                timeout=timeout,
            ),
        )
        data = _response_json(resp, "دریافت سفارش‌ها")
        rows = _unwrap_list(data, "orders")
        if not rows:
            break
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                try:
                    out.append(int(row["id"]))
                except (TypeError, ValueError):
                    continue
        if len(rows) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return out


def ps_list_recent_orders_preview(config, *, limit: int = 20, timeout=None) -> list[dict]:
    """آخرین سفارش‌ها (هر وضعیتی) — برای پیش‌نمایش تب سفارشات، نه sync واقعی."""
    cfg = config or {}
    resp = ps_call(
        "دریافت سفارش‌های اخیر",
        lambda: ps_rest_request(
            cfg, "GET", "orders",
            params={"limit": f"0,{int(limit)}", "sort": "id_DESC", "display": "full"},
            timeout=timeout,
        ),
    )
    data = _response_json(resp, "دریافت سفارش‌های اخیر")
    rows = _unwrap_list(data, "orders")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        out.append({
            "id": int(row["id"]),
            "valid": str(row.get("valid") or "0") == "1",
            "total_paid": row.get("total_paid") or "0",
            "customer_id": int(row.get("id_customer") or 0),
            "date_add": str(row.get("date_add") or "")[:10],
        })
    return out


def ps_list_orders_for_sales_report(config, *, since_days: int | None = None, timeout=None) -> list[dict]:
    """سفارش‌های valid=1 به شکل {id, date_created, total, line_items:[{sku,quantity,total,name}]} —
    همون شکلی که sales_report_helper.build_sales_report برای ووکامرس هم انتظار داره.

    ⚠️ پرستاشاپ فیلتر بازه‌ی تاریخ سروری‌ای که با اطمینان تأیید شده باشه نداره
    (برخلاف since_days ووکامرس که با after= سمت سرور فیلتر می‌شه) — همه‌ی
    سفارش‌های valid=1 خونده می‌شن و فیلتر since_days سمت کلاینت اعمال می‌شه.
    برای فروشگاه‌های با تاریخچه‌ی خیلی بزرگ این کندتره؛ فعلاً به‌خاطر عدم
    اطمینان از سینتکس فیلتر تاریخ Webservice، به حدس زدن ترجیح داده شده.
    """
    from datetime import datetime, timedelta

    cfg = config or {}
    cutoff = None
    if since_days:
        cutoff = (datetime.now() - timedelta(days=int(since_days))).strftime("%Y-%m-%d")

    out: list[dict] = []
    for order_id in ps_list_paid_order_ids(cfg, timeout=timeout):
        resp = ps_call(
            f"دریافت سفارش #{order_id} (گزارش فروش)",
            lambda oid=order_id: ps_rest_request(
                cfg, "GET", f"orders/{oid}", params={"display": "full"}, timeout=timeout,
            ),
        )
        if getattr(resp, "status_code", 0) == 404:
            continue
        data = _response_json(resp, f"دریافت سفارش #{order_id}")
        entry = _unwrap_dict(data, "order")
        if not entry.get("id"):
            continue
        date_created = str(entry.get("date_add") or "")[:10]
        if cutoff and date_created and date_created < cutoff:
            continue
        try:
            total = float(entry.get("total_paid") or entry.get("total_paid_tax_incl") or 0)
        except (TypeError, ValueError):
            total = 0.0
        line_items = []
        for row in _order_rows(entry):
            item = _order_row_to_line_item(row)
            line_items.append({
                "sku": item["sku"], "name": item["name"],
                "quantity": item["quantity"], "total": item["subtotal"],
            })
        out.append({
            "id": int(entry["id"]), "date_created": date_created,
            "total": total, "line_items": line_items,
        })
    return out


def ps_list_paid_order_customer_ids(config, *, timeout=None) -> set[int]:
    """id_customer سفارش‌های valid=1 — بدون واکشی خطوط سفارش (برای پیش‌نمایش مشتریان)."""
    cfg = config or {}
    ids: set[int] = set()
    offset = 0
    while True:
        resp = ps_call(
            f"دریافت مشتریان سفارش‌دار offset={offset}",
            lambda o=offset: ps_rest_request(
                cfg, "GET", "orders",
                params={
                    "filter[valid]": "[1]",
                    "limit": f"{o},{_PAGE_SIZE}",
                    "display": "full",
                },
                timeout=timeout,
            ),
        )
        data = _response_json(resp, "دریافت سفارش‌ها")
        rows = _unwrap_list(data, "orders")
        if not rows:
            break
        for row in rows:
            if isinstance(row, dict):
                cid = int(row.get("id_customer") or 0)
                if cid > 0:
                    ids.add(cid)
        if len(rows) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return ids


def ps_list_paid_orders(config, *, timeout=None) -> list[dict]:
    """سفارش‌های valid=1 با جزئیات کامل (billing + line_items)."""
    cfg = config or {}
    orders = []
    for order_id in ps_list_paid_order_ids(cfg, timeout=timeout):
        order = ps_get_order(cfg, order_id, timeout=timeout)
        if order:
            orders.append(order)
    return orders
