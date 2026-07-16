"""مسیر درختی Poshak — از برگ ItemArticle تا ریشه (parent-child).

نام هر سطح (Attribute) از روی PId گره Poshak و جدول PoshakProperties
تعیین می‌شود، نه با شماره ترتیب سطح؛ تا برگ‌هایی که مسیرشان از ریشه شروع
نمی‌شود هم عنوان درست بگیرند (رفع باگ «سطح ۲ با عنوان سطح ۱»).
"""

from __future__ import annotations

from sync_app.core.scripts.Poshakproperties import normalize_text

# بعضی دیتابیس‌ها ستون PId ندارند؛ نسخه بدون PId به‌عنوان fallback
POSHAK_LOAD_SQL = """
SELECT ID, A_Name, ParentID, PId
FROM Poshak
"""

POSHAK_LOAD_SQL_NO_PID = """
SELECT ID, A_Name, ParentID
FROM Poshak
"""

POSHAK_PROPERTIES_SQL = """
SELECT ID, ParentID, Name
FROM PoshakProperties
"""

_conn_cache: dict[int, dict] = {}
_props_cache: dict[int, dict] = {}


def _to_int(value) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def load_poshak_cache(cursor) -> dict[int, dict]:
    """کش ID -> {id, name, parent, pid} برای یک اتصال SQL."""
    conn_id = id(cursor.connection)
    cached = _conn_cache.get(conn_id)
    if cached is not None:
        return cached

    has_pid = True
    try:
        cursor.execute(POSHAK_LOAD_SQL)
    except Exception:
        # دیتابیس قدیمی بدون ستون PId
        cursor.execute(POSHAK_LOAD_SQL_NO_PID)
        has_pid = False
    rows = cursor.fetchall() or []
    out: dict[int, dict] = {}
    for row in rows:
        node_id = _to_int(row[0])
        if node_id is None:
            continue
        parent_id = _to_int(row[2]) or 0
        pid = _to_int(row[3]) if has_pid and len(row) > 3 else None
        out[node_id] = {
            "id": node_id,
            "name": normalize_text(row[1]),
            "parent": parent_id,
            "pid": pid,
        }
    _conn_cache[conn_id] = out
    return out


def load_poshak_properties_cache(cursor) -> dict:
    """نگاشت PId → نام Attribute از PoshakProperties.

    - ریشه (ParentID=0): نام خودش = نام Attribute
    - فرزند: نام Attribute = نام ریشه والدش
    خروجی: {pid_to_name, root_ids, child_to_parent}
    """
    conn_id = id(cursor.connection)
    cached = _props_cache.get(conn_id)
    if cached is not None:
        return cached

    pid_to_name: dict[int, str] = {}
    root_ids: set[int] = set()
    child_to_parent: dict[int, int] = {}
    try:
        cursor.execute(POSHAK_PROPERTIES_SQL)
        rows = cursor.fetchall() or []
    except Exception:
        rows = []
    for row in rows:
        node_id = _to_int(row[0])
        if node_id is None:
            continue
        parent_id = _to_int(row[1]) or 0
        pid_to_name[node_id] = normalize_text(row[2])
        if parent_id == 0:
            root_ids.add(node_id)
        else:
            child_to_parent[node_id] = parent_id

    out = {
        "pid_to_name": pid_to_name,
        "root_ids": root_ids,
        "child_to_parent": child_to_parent,
    }
    _props_cache[conn_id] = out
    return out


def attr_label_from_pid(props: dict, pid) -> str:
    """نام Attribute برای یک PId — با منطق ریشه/فرزند PoshakProperties."""
    if not props:
        return ""
    key = _to_int(pid)
    if key is None:
        return ""
    pid_to_name = props.get("pid_to_name") or {}
    root_ids = props.get("root_ids") or set()
    child_to_parent = props.get("child_to_parent") or {}
    if key in root_ids:
        return normalize_text(pid_to_name.get(key))
    if key in child_to_parent:
        root = child_to_parent[key]
        return normalize_text(pid_to_name.get(root))
    return ""


def clear_poshak_cache(conn=None) -> None:
    """پاک کردن کش (بعد از sync طولانی یا تست)."""
    if conn is None:
        _conn_cache.clear()
        _props_cache.clear()
        return
    _conn_cache.pop(id(conn), None)
    _props_cache.pop(id(conn), None)


def poshak_path_chain(cache: dict[int, dict], leaf_id) -> list[dict]:
    """گره‌های کامل از ریشه تا برگ — هر گره {id, name, parent, pid}."""
    start = _to_int(leaf_id)
    if start is None or not cache:
        return []

    chain_ids: list[int] = []
    seen: set[int] = set()
    cur = start
    while cur and cur not in seen:
        seen.add(cur)
        node = cache.get(cur)
        if not node:
            break
        chain_ids.append(cur)
        parent = int(node.get("parent") or 0)
        cur = parent if parent else 0
        if not cur:
            break

    chain_ids.reverse()
    return [cache[node_id] for node_id in chain_ids if node_id in cache]


def poshak_path_names(cache: dict[int, dict], leaf_id) -> list[str]:
    """نام گره‌ها از ریشه تا برگ — مثلاً [پیشرفته, نسیه, مدل ۱]."""
    names: list[str] = []
    for node in poshak_path_chain(cache, leaf_id):
        name = normalize_text(node.get("name"))
        if name:
            names.append(name)
    return names


def resolve_dimension_pairs(
    cache: dict[int, dict],
    poshak_id,
    poshak_id_c,
    dim_labels: list[str],
    props: dict | None = None,
) -> list[tuple[str, str]]:
    """
    جفت (برچسب سطح, مقدار) از ItemArticle.
    مسیر از PoshakID به بالا؛ در حالت پوشاک ۲ بعدی PoshakId_C مکمل می‌شود.

    اگر props (PoshakProperties) داده شود، نام هر سطح از روی PId همان گره
    تعیین می‌شود؛ وگرنه fallback به ترتیب سطح و dim_labels.
    """
    labels = [normalize_text(x) for x in (dim_labels or []) if normalize_text(x)]
    if not labels:
        labels = ["سایز", "رنگ"]

    chain = poshak_path_chain(cache, poshak_id)

    # حالت پوشاک ۲ بعدی: PoshakId_C گره مکمل مسیر است
    extra_id = _to_int(poshak_id_c)
    if extra_id is not None and extra_id in cache:
        leaf_id = _to_int(poshak_id)
        extra_name = normalize_text(cache[extra_id].get("name"))
        existing_names = [normalize_text(n.get("name")) for n in chain]
        if extra_name and extra_id != leaf_id and extra_name not in existing_names:
            if len(chain) <= 1 or extra_name != (existing_names[-1] if existing_names else ""):
                chain.append(cache[extra_id])

    if not chain:
        code = _to_int(poshak_id_c)
        if code is not None:
            return [(labels[0] if labels else "سطح ۱", f"گزینه {code}")]
        return []

    pairs: list[tuple[str, str]] = []
    for idx, node in enumerate(chain):
        val = normalize_text(node.get("name"))
        if not val:
            continue
        label = attr_label_from_pid(props, node.get("pid")) if props else ""
        if not label:
            label = labels[idx] if idx < len(labels) else f"سطح {idx + 1}"
        pairs.append((label, val))
    return pairs


def item_article_to_sync_row(
    a_code: str,
    few,
    poshak_id_c,
    poshak_id,
    dim_pairs: list[tuple[str, str]],
) -> dict:
    """ردیف استاندارد برای parse_row_to_variation."""
    return {
        "a_code": str(a_code or "").strip(),
        "few": few,
        "poshak_id_c": poshak_id_c,
        "poshak_id": poshak_id,
        "dim_pairs": list(dim_pairs or []),
    }
