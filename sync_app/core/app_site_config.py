"""خواندن نام و آدرس سایت فعال از تنظیمات — بدون fallback هاردکد فروشگاه."""

from __future__ import annotations

from sync_app.core.network_route_check import host_from_url
from sync_app.core.wc_site_profiles import (
    ensure_wc_sites,
    find_wc_site,
    get_active_site_id,
    get_wc_sites,
    site_display_label,
)

THEME_UI_LABELS = {
    "navy": "سورمه‌ای",
    "red": "قرمز",
    "green": "سبز",
}


def resolved_store_config(config=None) -> dict:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = dict(config or load_secure_config(None) or {})
    return ensure_wc_sites(cfg)


def get_active_store_site(config=None) -> dict | None:
    cfg = resolved_store_config(config)
    sites = get_wc_sites(cfg)
    active_id = get_active_site_id(cfg)
    return find_wc_site(sites, active_id) if active_id else None


def get_store_display_name(config=None) -> str:
    """نام فروشگاه فعال — از label سایت در تب تنظیمات یا هاست WC_URL."""
    site = get_active_store_site(config)
    if site:
        label = site_display_label(site)
        url = str(site.get("url") or "").strip()
        if label and label not in ("سایت جدید", ""):
            return label
        host = host_from_url(url, default="")
        if host:
            return host

    cfg = resolved_store_config(config)
    host = host_from_url(str(cfg.get("WC_URL") or "").strip(), default="")
    return host or "فروشگاه"


def get_app_window_title(config=None) -> str:
    from sync_app.core.app_version import app_version_label

    name = get_store_display_name(config)
    return f"{name} — همگام‌سازی هوشمند ({app_version_label()})"


def get_app_header_subtitle(config=None) -> str:
    from sync_app.core.user_profile import get_current_profile_display_name

    store = get_store_display_name(config)
    profile_name = get_current_profile_display_name()
    if profile_name:
        return f"{store} — کاربر: {profile_name}"
    return f"همگام‌سازی هوشمند — {store}"


def get_theme_ui_label(theme_key: str) -> str:
    return THEME_UI_LABELS.get(str(theme_key or "").strip(), str(theme_key or "سورمه‌ای"))
