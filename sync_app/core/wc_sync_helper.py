"""helper تماس با api ووکامرس (timeout و retry)."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from json import dumps as jsonencode
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth
from woocommerce import API

from sync_app.core.sync_utils import log
from sync_app.core.sync_cancel import check_cancelled, SyncCancelled
from sync_app.core.wc_api_helper import wc_api_config_for_sdk

WC_SYNC_RETRIES = 3
WC_SYNC_BACKOFF = (2.0, 4.0, 6.0)
WC_SYNC_BACKOFF_FAST = (1.0, 2.0, 3.0)
WP_UPLOAD_MAX_ATTEMPTS = 3
_UA_DEFAULT = object()


def apply_network_overrides(config):
    disable_proxy = (config or {}).get("WC_DISABLE_SYSTEM_PROXY", True)
    if not disable_proxy:
        return

    for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
        if key in os.environ:
            os.environ.pop(key, None)

    current_no_proxy = os.environ.get("NO_PROXY", "")
    hosts = ["localhost", "127.0.0.1"]
    try:
        from sync_app.core.wc_api_helper import wc_store_host

        wc_host = wc_store_host(config)
        if wc_host:
            hosts.append(wc_host)
    except Exception:
        pass
    parts = [p.strip() for p in current_no_proxy.split(",") if p.strip()]
    for host in hosts:
        if host and host not in parts:
            parts.append(host)
    os.environ["NO_PROXY"] = ",".join(parts)


def wc_timeout_pair(config) -> tuple[float, float]:
    """
    (connect, read) — connect کوتاه = retry سریع‌تر روی سیم‌کارت کند.
    read بلند = منتظر پاسخ فروشگاه فعال روی شبکه کند.
    """
    from sync_app.core.connectivity_service import load_connectivity_cache

    cfg = config or {}
    try:
        connect = int(cfg.get("WC_CONNECT_TIMEOUT", 25) or 25)
    except Exception:
        connect = 25
    try:
        read = int(cfg.get("WC_READ_TIMEOUT", 120) or 120)
    except Exception:
        read = 120

    connect = max(8, min(connect, 45))
    read = max(45, min(read, 180))

    cache = load_connectivity_cache(config)
    wc_ms = float(cache.get("wc_ms") or 0)
    wc_msg = str(cache.get("wc_msg") or "").lower()
    if wc_ms >= 3000 or "timeout" in wc_msg or "timed out" in wc_msg:
        read = max(read, 180)
    elif wc_ms >= 5000:
        read = max(read, min(int(wc_ms / 1000) + 50, 180))

    return (float(connect), float(read))


def wc_is_slow_connection(config) -> bool:
    """شبکه کند یا timeout اخیر — sync باید serial و با retry بیشتر باشد."""
    from sync_app.core.connectivity_service import load_connectivity_cache

    cfg = config or {}
    flag = cfg.get("WC_SLOW_SYNC")
    if flag in (True, "true", "1", 1):
        return True
    cache = load_connectivity_cache(cfg)
    wc_ms = float(cache.get("wc_ms") or 0)
    if wc_ms >= 3000:
        return True
    wc_msg = str(cache.get("wc_msg") or "").lower()
    return "timeout" in wc_msg or "timed out" in wc_msg


def wc_sync_timeout(config) -> int:
    """برای کدهای قدیمی."""
    connect, read = wc_timeout_pair(config)
    return int(max(connect, read))


def _install_session_transport(wcapi: API, config) -> None:
    """session مشترک برای درخواست‌ها."""
    timeout = wc_timeout_pair(config)
    session = requests.Session()

    def patched_request(method, endpoint, data, params=None, **kwargs):
        if params is None:
            params = {}
        url = wcapi._API__get_url(endpoint)
        auth = None
        headers = {
            "user-agent": wcapi.user_agent,
            "accept": "application/json",
            "User-Agent": wcapi.user_agent,
        }

        if wcapi.is_ssl is True and wcapi.query_string_auth is False:
            auth = HTTPBasicAuth(wcapi.consumer_key, wcapi.consumer_secret)
        elif wcapi.is_ssl is True and wcapi.query_string_auth is True:
            params.update({
                "consumer_key": wcapi.consumer_key,
                "consumer_secret": wcapi.consumer_secret,
            })
        else:
            encoded_params = urlencode(params)
            url = f"{url}?{encoded_params}"
            url = wcapi._API__get_oauth_url(url, method, **kwargs)

        req_data = None
        if data is not None:
            req_data = jsonencode(data, ensure_ascii=False).encode("utf-8")
            headers["content-type"] = "application/json;charset=utf-8"

        return session.request(
            method=method,
            url=url,
            verify=wcapi.verify_ssl,
            auth=auth,
            params=params,
            data=req_data,
            timeout=timeout,
            headers=headers,
            **kwargs,
        )

    wcapi._API__request = patched_request  # type: ignore[method-assign]
    wcapi._peecha_session = session  # type: ignore[attr-defined]
    wcapi.timeout = timeout  # type: ignore[attr-defined]


def build_wcapi(config, verify_ssl=None):
    cfg = wc_api_config_for_sdk(config or {})
    if verify_ssl is None:
        verify_ssl = bool((config or {}).get("WC_VERIFY_SSL", False))
    try:
        from sync_app.core.app_version import APP_VERSION

        peecha_ua = f"PeechaSync/{APP_VERSION}"
    except Exception:
        peecha_ua = "PeechaSync/1.0"
    wcapi = API(
        url=cfg.get("WC_URL"),
        consumer_key=cfg.get("WC_CONSUMER_KEY"),
        consumer_secret=cfg.get("WC_CONSUMER_SECRET"),
        version="wc/v3",
        timeout=wc_sync_timeout(config),
        verify_ssl=verify_ssl,
        user_agent=peecha_ua,
        query_string_auth=False,
    )
    _install_session_transport(wcapi, config)
    return wcapi


def wc_call(wcapi, label, call_fn, retries=WC_SYNC_RETRIES, backoff=None):
    check_cancelled()
    waits = backoff if backoff is not None else WC_SYNC_BACKOFF
    last_error = None
    for attempt in range(1, retries + 2):
        try:
            return call_fn()
        except SyncCancelled:
            raise
        except Exception as err:
            last_error = err
            if attempt <= retries:
                check_cancelled()
                idx = min(attempt - 1, len(waits) - 1)
                wait = waits[idx]
                log.warning(f"⚠️ {label} — تلاش {attempt} ناموفق ({wait:.0f}s صبر): {err}")
                time.sleep(wait)
                check_cancelled()
    raise last_error


def wc_call_config(config, label, call_fn, retries=WC_SYNC_RETRIES, backoff=None):
    """retry برای wc_rest_json — همان transport تست اتصال."""
    return wc_call(None, label, call_fn, retries=retries, backoff=backoff)


def _peecha_user_agent() -> str:
    try:
        from sync_app.core.app_version import APP_VERSION

        return f"PeechaSync/{APP_VERSION}"
    except Exception:
        return "PeechaSync/1.0"


def wc_rest_request(
    config,
    method: str,
    path: str,
    *,
    params=None,
    json_body=None,
    timeout=None,
):
    """درخواست REST ووکامرس — requests + Basic Auth + User-Agent PeechaSync (مثل تست اتصال)."""
    from sync_app.core.wc_api_helper import get_wc_auth, wc_endpoint

    cfg = config or {}
    apply_network_overrides(cfg)
    url = wc_endpoint(cfg.get("WC_URL", ""), path)
    if not url:
        raise RuntimeError("WC_URL خالی است.")
    auth = get_wc_auth(cfg)
    verify = bool(cfg.get("WC_VERIFY_SSL", False))
    req_timeout = timeout if timeout is not None else wc_timeout_pair(cfg)
    headers = {
        "Accept": "application/json",
        "User-Agent": _peecha_user_agent(),
    }
    data = None
    if json_body is not None:
        headers["Content-Type"] = "application/json;charset=utf-8"
        data = jsonencode(json_body, ensure_ascii=False).encode("utf-8")
    return requests.request(
        method.upper(),
        url,
        auth=auth,
        params=dict(params or {}),
        data=data,
        timeout=req_timeout,
        verify=verify,
        headers=headers,
    )


def wc_rest_json(
    config,
    method: str,
    path: str,
    *,
    params=None,
    json_body=None,
    label: str = "Woo",
    timeout=None,
):
    response = wc_rest_request(
        config,
        method,
        path,
        params=params,
        json_body=json_body,
        timeout=timeout,
    )
    return wcapi_parse_json(response, label, config)


def wc_category_image_update_error(response, config=None) -> str:
    """پیام خطای تنظیم تصویر دسته — WAF/HTML یا JSON ووکامرس."""
    if response_is_waf_block(response):
        return (
            "فایروال LiteSpeed/WAF هاست، PUT به wc/v3/products/categories را مسدود کرد.\n"
            "آپلود رسانه OK بود — Consumer Key باید Read/Write باشد؛ "
            "از پشتیبانی هاست مسیر wc/v3/products/categories را برای PUT باز کنید."
        )
    status = int(getattr(response, "status_code", 0) or 0)
    try:
        data = response.json()
        msg = data.get("message") or data.get("code") or ""
        if msg:
            return f"HTTP {status} — {msg}"
    except Exception:
        pass
    return wc_http_error_message(response, config) or f"HTTP {status}"


def update_wc_category_image(config, cat_id, *, media_id=0, src_url="", timeout=None):
    """
    تنظیم تصویر دسته در ووکامرس — wc_rest_request + User-Agent.
    برمی‌گرداند: (ok, response, error_text)
    """
    cid = int(cat_id or 0)
    if cid <= 0:
        return False, None, "شناسه دسته ووکامرس نامعتبر است."

    path = f"products/categories/{cid}"
    payloads = []
    if int(media_id or 0) > 0:
        payloads.append({"image": {"id": int(media_id)}})
    if (src_url or "").strip():
        payloads.append({"image": {"src": src_url.strip()}})

    if not payloads:
        return False, None, "media_id یا src_url برای تنظیم تصویر لازم است."

    last_resp = None
    last_err = ""
    for body in payloads:
        resp = wc_rest_request(
            config,
            "PUT",
            path,
            json_body=body,
            timeout=timeout,
        )
        last_resp = resp
        if resp.status_code in (200, 201):
            return True, resp, ""
        last_err = wc_category_image_update_error(resp, config)

    return False, last_resp, last_err or "تنظیم تصویر دسته ناموفق بود."


def wc_product_images_update_error(response, config=None) -> str:
    if response_is_waf_block(response):
        return (
            "فایروال LiteSpeed/WAF هاست، PUT به wc/v3/products را مسدود کرد.\n"
            "آپلود رسانه OK بود — Consumer Key باید Read/Write باشد."
        )
    status = int(getattr(response, "status_code", 0) or 0)
    try:
        data = response.json()
        msg = data.get("message") or data.get("code") or ""
        if msg:
            return f"HTTP {status} — {msg}"
    except Exception:
        pass
    return wc_http_error_message(response, config) or f"HTTP {status}"


def update_wc_product_images(config, product_id, images, timeout=None, *, allow_empty=False):
    """تنظیم گالری تصاویر محصول — wc_rest_request + User-Agent.

    allow_empty=True فقط برایِ حذفِ عمدیِ آخرین عکسِ باقی‌مانده (که نتیجه‌ش
    یه گالریِ کاملاً خالیه) لازمه — حالتِ پیش‌فرض (False) همچنان جلویِ
    خالی‌فرستادنِ سهوی رو می‌گیره."""
    pid = int(product_id or 0)
    if pid <= 0:
        return False, None, "شناسه محصول ووکامرس نامعتبر است."
    if not isinstance(images, list):
        return False, None, "لیست تصاویر نامعتبر است."
    if not images and not allow_empty:
        return False, None, "لیست تصاویر خالی است."

    resp = wc_rest_request(
        config,
        "PUT",
        f"products/{pid}",
        json_body={"images": images},
        timeout=timeout,
    )
    if resp.status_code in (200, 201):
        return True, resp, ""
    return False, resp, wc_product_images_update_error(resp, config)


def wc_http_error_message(response, config=None, *, prefix: str = "") -> str:
    """پیام فارسی از پاسخ HTTP ووکامرس — 401/403/timeout."""
    from sync_app.core.connectivity_service import (
        classify_network_error,
        network_error_user_hint,
    )
    from sync_app.core.wc_api_helper import wc_store_host

    status = int(getattr(response, "status_code", 0) or 0)
    body = (getattr(response, "text", None) or "")[:240]
    err = f"HTTP {status}: {body}" if status else body or "خطای نامشخص"
    host = wc_store_host(config)
    target = f"فروشگاه ({host})" if host else "فروشگاه"
    hint = network_error_user_hint(classify_network_error(err), target=target)
    if prefix:
        return f"{prefix}\n{hint}".strip()
    return hint


def wc_rest_raise(response, config=None, *, prefix: str = ""):
    if response is None:
        raise RuntimeError(prefix or "پاسخ ووکامرس خالی است.")
    if int(response.status_code or 0) < 400:
        return
    raise RuntimeError(wc_http_error_message(response, config, prefix=prefix))


def warm_wc_connection(wcapi) -> None:
    """یک get سبک برای گرم کردن اتصال."""
    def _ping():
        wcapi.get("products/attributes", params={"per_page": 1, "_fields": "id"}).json()

    try:
        wc_call(wcapi, "آماده‌سازی اتصال Woo", _ping, retries=1, backoff=(0.5, 1.0))
    except Exception:
        pass


def wc_store_label(config=None) -> str:
    from sync_app.core.network_route_check import host_from_url

    cfg = config or {}
    host = host_from_url((cfg.get("WC_URL") or "").strip(), default="")
    return f"WooCommerce ({host})" if host else "WooCommerce"


def format_wc_network_error(exc: Exception, config=None) -> str:
    from sync_app.core.connectivity_service import classify_network_error, network_error_user_hint

    text = str(exc or "")
    target = wc_store_label(config)
    category = classify_network_error(text)
    if category != "unknown":
        return network_error_user_hint(category, target=target)
    if "timed out" in text.lower() or "connecttimeout" in text.lower().replace(" ", ""):
        return network_error_user_hint("timeout", target=target)
    return text


def format_wc_api_error(exc, config=None) -> str:
    """پیام خطای REST ووکامرس — از رجیستری تشخیص."""
    from sync_app.core.diagnostics import format_wc_error

    return format_wc_error(exc=exc, config=config)


def _wc_response_text_snippet(response, limit: int = 180) -> str:
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        content = getattr(response, "content", None)
        if content:
            try:
                text = content.decode("utf-8", errors="replace").strip()
            except Exception:
                text = ""
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def wcapi_parse_json(response, label: str = "Woo", config=None):
    """پاسخ REST را parse کن — تشخیص خطا از رجیستری."""
    from sync_app.core.diagnostics import diagnose_wc, wc_context_from_response

    ctx = wc_context_from_response(response, config=config, label=label)
    status_num = ctx.http_status or 0
    if status_num >= 400:
        result = diagnose_wc(
            config=config,
            http_status=status_num,
            response_snippet=ctx.response_snippet,
            exc=Exception(ctx.error_text or f"HTTP {status_num}"),
            label=label,
        )
        raise RuntimeError(f"{label}: {result.full_message()}".strip())
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        result = diagnose_wc(
            exc=exc,
            config=config,
            http_status=status_num or None,
            response_snippet=ctx.response_snippet,
            label=label,
        )
        raise RuntimeError(f"{label}: {result.full_message()}".strip()) from exc
    if isinstance(data, dict) and data.get("code") and not data.get("id"):
        wp_code = str(data.get("code") or "")
        result = diagnose_wc(
            exc=Exception(wp_code),
            config=config,
            http_status=int(data.get("data", {}).get("status") or status_num or 0) or None,
            response_snippet=str(data.get("message") or "")[:180],
            label=label,
        )
        if result.code not in ("wc_unknown",):
            raise RuntimeError(f"{label}: {result.full_message()}".strip())
        msg = data.get("message") or wp_code
        raise RuntimeError(f"{label}: {msg}")
    return data


def wc_parse_json(response, label: str = "Woo"):
    """json پاسخ woo رو چک کن، خطا بود exception."""
    try:
        data = response.json()
    except Exception as exc:
        status = getattr(response, "status_code", "?")
        raise RuntimeError(f"{label}: پاسخ JSON نامعتبر (HTTP {status})") from exc
    if isinstance(data, dict) and data.get("code") and not data.get("id"):
        msg = data.get("message") or data.get("code") or str(data)
        raise RuntimeError(f"{label}: {msg}")
    return data


def guess_image_mime(filename):
    ext = os.path.splitext((filename or "").lower())[1]
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")


def normalize_wp_app_password(raw):
    """فاصله‌های نمایشی Application Password را حذف کن."""
    return re.sub(r"\s+", "", (raw or "").strip())


def wp_password_variants(raw):
    """چند شکل رمز — بعضی هاست‌ها فاصله را قبول نمی‌کنند."""
    s = (raw or "").strip()
    if not s:
        return []
    out = []
    for v in (s, normalize_wp_app_password(s)):
        if v and v not in out:
            out.append(v)
    return out


def get_wp_media_credentials(config):
    """نام کاربری + Application Password برای wp/v2/media."""
    from sync_app.core.wc_site_profiles import ensure_wc_sites

    cfg = ensure_wc_sites(config or {})
    user = (cfg.get("WP_USERNAME") or "").strip()
    pwd = (cfg.get("WP_APP_PASSWORD") or "").strip()
    return user, pwd


def wp_requests_verify(config) -> bool:
    return bool((config or {}).get("WC_VERIFY_SSL", False))


def wp_media_common_headers(extra: dict | None = None, *, user_agent=_UA_DEFAULT) -> dict:
    headers = {"Accept": "application/json"}
    if user_agent is _UA_DEFAULT:
        headers["User-Agent"] = _peecha_user_agent()
    elif user_agent:
        headers["User-Agent"] = user_agent
    if extra:
        headers.update(extra)
    return headers


def wp_media_upload_user_agents(config):
    """چند User-Agent — بعضی هاست‌ها فقط درخواست شبیه مرورگر را از WAF عبور می‌دهند."""
    base = wp_media_base_url(config) or "https://wordpress.org"
    return (
        _peecha_user_agent(),
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        f"WordPress/6.7; {base}",
        f"Mozilla/5.0 (compatible; WordPress/6.7; +{base})",
    )


def _wp_media_site_headers(config) -> dict:
    base = wp_media_base_url(config)
    if not base:
        return {}
    return {"Referer": f"{base}/wp-admin/", "Origin": base}


def wp_media_base_url(config):
    from sync_app.core.wc_api_helper import normalize_wc_store_url

    wc_url = (config or {}).get("WC_URL") or ""
    base = normalize_wc_store_url(wc_url)
    return base.rstrip("/") if base else ""


def wp_media_endpoint(config):
    base = wp_media_base_url(config)
    return f"{base}/wp-json/wp/v2/media" if base else ""


def wp_basic_auth_header(username, password):
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def response_is_waf_block(response) -> bool:
    """403 HTML از LiteSpeed/ModSecurity — قبل از رسیدن به وردپرس."""
    status = int(getattr(response, "status_code", 0) or 0)
    if status not in (403, 406, 429, 503):
        return False
    try:
        response.json()
        return False
    except Exception:
        pass
    raw = (getattr(response, "text", None) or "").lower()
    if not raw or "<html" not in raw:
        return False
    markers = (
        "litespeed",
        "mod_security",
        "modsecurity",
        "cloudflare",
        "access denied",
        "forbidden",
        "attention required",
        "proudly powered",
    )
    return any(m in raw for m in markers)


def parse_wp_error_message(response):
    status = int(getattr(response, "status_code", 0) or 0)
    if response_is_waf_block(response):
        raw = (response.text or "").lower()
        if "litespeed" in raw:
            return f"HTTP {status} — LiteSpeed/WAF هاست POST آپلود را مسدود کرد"
        if "cloudflare" in raw:
            return f"HTTP {status} — Cloudflare/WAF درخواست را مسدود کرد"
        return f"HTTP {status} — فایروال هاست (WAF) درخواست REST را مسدود کرد"
    try:
        data = response.json()
    except Exception:
        raw = (response.text or "").strip()
        low = raw.lower()
        if "cloudflare" in low or "attention required" in low:
            return f"HTTP {status} — WAF/Cloudflare درخواست را مسدود کرد"
        clean = re.sub(r"<[^>]+>", " ", raw)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) > 180:
            clean = clean[:180] + "..."
        return clean or f"HTTP {status} — پاسخ HTML (دسترسی رد شد)"
    msg = data.get("message") or data.get("code") or ""
    if isinstance(msg, str):
        msg = re.sub(r"<[^>]+>", "", msg)
    code = data.get("code") or ""
    if code and msg:
        return f"{code}: {msg}"
    return str(msg or code or (response.text or "")[:200])


def normalize_credential_text(raw: str) -> str:
    return re.sub(r"\s+", "", (raw or "").strip())


def looks_like_wp_app_password_token(raw: str) -> bool:
    """رمز Application Password وردپرس معمولاً ۲۴ کاراکتر alphanumeric است."""
    token = normalize_credential_text(raw)
    return len(token) == 24 and token.isalnum()


def detect_wp_credential_field_mismatch(user: str, pwd: str) -> str:
    """تشخیص جابه‌جایی فیلد Username و Application Password."""
    u = (user or "").strip()
    p = (pwd or "").strip()
    if not u or not p:
        return ""
    if looks_like_wp_app_password_token(u):
        p_short = normalize_credential_text(p)
        if len(p_short) <= 24 and not looks_like_wp_app_password_token(p):
            return (
                "به نظر می‌رسد فیلدهای WP Username و WP App Password جابه‌جا شده‌اند.\n"
                "رمز ۲۴ کاراکتری Application Password را در WP App Password بگذارید "
                "و login واقعی (از Users → All Users) را در WP Username."
            )
        return (
            "به نظر می‌رسد Application Password (رمز ۲۴ کاراکتری) را در فیلد WP Username گذاشته‌اید.\n"
            "login واقعی از Users → All Users را در WP Username بگذارید — "
            "نه عنوان Application Password و نه خود رمز."
        )
    if normalize_credential_text(u) == normalize_credential_text(p):
        return (
            "WP Username و WP App Password نباید یکسان باشند.\n"
            "Username = login وردپرس | App Password = رشتهٔ ۲۴ کاراکتری جدا."
        )
    return ""


def validate_wp_media_settings(config) -> tuple[bool, str]:
    """اعتبارسنجی قبل از آپلود — جلوگیری از username/secret اشتباه."""
    user, pwd = get_wp_media_credentials(config)
    if not user or not pwd:
        return False, (
            "WP Username یا Application Password خالی است.\n"
            "تنظیمات → سایت فعال → WP Username / WP App Password"
        )
    if pwd.startswith("ck_") or pwd.startswith("cs_"):
        return False, (
            "Application Password نباید Consumer Key/Secret ووکامرس (ck_/cs_) باشد.\n"
            "Users → Profile → Application Passwords — رمز جدا بسازید."
        )
    mismatch = detect_wp_credential_field_mismatch(user, pwd)
    if mismatch:
        return False, mismatch
    from sync_app.core.wc_api_helper import wc_store_host

    host = wc_store_host(config).lower().replace("www.", "")
    u_lower = user.lower().replace("www.", "")
    if host and u_lower == host:
        return False, (
            f"WP Username نباید همان آدرس سایت ({user}) باشد.\n"
            "در wp-admin → Users → All Users ستون «Username» را ببینید (معمولاً admin)."
        )
    if "." in u_lower and "@" not in u_lower and any(
        u_lower.endswith(suffix) for suffix in (".ir", ".com", ".net", ".org", ".io")
    ):
        return False, (
            f"WP Username «{user}» شبیه دامنه است نه نام login.\n"
            "Users → All Users → Username واقعی (مثلاً admin) را بگذارید."
        )
    return True, ""


def _wp_user_can_upload_media(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return True, ""
    roles = [str(r).lower() for r in (data.get("roles") or [])]
    caps = data.get("capabilities") or {}
    if isinstance(caps, dict) and (caps.get("upload_files") or caps.get("administrator")):
        return True, ""
    if "administrator" in roles or "editor" in roles:
        return True, ""
    role_txt = ", ".join(roles) or "نامشخص"
    login = data.get("slug") or data.get("username") or data.get("name") or "?"
    return False, (
        f"کاربر «{login}» نقش «{role_txt}» دارد و upload_files ندارد.\n"
        "برای آپلود تصویر باید Administrator باشد (یا Editor با مجوز رسانه)."
    )


def _probe_wp_media_api(config, user, pwd) -> tuple[bool, str]:
    """fallback وقتی users/me در دسترس نیست — لیست media با همان auth."""
    base = wp_media_base_url(config)
    if not base:
        return False, "WC URL در تنظیمات خالی است."
    url = f"{base}/wp-json/wp/v2/media?per_page=1"
    timeout = wc_timeout_pair(config)
    verify = wp_requests_verify(config)
    try:
        resp = requests.get(
            url,
            headers=wp_media_common_headers(wp_basic_auth_header(user, pwd)),
            timeout=timeout,
            verify=verify,
        )
    except requests.exceptions.SSLError as exc:
        return False, (
            f"خطای SSL: {exc}\n"
            "اگر گواهی خودامضا دارید، «تأیید SSL» را در تنظیمات خاموش کنید."
        )
    except requests.exceptions.RequestException as exc:
        return False, str(exc)

    if resp.status_code == 200:
        return True, ""
    detail = parse_wp_error_message(resp)
    hint = wp_auth_error_hint(resp, user)
    err = f"HTTP {resp.status_code} — {detail}"
    if hint:
        err += f" | {hint}"
    return False, err


def is_wp_upload_fatal_error(err_text: str) -> bool:
    """خطاهای احراز هویت/دسترسی — retry بی‌فایده است."""
    text = (err_text or "").lower()
    return any(
        token in text
        for token in (
            "http 401",
            "http 403",
            "401 —",
            "403 —",
            "incorrect_password",
            "invalid_username",
            "application password",
            "احراز هویت",
            "forbidden",
            "rest_cannot_create",
            "rest_cannot_edit",
            "upload_files",
            "empty is",
            "خالی است",
            "litespeed",
            "waf",
            "modsecurity",
            "cloudflare",
            "فایروال",
        )
    )


def should_retry_upload_error(err_text: str) -> bool:
    from sync_app.core.connectivity_wait import is_transient_connectivity_issue

    if is_wp_upload_fatal_error(err_text):
        return False
    return is_transient_connectivity_issue(err_text)


def verify_wp_media_credentials(config) -> tuple[bool, str]:
    """بررسی Application Password و دسترسی upload_files قبل از آپلود."""
    apply_network_overrides(config)
    ok_cfg, cfg_err = validate_wp_media_settings(config)
    if not ok_cfg:
        return False, cfg_err

    user, pwd_raw = get_wp_media_credentials(config)
    base = wp_media_base_url(config)
    if not base:
        return False, "WC URL در تنظیمات خالی است."

    url = f"{base}/wp-json/wp/v2/users/me?context=edit"
    timeout = wc_timeout_pair(config)
    verify = wp_requests_verify(config)
    last_err = ""

    for pwd in wp_password_variants(pwd_raw):
        try:
            resp = requests.get(
                url,
                headers=wp_media_common_headers(wp_basic_auth_header(user, pwd)),
                timeout=timeout,
                verify=verify,
            )
        except requests.exceptions.Timeout:
            return False, "timeout — اتصال به وردپرس برای بررسی رمز کند است."
        except requests.exceptions.SSLError as exc:
            return False, (
                f"خطای SSL: {exc}\n"
                "اگر گواهی خودامضا دارید، «تأیید SSL» را در تنظیمات خاموش کنید."
            )
        except requests.exceptions.ConnectionError as exc:
            return False, f"اتصال قطع شد: {exc}"
        except Exception as exc:
            return False, str(exc)

        if resp.status_code == 200:
            try:
                can, cap_err = _wp_user_can_upload_media(resp.json() or {})
            except Exception:
                can, cap_err = True, ""
            if not can:
                return False, cap_err
            ok_post, post_err = _probe_wp_media_post_upload(config, user, pwd)
            if not ok_post:
                return False, post_err
            return True, ""

        detail = parse_wp_error_message(resp)
        hint = wp_auth_error_hint(resp, user)
        last_err = f"HTTP {resp.status_code} — {detail}"
        if hint:
            last_err += f" | {hint}"

        if resp.status_code == 403 and response_is_waf_block(resp):
            ok_post, post_err = _probe_wp_media_post_upload(config, user, pwd)
            if ok_post:
                return True, ""
            if post_err:
                low = post_err.lower()
                if "incorrect_password" in low:
                    return False, (
                        "Application Password اشتباه یا منقضی است.\n"
                        "رمز جدید را از وردپرس کپی کنید، در تنظیمات بچسبانید و «ذخیره تنظیمات» بزنید.\n"
                        "WP Username باید همان کاربری باشد که رمز را برایش ساختید."
                    )
                if "invalid_username" in low:
                    return False, (
                        "WP Username اشتباه است.\n"
                        "در فیلد WP Username باید «Username» واقعی از Users → All Users باشد — "
                        "نه نام نمایشی، نه ایمیل، و نه عنوان Application Password."
                    )
                if not response_is_waf_block_from_text(post_err):
                    return False, post_err
            last_err = post_err or last_err
            continue

        if resp.status_code == 401:
            try:
                code = (resp.json() or {}).get("code") or ""
            except Exception:
                code = ""
            if code in ("incorrect_password", "invalid_username"):
                hint = wp_auth_error_hint(resp, user)
                msg = hint or detail
                if code not in (msg or "").lower():
                    msg = f"{code}: {msg}" if msg else code
                return False, msg
            continue

        if resp.status_code == 403:
            continue
        if resp.status_code in (404, 405, 501):
            ok_get, get_err = _probe_wp_media_api(config, user, pwd)
            if not ok_get:
                return False, get_err
            ok_post, post_err = _probe_wp_media_post_upload(config, user, pwd)
            if not ok_post:
                return False, post_err
            return True, ""
        break

    return False, last_err or "احراز هویت وردپرس ناموفق است."


def classify_wp_media_auth_error(err_text: str) -> str:
    """invalid_username | incorrect_password | waf | permission | generic"""
    text = (err_text or "").lower()
    if (
        "invalid_username" in text
        or "نام کاربری وردپرس اشتباه" in (err_text or "")
        or "wp username اشتباه" in text
        or "جابه‌جا" in (err_text or "")
        or "۲۴ کاراکتری" in (err_text or "")
        or "24 کاراکتری" in (err_text or "")
    ):
        return "invalid_username"
    if "incorrect_password" in text or "application password اشتباه" in text:
        return "incorrect_password"
    if (
        response_is_waf_block_from_text(err_text)
        or "litespeed" in text
        or "waf" in text
        or "فایروال" in (err_text or "")
    ):
        return "waf"
    if "upload_files" in text or "administrator" in text and "نقش" in (err_text or ""):
        return "permission"
    return "generic"


def format_wp_username_auth_error(err_type: str, *, entered_username: str = "", detail: str = "") -> str:
    user_txt = (entered_username or "").strip() or "—"
    if err_type == "invalid_username":
        lines = [
            "نام کاربری وردپرس (WP Username) اشتباه است.",
            "",
            f"مقدار فعلی در تنظیمات: «{user_txt}»",
            "",
            "چه چیزی باید وارد شود؟",
            "• همان Username از Users → All Users در wp-admin",
            "• نه نام نمایشی (Display Name)",
            "• نه ایمیل",
            "• نه عنوان Application Password (نام دلخواهی که هنگام ساخت رمز می‌دهید)",
            "",
            "Application Password را در فیلد جداگانهٔ WP App Password بگذارید.",
        ]
        if "@" in user_txt:
            lines.insert(3, "به نظر می‌رسد ایمیل وارد شده — وردپرس برای این ورود login name می‌خواهد.")
        return "\n".join(lines)
    if err_type == "incorrect_password":
        return (
            "Application Password (WP App Password) اشتباه یا منقضی است.\n\n"
            f"نام کاربری فعلی: «{user_txt}»\n\n"
            "۱. در وردپرس: Users → Profile → Application Passwords\n"
            "۲. یک رمز جدید بسازید و کل رشته را بدون فاصله کپی کنید\n"
            "۳. در فیلد WP App Password بچسبانید و «ذخیره تنظیمات» بزنید\n"
            "۴. دوباره «تست Application Password» را بزنید"
        )
    if err_type == "permission":
        return (
            f"{detail or 'کاربر انتخاب‌شده مجوز آپلود تصویر ندارد.'}\n\n"
            "برای آپلود تصویر دسته‌بندی، کاربر باید Administrator باشد "
            "(یا Editor با دسترسی رسانه)."
        )
    if detail:
        return detail
    return "Application Password نامعتبر است یا دسترسی آپلود ندارد."


def _wp_user_record_from_api(data: dict, *, verified_match: bool = False) -> dict | None:
    if not isinstance(data, dict):
        return None
    username = (
        str(data.get("username") or data.get("slug") or data.get("name") or "").strip()
    )
    if not username:
        return None
    roles = [str(r).lower() for r in (data.get("roles") or []) if r]
    caps = data.get("capabilities") or {}
    is_admin = "administrator" in roles or (
        isinstance(caps, dict) and bool(caps.get("administrator"))
    )
    if not is_admin and username.lower() in ("admin", "administrator"):
        is_admin = True
    can_upload = is_admin or "editor" in roles or (
        isinstance(caps, dict) and bool(caps.get("upload_files"))
    )
    return {
        "username": username,
        "name": str(data.get("name") or "").strip(),
        "roles": roles,
        "is_admin": is_admin,
        "can_upload": can_upload,
        "verified_match": verified_match,
    }


def _wp_user_sort_key(user: dict) -> tuple:
    return (
        0 if user.get("verified_match") else 1,
        0 if user.get("is_admin") else 1,
        0 if user.get("can_upload") else 1,
        str(user.get("username") or "").lower(),
    )


def _merge_wp_user_lists(*lists) -> list[dict]:
    merged: dict[str, dict] = {}
    for users in lists:
        for user in users or []:
            if not isinstance(user, dict):
                continue
            username = str(user.get("username") or "").strip()
            if not username:
                continue
            key = username.lower()
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(user)
                continue
            for field in ("name", "roles", "is_admin", "can_upload", "verified_match"):
                if user.get(field) and not existing.get(field):
                    existing[field] = user[field]
                elif field == "verified_match" and user.get(field):
                    existing[field] = True
                elif field == "is_admin" and user.get(field):
                    existing["is_admin"] = True
                elif field == "can_upload" and user.get(field):
                    existing["can_upload"] = True
            if user.get("roles"):
                roles = list(dict.fromkeys(list(existing.get("roles") or []) + list(user.get("roles") or [])))
                existing["roles"] = roles
    out = list(merged.values())
    out.sort(key=_wp_user_sort_key)
    return out


def fetch_wp_users_public(config, *, max_pages: int = 3) -> list[dict]:
    """لیست عمومی کاربران — بدون نیاز به احراز هویت (ممکن است ناقص باشد)."""
    base = wp_media_base_url(config)
    if not base:
        return []
    timeout = wc_timeout_pair(config)
    verify = wp_requests_verify(config)
    out: list[dict] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        url = f"{base}/wp-json/wp/v2/users?per_page=100&page={page}&context=view"
        try:
            resp = requests.get(
                url,
                headers=wp_media_common_headers(_wp_media_site_headers(config)),
                timeout=timeout,
                verify=verify,
            )
        except Exception:
            break
        if resp.status_code != 200:
            break
        try:
            payload = resp.json() or []
        except Exception:
            break
        if not isinstance(payload, list) or not payload:
            break
        for row in payload:
            rec = _wp_user_record_from_api(row)
            if not rec:
                continue
            key = str(rec.get("username") or "").lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(rec)
        if len(payload) < 100:
            break

    out.sort(key=_wp_user_sort_key)
    return out


def fetch_wp_users_authenticated(config, user: str, password: str) -> list[dict]:
    """لیست کامل کاربران با login واقعی — نیاز به Application Password معتبر دارد."""
    base = wp_media_base_url(config)
    if not base or not user or not password:
        return []
    url = f"{base}/wp-json/wp/v2/users?context=edit&per_page=100&orderby=registered_date&order=desc"
    timeout = wc_timeout_pair(config)
    verify = wp_requests_verify(config)
    for pwd in wp_password_variants(password):
        try:
            resp = requests.get(
                url,
                headers=wp_media_common_headers(
                    {**wp_basic_auth_header(user, pwd), **_wp_media_site_headers(config)}
                ),
                timeout=timeout,
                verify=verify,
            )
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        try:
            payload = resp.json() or []
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        out = []
        for row in payload:
            rec = _wp_user_record_from_api(row)
            if rec:
                out.append(rec)
        return out
    return []


def discover_wp_username_with_password(
    config,
    password: str,
    *,
    extra_candidates=None,
    max_probes: int = 25,
) -> list[dict]:
    """با همان Application Password، login درست را پیدا کن (وقتی Username اشتباه است)."""
    base = wp_media_base_url(config)
    pwd_raw = (password or "").strip()
    if not base or not pwd_raw:
        return []

    candidates: list[str] = []
    public_users = fetch_wp_users_public(config)
    admin_candidates = [
        str(u.get("username") or "").strip()
        for u in public_users
        if u.get("is_admin") and u.get("username")
    ]
    other_candidates = [
        str(u.get("username") or "").strip()
        for u in public_users
        if not u.get("is_admin") and u.get("username")
    ]
    for val in admin_candidates + other_candidates:
        if val and val.lower() not in {c.lower() for c in candidates}:
            candidates.append(val)

    for source in (extra_candidates or [],):
        if isinstance(source, list):
            for item in source:
                if isinstance(item, dict):
                    val = str(item.get("username") or "").strip()
                else:
                    val = str(item or "").strip()
                if val and val.lower() not in {c.lower() for c in candidates}:
                    candidates.append(val)
        elif isinstance(source, str) and source.strip():
            val = source.strip()
            if val.lower() not in {c.lower() for c in candidates}:
                candidates.append(val)

    for default_name in ("admin", "administrator", "editor", "shop_manager"):
        if default_name not in {c.lower() for c in candidates}:
            candidates.append(default_name)

    url = f"{base}/wp-json/wp/v2/users/me?context=edit"
    timeout = wc_timeout_pair(config)
    verify = wp_requests_verify(config)
    matches: list[dict] = []
    probed = 0

    for cand in candidates:
        if probed >= max_probes:
            break
        for pwd in wp_password_variants(pwd_raw):
            probed += 1
            try:
                resp = requests.get(
                    url,
                    headers=wp_media_common_headers(
                        {**wp_basic_auth_header(cand, pwd), **_wp_media_site_headers(config)}
                    ),
                    timeout=timeout,
                    verify=verify,
                )
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            try:
                data = resp.json() or {}
            except Exception:
                continue
            rec = _wp_user_record_from_api(data, verified_match=True)
            if rec:
                matches.append(rec)
            break

    matches.sort(key=_wp_user_sort_key)
    return matches


def fetch_wp_users_for_picker(
    config,
    *,
    probe_password: bool = False,
    entered_username: str = "",
) -> tuple[list[dict], str]:
    """
    کاربران سایت برای انتخاب WP Username.
    برمی‌گرداند: (users, note_fa)
    """
    user, pwd = get_wp_media_credentials(config)
    if entered_username:
        user = entered_username.strip() or user

    public_users = fetch_wp_users_public(config)
    auth_users = fetch_wp_users_authenticated(config, user, pwd) if user and pwd else []
    verified_users = (
        discover_wp_username_with_password(
            config,
            pwd,
            extra_candidates=[user] if user else None,
        )
        if probe_password and pwd
        else []
    )

    users = _merge_wp_user_lists(auth_users, verified_users, public_users)

    if auth_users:
        note = "لیست کامل کاربران از وردپرس دریافت شد."
    elif verified_users:
        note = (
            "Application Password با نام کاربری فعلی سازگار نبود؛ "
            "کاربرانی که با این رمز تأیید شدند علامت ✓ دارند."
        )
    elif public_users:
        note = (
            "لیست عمومی کاربران سایت دریافت شد. "
            "اگر login دقیق را نمی‌دانید، از Users → All Users در wp-admin ببینید."
        )
    else:
        note = "کاربری از API وردپرس دریافت نشد — ممکن است سایت لیست کاربران را بسته باشد."

    return users, note


def wp_auth_error_hint(response, username=""):
    code = ""
    try:
        code = (response.json() or {}).get("code") or ""
    except Exception:
        pass
    if code == "invalid_username":
        hint = (
            "نام کاربری وردپرس (WP Username) اشتباه است — "
            "login name از Users → All Users بگذارید، نه ایمیل یا عنوان Application Password."
        )
        if "@" in (username or ""):
            hint += " (به نظر می‌رسد ایمیل وارد شده است.)"
        return hint
    if code == "incorrect_password":
        return (
            "Application Password اشتباه یا منقضی است. "
            "Users → Profile → Application Passwords — رمز جدید بسازید و بدون فاصله کپی کنید."
        )
    if response.status_code == 401:
        return "احراز هویت وردپرس رد شد — WP Username و Application Password را در تنظیمات چک کنید."
    if response.status_code == 403:
        if response_is_waf_block(response):
            return (
                "فایروال LiteSpeed/WAF — درخواست REST مسدود شد. "
                "اگر همزمان incorrect_password هم می‌بینید، اول رمز/یوزر را اصلاح کنید."
            )
        raw = (getattr(response, "text", None) or "").lower()
        if "cloudflare" in raw:
            return (
                "WAF/Cloudflare درخواست REST را مسدود کرد — "
                "در پنل امنیت، wp-json/wp/v2/media را whitelist کنید."
            )
        return "دسترسی آپلود رسانه در وردپرس ندارید — کاربر باید Administrator باشد."
    return ""


def wp_media_filename_parts(filename, fallback_stem="upload"):
    """نام اصلی، نام ASCII-safe، و MIME."""
    name = os.path.basename(filename or "") or f"{fallback_stem}.jpg"
    stem, ext = os.path.splitext(name)
    if not ext:
        ext = ".jpg"
    ascii_stem = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "_"
        for ch in stem
    ).strip("._") or fallback_stem
    ascii_name = f"{ascii_stem}{ext}"
    return name, ascii_name, guess_image_mime(name)


def wp_media_upload_headers(filename, fallback_stem="upload", *, include_utf8=True):
    """هدر آپلود رسانه — raw POST با Content-Disposition."""
    from urllib.parse import quote

    name, ascii_name, mime = wp_media_filename_parts(filename, fallback_stem=fallback_stem)
    disposition = f'attachment; filename="{ascii_name}"'
    if include_utf8 and name != ascii_name:
        utf8_part = quote(name, safe="")
        disposition += f"; filename*=UTF-8''{utf8_part}"
    return {
        "Content-Disposition": disposition,
        "Content-Type": mime,
    }


def _wp_media_post_response(resp):
    if resp.status_code in (200, 201):
        try:
            body = resp.json() or {}
        except Exception:
            body = {}
        src = body.get("source_url") or ""
        media_id = int(body.get("id") or 0)
        if src:
            return True, media_id, src, ""
        return False, 0, "", "آپلود OK ولی source_url خالی بود."
    detail = parse_wp_error_message(resp)
    hint = wp_auth_error_hint(resp, "")
    last_err = f"HTTP {resp.status_code} — {detail}"
    if hint:
        last_err += f" | {hint}"
    return False, 0, "", last_err


def response_is_waf_block_from_text(err_text: str) -> bool:
    text = (err_text or "").lower()
    return any(
        token in text
        for token in ("litespeed", "waf", "modsecurity", "cloudflare", "فایروال")
    )


def wp_media_waf_user_message(detail: str = "") -> str:
    """وقتی POST توسط هاست بسته شده (نه incorrect_password)."""
    body = (
        "فایروال LiteSpeed/WAF هاست، POST آپلود به wp-json/wp/v2/media را مسدود می‌کند.\n\n"
        "اگر Application Password را تازه ساختید ولی این خطا را می‌بینید، "
        "اول «رمز اشتباه» را رد کنید: تست باید incorrect_password ندهد.\n\n"
        "از پشتیبانی هاست بخواهید wp-json/wp/v2/media برای POST باز شود."
    )
    detail = (detail or "").strip()
    if detail:
        body += f"\n\n{detail}"
    return body


def _wp_media_post_once(
    config, endpoint, user, pwd, image_data, filename, fallback_stem, mode, *, user_agent=_UA_DEFAULT
):
    """یک تلاش آپلود — raw ساده، multipart، یا raw با filename*."""
    timeout = wc_timeout_pair(config)
    verify = wp_requests_verify(config)
    auth_hdr = wp_basic_auth_header(user, pwd)
    name, ascii_name, mime = wp_media_filename_parts(filename, fallback_stem=fallback_stem)

    if mode == "multipart":
        req_headers = wp_media_common_headers(auth_hdr, user_agent=user_agent)
        req_headers.update(_wp_media_site_headers(config))
        files = {"file": (ascii_name, image_data, mime)}
        try:
            resp = requests.post(
                endpoint,
                headers=req_headers,
                files=files,
                timeout=timeout,
                verify=verify,
            )
        except requests.exceptions.Timeout:
            return False, 0, "", "timeout — آپلود رسانه طول کشید."
        except requests.exceptions.SSLError as exc:
            return False, 0, "", f"خطای SSL: {exc}"
        except requests.exceptions.ConnectionError as exc:
            return False, 0, "", f"اتصال قطع شد: {exc}"
        except Exception as exc:
            return False, 0, "", str(exc)
        return _wp_media_post_response(resp)

    include_utf8 = mode == "raw_rfc5987"
    upload_headers = wp_media_upload_headers(
        filename, fallback_stem=fallback_stem, include_utf8=include_utf8
    )
    req_headers = wp_media_common_headers(upload_headers, user_agent=user_agent)
    req_headers.update(auth_hdr)
    req_headers.update(_wp_media_site_headers(config))
    try:
        resp = requests.post(
            endpoint,
            headers=req_headers,
            data=image_data,
            timeout=timeout,
            verify=verify,
        )
    except requests.exceptions.Timeout:
        return False, 0, "", "timeout — آپلود رسانه طول کشید."
    except requests.exceptions.SSLError as exc:
        return False, 0, "", f"خطای SSL: {exc}"
    except requests.exceptions.ConnectionError as exc:
        return False, 0, "", f"اتصال قطع شد: {exc}"
    except Exception as exc:
        return False, 0, "", str(exc)
    return _wp_media_post_response(resp)


_PROBE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _wp_delete_media(config, user, pwd, media_id):
    base = wp_media_base_url(config)
    if not base or not media_id:
        return
    url = f"{base}/wp-json/wp/v2/media/{int(media_id)}?force=true"
    try:
        requests.delete(
            url,
            headers=wp_media_common_headers(wp_basic_auth_header(user, pwd)),
            timeout=wc_timeout_pair(config),
            verify=wp_requests_verify(config),
        )
    except Exception:
        pass


def update_wp_media_alt_text(config, media_id, alt_text) -> tuple[bool, str]:
    """
    آپدیت alt_text یک رسانه — با همون مکانیزم احراز هویت آپلود (WP Application
    Password روی wp/v2/media)، نه wcapi (که کلید API ووکامرسه و اصلاً به
    wp/v2/media دسترسی نداره — استفاده‌ی اشتباه از wcapi برای این کار باعث
    می‌شد Alt واقعاً هیچ‌وقت ست نشه، حتی اگه ظاهراً خطایی هم نشون داده نمی‌شد).
    """
    if not media_id:
        return False, "شناسه‌ی رسانه نامعتبر است."

    user, pwd_raw = get_wp_media_credentials(config)
    if not user or not pwd_raw:
        return False, "WP Username یا Application Password خالی است (تنظیمات > ووکامرس)."

    base = wp_media_base_url(config)
    if not base:
        return False, "WC URL در تنظیمات خالی است."

    url = f"{base}/wp-json/wp/v2/media/{int(media_id)}"
    last_err = ""
    for pwd in wp_password_variants(pwd_raw):
        try:
            resp = requests.post(
                url,
                json={"alt_text": alt_text},
                headers=wp_media_common_headers(wp_basic_auth_header(user, pwd)),
                timeout=wc_timeout_pair(config),
                verify=wp_requests_verify(config),
            )
            if resp.status_code in (200, 201):
                return True, ""
            last_err = f"کد {resp.status_code}: {resp.text[:200]}"
            if resp.status_code == 401:
                continue  # شاید رمز نیاز به شکل دیگه‌ای داشته باشه، واریانت بعدی رو امتحان کن
        except Exception as exc:
            last_err = str(exc)
    return False, last_err or "آپدیت Alt رسانه ناموفق بود."


def _wp_media_try_all_upload_methods(
    config, endpoint, user, pwd, image_data, filename, fallback_stem
):
    last_err = ""
    upload_modes = ("raw_simple", "multipart", "raw_rfc5987")
    for ua in wp_media_upload_user_agents(config):
        for mode in upload_modes:
            ok, media_id, src, err = _wp_media_post_once(
                config,
                endpoint,
                user,
                pwd,
                image_data,
                filename,
                fallback_stem,
                mode,
                user_agent=ua,
            )
            if ok:
                return True, media_id, src, ""
            last_err = err or last_err
            if err and ("401" in err or "incorrect_password" in err.lower()):
                return False, 0, "", last_err
    return False, 0, "", last_err or "آپلود رسانه ناموفق بود."


def _probe_wp_media_post_upload(config, user, pwd) -> tuple[bool, str]:
    """POST واقعی کوچک — GET users/me کافی نیست؛ LiteSpeed فقط POST را می‌بندد."""
    endpoint = wp_media_endpoint(config)
    if not endpoint:
        return False, "WC URL در تنظیمات خالی است."
    probe_name = f"peecha-sync-probe-{int(time.time())}.png"
    ok, media_id, _src, err = _wp_media_try_all_upload_methods(
        config, endpoint, user, pwd, _PROBE_PNG, probe_name, "probe"
    )
    if ok:
        _wp_delete_media(config, user, pwd, media_id)
        return True, ""
    if response_is_waf_block_from_text(err):
        return False, wp_media_waf_user_message(err)
    return False, err or "آپلود آزمایشی به wp/v2/media ناموفق بود."


def wp_upload_media_ex(config, image_data, filename, fallback_stem="upload", label=""):
    """
    آپلود به wp/v2/media با Application Password.
    برمی‌گرداند: (ok, media_id, source_url, error_text)
    """
    apply_network_overrides(config)
    user, pwd_raw = get_wp_media_credentials(config)
    if not user or not pwd_raw:
        return False, 0, "", (
            "WP Username یا Application Password خالی است.\n"
            "تنظیمات > WP Username / WP App Password"
        )

    endpoint = wp_media_endpoint(config)
    if not endpoint:
        return False, 0, "", "WC URL در تنظیمات خالی است."

    last_err = ""

    for pwd in wp_password_variants(pwd_raw):
        ok, media_id, src, err = _wp_media_try_all_upload_methods(
            config,
            endpoint,
            user,
            pwd,
            image_data,
            filename,
            fallback_stem,
        )
        if ok:
            return True, media_id, src, ""
        last_err = err or last_err
        if err and ("401" in err or "incorrect_password" in err.lower()):
            break

    if response_is_waf_block_from_text(last_err):
        last_err = wp_media_waf_user_message(last_err)

    prefix = f"{label}: " if label else ""
    return False, 0, "", prefix + (last_err or "آپلود رسانه ناموفق بود.")


def wp_upload_media(config, image_data, filename, fallback_stem="upload", label=""):
    """نسخه سازگار قدیمی — (ok, source_url, error_text)."""
    ok, _media_id, src, err = wp_upload_media_ex(
        config, image_data, filename, fallback_stem=fallback_stem, label=label
    )
    return ok, src, err


def open_external_url(parent, url, empty_message=None):
    """باز کردن لینک در مرورگر — چند روش برای ویندوز."""
    import subprocess
    import webbrowser

    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QDesktopServices
    from PyQt5.QtWidgets import QApplication, QMessageBox

    url = (url or "").strip()
    if not url:
        QMessageBox.warning(
            parent,
            "آدرس ناقص",
            empty_message or "ابتدا WC URL فروشگاه را وارد کنید (مثلاً https://example.com).",
        )
        return False

    if QDesktopServices.openUrl(QUrl(url)):
        return True
    try:
        if webbrowser.open(url, new=2):
            return True
    except Exception:
        pass
    if os.name == "nt":
        try:
            os.startfile(url)
            return True
        except Exception:
            pass
        try:
            subprocess.Popen(["cmd", "/c", "start", "", url], close_fds=True)
            return True
        except Exception:
            pass

    clip = QApplication.clipboard()
    if clip is not None:
        clip.setText(url)
    QMessageBox.warning(
        parent,
        "باز نشد",
        f"مرورگر باز نشد. آدرس در کلیپبورد کپی شد:\n{url}",
    )
    return False
