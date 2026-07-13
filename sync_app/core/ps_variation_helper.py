"""
sync واریانت/ویژگی محصول برای پرستاشاپ (Phase 2).

معادل پرستاشاپیِ «ویژگی سراسری + ترم» ووکامرس:
  - product_options          = گروه ویژگی (مثلاً «سایز»)
  - product_option_values    = مقدار داخل گروه (مثلاً «XL»)
  - combinations              = خودِ واریانت — reference (SKU)، price
    (impact نسبت به قیمت پایه محصول، نه قیمت مطلق)، و association به
    چند product_option_value.
  - موجودی هر واریانت مثل محصول ساده از stock_availables می‌آید، فقط
    id_product_attribute برابر id همان combination است (نه صفر).

داده‌ی ورودی (variations/attr_map) از fetch_variations_from_db در
update_variations.py می‌آید — همان تابعی که برای ووکامرس هم استفاده
می‌شود؛ کاملاً مستقل از پلتفرم است (فقط از ERP می‌خواند).

⚠️ مثل بقیه‌ی بخش پرستاشاپ، هنوز روی یک فروشگاه واقعی تست نشده.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from sync_app.core.ps_api_helper import ps_lang_id
from sync_app.core.ps_sync_helper import (
    PrestaShopAPIError,
    _build_xml,
    _lang_value,
    _raise_for_status,
    _response_json,
    _response_xml_id,
    _set_lang_text,
    _set_text,
    _unwrap_dict,
    _unwrap_list,
    ps_call,
    ps_rest_request,
    ps_set_stock_quantity,
)


# ---------------------------------------------------------------------------
# گروه‌های ویژگی (product_options)
# ---------------------------------------------------------------------------

def _group_to_shape(entry: dict, lang_id: int) -> dict:
    return {
        "id": int(entry.get("id") or 0),
        "name": _lang_value(entry.get("name"), lang_id),
        "group_type": str(entry.get("group_type") or "select"),
    }


def ps_list_attribute_groups(config, *, timeout=None) -> list[dict]:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    out: list[dict] = []
    offset = 0
    page_size = 100
    while True:
        resp = ps_call(
            f"دریافت گروه‌های ویژگی offset={offset}",
            lambda o=offset: ps_rest_request(
                cfg, "GET", "product_options",
                # بدون display=full فقط id برمی‌گرده — name خالی می‌مونه و
                # گروه موجود هیچ‌وقت با نام پیدا نمی‌شه (ساخت گروه تکراری).
                params={"limit": f"{o},{page_size}", "display": "full"},
                timeout=timeout,
            ),
        )
        data = _response_json(resp, "دریافت گروه‌های ویژگی")
        batch = _unwrap_list(data, "product_options")
        if not batch:
            break
        for entry in batch:
            if isinstance(entry, dict) and entry.get("id"):
                out.append(_group_to_shape(entry, lang_id))
        if len(batch) < page_size:
            break
        offset += page_size
    return out


def ps_create_attribute_group(config, name: str, *, group_type: str = "select", timeout=None) -> dict:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)

    def _build(node):
        _set_lang_text(node, "name", name, lang_id)
        _set_lang_text(node, "public_name", name, lang_id)
        _set_text(node, "group_type", group_type)
        _set_text(node, "position", 0)

    body = _build_xml("product_option", _build)
    resp = ps_call(
        f"ایجاد گروه ویژگی '{name}'",
        lambda: ps_rest_request(cfg, "POST", "product_options", xml_body=body, timeout=timeout),
    )
    new_id = _response_xml_id(resp, f"ایجاد گروه ویژگی '{name}'")
    return {"id": new_id, "name": name, "group_type": group_type}


def ps_ensure_attribute_group(config, name: str, *, timeout=None) -> int:
    """گروه ویژگی با این نام را برمی‌گرداند — اگر نبود می‌سازد."""
    name_norm = str(name or "").strip()
    if not name_norm:
        raise PrestaShopAPIError("نام گروه ویژگی خالی است.")
    for group in ps_list_attribute_groups(config, timeout=timeout):
        if group["name"].strip() == name_norm:
            return group["id"]
    return ps_create_attribute_group(config, name_norm, timeout=timeout)["id"]


def ps_get_attribute_group(config, group_id: int, *, timeout=None) -> dict | None:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        f"دریافت گروه ویژگی #{group_id}",
        lambda: ps_rest_request(cfg, "GET", f"product_options/{int(group_id)}", timeout=timeout),
    )
    if getattr(resp, "status_code", 0) == 404:
        return None
    data = _response_json(resp, f"دریافت گروه ویژگی #{group_id}")
    entry = _unwrap_dict(data, "product_option")
    if not entry.get("id"):
        return None
    return _group_to_shape(entry, lang_id)


def ps_update_attribute_group(config, group_id: int, *, name: str, timeout=None) -> None:
    """PUT کامل — چون Webservice پرستاشاپ فیلد ست‌نشده رو خالی می‌کنه، اول رکورد فعلی خونده می‌شه."""
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    current = ps_get_attribute_group(cfg, group_id, timeout=timeout) or {}
    group_type = str(current.get("group_type") or "select")

    def _build(node):
        _set_text(node, "id", int(group_id))
        _set_lang_text(node, "name", name, lang_id)
        _set_lang_text(node, "public_name", name, lang_id)
        _set_text(node, "group_type", group_type)
        _set_text(node, "position", 0)

    body = _build_xml("product_option", _build)
    resp = ps_call(
        f"به‌روزرسانی گروه ویژگی #{group_id}",
        lambda: ps_rest_request(cfg, "PUT", f"product_options/{int(group_id)}", xml_body=body, timeout=timeout),
    )
    _raise_for_status(resp, f"به‌روزرسانی گروه ویژگی #{group_id}")


# ---------------------------------------------------------------------------
# مقادیر ویژگی (product_option_values)
# ---------------------------------------------------------------------------

def _value_to_shape(entry: dict, lang_id: int) -> dict:
    return {
        "id": int(entry.get("id") or 0),
        "name": _lang_value(entry.get("name"), lang_id),
        "group_id": int(entry.get("id_attribute_group") or 0),
    }


def ps_list_attribute_values(config, group_id: int, *, timeout=None) -> list[dict]:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        f"دریافت مقادیر گروه ویژگی #{group_id}",
        lambda: ps_rest_request(
            cfg, "GET", "product_option_values",
            # display=full لازمه وگرنه name خالی برمی‌گرده و مقدار موجود
            # همیشه «پیدا نشد» حساب می‌شه (مقدار ویژگی تکراری ساخته می‌شه).
            params={
                "filter[id_attribute_group]": f"[{int(group_id)}]",
                "limit": "0,1000",
                "display": "full",
            },
            timeout=timeout,
        ),
    )
    data = _response_json(resp, f"دریافت مقادیر گروه ویژگی #{group_id}")
    return [
        _value_to_shape(entry, lang_id)
        for entry in _unwrap_list(data, "product_option_values")
        if isinstance(entry, dict) and entry.get("id")
    ]


def ps_create_attribute_value(config, group_id: int, value_name: str, *, timeout=None) -> dict:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)

    def _build(node):
        _set_text(node, "id_attribute_group", int(group_id))
        _set_lang_text(node, "name", value_name, lang_id)
        _set_text(node, "position", 0)

    body = _build_xml("product_option_value", _build)
    resp = ps_call(
        f"ایجاد مقدار ویژگی '{value_name}'",
        lambda: ps_rest_request(cfg, "POST", "product_option_values", xml_body=body, timeout=timeout),
    )
    new_id = _response_xml_id(resp, f"ایجاد مقدار ویژگی '{value_name}'")
    return {"id": new_id, "name": value_name, "group_id": int(group_id)}


def ps_ensure_attribute_value(config, group_id: int, value_name: str, *, timeout=None) -> int:
    name_norm = str(value_name or "").strip()
    if not name_norm:
        raise PrestaShopAPIError("نام مقدار ویژگی خالی است.")
    for value in ps_list_attribute_values(config, group_id, timeout=timeout):
        if value["name"].strip() == name_norm:
            return value["id"]
    return ps_create_attribute_value(config, group_id, name_norm, timeout=timeout)["id"]


def ps_get_attribute_value(config, value_id: int, *, timeout=None) -> dict | None:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        f"دریافت مقدار ویژگی #{value_id}",
        lambda: ps_rest_request(cfg, "GET", f"product_option_values/{int(value_id)}", timeout=timeout),
    )
    if getattr(resp, "status_code", 0) == 404:
        return None
    data = _response_json(resp, f"دریافت مقدار ویژگی #{value_id}")
    entry = _unwrap_dict(data, "product_option_value")
    if not entry.get("id"):
        return None
    return _value_to_shape(entry, lang_id)


def ps_update_attribute_value(config, value_id: int, *, name: str, timeout=None) -> None:
    """PUT کامل — اول رکورد فعلی خونده می‌شه تا id_attribute_group از دست نره."""
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    current = ps_get_attribute_value(cfg, value_id, timeout=timeout) or {}
    group_id = int(current.get("group_id") or 0)

    def _build(node):
        _set_text(node, "id", int(value_id))
        _set_text(node, "id_attribute_group", group_id)
        _set_lang_text(node, "name", name, lang_id)
        _set_text(node, "position", 0)

    body = _build_xml("product_option_value", _build)
    resp = ps_call(
        f"به‌روزرسانی مقدار ویژگی #{value_id}",
        lambda: ps_rest_request(cfg, "PUT", f"product_option_values/{int(value_id)}", xml_body=body, timeout=timeout),
    )
    _raise_for_status(resp, f"به‌روزرسانی مقدار ویژگی #{value_id}")


# ---------------------------------------------------------------------------
# ترکیب‌های محصول (combinations) — خودِ واریانت
# ---------------------------------------------------------------------------

def _combination_option_value_ids(entry: dict) -> list[int]:
    assoc = (entry.get("associations") or {}).get("product_option_values") or []
    out = []
    for item in assoc:
        if isinstance(item, dict) and item.get("id"):
            try:
                out.append(int(item["id"]))
            except (TypeError, ValueError):
                continue
    return out


def _combination_to_shape(entry: dict) -> dict:
    return {
        "id": int(entry.get("id") or 0),
        "reference": str(entry.get("reference") or "").strip(),
        "price_impact": float(entry.get("price") or 0),
        "default_on": str(entry.get("default_on") or "0") == "1",
        "option_value_ids": _combination_option_value_ids(entry),
    }


def ps_get_combination(config, combination_id: int, *, timeout=None) -> dict | None:
    cfg = config or {}
    resp = ps_call(
        f"دریافت ترکیب واریانت #{combination_id}",
        lambda: ps_rest_request(cfg, "GET", f"combinations/{int(combination_id)}", timeout=timeout),
    )
    if getattr(resp, "status_code", 0) == 404:
        return None
    data = _response_json(resp, f"دریافت ترکیب واریانت #{combination_id}")
    entry = _unwrap_dict(data, "combination")
    if not entry.get("id"):
        return None
    return entry


def ps_list_combinations(config, product_id: int, *, timeout=None) -> list[dict]:
    """لیست واریانت‌های یک محصول — شکل {id, reference, price_impact, default_on, option_value_ids}."""
    cfg = config or {}
    resp = ps_call(
        f"دریافت ترکیب‌های واریانت محصول #{product_id}",
        lambda: ps_rest_request(
            cfg, "GET", "combinations",
            params={"filter[id_product]": f"[{int(product_id)}]", "limit": "0,1000"},
            timeout=timeout,
        ),
    )
    data = _response_json(resp, f"دریافت ترکیب‌های واریانت محصول #{product_id}")
    rows = _unwrap_list(data, "combinations")
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        full = ps_get_combination(cfg, int(row["id"]), timeout=timeout)
        if full:
            out.append(_combination_to_shape(full))
    return out


def ps_create_combination(
    config, product_id: int, *, reference: str, price_impact: float,
    option_value_ids: list[int], default_on: bool = False, timeout=None,
) -> int:
    cfg = config or {}

    def _build(node):
        _set_text(node, "id_product", int(product_id))
        _set_text(node, "reference", reference)
        _set_text(node, "price", f"{float(price_impact or 0):.6f}")
        _set_text(node, "weight", "0.000000")
        _set_text(node, "default_on", 1 if default_on else 0)
        _set_text(node, "minimal_quantity", 1)
        assoc = ET.SubElement(node, "associations")
        povs = ET.SubElement(assoc, "product_option_values")
        for vid in option_value_ids:
            v = ET.SubElement(povs, "product_option_value")
            _set_text(v, "id", int(vid))

    body = _build_xml("combination", _build)
    resp = ps_call(
        f"ایجاد ترکیب واریانت {reference}",
        lambda: ps_rest_request(cfg, "POST", "combinations", xml_body=body, timeout=timeout),
    )
    return _response_xml_id(resp, f"ایجاد ترکیب واریانت {reference}")


def ps_update_combination(
    config, combination_id: int, *, reference: str | None = None, price_impact: float | None = None,
    option_value_ids: list[int] | None = None, default_on: bool | None = None, timeout=None,
) -> None:
    cfg = config or {}
    current = ps_get_combination(cfg, combination_id, timeout=timeout) or {}
    final_ref = reference if reference is not None else str(current.get("reference") or "")
    final_price = price_impact if price_impact is not None else float(current.get("price") or 0)
    final_default = (1 if default_on else 0) if default_on is not None else int(current.get("default_on") or 0)
    final_value_ids = (
        option_value_ids if option_value_ids is not None else _combination_option_value_ids(current)
    )
    id_product = int(current.get("id_product") or 0)

    def _build(node):
        _set_text(node, "id", int(combination_id))
        if id_product:
            _set_text(node, "id_product", id_product)
        _set_text(node, "reference", final_ref)
        _set_text(node, "price", f"{float(final_price or 0):.6f}")
        _set_text(node, "default_on", final_default)
        _set_text(node, "minimal_quantity", 1)
        assoc = ET.SubElement(node, "associations")
        povs = ET.SubElement(assoc, "product_option_values")
        for vid in final_value_ids:
            v = ET.SubElement(povs, "product_option_value")
            _set_text(v, "id", int(vid))

    body = _build_xml("combination", _build)
    resp = ps_call(
        f"به‌روزرسانی ترکیب واریانت #{combination_id}",
        lambda: ps_rest_request(cfg, "PUT", f"combinations/{combination_id}", xml_body=body, timeout=timeout),
    )
    _raise_for_status(resp, f"به‌روزرسانی ترکیب واریانت #{combination_id}")


def ps_delete_combination(config, combination_id: int, *, timeout=None) -> bool:
    """حذف کامل یک ترکیب واریانت — پرستاشاپ زباله‌دان نداره."""
    cfg = config or {}
    resp = ps_call(
        f"حذف ترکیب واریانت #{combination_id}",
        lambda: ps_rest_request(cfg, "DELETE", f"combinations/{int(combination_id)}", timeout=timeout),
    )
    if getattr(resp, "status_code", 0) == 404:
        return True
    _raise_for_status(resp, f"حذف ترکیب واریانت #{combination_id}")
    return True


def ps_list_all_combinations_grouped(config, *, timeout=None) -> dict[int, list[int]]:
    """id_product → لیست id ترکیب‌های واریانت — یک واکشی یک‌جا (بدون فیلتر)
    برای تشخیص ارزانِ «این محصول متغیره یا نه» بدون N+1 درخواست به‌ازای هر محصول
    (مثلاً برای تب تطبیق/Reconciliation)."""
    cfg = config or {}
    grouped: dict[int, list[int]] = {}
    offset = 0
    page_size = 1000
    while True:
        resp = ps_call(
            f"دریافت همه ترکیب‌های واریانت offset={offset}",
            lambda o=offset: ps_rest_request(
                cfg, "GET", "combinations",
                params={"limit": f"{o},{page_size}", "display": "full"},
                timeout=timeout,
            ),
        )
        data = _response_json(resp, "دریافت همه ترکیب‌های واریانت")
        rows = _unwrap_list(data, "combinations")
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            pid = int(row.get("id_product") or 0)
            cid = int(row["id"])
            if pid:
                grouped.setdefault(pid, []).append(cid)
        if len(rows) < page_size:
            break
        offset += page_size
    return grouped


# ---------------------------------------------------------------------------
# ارکستراتور — معادل sync_product_variations ووکامرس
# ---------------------------------------------------------------------------

def ps_sync_product_variations(
    config, product_id: int, variations: list[dict], attr_map: dict[str, list[str]],
    base_price_display, *, a_code: str = "", timeout=None,
) -> bool:
    """
    variations/attr_map از fetch_variations_from_db می‌آیند (همان تابع
    مشترک با ووکامرس). برای هر ترکیبِ سایز/رنگ یک combination در پرستاشاپ
    می‌سازد/به‌روز می‌کند و موجودی همان واریانت را روی stock_availables
    مخصوص آن combination می‌گذارد.
    """
    from sync_app.core.sync_utils import log

    if not variations:
        return True

    try:
        base_price = float(base_price_display or 0)
    except (TypeError, ValueError):
        base_price = 0.0

    group_ids: dict[str, int] = {}
    value_ids: dict[tuple[str, str], int] = {}
    try:
        for label, options in (attr_map or {}).items():
            label = str(label or "").strip()
            if not label:
                continue
            gid = ps_ensure_attribute_group(config, label, timeout=timeout)
            group_ids[label] = gid
            for opt in options:
                opt = str(opt or "").strip()
                if not opt:
                    continue
                value_ids[(label, opt)] = ps_ensure_attribute_value(config, gid, opt, timeout=timeout)
    except Exception as exc:
        log.error(f"❌ [{a_code}] ساخت گروه/مقدار ویژگی در پرستاشاپ ناموفق: {exc}")
        return False

    try:
        existing_by_ref = {
            c["reference"]: c for c in ps_list_combinations(config, product_id, timeout=timeout) if c.get("reference")
        }
    except Exception as exc:
        log.error(f"❌ [{a_code}] دریافت ترکیب‌های موجود از پرستاشاپ ناموفق: {exc}")
        existing_by_ref = {}

    has_default = any(c.get("default_on") for c in existing_by_ref.values())

    ok_count = 0
    failed_count = 0
    for var in variations:
        sku = str(var.get("sku") or "").strip()
        if not sku:
            continue

        option_ids: list[int] = []
        missing = False
        for attr in var.get("attributes") or []:
            if not isinstance(attr, dict):
                continue
            name = str(attr.get("name") or "").strip()
            option = str(attr.get("option") or "").strip()
            vid = value_ids.get((name, option))
            if vid:
                option_ids.append(vid)
            else:
                missing = True
        if missing or not option_ids:
            log.warning(f"⚠️ واریانت {sku}: مقدار ویژگی resolve نشد — رد شد.")
            failed_count += 1
            continue

        try:
            var_price = float(var.get("regular_price") or 0)
        except (TypeError, ValueError):
            var_price = 0.0
        price_impact = var_price - base_price
        try:
            stock_qty = max(0, int(var.get("stock_quantity") or 0))
        except (TypeError, ValueError):
            stock_qty = 0

        try:
            existing_combo = existing_by_ref.get(sku)
            if existing_combo:
                combo_id = int(existing_combo["id"])
                ps_update_combination(
                    config, combo_id, price_impact=price_impact, option_value_ids=option_ids, timeout=timeout,
                )
            else:
                is_default = not has_default
                combo_id = ps_create_combination(
                    config, product_id, reference=sku, price_impact=price_impact,
                    option_value_ids=option_ids, default_on=is_default, timeout=timeout,
                )
                if is_default:
                    has_default = True
            ps_set_stock_quantity(config, product_id, stock_qty, product_attribute_id=combo_id, timeout=timeout)
            ok_count += 1
            log.info(f"▸ [{a_code}] واریانت {sku} → قیمت={var_price:g} / موجودی={stock_qty}")
        except Exception as exc:
            log.error(f"❌ واریانت {sku} روی پرستاشاپ: {exc}")
            failed_count += 1

    log.info(f"📊 واریانت‌های [{a_code}] روی پرستاشاپ: {ok_count} موفق، {failed_count} خطا (از {len(variations)}).")
    return failed_count == 0
