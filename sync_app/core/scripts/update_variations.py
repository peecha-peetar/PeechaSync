"""sync واریانت‌ها (سایز و رنگ) از sql به woo."""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote

try:
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_utils import log
    from sync_app.core.currency_helper import erp_price_divisor
    from sync_app.core.article_price import (
        article_price_sc_id,
        article_price_sale_list_id,
        load_article_variant_prices,
        resolve_article_price,
    )
    from sync_app.core.category_price_list import resolve_article_price_sc_id
    from sync_app.core.product_selection import is_product_enabled, is_variation_enabled
    from sync_app.core.sql_connection_helper import open_sql_connection
    from sync_app.core.scripts.Poshakproperties import normalize_text
    from sync_app.core.wc_attr_cache import (
        attrs_fingerprint,
        load_product_attrs_fingerprint,
        load_wc_attr_cache,
        save_product_attrs_fingerprint,
        save_wc_attr_cache,
    )
    from sync_app.core.wc_sync_helper import (
        apply_network_overrides,
        build_wcapi,
        wc_call,
        warm_wc_connection,
        format_wc_network_error,
        wc_is_slow_connection,
    )
    from sync_app.core.product_woo_map_helper import (
        load_product_woo_map,
        save_product_woo_map,
        resolve_wc_product_id,
    )
    from sync_app.core.sync_cancel import check_cancelled, SyncCancelled
    from sync_app.core.field_sync_config import is_field_enabled
except ImportError:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_utils import log
    from sync_app.core.currency_helper import erp_price_divisor
    from sync_app.core.article_price import (
        article_price_sc_id,
        article_price_sale_list_id,
        load_article_variant_prices,
        resolve_article_price,
    )
    from sync_app.core.category_price_list import resolve_article_price_sc_id
    from sync_app.core.product_selection import is_product_enabled, is_variation_enabled
    from sync_app.core.sql_connection_helper import open_sql_connection
    from sync_app.core.scripts.Poshakproperties import normalize_text
    from sync_app.core.wc_attr_cache import (
        attrs_fingerprint,
        load_product_attrs_fingerprint,
        load_wc_attr_cache,
        save_product_attrs_fingerprint,
        save_wc_attr_cache,
    )
    from sync_app.core.wc_sync_helper import (
        apply_network_overrides,
        build_wcapi,
        wc_call,
        warm_wc_connection,
        format_wc_network_error,
        wc_is_slow_connection,
    )
    from sync_app.core.product_woo_map_helper import (
        load_product_woo_map,
        save_product_woo_map,
        resolve_wc_product_id,
    )
    from sync_app.core.sync_cancel import check_cancelled, SyncCancelled
    from sync_app.core.field_sync_config import is_field_enabled

from sync_app.core.variation_query import fetch_variation_rows
from sync_app.core.variation_rules import (
    build_attr_map_from_variations,
    count_non_empty_attributes,
    fetch_attribute_labels,
    fetch_attribute_labels_list,
    is_valid_bound_option,
    rows_to_sync_payloads,
    variation_bind_satisfied,
)

# Woo batch API تا ۱۰۰ آیتم در هر درخواست را می‌پذیرد — کمترین round-trip.
VARIATION_BATCH_SIZE = 100
# تعداد worker موازی روی شبکه سریع.
_VAR_PARALLEL_WORKERS = 10

_VAR_SYNC_SERIAL_ONLY = False
_VAR_SAVE_RETRIES = 2
_VAR_SAVE_BACKOFF = (1.0, 2.0)
_VAR_SAVE_GAP_SEC = 0.0
_LAST_VARIATION_NETWORK_ERROR = ""
_LAST_VARIATION_FAIL_HINTS: dict[str, str] = {}


def _configure_variation_network_mode(config):
    global _VAR_SYNC_SERIAL_ONLY, _VAR_SAVE_RETRIES, _VAR_SAVE_BACKOFF, _VAR_SAVE_GAP_SEC
    global _VAR_PARALLEL_WORKERS
    slow = wc_is_slow_connection(config)
    _VAR_SYNC_SERIAL_ONLY = slow or bool((config or {}).get("WC_VARIATION_SERIAL"))
    if _VAR_SYNC_SERIAL_ONLY:
        _VAR_SAVE_RETRIES = 5
        _VAR_SAVE_BACKOFF = (2.0, 4.0, 6.0, 8.0, 10.0)
        _VAR_SAVE_GAP_SEC = 0.8
        _log_step("شبکه کند — ارسال تک‌تک واریانت‌ها (بدون batch/موازی)")
    else:
        _VAR_SAVE_RETRIES = 2
        _VAR_SAVE_BACKOFF = (1.0, 2.0)
        _VAR_SAVE_GAP_SEC = 0.0
        try:
            _VAR_PARALLEL_WORKERS = max(2, int((config or {}).get("WC_PARALLEL_WORKERS", 10) or 10))
        except Exception:
            _VAR_PARALLEL_WORKERS = 10


def _is_network_timeout(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "timed out" in text or "connecttimeout" in text.replace(" ", "")


def _log_step(message):
    log.info(f"▸ {message}")


def _load_product_woo_map():
    return load_product_woo_map()


def _resolve_product_id(wcapi, a_code, product_map):
    return resolve_wc_product_id(wcapi, a_code, product_map, log_step=_log_step)


def _normalize_wc_slug(slug: str) -> str:
    """slug واقعی woo بدون pa_."""
    raw = unquote(str(slug or "").strip())
    if raw.startswith("pa_"):
        return raw[3:]
    return raw


def _global_meta_key(meta: dict) -> str:
    slug = _normalize_wc_slug(str(meta.get("slug") or meta.get("taxonomy") or ""))
    if not slug:
        return ""
    tax = slug if str(meta.get("taxonomy") or "").startswith("pa_") else f"pa_{slug}"
    if not tax.startswith("pa_"):
        tax = f"pa_{tax}"
    return f"attribute_{tax}"


def _global_attr_index(global_ids: dict) -> dict:
    """نام ERP، نام Woo و slug → همان meta."""
    index: dict = {}
    for key, meta in (global_ids or {}).items():
        if not isinstance(meta, dict):
            continue
        for candidate in (
            normalize_text(key),
            normalize_text(meta.get("name")),
            normalize_text(meta.get("slug")),
        ):
            if candidate and candidate not in index:
                index[candidate] = meta
    return index


def _lookup_global_attr_meta(global_ids: dict, erp_label: str):
    """تطبیق نام ویژگی ERP با attribute global ووکامرس."""
    norm = normalize_text(erp_label)
    if not norm or not global_ids:
        return None
    index = _global_attr_index(global_ids)
    if norm in index:
        return index[norm]
    for key, meta in index.items():
        if norm == key or norm in key or key in norm:
            return meta
    parts = [p.strip() for p in re.split(r"[+|,،]", norm) if p.strip()]
    for part in parts:
        if part in index:
            return index[part]
        for key, meta in index.items():
            if part == key or part in key or key in part:
                return meta
    return None


def _woo_attr_label(meta: dict, fallback: str = "") -> str:
    return str((meta or {}).get("name") or fallback or "").strip()


def _resolve_woo_dim_labels(
    global_ids: dict,
    dim1_erp: str,
    dim2_erp: str,
    dim3_erp: str = "",
) -> tuple[str, str, str]:
    """سازگاری قدیمی — سه برچسب اول."""
    labels = _resolve_woo_dim_labels_list(
        global_ids, [x for x in [dim1_erp, dim2_erp, dim3_erp] if x]
    )
    if not labels:
        return "", "", ""
    return (
        labels[0] if len(labels) > 0 else "",
        labels[1] if len(labels) > 1 else "",
        labels[2] if len(labels) > 2 else "",
    )


def _resolve_woo_dim_labels_list(
    global_ids: dict,
    erp_labels: list[str],
) -> list[str]:
    """برچسب‌های ERP را به نام attributeهای global Woo وصل می‌کند."""
    resolved: list[str] = []
    for erp in erp_labels or []:
        name = str(erp or "").strip()
        if not name:
            continue
        meta = _lookup_global_attr_meta(global_ids, name)
        if meta:
            resolved.append(_woo_attr_label(meta, name))
        else:
            log.info(f"ℹ️ ویژگی «{name}» در Woo نیست — از sync حذف شد.")
    return resolved


def _remap_attr_names_to_woo(attr_map: dict, erp_labels: list[str], woo_labels: list[str]) -> dict:
    """کلیدهای attr_map از نام ERP به نام Woo."""
    mapping = {}
    for idx, erp in enumerate(erp_labels):
        if idx < len(woo_labels) and erp and woo_labels[idx]:
            mapping[erp] = woo_labels[idx]
    out: dict = {}
    for name, opts in (attr_map or {}).items():
        woo_name = mapping.get(name, name)
        out[woo_name] = sorted(set(opts or []))
    return out


def _remap_variation_attr_names(variations: list[dict], erp_labels: list[str], woo_labels: list[str]) -> None:
    mapping = {}
    for idx, erp in enumerate(erp_labels):
        if idx < len(woo_labels) and erp and woo_labels[idx]:
            mapping[erp] = woo_labels[idx]
    for var in variations or []:
        for attr in var.get("attributes") or []:
            if not isinstance(attr, dict):
                continue
            erp_name = str(attr.get("name") or "").strip()
            if erp_name in mapping:
                attr["name"] = mapping[erp_name]


def _fetch_global_attribute_ids(wcapi):
    """لیست attributeهای global ووکامرس."""

    def _call():
        response = wcapi.get(
            "products/attributes",
            params={"per_page": 100, "_fields": "id,name,slug"},
        )
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError(f"پاسخ نامعتبر attributes: {data}")
        result = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            name = normalize_text(item.get("name"))
            attr_id = item.get("id")
            slug = _normalize_wc_slug(item.get("slug"))
            if name and attr_id:
                taxonomy = f"pa_{slug}" if slug else ""
                result[name] = {
                    "id": int(attr_id),
                    "name": str(item.get("name") or name).strip(),
                    "slug": slug,
                    "taxonomy": taxonomy,
                    "meta_key": _global_meta_key({"slug": slug, "taxonomy": taxonomy}),
                }
        return result

    return wc_call(wcapi, "دریافت attributes", _call)


def _apply_price(raw_price, config):
    try:
        val = float(raw_price or 0)
    except (TypeError, ValueError):
        val = 0.0
    if val <= 0:
        return "0"
    divisor = erp_price_divisor(config)
    return str(int(val / divisor))


def _resolve_article_price(row, price_col):
    return resolve_article_price(row, price_col, price_start_index=2)


def _fetch_attribute_labels(conn):
    return fetch_attribute_labels(conn)


def _fetch_attribute_labels_list(conn):
    return fetch_attribute_labels_list(conn)


def fetch_variations_from_db(
    conn,
    a_code,
    raw_base_price,
    size_label,
    color_label,
    dim3_label="",
    *,
    config=None,
):
    cursor = conn.cursor()
    rows = fetch_variation_rows(cursor, a_code)
    selected_groups = [str(g).strip() for g in (config or {}).get("SELECTED_SUB_GROUPS", []) if str(g).strip()]
    matched_group = next((g for g in selected_groups if str(a_code).startswith(g)), "")
    sc_id = resolve_article_price_sc_id(str(a_code), matched_group, config or {})
    sale_sc_id = article_price_sale_list_id(config or {})
    price_map = load_article_variant_prices(cursor, a_code, sc_id=sc_id)
    sale_map = (
        load_article_variant_prices(cursor, a_code, sc_id=sale_sc_id)
        if sale_sc_id and sale_sc_id != sc_id
        else {}
    )
    cursor.close()

    from sync_app.core.article_price import apply_price_markup
    price_map = {k: apply_price_markup(v, config or {}, is_sale=False) for k, v in price_map.items()}
    sale_map = {k: apply_price_markup(v, config or {}, is_sale=True) for k, v in sale_map.items()}

    def _woo_price(val):
        return _apply_price(val, config or {})

    variations, attr_map = rows_to_sync_payloads(
        rows,
        a_code,
        raw_base_price,
        size_label,
        color_label,
        dim3_label,
        price_by_poshak_id=price_map,
        sale_price_by_poshak_id=sale_map,
        apply_price=_woo_price,
    )
    if config:
        variations = [
            v for v in variations
            if is_variation_enabled(str(v.get("sku") or ""), config)
        ]
        attr_map = build_attr_map_from_variations(variations, size_label, color_label, dim3_label)
    return variations, attr_map


def _fetch_terms_for_attribute(wcapi, attr_name, meta):
    attr_id = meta["id"]

    def _fetch(aid=attr_id):
        response = wcapi.get(
            f"products/attributes/{aid}/terms",
            params={"per_page": 100, "_fields": "id,name,slug"},
        )
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError(f"پاسخ نامعتبر terms برای attribute {aid}: {data}")
        return data

    batch = wc_call(wcapi, f"دریافت terms برای attribute {attr_id}", _fetch, retries=1)
    term_map = {}
    for item in batch:
        if isinstance(item, dict) and item.get("name"):
            exact = str(item["name"]).strip()
            slug = str(item.get("slug") or exact).strip()
            term_map[normalize_text(exact)] = {"name": exact, "slug": slug}
    return normalize_text(attr_name), term_map


def _fetch_term_lookup(wcapi, global_attrs, only_names=None):
    """termهای سایز/رنگ رو از woo بگیر."""
    lookup = {}
    wanted = [normalize_text(n) for n in (only_names or []) if n]
    items = []
    seen_ids: set[int] = set()
    for attr_name, meta in global_attrs.items():
        if wanted:
            matched = normalize_text(attr_name) in wanted
            if not matched:
                for w in wanted:
                    found = _lookup_global_attr_meta(global_attrs, w)
                    if found and found.get("id") == meta.get("id"):
                        matched = True
                        break
            if not matched:
                continue
        aid = int(meta.get("id") or 0)
        if aid and aid in seen_ids:
            continue
        if aid:
            seen_ids.add(aid)
        items.append((attr_name, meta))

    if not items:
        return lookup

    if len(items) == 1:
        key, term_map = _fetch_terms_for_attribute(wcapi, items[0][0], items[0][1])
        lookup[key] = term_map
        return lookup

    with ThreadPoolExecutor(max_workers=min(6, len(items))) as pool:
        futures = [
            pool.submit(_fetch_terms_for_attribute, wcapi, name, meta)
            for name, meta in items
        ]
        for future in as_completed(futures):
            key, term_map = future.result()
            lookup[key] = term_map
    return lookup


def _resolve_wc_option(attr_name, option, term_lookup):
    norm_opt = normalize_text(option)
    if not norm_opt:
        return {"name": option, "slug": option}
    terms = term_lookup.get(normalize_text(attr_name), {})
    hit = terms.get(norm_opt)
    if hit:
        return hit
    clean = str(option).strip()
    return {"name": clean, "slug": clean}


def _apply_wc_term_names(attr_map, variations, term_lookup):
    """هم‌نام‌سازی optionها با termهای واقعی WooCommerce."""
    resolved_map = {}
    for name, options in attr_map.items():
        resolved_map[name] = sorted({
            _resolve_wc_option(name, opt, term_lookup)["name"] for opt in options if opt
        })

    for var in variations:
        for attr in var.get("attributes", []):
            aname = attr.get("name")
            if aname:
                resolved = _resolve_wc_option(aname, attr.get("option", ""), term_lookup)
                attr["option"] = resolved["name"]
                attr["_term_slug"] = resolved["slug"]
    return resolved_map


def _attribute_meta_key(taxonomy: str) -> str:
    tax = str(taxonomy or "").strip()
    if not tax:
        return ""
    return f"attribute_{tax}"


def _fetch_parent_attribute_map(wcapi, product_id):
    """attributeهای والد محصول از woo."""

    def _get():
        return wcapi.get(
            f"products/{product_id}",
            params={"context": "edit", "_fields": "id,attributes"},
        ).json()

    data = wc_call(wcapi, f"دریافت attributes محصول #{product_id}", _get, retries=2)
    result = {}
    if not isinstance(data, dict):
        return result
    for item in data.get("attributes") or []:
        if not isinstance(item, dict) or not item.get("variation"):
            continue
        norm = normalize_text(item.get("name"))
        if not norm:
            continue
        result[norm] = {
            "id": int(item["id"]) if item.get("id") else None,
            "name": str(item.get("name") or "").strip(),
            "slug": str(item.get("slug") or "").strip(),
            "options": list(item.get("options") or []),
        }
    return result


def _apply_parent_attribute_ids(variation_list, parent_map, global_ids):
    """نام attribute از والد بگیر، id نفرست."""
    for var in variation_list:
        for attr in var.get("attributes", []):
            norm = normalize_text(attr.get("name"))
            parent = parent_map.get(norm)
            if not parent:
                for pk, pv in parent_map.items():
                    if norm == pk or norm in pk or pk in norm:
                        parent = pv
                        break
            global_meta = _lookup_global_attr_meta(global_ids, attr.get("name"))
            if parent and parent.get("name"):
                attr["name"] = str(parent.get("name") or attr.get("name") or "").strip()
            elif global_meta:
                attr["name"] = str(global_meta.get("name") or attr.get("name") or "").strip()
            if global_meta:
                attr["_global_id"] = int(global_meta["id"])
                attr["_meta_key"] = str(global_meta.get("meta_key") or "").strip()
                attr["_term_slug"] = str(attr.get("_term_slug") or attr.get("option") or "").strip()
            attr.pop("id", None)


def _attach_global_ids(product_attributes, variation_list, attr_meta_map):
    """bind با name+option نه id."""
    for attr in product_attributes:
        meta = _lookup_global_attr_meta(attr_meta_map, attr.get("name"))
        if meta:
            attr["name"] = _woo_attr_label(meta, str(attr.get("name") or ""))
            attr.pop("id", None)

    for var in variation_list:
        for attr in var.get("attributes", []):
            key = normalize_text(attr.get("name"))
            meta = _lookup_global_attr_meta(attr_meta_map, attr.get("name"))
            if not meta:
                log.warning(f"⚠️ ویژگی global یافت نشد: {key}")
                continue
            option_name = (attr.get("option") or "").strip()
            term_slug = str(attr.get("_term_slug") or option_name).strip()
            if not option_name:
                log.warning(f"⚠️ option خالی برای ویژگی {key}")
                continue
            attr["name"] = str(meta.get("name") or attr.get("name") or key).strip()
            attr["option"] = option_name
            attr["_term_slug"] = term_slug
            attr["_global_id"] = int(meta["id"])
            attr["_meta_key"] = str(meta.get("meta_key") or _global_meta_key(meta)).strip()
            attr.pop("id", None)
            var.pop("meta_data", None)


def _ensure_attribute_terms(wcapi, attr_map, attr_meta_map, term_lookup=None):
    """term سایز/رنگ اگه نبود بساز."""
    for name, options in attr_map.items():
        norm_name = normalize_text(name)
        meta = _lookup_global_attr_meta(attr_meta_map, name)
        if not meta:
            continue
        attr_id = meta["id"]
        woo_name = normalize_text(_woo_attr_label(meta, name))
        existing = set()
        if term_lookup:
            for tk, tv in term_lookup.items():
                if tk == norm_name or tk == woo_name or norm_name in tk or tk in norm_name:
                    existing = set(tv.keys())
                    norm_name = tk
                    break
        if term_lookup and norm_name in term_lookup:
            existing = set(term_lookup[norm_name].keys())
        else:
            def _fetch_terms(aid=attr_id):
                response = wcapi.get(
                    f"products/attributes/{aid}/terms",
                    params={"per_page": 100},
                )
                data = response.json()
                if not isinstance(data, list):
                    raise RuntimeError(f"پاسخ نامعتبر terms برای attribute {aid}: {data}")
                return data

            batch = wc_call(wcapi, f"دریافت terms برای attribute {attr_id}", _fetch_terms, retries=1)
            existing = {
                normalize_text(item.get("name"))
                for item in batch
                if isinstance(item, dict) and item.get("name")
            }

        for option in options:
            norm_opt = normalize_text(option)
            if not norm_opt or norm_opt in existing:
                continue

            def _create_term(opt=option, aid=attr_id):
                return wcapi.post(
                    f"products/attributes/{aid}/terms",
                    {"name": opt},
                ).json()

            created = wc_call(wcapi, f"ساخت term '{option}'", _create_term, retries=1)
            existing.add(norm_opt)
            if term_lookup is not None:
                if isinstance(created, dict):
                    term_lookup.setdefault(norm_name, {})[norm_opt] = {
                        "name": str(created.get("name") or option).strip(),
                        "slug": str(created.get("slug") or option).strip(),
                    }
                else:
                    term_lookup.setdefault(norm_name, {})[norm_opt] = {
                        "name": str(option).strip(),
                        "slug": str(option).strip(),
                    }


def _build_product_attributes(attr_map, global_ids=None):
    """attributeهای محصول والد برای woo."""
    attrs = []
    for idx, (name, options) in enumerate(attr_map.items()):
        meta = _lookup_global_attr_meta(global_ids or {}, name)
        display_name = _woo_attr_label(meta, name)
        entry = {
            "name": display_name,
            "position": idx,
            "visible": True,
            "variation": True,
            "options": list(options),
        }
        if meta and meta.get("id"):
            entry["id"] = int(meta["id"])
        attrs.append(entry)
    return attrs


def _variation_attributes_name_only(var):
    """فقط name و option برای واریانت."""
    out = []
    for attr in var.get("attributes") or []:
        name = str(attr.get("name") or "").strip()
        option = str(attr.get("option") or "").strip()
        if name and option:
            out.append({"name": name, "option": option})
    return out


def _batch_payload_from_var(var, vid=None, config=None, a_code=""):
    payload = {
        "regular_price": var.get("regular_price"),
        "status": "publish",
        "attributes": _variation_attributes_name_only(var),
    }
    sku = str(var.get("sku") or "").strip()
    if is_field_enabled(config or {}, "SYNC_FIELD_VARIATION_STOCK"):
        from sync_app.core.stock_mode import resolve_variation_stock_mode, apply_stock_mode_to_payload
        selected_groups = [str(g).strip() for g in (config or {}).get("SELECTED_SUB_GROUPS", []) if str(g).strip()]
        matched_group = next((g for g in selected_groups if str(a_code).startswith(g)), "")
        v_mode = resolve_variation_stock_mode(sku, str(a_code), matched_group, config or {})
        apply_stock_mode_to_payload(payload, v_mode, int(var.get("stock_quantity") or 0))
    if sku:
        payload["sku"] = sku
    if vid:
        payload["id"] = int(vid)
        # فقط برای واریانت موجود (update) — واریانت جدید باید موجودی اولیه داشته باشد
        if not is_field_enabled(config or {}, "SYNC_FIELD_VARIATION_STOCK"):
            payload.pop("manage_stock", None)
            payload.pop("stock_quantity", None)
    return payload


def _batch_save_variations(wcapi, product_id, a_code, variations, id_by_sku, config=None):
    """ارسال batch واریانت‌ها — تکه‌تکه تا VARIATION_BATCH_SIZE."""
    creates: list[dict] = []
    updates: list[dict] = []
    for var in variations:
        sku = str(var.get("sku") or "").strip()
        vid = _lookup_variation_id(id_by_sku, sku) if sku else None
        payload = _batch_payload_from_var(var, vid, config=config, a_code=a_code)
        if not payload.get("attributes"):
            continue
        if vid:
            updates.append(payload)
        else:
            creates.append(payload)
    if not creates and not updates:
        return id_by_sku, 0, {}

    merged = dict(id_by_sku)
    saved = 0
    response_by_sku: dict[str, dict] = {}
    ops: list[tuple[str, dict]] = [("create", p) for p in creates] + [("update", p) for p in updates]
    for start in range(0, len(ops), VARIATION_BATCH_SIZE):
        chunk = ops[start : start + VARIATION_BATCH_SIZE]
        body = {"create": [], "update": []}
        for kind, payload in chunk:
            body[kind].append(payload)
        if not body["create"] and not body["update"]:
            continue
        part = start // VARIATION_BATCH_SIZE + 1
        total_parts = (len(ops) + VARIATION_BATCH_SIZE - 1) // VARIATION_BATCH_SIZE
        label = f"batch upsert {part}/{total_parts}"
        result = _batch_variations(wcapi, product_id, body, label, a_code)
        for key in ("create", "update"):
            for item in (result.get(key) or []):
                if not isinstance(item, dict):
                    continue
                if item.get("error"):
                    log.warning(f"⚠️ [{a_code}] batch/{key}: {item.get('error')}")
                    continue
                if not item.get("id"):
                    continue
                vid = int(item["id"])
                sku = str(item.get("sku") or "").strip()
                if sku:
                    _index_sku_aliases(merged, sku, vid)
                    for alias in _sku_aliases(sku):
                        response_by_sku[alias] = item
                saved += 1
    return merged, saved, response_by_sku


def _bind_failures_from_responses(variations, id_by_sku, response_by_sku):
    """بررسی bind از پاسخ batch — بدون GET اضافی."""
    failed = []
    for var in variations:
        sku = str(var.get("sku") or "").strip()
        vid = _lookup_variation_id(id_by_sku, sku) if sku else None
        if not vid:
            failed.append((var, None))
            continue
        resp = None
        if response_by_sku:
            for alias in _sku_aliases(sku):
                resp = response_by_sku.get(alias)
                if resp:
                    break
        if resp and variation_bind_satisfied(resp, var):
            continue
        failed.append((var, vid))
    return failed


def _save_variation_subset(wcapi, product_id, a_code, failed, id_by_sku, *, serial=False):
    if not failed:
        return 0, id_by_sku, 0
    vars_only = [var for var, _ in failed]
    return _save_all_variations(
        wcapi,
        product_id,
        a_code,
        vars_only,
        id_by_sku,
        use_slug_as_option=False,
        serial=serial,
    )


def _sku_aliases(sku):
    """دو فرمت sku واریانت."""
    sku = str(sku or "").strip()
    if not sku:
        return set()
    aliases = {sku}
    m = re.match(r"^(.+)-V(\d+)$", sku, re.IGNORECASE)
    if m:
        aliases.add(f"V{m.group(2)}-{m.group(1)}")
    m2 = re.match(r"^V(\d+)-(.+)$", sku, re.IGNORECASE)
    if m2:
        aliases.add(f"{m2.group(2)}-V{m2.group(1)}")
    return aliases


def _lookup_variation_id(by_sku, sku):
    for alias in _sku_aliases(sku):
        vid = by_sku.get(alias)
        if vid:
            return vid
    return None


def _variation_trait_key(attrs_source, *, from_wc: bool = False) -> str:
    """کلید تطبیق واریانت از روی optionهای attribute (مثل پیشرفته/ساده)."""
    opts: list[str] = []
    if from_wc:
        for attr in attrs_source or []:
            if not isinstance(attr, dict):
                continue
            opt = normalize_text(attr.get("option") or "")
            if opt:
                opts.append(opt.casefold())
    else:
        for attr in (attrs_source or {}).get("attributes") or attrs_source or []:
            if not isinstance(attr, dict):
                continue
            opt = normalize_text(attr.get("option") or "")
            if opt:
                opts.append(opt.casefold())
    if not opts:
        return ""
    return "|".join(sorted(set(opts)))


def _fetch_existing_variations_index(wcapi, product_id):
    """واریانت‌های Woo با sku و attribute — برای تطبیق سریع قیمت."""
    by_sku: dict[str, int] = {}
    by_id: dict[int, dict] = {}
    by_trait: dict[str, list[dict]] = {}
    page = 1
    while True:
        check_cancelled()
        page_num = page

        def _fetch(p=page_num):
            response = wcapi.get(
                f"products/{product_id}/variations",
                params={
                    "per_page": 100,
                    "page": p,
                    "_fields": "id,sku,attributes",
                },
            )
            data = response.json()
            if not isinstance(data, list):
                raise RuntimeError(f"پاسخ نامعتبر variations صفحه {p}: {data}")
            return data

        batch = wc_call(
            wcapi,
            f"واریانت‌های #{product_id} (صفحه {page_num})",
            _fetch,
            retries=1,
            backoff=(0.5,),
        )
        if not batch:
            break
        for item in batch:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            vid = int(item["id"])
            by_id[vid] = item
            sku = str(item.get("sku") or "").strip()
            if sku:
                _index_sku_aliases(by_sku, sku, vid)
            trait = _variation_trait_key(item.get("attributes"), from_wc=True)
            if trait:
                by_trait.setdefault(trait, []).append(item)
        if len(batch) < 100:
            break
        page += 1
    return by_sku, by_id, by_trait


def sync_variation_prices_quick(
    wcapi,
    conn,
    config,
    a_code,
    raw_price,
    product_map,
    *,
    size_label=None,
    color_label=None,
    variations=None,
):
    """فقط قیمت و موجودی واریانت‌های موجود — بدون bind/حذف/ساخت مجدد."""
    product_id = _resolve_product_id(wcapi, a_code, product_map)
    if not product_id:
        log.warning(f"⚠️ [{a_code}] محصول در Woo نیست — قیمت واریانت ارسال نشد.")
        return 0

    dim3_label = ""
    if size_label is None or color_label is None:
        size_label, color_label, dim3_label = _fetch_attribute_labels(conn)

    if variations is None:
        variations, _ = fetch_variations_from_db(
            conn,
            a_code,
            raw_price,
            size_label,
            color_label,
            dim3_label,
            config=config,
        )
    if not variations:
        from sync_app.core.integrations.erp_provider import erp_provider_label

        log.info(f"ℹ️ [{a_code}] واریانتی در {erp_provider_label(config)} نیست.")
        return 0

    by_sku, by_id, by_trait = _fetch_existing_variations_index(wcapi, product_id)
    if not by_id:
        log.info(f"ℹ️ [{a_code}] واریانتی در Woo نیست — ساخت از مسیر کامل...")
        return 0

    updates: list[dict] = []
    matched_vids: set[int] = set()
    unmatched: list[str] = []

    for var in variations:
        sku = str(var.get("sku") or "").strip()
        vid = _lookup_variation_id(by_sku, sku) if sku else None
        if not vid:
            trait = _variation_trait_key(var)
            candidates = by_trait.get(trait) or []
            open_candidates = [c for c in candidates if int(c.get("id") or 0) not in matched_vids]
            if len(open_candidates) == 1:
                vid = int(open_candidates[0]["id"])
        if not vid or vid in matched_vids:
            label = sku or _variation_trait_key(var) or "?"
            unmatched.append(label)
            continue

        matched_vids.add(vid)
        wc_sku = str((by_id.get(vid) or {}).get("sku") or "").strip()
        price = str(var.get("regular_price") or "0")
        patch = {
            "id": vid,
            "regular_price": price,
        }
        if is_field_enabled(config or {}, "SYNC_FIELD_VARIATION_STOCK"):
            from sync_app.core.stock_mode import resolve_variation_stock_mode, apply_stock_mode_to_payload
            selected_groups = [str(g).strip() for g in (config or {}).get("SELECTED_SUB_GROUPS", []) if str(g).strip()]
            matched_group = next((g for g in selected_groups if a_code.startswith(g)), "")
            v_mode = resolve_variation_stock_mode(wc_sku or sku, a_code, matched_group, config or {})
            apply_stock_mode_to_payload(patch, v_mode, int(var.get("stock_quantity") or 0))
        sale = str(var.get("sale_price") or "").strip()
        if sale and sale != "0":
            patch["sale_price"] = sale
        dejavu_meta = var.get("dejavu_meta") or []
        if dejavu_meta:
            patch["meta_data"] = list(dejavu_meta)
        updates.append(patch)
        log.info(
            f"▸ [{a_code}] #{vid} ({wc_sku or sku}) → قیمت={price}"
            + (f" / ویژه={sale}" if sale and sale != "0" else "")
        )

    if not updates:
        log.warning(
            f"⚠️ [{a_code}] تطبیق واریانت برای قیمت پیدا نشد"
            + (f" — نمونه: {', '.join(unmatched[:4])}" if unmatched else "")
        )
        return 0

    body = {"update": updates}
    result = _batch_variations(wcapi, product_id, body, "قیمت سریع", a_code)
    saved = _count_batch_ok(result, "update")
    log.info(f"✅ [{a_code}] قیمت {saved}/{len(updates)} واریانت → Woo #{product_id}")
    _prune_orphan_variations(wcapi, product_id, a_code, variations, config=config)
    return saved


def _build_variation_bind_body(var, *, bind_mode="name", use_slug_as_option=False):
    """body مربوط به bind سایز/رنگ."""
    attrs = []
    meta = []
    for attr in var.get("attributes", []):
        option = (attr.get("option") or "").strip()
        term_slug = (attr.get("_term_slug") or option).strip()
        name = (attr.get("name") or "").strip()
        gid = attr.get("_global_id")
        option_value = term_slug if use_slug_as_option else option
        meta_value = term_slug or option
        if not option_value and not meta_value:
            continue
        if bind_mode == "name" and name:
            attrs.append({"name": name, "option": option_value or meta_value})
        elif bind_mode == "id" and gid:
            attrs.append({"id": int(gid), "option": option_value or meta_value})
        meta_key = str(attr.get("_meta_key") or "").strip()
        if meta_key and meta_value:
            meta.append({"key": meta_key, "value": meta_value})

    body = {}
    if bind_mode == "meta":
        if meta:
            body["meta_data"] = meta
    else:
        if attrs:
            body["attributes"] = attrs
        if bind_mode == "id" and meta:
            body["meta_data"] = meta
    return body


def _build_variation_payload(
    var,
    vid=None,
    *,
    include_bind=True,
    bind_mode="name",
    use_slug_as_option=False,
):
    """قیمت + موجودی + sku + bind."""
    payload = {
        "regular_price": var.get("regular_price"),
        "manage_stock": var.get("manage_stock"),
        "stock_quantity": var.get("stock_quantity"),
        "status": "publish",
    }
    if include_bind:
        bind = _build_variation_bind_body(
            var, bind_mode=bind_mode, use_slug_as_option=use_slug_as_option
        )
        if bind.get("attributes"):
            payload["attributes"] = bind["attributes"]
        if bind.get("meta_data"):
            payload["meta_data"] = bind["meta_data"]

    sale = str(var.get("sale_price") or "").strip()
    if sale and sale != "0":
        payload["sale_price"] = sale

    dejavu_meta = var.get("dejavu_meta") or []
    if dejavu_meta:
        payload["meta_data"] = list(payload.get("meta_data") or []) + list(dejavu_meta)

    sku = str(var.get("sku") or "").strip()
    if sku:
        payload["sku"] = sku
    if vid:
        payload["id"] = vid
    return payload


def _build_stock_payload(var, vid=None):
    """همیشه bind هم بفرست."""
    return _build_variation_payload(var, vid, include_bind=True)


def _build_data_payload(var, vid=None):
    """اسم قدیمی تابع."""
    return _build_variation_payload(var, vid)


def _index_sku_aliases(by_sku, sku, vid):
    for alias in _sku_aliases(sku):
        by_sku[alias] = vid


def _expected_variation_keys(variations):
    """SKU و trait واریانت‌های ERP — برای تشخیص یتیم‌های Woo."""
    skus: set[str] = set()
    traits: set[str] = set()
    for var in variations or []:
        sku = str(var.get("sku") or "").strip()
        for alias in _sku_aliases(sku):
            skus.add(alias.casefold())
        trait = _variation_trait_key(var)
        if trait:
            traits.add(trait)
    return skus, traits


def _woo_variation_is_expected(item, expected_skus, expected_traits):
    """واریانت Woo باید بماند اگر SKU یا trait با ERP یکی باشد."""
    if not isinstance(item, dict):
        return False
    sku = str(item.get("sku") or "").strip()
    if sku:
        for alias in _sku_aliases(sku):
            if alias.casefold() in expected_skus:
                return True
    trait = _variation_trait_key(item.get("attributes"), from_wc=True)
    if trait and trait in expected_traits:
        return True
    return False


def _collect_orphan_variation_ids(by_id, variations):
    """شناسه واریانت‌های Woo که در لیست ERP نیستند."""
    if not by_id or not variations:
        return []
    expected_skus, expected_traits = _expected_variation_keys(variations)
    orphans = []
    for vid, item in by_id.items():
        if not _woo_variation_is_expected(item, expected_skus, expected_traits):
            orphans.append(int(vid))
    return orphans


def _parent_variation_attr_count(wcapi, product_id):
    """تعداد attributeهای variation روی محصول والد Woo."""

    def _get():
        response = wcapi.get(
            f"products/{product_id}",
            params={"_fields": "attributes"},
        )
        data = response.json()
        if not isinstance(data, dict):
            return 0
        return sum(
            1
            for attr in (data.get("attributes") or [])
            if isinstance(attr, dict) and attr.get("variation")
        )

    try:
        return int(
            wc_call(
                wcapi,
                f"ویژگی‌های والد #{product_id}",
                _get,
                retries=1,
                backoff=(0.5,),
            )
            or 0
        )
    except Exception:
        return 0


def _woo_variation_attr_dim_mismatch(wcapi, product_id, expected_dims):
    """واریانت‌های Woo کمتر از بعد ERP دارند — فقط قیمت کافی نیست."""
    if expected_dims <= 1:
        return False
    _, by_id, _ = _fetch_existing_variations_index(wcapi, product_id)
    if not by_id:
        return False
    for item in by_id.values():
        attrs = item.get("attributes") or []
        bound = sum(
            1
            for attr in attrs
            if isinstance(attr, dict) and str(attr.get("option") or "").strip()
        )
        if bound < expected_dims:
            return True
    return False


def should_skip_full_variation_sync(
    wcapi,
    product_id,
    erp_variations,
    attr_map,
    *,
    a_code="",
    config=None,
):
    """
    مسیر سریع قیمت فقط وقتی مجاز است که ساختار ویژگی‌ها هم درست باشد.
    """
    if not product_id or not erp_variations:
        return False

    expected_dims = len(attr_map or {})
    if expected_dims <= 0:
        for var in erp_variations:
            n = len(
                [
                    a
                    for a in (var.get("attributes") or [])
                    if isinstance(a, dict) and str(a.get("option") or "").strip()
                ]
            )
            expected_dims = max(expected_dims, n)

    parent_count = _parent_variation_attr_count(wcapi, product_id)
    if parent_count < expected_dims:
        from sync_app.core.integrations.erp_provider import erp_provider_label

        log.info(
            f"ℹ️ [{a_code}] والد {parent_count} ویژگی variation دارد، "
            f"{erp_provider_label(config)} {expected_dims} — مسیر کامل..."
        )
        return False

    if attr_map:
        fp = attrs_fingerprint(attr_map)
        saved_fp = load_product_attrs_fingerprint(product_id)
        if saved_fp and saved_fp != fp:
            log.info(f"ℹ️ [{a_code}] fingerprint ویژگی عوض شده — مسیر کامل...")
            return False

    if _woo_variation_attr_dim_mismatch(wcapi, product_id, expected_dims):
        log.info(f"ℹ️ [{a_code}] واریانت‌های Woo ناقص‌اند — مسیر کامل...")
        return False

    missing, woo_total, erp_total = _variation_coverage(
        wcapi, product_id, erp_variations
    )
    if missing > 0 or woo_total > erp_total:
        return False
    return True


def _variation_coverage(wcapi, product_id, variations):
    """تعداد واریانت گم‌شده در Woo و کل موجود روی محصول."""
    by_sku, by_id, by_trait = _fetch_existing_variations_index(wcapi, product_id)
    erp_total = len(variations or [])
    woo_total = len(by_id)
    missing = 0
    for var in variations or []:
        sku = str(var.get("sku") or "").strip()
        vid = _lookup_variation_id(by_sku, sku) if sku else None
        if not vid:
            trait = _variation_trait_key(var)
            candidates = by_trait.get(trait) or []
            open_candidates = [
                c for c in candidates if isinstance(c, dict) and c.get("id")
            ]
            if len(open_candidates) == 1:
                vid = int(open_candidates[0]["id"])
        if not vid:
            missing += 1
    return missing, woo_total, erp_total


def _prune_orphan_variations(wcapi, product_id, a_code, variations, config=None):
    """حذف واریانت‌های اضافی Woo که در ERP نیستند (باقی‌مانده sync قبلی)."""
    if not product_id or not variations:
        return 0
    _, by_id, _ = _fetch_existing_variations_index(wcapi, product_id)
    orphan_ids = _collect_orphan_variation_ids(by_id, variations)
    if not orphan_ids:
        return 0
    from sync_app.core.integrations.erp_provider import erp_provider_label

    _log_step(
        f"[{a_code}] حذف {len(orphan_ids)} واریانت اضافی Woo "
        f"({erp_provider_label(config)}={len(variations)}، Woo={len(by_id)})"
    )
    _delete_variations(wcapi, product_id, a_code, orphan_ids)
    return len(orphan_ids)


def _fetch_existing_variations_by_sku(wcapi, product_id):
    """واریانت‌های موجود رو با sku index کن."""
    by_sku = {}
    by_id = {}
    page = 1
    while True:
        check_cancelled()
        page_num = page

        def _fetch(p=page_num):
            response = wcapi.get(
                f"products/{product_id}/variations",
                params={"per_page": 100, "page": p, "_fields": "id,sku"},
            )
            data = response.json()
            if not isinstance(data, list):
                raise RuntimeError(f"پاسخ نامعتبر variations صفحه {p}: {data}")
            return data

        batch = wc_call(
            wcapi,
            f"دریافت واریانت‌های #{product_id} (صفحه {page_num})",
            _fetch,
            retries=3,
            backoff=(1.0, 2.0, 3.0),
        )
        if not batch:
            break
        for item in batch:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            vid = int(item["id"])
            by_id[vid] = item
            sku = str(item.get("sku") or "").strip()
            if sku:
                _index_sku_aliases(by_sku, sku, vid)
        if len(batch) < 100:
            break
        page += 1
    return by_sku, by_id


def _count_batch_ok(result, key):
    ok = 0
    for item in (result.get(key) or []):
        if isinstance(item, dict) and item.get("id"):
            ok += 1
        elif isinstance(item, dict) and item.get("error"):
            log.warning(f"⚠️ batch/{key}: {item.get('error', item)}")
    return ok


def _force_parent_attributes(wcapi, product_id, a_code, product_attributes, config=None):
    categories = []
    if a_code and config:
        from sync_app.core.category_rules import prepare_category_context, resolve_product_categories

        ctx = prepare_category_context(config, fetch_live=True)
        categories = resolve_product_categories(
            a_code,
            ctx["category_map"],
            ctx["slug_map"],
        )
        if ctx.get("stale_updates"):
            log.info(
                f"🔄 [{a_code}] category_map: {', '.join(ctx['stale_updates'][:3])}"
            )

    payload = {
        "type": "variable",
        "attributes": product_attributes,
        "manage_stock": False,
    }
    if categories:
        payload["categories"] = categories

    def _put(body=payload):
        return wcapi.put(f"products/{product_id}", body).json()

    retries = 4 if _VAR_SYNC_SERIAL_ONLY else 2
    backoff = _VAR_SAVE_BACKOFF if _VAR_SYNC_SERIAL_ONLY else (1.0, 2.0)
    wc_call(wcapi, f"به‌روزرسانی attributes محصول {a_code}", _put, retries=retries, backoff=backoff)
    if categories:
        cat_ids = ", ".join(str(c["id"]) for c in categories)
        log.info(f"▸ [{a_code}] دسته محصول حفظ شد: [{cat_ids}]")
    parent_map = _fetch_parent_attribute_map(wcapi, product_id)
    if not parent_map:
        log.warning(f"⚠️ [{a_code}] attributes والد بعد از PUT هنوز خالی است")
    return parent_map


def _delete_variations(wcapi, product_id, a_code, variation_ids):
    ids = [int(v) for v in variation_ids if v]
    if not ids:
        return
    _log_step(f"[{a_code}] حذف {len(ids)} واریانت...")
    _batch_variations(wcapi, product_id, {"delete": ids}, "batch delete", a_code)


def _log_bind_debug(wcapi, product_id, vid, sku=""):
    try:
        data = wcapi.get(
            f"products/{product_id}/variations/{int(vid)}",
            params={"context": "edit"},
        ).json()
        attrs = data.get("attributes") if isinstance(data, dict) else None
        meta = [
            m for m in (data.get("meta_data") or [])
            if isinstance(m, dict) and str(m.get("key") or "").startswith("attribute_")
        ]
        stock = data.get("stock_quantity") if isinstance(data, dict) else None
        log.warning(
            f"⚠️ bind debug #{vid} sku={sku}: stock={stock} attrs={attrs} | meta={meta[:4]}"
        )
    except Exception as exc:
        log.warning(f"⚠️ bind debug #{vid}: {exc}")


def _log_variation_payload_sample(a_code, var):
    try:
        payload = _build_variation_payload(var, include_bind=True, bind_mode="name")
        log.info(
            f"▸ [{a_code}] نمونه payload: "
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
    except Exception as exc:
        log.warning(f"⚠️ [{a_code}] log payload: {exc}")


def _batch_variations(wcapi, product_id, body, label, a_code):
    def _batch():
        return wcapi.post(
            f"products/{product_id}/variations/batch",
            body,
        ).json()

    return wc_call(wcapi, f"{label} {a_code}", _batch, retries=3, backoff=(1.0, 2.0, 3.0))


_BIND_MODES = (
    ("name", False),
    ("id", False),
    ("id", True),
    ("meta", False),
)


def _save_variation(wcapi, product_id, a_code, var, vid=None, *, bind_mode="name", use_slug_as_option=False):
    """یک واریانت رو put/post کن."""
    payload = _build_variation_payload(
        var, vid, include_bind=True, bind_mode=bind_mode, use_slug_as_option=use_slug_as_option
    )
    if not payload.get("attributes") and not payload.get("meta_data"):
        log.warning(f"⚠️ [{a_code}] واریانت بدون bind — sku={var.get('sku')}")

    if vid:
        def _put():
            return wcapi.put(
                f"products/{product_id}/variations/{int(vid)}", payload
            ).json()

        return wc_call(
            wcapi,
            f"PUT واریانت {a_code} #{vid}",
            _put,
            retries=_VAR_SAVE_RETRIES,
            backoff=_VAR_SAVE_BACKOFF,
        )

    def _post():
        return wcapi.post(f"products/{product_id}/variations", payload).json()

    return wc_call(
        wcapi,
        f"POST واریانت {a_code}",
        _post,
        retries=_VAR_SAVE_RETRIES,
        backoff=_VAR_SAVE_BACKOFF,
    )


def _save_variation_with_bind(wcapi, product_id, a_code, var, vid=None):
    """چند بار bind رو با روش‌های مختلف امتحان کن."""
    last = None
    for mode, use_slug in _BIND_MODES:
        try:
            result = _save_variation(
                wcapi,
                product_id,
                a_code,
                var,
                vid,
                bind_mode=mode,
                use_slug_as_option=use_slug,
            )
            last = result
            if isinstance(result, dict) and variation_bind_satisfied(result, var):
                return result
            new_vid = int((result or {}).get("id") or vid or 0)
            if new_vid and mode == "name":
                verified = _verify_variation_bind(wcapi, product_id, new_vid, var)
                if verified:
                    return result
        except Exception as exc:
            log.warning(f"⚠️ [{a_code}] bind mode={mode} sku={var.get('sku')}: {exc}")
    return last


def _bind_variation_attributes(wcapi, product_id, a_code, var, vid, *, use_slug_as_option=False):
    return _save_variation_with_bind(wcapi, product_id, a_code, var, vid) is not None


def _collect_bind_updates(variations, id_by_sku):
    """دیگه batch bind نداریم."""
    return []


def _verify_all_variation_binds(wcapi, product_id, variations, id_by_sku):
    failed = []
    for var in variations:
        sku = str(var.get("sku") or "").strip()
        vid = _lookup_variation_id(id_by_sku, sku) if sku else None
        if not vid:
            failed.append((var, None))
            continue
        try:
            if not _verify_variation_bind(wcapi, product_id, vid, var):
                failed.append((var, vid))
        except Exception as exc:
            log.warning(f"⚠️ بررسی bind #{vid}: {exc}")
            failed.append((var, vid))
    return failed


def _save_all_variations(
    wcapi,
    product_id,
    a_code,
    variations,
    id_by_sku,
    *,
    use_slug_as_option=False,
    serial=False,
):
    """ذخیره هر واریانت با PUT/POST جدا."""
    saved = 0
    bound_from_response = 0
    merged_ids = dict(id_by_sku)
    workers = 1 if serial else min(_VAR_PARALLEL_WORKERS, max(1, len(variations)))

    def _one(var):
        sku = str(var.get("sku") or "").strip()
        vid = _lookup_variation_id(merged_ids, sku) if sku else None
        result = _save_variation_with_bind(wcapi, product_id, a_code, var, vid)
        return var, sku, vid, result

    if serial:
        results = []
        for var in variations:
            results.append(_one(var))
            if _VAR_SAVE_GAP_SEC > 0:
                time.sleep(_VAR_SAVE_GAP_SEC)
    else:
        results = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_one, var) for var in variations]
            for future in as_completed(futures):
                results.append(future.result())

    for var, sku, _old_vid, result in results:
        try:
            if isinstance(result, dict) and result.get("id"):
                vid = int(result["id"])
                if sku:
                    _index_sku_aliases(merged_ids, sku, vid)
                saved += 1
                if variation_bind_satisfied(result, var):
                    bound_from_response += 1
        except Exception as exc:
            log.warning(f"⚠️ [{a_code}] ذخیره واریانت {sku or '?'}: {exc}")
            if _is_network_timeout(exc):
                global _LAST_VARIATION_NETWORK_ERROR
                _LAST_VARIATION_NETWORK_ERROR = format_wc_network_error(exc)

    return saved, merged_ids, bound_from_response


def _bind_all_variation_attributes(wcapi, product_id, a_code, variations, id_by_sku, batch_result=None):
    """هر واریانت رو جدا put کن (batch جواب نمیده)."""
    _log_step(f"[{a_code}] bind سایز/رنگ ({len(variations)} واریانت — PUT تکی)...")
    saved, merged_ids, bound = _save_all_variations(
        wcapi, product_id, a_code, variations, id_by_sku, use_slug_as_option=False, serial=True
    )

    failed = _verify_all_variation_binds(wcapi, product_id, variations, merged_ids)
    if failed:
        log.warning(f"⚠️ [{a_code}] {len(failed)} واریانت bind نشده — retry با slug...")
        for var, vid in failed:
            if not vid:
                continue
            try:
                _save_variation_with_bind(wcapi, product_id, a_code, var, vid)
            except Exception as exc:
                log.warning(f"⚠️ [{a_code}] retry bind #{vid}: {exc}")

        still_failed = _verify_all_variation_binds(wcapi, product_id, variations, merged_ids)
        if still_failed:
            skus = [str(v.get("sku") or "?") for v, _ in still_failed]
            log.error(f"❌ [{a_code}] bind ناموفق برای: {', '.join(skus)}")
        else:
            _log_step(f"[{a_code}] ✅ bind با retry slug موفق شد")

    if saved:
        _log_step(f"[{a_code}] ✅ {saved} واریانت ذخیره شد")
    return saved


def _is_valid_bound_option(option) -> bool:
    return is_valid_bound_option(option)


def _count_expected_bind_attributes(var):
    return count_non_empty_attributes(var)


def _variation_has_bound_attributes(variation_data, *, expected_min=None, source_var=None):
    if source_var is not None:
        return variation_bind_satisfied(variation_data, source_var)
    if expected_min is not None:
        attrs = variation_data.get("attributes") or []
        bound = sum(
            1 for a in attrs
            if isinstance(a, dict) and is_valid_bound_option(a.get("option"))
        )
        return bound >= max(1, int(expected_min))
    return variation_bind_satisfied(variation_data)


def _verify_variation_bind(wcapi, product_id, vid, var=None):
    def _get():
        return wcapi.get(
            f"products/{product_id}/variations/{int(vid)}",
            params={"context": "edit"},
        ).json()

    data = wc_call(wcapi, f"بررسی bind #{vid}", _get, retries=1)
    return isinstance(data, dict) and variation_bind_satisfied(data, var)


def _verify_variation_stock(wcapi, product_id, vid, expected_stock):
    def _get():
        return wcapi.get(
            f"products/{product_id}/variations/{int(vid)}",
            params={"context": "edit", "_fields": "id,stock_quantity"},
        ).json()

    data = wc_call(wcapi, f"بررسی stock #{vid}", _get, retries=1)
    if not isinstance(data, dict):
        return False
    try:
        return int(data.get("stock_quantity") or 0) == int(expected_stock or 0)
    except (TypeError, ValueError):
        return False


def _verify_all_variation_stocks(wcapi, product_id, variations, id_by_sku):
    ok = 0
    for var in variations:
        sku = str(var.get("sku") or "").strip()
        vid = _lookup_variation_id(id_by_sku, sku) if sku else None
        if not vid:
            continue
        try:
            if _verify_variation_stock(wcapi, product_id, vid, var.get("stock_quantity")):
                ok += 1
        except Exception:
            pass
    return ok


def _upsert_variations_fast(
    wcapi,
    product_id,
    variations,
    a_code,
    product_attributes=None,
    global_ids=None,
    config=None,
):
    """PUT/POST تکی + recreate در صورت bind ناموفق."""
    total = len(variations)
    _log_step(f"[{a_code}] دریافت واریانت‌های Woo...")
    existing_by_sku, existing_by_id, _ = _fetch_existing_variations_index(wcapi, product_id)

    new_count = 0
    update_count = 0
    for var in variations:
        sku = str(var.get("sku") or "").strip()
        vid = _lookup_variation_id(existing_by_sku, sku) if sku else None
        if vid:
            update_count += 1
        else:
            new_count += 1
    extra_ids = _collect_orphan_variation_ids(existing_by_id, variations)

    from sync_app.core.integrations.erp_provider import erp_provider_label

    _log_step(
        f"[{a_code}] upsert → جدید:{new_count} | "
        f"آپدیت:{update_count} | حذف:{len(extra_ids)} | {erp_provider_label(config)}:{total}"
    )

    if extra_ids:
        _delete_variations(wcapi, product_id, a_code, extra_ids)
        existing_by_sku, existing_by_id, _ = _fetch_existing_variations_index(wcapi, product_id)

    def _run_save(id_map, *, serial, use_slug=False):
        return _save_all_variations(
            wcapi,
            product_id,
            a_code,
            variations,
            id_map,
            use_slug_as_option=use_slug,
            serial=serial,
        )

    if _VAR_SYNC_SERIAL_ONLY:
        _log_step(f"[{a_code}] ذخیره {total} واریانت (تک‌تک — شبکه کند)...")
        saved, id_by_sku, bound_resp = _run_save(existing_by_sku, serial=True)
        if saved >= total or saved > 0:
            _log_step(f"[{a_code}] ✅ {saved}/{total} واریانت")
            return saved
        return 0

    _log_step(f"[{a_code}] ذخیره {total} واریانت (batch)...")
    id_by_sku, batch_saved, batch_responses = _batch_save_variations(
        wcapi, product_id, a_code, variations, existing_by_sku, config=config
    )
    failed = _bind_failures_from_responses(variations, id_by_sku, batch_responses)
    if batch_saved >= total and not failed:
        _log_step(f"[{a_code}] ✅ batch — {batch_saved}/{total}")
        return batch_saved or total

    if failed:
        log.warning(
            f"⚠️ [{a_code}] تکمیل {len(failed)}/{total} واریانت (PUT فقط موارد ناقص)..."
        )
        saved_extra, id_by_sku, _bound_resp = _save_variation_subset(
            wcapi, product_id, a_code, failed, id_by_sku, serial=_VAR_SYNC_SERIAL_ONLY
        )
        failed = _bind_failures_from_responses(variations, id_by_sku, {})
        if not failed and (batch_saved + saved_extra) >= total:
            _log_step(f"[{a_code}] ✅ {batch_saved + saved_extra}/{total} واریانت")
            return batch_saved + saved_extra or total

    if failed:
        for var, vid in failed:
            if not vid:
                continue
            try:
                _save_variation_with_bind(wcapi, product_id, a_code, var, vid)
            except Exception as exc:
                log.warning(f"⚠️ [{a_code}] retry bind #{vid}: {exc}")
        failed = _bind_failures_from_responses(variations, id_by_sku, {})

    if not failed and batch_saved > 0:
        _log_step(f"[{a_code}] ✅ {batch_saved}/{total} واریانت")
        return batch_saved or total

    if len(failed) < total:
        skus = [str(v.get("sku") or "?") for v, _ in failed]
        log.error(f"❌ [{a_code}] bind ناموفق برای: {', '.join(skus)}")
        return max(batch_saved, total - len(failed))

    all_ids = list(set(existing_by_id.keys()) | set(id_by_sku.values()))
    log.warning(f"⚠️ [{a_code}] recreate {len(all_ids)} واریانت...")
    if failed and failed[0][1]:
        _log_bind_debug(wcapi, product_id, failed[0][1], str(failed[0][0].get("sku") or ""))

    if all_ids:
        _delete_variations(wcapi, product_id, a_code, all_ids)

    if product_attributes:
        parent_map = _force_parent_attributes(
            wcapi, product_id, a_code, product_attributes, config=config
        )
        if parent_map and global_ids:
            _apply_parent_attribute_ids(variations, parent_map, global_ids)

    id_by_sku2, batch_saved2, batch_responses2 = _batch_save_variations(
        wcapi, product_id, a_code, variations, {}, config=config
    )
    failed2 = _bind_failures_from_responses(variations, id_by_sku2, batch_responses2)
    if not failed2 and batch_saved2 >= total:
        _log_step(f"[{a_code}] ✅ recreate + batch ({batch_saved2}/{total})")
        return batch_saved2 or total

    if failed2:
        saved2, id_by_sku2, _bound2 = _save_variation_subset(
            wcapi, product_id, a_code, failed2, id_by_sku2, serial=True
        )
        failed2 = _bind_failures_from_responses(variations, id_by_sku2, batch_responses2)
        if not failed2:
            _log_step(f"[{a_code}] ✅ recreate — {saved2 or batch_saved2}/{total} واریانت")
            return saved2 or batch_saved2 or total

    if failed2:
        if variations:
            _log_variation_payload_sample(a_code, variations[0])
        skus = [str(v.get("sku") or "?") for v, _ in failed2]
        log.error(f"❌ [{a_code}] bind ناموفق برای: {', '.join(skus)}")
        return 0

    return batch_saved2 or total


def sync_product_variations(
    wcapi,
    conn,
    config,
    a_code,
    product_name,
    raw_price,
    global_ids=None,
    product_map=None,
    term_lookup=None,
    size_label=None,
    color_label=None,
):
    try:
        check_cancelled()
        if product_map is None:
            product_map = _load_product_woo_map()

        product_id = _resolve_product_id(wcapi, a_code, product_map)
        if not product_id:
            hint = (
                f"محصول {a_code} در Woo یافت نشد — "
                f"ابتدا از تب «محصولات» محصول {a_code} را ارسال کنید "
                "تا شناسه Woo آن ذخیره شود، سپس متغیرها را همگام کنید."
            )
            _LAST_VARIATION_FAIL_HINTS[a_code] = hint
            log.warning(f"⚠️ [{a_code}] {hint}")
            return False

        erp_dim_labels = _fetch_attribute_labels_list(conn)

        if global_ids is None:
            global_ids = _fetch_global_attribute_ids(wcapi)

        woo_dim_labels = _resolve_woo_dim_labels_list(global_ids, erp_dim_labels)
        if not woo_dim_labels:
            woo_names = ", ".join(
                str(m.get("name") or k) for k, m in list(global_ids.items())[:6]
            )
            hint = (
                f"ویژگی global یافت نشد: {erp_dim_labels[0] if erp_dim_labels else '—'} — "
                f"Woo دارد: {woo_names or '—'} — "
                "ابتدا تب «ویژگی‌ها» را همگام کنید."
            )
            _LAST_VARIATION_FAIL_HINTS[a_code] = hint
            log.warning(f"⚠️ [{a_code}] {hint}")
            return False
        if len(woo_dim_labels) < len(erp_dim_labels):
            from sync_app.core.integrations.erp_provider import erp_provider_label

            log.info(
                f"ℹ️ [{a_code}] {len(woo_dim_labels)} ویژگی از {len(erp_dim_labels)} "
                f"سطح {erp_provider_label(config)} روی Woo هست."
            )

        from sync_app.core.integrations.erp_provider import erp_provider_label

        _log_step(f"[{a_code}] خواندن {product_name} از {erp_provider_label(config)}...")
        variations, attr_map = fetch_variations_from_db(
            conn,
            a_code,
            raw_price,
            erp_dim_labels[0] if erp_dim_labels else "سایز",
            erp_dim_labels[1] if len(erp_dim_labels) > 1 else "",
            erp_dim_labels[2] if len(erp_dim_labels) > 2 else "",
            config=config,
        )
        attr_map = _remap_attr_names_to_woo(attr_map, erp_dim_labels, woo_dim_labels)
        _remap_variation_attr_names(variations, erp_dim_labels, woo_dim_labels)
        if not variations:
            from sync_app.core.integrations.erp_provider import erp_provider_label

            log.info(f"ℹ️ {a_code} ({product_name}) واریانت در {erp_provider_label(config)} ندارد — رد شد.")
            return None

        sample = variations[0]
        log.info(
            f"▸ [{a_code}] {len(variations)} واریانت — "
            f"نمونه {sample.get('sku')}: قیمت={sample.get('regular_price')}"
        )

        dim_names = list(woo_dim_labels)
        missing = [n for n in attr_map if not _lookup_global_attr_meta(global_ids, n)]
        if missing:
            woo_names = ", ".join(
                str(m.get("name") or k)
                for k, m in list(global_ids.items())[:6]
            )
            hint = (
                f"ویژگی global یافت نشد: {', '.join(missing)} — "
                f"Woo دارد: {woo_names or '—'} — "
                "ابتدا تب «ویژگی‌ها» را همگام کنید."
            )
            _LAST_VARIATION_FAIL_HINTS[a_code] = hint
            log.warning(f"⚠️ [{a_code}] {hint}")
            return False

        if term_lookup is None:
            term_lookup = _fetch_term_lookup(wcapi, global_ids, only_names=dim_names)

        _ensure_attribute_terms(wcapi, attr_map, global_ids, term_lookup)
        attr_map = _apply_wc_term_names(attr_map, variations, term_lookup)
        product_attributes = _build_product_attributes(attr_map, global_ids)
        _attach_global_ids(product_attributes, variations, global_ids)

        parent_map = _force_parent_attributes(
            wcapi, product_id, a_code, product_attributes, config=config
        )
        if parent_map:
            _apply_parent_attribute_ids(variations, parent_map, global_ids)
        else:
            hint = (
                f"ویژگی‌های محصول #{product_id} روی سایت ثبت نشد — "
                "اتصال Woo را بررسی کنید و تب «ویژگی‌ها» را همگام کنید."
            )
            _LAST_VARIATION_FAIL_HINTS[a_code] = hint
            log.error(f"❌ [{a_code}] {hint}")
            return False

        save_product_attrs_fingerprint(product_id, attrs_fingerprint(attr_map))

        synced = _upsert_variations_fast(
            wcapi, product_id, variations, a_code,
            product_attributes=product_attributes,
            global_ids=global_ids,
            config=config,
        )

        if synced > 0:
            log.info(
                f"✅ {product_name} ({a_code}): {synced} واریانت — "
                f"ویژگی‌ها: {', '.join(dim_names)}"
            )
            _LAST_VARIATION_FAIL_HINTS.pop(a_code, None)
            return True
        from sync_app.core.integrations.erp_provider import erp_provider_label

        hint = (
            f"واریانت‌ها در Woo ساخته/به‌روز نشدند ({len(variations)} مورد در {erp_provider_label(config)}) — "
            "لاگ bind را ببینید؛ معمولاً ویژگی global یا term سایز/رنگ مشکل دارد."
        )
        _LAST_VARIATION_FAIL_HINTS[a_code] = hint
        log.error(f"❌ [{a_code}] {hint}")
        return False

    except SyncCancelled:
        raise
    except Exception as exc:
        global _LAST_VARIATION_NETWORK_ERROR
        log.error(f"❌ خطا در {a_code}: {exc}")
        if _is_network_timeout(exc):
            _LAST_VARIATION_NETWORK_ERROR = format_wc_network_error(exc)
        return False


def _build_variation_targets(conn, selected_groups, config):
    """محصولات واقعاً متغیر (سایز/رنگ) در ERP، بر اساس زیرگروه‌های انتخاب‌شده."""
    dim_labels = _fetch_attribute_labels_list(conn)

    cursor = conn.cursor()
    cursor.execute(
        "SELECT A_Code, A_Name, Sel_Price, Sel_Price2, Sel_Price3, Sel_Price4, Sel_Price5 "
        "FROM Article WHERE LEN(A_Code) >= 4"
    )
    rows = cursor.fetchall()
    cursor.close()

    disabled_products = set(config.get("DISABLED_PRODUCT_SKUS", []) or [])
    from sync_app.core.variation_query import load_variable_a_codes
    variable_codes = load_variable_a_codes(cursor2 := conn.cursor())
    cursor2.close()
    targets = []
    skipped_simple = 0
    for row in rows:
        a_code = str(row[0]).strip()
        if a_code in disabled_products:
            continue
        if not is_product_enabled(a_code, config):
            continue
        if not any(a_code.startswith(group) for group in selected_groups):
            continue
        # نکته‌ی مهم (رفع باگ قبلی): این ماژول فقط برای محصولاتی که تو
        # ERP واقعاً متغیر (چند سایز/رنگ) هستن اجرا بشه — قبلاً روی همه‌ی
        # محصولات (حتی ساده) اجرا می‌شد و باعث می‌شد ووکامرس اشتباهی
        # برچسب «متغیر» به محصولات ساده بده.
        if a_code not in variable_codes:
            skipped_simple += 1
            continue
        targets.append(row)

    return dim_labels, targets, skipped_simple


def _main_prestashop(config, selected_groups, price_col):
    from sync_app.core.integrations.commerce_provider import build_store_api, warm_store_connection
    from sync_app.core.ps_variation_helper import ps_sync_product_variations
    from sync_app.core.article_price import apply_price_markup
    from sync_app.core.sync_change_cache import load_hash_cache, save_hash_cache, should_skip_unchanged
    from sync_app.core.field_sync_config import all_field_keys, is_force_full_sync
    from sync_app.core.field_sync_config import is_field_enabled as _is_field_enabled

    _log_step("پرستاشاپ: ساخت اتصال...")
    api = build_store_api(config)
    warm_store_connection(api, config)
    conn = None
    stats = {"ok": 0, "failed": 0, "skipped": 0, "failed_skus": [], "network_error": False}
    # این تب یه مسیرِ کاملاً جدا از سینکِ اصلیِ محصولات (sync_fullproduct.py)
    # بود — تشخیصِ تغییرِ اونجا این‌جا رو پوشش نمی‌داد، پس این تب همیشه
    # همه‌ی واریانت‌های همه‌ی محصولات رو از اول دوباره می‌فرستاد.
    hash_cache = load_hash_cache("variants", config)
    settings_fingerprint = {k: _is_field_enabled(config or {}, k) for k in all_field_keys()}
    skipped_unchanged = 0
    force_full_sync = is_force_full_sync(config, "FORCE_FULL_SYNC_VARIANTS")
    if force_full_sync:
        log.info("⚡ «همیشه همه‌ی واریانت‌ها دوباره ارسال شود» فعاله — تشخیصِ تغییر این دور نادیده گرفته می‌شه.")

    try:
        conn, _, _ = open_sql_connection(config, timeout=10)

        _log_step("مرحله ۱/۲: خواندن محصولات از SQL...")
        dim_labels, targets, skipped_simple = _build_variation_targets(conn, selected_groups, config)
        if skipped_simple:
            log.info(f"ℹ️ {skipped_simple} محصول ساده (بدون سایز/رنگ) از این مرحله رد شدن — نیازی به واریانت ندارن.")

        product_map = _load_product_woo_map()

        total = len(targets)
        _log_step(f"مرحله ۲/۲: همگام {total} محصول (پرستاشاپ)...")
        if total == 0:
            log.warning("⚠️ محصولی برای گروه‌های انتخاب‌شده یافت نشد.")
            return stats

        for idx, row in enumerate(targets, start=1):
            check_cancelled()
            a_code = str(row[0]).strip()
            name = str(row[1]).strip()
            _log_step(f"محصول {idx}/{total}: {a_code} ({name})")
            raw_price = _resolve_article_price(row, price_col)
            erp_variations, attr_map = fetch_variations_from_db(
                conn,
                a_code,
                raw_price,
                dim_labels[0] if dim_labels else "سایز",
                dim_labels[1] if len(dim_labels) > 1 else "",
                dim_labels[2] if len(dim_labels) > 2 else "",
                config=config,
            )
            if not erp_variations:
                from sync_app.core.integrations.erp_provider import erp_provider_label

                log.info(f"ℹ️ {a_code} ({name}) واریانت در {erp_provider_label(config)} ندارد — رد شد.")
                stats["skipped"] += 1
                continue

            product_id = _resolve_product_id(api, a_code, product_map)
            if not product_id:
                log.warning(f"⚠️ {a_code} ({name}) محصول والد روی پرستاشاپ لینک/پیدا نشد — رد شد.")
                stats["failed"] += 1
                stats["failed_skus"].append(a_code)
                continue

            hash_payload = {"variants": erp_variations, "attr_map": attr_map, "settings": settings_fingerprint}
            skip, cache_entry, changed_parts = should_skip_unchanged(a_code, hash_payload, hash_cache, product_id)
            if force_full_sync:
                skip = False
            if skip:
                skipped_unchanged += 1
                stats["ok"] += 1
                continue
            if changed_parts and a_code in hash_cache:
                log.info(f"🔍 [{a_code}] این بخش‌ها عوض شده: {', '.join(changed_parts)}")

            log.info(f"▸ [{a_code}] {len(erp_variations)} واریانت — در حال ارسال به پرستاشاپ...")

            base_price = _apply_price(apply_price_markup(raw_price, config, is_sale=False), config)
            ok = ps_sync_product_variations(
                config, product_id, erp_variations, attr_map, base_price, a_code=a_code,
            )
            if ok:
                stats["ok"] += 1
                hash_cache[a_code] = cache_entry
            else:
                stats["failed"] += 1
                stats["failed_skus"].append(a_code)

    except SyncCancelled as exc:
        log.warning(f"⏹ {exc}")
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        log.error(f"🛑 خطای بحرانی: {exc}")
        raise RuntimeError(str(exc)) from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        save_hash_cache("variants", hash_cache, config)

    ok_count = stats["ok"]
    fail_count = stats["failed"]
    skip_count = stats["skipped"]
    summary = f"📊 پایان همگام‌سازی متغیرها: {ok_count} موفق"
    if skipped_unchanged:
        summary += f" ({skipped_unchanged} بدون تغییر رد شد)"
    if skip_count:
        summary += f"، {skip_count} بدون واریانت"
    if fail_count:
        summary += f"، {fail_count} ناموفق"
    log.info(summary)

    if fail_count > 0 and ok_count == 0:
        sku_list = "، ".join(stats["failed_skus"][:8])
        raise RuntimeError(
            f"هیچ واریانتی همگام نشد ({fail_count} خطا).\n"
            f"SKU: {sku_list}\n\n"
            "۱) تب «تطبیق» -> «محصول»: کد والد (مثلاً 0301001) -> پرستاشاپ\n"
            "۲) ابتدا از تب «محصولات» محصول والد را ارسال کنید"
        )

    return stats


def main():
    global _LAST_VARIATION_NETWORK_ERROR
    _LAST_VARIATION_NETWORK_ERROR = ""
    _LAST_VARIATION_FAIL_HINTS.clear()
    _log_step("شروع همگام‌سازی متغیرها (سایز + رنگ)")
    config = load_secure_config(None) or {}
    _configure_variation_network_mode(config)
    selected_groups = [str(g).strip() for g in config.get("SELECTED_SUB_GROUPS", []) if str(g).strip()]
    price_col = (config.get("PRICE_LIST_COLUMN") or "Sel_Price").strip()

    if not selected_groups:
        log.warning("⚠️ هیچ زیرگروهی انتخاب نشده — از تب دسته‌بندی انتخاب کنید.")
        return

    from sync_app.core.integrations.commerce_provider import is_prestashop
    if is_prestashop(config):
        return _main_prestashop(config, selected_groups, price_col)

    apply_network_overrides(config)
    wcapi = build_wcapi(config)
    warm_wc_connection(wcapi)
    conn = None
    stats = {"ok": 0, "failed": 0, "skipped": 0, "failed_skus": [], "network_error": False}

    try:
        conn, _, _ = open_sql_connection(config, timeout=10)

        dim_labels, targets, skipped_simple = _build_variation_targets(conn, selected_groups, config)
        only_attrs = list(dim_labels)

        from sync_app.core.wc_attr_cache import load_wc_attr_cache

        cached_ids, cached_terms = load_wc_attr_cache(dim_labels)
        if cached_ids and cached_terms:
            _log_step("مرحله ۱-۲/۴: cache ویژگی Woo (سریع)")
            global_ids = cached_ids
            term_lookup = cached_terms
        else:
            _log_step("مرحله ۱/۴: دریافت attributes از Woo...")
            global_ids = _fetch_global_attribute_ids(wcapi)

            _log_step("مرحله ۲/۴: دریافت terms سایز/رنگ...")
            term_lookup = _fetch_term_lookup(wcapi, global_ids, only_names=only_attrs)
            save_wc_attr_cache(global_ids, term_lookup, dim_labels)

        product_map = _load_product_woo_map()

        if skipped_simple:
            log.info(f"ℹ️ {skipped_simple} محصول ساده (بدون سایز/رنگ) از این مرحله رد شدن — نیازی به واریانت ندارن.")

        total = len(targets)
        _log_step(f"مرحله ۴/۴: همگام {total} محصول...")
        if total == 0:
            log.warning("⚠️ محصولی برای گروه‌های انتخاب‌شده یافت نشد.")
            return stats

        for idx, row in enumerate(targets, start=1):
            check_cancelled()
            a_code = str(row[0]).strip()
            name = str(row[1]).strip()
            _log_step(f"محصول {idx}/{total}: {a_code} ({name})")
            raw_price = _resolve_article_price(row, price_col)
            erp_variations, attr_map = fetch_variations_from_db(
                conn,
                a_code,
                raw_price,
                dim_labels[0] if dim_labels else "سایز",
                dim_labels[1] if len(dim_labels) > 1 else "",
                dim_labels[2] if len(dim_labels) > 2 else "",
                config=config,
            )
            quick_saved = sync_variation_prices_quick(
                wcapi,
                conn,
                config,
                a_code,
                raw_price,
                product_map,
                size_label=dim_labels[0] if dim_labels else None,
                color_label=dim_labels[1] if len(dim_labels) > 1 else None,
                variations=erp_variations,
            )
            product_id = _resolve_product_id(wcapi, a_code, product_map)
            if quick_saved >= len(erp_variations) and erp_variations:
                skip_full = True
            elif (
                quick_saved > 0
                and product_id
                and erp_variations
            ):
                skip_full = should_skip_full_variation_sync(
                    wcapi,
                    product_id,
                    erp_variations,
                    attr_map,
                    a_code=a_code,
                    config=config,
                )
            else:
                skip_full = False
            if skip_full:
                stats["ok"] += 1
                continue

            log.info(f"▸ [{a_code}] مسیر کامل واریانت (ساخت/به‌روز)...")
            result = sync_product_variations(
                wcapi,
                conn,
                config,
                a_code,
                name,
                raw_price,
                global_ids,
                product_map,
                term_lookup,
                dim_labels[0] if dim_labels else None,
                dim_labels[1] if len(dim_labels) > 1 else None,
            )
            if result is True:
                stats["ok"] += 1
            elif result is None:
                stats["skipped"] += 1
            else:
                stats["failed"] += 1
                stats["failed_skus"].append(a_code)

    except SyncCancelled as exc:
        log.warning(f"⏹ {exc}")
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        log.error(f"🛑 خطای بحرانی: {exc}")
        stats["network_error"] = "timed out" in str(exc).lower() or "connecttimeout" in str(exc).lower()
        raise RuntimeError(format_wc_network_error(exc)) from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    ok_count = stats["ok"]
    fail_count = stats["failed"]
    skip_count = stats["skipped"]
    summary = f"📊 پایان همگام‌سازی متغیرها: {ok_count} موفق"
    if skip_count:
        summary += f"، {skip_count} بدون واریانت"
    if fail_count:
        summary += f"، {fail_count} ناموفق"
    log.info(summary)

    if fail_count > 0:
        sku_list = "، ".join(stats["failed_skus"][:8])
        detail_lines = []
        for sku in stats["failed_skus"][:4]:
            hint = _LAST_VARIATION_FAIL_HINTS.get(sku)
            if hint:
                detail_lines.append(f"• {sku}: {hint}")
        detail_block = "\n".join(detail_lines)
        if ok_count == 0:
            if _LAST_VARIATION_NETWORK_ERROR:
                raise RuntimeError(
                    f"هیچ واریانتی همگام نشد ({fail_count} خطا).\n"
                    f"SKU: {sku_list}\n\n{_LAST_VARIATION_NETWORK_ERROR}"
                )
            raise RuntimeError(
                f"هیچ واریانتی همگام نشد ({fail_count} خطا).\n"
                f"SKU: {sku_list}\n\n"
                + (f"{detail_block}\n\n" if detail_block else "")
                + "۱) تب «تطبیق» -> «محصول»: کد والد (مثلاً 0301001) -> Woo\n"
                "۲) تب «ویژگی‌ها» را همگام کنید\n"
                "۳) تب «متغیرها» — ساخت واریانت در Woo اینجا انجام می‌شود، نه در تب تطبیق"
            )
        raise RuntimeError(
            f"همگام‌سازی ناقص: {ok_count} موفق، {fail_count} ناموفق.\n"
            f"SKUهای خطادار: {sku_list}"
        )

    return stats


if __name__ == "__main__":
    main()
