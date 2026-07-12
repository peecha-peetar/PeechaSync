"""
Site Health — بررسی وضعیت فنی فروشگاه:
SSL، سرعت پاسخ سایت، سلامت API ووکامرس، اتصال SQL، و لینک‌های کلیدی سایت.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class HealthCheckResult:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "warning"  # "critical" | "warning" | "info"


def check_ssl(url: str) -> HealthCheckResult:
    """آیا سایت روی HTTPS با گواهی معتبر بالا میاد؟"""
    import requests

    url = (url or "").strip()
    if not url:
        return HealthCheckResult("SSL", False, "آدرس سایت تنظیم نشده.", "critical")
    if not url.startswith("https://"):
        return HealthCheckResult("SSL", False, f"آدرس سایت با https شروع نمی‌شود: {url}", "critical")
    try:
        resp = requests.get(url, timeout=10, verify=True)
        if resp.status_code < 500:
            return HealthCheckResult("SSL", True, "گواهی SSL معتبر است و سایت با HTTPS بالا می‌آید.")
        return HealthCheckResult("SSL", False, f"سایت با کد {resp.status_code} پاسخ داد.", "warning")
    except requests.exceptions.SSLError as exc:
        return HealthCheckResult("SSL", False, f"گواهی SSL نامعتبر/منقضی است: {exc}", "critical")
    except Exception as exc:
        return HealthCheckResult("SSL", False, f"اتصال به سایت ناموفق بود: {exc}", "critical")


def check_site_speed(url: str) -> HealthCheckResult:
    """زمان پاسخ صفحه‌ی اصلی سایت."""
    import requests

    url = (url or "").strip()
    if not url:
        return HealthCheckResult("سرعت سایت", False, "آدرس سایت تنظیم نشده.", "critical")
    try:
        start = time.time()
        requests.get(url, timeout=15)
        elapsed = time.time() - start
        if elapsed < 1.5:
            return HealthCheckResult("سرعت سایت", True, f"{elapsed:.2f} ثانیه — خوب", "info")
        if elapsed < 4.0:
            return HealthCheckResult("سرعت سایت", True, f"{elapsed:.2f} ثانیه — قابل قبول", "warning")
        return HealthCheckResult("سرعت سایت", False, f"{elapsed:.2f} ثانیه — کند", "warning")
    except Exception as exc:
        return HealthCheckResult("سرعت سایت", False, f"اندازه‌گیری ناموفق بود: {exc}", "critical")


def check_wc_api(config: dict) -> HealthCheckResult:
    """آیا کلیدهای API ووکامرس معتبرند و پاسخ می‌دن؟"""
    from sync_app.core.wc_sync_helper import build_wcapi, apply_network_overrides

    try:
        apply_network_overrides(config)
        wcapi = build_wcapi(config)
        resp = wcapi.get("products", params={"per_page": 1, "_fields": "id"})
        if resp.status_code == 200:
            return HealthCheckResult("API ووکامرس", True, "اتصال و احراز هویت API موفق بود.")
        if resp.status_code in (401, 403):
            return HealthCheckResult("API ووکامرس", False, "کلید API نامعتبر یا دسترسی کافی ندارد.", "critical")
        return HealthCheckResult("API ووکامرس", False, f"پاسخ غیرمنتظره: کد {resp.status_code}", "warning")
    except Exception as exc:
        return HealthCheckResult("API ووکامرس", False, f"اتصال ناموفق بود: {exc}", "critical")


def check_sql_connection(config: dict) -> HealthCheckResult:
    """آیا اتصال به SQL Server (ERP) برقرار می‌شود؟"""
    from sync_app.core.sql_connection_helper import open_sql_connection

    try:
        conn, _, _ = open_sql_connection(config, timeout=8)
        conn.close()
        return HealthCheckResult("اتصال SQL", True, "اتصال به دیتابیس ERP برقرار است.")
    except Exception as exc:
        return HealthCheckResult("اتصال SQL", False, f"اتصال ناموفق بود: {exc}", "critical")


def check_key_pages(url: str) -> list[HealthCheckResult]:
    """چک کردن چند صفحه‌ی کلیدی فروشگاه (فروشگاه/سبد خرید) برای لینک شکسته."""
    import requests

    url = (url or "").strip().rstrip("/")
    if not url:
        return [HealthCheckResult("صفحات کلیدی", False, "آدرس سایت تنظیم نشده.", "critical")]

    pages = {
        "صفحه‌ی اصلی": url,
        "فروشگاه (shop)": f"{url}/shop",
        "سبد خرید (cart)": f"{url}/cart",
    }
    results = []
    for label, page_url in pages.items():
        try:
            resp = requests.get(page_url, timeout=10, allow_redirects=True)
            ok = resp.status_code < 400
            results.append(
                HealthCheckResult(
                    label, ok,
                    f"کد پاسخ: {resp.status_code}",
                    "info" if ok else "warning",
                )
            )
        except Exception as exc:
            results.append(HealthCheckResult(label, False, f"خطا: {exc}", "warning"))
    return results


def run_all_checks(config: dict) -> list[HealthCheckResult]:
    """اجرای همه‌ی چک‌های سلامت سایت — این تابع کند است (چند درخواست شبکه)، در Thread پس‌زمینه صدا بزنید."""
    url = str(config.get("WC_URL") or "").strip()
    results = []
    results.append(check_sql_connection(config))
    results.append(check_wc_api(config))
    results.append(check_ssl(url))
    results.append(check_site_speed(url))
    results.extend(check_key_pages(url))
    return results


def overall_health_score(results: list[HealthCheckResult]) -> int:
    if not results:
        return 0
    weights = {"critical": 3, "warning": 1, "info": 1}
    total_weight = sum(weights.get(r.severity, 1) for r in results)
    passed_weight = sum(weights.get(r.severity, 1) for r in results if r.ok)
    if total_weight == 0:
        return 0
    return round(passed_weight / total_weight * 100)
