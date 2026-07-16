"""چک آنلاین sql و woo برای badge بالا."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.sql_connection_helper import open_sql_connection, format_db_error
from sync_app.core.wc_api_helper import get_wc_auth, normalize_wc_store_url, wc_endpoint
from sync_app.core.wc_sync_helper import apply_network_overrides

_http_session: requests.Session | None = None


def _session() -> requests.Session:
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
    return _http_session

CACHE_KEY = "CONNECTIVITY_CACHE"

# رنگ ثابت — مستقل از تم (سبز/قرمز)
BADGE_ONLINE_STYLE = (
    "background-color: #16a34a; color: #ffffff; font-weight: 700;"
    " padding: 6px 14px; border-radius: 6px; border: 1px solid #14532d;"
)
BADGE_OFFLINE_STYLE = (
    "background-color: #dc2626; color: #ffffff; font-weight: 700;"
    " padding: 6px 14px; border-radius: 6px; border: 1px solid #991b1b;"
)
BADGE_PENDING_STYLE = (
    "background-color: #475569; color: #f1f5f9; font-weight: 600;"
    " padding: 6px 14px; border-radius: 6px; border: 1px solid #334155;"
)
# SQL — دو خط (وضعیت + نام DB) داخل همان badge
BADGE_ONLINE_STYLE_TALL = (
    "background-color: #16a34a; color: #ffffff;"
    " padding: 5px 12px 6px 12px; border-radius: 6px; border: 1px solid #14532d;"
)
BADGE_OFFLINE_STYLE_TALL = (
    "background-color: #dc2626; color: #ffffff;"
    " padding: 5px 12px 6px 12px; border-radius: 6px; border: 1px solid #991b1b;"
)
BADGE_PENDING_STYLE_TALL = (
    "background-color: #475569; color: #f1f5f9;"
    " padding: 5px 12px 6px 12px; border-radius: 6px; border: 1px solid #334155;"
)

# endpoint سبک — system_status سنگین است (~۵۰KB+)
_WC_PROBE_PATH = "settings/general/woocommerce_currency"


def load_connectivity_cache(config: dict | None = None) -> dict[str, Any]:
    cfg = config or load_secure_config(None) or {}
    raw = cfg.get(CACHE_KEY) or {}
    return raw if isinstance(raw, dict) else {}


def connectivity_cache_age_sec(config: dict | None = None) -> float | None:
    """ثانیه از آخرین پروب ذخیره‌شده — None اگر cache نباشد."""
    cached = load_connectivity_cache(config)
    at = cached.get("at")
    if not at:
        return None
    try:
        return max(0.0, time.time() - float(at))
    except (TypeError, ValueError):
        return None


def connectivity_age_label_fa(config: dict | None = None) -> str:
    age = connectivity_cache_age_sec(config)
    if age is None:
        return ""
    if age < 8:
        return "همین الان"
    if age < 60:
        return f"{int(age)} ثانیه پیش"
    if age < 3600:
        return f"{int(age // 60)} دقیقه پیش"
    return f"{int(age // 3600)} ساعت پیش"


def wc_offline_short_label(raw_msg: str) -> str:
    """یک برچسب کوتاه — سازگاری با کد قدیمی."""
    _title, sub = wc_badge_offline_lines(raw_msg)
    return sub


def _strip_wc_probe_msg(raw_msg: str) -> str:
    detail = (raw_msg or "").strip()
    for prefix in ("ووکامرس آفلاین:", "SQL آفلاین:", "ووکامرس:", "SQL:"):
        if detail.startswith(prefix):
            detail = detail[len(prefix):].strip()
            break
    return detail.split("\n")[0].strip()


def wc_badge_offline_lines(raw_msg: str, *, prefix: str = "Woo") -> tuple[str, str]:
    """
    دو خط badge فروشگاه (ووکامرس یا پرستاشاپ) وقتی آفلاین است.
    خط اول: عنوان | خط دوم: پیام دقیق خطا + اقدام.

    پیام دقیق (raw_msg) از خودِ چک اتصال پلتفرم فعال میاد (چه ووکامرس چه
    پرستاشاپ)، پس همیشه واقعیه — فقط برچسبِ عنوان (prefix) و چندتا پیشنهاد
    اقدامِ خیلی WC-محور (مثل «از REST API کلید جدید بگیرید») هنوز عمومی
    نشدن؛ برای پرستاشاپ ممکنه دقیق نباشن.
    """
    detail = _strip_wc_probe_msg(raw_msg)
    category = classify_network_error(raw_msg or detail)

    if "ناقص" in detail and "تنظیمات" in detail:
        return (
            f"{prefix} آفلاین · تنظیمات",
            "URL یا کلید API خالی است — فرم را کامل کنید و ذخیره بزنید",
        )

    if category == "auth":
        exact = detail or "کلید API نامعتبر"
        if any(k in exact.lower() for k in ("consumer", "401", "invalid signature")):
            exact = "Consumer Key/Secret نامعتبر"
        return (
            f"{prefix} آفلاین · کلید API",
            f"{exact} — کلید منقضی/نامعتبر است؛ کلید جدید بسازید",
        )

    if category == "vpn_tunnel":
        exact = detail[:90] if detail else "VPN/تونل ناقص"
        return (
            f"{prefix} آفلاین · VPN/Docker",
            f"{exact} — VPN را Exit کنید، Docker را ببندید، دوباره تست کنید",
        )

    if category == "timeout":
        exact = detail or "timeout"
        return (
            f"{prefix} آفلاین · Timeout",
            f"{exact} — شبکه کند یا فیلتر/VPN؛ اتصال را عوض کنید",
        )

    if category == "dns":
        exact = detail or "DNS"
        return (
            f"{prefix} آفلاین · DNS",
            f"{exact} — اینترنت/DNS را چک کنید یا VPN را قطع/وصل کنید",
        )

    if category == "ssl":
        exact = detail or "SSL"
        return (
            f"{prefix} آفلاین · SSL",
            f"{exact} — VPN را قطع/وصل کنید یا SSL را در تنظیمات بررسی کنید",
        )

    if category == "forbidden" or "403" in (raw_msg or "").lower():
        exact = detail or "HTTP 403"
        return (
            f"{prefix} آفلاین · 403",
            f"{exact} — کلید API باید مربوط به همین فروشگاه در تنظیمات باشد",
        )

    if category == "refused":
        exact = detail or "اتصال رد شد"
        return (
            f"{prefix} آفلاین · دسترسی",
            f"{exact} — فایروال یا پورت بسته",
        )

    if "404" in (raw_msg or "").lower() or "404" in detail:
        return (
            f"{prefix} آفلاین · آدرس API",
            "آدرس API پیدا نشد (404) — آدرس سایت را در تنظیمات بررسی کنید",
        )

    if detail:
        return (f"{prefix} آفلاین", f"{detail} — تنظیمات و شبکه را بررسی کنید")

    return (f"{prefix} آفلاین", "اتصال برقرار نشد — «تست اتصال» را بزنید")


def save_connectivity_cache(
    sql_ok: bool,
    sql_msg: str,
    wc_ok: bool,
    wc_msg: str,
    *,
    sql_ms: float = 0,
    wc_ms: float = 0,
) -> None:
    try:
        cfg = load_secure_config(None) or {}
        cfg[CACHE_KEY] = {
            "sql_ok": bool(sql_ok),
            "sql_msg": str(sql_msg or ""),
            "wc_ok": bool(wc_ok),
            "wc_msg": str(wc_msg or ""),
            "sql_ms": round(float(sql_ms or 0), 1),
            "wc_ms": round(float(wc_ms or 0), 1),
            "at": time.time(),
        }
        save_secure_config(cfg)
    except Exception:
        pass


def classify_network_error(message: str) -> str:
    text = (message or "").lower()
    if any(
        token in text
        for token in (
            "vpn/تونل",
            "vpn/تونل ناقص",
            "tunnel",
            "docker/wsl",
            "آداپتور مجازی",
            "172.18.",
            "172.17.",
        )
    ):
        return "vpn_tunnel"
    if any(token in text for token in ("getaddrinfo", "11001", "name or service not known", "nodename nor servname")):
        return "dns"
    if any(token in text for token in ("timed out", "timeout", "connecttimeout", "readtimeout")):
        return "timeout"
    if any(token in text for token in ("connection refused", "10061", "actively refused")):
        return "refused"
    if "401" in text or "consumer key" in text or "invalid signature" in text:
        return "auth"
    if "403" in text or "forbidden" in text:
        return "forbidden"
    if "نامعتبر" in text and any(k in text for k in ("consumer", "کلید", "api", "secret")):
        return "auth"
    if "ssl" in text or "certificate" in text or "unexpected_eof" in text or "ssleoferror" in text:
        return "ssl"
    return "unknown"


def network_error_user_hint(category: str, *, target: str = "WooCommerce") -> str:
    hints = {
        "dns": (
            f"اینترنت یا DNS در دسترس نیست و {target} پیدا نشد.\n"
            "سیم‌کارت/Wi‑Fi را عوض کنید، VPN را یک‌بار قطع/وصل کنید، "
            "سپس دوباره همگام‌سازی را بزنید."
        ),
        "timeout": (
            f"شبکه به {target} وصل شد اما پاسخ دیر رسید (timeout).\n"
            "اتصال کند است — چند ثانیه صبر کنید یا سیم‌کارت/شبکه دیگر امتحان کنید."
        ),
        "refused": (
            f"سرور {target} درخواست را رد کرد.\n"
            "آدرس فروشگاه یا فایروال/پروکسی را بررسی کنید."
        ),
        "forbidden": (
            f"سرور {target} دسترسی API را رد کرد (403 Forbidden).\n"
            "Consumer Key/Secret همین سایت را با دسترسی Read/Write بسازید، "
            "«ذخیره تنظیمات» را بزنید، و WAF/افزونه امنیتی را بررسی کنید."
        ),
        "auth": (
            f"کلید API {target} نامعتبر یا منقضی شده.\n"
            "WooCommerce → Settings → Advanced → REST API → کلید جدید Read/Write بسازید، "
            "سپس Consumer Key/Secret را ذخیره و تست کنید."
        ),
        "ssl": (
            f"خطای SSL در اتصال به {target}.\n"
            "معمولاً موقت است — دوباره تست کنید.\n"
            "VPN/فیلترشکن را یک‌بار قطع/وصل کنید؛ در صورت تداوم «تأیید SSL» را در تنظیمات بررسی کنید."
        ),
        "vpn_tunnel": (
            f"اتصال به {target} از تونل/VPN ناقص رد می‌شود.\n"
            "TCP وصل می‌شود اما HTTPS قطع می‌شود — badge قرمز می‌ماند.\n\n"
            "راه‌حل:\n"
            "• VPN را کاملاً ببندید (Exit از برنامه، نه فقط Disconnect)\n"
            "• Docker Desktop یا WSL را در صورت نیاز خاموش کنید\n"
            "• پس از تعویض سیم‌کارت: حالت پرواز ON/OFF\n"
            "• در صورت تداوم: restart ویندوز"
        ),
        "unknown": (
            f"اتصال به {target} برقرار نشد.\n"
            "اینترنت، VPN و تنظیمات فروشگاه را بررسی کنید."
        ),
    }
    return hints.get(category, hints["unknown"])


def format_network_error_message(error, config=None) -> str:
    """پیام خطای شبکه/API برای نمایش در تب‌های مشتریان و سفارشات."""
    from urllib.parse import urlparse

    raw = str(error or "").strip()
    if not raw:
        return network_error_user_hint("unknown")

    # پیام از wc_http_error_message یا format_recon_load_error
    if "\n" in raw and any(
        token in raw
        for token in ("کلید API", "Forbidden", "403", "WooCommerce →", "Consumer Key")
    ):
        return raw

    cfg = config or {}
    host = urlparse(str(cfg.get("WC_URL") or "")).netloc
    target = f"فروشگاه ({host})" if host else "WooCommerce"
    return network_error_user_hint(classify_network_error(raw), target=target)


def describe_offline_reason(raw_msg: str, *, target: str = "WooCommerce", host: str = "") -> str:
    """یک خط فارسی — علت احتمالی قطع اتصال از نتیجه پروب واقعی."""
    import re

    msg = (raw_msg or "").strip()
    if not msg:
        return f"{target}: هنوز بررسی نشده — چند ثانیه صبر کنید"

    detail = msg
    for prefix in ("ووکامرس آفلاین:", "SQL آفلاین:", "ووکامرس:", "SQL:"):
        if detail.startswith(prefix):
            detail = detail[len(prefix):].strip()
            break
    detail = detail.split("\n(یک timeout")[0].strip()
    detail = detail.split("\n")[0].strip()

    host_label = (host or "").strip() or target
    text = detail.lower()

    http_match = re.search(r"http\s*(\d{3})", text)
    if http_match:
        code = int(http_match.group(1))
        http_hints = {
            401: f"کلید API {host_label} نامعتبر — Consumer Key/Secret را در تنظیمات بررسی کنید",
            403: (
                f"سرور {host_label} دسترسی API را رد کرد (403) — "
                "کلید REST با Read/Write، WAF/Wordfence، یا مسدودیت IP"
            ),
            404: f"آدرس API {host_label} پیدا نشد (404) — WC_URL در تنظیمات را بررسی کنید",
            500: f"خطای داخلی سرور وردپرس {host_label} (500)",
            502: f"هاست/پروکسی {host_label} در دسترس نیست (502)",
            503: f"سرور {host_label} موقتاً overload یا در تعمیر است (503)",
            504: f"Gateway timeout — سرور {host_label} به موقع پاسخ نداد (504)",
        }
        if code in http_hints:
            return http_hints[code]

    if "consumer key" in text or "invalid signature" in text:
        return f"کلید API {host_label} نامعتبر — Consumer Key/Secret"

    if "تنظیمات" in detail and "ناقص" in detail:
        return detail

    if "timeout پاسخ" in detail or "response timeout" in text:
        return (
            f"سرور {host_label} پاسخ نمی‌دهد (timeout) — "
            "کندی شبکه، فیلتر، VPN، یا مسدودیت IP/کشور"
        )
    if "timeout اتصال" in detail or "connecttimeout" in text:
        return (
            f"اتصال TCP به {host_label} برقرار نشد — "
            "فیلتر، VPN، DNS، یا مسدودیت IP/کشور"
        )

    category = classify_network_error(detail)
    category_reasons = {
        "dns": f"دامنه {host_label} resolve نمی‌شود — DNS، قطع اینترنت، یا فیلتر",
        "timeout": (
            f"به {host_label} می‌رسد اما پاسخ نمی‌دهد — "
            "timeout؛ فیلتر، VPN، کندی، یا مسدودیت IP/کشور"
        ),
        "refused": f"سرور {host_label} اتصال را رد کرد — فایروال، پورت بسته، یا سرویس خاموش",
        "forbidden": (
            f"سرور {host_label} API را رد کرد (403) — "
            "Consumer Key/Secret Read/Write یا WAF/Wordfence"
        ),
        "auth": f"احراز هویت API {host_label} ناموفق — Consumer Key/Secret",
        "ssl": f"خطای SSL به {host_label} — گواهی، VPN، یا MiTM",
        "vpn_tunnel": (
            f"احتمال VPN/تونل ناقص (Docker/WSL) — {host_label} از مسیر مجازی رد می‌شود؛ "
            "HTTPS قطع می‌شود"
        ),
        "unknown": f"اتصال به {host_label} برقرار نشد",
    }
    reason = category_reasons.get(category, category_reasons["unknown"])
    if detail and detail not in reason and len(detail) <= 100:
        return f"{reason} — {detail}"
    return reason


def probe_sql(config: dict | None) -> tuple[bool, str, float]:
    from sync_app.core.integrations.erp_provider import erp_provider_label

    config = config or {}
    erp_label = erp_provider_label(config)
    t0 = time.perf_counter()
    server = (config.get("SQL_SERVER") or "").strip()
    database = (config.get("SQL_DATABASE") or "").strip()
    if not server or not database:
        return False, f"تنظیمات {erp_label} ناقص است", 0.0

    conn = None
    try:
        import pyodbc  # noqa: F401

        conn, auth_mode, _ = open_sql_connection(config, timeout=4)
        cur = conn.cursor()
        cur.execute("SELECT DB_NAME(), @@SERVERNAME")
        row = cur.fetchone()
        db_name = row[0] if row and row[0] else database
        db_server = row[1] if row and len(row) > 1 and row[1] else server
        ms = (time.perf_counter() - t0) * 1000
        return (
            True,
            f"{erp_label} آنلاین ({ms:.0f}ms) | DB={db_name} | Server={db_server} | Auth={auth_mode}",
            ms,
        )
    except Exception as exc:
        ms = (time.perf_counter() - t0) * 1000
        return False, f"{erp_label} آفلاین: {format_db_error(exc)[:160]}", ms
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _wc_probe_urls(config: dict) -> list[str]:
    return [
        wc_endpoint(config.get("WC_URL", ""), _WC_PROBE_PATH),
        wc_endpoint(config.get("WC_URL", ""), ""),
    ]


def _verify_wc_categories_api(config, session, auth, verify, probe_timeout) -> tuple[bool, str]:
    """همان endpoint همگام‌سازی دسته — تست سبک settings کافی نیست."""
    from sync_app.core.diagnostics import format_wc_error
    from sync_app.core.wc_sync_helper import wc_rest_json

    try:
        data = wc_rest_json(
            config,
            "GET",
            "products/categories",
            params={"per_page": 1, "_fields": "id"},
            label="products/categories",
            timeout=probe_timeout,
        )
        if not isinstance(data, list):
            return False, "پاسخ نامعتبر از products/categories (لیست JSON نیست)."
        return True, ""
    except Exception as exc:
        return False, format_wc_error(exc=exc, config=config)


def _reset_http_session() -> None:
    global _http_session
    _http_session = None


def _enrich_wc_failure(config: dict, last_err: str) -> tuple[str, str]:
    """اگر timeout/ssl باشد، تونل VPN ناقص را بررسی کن."""
    category = classify_network_error(last_err)
    if category not in ("timeout", "ssl"):
        return f"ووکامرس آفلاین: {last_err}", category

    from sync_app.core.network_route_check import detect_broken_tunnel, host_from_url

    host = host_from_url(config.get("WC_URL", ""))
    tunnel = detect_broken_tunnel(host, wc_failed_timeout_or_ssl=True)
    if tunnel.get("suspected"):
        msg = str(tunnel.get("user_message_fa") or "").strip()
        if msg:
            return f"ووکامرس آفلاین: {msg}", "vpn_tunnel"
    return f"ووکامرس آفلاین: {last_err}", category


def _probe_ps_once(config: dict | None, *, fast: bool = False) -> tuple[bool, str, float]:
    from sync_app.core.ps_sync_helper import check_prestashop_connection

    t0 = time.perf_counter()
    ok, msg, _currency = check_prestashop_connection(config or {})
    ms = (time.perf_counter() - t0) * 1000
    if ok:
        return True, f"پرستاشاپ آنلاین ({ms:.0f}ms)", ms
    return False, msg, ms


def _probe_wc_once(config: dict | None, *, fast: bool = False) -> tuple[bool, str, float]:
    config = config or {}

    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        return _probe_ps_once(config, fast=fast)

    apply_network_overrides(config)

    base = normalize_wc_store_url(config.get("WC_URL", ""))
    ck, cs = get_wc_auth(config)
    if not base or not ck or not cs:
        return False, "تنظیمات ووکامرس ناقص است", 0.0

    verify = bool(config.get("WC_VERIFY_SSL", False))
    auth = (ck, cs)
    session = _session()
    t0 = time.perf_counter()
    last_err = ""

    try:
        from sync_app.core.wc_sync_helper import wc_timeout_pair

        connect, read = wc_timeout_pair(config)
        if fast:
            probe_timeout = (4, 12)
        else:
            probe_timeout = (min(connect, 12), min(read, 25))
    except Exception:
        probe_timeout = (4, 12) if fast else (8, 20)

    for url in _wc_probe_urls(config):
        if not url:
            continue
        try:
            resp = session.get(
                url,
                auth=auth,
                timeout=probe_timeout,
                verify=verify,
                headers={"Accept": "application/json", "User-Agent": "PeechaSync/1.0"},
            )
            ms = (time.perf_counter() - t0) * 1000
            if resp.status_code == 200:
                if not fast:
                    cat_ok, cat_msg = _verify_wc_categories_api(
                        config, session, auth, verify, probe_timeout
                    )
                    if not cat_ok:
                        return False, cat_msg, ms
                    return True, f"ووکامرس آنلاین ({ms:.0f}ms) | API دسته‌بندی OK", ms
                return True, f"ووکامرس آنلاین ({ms:.0f}ms)", ms
            if resp.status_code == 401:
                return False, "ووکامرس: Consumer Key/Secret نامعتبر", ms
            last_err = f"HTTP {resp.status_code}"
        except requests.exceptions.ConnectTimeout:
            last_err = "timeout اتصال"
            break
        except requests.exceptions.ReadTimeout:
            last_err = "timeout پاسخ"
            break
        except Exception as exc:
            last_err = str(exc)[:160]
            if classify_network_error(last_err) == "ssl":
                _reset_http_session()

    ms = (time.perf_counter() - t0) * 1000
    if fast:
        if last_err:
            return False, f"ووکامرس آفلاین: {last_err}", ms
        return False, "ووکامرس آفلاین: نامشخص", ms
    fail_msg, _category = _enrich_wc_failure(config, last_err or "نامشخص")
    return False, fail_msg, ms


def probe_wc(config: dict | None, *, attempts: int = 2, fast: bool = False) -> tuple[bool, str, float]:
    config = config or {}
    attempts = 1 if fast else max(1, int(attempts))
    last: tuple[bool, str, float] = (False, "", 0.0)
    for attempt in range(attempts):
        last = _probe_wc_once(config, fast=fast)
        if last[0]:
            return last
        category = classify_network_error(last[1])
        if attempt < attempts - 1 and category in ("timeout", "ssl", "unknown"):
            time.sleep(1.0 + attempt)
            _reset_http_session()
    return last


def probe_all(config: dict | None = None) -> dict[str, Any]:
    """sql و woo رو همزمان ping کن."""
    config = dict(config or load_secure_config(None) or {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        sql_f = pool.submit(probe_sql, config)
        wc_f = pool.submit(probe_wc, config)
        sql_ok, sql_msg, sql_ms = sql_f.result()
        wc_ok, wc_msg, wc_ms = wc_f.result()

    wc_category = "ok" if wc_ok else classify_network_error(wc_msg)
    save_connectivity_cache(sql_ok, sql_msg, wc_ok, wc_msg, sql_ms=sql_ms, wc_ms=wc_ms)
    return {
        "sql_ok": sql_ok,
        "sql_msg": sql_msg,
        "sql_ms": sql_ms,
        "sql_category": "ok" if sql_ok else classify_network_error(sql_msg),
        "wc_ok": wc_ok,
        "wc_msg": wc_msg,
        "wc_ms": wc_ms,
        "wc_category": wc_category,
    }


def probe_all_robust(
    config: dict | None = None,
    *,
    wc_attempts: int = 3,
    sql_attempts: int = 2,
    pause_sec: float = 1.5,
) -> dict[str, Any]:
    """
    قبل از sync: چند بار تلاش با فاصله — برای سیم‌کارت/شبکه‌های ناپایدار.
    """
    config = dict(config or load_secure_config(None) or {})
    wc_attempts = max(1, int(wc_attempts))
    sql_attempts = max(1, int(sql_attempts))

    sql_ok, sql_msg, sql_ms = False, "", 0.0
    sql_category = "unknown"
    for attempt in range(sql_attempts):
        sql_ok, sql_msg, sql_ms = probe_sql(config)
        if sql_ok:
            sql_category = "ok"
            break
        sql_category = classify_network_error(sql_msg)
        if attempt < sql_attempts - 1:
            time.sleep(pause_sec)

    wc_ok, wc_msg, wc_ms = False, "", 0.0
    wc_category = "unknown"
    for attempt in range(wc_attempts):
        wc_ok, wc_msg, wc_ms = probe_wc(config)
        if wc_ok:
            wc_category = "ok"
            break
        wc_category = classify_network_error(wc_msg)
        if attempt < wc_attempts - 1:
            time.sleep(pause_sec * (attempt + 1))

    save_connectivity_cache(sql_ok, sql_msg, wc_ok, wc_msg, sql_ms=sql_ms, wc_ms=wc_ms)
    return {
        "sql_ok": sql_ok,
        "sql_msg": sql_msg,
        "sql_ms": sql_ms,
        "sql_category": sql_category,
        "wc_ok": wc_ok,
        "wc_msg": wc_msg,
        "wc_ms": wc_ms,
        "wc_category": wc_category,
        "attempts": {"wc": wc_attempts, "sql": sql_attempts},
    }


def wc_offline_tooltip(raw_msg: str, *, host: str = "", target: str = "WooCommerce") -> str:
    """متن tooltip/badge برای قطع فروشگاه (ووکامرس یا پرستاشاپ) — با تشخیص VPN در صورت امکان."""
    from sync_app.core.network_route_check import host_from_url

    host_label = host_from_url(host) if "://" in (host or "") else (host or "").strip()
    if not host_label:
        host_label = "فروشگاه"
    return describe_offline_reason(raw_msg, target=target, host=host_label)
