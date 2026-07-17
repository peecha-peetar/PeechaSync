"""واکشیِ زنده‌ی اطلاعاتِ محصول (لینکِ واقعیِ صفحه‌ی محصول + عکس‌ها + توضیح)
از فروشگاه — برای پرکردنِ خودکارِ متن/عکسِ پست‌های تقویمِ محتوا، به‌جای
لینکِ حدسی (?p=ID که همیشه درست resolve نمی‌شه) یا نبودِ عکس. عکسِ اصلی
(image_url) هنوز برای سازگاری با کدِ قدیمی برگردونده می‌شه؛ image_urls
همه‌ی عکس‌های محصول رو برمی‌گردونه (برای «همه‌ی عکس‌های سایط» در یک پست)."""

from __future__ import annotations

import html
import os
import re
import tempfile

import requests

_EMPTY_CONTENT = {"permalink": "", "image_url": "", "image_urls": [], "description": ""}


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_wc_product_content(config: dict, wc_id: int) -> dict:
    """{'permalink', 'image_url', 'image_urls', 'description'} — از خودِ پاسخِ WooCommerce API."""
    from sync_app.core.wc_sync_helper import build_wcapi, wc_call

    wcapi = build_wcapi(config)
    resp = wc_call(wcapi, "دریافتِ محصول برای تقویمِ محتوا", lambda: wcapi.get(f"products/{int(wc_id)}"))
    if resp is None or getattr(resp, "status_code", 0) != 200:
        return dict(_EMPTY_CONTENT)
    data = resp.json() or {}
    permalink = str(data.get("permalink") or "").strip()
    images = data.get("images") or []
    image_urls = [str((img or {}).get("src") or "").strip() for img in images]
    image_urls = [u for u in image_urls if u]
    image_url = image_urls[0] if image_urls else ""
    description = _strip_html(data.get("short_description") or data.get("description") or "")
    return {"permalink": permalink, "image_url": image_url, "image_urls": image_urls, "description": description}


def fetch_ps_product_content(config: dict, wc_id: int) -> dict:
    """{'permalink', 'image_url', 'image_urls', 'description'} — لینک از فرمتِ
    همیشه-معتبرِ index.php?id_product=..، عکس‌ها با دانلودِ مستقیم از API
    (چون آدرسِ عمومیِ عکس به تنظیماتِ rewrite هر فروشگاه بستگی داره و
    قابلِ حدس نیست)."""
    from sync_app.core.ps_sync_helper import (
        ps_call, ps_get_product_image_ids, ps_rest_request, _response_json, _unwrap_dict,
    )

    site_url = str(config.get("PS_URL") or "").strip().rstrip("/")
    permalink = f"{site_url}/index.php?id_product={int(wc_id)}&controller=product" if site_url else ""

    image_urls: list[str] = []
    try:
        image_ids = ps_get_product_image_ids(config, int(wc_id))
        for image_id in image_ids:
            resp = ps_rest_request(config, "GET", f"images/products/{int(wc_id)}/{image_id}")
            if getattr(resp, "status_code", 0) == 200 and resp.content:
                fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="peecha_ps_img_")
                with os.fdopen(fd, "wb") as f:
                    f.write(resp.content)
                image_urls.append(tmp_path)  # مسیرِ محلی — چون از قبل دانلود شده
    except Exception:
        pass

    description = ""
    try:
        resp = ps_call(
            f"دریافتِ توضیحِ محصول #{wc_id} برای تقویمِ محتوا",
            lambda: ps_rest_request(config, "GET", f"products/{int(wc_id)}"),
        )
        data = _response_json(resp, f"دریافتِ توضیحِ محصول #{wc_id}")
        entry = _unwrap_dict(data, "product")
        raw_desc = entry.get("description_short") or entry.get("description") or ""
        if isinstance(raw_desc, dict):
            raw_desc = raw_desc.get("value") or next(iter(raw_desc.values()), "")
        description = _strip_html(str(raw_desc))
    except Exception:
        description = ""

    image_url = image_urls[0] if image_urls else ""
    return {"permalink": permalink, "image_url": image_url, "image_urls": image_urls, "description": description}


def fetch_product_content(config: dict, wc_id: int) -> dict:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if not wc_id:
        return dict(_EMPTY_CONTENT)
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


def download_images_to_temp(image_urls: list[str], *, timeout: int = 30, max_images: int = 10) -> list[str]:
    """دانلودِ چند عکس (برای «همه‌ی عکس‌های سایط»)؛ آدرس‌های ناموفق حذف می‌شن."""
    out = []
    for url in (image_urls or [])[:max_images]:
        local_path = download_image_to_temp(url, timeout=timeout)
        if local_path:
            out.append(local_path)
    return out
