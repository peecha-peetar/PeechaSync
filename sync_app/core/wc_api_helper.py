""" URL و auth ووکامرس API """

from __future__ import annotations


def normalize_wc_store_url(url: str) -> str:
    """ ریشه سایت بدون wp-json """
    u = (url or "").strip().rstrip("/")
    if "/wp-json" in u:
        u = u.split("/wp-json")[0].rstrip("/")
    return u


def wc_rest_base(url: str) -> str:
    store = normalize_wc_store_url(url)
    if not store:
        return ""
    return f"{store}/wp-json/wc/v3"


def wc_endpoint(url: str, path: str) -> str:
    base = wc_rest_base(url)
    if not base:
        return ""
    return f"{base}/{path.lstrip('/')}"


def wc_store_host(config: dict | None = None, *, url: str = "") -> str:
    """هاست فروشگاه از WC_URL — بدون fallback به peecha.ir."""
    from sync_app.core.network_route_check import host_from_url

    raw = (url or "").strip() or str((config or {}).get("WC_URL") or "").strip()
    return host_from_url(raw, default="")


def get_wc_auth(config: dict) -> tuple:
    cfg = config or {}
    return (
        (cfg.get("WC_CONSUMER_KEY") or "").strip(),
        (cfg.get("WC_CONSUMER_SECRET") or "").strip(),
    )


def wc_api_config_for_sdk(config: dict) -> dict:
    """ config برای کتابخانه woocommerce """
    cfg = dict(config or {})
    cfg["WC_URL"] = normalize_wc_store_url(cfg.get("WC_URL", ""))
    return cfg
