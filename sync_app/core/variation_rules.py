"""قواعد مرکزی متغیر — تشخیص خودکار همه سناریوها (پوشاک / نرم‌افزار / DB9).

خلاصه:
- ItemArticle دارد → محصول variable
- SKU واریانت = {A_Code}-V{PoshakId_C}
- attribute = فقط بعدهای غیرخالی (۱ تا ۳)
- bind موفق = bound_count >= expected_bind_count (نه همیشه ۲)
"""

from __future__ import annotations

from sync_app.core.variation_query import build_variation_sku, has_item_variations

PROPERTY_NAMES_SQL = """
SELECT Id, Name FROM PoshakProperties WHERE ParentID = 0 ORDER BY Id
"""

_ANY_OPTION_MARKERS = (
    "any",
    "هر سایز",
    "هر رنگ",
    "any size",
    "any color",
)


def normalize_dim_value(value) -> str:
    from sync_app.core.scripts.Poshakproperties import normalize_text

    return normalize_text(value)


def _as_cursor(conn_or_cursor):
    """ورودی می‌تواند connection یا cursor باشد — cursor و فلگ مالکیت برمی‌گرداند."""
    if hasattr(conn_or_cursor, "cursor"):
        return conn_or_cursor.cursor(), True
    return conn_or_cursor, False


def fetch_attribute_labels_list(conn_or_cursor) -> list[str]:
    """همه برچسب‌های سطح از PoshakProperties — بدون محدودیت تعداد."""
    cursor, own = _as_cursor(conn_or_cursor)
    cursor.execute(PROPERTY_NAMES_SQL)
    rows = cursor.fetchall()
    if own:
        cursor.close()
    labels = [
        normalize_dim_value(r[1])
        for r in rows
        if r[0] is not None and normalize_dim_value(r[1])
    ]
    return labels or ["سایز", "رنگ"]


def fetch_attribute_labels(conn) -> tuple[str, str, str]:
    """سازگاری قدیمی — سه برچسب اول."""
    labels = fetch_attribute_labels_list(conn)
    dim1 = labels[0] if len(labels) > 0 else "سایز"
    dim2 = labels[1] if len(labels) > 1 else "رنگ"
    dim3 = labels[2] if len(labels) > 2 else ""
    return dim1, dim2, dim3


def fetch_variant_code_label(conn) -> str:
    """برچسب فارسی فیلد PoshakId_C (poshak_C) — از PoshakProperties یا «کد پوشاک»."""
    try:
        cursor = conn.cursor()
        cursor.execute(PROPERTY_NAMES_SQL)
        rows = cursor.fetchall()
        cursor.close()
        for row in rows:
            name = normalize_dim_value(row[1] if len(row) > 1 else "")
            if "کد" in name:
                return name
        _dim1, dim2, _dim3 = fetch_attribute_labels(conn)
        if dim2 and dim2 not in ("رنگ", "سایز"):
            return dim2
    except Exception:
        pass
    return "کد پوشاک"


def _is_three_level_row(row, *, list_mode: bool = False) -> bool:
    min_len = 8 if list_mode else 7
    return len(row or []) >= min_len


def _sync_row_indices(row=None, *, list_mode: bool = False) -> dict[str, int]:
    """نگاشت نام ستون — همیشه alias سایز/رنگ برای سازگاری با کد قدیمی."""
    if _is_three_level_row(row, list_mode=list_mode):
        base = 2 if list_mode else 1
        return {
            "name": 1,
            "dim1": base,
            "size": base,
            "dim2": base + 1,
            "color": base + 1,
            "dim3": base + 2,
            "stock": base + 3,
            "poshak_id_c": base + 4,
            "poshak_id": base + 5,
        }
    if list_mode:
        return {
            "name": 1,
            "size": 2,
            "dim1": 2,
            "color": 3,
            "dim2": 3,
            "stock": 4,
            "poshak_id_c": 5,
            "poshak_id": 6,
        }
    return {
        "size": 1,
        "dim1": 1,
        "color": 2,
        "dim2": 2,
        "stock": 3,
        "poshak_id_c": 4,
        "poshak_id": 5,
    }


def _row_col(row, idx: dict[str, int], key: str, default=""):
    """خواندن امن یک ستون — بدون KeyError روی نام فیلد."""
    col = idx.get(key)
    if col is None or len(row or []) <= col:
        return default
    return row[col]


def _row_is_dict(row) -> bool:
    return isinstance(row, dict)


def resolve_row_dimensions(row, *, list_mode: bool = False) -> tuple[str, str, str, object, object]:
    """بعدهای نمایشی (۱ تا ۳) + PoshakId_C و PoshakID."""
    if _row_is_dict(row):
        pairs = row.get("dim_pairs") or []
        dim1_val = pairs[0][1] if len(pairs) > 0 else ""
        dim2_val = pairs[1][1] if len(pairs) > 1 else ""
        dim3_val = pairs[2][1] if len(pairs) > 2 else ""
        return (
            normalize_dim_value(dim1_val),
            normalize_dim_value(dim2_val),
            normalize_dim_value(dim3_val),
            row.get("poshak_id_c"),
            row.get("poshak_id"),
        )

    idx = _sync_row_indices(row, list_mode=list_mode)
    dim1_val = normalize_dim_value(_row_col(row, idx, "dim1") or _row_col(row, idx, "size"))
    dim2_val = normalize_dim_value(_row_col(row, idx, "dim2") or _row_col(row, idx, "color"))
    dim3_val = normalize_dim_value(_row_col(row, idx, "dim3")) if "dim3" in idx else ""
    poshak_id_c = _row_col(row, idx, "poshak_id_c", default=None)
    poshak_id = _row_col(row, idx, "poshak_id", default=None)

    if not dim1_val and dim2_val:
        dim1_val, dim2_val = dim2_val, ""
    if not dim1_val and not dim2_val and not dim3_val and poshak_id_c is not None:
        try:
            code = int(float(poshak_id_c))
            dim1_val = f"گزینه {code}"
        except (TypeError, ValueError):
            dim1_val = str(poshak_id_c).strip()

    return dim1_val, dim2_val, dim3_val, poshak_id_c, poshak_id


def product_is_variable(cursor, a_code: str) -> bool:
    """هر ردیف ItemArticle → variable."""
    return has_item_variations(cursor, str(a_code or "").strip())


def _row_key(row) -> tuple[str, str]:
    if _row_is_dict(row):
        a_code = str(row.get("a_code") or "").strip()
        poshak_id_c = row.get("poshak_id_c")
    else:
        a_code = str(row[0] or "").strip()
        idx = _sync_row_indices(row)
        poshak_id_c = row[idx["poshak_id_c"]] if len(row) > idx["poshak_id_c"] else None
    try:
        code = int(float(poshak_id_c)) if poshak_id_c is not None else -1
    except (TypeError, ValueError):
        code = -1
    return a_code, str(code)


def _row_quality(row) -> int:
    """برای dedupe: ردیفی که بعد بیشتری پر دارد اولویت دارد."""
    if _row_is_dict(row):
        return len(row.get("dim_pairs") or [])
    list_mode = len(row or []) >= 8
    dim1, dim2, dim3, _, _ = resolve_row_dimensions(row, list_mode=list_mode)
    return (1 if dim1 else 0) + (1 if dim2 else 0) + (1 if dim3 else 0)


def dedupe_variation_rows(rows: list) -> list:
    """ادغام hierarchy + direct — یک SKU (A_Code, PoshakId_C) فقط یک‌بار."""
    best: dict[tuple[str, str], tuple] = {}
    order: list[tuple[str, str]] = []
    for row in rows or []:
        key = _row_key(row)
        if key[1] == "-1":
            continue
        if key not in best:
            order.append(key)
            best[key] = row
            continue
        if _row_quality(row) > _row_quality(best[key]):
            best[key] = row
    return [best[k] for k in order if k in best]


def build_variation_attributes(
    dim1_val: str,
    dim2_val: str,
    dim1_label: str,
    dim2_label: str,
    *,
    dim3_val: str = "",
    dim3_label: str = "",
    dim_pairs: list[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    """فقط بعدهای غیرخالی — تعداد سطح نامحدود."""
    if dim_pairs:
        return [
            {"name": str(label).strip(), "option": str(val).strip()}
            for label, val in dim_pairs
            if str(label).strip() and str(val).strip()
        ]
    attrs: list[dict[str, str]] = []
    if dim1_val and dim1_label:
        attrs.append({"name": dim1_label, "option": dim1_val})
    if dim2_val and dim2_label:
        attrs.append({"name": dim2_label, "option": dim2_val})
    if dim3_val and dim3_label:
        attrs.append({"name": dim3_label, "option": dim3_val})
    return attrs


def is_valid_bound_option(option) -> bool:
    opt = str(option or "").strip()
    if not opt:
        return False
    low = opt.lower()
    if low in _ANY_OPTION_MARKERS:
        return False
    if opt.startswith("هر "):
        return False
    return True


def count_non_empty_attributes(var: dict) -> int:
    """تعداد attributeهای غیرخالی که باید bind شوند."""
    count = 0
    for attr in var.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        name = str(attr.get("name") or "").strip()
        option = str(attr.get("option") or "").strip()
        if name and option and is_valid_bound_option(option):
            count += 1
    return count


def variation_bind_satisfied(wc_variation: dict, source_var: dict | None = None) -> bool:
    """bind کافی است اگر bound >= expected (۱ یا ۲)."""
    expected = count_non_empty_attributes(source_var or {})
    expected = max(1, expected)

    attrs = wc_variation.get("attributes") or []
    bound_opts = [
        str(a.get("option") or "").strip()
        for a in attrs
        if isinstance(a, dict) and is_valid_bound_option(a.get("option"))
    ]
    meta_hits = 0
    for item in wc_variation.get("meta_data") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        val = str(item.get("value") or "").strip()
        if key.startswith("attribute_pa_") and val:
            meta_hits += 1

    bound_count = max(len(bound_opts), meta_hits)
    return bound_count >= expected


def parse_row_to_variation(
    row,
    *,
    a_code: str | None = None,
    base_price: str = "0",
    dim1_label: str = "سایز",
    dim2_label: str = "رنگ",
    dim3_label: str = "",
    variant_price: str | None = None,
    variant_sale_price: str | None = None,
) -> dict | None:
    """
    تبدیل یک ردیف SQL به payload واریانت.
    None = ردیف نامعتبر (بدون PoshakId_C یا بدون attribute).
    """
    if _row_is_dict(row):
        code = str(a_code or row.get("a_code") or "").strip()
        dim_pairs = list(row.get("dim_pairs") or [])
        poshak_id_c = row.get("poshak_id_c")
        poshak_id = row.get("poshak_id")
        try:
            stock = max(0, int(row.get("few") or 0))
        except (TypeError, ValueError):
            stock = 0
    else:
        code = str(a_code or row[0] or "").strip()
        dim_pairs = None
        dim1_val, dim2_val, dim3_val, poshak_id_c, poshak_id = resolve_row_dimensions(
            row, list_mode=False
        )
        idx = _sync_row_indices(row)
        try:
            stock = max(0, int(row[idx["stock"]] or 0))
        except (TypeError, ValueError):
            stock = 0

    if not code:
        return None

    variant_sku = build_variation_sku(code, poshak_id_c)
    if not variant_sku:
        return None

    if dim_pairs is not None:
        attrs = build_variation_attributes(
            "", "", "", "", dim_pairs=dim_pairs
        )
        dim1_val = dim_pairs[0][1] if len(dim_pairs) > 0 else ""
        dim2_val = dim_pairs[1][1] if len(dim_pairs) > 1 else ""
        dim3_val = dim_pairs[2][1] if len(dim_pairs) > 2 else ""
    else:
        attrs = build_variation_attributes(
            dim1_val,
            dim2_val,
            dim1_label,
            dim2_label,
            dim3_val=dim3_val,
            dim3_label=dim3_label,
        )
    if not attrs:
        return None

    price_str = str(variant_price if variant_price is not None else base_price or "0")

    if dim_pairs:
        full_path_str = " ← ".join(
            str(v).strip() for _, v in dim_pairs if str(v).strip()
        )
    else:
        full_path_str = " ← ".join(
            str(v).strip() for v in (dim1_val, dim2_val, dim3_val) if str(v).strip()
        )

    dejavu_meta: list[dict[str, str]] = []
    if poshak_id is not None and str(poshak_id).strip():
        dejavu_meta.append({"key": "_dejavu_poshak_id", "value": str(poshak_id).strip()})
    if full_path_str:
        dejavu_meta.append({"key": "_dejavu_poshak_path", "value": full_path_str})
    dejavu_meta.append({"key": "_dejavu_few", "value": str(stock)})

    payload = {
        "regular_price": price_str,
        "manage_stock": True,
        "stock_quantity": stock,
        "attributes": attrs,
        "sku": variant_sku,
        "dejavu_meta": dejavu_meta,
        "_poshak_id_c": poshak_id_c,
        "_poshak_id": poshak_id,
        "_dim1_val": dim1_val,
        "_dim2_val": dim2_val,
        "_dim3_val": dim3_val,
    }
    sale_str = str(variant_sale_price or "").strip()
    if sale_str and sale_str != "0":
        payload["sale_price"] = sale_str
    return payload


def build_attr_map_from_variations(
    variations: list[dict],
    dim1_label: str = "",
    dim2_label: str = "",
    dim3_label: str = "",
) -> dict[str, list[str]]:
    """attributeهای والد — از خود واریانت‌ها (هر تعداد سطح)."""
    dim_opts: dict[str, set[str]] = {}
    for label in (dim1_label, dim2_label, dim3_label):
        if label:
            dim_opts.setdefault(label, set())
    for var in variations or []:
        for attr in var.get("attributes") or []:
            if not isinstance(attr, dict):
                continue
            name = str(attr.get("name") or "").strip()
            option = str(attr.get("option") or "").strip()
            if not name or not option:
                continue
            dim_opts.setdefault(name, set()).add(option)

    attr_map: dict[str, list[str]] = {}
    for label, opts in dim_opts.items():
        if label and opts:
            attr_map[label] = sorted(opts)
    return attr_map


def rows_to_sync_payloads(
    rows: list,
    a_code: str,
    raw_base_price,
    dim1_label: str,
    dim2_label: str,
    dim3_label: str = "",
    *,
    price_by_poshak_id: dict[int, float] | None = None,
    sale_price_by_poshak_id: dict[int, float] | None = None,
    apply_price=None,
) -> tuple[list[dict], dict[str, list[str]]]:
    """ردیف‌های dedupe‌شده → لیست واریانت + attr_map والد."""
    from sync_app.core.article_price import resolve_variant_price, woo_sale_price_str

    deduped = dedupe_variation_rows(rows)
    variations: list[dict] = []
    seen_sku: set[str] = set()

    try:
        base_val = float(raw_base_price or 0)
    except (TypeError, ValueError):
        base_val = 0.0

    woo_base_default = apply_price(base_val) if apply_price and base_val > 0 else "0"

    for row in deduped:
        _, _, _, poshak_id_c, poshak_id = resolve_row_dimensions(row, list_mode=False)
        raw_variant_price = resolve_variant_price(
            price_by_poshak_id=price_by_poshak_id,
            poshak_id=poshak_id,
            poshak_id_c=poshak_id_c,
            base_price=base_val,
        )
        raw_variant_sale = resolve_variant_price(
            price_by_poshak_id=sale_price_by_poshak_id,
            poshak_id=poshak_id,
            poshak_id_c=poshak_id_c,
            base_price=0.0,
        )
        if apply_price:
            price_str = apply_price(raw_variant_price)
            sale_str = ""
            if raw_variant_sale > 0 and raw_variant_price > 0 and raw_variant_sale < raw_variant_price:
                sale_str = apply_price(raw_variant_sale)
                try:
                    if float(sale_str or 0) <= 0 or float(sale_str) >= float(price_str or 0):
                        sale_str = ""
                except (TypeError, ValueError):
                    sale_str = ""
        else:
            price_str = (
                str(int(raw_variant_price))
                if raw_variant_price > 0
                else woo_base_default
            )
            sale_str = woo_sale_price_str(raw_variant_price, raw_variant_sale, 1.0)

        var = parse_row_to_variation(
            row,
            a_code=a_code,
            base_price=woo_base_default,
            dim1_label=dim1_label,
            dim2_label=dim2_label,
            dim3_label=dim3_label,
            variant_price=price_str,
            variant_sale_price=sale_str,
        )
        if not var:
            continue
        sku = str(var.get("sku") or "").strip()
        if sku in seen_sku:
            continue
        seen_sku.add(sku)
        clean = {k: v for k, v in var.items() if not str(k).startswith("_")}
        variations.append(clean)

    attr_map = build_attr_map_from_variations(variations, dim1_label, dim2_label, dim3_label)
    return variations, attr_map


def parse_list_row_for_ui(
    row,
    *,
    variant_code_label: str = "کد متغیر",
    price_by_poshak_id: dict[int, float] | None = None,
    sale_price_by_poshak_id: dict[int, float] | None = None,
    base_price: float = 0.0,
    price_divisor: float = 1.0,
) -> dict | None:
    """ردیف لیست تب متغیرها — برای نمایش."""
    if _row_is_dict(row):
        sku = str(row.get("a_code") or "").strip()
        name = str(row.get("name") or sku).strip()
        dim_pairs = row.get("dim_pairs") or []
        dim1_val = dim_pairs[0][1] if len(dim_pairs) > 0 else ""
        dim2_val = dim_pairs[1][1] if len(dim_pairs) > 1 else ""
        dim3_val = dim_pairs[2][1] if len(dim_pairs) > 2 else ""
        poshak_id_c = row.get("poshak_id_c")
        poshak_id = row.get("poshak_id")
        try:
            stock = int(row.get("few") or 0)
        except (TypeError, ValueError):
            stock = 0
        full_path = " ← ".join(
            str(v).strip() for _, v in dim_pairs if str(v).strip()
        )
    else:
        sku = str(row[0] or "").strip()
        if not sku:
            return None
        dim1_val, dim2_val, dim3_val, poshak_id_c, poshak_id = resolve_row_dimensions(
            row, list_mode=True
        )
        idx = _sync_row_indices(row, list_mode=True)
        name = str(row[idx["name"]] or "").strip()
        try:
            stock = int(row[idx["stock"]] or 0)
        except (TypeError, ValueError):
            stock = 0
        full_path = " ← ".join(v for v in (dim1_val, dim2_val, dim3_val) if v)

    if not sku:
        return None
    variant_sku = build_variation_sku(sku, poshak_id_c)
    if not variant_sku:
        return None

    from sync_app.core.article_price import resolve_variant_price

    raw_price = resolve_variant_price(
        price_by_poshak_id=price_by_poshak_id,
        poshak_id=poshak_id,
        poshak_id_c=poshak_id_c,
        base_price=base_price,
    )
    display_price = raw_price / (price_divisor or 1.0) if raw_price > 0 else 0.0

    raw_sale = resolve_variant_price(
        price_by_poshak_id=sale_price_by_poshak_id or {},
        poshak_id=poshak_id,
        poshak_id_c=poshak_id_c,
        base_price=0.0,
    )
    display_sale = raw_sale / (price_divisor or 1.0) if raw_sale > 0 and raw_sale < raw_price else 0.0

    return {
        "sku": sku,
        "variant_sku": variant_sku,
        "variant_code": str(poshak_id_c or "").strip(),
        "variant_code_label": variant_code_label,
        "name": name,
        "full_path": full_path or name,
        "size": dim1_val,
        "color": dim2_val,
        "dim3": dim3_val,
        "stock": stock,
        "price": display_price,
        "sale_price": display_sale,
        "poshak_id": poshak_id,
    }
