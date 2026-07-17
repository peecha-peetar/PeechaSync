"""چند سایت پرستاشاپ — ذخیره پروفایل‌ها و اعمال سایت فعال روی کلیدهای PS_*.

هم‌ساختار با wc_site_profiles.py (که همین مکانیزم رو برای ووکامرس پیاده
می‌کنه) تا هر دو پلتفرم از یک الگوی یکسان برای «چند فروشگاه در یک پروفایل»
استفاده کنن.
"""

from __future__ import annotations

import copy
import uuid
from urllib.parse import urlparse

PS_SITES_KEY = "PS_SITES"
ACTIVE_PS_SITE_ID_KEY = "ACTIVE_PS_SITE_ID"

_SITE_FIELDS = (
    "url",
    "api_key",
    "verify_ssl",
    "lang_id",
    "root_category_id",
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
    url = str(cfg.get("PS_URL") or "").strip()
    return {
        "id": _new_site_id(),
        "label": _host_label(url),
        "url": url,
        "api_key": str(cfg.get("PS_API_KEY") or "").strip(),
        "verify_ssl": bool(cfg.get("PS_VERIFY_SSL", False)),
        "lang_id": int(cfg.get("PS_LANG_ID") or 1),
        "root_category_id": int(cfg.get("PS_ROOT_CATEGORY_ID") or 2),
        "currency_is_toman": bool(cfg.get("WC_CURRENCY_IS_TOMAN", True)),
    }


def _normalize_site(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    site_id = str(raw.get("id") or "").strip() or _new_site_id()
    url = str(raw.get("url") or raw.get("PS_URL") or "").strip()
    try:
        lang_id = int(raw.get("lang_id") if raw.get("lang_id") is not None else raw.get("PS_LANG_ID") or 1)
    except (TypeError, ValueError):
        lang_id = 1
    try:
        root_category_id = int(
            raw.get("root_category_id")
            if raw.get("root_category_id") is not None
            else raw.get("PS_ROOT_CATEGORY_ID") or 2
        )
    except (TypeError, ValueError):
        root_category_id = 2
    return {
        "id": site_id,
        "label": str(raw.get("label") or "").strip() or _host_label(url),
        "url": url,
        "api_key": str(raw.get("api_key") or raw.get("PS_API_KEY") or "").strip(),
        "verify_ssl": bool(raw.get("verify_ssl", raw.get("PS_VERIFY_SSL", False))),
        "lang_id": lang_id,
        "root_category_id": root_category_id,
        "currency_is_toman": bool(
            raw.get("currency_is_toman", raw.get("WC_CURRENCY_IS_TOMAN", True))
        ),
    }


def get_ps_sites(config: dict | None) -> list[dict]:
    cfg = config or {}
    sites_raw = cfg.get(PS_SITES_KEY)
    if not isinstance(sites_raw, list):
        return []
    sites: list[dict] = []
    for item in sites_raw:
        site = _normalize_site(item)
        if site is not None:
            sites.append(site)
    return sites


def get_active_site_id(config: dict | None) -> str:
    return str((config or {}).get(ACTIVE_PS_SITE_ID_KEY) or "").strip()


def find_ps_site(sites: list[dict], site_id: str) -> dict | None:
    sid = (site_id or "").strip()
    if not sid:
        return None
    for site in sites:
        if str(site.get("id") or "") == sid:
            return site
    return None


def apply_site_to_flat_keys(config: dict, site: dict | None) -> None:
    """کلیدهای PS_* را از یک پروفایل سایت پر می‌کند."""
    cfg = config
    if not isinstance(site, dict):
        return
    cfg["PS_URL"] = str(site.get("url") or "").strip()
    cfg["PS_API_KEY"] = str(site.get("api_key") or "").strip()
    cfg["PS_VERIFY_SSL"] = bool(site.get("verify_ssl", False))
    cfg["PS_LANG_ID"] = int(site.get("lang_id") or 1)
    cfg["PS_ROOT_CATEGORY_ID"] = int(site.get("root_category_id") or 2)
    cfg["WC_CURRENCY_IS_TOMAN"] = bool(site.get("currency_is_toman", True))


def ensure_ps_sites(config: dict | None) -> dict:
    """مهاجرت از فرمت تک‌سایته و هم‌تراز کردن کلیدهای فعال."""
    cfg = dict(config or {})
    sites = get_ps_sites(cfg)
    active_id = get_active_site_id(cfg)

    if not sites:
        flat_url = str(cfg.get("PS_URL") or "").strip()
        flat_key = str(cfg.get("PS_API_KEY") or "").strip()
        if flat_url or flat_key:
            site = _site_from_flat(cfg)
            sites = [site]
            active_id = site["id"]
        else:
            sites = []
            active_id = ""

    if active_id and not find_ps_site(sites, active_id):
        active_id = str(sites[0]["id"]) if sites else ""

    cfg[PS_SITES_KEY] = sites
    cfg[ACTIVE_PS_SITE_ID_KEY] = active_id

    active = find_ps_site(sites, active_id)
    if active and str(cfg.get("STORE_PLATFORM") or "").strip().lower() == "prestashop":
        apply_site_to_flat_keys(cfg, active)

    return cfg


def site_from_form(
    *,
    url: str,
    api_key: str,
    verify_ssl: bool,
    lang_id: int,
    root_category_id: int,
    currency_is_toman: bool,
    site_id: str = "",
    label: str = "",
) -> dict:
    url = (url or "").strip()
    site = {
        "id": (site_id or "").strip() or _new_site_id(),
        "label": (label or "").strip() or _host_label(url),
        "url": url,
        "api_key": (api_key or "").strip(),
        "verify_ssl": bool(verify_ssl),
        "lang_id": int(lang_id or 1),
        "root_category_id": int(root_category_id or 2),
        "currency_is_toman": bool(currency_is_toman),
    }
    return site


def merge_form_into_site(
    site: dict,
    *,
    url: str,
    api_key: str,
    verify_ssl: bool,
    lang_id: int,
    root_category_id: int,
    currency_is_toman: bool,
    preserve_secrets: bool = True,
) -> dict:
    """فرم را در پروفایل ادغام می‌کند؛ فیلد خالی کلید API را نگه می‌دارد."""
    merged = dict(site or {})
    merged["url"] = (url or "").strip()
    if (api_key or "").strip():
        merged["api_key"] = api_key.strip()
    elif not preserve_secrets:
        merged["api_key"] = ""
    merged["verify_ssl"] = bool(verify_ssl)
    merged["lang_id"] = int(lang_id or 1)
    merged["root_category_id"] = int(root_category_id or 2)
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
    """لیستِ سایت‌ها و سایتِ فعال را در config ذخیره و کلیدهای PS_* را به‌روز می‌کند."""
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

    if active_id and not find_ps_site(normalized, active_id):
        active_id = str(normalized[0]["id"]) if normalized else ""

    cfg[PS_SITES_KEY] = normalized
    cfg[ACTIVE_PS_SITE_ID_KEY] = active_id

    active = find_ps_site(normalized, active_id)
    if active:
        apply_site_to_flat_keys(cfg, active)

    return cfg


def create_empty_site(*, label: str = "") -> dict:
    return {
        "id": _new_site_id(),
        "label": (label or "").strip() or "سایت جدید",
        "url": "",
        "api_key": "",
        "verify_ssl": False,
        "lang_id": 1,
        "root_category_id": 2,
        "currency_is_toman": True,
    }


def copy_sites(sites: list[dict]) -> list[dict]:
    return copy.deepcopy(sites or [])
