"""POS.ItemGroup — گروه/زیرگروهِ کالایِ سپیدار/دشت، از دسته‌بندیِ سایت.

جهتِ سینک: سایت → سپیدار (برعکسِ ProductCategoriesSync.py دژاوو که از
ERP به سایت می‌ره) — در دیپلویمنتِ سپیدار/دشتِ این کاربر، دسته‌بندیِ کالا
رویِ خودِ سایت تعریف می‌شه و باید در سپیدار هم به‌عنوانِ ItemGroup ساخته
بشه تا کالا/فاکتور بتونن بهش وصل بشن.

فقط ۲ سطح (گروه/زیرگروه) ساخته می‌شه — مثلِ M_Group/S_Group دژاوو. دسته‌هایِ
عمیق‌ترِ سایت به نزدیک‌ترین والدِ سینک‌شده نسبت داده می‌شن
(resolve_mapped_item_group_from_index)، بدونِ اینکه خودشون ItemGroupِ
جدا بگیرن.

INSERT دقیقاً مطابقِ ترِیسِ واقعیِ سپیدار (Article_Group.txt /
Article_Sub_Group.txt): ریشه = ParentGroupRef -5، بعدِ هر INSERT جدید
EXEC POS.spUpdateItemGroupHierarchyColumns الزامیه."""

from __future__ import annotations

from sync_app.core.scripts.sepidar.sepidar_common import (
    get_sepidar_connection,
    load_sepidar_map,
    next_int_code,
    next_padded_code,
    save_sepidar_map,
    sepidar_apply_lock,
)

_MAP_FILE = "sepidar_category_map.json"
_ROOT_PARENT_REF = -5  # مطابقِ ترِیسِ واقعی
_CHILD_CODE_LENGTH = 2


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


def _create_item_group(cursor, title: str, parent_ref: int) -> int:
    item_group_id = next_int_code(cursor, "POS.ItemGroup", "ItemGroupID")
    code = next_padded_code(
        cursor, "POS.ItemGroup", "Code", _CHILD_CODE_LENGTH,
        where_sql="ParentGroupRef = ?", params=(parent_ref,),
    )
    cursor.execute(
        """
        INSERT INTO POS.[ItemGroup]
            ([Code], [ChildCodeLength], [HasChild], [ItemGroupID], [Title],
             [ParentGroupRef], [Creator], [CreationDate], [LastModifier], [LastModificationDate], [Version])
        VALUES (?, ?, 0, ?, ?, ?, ?, GETDATE(), ?, GETDATE(), 1)
        """,
        (code, _CHILD_CODE_LENGTH, item_group_id, title or f"گروه {item_group_id}", parent_ref, 1, 1),
    )
    cursor.execute("EXEC POS.spUpdateItemGroupHierarchyColumns ?", (item_group_id,))
    return item_group_id


def sync_categories(config: dict | None = None) -> dict:
    """دسته‌بندیِ سایت → POS.ItemGroup. خروجی: {"created", "existing", "total"}."""
    from sync_app.core.sync_utils import log

    config = config or {}
    site_categories = fetch_site_categories(config)
    if not site_categories:
        log.info("ℹ️ هیچ دسته‌بندیِ کالایی در سایت یافت نشد.")
        return {"created": 0, "existing": 0, "total": 0}

    category_map = load_sepidar_map(_MAP_FILE)
    by_id = {c["id"]: c for c in site_categories}
    created = 0

    conn = get_sepidar_connection(config)
    try:
        cursor = conn.cursor()
        sepidar_apply_lock(cursor, "ItemGroup")

        top_level = [c for c in site_categories if not c["parent"]]
        for cat in top_level:
            key = str(cat["id"])
            if key in category_map:
                continue
            item_group_id = _create_item_group(cursor, cat["name"], _ROOT_PARENT_REF)
            category_map[key] = item_group_id
            created += 1

        sub_level = [
            c for c in site_categories
            if c["parent"] and c["parent"] in by_id and not by_id[c["parent"]]["parent"]
        ]
        for cat in sub_level:
            key = str(cat["id"])
            if key in category_map:
                continue
            parent_item_group = category_map.get(str(cat["parent"]))
            if parent_item_group is None:
                continue
            item_group_id = _create_item_group(cursor, cat["name"], int(parent_item_group))
            category_map[key] = item_group_id
            created += 1

        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error(f"❌ خطا در سینکِ دسته‌بندیِ سپیدار: {exc}")
        raise
    finally:
        conn.close()

    save_sepidar_map(_MAP_FILE, category_map)
    log.info(f"✅ دسته‌بندیِ سپیدار: {created} گروهِ جدید ساخته شد (مجموع نگاشت: {len(category_map)}).")
    return {"created": created, "existing": len(category_map) - created, "total": len(category_map)}


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


def main(config: dict | None = None) -> dict:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config or load_secure_config(None) or {}
    return sync_categories(cfg)


if __name__ == "__main__":
    main()
