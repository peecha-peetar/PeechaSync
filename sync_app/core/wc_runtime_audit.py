"""ممیزی مسیر WC_URL — ثابت می‌کند درخواست Woo از تنظیمات خوانده می‌شود."""

from __future__ import annotations

from sync_app.core.wc_api_helper import (
    get_wc_auth,
    normalize_wc_store_url,
    wc_endpoint,
    wc_store_host,
)
from sync_app.core.wc_site_profiles import (
    find_wc_site,
    get_active_site_id,
    get_wc_sites,
    site_display_label,
)

# فقط این ماژول‌ها مجازند WC را بسازند — peecha.ir نباید در URL نهایی باشد مگر در config
_WC_URL_BUILDERS = (
    "sync_app.core.wc_api_helper.wc_endpoint",
    "sync_app.core.wc_sync_helper.wc_rest_request",
    "sync_app.core.connectivity_service._wc_probe_urls",
)


def audit_wc_runtime(config: dict | None) -> dict:
    """خلاصه منبع واقعی اتصال Woo برای نمایش به کاربر یا تست."""
    cfg = dict(config or {})
    sites = get_wc_sites(cfg)
    active_id = get_active_site_id(cfg)
    active = find_wc_site(sites, active_id) if active_id else None

    wc_url = str(cfg.get("WC_URL") or "").strip()
    base = normalize_wc_store_url(wc_url)
    host = wc_store_host(cfg)
    ck, cs = get_wc_auth(cfg)

    probe_settings = wc_endpoint(wc_url, "settings/general/woocommerce_currency")
    probe_categories = wc_endpoint(wc_url, "products/categories")

    peecha_in_url = "peecha.ir" in (wc_url + base + probe_settings + probe_categories).lower()

    return {
        "active_site_id": active_id,
        "active_site_label": site_display_label(active) if active else "",
        "wc_url": wc_url,
        "wc_base": base,
        "wc_host": host,
        "consumer_key_prefix": (ck[:10] + "...") if ck else "",
        "has_consumer_secret": bool(cs),
        "probe_settings_url": probe_settings,
        "probe_categories_url": probe_categories,
        "sites_count": len(sites),
        "sites_labels": [site_display_label(s) for s in sites],
        "peecha_in_wc_url": peecha_in_url,
        "url_builders": list(_WC_URL_BUILDERS),
    }


def format_wc_audit_report(audit: dict) -> str:
    a = audit or {}
    lines = [
        "═══ ممیزی مسیر ووکامرس ═══",
        f"سایت فعال: {a.get('active_site_label') or '—'} (id={a.get('active_site_id') or '—'})",
        f"WC_URL ذخیره‌شده: {a.get('wc_url') or '—'}",
        f"هاست: {a.get('wc_host') or '—'}",
        f"Consumer Key: {a.get('consumer_key_prefix') or 'خالی'}",
        f"تعداد پروفایل‌ها: {a.get('sites_count', 0)}",
    ]
    if a.get("sites_labels"):
        lines.append("پروفایل‌ها: " + " | ".join(a["sites_labels"]))
    lines.extend(
        [
            "",
            "URLهای واقعی درخواست (ساخته‌شده از WC_URL):",
            f"  • تست تنظیمات: {a.get('probe_settings_url') or '—'}",
            f"  • API دسته‌ها: {a.get('probe_categories_url') or '—'}",
            "",
        ]
    )
    if a.get("peecha_in_wc_url"):
        lines.append("⚠️ peecha.ir در WC_URL فعال دیده می‌شود — چون شما آن را در تنظیمات انتخاب کرده‌اید.")
    else:
        lines.append("✅ peecha.ir در WC_URL فعال نیست — درخواست‌ها به همان آدرسی می‌روند که در تب تنظیمات است.")
    lines.append("")
    lines.append("تب لایسنس/بروزرسانی جداست (LICENSE_SERVER_URL) و ربطی به همگام‌سازی Woo ندارد.")
    return "\n".join(lines)
