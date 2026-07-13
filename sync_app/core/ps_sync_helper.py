"""
transport پرستاشاپ (Webservice API) — نگاشت به همون واژگان/شکل JSON که
wc_sync_helper/wcapi برای ووکامرس برمی‌گردونن، تا کد بالادستی (sync
محصول/دسته) بین دو پلتفرم تا حد امکان مشترک بمونه.

خواندن (GET) با output_format=JSON — نوشتن (POST/PUT) با XML، چون این
همون فرمتیه که Webservice API پرستاشاپ برای فیلدهای چندزبانه (name،
link_rewrite، description) رسمی و همیشه پشتیبانی می‌کنه.

⚠️ این کلاینت بر اساس مستندات رسمی Webservice API نوشته شده و هنوز روی
یک فروشگاه واقعی پرستاشاپ تست نشده — قبل از استفاده‌ی واقعی حتماً با
تب تنظیمات → تست اتصال روی سایت واقعی/آزمایشی بررسی شود.
"""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote

import requests

from sync_app.core.ps_api_helper import get_ps_auth, ps_endpoint, ps_lang_id, ps_store_host
from sync_app.core.sync_cancel import check_cancelled, SyncCancelled

PS_SYNC_RETRIES = 3
PS_SYNC_BACKOFF = (2.0, 4.0, 6.0)
PS_DEFAULT_PARENT_CATEGORY_ID = 2  # "Home" در یک نصب استاندارد تک‌فروشگاهی


class PrestaShopAPIError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# timeout / retry — همون الگوی wc_call، مستقل از پلتفرم
# ---------------------------------------------------------------------------

def ps_timeout_pair(config) -> tuple[float, float]:
    cfg = config or {}
    try:
        connect = int(cfg.get("PS_CONNECT_TIMEOUT", 25) or 25)
    except Exception:
        connect = 25
    try:
        read = int(cfg.get("PS_READ_TIMEOUT", 120) or 120)
    except Exception:
        read = 120
    return (float(max(8, min(connect, 45))), float(max(45, min(read, 180))))


def ps_call(label, call_fn, retries=PS_SYNC_RETRIES, backoff=None):
    from sync_app.core.sync_utils import log

    check_cancelled()
    waits = backoff if backoff is not None else PS_SYNC_BACKOFF
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
                wait = waits[min(attempt - 1, len(waits) - 1)]
                log.warning(f"⚠️ {label} — تلاش {attempt} ناموفق ({wait:.0f}s صبر): {err}")
                time.sleep(wait)
                check_cancelled()
    raise last_error


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _set_text(parent, tag, value):
    el = ET.SubElement(parent, tag)
    el.text = "" if value is None else str(value)
    return el


def _int_or_default(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _set_lang_text(parent, tag, value, lang_id):
    el = ET.SubElement(parent, tag)
    lang_el = ET.SubElement(el, "language", {"id": str(lang_id)})
    lang_el.text = "" if value is None else str(value)
    return el


def _build_xml(resource_name: str, build_fn) -> bytes:
    root = ET.Element("prestashop")
    node = ET.SubElement(root, resource_name)
    build_fn(node)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="utf-8")


def _lang_value(value, lang_id=1) -> str:
    """مقدار یک فیلد چندزبانه (name/link_rewrite/description) از پاسخ JSON."""
    if value is None:
        return ""
    if isinstance(value, dict):
        if "value" not in value and "#text" not in value and "language" in value:
            # روی برخی نصب‌های تک‌زبانه پرستاشاپ، فیلد چندزبانه به‌جای لیست
            # مستقیم [{"id":"1","value":"..."}] این‌طور برمی‌گرده:
            # {"language": {"id":"1","value":"..."}} یا {"language": [...]}
            return _lang_value(value.get("language"), lang_id)
        return str(value.get("value") or value.get("#text") or "")
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and str(item.get("id")) == str(lang_id):
                return str(item.get("value") or "")
        if value and isinstance(value[0], dict):
            return str(value[0].get("value") or "")
        return ""
    return str(value)


def _xml_error_message(raw_text: str) -> str:
    try:
        root = ET.fromstring(raw_text)
    except Exception:
        clean = re.sub(r"<[^>]+>", " ", raw_text or "")
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean[:220]
    parts = []
    for err in root.iter("error"):
        code = (err.findtext("code") or "").strip()
        msg = (err.findtext("message") or "").strip()
        parts.append(f"{code}: {msg}" if code else msg)
    return "; ".join(p for p in parts if p) or "خطای نامشخص پرستاشاپ"


def _peecha_user_agent() -> str:
    try:
        from sync_app.core.app_version import APP_VERSION

        return f"PeechaSync/{APP_VERSION}"
    except Exception:
        return "PeechaSync/1.0"


def ps_response_is_waf_block(response) -> bool:
    """403/406/429/503 با HTML خام (نه JSON/XML پرستاشاپ) — یعنی فایروال هاست
    (LiteSpeed/ModSecurity/Cloudflare) قبل از رسیدن درخواست به پرستاشاپ آن را
    مسدود کرده — نه خطای احراز هویت کلید Webservice."""
    status = int(getattr(response, "status_code", 0) or 0)
    if status not in (403, 406, 429, 503):
        return False
    raw = (getattr(response, "text", None) or "").lower()
    if not raw or "<html" not in raw:
        return False
    markers = (
        "litespeed",
        "mod_security",
        "modsecurity",
        "cloudflare",
        "access denied",
        "attention required",
        "proudly powered",
    )
    return any(m in raw for m in markers)


def ps_waf_block_message(response) -> str:
    raw = (getattr(response, "text", None) or "").lower()
    if "litespeed" in raw:
        who = "فایروال LiteSpeed هاست"
    elif "cloudflare" in raw:
        who = "Cloudflare/WAF"
    else:
        who = "فایروال (WAF) هاست"
    return (
        f"{who} درخواست به /api/ را قبل از رسیدن به پرستاشاپ مسدود کرد "
        "(این خطای کلید Webservice نیست).\n\n"
        "بررسی کنید:\n"
        "۱. پیشخوان پرستاشاپ → Advanced Parameters → Webservice → «Enable PrestaShop's webservice» فعال باشد.\n"
        "۲. مسیر /api/ در تنظیمات امنیتی هاست (WAF/فایروال) مسدود نشده باشد — از پشتیبانی هاست بخواهید "
        "مسیر /api/ را برای درخواست‌های REST سفید کنند.\n"
        "۳. اگر از افزونه‌ی امنیتی (مثل ModSecurity سفارشی) استفاده می‌کنید، User-Agent برنامه‌های خارجی را بلاک نکند."
    )


def _ps_error_message(response) -> str:
    status = int(getattr(response, "status_code", 0) or 0)
    if ps_response_is_waf_block(response):
        return ps_waf_block_message(response)
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        return f"HTTP {status}"
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("errors"):
            errs = data["errors"]
            if isinstance(errs, list):
                msgs = [str(e.get("message") or e) for e in errs if isinstance(e, dict)] or [str(errs)]
            else:
                msgs = [str(errs)]
            return f"HTTP {status} — " + "; ".join(msgs)
    except Exception:
        pass
    return f"HTTP {status} — {_xml_error_message(text)}"


def _unwrap_list(data, key: str) -> list:
    """
    برخی نصب‌های پرستاشاپ وقتی فیلتر نتیجه‌ی خالی داره، به‌جای
    {"key": []} مستقیماً [] برمی‌گردونن — این هر دو شکل رو یکسان می‌کنه.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get(key) or []
    return []


def _unwrap_dict(data, key: str) -> dict:
    if isinstance(data, dict):
        inner = data.get(key)
        if isinstance(inner, dict):
            return inner
        if key in data:
            return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# transport پایه
# ---------------------------------------------------------------------------

def ps_rest_request(
    config,
    method: str,
    resource: str,
    *,
    params=None,
    xml_body: bytes | None = None,
    timeout=None,
):
    cfg = config or {}
    url = ps_endpoint(cfg.get("PS_URL", ""), resource)
    if not url:
        raise PrestaShopAPIError("PS_URL خالی است.")
    auth = get_ps_auth(cfg)
    if not auth[0]:
        raise PrestaShopAPIError("PS_API_KEY خالی است.")
    verify = bool(cfg.get("PS_VERIFY_SSL", False))
    req_timeout = timeout if timeout is not None else ps_timeout_pair(cfg)

    query = dict(params or {})
    headers = {"Accept": "application/json", "User-Agent": _peecha_user_agent()}
    data = None
    if method.upper() == "GET":
        query.setdefault("output_format", "JSON")
    if xml_body is not None:
        headers["Content-Type"] = "text/xml; charset=utf-8"
        data = xml_body

    return requests.request(
        method.upper(),
        url,
        auth=auth,
        params=query,
        data=data,
        timeout=req_timeout,
        verify=verify,
        headers=headers,
    )


def _raise_for_status(response, label: str):
    status = int(getattr(response, "status_code", 0) or 0)
    if 200 <= status < 300:
        return
    raise PrestaShopAPIError(f"{label}: {_ps_error_message(response)}")


def _response_json(response, label: str):
    _raise_for_status(response, label)
    try:
        return response.json()
    except Exception as exc:
        raise PrestaShopAPIError(f"{label}: پاسخ JSON نامعتبر — {exc}") from exc


def _response_xml_id(response, label: str) -> int:
    """id ساخته‌شده از پاسخ XML یک POST — پاسخ نوشتن همیشه XML است."""
    _raise_for_status(response, label)
    text = (getattr(response, "text", None) or "").strip()
    try:
        root = ET.fromstring(text)
        id_text = root.findtext(".//id")
        if id_text and id_text.strip().isdigit():
            return int(id_text.strip())
    except Exception:
        pass
    raise PrestaShopAPIError(f"{label}: id در پاسخ یافت نشد.")


# ---------------------------------------------------------------------------
# دسته‌بندی‌ها
# ---------------------------------------------------------------------------

def _category_to_wc_shape(entry: dict, lang_id: int) -> dict:
    return {
        "id": int(entry.get("id") or 0),
        "name": _lang_value(entry.get("name"), lang_id),
        "slug": _lang_value(entry.get("link_rewrite"), lang_id),
        "parent": int(entry.get("id_parent") or 0),
    }


def ps_list_categories(config, *, timeout=None) -> list[dict]:
    """همه دسته‌ها — شکل {id, name, slug, parent} مثل fetch_wc_slug_map."""
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    out: list[dict] = []
    offset = 0
    page_size = 100
    while True:
        check_cancelled()
        resp = ps_call(
            f"دریافت categories offset={offset}",
            lambda o=offset: ps_rest_request(
                cfg, "GET", "categories",
                # بدون display=full، Webservice پرستاشاپ توی حالت لیست فقط id
                # برمی‌گردونه (name/link_rewrite خالی می‌مونه) — باعث می‌شد
                # دسته‌های موجود همیشه «پیدا نشد» به حساب بیان و هر بار از نو
                # ساخته بشن (دسته‌بندی تکراری).
                params={"limit": f"{o},{page_size}", "display": "full"},
                timeout=timeout,
            ),
        )
        data = _response_json(resp, "دریافت categories")
        batch = _unwrap_list(data, "categories")
        if not batch:
            break
        for entry in batch:
            if isinstance(entry, dict) and entry.get("id"):
                shaped_probe = _category_to_wc_shape(entry, lang_id)
                if not shaped_probe.get("slug"):
                    from sync_app.core.sync_utils import log

                    log.warning(
                        f"🔎 [تشخیص] دسته #{entry.get('id')} slug خالی برگشت — "
                        f"name خام={entry.get('name')!r} | link_rewrite خام={entry.get('link_rewrite')!r}"
                    )
                out.append(_category_to_wc_shape(entry, lang_id))
        if len(batch) < page_size:
            break
        offset += page_size
    return out


def ps_fetch_slug_map(config, *, timeout=None, cancel_check=None) -> dict:
    """شکل خروجی مثل fetch_wc_slug_map: {slug: {id, name, slug, parent}}."""
    out = {}
    for cat in ps_list_categories(config, timeout=timeout):
        slug = unquote((cat.get("slug") or "").strip().lower())
        if not slug:
            continue
        out[slug] = cat
        if cancel_check:
            cancel_check()
    return out


def ps_get_category(config, category_id: int, *, timeout=None) -> dict:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        f"دریافت دسته #{category_id}",
        lambda: ps_rest_request(cfg, "GET", f"categories/{int(category_id)}", timeout=timeout),
    )
    data = _response_json(resp, f"دریافت دسته #{category_id}")
    entry = _unwrap_dict(data, "category")
    return _category_to_wc_shape(entry, lang_id)


def ps_create_category(config, *, name: str, slug: str, parent: int = 0, timeout=None) -> dict:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    parent_id = int(parent or cfg.get("PS_ROOT_CATEGORY_ID") or PS_DEFAULT_PARENT_CATEGORY_ID)

    def _build(node):
        _set_text(node, "id_parent", parent_id)
        _set_lang_text(node, "name", name, lang_id)
        _set_lang_text(node, "link_rewrite", slug, lang_id)
        _set_text(node, "active", 1)

    body = _build_xml("category", _build)
    resp = ps_call(
        f"ایجاد دسته '{name}'",
        lambda: ps_rest_request(cfg, "POST", "categories", xml_body=body, timeout=timeout),
    )
    new_id = _response_xml_id(resp, f"ایجاد دسته '{name}'")
    return {"id": new_id, "name": name, "slug": slug, "parent": parent_id}


def ps_update_category(
    config, category_id: int, *, name: str | None = None, slug: str | None = None,
    parent: int | None = None, timeout=None,
) -> dict:
    """PUT کامل — چون Webservice پرستاشاپ فیلد ست‌نشده رو خالی می‌کنه، اول رکورد فعلی خونده می‌شه."""
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    current = ps_get_category(cfg, category_id, timeout=timeout)
    final_name = name if name is not None else current.get("name")
    final_slug = slug if slug is not None else current.get("slug")
    final_parent = int(parent if parent is not None else (current.get("parent") or 0)) or PS_DEFAULT_PARENT_CATEGORY_ID

    def _build(node):
        _set_text(node, "id", int(category_id))
        _set_text(node, "id_parent", final_parent)
        _set_lang_text(node, "name", final_name, lang_id)
        _set_lang_text(node, "link_rewrite", final_slug, lang_id)
        _set_text(node, "active", 1)

    body = _build_xml("category", _build)
    resp = ps_call(
        f"به‌روزرسانی دسته #{category_id}",
        lambda: ps_rest_request(cfg, "PUT", f"categories/{int(category_id)}", xml_body=body, timeout=timeout),
    )
    _raise_for_status(resp, f"به‌روزرسانی دسته #{category_id}")
    return {"id": int(category_id), "name": final_name, "slug": final_slug, "parent": final_parent}


# ---------------------------------------------------------------------------
# محصولات ساده (Phase 1 — بدون combination/واریانت)
# ---------------------------------------------------------------------------

def _product_to_wc_shape(entry: dict, lang_id: int, *, stock_quantity: int | None = None) -> dict:
    active = str(entry.get("active") or "0") == "1"
    visibility = str(entry.get("visibility") or "both")
    return {
        "id": int(entry.get("id") or 0),
        "sku": str(entry.get("reference") or "").strip(),
        "name": _lang_value(entry.get("name"), lang_id),
        "type": "simple",
        "status": "publish" if active else "draft",
        "catalog_visibility": "visible" if visibility != "none" else "hidden",
        "regular_price": str(entry.get("price") or "0"),
        "manage_stock": stock_quantity is not None,
        "stock_quantity": stock_quantity,
        "categories": [{"id": int(entry.get("id_category_default") or 0)}] if entry.get("id_category_default") else [],
        "images": [],
        "description": _lang_value(entry.get("description"), lang_id),
        "short_description": _lang_value(entry.get("description_short"), lang_id),
        "meta_title": _lang_value(entry.get("meta_title"), lang_id),
        "meta_description": _lang_value(entry.get("meta_description"), lang_id),
        "meta_keywords": _lang_value(entry.get("meta_keywords"), lang_id),
    }


def ps_find_product_by_reference(config, sku: str, *, timeout=None) -> dict | None:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    sku = str(sku or "").strip()
    if not sku:
        return None
    resp = ps_call(
        f"جستجوی SKU {sku}",
        lambda: ps_rest_request(
            cfg, "GET", "products",
            params={"filter[reference]": f"[{sku}]", "limit": "0,5"},
            timeout=timeout,
        ),
    )
    data = _response_json(resp, f"جستجوی SKU {sku}")
    rows = _unwrap_list(data, "products")
    for row in rows:
        if isinstance(row, dict) and str(row.get("id") or ""):
            full = ps_get_product(cfg, int(row["id"]), timeout=timeout)
            if full and full.get("sku") == sku:
                return full
    return None


def ps_list_products(config, *, timeout=None) -> list[dict]:
    """همه محصولات — شکل {id, sku, name, status, type, ...} مثل fetch_wc products.

    برای تشخیص محصول متغیر (type=variable)، این تابع فیلد type رو همیشه
    "simple" برمی‌گردونه — چون پرستاشاپ چنین فیلدی نداره؛ فراخوان (مثلاً
    reconciliation) باید جدا با ps_variation_helper.ps_list_all_combinations_grouped
    محصولات دارای combination رو مشخص کنه.
    """
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    out: list[dict] = []
    offset = 0
    page_size = 100
    while True:
        check_cancelled()
        resp = ps_call(
            f"دریافت محصولات offset={offset}",
            lambda o=offset: ps_rest_request(
                cfg, "GET", "products",
                params={"limit": f"{o},{page_size}", "display": "full"},
                timeout=timeout,
            ),
        )
        data = _response_json(resp, "دریافت محصولات")
        batch = _unwrap_list(data, "products")
        if not batch:
            break
        for entry in batch:
            if isinstance(entry, dict) and entry.get("id"):
                out.append(_product_to_wc_shape(entry, lang_id))
        if len(batch) < page_size:
            break
        offset += page_size
    return out


def ps_count_products(config, *, timeout=None) -> int:
    """تعداد کل محصولات — فقط id خام (بدون display=full)، سبک برای شمارش."""
    cfg = config or {}
    count = 0
    offset = 0
    page_size = 1000
    while True:
        resp = ps_call(
            f"شمارش محصولات offset={offset}",
            lambda o=offset: ps_rest_request(
                cfg, "GET", "products", params={"limit": f"{o},{page_size}"}, timeout=timeout,
            ),
        )
        data = _response_json(resp, "شمارش محصولات")
        rows = _unwrap_list(data, "products")
        if not rows:
            break
        count += len(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return count


def ps_get_product(config, product_id: int, *, timeout=None) -> dict | None:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        f"دریافت محصول #{product_id}",
        lambda: ps_rest_request(cfg, "GET", f"products/{int(product_id)}", timeout=timeout),
    )
    if getattr(resp, "status_code", 0) == 404:
        return None
    data = _response_json(resp, f"دریافت محصول #{product_id}")
    entry = _unwrap_dict(data, "product")
    if not entry.get("id"):
        return None
    try:
        _stock_id, qty = ps_get_stock_available(cfg, int(product_id), timeout=timeout)
    except Exception as exc:
        from sync_app.core.sync_utils import log

        log.warning(
            f"⚠️ دریافت موجودی محصول #{product_id} ناموفق بود ({exc}) — "
            "شناسایی محصول بدون موجودی ادامه می‌یابد (از تکراری‌سازی جلوگیری می‌شود)"
        )
        qty = None
    return _product_to_wc_shape(entry, lang_id, stock_quantity=qty)


def _visibility_from_wc(catalog_visibility: str) -> str:
    return "none" if (catalog_visibility or "").strip() == "hidden" else "both"


def ps_create_product(
    config, *, sku: str, name: str, price, description: str = "",
    category_ids: list[int] | None = None, active: bool = True,
    catalog_visibility: str = "visible", out_of_stock: int | None = None,
    has_variants: bool = False, timeout=None,
) -> dict:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    cat_ids = [int(c) for c in (category_ids or []) if int(c or 0) > 0]
    default_cat = cat_ids[-1] if cat_ids else int(cfg.get("PS_ROOT_CATEGORY_ID") or PS_DEFAULT_PARENT_CATEGORY_ID)

    def _build(node):
        _set_text(node, "reference", sku)
        _set_lang_text(node, "name", name, lang_id)
        _set_lang_text(node, "link_rewrite", _slugify_reference(sku), lang_id)
        if description:
            _set_lang_text(node, "description", description, lang_id)
        _set_text(node, "price", f"{float(price or 0):.6f}")
        _set_text(node, "active", 1 if active else 0)
        _set_text(node, "state", 1)
        _set_text(node, "visibility", _visibility_from_wc(catalog_visibility))
        _set_text(node, "id_category_default", default_cat)
        # product_type — از پرستاشاپ ۸/۹ به بعد، محصول باید صریحاً
        # «combinations» باشه تا هم پنل ادمین ترکیب‌های ساخته‌شده رو به رسمیت
        # بشناسه (وگرنه صفحه‌ی «تولید ترکیب‌ها» رو نشون می‌ده انگار هیچ
        # ترکیبی نیست)، هم موجودیِ واقعیِ خرید از سطح خودِ هر ترکیب خونده بشه
        # نه از رکورد کلیِ محصول (که ما همیشه «همیشه موجود» می‌فرستیم چون
        # بی‌معنیه — موجودیِ واقعی مال هر ترکیبه).
        _set_text(node, "product_type", "combinations" if has_variants else "standard")
        # out_of_stock هم روی خودِ محصول (نه فقط stock_availables) ست می‌شه —
        # پرستاشاپ موقع ذخیره‌ی محصول از فیلد out_of_stock خودِ محصول برای
        # هم‌گام‌سازیِ stock_availables استفاده می‌کنه؛ اگه این‌جا نباشه، هر PUT
        # بعدیِ محصول (مثلاً تنظیم سئو) بی‌صدا مقدارِ درستِ stock_availables رو
        # به «۲ = پیش‌فرض فروشگاه» ریست می‌کنه.
        _set_text(node, "out_of_stock", int(out_of_stock) if out_of_stock is not None else 2)
        if cat_ids:
            assoc = ET.SubElement(node, "associations")
            cats_node = ET.SubElement(assoc, "categories")
            for cid in cat_ids:
                cat_node = ET.SubElement(cats_node, "category")
                _set_text(cat_node, "id", cid)

    body = _build_xml("product", _build)
    resp = ps_call(
        f"ایجاد محصول {sku}",
        lambda: ps_rest_request(cfg, "POST", "products", xml_body=body, timeout=timeout),
    )
    new_id = _response_xml_id(resp, f"ایجاد محصول {sku}")
    return {"id": new_id, "sku": sku, "name": name, "type": "simple"}


def ps_update_product(
    config, product_id: int, *, sku: str | None = None, name: str | None = None,
    price=None, description: str | None = None, category_ids: list[int] | None = None,
    active: bool | None = None, catalog_visibility: str | None = None,
    out_of_stock: int | None = None, has_variants: bool | None = None, timeout=None,
) -> dict:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        f"دریافت محصول #{product_id} برای به‌روزرسانی",
        lambda: ps_rest_request(cfg, "GET", f"products/{int(product_id)}", timeout=timeout),
    )
    current = _response_json(resp, f"دریافت محصول #{product_id}").get("product") or {}

    final_sku = sku if sku is not None else str(current.get("reference") or "")
    final_name = name if name is not None else _lang_value(current.get("name"), lang_id)
    final_price = price if price is not None else current.get("price")
    final_active = int(current.get("active") or 0) if active is None else (1 if active else 0)
    current_visibility = str(current.get("visibility") or "both")
    final_visibility = (
        current_visibility if catalog_visibility is None else _visibility_from_wc(catalog_visibility)
    )
    cat_ids = [int(c) for c in (category_ids or []) if int(c or 0) > 0]
    default_cat = cat_ids[-1] if cat_ids else int(current.get("id_category_default") or PS_DEFAULT_PARENT_CATEGORY_ID)

    def _build(node):
        _set_text(node, "id", int(product_id))
        _set_text(node, "reference", final_sku)
        _set_lang_text(node, "name", final_name, lang_id)
        _set_lang_text(
            node, "link_rewrite",
            _lang_value(current.get("link_rewrite"), lang_id) or _slugify_reference(final_sku),
            lang_id,
        )
        # برخلاف بقیه‌ی این تابع، description قبلاً وقتی None بود کلاً از XML
        # حذف می‌شد (نه اینکه مقدار فعلی حفظ بشه) — و چون Webservice پرستاشاپ
        # فیلد نیومده رو خالی می‌کنه، این باعث می‌شد توضیحات محصول با هر PUT
        # بی‌صدا پاک بشه (مثلاً وقتی این دور، ERP توضیحاتی نداشت یا فیلد
        # SYNC_FIELD_PRODUCT_DESCRIPTION غیرفعال بود).
        final_description = (
            description if description is not None
            else _lang_value(current.get("description"), lang_id)
        )
        _set_lang_text(node, "description", final_description, lang_id)
        _set_text(node, "price", f"{float(final_price or 0):.6f}")
        _set_text(node, "active", final_active)
        _set_text(node, "state", 1)
        _set_text(node, "visibility", final_visibility)
        _set_text(node, "id_category_default", default_cat)
        # product_type — مثل ps_create_product؛ اگه صریح پاس داده نشده باشه
        # (has_variants=None)، مقدار فعلیِ محصول حفظ می‌شه.
        if has_variants is not None:
            final_product_type = "combinations" if has_variants else "standard"
        else:
            final_product_type = str(current.get("product_type") or "standard")
        _set_text(node, "product_type", final_product_type)
        # مثل ps_create_product — اگه صریح پاس داده نشده باشه، مقدار فعلیِ
        # محصول حفظ می‌شه (نه اینکه ریست بشه به پیش‌فرض) تا این PUT مقدارِ
        # درستِ out_of_stock که یه فراخوانیِ قبلی ست کرده رو خراب نکنه.
        final_out_of_stock = (
            int(out_of_stock) if out_of_stock is not None
            else _int_or_default(current.get("out_of_stock"), 2)
        )
        _set_text(node, "out_of_stock", final_out_of_stock)
        if cat_ids:
            assoc = ET.SubElement(node, "associations")
            cats_node = ET.SubElement(assoc, "categories")
            for cid in cat_ids:
                cat_node = ET.SubElement(cats_node, "category")
                _set_text(cat_node, "id", cid)

    body = _build_xml("product", _build)
    resp2 = ps_call(
        f"به‌روزرسانی محصول #{product_id}",
        lambda: ps_rest_request(cfg, "PUT", f"products/{int(product_id)}", xml_body=body, timeout=timeout),
    )
    _raise_for_status(resp2, f"به‌روزرسانی محصول #{product_id}")

    if out_of_stock is not None or has_variants is not None:
        # تأیید تشخیصی: آیا فیلدهای out_of_stock/product_type خودِ محصول
        # (نه stock_availables) واقعاً روی این نصبِ پرستاشاپ نوشتنی/معتبرن؟
        # بعضی فروشگاه‌ها ممکنه این فیلدها رو روی ریسورس محصول نادیده بگیرن.
        try:
            from sync_app.core.sync_utils import log

            verify_resp = ps_rest_request(cfg, "GET", f"products/{int(product_id)}", timeout=timeout)
            verify_current = _response_json(verify_resp, f"تأیید محصول #{product_id}").get("product") or {}
            if out_of_stock is not None:
                actual = verify_current.get("out_of_stock")
                if str(actual) != str(int(out_of_stock)):
                    log.warning(
                        f"⚠️ [تأیید] محصول #{product_id}: فیلد out_of_stock خودِ محصول رو {out_of_stock} "
                        f"فرستادیم ولی فروشگاه {actual!r} برمی‌گردونه — این فیلد شاید روی این نصب نوشتنی نباشه."
                    )
                else:
                    log.info(f"✔️ [تأیید] محصول #{product_id}: فیلد out_of_stock خودِ محصول = {actual} (مطابق انتظار)")
            if has_variants is not None:
                expected_type = "combinations" if has_variants else "standard"
                actual_type = verify_current.get("product_type")
                if str(actual_type) != expected_type:
                    log.warning(
                        f"⚠️ [تأیید] محصول #{product_id}: product_type رو «{expected_type}» فرستادیم ولی "
                        f"فروشگاه {actual_type!r} برمی‌گردونه — پنل ادمین شاید ترکیب‌های این محصول رو نبینه."
                    )
                else:
                    log.info(f"✔️ [تأیید] محصول #{product_id}: product_type={actual_type} (مطابق انتظار)")
        except Exception as verify_exc:
            log.warning(f"⚠️ [تأیید] محصول #{product_id}: خواندنِ دوباره ناموفق بود: {verify_exc}")

    return {"id": int(product_id), "sku": final_sku, "name": final_name, "type": "simple"}


def ps_try_set_price_visibility(config, product_id: int, *, timeout=None) -> bool:
    """تلاش best-effort برای اطمینان از نمایش قیمت/امکان سفارش صرف‌نظر از
    موجودی (available_for_order=1 / show_price=1).

    عمداً از ps_create_product/ps_update_product جداست: این دو فیلد صرفاً
    یک بهبود جانبی‌ان، نه بخش اصلی سینک — اگه یک فروشگاه خاص این فیلدها رو
    رد کنه (مثلاً به‌خاطر نسخه/تنظیمات ماژول)، نباید بروزرسانیِ اصلی محصول
    یا اعمال موجودی (که در ps_update_product/_ps_apply_stock_from_payload
    انجام می‌شه) به‌خاطرش خراب بشه. کنترل واقعیِ «اجازه‌ی خرید با موجودی
    صفر» با فیلد out_of_stock در stock_availables انجام می‌شه، نه این‌جا.
    """
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    try:
        resp = ps_call(
            f"دریافت محصول #{product_id} برای تنظیم نمایش قیمت",
            lambda: ps_rest_request(cfg, "GET", f"products/{int(product_id)}", timeout=timeout),
        )
        current = _response_json(resp, f"دریافت محصول #{product_id}").get("product") or {}

        def _build(node):
            _set_text(node, "id", int(product_id))
            _set_text(node, "reference", str(current.get("reference") or ""))
            _set_lang_text(node, "name", _lang_value(current.get("name"), lang_id), lang_id)
            _set_lang_text(
                node, "link_rewrite", _lang_value(current.get("link_rewrite"), lang_id), lang_id,
            )
            _set_text(node, "price", f"{float(current.get('price') or 0):.6f}")
            _set_text(node, "active", int(current.get("active") or 0))
            _set_text(node, "state", 1)
            _set_text(node, "visibility", str(current.get("visibility") or "both"))
            _set_text(
                node, "id_category_default",
                int(current.get("id_category_default") or PS_DEFAULT_PARENT_CATEGORY_ID),
            )
            _set_text(node, "available_for_order", 1)
            _set_text(node, "show_price", 1)
            # حفظ out_of_stock فعلی — این PUT نباید حالت موجودیِ ست‌شده توسط
            # ps_update_product/_ps_apply_stock_from_payload رو بی‌صدا ریست کنه.
            _set_text(node, "out_of_stock", _int_or_default(current.get("out_of_stock"), 2))
            # حفظ product_type فعلی — وگرنه محصولِ ترکیبی («combinations») به
            # «standard» ریست می‌شه و پنل ادمین دیگه ترکیب‌های ساخته‌شده رو
            # به رسمیت نمی‌شناسه.
            _set_text(node, "product_type", str(current.get("product_type") or "standard"))

        body = _build_xml("product", _build)
        resp2 = ps_call(
            f"تنظیم نمایش قیمت محصول #{product_id}",
            lambda: ps_rest_request(cfg, "PUT", f"products/{int(product_id)}", xml_body=body, timeout=timeout),
        )
        _raise_for_status(resp2, f"تنظیم نمایش قیمت محصول #{product_id}")
        from sync_app.core.sync_utils import log

        log.info(f"💲 [#{product_id}] available_for_order/show_price=1 تنظیم شد.")
        return True
    except Exception as exc:
        from sync_app.core.sync_utils import log

        log.warning(
            f"⚠️ تنظیم نمایش قیمت/امکان سفارشِ محصول #{product_id} ناموفق بود "
            f"(نادیده گرفته شد، بروزرسانی اصلی محصول/موجودی تحت تأثیر قرار نگرفت): {exc}"
        )
        return False


def ps_update_product_seo(
    config, product_id: int, *, description: str | None = None,
    short_description: str | None = None, meta_title: str | None = None,
    meta_description: str | None = None, meta_keywords: str | None = None, timeout=None,
) -> None:
    """به‌روزرسانی فیلدهای سئوی بومی محصول — برخلاف ووکامرس/Yoast، این‌ها
    فیلد رسمی محصول پرستاشاپن (نه متادیتای یک افزونه‌ی جدا)، پس نیازی به
    نوشتن هم‌زمان چند کلید حدسی (مثل Yoast/RankMath) نیست.

    مثل ps_update_product، چون Webservice پرستاشاپ فیلد ست‌نشده رو توی PUT
    خالی می‌کنه، اول رکورد کامل فعلی خونده می‌شه.
    """
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        f"دریافت محصول #{product_id} برای به‌روزرسانی سئو",
        lambda: ps_rest_request(cfg, "GET", f"products/{int(product_id)}", timeout=timeout),
    )
    current = _response_json(resp, f"دریافت محصول #{product_id}").get("product") or {}

    def _build(node):
        _set_text(node, "id", int(product_id))
        _set_text(node, "reference", str(current.get("reference") or ""))
        _set_lang_text(node, "name", _lang_value(current.get("name"), lang_id), lang_id)
        _set_lang_text(node, "link_rewrite", _lang_value(current.get("link_rewrite"), lang_id), lang_id)
        _set_text(node, "price", f"{float(current.get('price') or 0):.6f}")
        _set_text(node, "active", int(current.get("active") or 0))
        _set_text(node, "state", 1)
        _set_text(node, "visibility", str(current.get("visibility") or "both"))
        _set_text(node, "id_category_default", int(current.get("id_category_default") or PS_DEFAULT_PARENT_CATEGORY_ID))
        _set_text(node, "available_for_order", _int_or_default(current.get("available_for_order"), 1))
        _set_text(node, "show_price", _int_or_default(current.get("show_price"), 1))
        # حفظ out_of_stock فعلی — این PUT نباید حالت موجودیِ ست‌شده رو ریست کنه.
        _set_text(node, "out_of_stock", _int_or_default(current.get("out_of_stock"), 2))
        # حفظ product_type فعلی — وگرنه محصولِ ترکیبی به «standard» ریست می‌شه.
        _set_text(node, "product_type", str(current.get("product_type") or "standard"))
        final_description = description if description is not None else _lang_value(current.get("description"), lang_id)
        _set_lang_text(node, "description", final_description, lang_id)
        final_short = short_description if short_description is not None else _lang_value(current.get("description_short"), lang_id)
        _set_lang_text(node, "description_short", final_short, lang_id)
        final_meta_title = meta_title if meta_title is not None else _lang_value(current.get("meta_title"), lang_id)
        _set_lang_text(node, "meta_title", final_meta_title, lang_id)
        final_meta_desc = meta_description if meta_description is not None else _lang_value(current.get("meta_description"), lang_id)
        _set_lang_text(node, "meta_description", final_meta_desc, lang_id)
        final_meta_kw = meta_keywords if meta_keywords is not None else _lang_value(current.get("meta_keywords"), lang_id)
        _set_lang_text(node, "meta_keywords", final_meta_kw, lang_id)

    body = _build_xml("product", _build)
    resp2 = ps_call(
        f"به‌روزرسانی سئوی محصول #{product_id}",
        lambda: ps_rest_request(cfg, "PUT", f"products/{int(product_id)}", xml_body=body, timeout=timeout),
    )
    _raise_for_status(resp2, f"به‌روزرسانی سئوی محصول #{product_id}")


def ps_delete_product(config, product_id: int, *, timeout=None) -> bool:
    """حذف کامل محصول — پرستاشاپ برخلاف ووکامرس زباله‌دان (soft-delete) نداره."""
    cfg = config or {}
    resp = ps_call(
        f"حذف محصول #{product_id}",
        lambda: ps_rest_request(cfg, "DELETE", f"products/{int(product_id)}", timeout=timeout),
    )
    if getattr(resp, "status_code", 0) == 404:
        return True
    _raise_for_status(resp, f"حذف محصول #{product_id}")
    return True


def _slugify_reference(sku: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", str(sku or "").strip()).strip("-").lower()
    return text or "product"


# ---------------------------------------------------------------------------
# موجودی (stock_availables) — همیشه یک رکورد جدا از محصول
# ---------------------------------------------------------------------------

def _pick_shop_stock_available_row(rows: list[dict]) -> dict | None:
    """از بین چند رکورد stock_availables (پرستاشاپ چندشاپی حتی توی حالت
    تک‌فروشگاهی می‌تونه بیش از یک رکورد داشته باشه)، رکوردِ واقعیِ یک شاپِ
    مشخص رو انتخاب می‌کنه، نه رکورد id_shop=0 (که یه رکورد عمومی/گروهیه و
    پنل ادمین بر اساس شاپِ فعال، نه این رکورد، مقدار رو نشون می‌ده).

    این باگِ واقعی روی یک فروشگاه پرستاشاپ ۹.۱.۳ تأیید شده: نوشتن روی
    id_shop=0 موفق بود ولی پنل (که از رکورد id_shop=1 می‌خوند) هیچ‌وقت
    عوض نمی‌شد.
    """
    if not rows:
        return None
    shop_rows = [r for r in rows if int(r.get("id_shop") or 0) > 0]
    if shop_rows:
        return min(shop_rows, key=lambda r: int(r.get("id_shop") or 0))
    return rows[0]


def _ps_fetch_stock_available_row(config, product_id: int, *, product_attribute_id: int = 0, timeout=None):
    """رکورد stock_availablesِ واقعیِ شاپ رو برمی‌گردونه (dict کامل، شامل
    id/quantity/id_shop/id_shop_group) یا None.

    ⚠️ ممکنه بیش از یک رکورد برای همین (product, attribute) برگرده — یکی
    id_shop=0 (عمومی/گروهی، پنل ادمین ازش نمی‌خونه) و یکی id_shop=N (واقعیِ
    شاپ فعال). limit رو بالا می‌بریم و رکورد واقعیِ شاپ رو ترجیح می‌دیم؛
    وگرنه رکورد id_shop=0 اول برمی‌گشت و می‌نوشتیم روش، بدون اینکه پنل ادمین
    اصلاً عوض بشه. id_shop/id_shop_group هم لازمه، چون هر PUTِ بعدی باید
    دقیقاً همین دو مقدار رو با خودش ببره — وگرنه پرستاشاپ روی UPDATE، id_shop
    رو با پیش‌فرض (۰) جایگزین می‌کنه و چون کلید یکتای جدول
    (product, attribute, shop, shop_group) با رکورد id_shop=0 موجود برخورد
    می‌کنه، خطای SQL «Duplicate entry» می‌ده.
    """
    cfg = config or {}
    resp = ps_call(
        f"دریافت موجودی محصول #{product_id}",
        lambda: ps_rest_request(
            cfg, "GET", "stock_availables",
            params={
                "filter[id_product]": f"[{int(product_id)}]",
                "filter[id_product_attribute]": f"[{int(product_attribute_id)}]",
                "display": "full",
                "limit": "0,20",
            },
            timeout=timeout,
        ),
    )
    data = _response_json(resp, f"دریافت موجودی محصول #{product_id}")
    rows = _unwrap_list(data, "stock_availables")
    row = _pick_shop_stock_available_row(rows)
    if not row:
        return None
    sid = int(row.get("id") or 0)
    if not sid:
        return None
    return {
        "id": sid,
        "quantity": int(row.get("quantity") or 0),
        "id_shop": int(row.get("id_shop") or 0),
        "id_shop_group": int(row.get("id_shop_group") or 0),
    }


def ps_get_stock_available(config, product_id: int, *, product_attribute_id: int = 0, timeout=None):
    """(stock_available_id, quantity) برای یک محصول ساده (بدون combination) —
    نسخه‌ی سبک _ps_fetch_stock_available_row، برای کالرهایی که فقط شناسه و
    تعداد لازم دارن (نه id_shop)."""
    row = _ps_fetch_stock_available_row(
        config, product_id, product_attribute_id=product_attribute_id, timeout=timeout,
    )
    if not row:
        return None, None
    return row["id"], row["quantity"]


def ps_set_stock_quantity(
    config, product_id: int, quantity: int, *, product_attribute_id: int = 0,
    out_of_stock: int = 2, timeout=None,
) -> bool:
    """
    out_of_stock کنترل می‌کنه که با موجودیِ صفر، خرید از سایت مجاز باشه یا نه:
      0 = رد سفارش (موجودی واقعی، همون رفتار پیش‌فرضِ ووکامرس برای
          manage_stock=True بدون backorder)
      1 = اجازه‌ی سفارش با وجود موجودیِ صفر (معادل «همیشه موجود»/«دانلودی»
          ووکامرس — آنجا با manage_stock=False + stock_status=instock انجام
          می‌شه، اینجا باید صریح ست بشه، چون پیش‌فرض «طبق تنظیم فروشگاه»
          الزاماً همین معنی رو نداره)
      2 = طبق تنظیم پیش‌فرض فروشگاه (Preferences > Products)
    """
    cfg = config or {}
    stock_row = _ps_fetch_stock_available_row(
        cfg, product_id, product_attribute_id=product_attribute_id, timeout=timeout,
    )
    if not stock_row:
        raise PrestaShopAPIError(
            f"رکورد stock_availables برای محصول #{product_id} یافت نشد "
            "(محصول باید قبلاً روی پرستاشاپ ساخته شده باشد)."
        )
    sid = stock_row["id"]
    row_id_shop = stock_row["id_shop"]
    row_id_shop_group = stock_row["id_shop_group"]

    def _build(node):
        _set_text(node, "id", sid)
        _set_text(node, "id_product", int(product_id))
        _set_text(node, "id_product_attribute", int(product_attribute_id))
        # id_shop/id_shop_group باید دقیقاً همون مقدارِ رکورد فعلی رو حفظ کنن —
        # اگه نفرستیمشون، پرستاشاپ روی UPDATE پیش‌فرض ۰ می‌ذاره و چون کلید
        # یکتای جدول (product, attribute, shop, shop_group) با رکورد
        # id_shop=0 موجود برخورد می‌کنه، خطای SQL «Duplicate entry» می‌ده.
        _set_text(node, "id_shop", row_id_shop)
        _set_text(node, "id_shop_group", row_id_shop_group)
        _set_text(node, "quantity", int(quantity))
        # depends_on_stock=0 یعنی موجودی مستقیم از quantity میاد (نه انبار پیشرفته).
        _set_text(node, "depends_on_stock", 0)
        _set_text(node, "out_of_stock", int(out_of_stock))

    body = _build_xml("stock_available", _build)
    resp = ps_call(
        f"به‌روزرسانی موجودی محصول #{product_id}",
        lambda: ps_rest_request(cfg, "PUT", f"stock_availables/{sid}", xml_body=body, timeout=timeout),
    )
    _raise_for_status(resp, f"به‌روزرسانی موجودی محصول #{product_id}")

    # تأیید تشخیصی: بلافاصله بعد از نوشتن، دوباره می‌خونیم تا مطمئن بشیم
    # مقداری که واقعاً روی فروشگاه ذخیره شده با چیزی که فرستادیم یکیه — یه
    # مورد واقعی دیده شده که برنامه موفقیت لاگ می‌کرد ولی پنل پرستاشاپ
    # مقدار متفاوتی (رد سفارشات) نشون می‌داد. بدون فیلتر id_shop می‌خونیم و
    # limit رو بالا می‌بریم — چون پرستاشاپ (خصوصاً نسخه‌های جدید، چند
    # فروشگاهی زیرساختی) ممکنه بیش از یک رکورد stock_availables برای همین
    # (product, attribute) داشته باشه (یکی به‌ازای هر شاپ) و پنل ادمین از
    # رکورد شاپِ فعال بخونه، نه لزوماً همونی که ما با limit=0,1 گرفتیم.
    try:
        from sync_app.core.sync_utils import log

        verify_resp = ps_rest_request(
            cfg, "GET", "stock_availables",
            params={
                "filter[id_product]": f"[{int(product_id)}]",
                "filter[id_product_attribute]": f"[{int(product_attribute_id)}]",
                "display": "full", "limit": "0,20",
            },
            timeout=timeout,
        )
        verify_rows = _unwrap_list(_response_json(verify_resp, "تأیید موجودی"), "stock_availables")
        if verify_rows:
            if len(verify_rows) > 1:
                log.info(
                    f"ℹ️ [تأیید] #{product_id}: {len(verify_rows)} رکورد stock_availables برای همین محصول "
                    "پیدا شد (چندشاپی) — رکوردی که واقعاً نوشتیم رو با id چک می‌کنیم، نه فقط اولی رو:"
                )
            for row in verify_rows:
                log.info(
                    f"    stock_availables id={row.get('id')} id_shop={row.get('id_shop')!r} "
                    f"id_shop_group={row.get('id_shop_group')!r} out_of_stock={row.get('out_of_stock')!r} "
                    f"quantity={row.get('quantity')!r}"
                )
            # همون رکوردی که PUT کردیم (sid) رو دقیق پیدا می‌کنیم — نه صرفاً
            # اولین رکورد لیست — چون توی چندشاپی، رکورد اول لزوماً همونی
            # نیست که ما نوشتیم.
            written_row = next((r for r in verify_rows if int(r.get("id") or 0) == sid), None)
            if written_row is None:
                log.warning(f"⚠️ [تأیید] #{product_id}: رکورد id={sid} که نوشتیم دیگه توی نتیجه نیست!")
            else:
                actual_oos = written_row.get("out_of_stock")
                actual_qty = written_row.get("quantity")
                if str(actual_oos) != str(int(out_of_stock)):
                    log.warning(
                        f"⚠️ [تأیید] #{product_id} (رکورد id={sid}): نوشتیم out_of_stock={out_of_stock} ولی "
                        f"فروشگاه الان {actual_oos!r} برمی‌گردونه (quantity={actual_qty!r}) — با هم فرق دارن!"
                    )
                else:
                    log.info(
                        f"✔️ [تأیید] #{product_id} (رکورد id={sid}): "
                        f"stock_availables.out_of_stock={actual_oos} (مطابق انتظار)"
                    )
        else:
            log.warning(f"⚠️ [تأیید] #{product_id}: بعد از نوشتن، رکورد stock_availables دیگه پیدا نشد.")
    except Exception as verify_exc:
        log.warning(f"⚠️ [تأیید] #{product_id}: خواندنِ دوباره برای تأیید ناموفق بود: {verify_exc}")

    return True


# ---------------------------------------------------------------------------
# تصویر محصول (multipart POST) — پایه برای فازهای بعدی
# ---------------------------------------------------------------------------

_IMAGE_MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
}


def ps_upload_product_image(config, product_id: int, image_data: bytes, filename: str, *, timeout=None) -> int:
    cfg = config or {}
    url = ps_endpoint(cfg.get("PS_URL", ""), f"images/products/{int(product_id)}")
    if not url:
        raise PrestaShopAPIError("PS_URL خالی است.")
    auth = get_ps_auth(cfg)
    verify = bool(cfg.get("PS_VERIFY_SSL", False))
    req_timeout = timeout if timeout is not None else ps_timeout_pair(cfg)
    final_name = filename or "image.jpg"
    ext = os.path.splitext(final_name.lower())[1]
    mime = _IMAGE_MIME_BY_EXT.get(ext, "image/jpeg")
    files = {"image": (final_name, image_data, mime)}
    resp = requests.post(
        url, auth=auth, files=files, timeout=req_timeout, verify=verify,
        headers={"User-Agent": _peecha_user_agent()},
    )
    _raise_for_status(resp, f"آپلود تصویر محصول #{product_id}")
    try:
        root = ET.fromstring(resp.text)
        id_text = root.findtext(".//id")
        if id_text and id_text.strip().isdigit():
            return int(id_text.strip())
    except Exception:
        pass
    raise PrestaShopAPIError(f"آپلود تصویر محصول #{product_id}: id در پاسخ یافت نشد.")


def ps_upload_category_image(config, category_id: int, image_data: bytes, filename: str, *, timeout=None) -> int:
    """آپلود تصویر یک دسته — POST images/categories/{id}، مثل ps_upload_product_image
    ولی روی منبع categories؛ پرستاشاپ برای هر دسته فقط یک تصویر (کاور) داره،
    آپلود جدید جایگزین قبلی می‌شه (برخلاف گالری محصول که چندتایی و افزوده‌شونده‌ست)."""
    cfg = config or {}
    url = ps_endpoint(cfg.get("PS_URL", ""), f"images/categories/{int(category_id)}")
    if not url:
        raise PrestaShopAPIError("PS_URL خالی است.")
    auth = get_ps_auth(cfg)
    verify = bool(cfg.get("PS_VERIFY_SSL", False))
    req_timeout = timeout if timeout is not None else ps_timeout_pair(cfg)
    final_name = filename or "image.jpg"
    ext = os.path.splitext(final_name.lower())[1]
    mime = _IMAGE_MIME_BY_EXT.get(ext, "image/jpeg")
    files = {"image": (final_name, image_data, mime)}
    resp = requests.post(
        url, auth=auth, files=files, timeout=req_timeout, verify=verify,
        headers={"User-Agent": _peecha_user_agent()},
    )
    _raise_for_status(resp, f"آپلود تصویر دسته #{category_id}")
    try:
        root = ET.fromstring(resp.text)
        id_text = root.findtext(".//id")
        if id_text and id_text.strip().isdigit():
            return int(id_text.strip())
    except Exception:
        pass
    raise PrestaShopAPIError(f"آپلود تصویر دسته #{category_id}: id در پاسخ یافت نشد.")


def ps_delete_product_image(config, product_id: int, image_id: int, *, timeout=None) -> None:
    """حذف یک تصویر از گالری محصول — DELETE images/products/{product}/{image}.

    ⚠️ برخلاف بقیه‌ی مسیرهای این فایل، این مسیر (به‌همراه ps_get_product_image_ids
    زیر) روی مستندات رسمی Webservice نوشته شده ولی هنوز روی یک فروشگاه واقعی
    تأیید نشده — پرستاشاپ برای گالری تصاویر، برخلاف ووکامرس، آرایه‌ی «ست‌کردن
    یک‌جا» نداره؛ هر تصویر جدا آپلود/حذف می‌شه.
    """
    cfg = config or {}
    resp = ps_call(
        f"حذف تصویر #{image_id} محصول #{product_id}",
        lambda: ps_rest_request(
            cfg, "DELETE", f"images/products/{int(product_id)}/{int(image_id)}", timeout=timeout,
        ),
    )
    if getattr(resp, "status_code", 0) == 404:
        return
    _raise_for_status(resp, f"حذف تصویر #{image_id} محصول #{product_id}")


def ps_get_product_image_ids(config, product_id: int, *, timeout=None) -> list[int]:
    """شناسه‌ی تصاویر فعلی گالری محصول — از associations.images محصول خام."""
    cfg = config or {}
    resp = ps_call(
        f"دریافت تصاویر محصول #{product_id}",
        lambda: ps_rest_request(cfg, "GET", f"products/{int(product_id)}", timeout=timeout),
    )
    if getattr(resp, "status_code", 0) == 404:
        return []
    data = _response_json(resp, f"دریافت تصاویر محصول #{product_id}")
    entry = _unwrap_dict(data, "product")
    images = (entry.get("associations") or {}).get("images") or []
    out = []
    for item in images:
        if isinstance(item, dict) and item.get("id"):
            try:
                out.append(int(item["id"]))
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# تست اتصال
# ---------------------------------------------------------------------------

def check_prestashop_connection(config=None, update_config_status=True):
    """(ok, message, currency) — شبیه check_woocommerce_connection."""
    cfg = config or {}
    ps_url = (cfg.get("PS_URL") or "").strip()
    ps_key = (cfg.get("PS_API_KEY") or "").strip()
    currency_code = "N/A"

    if not ps_url or not ps_key:
        return False, "تنظیمات API پرستاشاپ کامل نیستند (آدرس/کلید Webservice).", currency_code

    try:
        resp = ps_rest_request(cfg, "GET", "", params={"limit": "0,1"})
        if resp.status_code == 401:
            return False, "کلید Webservice پرستاشاپ نامعتبر است یا دسترسی Webservice غیرفعال است.", currency_code
        if resp.status_code >= 400:
            return False, _ps_error_message(resp), currency_code

        try:
            langs_resp = ps_rest_request(cfg, "GET", "languages", params={"limit": "0,1"})
            if langs_resp.status_code == 200:
                pass
        except Exception:
            pass

        try:
            cur_resp = ps_rest_request(
                cfg, "GET", "currencies",
                params={"filter[id_default]": "[1]"} if False else {},
            )
            if cur_resp.status_code == 200:
                data = cur_resp.json()
                rows = _unwrap_list(data, "currencies")
                if rows:
                    currency_code = str(rows[0].get("iso_code") or "N/A").upper()
        except Exception:
            pass

        host = ps_store_host(cfg)
        return True, f"اتصال موفق. سایت: {host or ps_url}", currency_code
    except requests.exceptions.Timeout:
        return False, "زمان اتصال به پرستاشاپ به پایان رسید (Timeout).", currency_code
    except requests.exceptions.RequestException as req_err:
        return False, f"خطای شبکه/پروتکل: {req_err}", currency_code
    except Exception as e:
        return False, f"خطای کلی اتصال پرستاشاپ: {e}", currency_code
