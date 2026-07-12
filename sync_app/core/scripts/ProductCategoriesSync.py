# ---------------------------------------------------------
# importهای داخلی
# ---------------------------------------------------------
import json
import re
import sys
import os
import pyodbc
from urllib.parse import unquote

# ---------------------------------------------------------
# 🔧 مسیر داینامیک برای EXE و سورس
# ---------------------------------------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


# ---------------------------------------------------------
# 🔧 importهای داخلی (به صورت پکیجی)
# ---------------------------------------------------------
try:
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_utils import log, app_path
    from sync_app.core.wc_api_helper import wc_api_config_for_sdk
    from sync_app.core.category_resolver import dejavu_category_slug, extract_code_from_wc_slug, load_category_map
    from sync_app.core.category_rules import (
        categories_confirmed_on_woo,
        prepare_category_context,
        sort_categories_for_sync,
    )
    from sync_app.core.wc_sync_helper import (
        apply_network_overrides,
        build_wcapi,
        wc_call_config,
        wc_rest_json,
    )
    from sync_app.core.scripts.sync_fullproduct import patch_product_categories
    from sync_app.core.sync_cancel import check_cancelled, SyncCancelled
    from sync_app.core.field_sync_config import is_field_enabled
except ImportError:
    class MockLog:
        def info(self, msg): print(f"INFO: {msg}")
        def error(self, msg): print(f"ERROR: {msg}")
        def warning(self, msg): print(f"WARNING: {msg}")
        def critical(self, msg): print(f"CRITICAL: {msg}")

    log = MockLog()

    def load_secure_config(_):
        log.critical("❌ ماژول‌های اصلی یافت نشد.")
        return {}

    def app_path(name):
        return os.path.join(os.getcwd(), name)

    def is_field_enabled(_config, _key):
        return True


# ---------------------------------------------------------
# 🔧 توابع اصلی
# ---------------------------------------------------------
def create_woocommerce_api(config):
    cfg = wc_api_config_for_sdk(config or {})
    url = cfg.get('WC_URL')
    ck = cfg.get('WC_CONSUMER_KEY')
    cs = cfg.get('WC_CONSUMER_SECRET')

    if not isinstance(url, str) or not url.strip():
        log.error("❌ تنظیم WC_URL خالی یا نامعتبر است.")
        return None
    if not isinstance(ck, str) or not ck.strip():
        log.error("❌ تنظیم WC_CONSUMER_KEY خالی یا نامعتبر است.")
        return None
    if not isinstance(cs, str) or not cs.strip():
        log.error("❌ تنظیم WC_CONSUMER_SECRET خالی یا نامعتبر است.")
        return None

    apply_network_overrides(config or {})
    return build_wcapi(config or {})


def fetch_data_from_sql_server(conn_string, query):
    # اعتبارسنجی رشته اتصال
    if not isinstance(conn_string, str) or not conn_string.strip():
        log.error("❌ رشته اتصال SQL_CONN_STRING خالی یا نامعتبر است.")
        return []

    conn = None
    try:
        conn = pyodbc.connect(conn_string.strip(), timeout=10)
        cursor = conn.cursor()
        log.info("✅ اتصال به دیتابیس برقرار شد.")
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except pyodbc.Error as ex:
        # تبدیل خطای pyodbc به پیام خوانا
        try:
            error_message = f"({ex.args[0][0]}) {ex.args[1]}" if len(ex.args) > 1 and ex.args[1] else str(ex)
        except Exception:
            error_message = str(ex)
        log.error(f"❌ خطای دیتابیس: {error_message}")
        return []
    except Exception as e:
        log.error(f"❌ خطا در اجرای کوئری: {e}")
        return []
    finally:
        if conn:
            conn.close()
            log.info("✅ اتصال به دیتابیس بسته شد.")


def process_categories_for_woocommerce(raw_data):
    processed_categories = []
    seen_ids = set()

    # اطمینان از اینکه فیلدها رشته هستند
    try:
        raw_data.sort(key=lambda x: len(str(x['Dejavu_ID']).strip()))
    except Exception as e:
        log.warning(f"⚠️ خطا در مرتب‌سازی دسته‌بندی‌ها: {e}")

    for row in raw_data:
        dejavu_id_raw = str(row.get('Dejavu_ID', '')).strip()
        if not dejavu_id_raw or dejavu_id_raw in seen_ids:
            continue

        name_raw = row.get('Group_Name', '')
        name = re.sub(r'[^\w\s\-\.]', '', str(name_raw).strip()) if name_raw is not None else ''

        dejavu_id = dejavu_id_raw
        slug = dejavu_category_slug(dejavu_id)

        parent_raw = row.get('Parent_Dejavu_ID')
        parent_dejavu_id = str(parent_raw).strip() if parent_raw is not None else None

        processed_categories.append({
            'dejavu_id': dejavu_id,
            'parent_dejavu_id': parent_dejavu_id,
            'name': name,
            'slug': slug,
            'parent_id': 0
        })
        seen_ids.add(dejavu_id)
    return processed_categories


def _norm_cat_name(name) -> str:
    """نرمال‌سازی نام دسته برای تطبیق: یکسان‌سازی ی/ک عربی‌وفارسی + فاصله‌ها."""
    txt = str(name or "").strip()
    # ي/ی و ك/ک و اعراب/نیم‌فاصله را یکسان کن تا تطبیق نام درست شود
    txt = txt.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    txt = txt.replace("ة", "ه").replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    txt = re.sub(r"[\u064B-\u0652]", "", txt)  # حذف اعراب عربی
    txt = re.sub(r"\s+", " ", txt)
    return txt.casefold()


def _term_exists_id(wc_response) -> int | None:
    """id دستهٔ موجود از خطای term_exists ووکامرس."""
    if not isinstance(wc_response, dict):
        return None
    data = wc_response.get("data")
    if isinstance(data, dict) and data.get("resource_id"):
        try:
            return int(data["resource_id"])
        except (TypeError, ValueError):
            return None
    return None


def _wanted_dejavu_codes(categories_to_sync):
    return {
        str(c.get("dejavu_id", "")).strip()
        for c in (categories_to_sync or [])
        if str(c.get("dejavu_id", "")).strip()
    }


def _category_put_payload(category, code_to_wc_id: dict, config=None, *, is_create=False) -> dict:
    """
    بدنه PUT/POST دسته — والد از نگاشت کد ERP.
    نکته: «Slug» همیشه ارسال می‌شود و چک‌باکس ندارد — چون خود برنامه از روی
    الگوی slug (بر پایه کد ERP) دسته‌های موجود روی Woo را در سینک‌های بعدی
    پیدا می‌کند؛ غیرفعال کردنش می‌تواند باعث ساخت دسته‌های تکراری شود.
    موقع ایجاد دسته‌ی جدید (is_create=True) همیشه همه‌ی فیلدها کامل ارسال می‌شوند.
    """
    parent_dejavu_id = category.get("parent_dejavu_id")
    parent_wc_id = 0
    if parent_dejavu_id:
        parent_wc_id = int(code_to_wc_id.get(str(parent_dejavu_id)) or 0)
    payload = {
        "name": str(category.get("name") or ""),
        "slug": str(category.get("slug") or ""),
        "parent": parent_wc_id,
    }
    if not is_create:
        cfg = config or {}
        if not is_field_enabled(cfg, "SYNC_FIELD_CATEGORY_NAME"):
            payload.pop("name", None)
        if not is_field_enabled(cfg, "SYNC_FIELD_CATEGORY_PARENT"):
            payload.pop("parent", None)
    return payload


def _put_category_update(config, wc_id, payload, name, update_failed) -> bool:
    try:
        def _update(cid=wc_id, body=payload, cat_name=name):
            return wc_rest_json(
                config,
                "PUT",
                f"products/categories/{cid}",
                json_body=body,
                label=f"به‌روزرسانی دسته '{cat_name}'",
            )

        wc_call_config(config, f"به‌روزرسانی دسته '{name}'", _update)
        log.info(f"🔄 به‌روزرسانی: '{name}' (ID: {wc_id})")
        return True
    except Exception as e:
        log.warning(
            f"⚠️ به‌روزرسانی '{name}' (ID: {wc_id}) timeout/خطا — "
            f"دسته در Woo موجود است: {e}"
        )
        update_failed.append(name)
        return False


def _sync_category_name_updates(config, categories_to_sync, code_to_wc_id: dict):
    """نام/slug/parent دسته‌های موجود را روی Woo به‌روز می‌کند."""
    update_failed: list = []
    ordered = sort_categories_for_sync(categories_to_sync)
    active_map = dict(code_to_wc_id or {})
    for category in ordered:
        check_cancelled()
        code_key = str(category.get("dejavu_id") or "").strip()
        if not code_key:
            continue
        wc_id = int(active_map.get(code_key) or 0)
        if not wc_id:
            continue
        payload = _category_put_payload(category, active_map, config)
        _put_category_update(config, wc_id, payload, category.get("name"), update_failed)
        active_map[code_key] = wc_id
    return update_failed, active_map


def _save_category_map_payload(payload):
    if not payload:
        return False
    try:
        map_path = app_path("category_map.json")
        with open(map_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
        log.info(f"✅ نقشه دسته‌بندی‌ها در {map_path} ذخیره شد ({len(payload)} مورد).")
        return True
    except Exception as e:
        log.error(f"❌ خطا در ذخیره category_map.json: {e}")
        return False


def _try_fast_category_apply(config, categories_to_sync):
    """map کامل است — فقط اگر دسته‌ها واقعاً روی Woo باشند."""
    prior = load_category_map()
    wanted = _wanted_dejavu_codes(categories_to_sync)
    if not wanted or not wanted.issubset(prior.keys()):
        return None

    ctx = prepare_category_context(config, fetch_live=True)
    slug_map = ctx.get("slug_map") or {}
    if not categories_confirmed_on_woo(wanted, slug_map):
        log.info(
            f"دسته‌ها روی Woo نیستند یا ناقص‌اند ({len(wanted)} مورد) — "
            f"sync کامل دسته‌بندی..."
        )
        return None

    merged = ctx["category_map"]
    if not wanted.issubset(merged.keys()):
        return None

    log.info(
        f"⚡ {len(wanted)} دسته روی Woo تأیید شد — "
        f"فقط اعمال روی محصولات..."
    )
    patch_stats = patch_product_categories(config)
    return {
        "synced": len(wanted),
        "failed": [],
        "update_failed": [],
        "total": len(categories_to_sync),
        "used_local_map": True,
        "products_patched": patch_stats.get("ok", 0),
        "products_patch_failed": patch_stats.get("failed", 0),
        "products_patch_failed_skus": patch_stats.get("failed_skus", []),
        "products_skipped": patch_stats.get("skipped", 0),
    }


def _all_categories_in_local_map(categories_to_sync, prior):
    wanted = _wanted_dejavu_codes(categories_to_sync)
    if not wanted or not wanted.issubset(prior.keys()):
        return False
    if not all(prior.get(code) for code in wanted):
        return False
    parent_codes = {
        str(c.get("parent_dejavu_id")).strip()
        for c in (categories_to_sync or [])
        if c.get("parent_dejavu_id")
    }
    return parent_codes.issubset(prior.keys())


def sync_categories_to_woocommerce(categories_to_sync, config=None):
    prior = load_category_map()
    wanted = _wanted_dejavu_codes(categories_to_sync)
    # فقط از دادهٔ زندهٔ Woo پر می‌شود (نه map قدیمی) تا «روی Woo هست»ِ دروغین نگیریم.
    TEMP_ID_MAP: dict = {}
    DEJAVU_ID_TO_WC_ID_MAP: dict = {}
    failed = []
    update_failed = []
    last_error = ""

    ordered = sort_categories_for_sync(categories_to_sync)

    live_ctx = prepare_category_context(config, fetch_live=True) if config else {}
    live_slug_map = (live_ctx or {}).get("slug_map") or {}

    if _all_categories_in_local_map(categories_to_sync, prior) and categories_confirmed_on_woo(
        wanted, live_slug_map
    ):
        merged_live = (live_ctx or {}).get("category_map") or prior
        mapping = {str(code): int(merged_live[str(code)]) for code in wanted if str(code) in merged_live}
        log.info(f"⚡ {len(mapping)} دسته روی Woo تأیید شد — به‌روزرسانی نام‌ها...")
        update_failed, mapping = _sync_category_name_updates(config, categories_to_sync, mapping)
        _save_category_map_payload({**prior, **mapping})
        return {
            "synced": len(mapping),
            "failed": [],
            "update_failed": update_failed,
            "total": len(categories_to_sync),
            "used_local_map": True,
        }

    if _all_categories_in_local_map(categories_to_sync, prior) and not categories_confirmed_on_woo(
        wanted, live_slug_map
    ):
        log.info("دسته‌ها در map محلی هستند ولی روی Woo نیستند — ساخت مجدد...")

    # نگاشت نام دستهٔ Woo → id (برای تطبیق وقتی slug فارسی/متفاوت است)
    NAME_ID_MAP: dict[str, int] = {}

    log.info("▶️ واکشی دسته‌بندی‌های موجود از ووکامرس...")
    try:
        page = 1
        while True:
            check_cancelled()
            def _fetch_page(p=page):
                data = wc_rest_json(
                    config,
                    "GET",
                    "products/categories",
                    params={"per_page": 100, "page": p, "_fields": "id,slug,name"},
                    label=f"دریافت categories صفحه {p}",
                )
                if not isinstance(data, list):
                    raise RuntimeError(f"پاسخ نامعتبر categories: {data}")
                return data

            batch = wc_call_config(config, f"دریافت categories صفحه {page}", _fetch_page)
            if not batch:
                break
            for cat in batch:
                slug_val = unquote(str(cat.get('slug', '')).lower())
                code = extract_code_from_wc_slug(slug_val)
                if code:
                    TEMP_ID_MAP[code] = cat.get('id')
                nkey = _norm_cat_name(cat.get('name'))
                if nkey and cat.get('id'):
                    NAME_ID_MAP.setdefault(nkey, int(cat['id']))
            if len(batch) < 100:
                break
            page += 1
        log.info(
            f"✔️ {len(TEMP_ID_MAP)} کد (slug) و {len(NAME_ID_MAP)} نام دسته از ووکامرس واکشی شد."
        )
    except Exception as e:
        last_error = str(e)
        log.error(f"❌ خطا در واکشی دسته‌بندی‌ها: {e}")

    log.info("▶️ شروع ساخت و بروزرسانی دسته‌بندی‌ها...")
    for category in ordered:
        check_cancelled()
        code_key = str(category.get("dejavu_id") or "").strip()
        name = category.get("name", "")
        code_map = {**prior, **DEJAVU_ID_TO_WC_ID_MAP, **TEMP_ID_MAP}
        data = _category_put_payload(category, code_map, config)

        wc_id = None

        if code_key in TEMP_ID_MAP:
            wc_id = int(TEMP_ID_MAP[code_key])
            _put_category_update(config, wc_id, data, name, update_failed)
        elif code_key in prior and prior.get(code_key):
            log.warning(
                f"⚠️ '{name}' — کد {code_key} در map هست ولی slug روی Woo نیست؛ "
                "تطبیق با نام یا ایجاد..."
            )

        def _heal_slug(cid):
            """slug دستهٔ موجود را به cat-XXXX برسان تا دفعهٔ بعد با slug پیدا شود."""
            try:
                def _put(c=cid, payload=data):
                    return wc_rest_json(
                        config,
                        "PUT",
                        f"products/categories/{c}",
                        json_body=payload,
                        label="ترمیم slug دسته",
                    )

                wc_call_config(config, f"ترمیم slug دستهٔ '{name}'", _put)
            except Exception as exc:
                log.warning(f"⚠️ ترمیم slug '{name}' (ID:{cid}) خطا — ID موجود استفاده می‌شود: {exc}")

        if not wc_id:
            # تطبیق بر اساس نام: دسته با slug فارسی/متفاوت از قبل روی Woo هست
            existing_id = NAME_ID_MAP.get(_norm_cat_name(name))
            if existing_id:
                wc_id = existing_id
                _heal_slug(wc_id)
                log.info(f"🩹 تطبیق با نام و ترمیم slug: '{name}' (ID: {wc_id})")
                TEMP_ID_MAP[code_key] = wc_id
            else:
                try:
                    full_payload = _category_put_payload(category, code_map, is_create=True)

                    def _create(payload=full_payload, cat_name=name):
                        return wc_rest_json(
                            config,
                            "POST",
                            "products/categories",
                            json_body=payload,
                            label=f"ایجاد دسته '{cat_name}'",
                        )

                    wc_response = wc_call_config(config, f"ایجاد دسته '{name}'", _create)
                    wc_id = wc_response.get('id') if isinstance(wc_response, dict) else None
                    if wc_id:
                        log.info(f"➕ ایجاد شد: '{name}' (ID: {wc_id})")
                        TEMP_ID_MAP[code_key] = wc_id
                    else:
                        # دسته با همین نام قبلاً هست (term_exists) → از ID موجود استفاده کن
                        exists_id = _term_exists_id(wc_response)
                        if exists_id:
                            wc_id = exists_id
                            _heal_slug(wc_id)
                            log.info(
                                f"🔁 دسته موجود بود (term_exists) — ID: {wc_id}، slug ترمیم شد"
                            )
                            TEMP_ID_MAP[code_key] = wc_id
                        else:
                            error_message = (
                                wc_response.get('message', 'خطای ناشناخته')
                                if isinstance(wc_response, dict) else str(wc_response)
                            )
                            log.error(f"❌ شکست در ایجاد '{name}': {error_message}")
                            failed.append(name)
                            continue
                except Exception as e:
                    last_error = str(e)
                    log.error(f"❌ خطای API در ایجاد '{name}': {e}")
                    failed.append(name)
                    continue

        if wc_id:
            DEJAVU_ID_TO_WC_ID_MAP[code_key] = int(wc_id)

    # اگر fetch ناموفق بود ولی map قبلی داریم، همان را نگه دار
    if not DEJAVU_ID_TO_WC_ID_MAP:
        prior = load_category_map()
        wanted = {str(c.get("dejavu_id", "")).strip() for c in categories_to_sync if c.get("dejavu_id")}
        for code in wanted:
            if code in prior:
                DEJAVU_ID_TO_WC_ID_MAP[code] = prior[code]
        if DEJAVU_ID_TO_WC_ID_MAP:
            log.warning(
                f"⚠️ sync جدید ناموفق — از category_map.json قبلی "
                f"({len(DEJAVU_ID_TO_WC_ID_MAP)} مورد) استفاده می‌شود."
            )

    if DEJAVU_ID_TO_WC_ID_MAP:
        log.info(f"📦 تطبیق نهایی دسته‌بندی‌ها: {len(DEJAVU_ID_TO_WC_ID_MAP)} آیتم.")
        _save_category_map_payload({**prior, **DEJAVU_ID_TO_WC_ID_MAP})
    else:
        log.warning("⚠️ تطبیق دسته‌بندی‌ها خالی است. فایل category_map.json ذخیره نشد.")

    log.info("✅ عملیات همگام‌سازی دسته‌بندی‌ها به پایان رسید.")
    return {
        "synced": len(DEJAVU_ID_TO_WC_ID_MAP),
        "failed": failed,
        "update_failed": update_failed,
        "total": len(categories_to_sync),
        "used_local_map": False,
        "last_error": last_error,
    }


# ---------------------------------------------------------
# main
# ---------------------------------------------------------
def main():
    log.info("▶️ شروع همگام‌سازی دسته‌بندی‌های محصول...")

    # توجه: ماژول تنظیمات تو قبلاً با امضای load_secure_config(None) استفاده می‌شود
    # اینجا هم سازگار با آن فراخوانی می‌کنیم
    config = load_secure_config(None)

    SQL_CONN_STRING = config.get("SQL_CONN_STRING", "")

    selected_main_groups = config.get("SELECTED_CATEGORY_GROUPS", [])
    selected_sub_groups = config.get("SELECTED_SUB_GROUPS", [])

    # اگر هیچ گروهی انتخاب نشده باشد، همگام‌سازی اجرا نمی‌شود
    if not selected_main_groups and not selected_sub_groups:
        log.error("❌ هیچ گروهی انتخاب نشده است. لطفاً ابتدا گروه‌ها را در تب دسته‌بندی‌ها تیک بزنید.")
        return {"synced": 0, "failed": [], "total": 0}

    required_main_groups = set()
    required_sub_group_codes = []

    if selected_main_groups:
        for code in selected_main_groups:
            if isinstance(code, str) and len(code.strip()) == 2:
                required_main_groups.add(code.strip())

    if selected_sub_groups:
        for code in selected_sub_groups:
            if isinstance(code, str) and len(code.strip()) == 4:
                code = code.strip()
                required_sub_group_codes.append(code)
                required_main_groups.add(code[:2])

    main_group_where = ""
    sub_group_where = ""

    if required_main_groups:
        all_main_codes_str = ', '.join([f"'{code}'" for code in sorted(required_main_groups)])
        main_group_where = f" WHERE LTRIM(RTRIM(M_Groupcode)) IN ({all_main_codes_str})"
        log.info(f"✔️ فیلتر گروه‌های اصلی: {all_main_codes_str}")

    if required_sub_group_codes:
        all_sub_codes_str = ', '.join([f"'{code}'" for code in required_sub_group_codes])
        sub_group_where = f" WHERE LTRIM(RTRIM(M_Groupcode)) + LTRIM(RTRIM(S_Groupcode)) IN ({all_sub_codes_str})"
        log.info(f"✔️ فیلتر زیرگروه‌ها: {all_sub_codes_str}")

    query_main_groups = f"""
        SELECT
            LTRIM(RTRIM(M_Groupcode)) AS Dejavu_ID,
            NULL AS Parent_Dejavu_ID,
            M_GroupName AS Group_Name
        FROM M_Group
        {main_group_where}
    """

    query_sub_groups = f"""
        SELECT
            LTRIM(RTRIM(M_Groupcode)) + LTRIM(RTRIM(S_Groupcode)) AS Dejavu_ID,
            LTRIM(RTRIM(M_Groupcode)) AS Parent_Dejavu_ID,
            S_GroupName AS Group_Name
        FROM S_Group
        {sub_group_where if required_sub_group_codes else main_group_where}
    """

    SQL_QUERY_CATEGORIES_DYNAMIC = f"{query_main_groups}\nUNION\n{query_sub_groups}"
    log.info("✅ کوئری نهایی SQL برای دسته‌بندی‌ها ساخته شد.")

    raw_data = fetch_data_from_sql_server(SQL_CONN_STRING, SQL_QUERY_CATEGORIES_DYNAMIC)
    log.info(f"📊 تعداد ردیف‌های واکشی‌شده: {len(raw_data)}")

    if raw_data:
        categories_to_sync = process_categories_for_woocommerce(raw_data)
        log.info(f"📦 دسته‌بندی‌های آماده برای همگام‌سازی: {len(categories_to_sync)}")

        if not create_woocommerce_api(config):
            log.error("❌ تنظیمات WooCommerce ناقص است. URL/Key/Secret را بررسی کنید.")
            return {"synced": 0, "failed": [], "total": 0}

        result = sync_categories_to_woocommerce(categories_to_sync, config)
        if not result.get("used_local_map"):
            patch_stats = patch_product_categories(config)
            result["products_patched"] = patch_stats.get("ok", 0)
            result["products_patch_failed"] = patch_stats.get("failed", 0)
            result["products_patch_failed_skus"] = patch_stats.get("failed_skus", [])
            result["products_skipped"] = patch_stats.get("skipped", 0)
        return result
        return {"synced": 0, "failed": ["API"], "total": 0}

    log.warning("⚠️ داده‌ای برای همگام‌سازی پیدا نشد.")
    return {"synced": 0, "failed": [], "total": 0}


# ---------------------------------------------------------
# اجرای ماژول
# ---------------------------------------------------------
if __name__ == "__main__":
    main()
