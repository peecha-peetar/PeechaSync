"""
تحلیل فروش از روی سفارشات ووکامرس (آنلاین، فقط فروش سایت).
چون گرفتن کل سفارشات به‌ازای هر ردیف محصول کند است، یک‌بار همه‌ی سفارشات
گرفته و در یک فایل محلی خلاصه/کش می‌شود؛ نمایش per-row از همین کش سریع خوانده می‌شود.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from sync_app.core.sync_utils import app_path

SALES_CACHE_FILE = "sales_report_cache.json"
_ORDER_STATUSES_COUNTED = ("completed", "processing", "on-hold")


@dataclass
class ProductSalesStat:
    sku: str = ""
    name: str = ""
    qty_sold: int = 0
    revenue: float = 0.0
    order_count: int = 0
    last_sale_date: str = ""


@dataclass
class SalesReport:
    generated_at: str = ""
    total_orders: int = 0
    total_revenue: float = 0.0
    by_sku: dict = field(default_factory=dict)  # sku -> ProductSalesStat
    monthly_revenue: dict = field(default_factory=dict)  # "YYYY-MM" -> revenue
    daily_revenue: dict = field(default_factory=dict)  # "YYYY-MM-DD" -> revenue

    def top_products(self, n: int = 10) -> list[ProductSalesStat]:
        return sorted(self.by_sku.values(), key=lambda s: s.revenue, reverse=True)[:n]

    def sorted_months(self) -> list[tuple[str, float]]:
        return sorted(self.monthly_revenue.items())


def _fetch_all_orders(wcapi, *, since_days: int | None = None, progress_cb=None) -> list[dict]:
    from sync_app.core.wc_sync_helper import wc_call

    orders: list[dict] = []
    page = 1
    params = {
        "per_page": 100,
        "status": ",".join(_ORDER_STATUSES_COUNTED),
        "_fields": "id,date_created,total,status,line_items",
    }
    if since_days:
        import datetime

        after = (datetime.datetime.now() - datetime.timedelta(days=since_days)).isoformat()
        params["after"] = after

    while True:
        page_params = dict(params, page=page)

        def _fetch(p=page_params):
            resp = wcapi.get("orders", params=p)
            data = resp.json()
            if not isinstance(data, list):
                raise RuntimeError(f"پاسخ نامعتبر سفارشات: {data}")
            return data

        batch = wc_call(wcapi, f"دریافت سفارشات صفحه {page}", _fetch, retries=1)
        if not batch:
            break
        orders.extend(batch)
        if progress_cb:
            progress_cb(len(orders))
        if len(batch) < 100:
            break
        page += 1
    return orders


def build_sales_report(config, *, since_days: int | None = None, progress_cb=None) -> SalesReport:
    """سفارشات فروشگاه (ووکامرس یا پرستاشاپ) را می‌گیرد و بر اساس SKU جمع می‌بندد."""
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        from sync_app.core.ps_order_helper import ps_list_orders_for_sales_report

        orders = ps_list_orders_for_sales_report(config, since_days=since_days)
        if progress_cb:
            progress_cb(len(orders))
    else:
        from sync_app.core.wc_sync_helper import apply_network_overrides, build_wcapi

        apply_network_overrides(config)
        wcapi = build_wcapi(config)
        orders = _fetch_all_orders(wcapi, since_days=since_days, progress_cb=progress_cb)

    report = SalesReport(generated_at=time.strftime("%Y-%m-%d %H:%M"))
    report.total_orders = len(orders)

    for order in orders:
        total = float(order.get("total") or 0)
        report.total_revenue += total
        order_date = str(order.get("date_created") or "")[:10]
        month_key = order_date[:7]  # "YYYY-MM"
        if month_key:
            report.monthly_revenue[month_key] = report.monthly_revenue.get(month_key, 0.0) + total
        if order_date:
            report.daily_revenue[order_date] = report.daily_revenue.get(order_date, 0.0) + total
        seen_skus_in_order: set[str] = set()

        for item in order.get("line_items") or []:
            sku_raw = str(item.get("sku") or "").strip()
            # واریانت‌ها را به کد اصلی کالا (قبل از -V) نگاشت کن تا فروش زیر یک SKU جمع شود
            sku = sku_raw.split("-V")[0].split("-v")[0] if sku_raw else ""
            if not sku:
                continue
            qty = int(item.get("quantity") or 0)
            line_total = float(item.get("total") or 0)
            name = str(item.get("name") or "").strip()

            stat = report.by_sku.get(sku)
            if stat is None:
                stat = ProductSalesStat(sku=sku, name=name)
                report.by_sku[sku] = stat

            stat.qty_sold += qty
            stat.revenue += line_total
            if not stat.name and name:
                stat.name = name
            if order_date > stat.last_sale_date:
                stat.last_sale_date = order_date
            if sku not in seen_skus_in_order:
                stat.order_count += 1
                seen_skus_in_order.add(sku)

    return report


def save_sales_report(report: SalesReport) -> None:
    payload = {
        "generated_at": report.generated_at,
        "total_orders": report.total_orders,
        "total_revenue": report.total_revenue,
        "monthly_revenue": report.monthly_revenue,
        "by_sku": {
            sku: {
                "sku": s.sku,
                "name": s.name,
                "qty_sold": s.qty_sold,
                "revenue": s.revenue,
                "order_count": s.order_count,
                "last_sale_date": s.last_sale_date,
            }
            for sku, s in report.by_sku.items()
        },
    }
    with open(app_path(SALES_CACHE_FILE), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def load_sales_report() -> SalesReport | None:
    try:
        with open(app_path(SALES_CACHE_FILE), "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None

    report = SalesReport(
        generated_at=payload.get("generated_at", ""),
        total_orders=int(payload.get("total_orders") or 0),
        total_revenue=float(payload.get("total_revenue") or 0),
        monthly_revenue=dict(payload.get("monthly_revenue") or {}),
    )
    for sku, s in (payload.get("by_sku") or {}).items():
        report.by_sku[sku] = ProductSalesStat(
            sku=s.get("sku", sku),
            name=s.get("name", ""),
            qty_sold=int(s.get("qty_sold") or 0),
            revenue=float(s.get("revenue") or 0),
            order_count=int(s.get("order_count") or 0),
            last_sale_date=s.get("last_sale_date", ""),
        )
    return report


def get_product_sales_stat(sku: str, report: SalesReport | None = None) -> ProductSalesStat:
    """آمار فروش یک محصول از کش — اگر کش نبود یا محصول در آن نبود، آمار صفر برمی‌گرداند."""
    rep = report if report is not None else load_sales_report()
    if rep is None:
        return ProductSalesStat(sku=sku)
    return rep.by_sku.get(sku, ProductSalesStat(sku=sku))
