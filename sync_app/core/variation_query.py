"""کوئری‌های مشترک واریانت — پشتیبانی از دو ساختار Poshak/ItemArticle.



قانون کد متغیر (تأیید کارفرما):

- ``PoshakId_C`` = کد متغیر → SKU ووکامرس: ``{A_Code}-V{PoshakId_C}``

- ``PoshakID`` = ویژگی اول (معمولاً سایز) برای نام نمایشی از جدول Poshak

"""



from __future__ import annotations





def build_variation_sku(a_code: str, poshak_id_c) -> str:

    """SKU واریانت در ووکامرس — همیشه بر اساس PoshakId_C."""

    if poshak_id_c is None or str(poshak_id_c).strip() == "":

        return ""

    try:

        code = int(float(poshak_id_c))

    except (TypeError, ValueError):

        return ""

    sku = str(a_code or "").strip()

    if not sku:

        return ""

    return f"{sku}-V{code}"


def variation_sku_aliases(sku: str) -> set[str]:
    """دو فرمت SKU واریانت: 0301001-V11 و V11-0301001."""
    import re

    sku = str(sku or "").strip()
    if not sku:
        return set()
    aliases = {sku.casefold()}
    m = re.match(r"^(.+)-V(\d+)$", sku, re.IGNORECASE)
    if m:
        aliases.add(f"V{m.group(2)}-{m.group(1)}".casefold())
    m2 = re.match(r"^V(\d+)-(.+)$", sku, re.IGNORECASE)
    if m2:
        aliases.add(f"{m2.group(2)}-V{m2.group(1)}".casefold())
    return aliases


def variation_skus_match(left: str, right: str) -> bool:
    """تطبیق SKU واریانت با هر دو فرمت."""
    left_set = variation_sku_aliases(left)
    right_set = variation_sku_aliases(right)
    return bool(left_set & right_set)


# ساختار پوشاک: سایز (ParentID=0) → رنگ (فرزند) → ItemArticle.PoshakID = رنگ

VARIATION_SQL_HIERARCHY = """

SELECT

    Art.A_Code,

    SizeTable.A_Name AS SizeName,

    RangTable.A_Name AS ColorName,

    ItemArticle.Few,

    ItemArticle.PoshakId_C,

    ItemArticle.PoshakID

FROM (((Poshak AS SizeTable

    LEFT JOIN Poshak AS RangTable ON SizeTable.ID = RangTable.ParentID)

    LEFT JOIN ItemArticle ON RangTable.ID = ItemArticle.PoshakID)

    INNER JOIN Article AS Art ON ItemArticle.A_Code = Art.A_Code)

WHERE SizeTable.ParentID = 0

  AND RangTable.ParentID <> 0

  {a_code_filter}

ORDER BY Art.A_Code, SizeName, ColorName

"""



# ساختار سه‌سطحی: سطح۱ (ParentID=0) -> سطح۲ -> سطح۳ (برگ) -> ItemArticle

VARIATION_SQL_HIERARCHY_3LEVEL = """

SELECT

    Art.A_Code,

    L1.A_Name AS Dim1Name,

    L2.A_Name AS Dim2Name,

    L3.A_Name AS Dim3Name,

    ia.Few,

    ia.PoshakId_C,

    ia.PoshakID

FROM ItemArticle ia

INNER JOIN Article AS Art ON ia.A_Code = Art.A_Code

INNER JOIN Poshak AS L3 ON ia.PoshakID = L3.ID

INNER JOIN Poshak AS L2 ON L3.ParentID = L2.ID AND L2.ParentID <> 0

INNER JOIN Poshak AS L1 ON L2.ParentID = L1.ID AND L1.ParentID = 0

  {a_code_filter}

ORDER BY Art.A_Code, Dim1Name, Dim2Name, Dim3Name

"""



# ساختار مستقیم DB9: PoshakID = سایز، PoshakId_C = کد متغیر

VARIATION_SQL_DIRECT = """

SELECT

    Art.A_Code,

    ISNULL(SizeTable.A_Name, '') AS SizeName,

    ISNULL(ColorTable.A_Name, '') AS ColorName,

    ia.Few,

    ia.PoshakId_C,

    ia.PoshakID

FROM ItemArticle ia

INNER JOIN Article AS Art ON ia.A_Code = Art.A_Code

LEFT JOIN Poshak AS SizeTable ON ia.PoshakID = SizeTable.ID

LEFT JOIN Poshak AS ColorTable ON CAST(ia.PoshakId_C AS INT) = ColorTable.ID

WHERE NOT EXISTS (

    SELECT 1

    FROM Poshak AS RangTable

    INNER JOIN Poshak AS SizeParent ON SizeParent.ID = RangTable.ParentID

    WHERE RangTable.ID = ia.PoshakID

      AND SizeParent.ParentID = 0

      AND RangTable.ParentID <> 0

)

  {a_code_filter}

ORDER BY Art.A_Code, SizeName, ColorName

"""



# همه ردیف‌های ItemArticle — برای نرم‌افزار و مواردی که join قبلی از دست می‌دهد

VARIATION_SQL_ITEM_ARTICLE = """

SELECT

    Art.A_Code,

    ISNULL(pSize.A_Name, ISNULL(pCode.A_Name, '')) AS SizeName,

    CASE

        WHEN pSize.ID IS NOT NULL AND pCode.ID IS NOT NULL AND pCode.ID <> pSize.ID

        THEN ISNULL(pCode.A_Name, '')

        ELSE ''

    END AS ColorName,

    ia.Few,

    ia.PoshakId_C,

    ia.PoshakID

FROM ItemArticle ia

INNER JOIN Article AS Art ON ia.A_Code = Art.A_Code

LEFT JOIN Poshak AS pSize ON ia.PoshakID = pSize.ID

LEFT JOIN Poshak AS pCode ON CAST(ia.PoshakId_C AS INT) = pCode.ID

  {a_code_filter}

ORDER BY Art.A_Code, ia.PoshakID, ia.PoshakId_C

"""



VARIATION_SQL_LIST_HIERARCHY = """

SELECT

    Art.A_Code,

    Art.A_Name,

    SizeTable.A_Name AS SizeName,

    RangTable.A_Name AS ColorName,

    ItemArticle.Few,

    ItemArticle.PoshakId_C,

    ItemArticle.PoshakID

FROM (((Poshak AS SizeTable

    LEFT JOIN Poshak AS RangTable ON SizeTable.ID = RangTable.ParentID)

    LEFT JOIN ItemArticle ON RangTable.ID = ItemArticle.PoshakID)

    INNER JOIN Article AS Art ON ItemArticle.A_Code = Art.A_Code)

WHERE SizeTable.ParentID = 0

  AND RangTable.ParentID <> 0

ORDER BY Art.A_Name, Art.A_Code, SizeName, ColorName

"""



VARIATION_SQL_LIST_HIERARCHY_3LEVEL = """

SELECT

    Art.A_Code,

    Art.A_Name,

    L1.A_Name AS Dim1Name,

    L2.A_Name AS Dim2Name,

    L3.A_Name AS Dim3Name,

    ia.Few,

    ia.PoshakId_C,

    ia.PoshakID

FROM ItemArticle ia

INNER JOIN Article AS Art ON ia.A_Code = Art.A_Code

INNER JOIN Poshak AS L3 ON ia.PoshakID = L3.ID

INNER JOIN Poshak AS L2 ON L3.ParentID = L2.ID AND L2.ParentID <> 0

INNER JOIN Poshak AS L1 ON L2.ParentID = L1.ID AND L1.ParentID = 0

ORDER BY Art.A_Name, Art.A_Code, Dim1Name, Dim2Name, Dim3Name

"""



VARIATION_SQL_LIST_DIRECT = """

SELECT

    Art.A_Code,

    Art.A_Name,

    ISNULL(SizeTable.A_Name, '') AS SizeName,

    ISNULL(ColorTable.A_Name, '') AS ColorName,

    ia.Few,

    ia.PoshakId_C,

    ia.PoshakID

FROM ItemArticle ia

INNER JOIN Article AS Art ON ia.A_Code = Art.A_Code

LEFT JOIN Poshak AS SizeTable ON ia.PoshakID = SizeTable.ID

LEFT JOIN Poshak AS ColorTable ON CAST(ia.PoshakId_C AS INT) = ColorTable.ID

WHERE NOT EXISTS (

    SELECT 1

    FROM Poshak AS RangTable

    INNER JOIN Poshak AS SizeParent ON SizeParent.ID = RangTable.ParentID

    WHERE RangTable.ID = ia.PoshakID

      AND SizeParent.ParentID = 0

      AND RangTable.ParentID <> 0

)

ORDER BY Art.A_Name, Art.A_Code, SizeName, ColorName

"""



VARIATION_SQL_LIST_ITEM_ARTICLE = """

SELECT

    Art.A_Code,

    Art.A_Name,

    ISNULL(pSize.A_Name, ISNULL(pCode.A_Name, '')) AS SizeName,

    CASE

        WHEN pSize.ID IS NOT NULL AND pCode.ID IS NOT NULL AND pCode.ID <> pSize.ID

        THEN ISNULL(pCode.A_Name, '')

        ELSE ''

    END AS ColorName,

    ia.Few,

    ia.PoshakId_C,

    ia.PoshakID

FROM ItemArticle ia

INNER JOIN Article AS Art ON ia.A_Code = Art.A_Code

LEFT JOIN Poshak AS pSize ON ia.PoshakID = pSize.ID

LEFT JOIN Poshak AS pCode ON CAST(ia.PoshakId_C AS INT) = pCode.ID

ORDER BY Art.A_Name, Art.A_Code, ia.PoshakID, ia.PoshakId_C

"""



HAS_VARIATIONS_SQL = """

SELECT COUNT(*)

FROM ItemArticle

WHERE A_Code = ?

"""



VARIATION_SQL_ITEM_ARTICLE_RAW = """

SELECT

    Art.A_Code,

    ia.Few,

    ia.PoshakId_C,

    ia.PoshakID

FROM ItemArticle ia

INNER JOIN Article AS Art ON ia.A_Code = Art.A_Code

  {a_code_filter}

ORDER BY Art.A_Code, ia.PoshakID, ia.PoshakId_C

"""



VARIATION_SQL_LIST_ITEM_ARTICLE_RAW = """

SELECT

    Art.A_Code,

    Art.A_Name,

    ia.Few,

    ia.PoshakId_C,

    ia.PoshakID

FROM ItemArticle ia

INNER JOIN Article AS Art ON ia.A_Code = Art.A_Code

ORDER BY Art.A_Name, Art.A_Code, ia.PoshakID, ia.PoshakId_C

"""





def _code_filter(a_code: str | None) -> tuple[str, tuple]:

    if a_code:

        return "AND Art.A_Code = ?", (str(a_code).strip(),)

    return "", ()





def _fetch_query_rows(cursor, sql: str, params: tuple = ()) -> list:

    cursor.execute(sql, params)

    return list(cursor.fetchall() or [])





def _rows_from_item_article_poshak(cursor, a_code: str | None = None) -> list:
    """مسیر اصلی: ItemArticle + مسیر درختی Poshak (بدون محدودیت عمق)."""
    from sync_app.core.poshak_resolver import (
        item_article_to_sync_row,
        load_poshak_cache,
        load_poshak_properties_cache,
        resolve_dimension_pairs,
    )
    from sync_app.core.variation_rules import fetch_attribute_labels_list

    dim_labels = fetch_attribute_labels_list(cursor)
    cache = load_poshak_cache(cursor)
    props = load_poshak_properties_cache(cursor)
    code_sql, params = _code_filter(a_code)
    raw_rows = _fetch_query_rows(
        cursor,
        VARIATION_SQL_ITEM_ARTICLE_RAW.format(a_code_filter=code_sql),
        params,
    )
    out: list = []
    for row in raw_rows:
        a_code_val = str(row[0] or "").strip()
        if not a_code_val:
            continue
        pairs = resolve_dimension_pairs(cache, row[3], row[2], dim_labels, props)
        if not pairs:
            continue
        out.append(
            item_article_to_sync_row(
                a_code_val,
                row[1],
                row[2],
                row[3],
                pairs,
            )
        )
    return out


def fetch_variation_rows(cursor, a_code: str | None = None) -> list:

    """ردیف‌های واریانت — درخت Poshak؛ در صورت خالی بودن fallback به کوئری‌های قدیمی."""

    from sync_app.core.variation_rules import dedupe_variation_rows

    rows = _rows_from_item_article_poshak(cursor, a_code)
    if rows:
        return dedupe_variation_rows(rows)

    code_sql, params = _code_filter(a_code)
    legacy: list = []
    legacy.extend(
        _fetch_query_rows(
            cursor, VARIATION_SQL_HIERARCHY_3LEVEL.format(a_code_filter=code_sql), params
        )
    )
    legacy.extend(
        _fetch_query_rows(
            cursor, VARIATION_SQL_HIERARCHY.format(a_code_filter=code_sql), params
        )
    )
    legacy.extend(
        _fetch_query_rows(
            cursor, VARIATION_SQL_DIRECT.format(a_code_filter=code_sql), params
        )
    )
    legacy.extend(
        _fetch_query_rows(
            cursor, VARIATION_SQL_ITEM_ARTICLE.format(a_code_filter=code_sql), params
        )
    )
    return dedupe_variation_rows(legacy)





def _list_rows_from_item_article_poshak(cursor) -> list:
    from sync_app.core.poshak_resolver import (
        item_article_to_sync_row,
        load_poshak_cache,
        load_poshak_properties_cache,
        resolve_dimension_pairs,
    )
    from sync_app.core.variation_rules import fetch_attribute_labels_list

    dim_labels = fetch_attribute_labels_list(cursor)
    cache = load_poshak_cache(cursor)
    props = load_poshak_properties_cache(cursor)
    raw_rows = _fetch_query_rows(cursor, VARIATION_SQL_LIST_ITEM_ARTICLE_RAW)
    out: list = []
    for row in raw_rows:
        a_code_val = str(row[0] or "").strip()
        if not a_code_val:
            continue
        pairs = resolve_dimension_pairs(cache, row[4], row[3], dim_labels, props)
        if not pairs:
            continue
        item = item_article_to_sync_row(a_code_val, row[2], row[3], row[4], pairs)
        item["name"] = str(row[1] or "").strip()
        out.append(item)
    return out


def fetch_variation_list_rows(cursor) -> list:

    """لیست واریانت‌ها برای تب متغیرها — dedupe."""

    from sync_app.core.variation_rules import dedupe_variation_rows

    rows = _list_rows_from_item_article_poshak(cursor)
    if rows:
        return dedupe_variation_rows(rows)

    legacy: list = []
    legacy.extend(_fetch_query_rows(cursor, VARIATION_SQL_LIST_HIERARCHY_3LEVEL))
    legacy.extend(_fetch_query_rows(cursor, VARIATION_SQL_LIST_HIERARCHY))
    legacy.extend(_fetch_query_rows(cursor, VARIATION_SQL_LIST_DIRECT))
    legacy.extend(_fetch_query_rows(cursor, VARIATION_SQL_LIST_ITEM_ARTICLE))
    return dedupe_variation_rows(legacy)





def has_item_variations(cursor, a_code: str) -> bool:

    cursor.execute(HAS_VARIATIONS_SQL, (str(a_code).strip(),))

    count = int((cursor.fetchone() or [0])[0] or 0)

    return count > 0


def load_variable_a_codes(cursor) -> set[str]:
    """یک کوئری به‌جای COUNT برای هر SKU."""
    cursor.execute("SELECT DISTINCT A_Code FROM ItemArticle")
    return {
        str(row[0]).strip()
        for row in (cursor.fetchall() or [])
        if row and str(row[0] or "").strip()
    }


