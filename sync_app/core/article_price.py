"""قیمت از ستون‌های sel_price و جدول ArticlePrice."""

# بعضی دیتابیس‌ها SelID دارند، بعضی ScID
_PRICE_LIST_COL: str | None = None


def _price_list_col(cursor) -> str:
    """ستون لیست قیمت در ArticlePrice — SelID یا ScID."""
    global _PRICE_LIST_COL
    if _PRICE_LIST_COL:
        return _PRICE_LIST_COL
    for col in ("SelID", "ScID"):
        try:
            cursor.execute(f"SELECT TOP 1 {col} FROM ArticlePrice")
            cursor.fetchone()
            _PRICE_LIST_COL = col
            return col
        except Exception:
            continue
    _PRICE_LIST_COL = "SelID"
    return _PRICE_LIST_COL


def price_list_id_from_config(config, *, key: str = "PRICE_LIST_INDEX") -> int:
    """شماره لیست قیمت (۱-based) از تنظیمات."""
    try:
        return int((config or {}).get(key, 0) or 0) + 1
    except (TypeError, ValueError):
        return 1


def apply_price_markup(price: float, config: dict, *, is_sale: bool = False) -> float:
    """
    درصد افزایش قیمت رو (اگه تنظیم شده باشه) روی قیمت اعمال می‌کنه —
    برای قیمت عادی از PRICE_MARKUP_PERCENT، برای قیمت ویژه از
    SALE_PRICE_MARKUP_PERCENT. مقدار صفر یا خالی یعنی بدون تغییر.
    """
    try:
        price = float(price or 0)
    except (TypeError, ValueError):
        return 0.0
    if price <= 0:
        return price
    key = "SALE_PRICE_MARKUP_PERCENT" if is_sale else "PRICE_MARKUP_PERCENT"
    try:
        percent = float((config or {}).get(key, 0) or 0)
    except (TypeError, ValueError):
        percent = 0.0
    if not percent:
        return price
    return price * (1 + percent / 100.0)


def resolve_article_price(row, price_col, *, price_start_index=2):
    """
    row: tuple با Sel_Price..5 از index price_start_index
    price_col: نام ستون ترجیحی از تنظیمات (مثلاً Sel_Price2)
    """
    cols = ["Sel_Price", "Sel_Price2", "Sel_Price3", "Sel_Price4", "Sel_Price5"]
    ordered = [price_col] + [c for c in cols if c != price_col]
    col_index = {name: price_start_index + i for i, name in enumerate(cols)}
    for name in ordered:
        idx = col_index.get(name)
        if idx is None or idx >= len(row):
            continue
        val = row[idx]
        if val is not None and float(val or 0) > 0:
            return float(val)
    return 0.0


def article_price_sc_id(config) -> int:
    """شناسه لیست قیمت در ArticlePrice — مطابق PRICE_LIST_INDEX."""
    return price_list_id_from_config(config, key="PRICE_LIST_INDEX")


def price_list_column_for_index(index: int) -> str:
    """نام ستون Article مطابق شماره لیست (۰-based index)."""
    n = int(index or 0) + 1
    return "Sel_Price" if n <= 1 else f"Sel_Price{n}"


def article_price_sale_list_id(config) -> int | None:
    """لیست قیمت ویژه — اگر در تنظیمات فعال باشد."""
    if not (config or {}).get("SALE_PRICE_LIST_ENABLED"):
        return None
    return price_list_id_from_config(config, key="SALE_PRICE_LIST_INDEX")


def sale_price_list_column(config) -> str | None:
    if not (config or {}).get("SALE_PRICE_LIST_ENABLED"):
        return None
    return price_list_column_for_index((config or {}).get("SALE_PRICE_LIST_INDEX", 1))


def resolve_sale_article_price(row, config, *, price_start_index=2) -> float:
    """قیمت ویژه محصول ساده از ستون‌های Article."""
    col = sale_price_list_column(config)
    if not col:
        return 0.0
    return resolve_article_price(row, col, price_start_index=price_start_index)


def woo_sale_price_str(regular_raw: float, sale_raw: float, price_divisor: float) -> str:
    """قیمت ویژه Woo — فقط اگر کمتر از عادی و مثبت باشد."""
    try:
        reg = float(regular_raw or 0)
        sale = float(sale_raw or 0)
    except (TypeError, ValueError):
        return ""
    if sale <= 0 or reg <= 0 or sale >= reg:
        return ""
    return str(int(sale / max(float(price_divisor or 1), 1.0)))


def _to_int(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _rows_to_price_map(rows) -> dict[int, float]:
    out: dict[int, float] = {}
    for row in rows or []:
        pid = _to_int(row[0] if len(row) > 0 else None)
        if pid is None:
            continue
        try:
            price = float(row[1] or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price > 0:
            out[pid] = price
    return out


def load_article_variant_prices(cursor, a_code: str, sc_id: int = 1) -> dict[int, float]:
    """نگاشت PoshakID → قیمت از ArticlePrice برای یک کالا (Min_Price اگر مثبت باشد، وگرنه Sel_Price)."""
    code = str(a_code or "").strip()
    if not code:
        return {}
    list_col = _price_list_col(cursor)
    try:
        cursor.execute(
            f"SELECT PoshakID, ISNULL(NULLIF(Min_Price, 0), Sel_Price) AS Price "
            f"FROM ArticlePrice WHERE A_Code = ? AND {list_col} = ?",
            (code, int(sc_id)),
        )
        result = _rows_to_price_map(cursor.fetchall())
        if not result:
            try:
                from sync_app.core.sync_utils import log as _log
                _log.warning(
                    f"⚠️ قیمت متغیر [{code}]: ArticlePrice برای SelID={sc_id} خالی است "
                    f"(ستون={list_col}) — قیمت پایه کالا استفاده می‌شود"
                )
            except Exception:
                pass
        return result
    except Exception as exc:
        try:
            from sync_app.core.sync_utils import log as _log
            _log.error(f"❌ خطا در بارگذاری قیمت متغیر [{code}] (SelID={sc_id}): {exc}")
        except Exception:
            pass
        return {}


def load_bulk_article_variant_prices(
    cursor,
    a_codes: list[str],
    sc_id: int = 1,
    *,
    chunk_size: int = 150,
) -> dict[str, dict[int, float]]:
    """یک‌جا قیمت واریانت‌ها — جلوگیری از N+1 کوئری در تب متغیرها."""
    codes = sorted({str(c or "").strip() for c in a_codes if str(c or "").strip()})
    if not codes:
        return {}
    out: dict[str, dict[int, float]] = {}
    sid = int(sc_id)
    for start in range(0, len(codes), chunk_size):
        chunk = codes[start : start + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        list_col = _price_list_col(cursor)
        try:
            cursor.execute(
                f"SELECT A_Code, PoshakID, ISNULL(NULLIF(Min_Price, 0), Sel_Price) AS Price "
                f"FROM ArticlePrice "
                f"WHERE {list_col} = ? AND A_Code IN ({placeholders})",
                (sid, *chunk),
            )
            for row in cursor.fetchall() or []:
                code = str(row[0] or "").strip()
                if not code:
                    continue
                pid = _to_int(row[1] if len(row) > 1 else None)
                if pid is None:
                    continue
                try:
                    price = float(row[2] or 0)
                except (TypeError, ValueError):
                    price = 0.0
                if price <= 0:
                    continue
                out.setdefault(code, {})[pid] = price
        except Exception:
            for code in chunk:
                out.setdefault(code, {}).update(load_article_variant_prices(cursor, code, sc_id=sid))
    return out


def resolve_variant_price(
    *,
    price_by_poshak_id: dict[int, float] | None,
    poshak_id,
    poshak_id_c,
    base_price: float = 0.0,
) -> float:
    """قیمت واریانت — اول ArticlePrice، بعد قیمت پایه Article."""
    lookup = price_by_poshak_id or {}
    for key in (_to_int(poshak_id), _to_int(poshak_id_c)):
        if key is not None and key in lookup:
            return float(lookup[key])
    return float(base_price or 0)
