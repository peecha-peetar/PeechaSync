"""POS.ItemGroup — گروه/زیرگروهِ کالایِ سپیدار/دشت.

جهتِ سینک: ERP → سایت — دقیقاً مثلِ ProductCategoriesSync.py دژاوو
(M_Group/S_Group از ERP خونده می‌شه و به‌عنوانِ دسته‌بندیِ ووکامرس/
پرستاشاپ ساخته/به‌روزرسانی می‌شه). POS.ItemGroup برخلافِ M_Group/S_Groupِ
دژاوو (دقیقاً ۲ سطحِ ثابت)، یک درختِ عمقِ دلخواهه (ParentGroupRef زنجیره‌ای،
ریشه = -5) — پس sync_categories_from_erp به‌جایِ فرضِ ۲ سطح، زنجیره‌یِ
والدها رو تا ریشه دنبال می‌کنه.

fetch_site_categories همچنان لازمه (سمتِ سایتِ تطبیق در
reconciliation_service.py)."""

from __future__ import annotations

from sync_app.core.scripts.sepidar.sepidar_common import load_sepidar_map, save_sepidar_map

_MAP_FILE = "sepidar_category_map.json"
_ROOT_PARENT_REF = -5  # مطابقِ ترِیسِ واقعی


def fetch_site_categories(config: dict | None = None) -> list[dict]:
    """[{id, name, parent}] — همهٔ دسته‌هایِ محصولِ فروشگاه (ووکامرس/پرستاشاپ)."""
    from sync_app.core.integrations.commerce_provider import store_rest_json

    out: list[dict] = []
    page = 1
    while True:
        data = store_rest_json(
            config or {}, "GET", "products/categories",
            params={"per_page": 100, "page": page},
            label="دسته‌بندی‌هایِ سایت (سپیدار)",
        )
        if not isinstance(data, list) or not data:
            break
        for row in data:
            if isinstance(row, dict) and row.get("id"):
                out.append({
                    "id": int(row["id"]),
                    "name": str(row.get("name") or "").strip(),
                    "parent": int(row.get("parent") or 0),
                })
        if len(data) < 100:
            break
        page += 1
    return out


def _sepidar_category_slug(item_group_id) -> str:
    return f"cat-sepidar-{item_group_id}"


def _sepidar_id_from_slug(slug: str) -> int | None:
    slug = (slug or "").strip().lower()
    prefix = "cat-sepidar-"
    if not slug.startswith(prefix):
        return None
    tail = slug[len(prefix):].split("-", 1)[0]  # حذفِ پسوندِ ضدتکراریِ ووکامرس ("-2")
    return int(tail) if tail.isdigit() else None


def _reconcile_sepidar_category_map(config: dict) -> dict[int, int]:
    """{erp_item_group_id: wc_category_id} — نگاشتِ محلی + وضعیتِ زنده‌یِ سایت
    (زنده برنده، دقیقاً هم‌سیاستِ merge_category_map_with_slug_map دژاوو).

    نکته: عمداً از category_resolver.py/category_rules.py استفاده نمی‌شه —
    extract_code_from_wc_slug برایِ اسلاگِ cat-sepidar-N کدِ اشتباه استخراج
    می‌کنه، و category_map.jsonِ دژاوو جهتِ کلید/مقدارش برعکسِ
    sepidar_category_map.jsonه ({wc_id: item_group_id})."""
    from sync_app.core.integrations.commerce_provider import fetch_store_slug_map

    raw = load_sepidar_map(_MAP_FILE)  # {wc_id_str: item_group_id}
    prior_erp_to_wc: dict[int, int] = {}
    for wc_key, erp_val in raw.items():
        try:
            prior_erp_to_wc[int(erp_val)] = int(wc_key)
        except (TypeError, ValueError):
            continue

    erp_to_wc = dict(prior_erp_to_wc)
    try:
        slug_map = fetch_store_slug_map(config, timeout=45)
    except Exception:
        slug_map = {}

    for slug, entry in slug_map.items():
        erp_id = _sepidar_id_from_slug(slug)
        wc_id = entry.get("id") if isinstance(entry, dict) else None
        if erp_id is not None and wc_id:
            erp_to_wc[erp_id] = int(wc_id)

    if erp_to_wc != prior_erp_to_wc:
        save_sepidar_map(_MAP_FILE, {str(wc): erp for erp, wc in erp_to_wc.items()})
    return erp_to_wc


def _heal_sepidar_category_slug(config, wc_id, name: str, slug: str) -> None:
    """اسلاگِ دسته‌یِ موجود (که با تطبیقِ نام پیدا شده) رو به cat-sepidar-N
    برسون تا دفعه‌یِ بعد با slug پیدا بشه — معادلِ محلیِ _heal_slug دژاوو
    (که یک closureِ داخلیه و قابلِ import نیست)."""
    from sync_app.core.integrations.commerce_provider import store_rest_json
    from sync_app.core.sync_utils import log

    try:
        store_rest_json(
            config, "PUT", f"products/categories/{wc_id}",
            json_body={"slug": slug}, label=f"ترمیمِ slugِ دسته‌یِ '{name}'",
        )
    except Exception as exc:
        log.warning(f"⚠️ ترمیمِ slugِ '{name}' (ID:{wc_id}) خطا — از IDِ موجود استفاده می‌شه: {exc}")


def _sepidar_category_payload(title: str, parent_wc_id: int, slug: str) -> dict:
    return {"name": title, "slug": slug, "parent": int(parent_wc_id or 0)}


def _sepidar_group_sync_plan(config: dict, groups: list[dict]) -> tuple[list[str], list[str]]:
    """مجموعه‌یِ گروه‌هایِ لازم برایِ سینک (انتخاب‌شده‌ها + همه‌یِ والدهاشون تا
    ریشه، برایِ اینکه زنجیره‌یِ parent در سایت همیشه معتبر بمونه)، مرتب‌شده
    از کم‌عمق‌ترین به عمیق‌ترین (والد قبل از فرزند) — به‌همراهِ فهرستِ
    زنجیره‌هایِ خراب (چرخه/ارجاعِ ناموجود) که کلاً رد شدن."""
    selected = [str(g).strip() for g in config.get("SEPIDAR_SELECTED_GROUPS", []) if str(g).strip()]
    by_id = {str(g["id"]): g for g in groups}

    to_sync: set[str] = set()
    broken: list[str] = []
    for gid in selected:
        if gid not in by_id:
            continue
        cur, visited, chain = gid, set(), []
        cyclic = False
        while cur in by_id:
            if cur in visited:
                cyclic = True
                break
            visited.add(cur)
            chain.append(cur)
            parent_ref = by_id[cur]["parent_ref"]
            parent_key = str(parent_ref) if parent_ref is not None else None
            if parent_key is None or parent_key == str(_ROOT_PARENT_REF) or parent_key not in by_id:
                break
            cur = parent_key
        if cyclic:
            broken.append(gid)
            continue
        to_sync.update(chain)

    depth_cache: dict[str, int] = {}

    def _depth(gid: str) -> int:
        if gid in depth_cache:
            return depth_cache[gid]
        depth = 0
        cur, seen = gid, {gid}
        while cur in by_id:
            parent_ref = by_id[cur]["parent_ref"]
            parent_key = str(parent_ref) if parent_ref is not None else None
            if parent_key is None or parent_key == str(_ROOT_PARENT_REF) or parent_key not in by_id or parent_key in seen:
                break
            seen.add(parent_key)
            cur = parent_key
            depth += 1
        depth_cache[gid] = depth
        return depth

    ordered = sorted(to_sync, key=_depth)
    return ordered, broken


def sync_categories_from_erp(config: dict | None = None) -> dict:
    """POS.ItemGroup → دسته‌بندیِ سایت. جهتِ درستِ ERP→سایت (مثلِ
    ProductCategoriesSync.main دژاوو). خروجی: {"synced","failed",
    "update_failed","total","broken_groups"} (یا {"disabled": True} اگه
    DISABLE_ERP_CATEGORY_SYNC روشن باشه، یا خروجیِ خالی اگه هیچ گروهی
    انتخاب نشده باشه)."""
    from sync_app.core.integrations.commerce_provider import fetch_store_slug_map, store_rest_json
    from sync_app.core.scripts.ProductCategoriesSync import _norm_cat_name, _term_exists_id
    from sync_app.core.sync_utils import log

    config = config or {}
    if config.get("DISABLE_ERP_CATEGORY_SYNC"):
        return {"synced": 0, "failed": [], "total": 0, "disabled": True}

    if not [str(g).strip() for g in config.get("SEPIDAR_SELECTED_GROUPS", []) if str(g).strip()]:
        return {"synced": 0, "failed": [], "total": 0}

    groups = fetch_sepidar_item_groups(config)
    if not groups:
        log.info("ℹ️ هیچ گروهِ کالایی در سپیدار یافت نشد.")
        return {"synced": 0, "failed": [], "total": 0}
    by_id = {str(g["id"]): g for g in groups}

    ordered, broken = _sepidar_group_sync_plan(config, groups)
    if not ordered:
        return {"synced": 0, "failed": [], "total": 0, "broken_groups": broken}

    erp_to_wc = _reconcile_sepidar_category_map(config)

    name_id_map: dict[str, int] = {}
    try:
        for entry in (fetch_store_slug_map(config, timeout=45) or {}).values():
            nkey = _norm_cat_name(entry.get("name")) if isinstance(entry, dict) else ""
            if nkey and isinstance(entry, dict) and entry.get("id"):
                name_id_map.setdefault(nkey, int(entry["id"]))
    except Exception:
        pass

    synced_ids: set[str] = set()
    failed: list[str] = []
    update_failed: list[str] = []

    for gid in ordered:
        g = by_id[gid]
        title = g["title"] or f"گروه {gid}"
        erp_id_int = int(gid)

        parent_ref = g["parent_ref"]
        parent_key = str(parent_ref) if parent_ref is not None else None
        parent_wc_id = 0
        if parent_key and parent_key != str(_ROOT_PARENT_REF):
            try:
                parent_wc_id = erp_to_wc.get(int(parent_key), 0)
            except (TypeError, ValueError):
                parent_wc_id = 0

        slug = _sepidar_category_slug(gid)
        payload = _sepidar_category_payload(title, parent_wc_id, slug)
        wc_id = erp_to_wc.get(erp_id_int)

        if wc_id:
            try:
                store_rest_json(
                    config, "PUT", f"products/categories/{wc_id}",
                    json_body=payload, label=f"به‌روزرسانیِ دسته‌یِ '{title}'",
                )
                log.info(f"🔄 به‌روزرسانی: '{title}' (ID: {wc_id})")
            except Exception as exc:
                log.warning(f"⚠️ به‌روزرسانیِ '{title}' (ID:{wc_id}) ناموفق — دسته رویِ سایت موجوده: {exc}")
                update_failed.append(title)
            erp_to_wc[erp_id_int] = int(wc_id)
            synced_ids.add(gid)
            continue

        existing_id = name_id_map.get(_norm_cat_name(title))
        if existing_id:
            _heal_sepidar_category_slug(config, existing_id, title, slug)
            log.info(f"🩹 تطبیق با نام و ترمیمِ slug: '{title}' (ID: {existing_id})")
            erp_to_wc[erp_id_int] = int(existing_id)
            synced_ids.add(gid)
            continue

        try:
            response = store_rest_json(
                config, "POST", "products/categories",
                json_body=payload, label=f"ایجادِ دسته‌یِ '{title}'",
            )
            new_id = response.get("id") if isinstance(response, dict) else None
            if new_id:
                log.info(f"➕ ایجاد شد: '{title}' (ID: {new_id})")
                erp_to_wc[erp_id_int] = int(new_id)
                synced_ids.add(gid)
            else:
                exists_id = _term_exists_id(response)
                if exists_id:
                    _heal_sepidar_category_slug(config, exists_id, title, slug)
                    log.info(f"🔁 دسته موجود بود (term_exists) — ID: {exists_id}، slug ترمیم شد")
                    erp_to_wc[erp_id_int] = int(exists_id)
                    synced_ids.add(gid)
                else:
                    error_message = response.get("message", "خطای ناشناخته") if isinstance(response, dict) else str(response)
                    log.error(f"❌ شکست در ایجادِ '{title}': {error_message}")
                    failed.append(title)
        except Exception as exc:
            log.error(f"❌ خطایِ APIِ ایجادِ '{title}': {exc}")
            failed.append(title)

    save_sepidar_map(_MAP_FILE, {str(wc): erp for erp, wc in erp_to_wc.items()})

    log.info(f"✅ دسته‌بندیِ سپیدار (ERP→سایت): {len(synced_ids)} از {len(ordered)} گروه سینک شد.")
    return {
        "synced": len(synced_ids),
        "failed": failed,
        "update_failed": update_failed,
        "total": len(ordered),
        "broken_groups": broken,
    }


def resolve_mapped_item_group_from_index(category_ids: list[int], category_map: dict, by_id: dict) -> int | None:
    """نزدیک‌ترین ItemGroupِ سینک‌شده برایِ یکی از دسته‌هایِ محصول — والدها
    رو بالا می‌ره تا یکی رو تو نگاشت پیدا کنه (برایِ دسته‌هایِ عمیق‌ترِ سایت)."""
    for cat_id in category_ids or []:
        current = cat_id
        depth = 0
        while current and depth < 10:
            key = str(current)
            if key in category_map:
                return int(category_map[key])
            parent = (by_id.get(current) or {}).get("parent")
            current = parent if parent else None
            depth += 1
    return None


def fetch_sepidar_item_groups(config: dict | None = None) -> list[dict]:
    """[{id, code, title, parent_ref}] — گروه/زیرگروه‌هایِ موجود در
    POS.ItemGroup — برایِ نمایشِ سمتِ سپیدار در تبِ «تطبیق» (تبِ محصولات/
    sync_products فقط INSERT دارن، این تابع اولین SELECT از این جدوله)."""
    from sync_app.core.scripts.sepidar.sepidar_common import get_sepidar_connection

    conn = get_sepidar_connection(config or {})
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ItemGroupID, Code, Title, ParentGroupRef FROM POS.ItemGroup")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return [
        {
            "id": int(r[0]),
            "code": str(r[1] or "").strip(),
            "title": str(r[2] or "").strip(),
            "parent_ref": int(r[3]) if r[3] is not None else None,
        }
        for r in rows
    ]


def main(config: dict | None = None) -> dict:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config or load_secure_config(None) or {}
    return sync_categories_from_erp(cfg)


if __name__ == "__main__":
    main()
