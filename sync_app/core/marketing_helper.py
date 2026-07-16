"""
Marketing Manager — تحلیل فروش و پیشنهادهای بازاریابی، بر پایه‌ی ترکیب
موجودی SQL (ERP) و آمار فروش واقعی ووکامرس (sales_report_helper).
همه‌ی پیشنهادها قالب‌محور (rule-based) هستند، نه هوش مصنوعی واقعی.
"""

from __future__ import annotations

from dataclasses import dataclass

from sync_app.core.jalali_log_formatter import gregorian_to_jalali


@dataclass
class ProductMarketingInfo:
    sku: str
    name: str
    stock: int = 0
    qty_sold: int = 0
    revenue: float = 0.0
    last_sale_date: str = ""


def build_marketing_infos(sql_products: list[dict], sales_report) -> list[ProductMarketingInfo]:
    """
    sql_products: [{"sku":..., "name":..., "stock":...}, ...] از دیتابیس محلی
    sales_report: خروجی sales_report_helper.load_sales_report()/build_sales_report()
    """
    infos = []
    by_sku = sales_report.by_sku if sales_report else {}
    for p in sql_products:
        sku = str(p.get("sku") or "").strip()
        stat = by_sku.get(sku)
        infos.append(
            ProductMarketingInfo(
                sku=sku,
                name=str(p.get("name") or "").strip(),
                stock=int(p.get("stock") or 0),
                qty_sold=stat.qty_sold if stat else 0,
                revenue=stat.revenue if stat else 0.0,
                last_sale_date=stat.last_sale_date if stat else "",
            )
        )
    return infos


def no_sale_products(infos: list[ProductMarketingInfo]) -> list[ProductMarketingInfo]:
    """محصولات بدون هیچ فروشی — که هنوز موجودی هم دارن (یعنی واقعاً قابل‌فروشن)."""
    return sorted(
        [i for i in infos if i.qty_sold == 0 and i.stock > 0],
        key=lambda i: i.stock, reverse=True,
    )


def best_sellers(infos: list[ProductMarketingInfo], n: int = 15) -> list[ProductMarketingInfo]:
    return sorted(infos, key=lambda i: i.qty_sold, reverse=True)[:n]


def high_stock_low_sales(
    infos: list[ProductMarketingInfo], *, stock_threshold: int = 20, sales_threshold: int = 2
) -> list[ProductMarketingInfo]:
    """موجودی بالا ولی فروش پایین — نامزد تخفیف/کمپین."""
    return sorted(
        [i for i in infos if i.stock >= stock_threshold and i.qty_sold <= sales_threshold],
        key=lambda i: i.stock, reverse=True,
    )


def low_stock_warning(
    infos: list[ProductMarketingInfo], *, stock_threshold: int = 5
) -> list[ProductMarketingInfo]:
    """نزدیک اتمام موجودی — ولی هنوز فروش هم داره (یعنی نیاز واقعی به شارژ موجودیه)."""
    return sorted(
        [i for i in infos if 0 < i.stock <= stock_threshold and i.qty_sold > 0],
        key=lambda i: i.stock,
    )


def suggest_action(info: ProductMarketingInfo) -> str:
    """پیشنهاد ساده و قالب‌محور برای یک محصول، بر اساس ترکیب موجودی/فروش."""
    if info.qty_sold == 0 and info.stock > 0:
        return "بدون فروش — پیشنهاد: تخفیف معرفی (١۵-٢۵٪) یا بررسی تصاویر/توضیحات/سئو"
    if info.stock >= 20 and info.qty_sold <= 2:
        return "موجودی بالا، فروش کم — پیشنهاد: تخفیف یا کمپین ویژه برای این محصول"
    if 0 < info.stock <= 5 and info.qty_sold > 0:
        return "موجودی رو به اتمام — پیشنهاد: سفارش تأمین مجدد قبل از تمام شدن"
    if info.qty_sold >= 10:
        return "پرفروش — پیشنهاد: تولید محتوا/پست شبکه‌ی اجتماعی برای این محصول"
    return ""


# ---------------------------------------------------------------------------
# تقویم مناسبتی تبلیغات (مناسبت‌های رایج فروشگاهی ایران)
# ---------------------------------------------------------------------------

SEASONAL_CALENDAR = [
    {"name": "شب یلدا", "jalali_month": 9, "note": "پیشنهاد کمپین/تخفیف شب یلدا"},
    {"name": "چهارشنبه‌سوری و نوروز", "jalali_month": 12, "note": "پیشنهاد کمپین تخفیف پایان سال / عیدانه"},
    {"name": "سیزده‌به‌در و فروردین", "jalali_month": 1, "note": "پیشنهاد کمپین شروع سال نو"},
    {"name": "روز مادر", "jalali_month": 12, "note": "پیشنهاد کمپین مناسبتی روز مادر (تقریبی)"},
    {"name": "بلک فرایدی", "jalali_month": 9, "note": "پیشنهاد تخفیف ویژه بلک فرایدی (آذرماه)"},
]


def current_jalali_month() -> int:
    import datetime

    now = datetime.datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return jm


def upcoming_occasions(window_months: int = 2) -> list[dict]:
    """مناسبت‌هایی که ماه جاری یا تا window_months ماه بعد قرار دارن (چرخشی روی ۱۲ ماه)."""
    current = current_jalali_month()
    result = []
    for occ in SEASONAL_CALENDAR:
        diff = (occ["jalali_month"] - current) % 12
        if diff <= window_months:
            result.append({**occ, "months_away": diff})
    return sorted(result, key=lambda o: o["months_away"])
