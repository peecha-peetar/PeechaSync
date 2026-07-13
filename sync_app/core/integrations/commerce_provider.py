"""
لایه‌ی انتزاعی «فروشگاه» — ووکامرس یا پرستاشاپ.

STORE_PLATFORM در تنظیمات مشخص می‌کند کدام پلتفرم فعال است (پیش‌فرض:
woocommerce، برای سازگاری با نصب‌های قبلی). بیشتر کدهای sync (دسته‌بندی،
محصول ساده) به‌جای صدا زدن مستقیم wcapi/wc_rest_json، از توابع همین فایل
استفاده می‌کنند تا هر دو پلتفرم را بدون شاخه‌زدن در منطق تجاری پشتیبانی
کنند.

Phase 1: اتصال + دسته‌بندی + محصول ساده (بدون واریانت) + قیمت/موجودی.
واریانت/ویژگی، سفارش/مشتری، و مدیا/سئو/مارکتینگ برای پرستاشاپ هنوز
پیاده‌سازی نشده‌اند و در صورت استفاده خطای روشن می‌دهند (نه شکست خاموش).
"""

from __future__ import annotations

from typing import Any


def store_platform(config: dict | None) -> str:
    platform = str((config or {}).get("STORE_PLATFORM") or "woocommerce").strip().lower()
    return platform if platform in ("woocommerce", "prestashop") else "woocommerce"


def is_prestashop(config: dict | None) -> bool:
    return store_platform(config) == "prestashop"


def store_platform_label(config: dict | None) -> str:
    return "پرستاشاپ" if is_prestashop(config) else "ووکامرس"


# ---------------------------------------------------------------------------
# اتصال
# ---------------------------------------------------------------------------

def check_store_connection(config=None, update_config_status: bool = True):
    """(ok, message, currency)"""
    if is_prestashop(config):
        from sync_app.core.ps_sync_helper import check_prestashop_connection

        return check_prestashop_connection(config, update_config_status=update_config_status)
    from sync_app.core.sync_utils import check_woocommerce_connection

    return check_woocommerce_connection(config, update_config_status=update_config_status)


def fetch_store_slug_map(config, *, timeout=60, cancel_check=None) -> dict:
    if is_prestashop(config):
        from sync_app.core.ps_sync_helper import ps_fetch_slug_map

        return ps_fetch_slug_map(config, timeout=timeout, cancel_check=cancel_check)
    from sync_app.core.category_resolver import fetch_wc_slug_map

    return fetch_wc_slug_map(config, timeout=timeout, cancel_check=cancel_check)


# ---------------------------------------------------------------------------
# API شیءمانند سازگار با wcapi.get/post/put/delete
# ---------------------------------------------------------------------------

def build_store_api(config, verify_ssl=None):
    """شیء با متدهای get/post/put/delete — روی ووکامرس همان wcapi واقعی است."""
    if is_prestashop(config):
        return PrestaShopAPIAdapter(config)
    from sync_app.core.wc_sync_helper import build_wcapi

    return build_wcapi(config, verify_ssl=verify_ssl)


def warm_store_connection(api_obj, config=None) -> None:
    if is_prestashop(config):
        return
    from sync_app.core.wc_sync_helper import warm_wc_connection

    warm_wc_connection(api_obj)


def store_rest_json(
    config, method: str, path: str, *, params=None, json_body=None, label: str = "Store", timeout=None
):
    """معادل wc_rest_json ولی platform-aware — برای کدهایی که wcapi ندارند (مثل sync دسته‌بندی)."""
    if is_prestashop(config):
        return _ps_dispatch(config, method, path, params=params, json_body=json_body, timeout=timeout)
    from sync_app.core.wc_sync_helper import wc_rest_json

    return wc_rest_json(config, method, path, params=params, json_body=json_body, label=label, timeout=timeout)


# ---------------------------------------------------------------------------
# آداپتور پرستاشاپ — همان واژگان مسیر/JSON ووکامرس، پشت صحنه XML پرستاشاپ
# ---------------------------------------------------------------------------

class _FakeResponse:
    """شبیه requests.Response — فقط برای اینکه wc_parse_json/wc_call بدون تغییر کار کنند."""

    def __init__(self, data: Any, status_code: int = 200):
        self._data = data
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._data


class PrestaShopAPIAdapter:
    """رابط سازگار با wcapi.get/post/put/delete — پشت صحنه Webservice پرستاشاپ."""

    def __init__(self, config):
        self.config = config or {}

    def get(self, endpoint, params=None):
        data = _ps_dispatch(self.config, "GET", endpoint, params=params)
        return _FakeResponse(data)

    def post(self, endpoint, data=None):
        result = _ps_dispatch(self.config, "POST", endpoint, json_body=data)
        return _FakeResponse(result, status_code=201)

    def put(self, endpoint, data=None):
        result = _ps_dispatch(self.config, "PUT", endpoint, json_body=data)
        return _FakeResponse(result)

    def delete(self, endpoint, params=None):
        result = _ps_dispatch(self.config, "DELETE", endpoint, params=params)
        return _FakeResponse(result)


def _to_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ps_categories_list(config, params, timeout):
    from sync_app.core.ps_sync_helper import ps_list_categories

    all_cats = ps_list_categories(config, timeout=timeout)
    try:
        page = int((params or {}).get("page", 1) or 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int((params or {}).get("per_page", 100) or 100)
    except (TypeError, ValueError):
        per_page = 100
    start = max(0, (page - 1) * per_page)
    return all_cats[start : start + per_page]


def _ps_attr_group_to_wc_shape(group: dict) -> dict:
    name = str(group.get("name") or "")
    return {"id": group.get("id"), "name": name, "slug": name}


def _ps_attr_value_to_wc_shape(value: dict) -> dict:
    name = str(value.get("name") or "")
    return {"id": value.get("id"), "name": name, "slug": name}


def _ps_attribute_groups_list(config, timeout):
    """معادل GET products/attributes ووکامرس — گروه‌های ویژگی (سایز/رنگ)."""
    from sync_app.core.ps_variation_helper import ps_list_attribute_groups

    groups = ps_list_attribute_groups(config, timeout=timeout)
    return [_ps_attr_group_to_wc_shape(g) for g in groups]


def _ps_attribute_group_get(config, group_id, timeout):
    from sync_app.core.ps_sync_helper import PrestaShopAPIError
    from sync_app.core.ps_variation_helper import ps_get_attribute_group

    group = ps_get_attribute_group(config, group_id, timeout=timeout)
    if group is None:
        raise PrestaShopAPIError(f"گروه ویژگی #{group_id} در پرستاشاپ یافت نشد.")
    return _ps_attr_group_to_wc_shape(group)


def _ps_attribute_group_create(config, body, timeout):
    from sync_app.core.ps_variation_helper import ps_create_attribute_group

    created = ps_create_attribute_group(config, str(body.get("name") or ""), timeout=timeout)
    return _ps_attr_group_to_wc_shape(created)


def _ps_attribute_group_update(config, group_id, body, timeout):
    from sync_app.core.ps_variation_helper import ps_update_attribute_group

    name = str(body.get("name") or "")
    ps_update_attribute_group(config, group_id, name=name, timeout=timeout)
    return {"id": group_id, "name": name}


def _ps_attribute_values_list(config, group_id, page, timeout):
    """معادل GET products/attributes/{id}/terms ووکامرس — همه مقادیر یکجا روی page=1."""
    from sync_app.core.ps_variation_helper import ps_list_attribute_values

    if page != 1:
        return []
    values = ps_list_attribute_values(config, group_id, timeout=timeout)
    return [_ps_attr_value_to_wc_shape(v) for v in values]


def _ps_attribute_value_create(config, group_id, body, timeout):
    from sync_app.core.ps_variation_helper import ps_create_attribute_value

    created = ps_create_attribute_value(config, group_id, str(body.get("name") or ""), timeout=timeout)
    return _ps_attr_value_to_wc_shape(created)


def _ps_attribute_value_update(config, value_id, body, timeout):
    from sync_app.core.ps_variation_helper import ps_update_attribute_value

    name = str(body.get("name") or "")
    ps_update_attribute_value(config, value_id, name=name, timeout=timeout)
    return {"id": value_id, "name": name}


def _ps_products_search(config, params, timeout):
    from sync_app.core.ps_sync_helper import ps_find_product_by_reference

    params = params or {}
    if str(params.get("status") or "").strip() == "trash":
        # پرستاشاپ سطل‌زباله ندارد — محصول حذف‌شده واقعاً حذف است.
        return []
    sku = str(params.get("sku") or "").strip()
    if not sku:
        return []
    product = ps_find_product_by_reference(config, sku, timeout=timeout)
    return [product] if product else []


def _ps_apply_stock_from_payload(config, product_id, body, timeout):
    from sync_app.core.ps_sync_helper import ps_set_stock_quantity

    if "stock_quantity" in body:
        try:
            qty = int(body.get("stock_quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        ps_set_stock_quantity(config, product_id, qty, timeout=timeout)
    elif body.get("manage_stock") is False:
        # «همیشه موجود» / «دانلودی» — موجودی زیاد تا سفارش رد نشود
        ps_set_stock_quantity(config, product_id, 9999, timeout=timeout)


def _ps_product_create_from_payload(config, body, timeout):
    from sync_app.core.ps_sync_helper import ps_create_product, ps_get_product

    sku = str(body.get("sku") or "").strip()
    name = str(body.get("name") or sku)
    price = _to_float(body.get("regular_price"))
    description = str(body.get("description") or "")
    category_ids = [
        int(c["id"]) for c in (body.get("categories") or []) if isinstance(c, dict) and c.get("id")
    ]
    active = str(body.get("status") or "publish") == "publish"
    catalog_visibility = str(body.get("catalog_visibility") or "visible")

    created = ps_create_product(
        config,
        sku=sku,
        name=name,
        price=price,
        description=description,
        category_ids=category_ids,
        active=active,
        catalog_visibility=catalog_visibility,
        timeout=timeout,
    )
    _ps_apply_stock_from_payload(config, created["id"], body, timeout)
    full = ps_get_product(config, created["id"], timeout=timeout) or created
    full.setdefault("status", "publish" if active else "draft")
    return full


def _ps_product_update_from_payload(config, product_id, body, timeout):
    from sync_app.core.ps_sync_helper import ps_update_product, ps_get_product, PrestaShopAPIError

    keys = set(body.keys())
    if keys and keys <= {"categories"}:
        cat_ids = [
            int(c["id"]) for c in (body.get("categories") or []) if isinstance(c, dict) and c.get("id")
        ]
        ps_update_product(config, product_id, category_ids=cat_ids, timeout=timeout)
        return ps_get_product(config, product_id, timeout=timeout) or {"id": product_id}
    if keys and keys <= {"images"}:
        raise PrestaShopAPIError("آپلود گالری تصویر محصول برای پرستاشاپ هنوز پیاده‌سازی نشده است.")

    price = _to_float(body.get("regular_price")) if "regular_price" in body else None
    category_ids = None
    if "categories" in body:
        category_ids = [
            int(c["id"]) for c in (body.get("categories") or []) if isinstance(c, dict) and c.get("id")
        ]
    active = None
    if "status" in body:
        active = str(body.get("status") or "publish") == "publish"

    ps_update_product(
        config,
        product_id,
        sku=body.get("sku"),
        name=body.get("name"),
        price=price,
        description=body.get("description"),
        category_ids=category_ids,
        active=active,
        catalog_visibility=body.get("catalog_visibility"),
        timeout=timeout,
    )
    _ps_apply_stock_from_payload(config, product_id, body, timeout)
    full = ps_get_product(config, product_id, timeout=timeout) or {"id": product_id}
    full.setdefault("status", "publish" if active is not False else "draft")
    return full


def _ps_dispatch(config, method: str, path: str, *, params=None, json_body=None, timeout=None):
    from sync_app.core.ps_sync_helper import (
        PrestaShopAPIError,
        ps_create_category,
        ps_get_category,
        ps_get_product,
        ps_update_category,
    )

    method = (method or "GET").upper()
    params = params or {}
    body = json_body or {}
    clean_path = (path or "").strip("/")

    if clean_path == "products/categories":
        if method == "GET":
            return _ps_categories_list(config, params, timeout)
        if method == "POST":
            return ps_create_category(
                config,
                name=str(body.get("name") or ""),
                slug=str(body.get("slug") or ""),
                parent=int(body.get("parent") or 0),
                timeout=timeout,
            )

    elif clean_path.startswith("products/categories/"):
        cat_id_str = clean_path.rsplit("/", 1)[-1]
        if cat_id_str.isdigit():
            cat_id = int(cat_id_str)
            if method == "PUT":
                return ps_update_category(
                    config,
                    cat_id,
                    name=body.get("name"),
                    slug=body.get("slug"),
                    parent=body.get("parent"),
                    timeout=timeout,
                )
            if method == "GET":
                return ps_get_category(config, cat_id, timeout=timeout)

    elif clean_path == "products/attributes":
        if method == "GET":
            return _ps_attribute_groups_list(config, timeout)
        if method == "POST":
            return _ps_attribute_group_create(config, body, timeout)

    elif clean_path.endswith("/terms") and clean_path.startswith("products/attributes/"):
        group_id_str = clean_path[len("products/attributes/"):-len("/terms")]
        if group_id_str.isdigit():
            group_id = int(group_id_str)
            if method == "GET":
                page = int(params.get("page") or 1)
                return _ps_attribute_values_list(config, group_id, page, timeout)
            if method == "POST":
                return _ps_attribute_value_create(config, group_id, body, timeout)

    elif "/terms/" in clean_path and clean_path.startswith("products/attributes/"):
        value_id_str = clean_path.rsplit("/", 1)[-1]
        if value_id_str.isdigit() and method == "PUT":
            return _ps_attribute_value_update(config, int(value_id_str), body, timeout)

    elif clean_path.startswith("products/attributes/"):
        attr_id_str = clean_path[len("products/attributes/"):]
        if attr_id_str.isdigit():
            attr_id = int(attr_id_str)
            if method == "GET":
                return _ps_attribute_group_get(config, attr_id, timeout)
            if method == "PUT":
                return _ps_attribute_group_update(config, attr_id, body, timeout)

    elif clean_path == "products":
        if method == "GET":
            return _ps_products_search(config, params, timeout)
        if method == "POST":
            return _ps_product_create_from_payload(config, body, timeout)

    elif clean_path.startswith("products/"):
        pid_str = clean_path.rsplit("/", 1)[-1]
        if pid_str.isdigit():
            pid = int(pid_str)
            if method == "GET":
                data = ps_get_product(config, pid, timeout=timeout)
                if data is None:
                    raise PrestaShopAPIError(f"محصول #{pid} در پرستاشاپ یافت نشد.")
                return data
            if method == "PUT":
                return _ps_product_update_from_payload(config, pid, body, timeout)
            if method == "DELETE":
                from sync_app.core.ps_sync_helper import ps_delete_product

                ps_delete_product(config, pid, timeout=timeout)
                return {"id": pid, "deleted": True}

    elif clean_path.startswith("combinations/"):
        cid_str = clean_path.rsplit("/", 1)[-1]
        if cid_str.isdigit() and method == "DELETE":
            from sync_app.core.ps_variation_helper import ps_delete_combination

            ps_delete_combination(config, int(cid_str), timeout=timeout)
            return {"id": int(cid_str), "deleted": True}

    raise PrestaShopAPIError(
        f"عملیات '{method} /{clean_path}' هنوز برای پرستاشاپ پیاده‌سازی نشده است "
        "(فاز بعدی: واریانت/سفارش/مشتری/مدیا)."
    )
