import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher

import pyodbc
import requests
from woocommerce import API

try:
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_utils import log
    from sync_app.core.wc_api_helper import wc_api_config_for_sdk
    from sync_app.core.wc_sync_helper import (
        apply_network_overrides,
        build_wcapi,
        wc_call,
        WC_SYNC_RETRIES,
        format_wc_network_error,
        warm_wc_connection,
    )
    from sync_app.core.field_sync_config import is_field_enabled
except ImportError:
    class MockLog:
        def info(self, msg):
            print(f"INFO: {msg}")

        def error(self, msg):
            print(f"ERROR: {msg}")

        def warning(self, msg):
            print(f"WARN: {msg}")

    log = MockLog()

    def load_secure_config(_):
        return {}

    def wc_api_config_for_sdk(cfg):
        return cfg or {}

    def is_field_enabled(_config, _key):
        return True


SQL_QUERY = """
SELECT
    T1.Id AS Attribute_ID,
    T1.Name AS Attribute_Name_Fa,
    T2.Id AS Term_ID,
    T2.Name AS Term_Name_Fa
FROM
    PoshakProperties AS T1
LEFT JOIN
    PoshakProperties AS T2
    ON T1.Id = T2.ParentID
WHERE
    T1.ParentID = 0
ORDER BY
    T1.Id, T2.Id;
"""

# timeout و retry در wc_sync_helper
_TERM_PARALLEL_WORKERS = 8
_LOG = "[ویژگی‌ها]"


def normalize_text(value):
    text = str(value or "").strip()
    text = text.replace("ي", "ی").replace("ك", "ک")
    return " ".join(text.split())


# ارقام فارسی/عربی برای تطبیق termها
_MATCH_KEY_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def _match_key(value):
    """کلید یکسان برای مقایسه نام attribute/term بین ERP و Woo."""
    return normalize_text(value).translate(_MATCH_KEY_DIGITS).casefold()


def _attr_slug(attr_name):
    # نام فارسی slug خیلی بلند می‌سازد و از سقف taxonomy ووکامرس (pa_ + 28 کاراکتر) رد می‌شود؛
    # یک نامک کوتاه و پایدار از hash نام می‌سازیم. نام نمایشی فارسی دست‌نخورده می‌ماند.
    digest = hashlib.md5(_match_key(attr_name).encode("utf-8")).hexdigest()[:10]
    return f"attr-{digest}"


def fetch_poshak_properties_rows(config):
    """خواندن PoshakProperties — همان مسیر اتصال open_sql_connection (مثل پیش‌نمایش تب)."""
    from sync_app.core.sql_connection_helper import format_db_error, open_sql_connection

    try:
        conn, _, _ = open_sql_connection(config, timeout=10)
    except Exception as exc:
        log.error(f"{_LOG} ❌ خطا در اتصال به SQL: {exc}")
        raise RuntimeError(format_db_error(exc)) from exc

    try:
        cursor = conn.cursor()
        cursor.execute(SQL_QUERY)
        return cursor.fetchall(), conn
    except Exception as exc:
        conn.close()
        log.error(f"{_LOG} ❌ خطا در خواندن PoshakProperties: {exc}")
        raise RuntimeError(format_db_error(exc)) from exc


def fetch_data_from_sql_server(conn_str, query):
    """سازگاری قدیمی — ترجیحاً fetch_poshak_properties_rows(config)."""
    try:
        cnxn = pyodbc.connect(conn_str, timeout=10)
        cursor = cnxn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        return rows, cnxn
    except Exception as e:
        log.error(f"{_LOG} ❌ خطا در اتصال به SQL: {e}")
        return None, None


def process_data_for_woocommerce(raw_data):
    attributes_dict = {}
    for row in raw_data:
        attr_name = normalize_text(row.Attribute_Name_Fa)
        term_name = normalize_text(row.Term_Name_Fa) if row.Term_Name_Fa else None

        if not attr_name:
            continue

        if attr_name not in attributes_dict:
            attributes_dict[attr_name] = set()

        if term_name and term_name != attr_name:
            attributes_dict[attr_name].add(term_name)

    return attributes_dict


def apply_network_overrides(config):  # noqa: F811 — re-export for scripts that import from here
    from sync_app.core.wc_sync_helper import apply_network_overrides as _apply

    return _apply(config)


def create_wcapi(config, verify_ssl):
    from sync_app.core.integrations.commerce_provider import build_store_api

    return build_store_api(config, verify_ssl=verify_ssl)


def _wc_call(wcapi, label, call_fn, retries=WC_SYNC_RETRIES):
    return wc_call(wcapi, label, call_fn, retries=retries)


def _fetch_wc_attributes(wcapi):
    def _call():
        response = wcapi.get(
            "products/attributes",
            params={"per_page": 100, "_fields": "id,name,slug"},
        )
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError(f"پاسخ نامعتبر attributes: {data}")
        return data

    return _wc_call(wcapi, f"{_LOG} دریافت attributes", _call, retries=1)


def _fetch_attribute_terms(wcapi, attr_id):
    def _call():
        terms = []
        page = 1
        while True:
            response = wcapi.get(
                f"products/attributes/{attr_id}/terms",
                params={"per_page": 100, "page": page},
            )
            batch = response.json()
            if isinstance(batch, dict) and batch.get("code"):
                raise RuntimeError(batch.get("message") or str(batch))
            if not isinstance(batch, list) or not batch:
                break
            terms.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return terms

    return _wc_call(wcapi, f"{_LOG} دریافت terms #{attr_id}", _call, retries=1)


def _find_attr_id(all_attrs, name):
    target = _match_key(name)
    if not target:
        return None
    for attr in all_attrs:
        if not isinstance(attr, dict):
            continue
        attr_name = _match_key(attr.get("name"))
        attr_slug = _match_key(attr.get("slug"))
        if target == attr_name or target == attr_slug:
            return attr.get("id")
    return None


def _build_attrs_map(all_attrs):
    """نقشه نام/slug نرمال‌شده → id — فقط از لیست زنده Woo."""
    out = {}
    for attr in all_attrs or []:
        if not isinstance(attr, dict) or not attr.get("id"):
            continue
        for raw in (attr.get("name"), attr.get("slug")):
            key = _match_key(raw)
            if key and key not in out:
                out[key] = attr.get("id")
    return out


def _resolve_attr_id(all_attrs, attrs_map, attr_name):
    key = _match_key(attr_name)
    if not key:
        return None
    aid = attrs_map.get(key)
    if aid:
        return aid
    aid = _find_attr_id(all_attrs, attr_name)
    if aid:
        attrs_map[key] = aid
    return aid


def _verify_attr_live(wcapi, attr_id, attr_name):
    """attribute را با GET تکی تأیید می‌کند — id قدیمی/نامعتبر رد می‌شود."""
    def _call():
        resp = wcapi.get(
            f"products/attributes/{int(attr_id)}",
            params={"_fields": "id,name,slug"},
        ).json()
        if isinstance(resp, dict) and resp.get("code"):
            return None
        if not isinstance(resp, dict) or not resp.get("id"):
            return None
        target = _match_key(attr_name)
        wc_name = _match_key(resp.get("name"))
        wc_slug = _match_key(resp.get("slug"))
        if target and (target == wc_name or target == wc_slug):
            return resp
        return None

    try:
        return _wc_call(wcapi, f"{_LOG} تأیید attribute '{attr_name}'", _call, retries=0)
    except Exception:
        return None


def _update_attr_name(wcapi, attr_id, new_name):
    """نام attribute موجود را در Woo به‌روز می‌کند (PUT)."""
    def _call(aid=attr_id, name=new_name):
        return wcapi.put(f"products/attributes/{int(aid)}", {"name": name}).json()
    try:
        result = _wc_call(wcapi, f"{_LOG} به‌روزرسانی نام attribute '{new_name}'", _call, retries=1)
        if isinstance(result, dict) and result.get("id"):
            log.info(f"{_LOG} 🔄 نام ویژگی به‌روز شد: '{new_name}' (ID: {attr_id})")
            return True
        return False
    except Exception as exc:
        log.warning(f"{_LOG} ⚠️ به‌روزرسانی نام '{new_name}' (ID:{attr_id}) — {exc}")
        return False


def _load_attr_id_map() -> dict[str, int]:
    """بارگذاری نگاشت نام‌نرمال ERP → Woo attribute ID از فایل."""
    try:
        from sync_app.core.sync_utils import app_path
        import json
        path = app_path("attr_id_map.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {str(k): int(v) for k, v in data.items() if v}
    except Exception:
        pass
    return {}


def _save_attr_id_map(mapping: dict[str, int]) -> None:
    """ذخیره نگاشت نام‌نرمال ERP → Woo attribute ID در فایل."""
    try:
        from sync_app.core.sync_utils import app_path
        import json
        path = app_path("attr_id_map.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({str(k): int(v) for k, v in mapping.items() if v}, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"{_LOG} ⚠️ ذخیره attr_id_map.json ناموفق: {exc}")


def _term_keys_from_wc(terms):
    keys = set()
    for term in terms or []:
        if not isinstance(term, dict):
            continue
        for raw in (term.get("name"), term.get("slug")):
            key = _match_key(raw)
            if key:
                keys.add(key)
    return keys


def _erp_term_keys(terms):
    return {_match_key(t) for t in (terms or []) if _match_key(t)}


def _term_overlap_score(erp_keys: set[str], wc_keys: set[str]) -> float:
    if not erp_keys or not wc_keys:
        return 0.0
    inter = len(erp_keys & wc_keys)
    if inter == 0:
        return 0.0
    return inter / max(1, min(len(erp_keys), len(wc_keys)))


def _find_attr_by_term_overlap(
    wcapi,
    erp_terms,
    candidate_attrs,
    *,
    claimed_ids: set[int],
    min_score: float = 0.35,
):
    """وقتی نام ویژگی در ERP عوض شده، با همپوشانی termها همان attribute Woo را پیدا کن."""
    erp_keys = _erp_term_keys(erp_terms)
    if not erp_keys:
        return None, 0.0

    best_id = None
    best_score = 0.0
    for attr in candidate_attrs or []:
        if not isinstance(attr, dict):
            continue
        aid = int(attr.get("id") or 0)
        if not aid or aid in claimed_ids:
            continue
        try:
            wc_terms = _fetch_attribute_terms(wcapi, aid)
        except Exception:
            continue
        wc_keys = _term_keys_from_wc(wc_terms)
        score = _term_overlap_score(erp_keys, wc_keys)
        if score > best_score:
            best_score = score
            best_id = aid

    if best_id and best_score >= min_score:
        return best_id, best_score
    return None, 0.0


def _purge_id_map_keys_for_attr(id_map: dict[str, int], attr_id: int, keep_key: str = "") -> None:
    """کلیدهای قدیمی نگاشت که به همان Woo ID اشاره می‌کنند حذف می‌شوند."""
    keep = _match_key(keep_key) if keep_key else ""
    stale = [k for k, v in id_map.items() if int(v) == int(attr_id) and k != keep]
    for k in stale:
        id_map.pop(k, None)


def _get_attr_record(wcapi, attr_id):
    def _call(aid=attr_id):
        resp = wcapi.get(
            f"products/attributes/{int(aid)}",
            params={"_fields": "id,name,slug"},
        ).json()
        if isinstance(resp, dict) and resp.get("id"):
            return resp
        return None

    try:
        return _wc_call(wcapi, f"{_LOG} دریافت attribute ID={attr_id}", _call, retries=0)
    except Exception:
        return None


def _rename_attr_if_needed(wcapi, attr_id, erp_name, existing_attrs_map, config=None):
    """نام Woo را با ERP هماهنگ کن — بدون ساخت attribute تکراری."""
    record = _get_attr_record(wcapi, attr_id)
    if not record:
        return False
    old_name = str(record.get("name") or "").strip()
    if _match_key(old_name) == _match_key(erp_name):
        return True
    if not is_field_enabled(config or {}, "SYNC_FIELD_ATTRIBUTE_NAME"):
        log.info(f"{_LOG} ⏭️ همگام‌سازی «نام ویژگی» غیرفعال است — رد شد: '{old_name}'")
        return True
    log.info(f"{_LOG} 🔄 نام ویژگی تغییر کرد: '{old_name}' -> '{erp_name}' (ID: {attr_id})")
    if not _update_attr_name(wcapi, attr_id, erp_name):
        return False
    old_key = _match_key(old_name)
    new_key = _match_key(erp_name)
    if old_key and old_key in existing_attrs_map:
        del existing_attrs_map[old_key]
    if new_key:
        existing_attrs_map[new_key] = attr_id
    return True


def _missing_term_names(erp_terms, wc_term_keys):
    missing = []
    for term in sorted(erp_terms or []):
        if term and _match_key(term) not in wc_term_keys:
            missing.append(term)
    return missing


def _term_similarity(a: str, b: str) -> float:
    ka, kb = _match_key(a), _match_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    ratio = SequenceMatcher(None, ka, kb).ratio()
    if ka in kb or kb in ka:
        ratio = max(ratio, 0.82)
    return ratio


def _rename_term_if_needed(wcapi, attr_id, term_id, new_name):
    def _call():
        return wcapi.put(
            f"products/attributes/{int(attr_id)}/terms/{int(term_id)}",
            {"name": new_name},
        ).json()

    try:
        result = _wc_call(
            wcapi,
            f"{_LOG} به‌روزرسانی term '{new_name}'",
            _call,
            retries=1,
        )
        if isinstance(result, dict) and result.get("id"):
            return True
        return False
    except Exception as exc:
        log.warning(f"{_LOG} ⚠️ به‌روزرسانی term '{new_name}' — {exc}")
        return False


def _sync_renamed_terms(wcapi, attr_id, erp_terms, wc_terms, wc_term_keys, config=None):
    """وقتی نام term در ERP عوض شده، همان term قدیمی Woo را rename می‌کند."""
    if not is_field_enabled(config or {}, "SYNC_FIELD_ATTRIBUTE_NAME"):
        return 0, wc_term_keys
    erp_keys = _erp_term_keys(erp_terms)
    renamed = 0
    used_wc_ids: set[int] = set()

    wc_candidates = []
    for term in wc_terms or []:
        if not isinstance(term, dict) or not term.get("id"):
            continue
        name = normalize_text(term.get("name"))
        key = _match_key(name)
        if not key or key in erp_keys:
            continue
        wc_candidates.append(
            {"id": int(term["id"]), "name": name, "key": key}
        )

    missing_erp = _missing_term_names(erp_terms, wc_term_keys)
    if not missing_erp or not wc_candidates:
        return renamed, wc_term_keys

    for erp_name in missing_erp:
        erp_key = _match_key(erp_name)
        best = None
        best_score = 0.0
        for wc_term in wc_candidates:
            if wc_term["id"] in used_wc_ids:
                continue
            score = _term_similarity(erp_name, wc_term["name"])
            if score > best_score:
                best_score = score
                best = wc_term
        if best is None or best_score < 0.72:
            continue
        if _rename_term_if_needed(wcapi, attr_id, best["id"], erp_name):
            used_wc_ids.add(best["id"])
            wc_term_keys.discard(best["key"])
            wc_term_keys.add(erp_key)
            renamed += 1
            log.info(
                f"{_LOG} 🔄 term به‌روز شد: '{best['name']}' -> '{erp_name}' "
                f"(شباهت: {best_score:.0%})"
            )

    return renamed, wc_term_keys


def _post_term(wcapi, attr_id, term_name):
    def _call():
        return wcapi.post(f"products/attributes/{attr_id}/terms", {"name": term_name}).json()

    return _wc_call(wcapi, f"ساخت term '{term_name}'", _call, retries=0)


def _create_missing_terms(wcapi, attr_id, terms, wc_term_keys):
    missing = _missing_term_names(terms, wc_term_keys)
    if not missing:
        return 0, []

    created = 0
    errors = []

    def _one(term):
        try:
            resp = _post_term(wcapi, attr_id, term)
            if isinstance(resp, dict):
                if resp.get("code") == "term_exists":
                    return term, "exists"
                if resp.get("id"):
                    return term, "created"
                return term, resp.get("message") or str(resp)
            return term, "پاسخ نامعتبر از Woo"
        except Exception as exc:
            return term, str(exc)

    workers = 1 if len(missing) <= 2 else min(_TERM_PARALLEL_WORKERS, len(missing))
    if workers == 1:
        jobs = [_one(t) for t in missing]
    else:
        jobs = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_one, term): term for term in missing}
            for future in as_completed(futures):
                jobs.append(future.result())

    for term, status in jobs:
        if status == "created":
            created += 1
            log.info(f"{_LOG} ➕ مقدار اضافه شد: {term}")
        elif status == "exists":
            log.info(f"{_LOG} ℹ️ مقدار از قبل موجود بود: {term}")
        else:
            errors.append(f"{term}: {status}")
            log.error(f"{_LOG} ❌ خطا در term '{term}': {status}")

    return created, errors


def _create_attribute(wcapi, attr_name, attrs_map, all_attrs):
    log.info(f"{_LOG} 🆕 ساخت ویژگی جدید: {attr_name}")
    new_attr = _wc_call(
        wcapi,
        f"ساخت attribute '{attr_name}'",
        lambda an=attr_name: wcapi.post(
            "products/attributes",
            {"name": an, "slug": _attr_slug(an), "type": "select"},
        ).json(),
    )
    attr_id = new_attr.get("id") if isinstance(new_attr, dict) else None
    if not attr_id and isinstance(new_attr, dict) and new_attr.get("code"):
        log.warning(f"{_LOG} ⚠️ Woo خطا برای '{attr_name}': {new_attr.get('code')} — {new_attr.get('message', '')}")
        # slug تکراری یا attribute موجود — دوباره از لیست زنده پیدا کن
        all_attrs[:] = _fetch_wc_attributes(wcapi)
        attrs_map.clear()
        attrs_map.update(_build_attrs_map(all_attrs))
        attr_id = _resolve_attr_id(all_attrs, attrs_map, attr_name)
        # اگر هنوز پیدا نشد، با مقایسه نرم‌شده (حذف هایفن) هم امتحان کن
        if not attr_id:
            norm = _match_key(attr_name).replace("-", " ").replace("  ", " ")
            for attr in all_attrs:
                for raw in (attr.get("name"), attr.get("slug")):
                    candidate = _match_key(str(raw or "")).replace("-", " ").replace("  ", " ")
                    if candidate and candidate == norm:
                        attr_id = attr.get("id")
                        break
                if attr_id:
                    break
    if not attr_id:
        all_attrs[:] = _fetch_wc_attributes(wcapi)
        attrs_map.clear()
        attrs_map.update(_build_attrs_map(all_attrs))
        attr_id = _resolve_attr_id(all_attrs, attrs_map, attr_name)
    if attr_id:
        key = _match_key(attr_name)
        if key:
            attrs_map[key] = attr_id
    return attr_id


def sync_attributes_dynamic(wcapi, attributes_data_dejavu, config=None):
    stats = {
        "attrs_synced": 0,
        "attrs_created": 0,
        "attrs_already_ok": 0,
        "terms_created": 0,
        "errors": [],
    }

    log.info(f"{_LOG} 🔍 استخراج ویژگی‌های فعلی از ووکامرس...")
    existing_attributes = _fetch_wc_attributes(wcapi)
    existing_attrs_map = _build_attrs_map(existing_attributes)

    # نگاشت پایدار نام ERP → Woo ID (برای تطبیق حتی بعد از تغییر نام)
    saved_id_map = _load_attr_id_map()
    updated_id_map: dict[str, int] = dict(saved_id_map)
    claimed_attr_ids: set[int] = set()

    for attr_name, terms in attributes_data_dejavu.items():
        attr_name = normalize_text(attr_name)
        terms = {normalize_text(t) for t in terms if normalize_text(t)}
        if not attr_name:
            continue

        attr_created = False
        norm_key = _match_key(attr_name)

        # ۱. جستجو با نام/slug در Woo
        attr_id = _resolve_attr_id(existing_attributes, existing_attrs_map, attr_name)

        # ۲. اگر با نام پیدا نشد، از نگاشت ذخیره‌شده استفاده کن
        if not attr_id and norm_key and norm_key in saved_id_map:
            attr_id = saved_id_map[norm_key]
            log.info(f"{_LOG} 🗂️ ویژگی '{attr_name}' از نگاشت ذخیره‌شده — ID: {attr_id}")

        # ۳. نام ERP عوض شده — با همپوشانی termها همان attribute قدیمی را پیدا کن
        if not attr_id:
            overlap_id, overlap_score = _find_attr_by_term_overlap(
                wcapi,
                terms,
                existing_attributes,
                claimed_ids=claimed_attr_ids,
            )
            if overlap_id:
                attr_id = overlap_id
                log.info(
                    f"{_LOG} 🔗 ویژگی '{attr_name}' با تطبیق term پیدا شد "
                    f"(ID: {attr_id}، شباهت: {overlap_score:.0%})"
                )

        if attr_id and attr_id in claimed_attr_ids:
            attr_id = None

        live_attr = _verify_attr_live(wcapi, attr_id, attr_name) if attr_id else None

        if attr_id and not live_attr:
            existing_wc = _get_attr_record(wcapi, attr_id)
            if existing_wc and existing_wc.get("id"):
                if not _rename_attr_if_needed(wcapi, attr_id, attr_name, existing_attrs_map, config=config):
                    log.warning(f"{_LOG} ⚠️ به‌روزرسانی نام '{attr_name}' (ID:{attr_id}) ناموفق بود")
                live_attr = {"id": attr_id, "name": attr_name}
            else:
                log.warning(
                    f"{_LOG} ⚠️ ویژگی '{attr_name}' با id={attr_id} روی Woo نیست — دوباره جستجو می‌شود"
                )
                if norm_key and norm_key in existing_attrs_map:
                    del existing_attrs_map[norm_key]
                attr_id = None

        if not attr_id:
            try:
                attr_id = _create_attribute(
                    wcapi, attr_name, existing_attrs_map, existing_attributes
                )
                if not attr_id:
                    msg = f"ساخت ویژگی '{attr_name}' ناموفق بود"
                    stats["errors"].append(msg)
                    log.error(f"{_LOG} ⚠️ {msg}")
                    continue
                attr_created = True
                stats["attrs_created"] += 1
            except Exception as exc:
                msg = f"ویژگی '{attr_name}': {exc}"
                stats["errors"].append(msg)
                log.error(f"{_LOG} ❌ {msg}")
                continue

        if attr_id:
            claimed_attr_ids.add(int(attr_id))

        # ذخیره نگاشت برای دفعات بعد
        if attr_id and norm_key:
            _purge_id_map_keys_for_attr(updated_id_map, int(attr_id), keep_key=norm_key)
            updated_id_map[norm_key] = int(attr_id)

        log.info(f"{_LOG} 🔄 {attr_name} — {len(terms)} مقدار ERP")
        try:
            existing_terms = _fetch_attribute_terms(wcapi, attr_id)
            wc_term_keys = _term_keys_from_wc(existing_terms)
            renamed, wc_term_keys = _sync_renamed_terms(
                wcapi, attr_id, terms, existing_terms, wc_term_keys, config=config
            )
            if renamed:
                stats["terms_created"] += renamed
            missing_terms = _missing_term_names(terms, wc_term_keys)
            if not missing_terms:
                log.info(f"{_LOG} ✅ {attr_name} — همه termها موجود (تأیید زنده)")
                stats["attrs_synced"] += 1
                if not attr_created:
                    stats["attrs_already_ok"] += 1
                continue
            log.info(
                f"{_LOG} ➕ {attr_name} — {len(missing_terms)} term کم است: "
                f"{', '.join(missing_terms[:5])}"
            )
            created, term_errors = _create_missing_terms(
                wcapi, attr_id, terms, wc_term_keys
            )
            stats["terms_created"] += created
            stats["errors"].extend(term_errors)
            stats["attrs_synced"] += 1
        except Exception as exc:
            msg = f"terms '{attr_name}': {exc}"
            stats["errors"].append(msg)
            log.error(f"{_LOG} ❌ {msg}")

    # ذخیره نگاشت به‌روز شده
    if updated_id_map:
        _save_attr_id_map(updated_id_map)

    return stats


def main():
    log.info(f"{_LOG} 🚀 شروع همگام‌سازی داینامیک ویژگی‌ها...")
    log.info(f"{_LOG} Poshakproperties — اتصال SQL و فروشگاه...")
    config = load_secure_config(None) or {}

    from sync_app.core.integrations.commerce_provider import is_prestashop, store_platform_label

    ps_mode = is_prestashop(config)
    if ps_mode:
        if not config.get("PS_URL") or not config.get("PS_API_KEY"):
            raise RuntimeError("تنظیمات پرستاشاپ ناقص است.")
    else:
        apply_network_overrides(config)
        if not config.get("WC_URL"):
            raise RuntimeError(f"تنظیمات {store_platform_label(config)} ناقص است.")
    if not (
        config.get("SQL_CONN_STRING")
        or (config.get("SQL_SERVER") and config.get("SQL_DATABASE"))
    ):
        raise RuntimeError("تنظیمات SQL ناقص است.")

    raw_data, cnxn = fetch_poshak_properties_rows(config)
    if not raw_data:
        cnxn.close()
        raise RuntimeError(
            "داده‌ای از SQL برای ویژگی‌ها یافت نشد.\n"
            "جدول PoshakProperties در دیتابیس ERP خالی است یا دسترسی ندارید."
        )

    attributes_data_dejavu = process_data_for_woocommerce(raw_data)
    if not attributes_data_dejavu:
        cnxn.close()
        log.warning(f"{_LOG} ℹ️ هیچ ویژگی‌ای در ERP برای همگام‌سازی نیست.")
        return {"attrs_synced": 0, "terms_created": 0, "errors": []}

    from sync_app.core.integrations.commerce_provider import warm_store_connection

    verify_ssl = bool(config.get("WC_VERIFY_SSL", False))
    wcapi = create_wcapi(config, verify_ssl=verify_ssl)
    warm_store_connection(wcapi, config)

    try:
        stats = sync_attributes_dynamic(wcapi, attributes_data_dejavu, config=config)
    except requests.exceptions.SSLError:
        log.warning(f"{_LOG} ⚠️ SSL ناپایدار — تلاش مجدد با verify_ssl=False")
        wcapi = create_wcapi(config, verify_ssl=False)
        stats = sync_attributes_dynamic(wcapi, attributes_data_dejavu, config=config)
    except Exception as exc:
        raise RuntimeError(format_wc_network_error(exc)) from exc
    finally:
        cnxn.close()

    err_count = len(stats.get("errors") or [])
    log.info(
        f"{_LOG} 📊 پایان ویژگی‌ها: "
        f"{stats.get('attrs_created', 0)} ویژگی جدید، "
        f"{stats.get('attrs_already_ok', 0)} از قبل موجود، "
        f"{stats.get('terms_created', 0)} term جدید، {err_count} خطا"
    )

    try:
        from sync_app.core.secure_config_loader import save_secure_config
        from sync_app.core.wc_attr_cache import WC_ATTR_CACHE_KEY

        cfg = load_secure_config(None) or {}
        if WC_ATTR_CACHE_KEY in cfg:
            del cfg[WC_ATTR_CACHE_KEY]
            save_secure_config(cfg)
            log.info(f"{_LOG} 🧹 کش ویژگی‌های Woo پاک شد")
    except Exception:
        pass

    if err_count > 0:
        sample = "؛ ".join((stats["errors"][:3]))
        raise RuntimeError(
            f"همگام‌سازی ویژگی‌ها ناقص بود ({err_count} خطا).\n{sample}\n"
            "اتصال Woo آنلاین و VPN را بررسی کنید."
        )

    if stats.get("attrs_synced", 0) == 0:
        raise RuntimeError("هیچ ویژگی‌ای به ووکامرس ارسال نشد.")

    log.info(f"{_LOG} ✅ همگام‌سازی ویژگی‌ها با موفقیت انجام شد.")
    return stats


if __name__ == "__main__":
    main()
