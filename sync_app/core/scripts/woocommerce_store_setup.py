"""ساخت صفحات cart/checkout در وردپرس."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

try:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
    from sync_app.core.sync_utils import log
    from sync_app.core.wc_api_helper import normalize_wc_store_url
    from sync_app.core.wc_sync_helper import (
        apply_network_overrides,
        build_wcapi,
        format_wc_network_error,
        wc_call,
        wc_sync_timeout,
    )
except ImportError:
    import os

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
    from sync_app.core.sync_utils import log
    from sync_app.core.wc_api_helper import normalize_wc_store_url
    from sync_app.core.wc_sync_helper import (
        apply_network_overrides,
        build_wcapi,
        format_wc_network_error,
        wc_call,
        wc_sync_timeout,
    )


PAGE_SETTINGS = (
    ("cart", "woocommerce_cart_page_id", "cart"),
    ("checkout", "woocommerce_checkout_page_id", "checkout"),
    ("myaccount", "woocommerce_myaccount_page_id", "my-account"),
)

# setup UI — یک تلاش برای خواندن؛ retry فقط برای install_pages
_SETUP_FETCH_RETRIES = 0
_SETUP_INSTALL_RETRIES = 1


def _log_step(msg):
    log.info(f"▸ {msg}")


def _timeout(config) -> int:
    try:
        return max(10, min(int((config or {}).get("WC_TIMEOUT", 60) or 60), 120))
    except Exception:
        return 60


def _wp_base(config) -> str:
    return normalize_wc_store_url((config or {}).get("WC_URL", ""))


def _get_single_setting(wcapi, setting_id):
    data = wcapi.get(f"settings/advanced/{setting_id}").json()
    if isinstance(data, dict):
        return data.get("value")
    raise RuntimeError(f"پاسخ نامعتبر برای {setting_id}")


def _fetch_advanced_bulk(wcapi):
    def _get():
        data = wcapi.get("settings/advanced").json()
        if not isinstance(data, list):
            raise RuntimeError(f"پاسخ نامعتبر settings/advanced: {data}")
        return {str(item.get("id")): item.get("value") for item in data if isinstance(item, dict)}

    return wc_call(wcapi, "settings/advanced", _get, retries=_SETUP_FETCH_RETRIES)


def _has_cart_checkout(advanced_map):
    needed = {sid for name, sid, _ in PAGE_SETTINGS if name in ("cart", "checkout")}
    return needed.issubset({sid for sid, val in advanced_map.items() if val})


def _fetch_missing_only(wcapi, advanced_map):
    for name, sid, _ in PAGE_SETTINGS:
        if advanced_map.get(sid):
            continue
        try:
            val = _get_single_setting(wcapi, sid)
            advanced_map[sid] = val
            log.info(f"  {name} → {val or '—'}")
        except Exception as exc:
            log.warning(f"  ⚠️ {name}: {exc}")
    return advanced_map


def _fetch_page_ids(wcapi, config):
    """۳ تا setting جدا بزن."""
    _log_step("بررسی Cart / Checkout / My Account...")
    advanced_map = {}
    wait_sec = wc_sync_timeout(config) + 5

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_get_single_setting, wcapi, sid): (name, sid)
            for name, sid, _ in PAGE_SETTINGS
        }
        try:
            for fut in as_completed(futures, timeout=wait_sec):
                name, sid = futures[fut]
                try:
                    val = fut.result()
                    advanced_map[sid] = val
                    log.info(f"  {name} → {val or '—'}")
                except Exception as exc:
                    log.warning(f"  ⚠️ {name}: {exc}")
        except TimeoutError:
            log.warning("⚠️ timeout در دریافت settings — ادامه با fallback")

    if len(advanced_map) < 3:
        if _has_cart_checkout(advanced_map):
            advanced_map = _fetch_missing_only(wcapi, advanced_map)
        else:
            try:
                bulk = _fetch_advanced_bulk(wcapi)
                for _, sid, _ in PAGE_SETTINGS:
                    if sid not in advanced_map and sid in bulk:
                        advanced_map[sid] = bulk[sid]
            except Exception as exc:
                log.warning(f"⚠️ settings/advanced: {exc}")
                advanced_map = _fetch_missing_only(wcapi, advanced_map)

    return advanced_map


def _apply_cache(advanced_map, config):
    cached = (config or {}).get("WC_STORE_PAGES") or {}
    if not isinstance(cached, dict):
        return advanced_map
    for name, sid, _ in PAGE_SETTINGS:
        if not advanced_map.get(sid):
            pid = cached.get(name)
            if pid:
                advanced_map[sid] = pid
                log.info(f"  {name} → {pid} (cache)")
    return advanced_map


def _save_cache(config, by_name):
    try:
        cfg = load_secure_config(None) or dict(config or {})
        cfg["WC_STORE_PAGES"] = {
            name: int((by_name.get(name) or {}).get("page_id") or 0)
            for name, _, _ in PAGE_SETTINGS
        }
        save_secure_config(cfg)
    except Exception:
        pass


def _read_page_ids(advanced_map):
    result = {}
    for name, setting_id, slug in PAGE_SETTINGS:
        raw = advanced_map.get(setting_id)
        try:
            page_id = int(raw) if raw not in (None, "", "0") else 0
        except (TypeError, ValueError):
            page_id = 0
        result[name] = {
            "page_name": name,
            "page_id": page_id,
            "slug": slug,
            "page_set": page_id > 0,
            "page_exists": page_id > 0,
        }
    return result


def _pages_summary(by_name):
    for name, _, _ in PAGE_SETTINGS:
        item = by_name.get(name) or {}
        page_id = item.get("page_id") or 0
        mark = "✅" if page_id > 0 else "❌"
        log.info(f"{mark} {name} → ID={page_id}")


def _core_pages_ready(by_name):
    return all((by_name.get(name) or {}).get("page_id", 0) > 0 for name, _, _ in PAGE_SETTINGS)


def _checkout_pages_ready(by_name):
    return all(
        (by_name.get(name) or {}).get("page_id", 0) > 0
        for name, _, _ in PAGE_SETTINGS
        if name in ("cart", "checkout")
    )


def _install_wc_pages(wcapi):
    def _put():
        resp = wcapi.put("system_status/tools/install_pages", {})
        data = resp.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(data.get("message") or str(data))
        return data

    return wc_call(wcapi, "install_pages", _put, retries=_SETUP_INSTALL_RETRIES)


def _install_succeeded(result):
    if not isinstance(result, dict):
        return bool(result)
    if result.get("success") is False:
        return False
    return True


def _check_public_url(config, slug, page_id=0):
    base = _wp_base(config)
    if not base:
        return False, "WC_URL خالی است"
    url = f"{base}/{slug}/"
    try:
        resp = requests.get(
            url,
            timeout=12,
            allow_redirects=True,
            verify=bool((config or {}).get("WC_VERIFY_SSL", False)),
        )
    except Exception as exc:
        return False, f"timeout: {exc}"

    text = resp.text or ""
    lower = text.lower()
    blog_fallback = "چیزی پیدا نشد" in text or (">بلاگ<" in lower and "woocommerce" not in lower)
    page_marker = f"page-id-{page_id}" in lower if page_id else False
    good = page_marker or any(
        m in lower
        for m in (
            "woocommerce-cart",
            "woocommerce-checkout",
            "woocommerce-account",
            "woocommerce/assets",
            "wc-blocks",
            "wc-block-cart",
            "wc-block-checkout",
            "woocommerce-page",
        )
    )
    ok = resp.status_code == 200 and good and not blog_fallback
    detail = f"HTTP {resp.status_code}"
    if ok:
        detail += f" — page-id-{page_id}" if page_marker else " — OK"
    elif blog_fallback:
        detail += " — بلاگ/404"
    return ok, detail


def ensure_store_pages(config=None, *, force_install=False, verify_urls=False):
    config = config or load_secure_config(None) or {}
    apply_network_overrides(config)
    wcapi = build_wcapi(config)

    report = {
        "ready": False,
        "installed": False,
        "pages": {},
        "verified": [],
        "warnings": [],
    }

    install_result = None

    cached = _apply_cache({}, config)
    cached_by_name = _read_page_ids(cached)
    if _checkout_pages_ready(cached_by_name) and not force_install:
        _log_step("Cart/Checkout از cache — بدون انتظار API")
        report["pages"] = cached_by_name
        _pages_summary(cached_by_name)
        report["ready"] = True
        return report

    advanced = _apply_cache(_fetch_page_ids(wcapi, config), config)
    by_name = _read_page_ids(advanced)
    report["pages"] = by_name
    _pages_summary(by_name)

    if _checkout_pages_ready(by_name) and not force_install:
        _log_step("Cart و Checkout از قبل تنظیم شده‌اند")
        if not _core_pages_ready(by_name):
            log.warning("⚠️ My Account هنوز تأیید نشد — checkout کار می‌کند")
        report["ready"] = True
    else:
        _log_step("اجرای install_pages...")
        install_result = _install_wc_pages(wcapi)
        msg = (install_result or {}).get("message") if isinstance(install_result, dict) else str(install_result)
        log.info(f"✅ install_pages: {msg or 'انجام شد'}")
        report["installed"] = True

        fetched = _fetch_page_ids(wcapi, config)
        advanced = _apply_cache({**advanced, **fetched}, config)
        by_name = _read_page_ids(advanced)
        report["pages"] = by_name
        _pages_summary(by_name)
        report["ready"] = _checkout_pages_ready(by_name)

        if not report["ready"] and _install_succeeded(install_result):
            log.warning("⚠️ install_pages موفق بود — API کند است، checkout احتمالاً آماده است")
            report["ready"] = True
            report["warnings"].append("تأیید ID از API timeout — install_pages موفق بود")

    if not report["ready"]:
        raise RuntimeError(
            "صفحات Cart/Checkout تنظیم نشدند.\n"
            "Consumer Key باید Write داشته باشد و اتصال پایدار باشد."
        )

    if _checkout_pages_ready(by_name):
        _save_cache(config, by_name)

    if verify_urls:
        _log_step("بررسی URL عمومی (اختیاری)...")
        for name, _, slug in PAGE_SETTINGS:
            page_id = (by_name.get(name) or {}).get("page_id") or 0
            ok, detail = _check_public_url(config, slug, page_id=page_id)
            if ok:
                report["verified"].append(f"/{slug}/ {detail}")
                log.info(f"✅ /{slug}/ — {detail}")
            else:
                report["warnings"].append(f"/{slug}/ — {detail}")
                log.warning(f"⚠️ /{slug}/ — {detail}")

    return report


STORE_SETUP_USER_HINT = (
    "صفحات Cart و Checkout در فروشگاه WooCommerce تنظیم نشده‌اند.\n"
    "بدون این صفحات مشتریان نمی‌توانند خرید کنند و سفارش جدیدی ثبت نمی‌شود.\n\n"
    "رفع مشکل:\n"
    "• به تب «تنظیمات» بروید\n"
    "• دکمه «راه‌اندازی Cart/Checkout» را بزنید\n"
    "• منتظر پیام موفق بمانید، سپس دوباره تلاش کنید"
)


class StorePagesNotReadyError(RuntimeError):
    """صفحات ضروری فروشگاه (Cart/Checkout) آماده نیستند."""


def store_pages_ready(config=None) -> bool:
    """بررسی سریع از cache — بدون فراخوانی API."""
    config = config or load_secure_config(None) or {}
    return _checkout_pages_ready(_read_page_ids(_apply_cache({}, config)))


def store_setup_user_message() -> str:
    return STORE_SETUP_USER_HINT


def store_pages_status_line(config=None) -> str:
    config = config or load_secure_config(None) or {}
    by_name = _read_page_ids(_apply_cache({}, config))
    parts = []
    for name, _, _ in PAGE_SETTINGS:
        pid = (by_name.get(name) or {}).get("page_id") or 0
        mark = "+" if pid > 0 else "-"
        parts.append(f"{name} {mark}")
    return " | ".join(parts)


def main(config=None, *, verify_urls=False):
    _log_step("شروع راه‌اندازی WooCommerce")
    try:
        report = ensure_store_pages(config, verify_urls=verify_urls)
    except Exception as exc:
        raise RuntimeError(format_wc_network_error(exc)) from exc

    log.info(
        f"📊 پایان — آماده:{report['ready']} | "
        f"install:{report['installed']} | URL OK:{len(report['verified'])}"
    )
    return report


if __name__ == "__main__":
    main()
