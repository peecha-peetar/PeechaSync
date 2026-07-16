"""چند سایت ووکامرس — ذخیره پروفایل‌ها و اعمال سایت فعال روی کلیدهای WC_*."""

from __future__ import annotations

import copy
import uuid
from typing import Any
from urllib.parse import urlparse

WC_SITES_KEY = "WC_SITES"
ACTIVE_WC_SITE_ID_KEY = "ACTIVE_WC_SITE_ID"

_SITE_FIELDS = (
    "url",
    "consumer_key",
    "consumer_secret",
    "wp_username",
    "wp_app_password",
    "currency_is_toman",
)


def _new_site_id() -> str:
    return uuid.uuid4().hex[:12]


def _host_label(url: str) -> str:
    host = (urlparse((url or "").strip()).netloc or "").strip()
    if host.startswith("www."):
        host = host[4:]
    return host or "سایت جدید"


def site_display_label(site: dict | None) -> str:
    if not isinstance(site, dict):
        return "سایت جدید"
    label = str(site.get("label") or "").strip()
    if label:
        return label
    return _host_label(str(site.get("url") or ""))


def _site_from_flat(config: dict) -> dict:
    cfg = config or {}
    url = str(cfg.get("WC_URL") or "").strip()
    return {
        "id": _new_site_id(),
        "label": _host_label(url),
        "url": url,
        "consumer_key": str(cfg.get("WC_CONSUMER_KEY") or "").strip(),
        "consumer_secret": str(cfg.get("WC_CONSUMER_SECRET") or "").strip(),
        "wp_username": str(cfg.get("WP_USERNAME") or "").strip(),
        "wp_app_password": str(cfg.get("WP_APP_PASSWORD") or "").strip(),
        "currency_is_toman": bool(cfg.get("WC_CURRENCY_IS_TOMAN", True)),
    }


def _normalize_site(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    site_id = str(raw.get("id") or "").strip() or _new_site_id()
    url = str(raw.get("url") or raw.get("WC_URL") or "").strip()
    return {
        "id": site_id,
        "label": str(raw.get("label") or "").strip() or _host_label(url),
        "url": url,
        "consumer_key": str(raw.get("consumer_key") or raw.get("WC_CONSUMER_KEY") or "").strip(),
        "consumer_secret": str(
            raw.get("consumer_secret") or raw.get("WC_CONSUMER_SECRET") or ""
        ).strip(),
        "wp_username": str(raw.get("wp_username") or raw.get("WP_USERNAME") or "").strip(),
        "wp_app_password": str(
            raw.get("wp_app_password") or raw.get("WP_APP_PASSWORD") or ""
        ).strip(),
        "currency_is_toman": bool(
            raw.get("currency_is_toman", raw.get("WC_CURRENCY_IS_TOMAN", True))
        ),
    }


def get_wc_sites(config: dict | None) -> list[dict]:
    cfg = config or {}
    sites_raw = cfg.get(WC_SITES_KEY)
    if not isinstance(sites_raw, list):
        return []
    sites: list[dict] = []
    for item in sites_raw:
        site = _normalize_site(item)
        if site is not None:
            sites.append(site)
    return sites


def get_active_site_id(config: dict | None) -> str:
    return str((config or {}).get(ACTIVE_WC_SITE_ID_KEY) or "").strip()


def find_wc_site(sites: list[dict], site_id: str) -> dict | None:
    sid = (site_id or "").strip()
    if not sid:
        return None
    for site in sites:
        if str(site.get("id") or "") == sid:
            return site
    return None


def apply_site_to_flat_keys(config: dict, site: dict | None) -> None:
    """کلیدهای WC_* و WP_* را از یک پروفایل سایت پر می‌کند."""
    cfg = config
    if not isinstance(site, dict):
        return
    cfg["WC_URL"] = str(site.get("url") or "").strip()
    cfg["WC_CONSUMER_KEY"] = str(site.get("consumer_key") or "").strip()
    cfg["WC_CONSUMER_SECRET"] = str(site.get("consumer_secret") or "").strip()
    cfg["WP_USERNAME"] = str(site.get("wp_username") or "").strip()
    cfg["WP_APP_PASSWORD"] = str(site.get("wp_app_password") or "").strip()
    cfg["WC_CURRENCY_IS_TOMAN"] = bool(site.get("currency_is_toman", True))


def ensure_wc_sites(config: dict | None) -> dict:
    """مهاجرت از فرمت تک‌سایته و هم‌تراز کردن کلیدهای فعال."""
    cfg = dict(config or {})
    sites = get_wc_sites(cfg)
    active_id = get_active_site_id(cfg)

    if not sites:
        flat_url = str(cfg.get("WC_URL") or "").strip()
        flat_ck = str(cfg.get("WC_CONSUMER_KEY") or "").strip()
        if flat_url or flat_ck:
            site = _site_from_flat(cfg)
            sites = [site]
            active_id = site["id"]
        else:
            sites = []
            active_id = ""

    if active_id and not find_wc_site(sites, active_id):
        active_id = str(sites[0]["id"]) if sites else ""

    cfg[WC_SITES_KEY] = sites
    cfg[ACTIVE_WC_SITE_ID_KEY] = active_id

    active = find_wc_site(sites, active_id)
    if active:
        apply_site_to_flat_keys(cfg, active)

    return cfg


def site_from_form(
    *,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    wp_username: str,
    wp_app_password: str,
    currency_is_toman: bool,
    site_id: str = "",
    label: str = "",
) -> dict:
    url = (url or "").strip()
    site = {
        "id": (site_id or "").strip() or _new_site_id(),
        "label": (label or "").strip() or _host_label(url),
        "url": url,
        "consumer_key": (consumer_key or "").strip(),
        "consumer_secret": (consumer_secret or "").strip(),
        "wp_username": (wp_username or "").strip(),
        "wp_app_password": (wp_app_password or "").strip(),
        "currency_is_toman": bool(currency_is_toman),
    }
    return site


def merge_form_into_site(
    site: dict,
    *,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    wp_username: str,
    wp_app_password: str,
    currency_is_toman: bool,
    preserve_secrets: bool = True,
) -> dict:
    """فرم را در پروفایل ادغام می‌کند؛ فیلدهای خالی رمز را نگه می‌دارد."""
    merged = dict(site or {})
    merged["url"] = (url or "").strip()
    if (consumer_key or "").strip():
        merged["consumer_key"] = consumer_key.strip()
    elif not preserve_secrets:
        merged["consumer_key"] = ""
    if (consumer_secret or "").strip():
        merged["consumer_secret"] = consumer_secret.strip()
    elif not preserve_secrets:
        merged["consumer_secret"] = ""
    merged["wp_username"] = (wp_username or "").strip()
    if (wp_app_password or "").strip():
        merged["wp_app_password"] = wp_app_password.strip()
    elif not preserve_secrets:
        merged["wp_app_password"] = ""
    merged["currency_is_toman"] = bool(currency_is_toman)
    if not str(merged.get("label") or "").strip():
        merged["label"] = _host_label(merged.get("url") or "")
    return merged


def sync_sites_to_config(
    config: dict,
    sites: list[dict],
    active_site_id: str,
    *,
    form_site: dict | None = None,
) -> dict:
    """لیست سایت‌ها و سایت فعال را در config ذخیره و کلیدهای WC_* را به‌روز می‌کند."""
    cfg = dict(config or {})
    normalized: list[dict] = []
    seen: set[str] = set()
    active_id = (active_site_id or "").strip()

    for item in sites or []:
        site = _normalize_site(item)
        if site is None:
            continue
        sid = str(site["id"])
        if sid in seen:
            continue
        seen.add(sid)
        normalized.append(site)

    if form_site:
        fs = _normalize_site(form_site)
        if fs:
            replaced = False
            for idx, site in enumerate(normalized):
                if str(site.get("id")) == fs["id"]:
                    normalized[idx] = fs
                    replaced = True
                    break
            if not replaced:
                normalized.append(fs)
            active_id = fs["id"]

    if active_id and not find_wc_site(normalized, active_id):
        active_id = str(normalized[0]["id"]) if normalized else ""

    cfg[WC_SITES_KEY] = normalized
    cfg[ACTIVE_WC_SITE_ID_KEY] = active_id

    active = find_wc_site(normalized, active_id)
    if active:
        apply_site_to_flat_keys(cfg, active)

    return cfg


def create_empty_site(*, label: str = "") -> dict:
    return {
        "id": _new_site_id(),
        "label": (label or "").strip() or "سایت جدید",
        "url": "",
        "consumer_key": "",
        "consumer_secret": "",
        "wp_username": "",
        "wp_app_password": "",
        "currency_is_toman": True,
    }


def copy_sites(sites: list[dict]) -> list[dict]:
    return copy.deepcopy(sites or [])
