"""Online license API for PeechaSync."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

import requests

from sync_app.core.app_version import APP_VERSION
from sync_app.core.secure_config_loader import load_secure_config

DEFAULT_OFFLINE_GRACE_DAYS = 7

_session: requests.Session | None = None


def _http() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": f"PeechaSync/{APP_VERSION}"})
    return _session


def license_server_url(config: dict | None = None) -> str:
    cfg = config or load_secure_config(None) or {}
    raw = str(cfg.get("LICENSE_SERVER_URL") or "").strip()
    return raw.rstrip("/")


def license_server_host(config: dict | None = None) -> str:
    """هاست سرور لایسنس از LICENSE_SERVER_URL — برای متن UI."""
    from sync_app.core.network_route_check import host_from_url

    return host_from_url(license_server_url(config), default="سرور لایسنس")


def license_support_url(config: dict | None = None) -> str:
    cfg = config or load_secure_config(None) or {}
    base = license_server_url(cfg)
    raw = str(cfg.get("LICENSE_SUPPORT_URL") or "").strip()
    if raw:
        return raw.rstrip("/")
    return f"{base}/contact"

def license_api_key(config: dict | None = None) -> str:
    cfg = config or load_secure_config(None) or {}
    return str(cfg.get("LICENSE_API_KEY") or "").strip()


def offline_grace_days(config: dict | None = None) -> int:
    cfg = config or load_secure_config(None) or {}
    try:
        days = int(cfg.get("LICENSE_OFFLINE_GRACE_DAYS") or DEFAULT_OFFLINE_GRACE_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_OFFLINE_GRACE_DAYS
    return max(1, days)


def _runtime_license_config(config: dict | None = None) -> dict:
    merged: dict[str, Any] = {}
    try:
        from sync_app.core.user_profile import load_secure_config_after_profile

        merged.update(load_secure_config_after_profile() or {})
    except Exception:
        pass
    if not merged:
        merged.update(load_secure_config(None) or {})
    if config:
        merged.update(config)
    return merged


def license_site_url(config: dict | None = None) -> str:
    """فروشگاهی که این دستگاه با آن سینک می‌کند — برای نمایش در پنل لایسنس."""
    cfg = _runtime_license_config(config)
    raw = str(cfg.get("WC_URL") or cfg.get("WOOCOMMERCE_URL") or "").strip()
    if not raw:
        return ""
    try:
        from sync_app.core.wc_api_helper import normalize_wc_store_url

        return normalize_wc_store_url(raw)
    except Exception:
        return raw.rstrip("/")


def _api_headers(config: dict | None = None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    cfg = _runtime_license_config(config)
    api_key = license_api_key(cfg)
    if api_key:
        headers["X-Peecha-Api-Key"] = api_key
    site = license_site_url(cfg)
    if site:
        headers["X-Peecha-Site-Url"] = site
    return headers


def _parse_json(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return {}
    return data


def _error_from_response(resp: requests.Response, data: dict[str, Any]) -> str:
    if isinstance(data.get("message"), str) and data["message"].strip():
        return data["message"].strip()
    if isinstance(data.get("code"), str) and data["code"].strip():
        return data["code"].strip()
    text = (resp.text or "").strip()
    if text:
        return text[:240]
    return f"HTTP {resp.status_code}"


def humanize_license_error(err: str) -> str:
    code = (err or "").strip().lower()
    support = license_server_host()
    if code == "revoked" or "license revoked" in code:
        return f"لایسنس شما باطل شده است.\n\nبا {support} تماس بگیرید."
    if code == "expired" or "license expired" in code:
        return f"لایسنس شما در سرور منقضی یا باطل شده است.\n\nبا {support} تماس بگیرید."
    from sync_app.core.update_ui import humanize_update_error

    return humanize_update_error(err)


def _server_error_code(err: str, data: dict[str, Any] | None) -> str:
    if isinstance(data, dict):
        code = str(data.get("code") or "").strip().lower()
        if code:
            return code
        inner = data.get("data")
        if isinstance(inner, dict):
            inner_code = str(inner.get("code") or "").strip().lower()
            if inner_code:
                return inner_code
    low = (err or "").strip().lower()
    if "license revoked" in low:
        return "revoked"
    if "license expired" in low:
        return "expired"
    if "license key not found" in low or low == "not_found":
        return "not_found"
    return low


def is_revoked_error(err: str, data: dict[str, Any] | None = None) -> bool:
    return _server_error_code(err, data) == "revoked"


def is_server_denied_status(status: str) -> bool:
    return (status or "").strip().lower() in (
        "revoked",
        "expired",
        "not_found",
        "hwid_mismatch",
    )


def _license_fields_from_response(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    inner = data.get("data")
    if isinstance(inner, dict):
        if inner.get("license_expires") or inner.get("status"):
            return inner
        nested = inner.get("data")
        if isinstance(nested, dict):
            return nested
    return data


def mark_license_server_status(
    hwid: str,
    status: str,
    *,
    license_data: dict[str, Any] | None = None,
) -> None:
    status = (status or "").strip().lower()
    if not is_server_denied_status(status):
        return
    payload = load_license_file()
    cache = payload.get("remote_cache") if isinstance(payload.get("remote_cache"), dict) else {}
    cache["status"] = status
    cache["validated_at"] = datetime.now().isoformat(timespec="seconds")
    cache["hwid"] = (hwid or "").strip()
    cache["server_registered"] = True
    fields = _license_fields_from_response(license_data)
    expiry = fields.get("license_expires")
    if expiry:
        cache["license_expires"] = str(expiry)
    updates = fields.get("updates_until")
    if updates:
        cache["updates_until"] = str(updates)
    payload["remote_cache"] = cache
    save_license_file(payload)


def mark_license_revoked(hwid: str) -> None:
    mark_license_server_status(hwid, "revoked")


def apply_server_license_denial(hwid: str, err: str, data: dict[str, Any] | None) -> str:
    code = _server_error_code(err, data)
    if is_server_denied_status(code):
        mark_license_server_status(hwid, code, license_data=data)
        return code
    return ""


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    payload: dict | None = None,
    config: dict | None = None,
    timeout: float = 15,
) -> tuple[bool, dict[str, Any], str]:
    base = license_server_url(config)
    url = f"{base}/wp-json/peecha/v1/{path.lstrip('/')}"
    cfg = _runtime_license_config(config)
    try:
        resp = _http().request(
            method.upper(),
            url,
            params=params,
            json=payload,
            headers=_api_headers(cfg),
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        return False, {}, "timeout"
    except requests.exceptions.ConnectionError:
        return False, {}, "connection_error"
    except requests.exceptions.RequestException as exc:
        return False, {}, str(exc)

    data = _parse_json(resp)
    if resp.status_code >= 400:
        return False, data, _error_from_response(resp, data)
    return True, data, ""


def activate_license(
    license_key: str,
    hwid: str,
    *,
    app_version: str | None = None,
    config: dict | None = None,
    timeout: float = 15,
) -> tuple[bool, dict[str, Any], str]:
    payload = {
        "license_key": (license_key or "").strip(),
        "hwid": (hwid or "").strip(),
        "app_version": app_version or APP_VERSION,
        "site_url": license_site_url(config),
    }
    ok, data, err = _request("POST", "license/activate", payload=payload, config=config, timeout=timeout)
    if not ok:
        denied = apply_server_license_denial(hwid, err, data)
        if denied:
            return False, data if isinstance(data, dict) else {}, denied
        return False, data if isinstance(data, dict) else {}, err
    lic = data.get("license") if isinstance(data.get("license"), dict) else {}
    if not lic.get("valid"):
        return False, lic, str(lic.get("message") or "invalid_license")
    return True, lic, ""


def validate_license(
    license_key: str,
    hwid: str,
    *,
    app_version: str | None = None,
    config: dict | None = None,
    timeout: float = 15,
) -> tuple[bool, dict[str, Any], str]:
    payload = {
        "license_key": (license_key or "").strip(),
        "hwid": (hwid or "").strip(),
        "app_version": app_version or APP_VERSION,
        "site_url": license_site_url(config),
    }
    ok, data, err = _request("POST", "license/validate", payload=payload, config=config, timeout=timeout)
    if not ok:
        denied = apply_server_license_denial(hwid, err, data)
        if denied:
            return False, data if isinstance(data, dict) else {}, denied
        return False, data if isinstance(data, dict) else {}, err
    lic = data.get("license") if isinstance(data.get("license"), dict) else {}
    if not lic.get("valid"):
        return False, lic, str(lic.get("message") or "invalid_license")
    return True, lic, ""


def check_updates(
    license_key: str,
    hwid: str,
    *,
    current_version: str | None = None,
    config: dict | None = None,
) -> tuple[bool, dict[str, Any], str]:
    params = {
        "license_key": (license_key or "").strip(),
        "hwid": (hwid or "").strip(),
        "version": current_version or APP_VERSION,
    }
    site = license_site_url(config)
    if site:
        params["site_url"] = site
    last_err = ""
    for attempt in range(2):
        timeout = 45.0 if attempt else 30.0
        ok, data, err = _request(
            "GET",
            "updates/check",
            params=params,
            config=config,
            timeout=timeout,
        )
        if ok:
            return True, data, ""
        last_err = err or ""
        if last_err not in ("timeout", "connection_error"):
            break
    return False, {}, last_err


def remote_cache_from_license(license_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "validated_at": datetime.now().isoformat(timespec="seconds"),
        "license_expires": license_data.get("license_expires"),
        "updates_until": license_data.get("updates_until"),
        "updates_allowed": bool(license_data.get("updates_allowed")),
        "customer_name": license_data.get("customer_name") or "",
        "customer_email": license_data.get("customer_email") or "",
        "status": license_data.get("status") or "active",
        "offline_grace_days": int(license_data.get("offline_grace_days") or offline_grace_days()),
        "server_registered": True,
    }


def fetch_server_health(config: dict | None = None, *, timeout: float = 8) -> tuple[bool, dict[str, Any], str]:
    ok, data, err = _request("GET", "health", config=config, timeout=timeout)
    if not ok:
        return False, {}, err
    return True, data, ""


def _store_server_plugin_version(version: str) -> None:
    ver = (version or "").strip()
    if not ver:
        return
    payload = load_license_file()
    cache = payload.get("remote_cache") if isinstance(payload.get("remote_cache"), dict) else {}
    cache["server_plugin_version"] = ver
    payload["remote_cache"] = cache
    save_license_file(payload)


def register_license_with_server(
    license_key: str,
    hwid: str,
    *,
    config: dict | None = None,
) -> tuple[bool, dict[str, Any], str]:
    """Activate on peecha.ir with retries — creates row in wp-admin list."""
    import time

    cfg = _runtime_license_config(config)
    health_ok, health, health_err = fetch_server_health(cfg)
    server_ver = str(health.get("plugin_version") or "").strip() if health_ok else ""
    if server_ver:
        _store_server_plugin_version(server_ver)

    if health_ok and server_ver and server_ver < "1.0.21":
        return False, {}, f"server_plugin_old:{server_ver}"

    if not license_api_key(cfg) and health_ok:
        api_required = bool(health.get("api_key_required"))
        if api_required:
            return False, {}, "api_key_missing"

    last_err = ""
    for attempt in range(3):
        ok, lic, err = refresh_license_from_server(
            license_key,
            hwid,
            activate=True,
            config=cfg,
            timeout=12,
        )
        if ok:
            if server_ver:
                _store_server_plugin_version(server_ver)
            return True, lic, ""
        last_err = err or ""
        if last_err not in ("timeout", "connection_error"):
            break
        time.sleep(1.0 + attempt)

    if not health_ok and health_err:
        return False, {}, health_err
    return False, {}, last_err


def remote_cache_is_fresh(cache: dict[str, Any] | None, config: dict | None = None) -> bool:
    if not cache:
        return False
    validated_at = cache.get("validated_at")
    if not validated_at:
        return False
    try:
        seen = datetime.fromisoformat(str(validated_at))
    except ValueError:
        return False

    grace = int(cache.get("offline_grace_days") or offline_grace_days(config))
    return datetime.now() - seen <= timedelta(days=grace)


def remote_cache_license_valid(cache: dict[str, Any] | None, hwid: str) -> bool:
    if not cache:
        return False
    if str(cache.get("status") or "").lower() in ("revoked", "expired", "not_found", "hwid_mismatch"):
        return False

    expiry = cache.get("license_expires")
    if not expiry:
        return False
    try:
        exp_dt = datetime.strptime(str(expiry), "%Y-%m-%d")
    except ValueError:
        return False
    if exp_dt.date() < datetime.now().date():
        return False

    bound_hwid = str(cache.get("hwid") or "").strip()
    if bound_hwid and bound_hwid != (hwid or "").strip():
        return False
    return True


def load_license_file() -> dict[str, Any]:
    from sync_app.core.tabs.tab_license import license_file_path

    path = license_file_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_license_file(data: dict[str, Any]) -> None:
    from sync_app.core.tabs.tab_license import license_file_path

    path = license_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def try_refresh_stale_denial(
    *,
    config: dict | None = None,
    timeout: float = 12,
) -> tuple[bool, str]:
    """Re-check peecha.ir when local cache says expired/revoked but admin renewed."""
    from sync_app.core.tabs.tab_license import LicenseTab

    key = LicenseTab._load_license_key()
    if not key:
        return False, "no_license_key"
    if not LicenseTab.is_license_server_denied():
        return True, ""

    hwid = LicenseTab.get_hwid()
    ok, lic, err = try_online_validate(
        key,
        hwid,
        activate=True,
        config=config,
        timeout=timeout,
    )
    if ok:
        merge_remote_cache(key, lic, hwid)
        return True, ""
    return False, err or "refresh_failed"


def refresh_denied_license_if_needed(
    *,
    config: dict | None = None,
    timeout: float = 8,
) -> bool:
    """Online refresh after admin re-activates; returns True if no longer denied."""
    from sync_app.core.tabs.tab_license import LicenseTab

    if not LicenseTab.is_license_server_denied():
        return True
    ok, _err = try_refresh_stale_denial(config=config, timeout=timeout)
    return ok and not LicenseTab.is_license_server_denied()


def merge_remote_cache(license_key: str, license_data: dict[str, Any], hwid: str) -> dict[str, Any]:
    payload = load_license_file()
    payload["license_key"] = license_key
    cache = remote_cache_from_license(license_data)
    cache["hwid"] = hwid
    payload["remote_cache"] = cache
    save_license_file(payload)
    return payload


def try_online_validate(
    license_key: str,
    hwid: str,
    *,
    activate: bool = False,
    config: dict | None = None,
    timeout: float = 15,
) -> tuple[bool, dict[str, Any], str]:
    if activate:
        return activate_license(license_key, hwid, config=config, timeout=timeout)
    return validate_license(license_key, hwid, config=config, timeout=timeout)


def refresh_license_from_server(
    license_key: str,
    hwid: str,
    *,
    activate: bool = False,
    config: dict | None = None,
    timeout: float = 15,
) -> tuple[bool, dict[str, Any], str]:
    """Online check against peecha.ir — updates license.json remote_cache."""
    ok, lic, err = try_online_validate(
        license_key,
        hwid,
        activate=activate,
        config=config,
        timeout=timeout,
    )
    if ok:
        merge_remote_cache(license_key, lic, hwid)
    else:
        denied = apply_server_license_denial(hwid, err, lic if isinstance(lic, dict) else {})
        if denied:
            return False, lic, denied
    return ok, lic, err


def push_license_site_to_server(config: dict | None = None, *, timeout: float = 8) -> bool:
    """Send WC URL to wp-admin on any online license touch."""
    from sync_app.core.tabs.tab_license import LicenseTab

    key = LicenseTab._load_license_key()
    if not key or not license_site_url(config):
        return False
    hwid = LicenseTab.get_hwid()
    cfg = _runtime_license_config(config)
    cache = load_license_file().get("remote_cache") or {}
    activate = not bool(cache.get("server_registered"))
    ok, _lic, _err = try_online_validate(
        key, hwid, activate=activate, config=cfg, timeout=timeout
    )
    if ok:
        return True
    ok, _lic, _err = try_online_validate(key, hwid, activate=True, config=cfg, timeout=timeout)
    return ok


def background_license_sync(
    config: dict | None = None,
    *,
    timeout: float = 10,
) -> dict[str, Any]:
    """Online license check — updates remote_cache without UI."""
    from sync_app.core.tabs.tab_license import LicenseTab

    result: dict[str, Any] = {"license_ok": False, "license_err": ""}
    key = LicenseTab._load_license_key()
    if not key:
        result["license_err"] = "no_license_key"
        return result

    hwid = LicenseTab.get_hwid()
    cfg = _runtime_license_config(config)
    if LicenseTab.is_license_server_denied():
        ok, err = try_refresh_stale_denial(config=cfg, timeout=timeout)
        result["license_ok"] = ok
        result["license_err"] = err or ""
        return result

    cache = load_license_file().get("remote_cache") or {}
    ok, _lic, err = refresh_license_from_server(
        key,
        hwid,
        activate=not bool(cache.get("server_registered")),
        config=cfg,
        timeout=timeout,
    )
    result["license_ok"] = ok
    result["license_err"] = err or ""
    return result


def startup_remote_sync(config: dict | None = None, *, include_update_check: bool = True) -> dict[str, Any]:
    """License validate + optional update check (for background worker on app load)."""
    from sync_app.core.app_update import lookup_update_info
    from sync_app.core.tabs.tab_license import LicenseTab

    result: dict[str, Any] = {
        "license_ok": False,
        "license_err": "",
        "server_plugin_version": "",
        "update_info": None,
        "update_err": "",
    }
    key = LicenseTab._load_license_key()
    if not key:
        result["license_err"] = "no_license_key"
        return result

    hwid = LicenseTab.get_hwid()
    sync = background_license_sync(config=config)
    result["license_ok"] = sync.get("license_ok", False)
    result["license_err"] = sync.get("license_err") or ""

    health_ok, health, _ = fetch_server_health(config)
    if health_ok:
        result["server_plugin_version"] = str(health.get("plugin_version") or "")

    if not include_update_check:
        return result

    ok_u, info, err_u = lookup_update_info(license_key=key, hwid=hwid, config=config)
    if ok_u:
        result["update_info"] = info
    else:
        result["update_err"] = err_u or ""
    return result
