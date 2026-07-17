"""واکشیِ زنده‌ی اطلاعاتِ محصول (لینکِ واقعیِ صفحه‌ی محصول + عکسِ اصلی) از
فروشگاه — برای پرکردنِ خودکارِ متن/عکسِ پست‌های تقویمِ محتوا، به‌جای
لینکِ حدسی (?p=ID که همیشه درست resolve نمی‌شه) یا نبودِ عکس."""

from __future__ import annotations

import os
import tempfile

import requests


def fetch_wc_product_content(config: dict, wc_id: int) -> dict:
    """{'permalink': ..., 'image_url': ...} — از خودِ پاسخِ WooCommerce API."""
    from sync_app.core.wc_sync_helper import build_wcapi, wc_call

    wcapi = build_wcapi(config)
    resp = wc_call(wcapi, "دریافتِ محصول برای تقویمِ محتوا", lambda: wcapi.get(f"products/{int(wc_id)}"))
    if resp is None or getattr(resp, "status_code", 0) != 200:
        return {"permalink": "", "image_url": ""}
    data = resp.json() or {}
    permalink = str(data.get("permalink") or "").strip()
    images = data.get("images") or []
    image_url = str((images[0] or {}).get("src") or "").strip() if images else ""
    return {"permalink": permalink, "image_url": image_url}


def fetch_ps_product_content(config: dict, wc_id: int) -> dict:
    """{'permalink': ..., 'image_url': ...} — لینک از فرمتِ همیشه-معتبرِ
    index.php?id_product=..، عکس با دانلودِ مستقیم از API (چون آدرسِ
    عمومیِ عکس به تنظیماتِ rewrite هر فروشگاه بستگی داره و قابلِ حدس نیست)."""
    from sync_app.core.ps_sync_helper import ps_get_product_image_ids, ps_rest_request

    site_url = str(config.get("PS_URL") or "").strip().rstrip("/")
    permalink = f"{site_url}/index.php?id_product={int(wc_id)}&controller=product" if site_url else ""

    image_url = ""
    try:
        image_ids = ps_get_product_image_ids(config, int(wc_id))
        if image_ids:
            resp = ps_rest_request(config, "GET", f"images/products/{int(wc_id)}/{image_ids[0]}")
            if getattr(resp, "status_code", 0) == 200 and resp.content:
                fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="peecha_ps_img_")
                with os.fdopen(fd, "wb") as f:
                    f.write(resp.content)
                image_url = tmp_path  # مسیرِ محلی — چون از قبل دانلود شده
    except Exception:
        image_url = ""

    return {"permalink": permalink, "image_url": image_url}


def fetch_product_content(config: dict, wc_id: int) -> dict:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if not wc_id:
        return {"permalink": "", "image_url": ""}
    if is_prestashop(config):
        return fetch_ps_product_content(config, wc_id)
    return fetch_wc_product_content(config, wc_id)


def download_image_to_temp(image_url: str, *, timeout: int = 30) -> str:
    """دانلودِ یک عکسِ ریموت (فقط برای WooCommerce لازمه — عکسِ PS از قبل
    لوکاله چون مستقیم از API دانلود شده). خروجی: مسیرِ فایلِ محلی، یا خالی."""
    url = (image_url or "").strip()
    if not url:
        return ""
    if os.path.isfile(url):
        return url  # از قبل یک فایلِ محلیه (مسیرِ PS)
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200 or not resp.content:
            return ""
        ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
        if len(ext) > 5:
            ext = ".jpg"
        fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="peecha_wc_img_")
        with os.fdopen(fd, "wb") as f:
            f.write(resp.content)
        return tmp_path
    except requests.RequestException:
        return ""
