""" URL و auth پرستاشاپ (Webservice API) """

from __future__ import annotations


def normalize_ps_store_url(url: str) -> str:
    """ ریشه سایت بدون /api """
    u = (url or "").strip().rstrip("/")
    if u.endswith("/api"):
        u = u[: -len("/api")].rstrip("/")
    return u


def ps_api_base(url: str) -> str:
    store = normalize_ps_store_url(url)
    if not store:
        return ""
    return f"{store}/api"


def ps_endpoint(url: str, resource: str) -> str:
    base = ps_api_base(url)
    if not base:
        return ""
    return f"{base}/{resource.lstrip('/')}"


def ps_store_host(config: dict | None = None, *, url: str = "") -> str:
    """هاست فروشگاه از PS_URL — بدون fallback."""
    from sync_app.core.network_route_check import host_from_url

    raw = (url or "").strip() or str((config or {}).get("PS_URL") or "").strip()
    return host_from_url(raw, default="")


def get_ps_auth(config: dict) -> tuple:
    """Basic Auth پرستاشاپ: کلید Webservice به‌عنوان username، پسورد خالی."""
    cfg = config or {}
    key = (cfg.get("PS_API_KEY") or "").strip()
    return (key, "")


def ps_lang_id(config: dict | None = None) -> int:
    try:
        return int((config or {}).get("PS_LANG_ID", 1) or 1)
    except (TypeError, ValueError):
        return 1
