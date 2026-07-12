"""قواعد مرکزی دسته‌بندی ERP ↔ WooCommerce — همه سناریوها.

خلاصه:
- کد اصلی = M_Groupcode (۲ رقم)، زیرگروه = M+S (۴ رقم)
- slug Woo = cat-{code}
- محصول SKU → اول ۴ رقم (زیرگروه)، بعد ۲ رقم (گروه)
- ID زنده Woo از slug_map بر map محلی اولویت دارد
- روی محصول: parent + leaf (اگر هر دو موجود)
"""

from __future__ import annotations

from typing import Any

from sync_app.core.category_resolver import (
    build_code_index_from_slug_map,
    dejavu_category_slug,
    extract_code_from_wc_slug,
    load_category_map,
    resolve_wc_category_id,
    save_category_map,
)


def normalize_dejavu_code(code) -> str:
    return str(code or "").strip()


def is_main_group_code(code: str) -> bool:
    code = normalize_dejavu_code(code)
    return len(code) == 2 and code.isdigit()


def is_sub_group_code(code: str) -> bool:
    code = normalize_dejavu_code(code)
    return len(code) == 4 and code.isdigit()


def parent_group_code(code: str) -> str | None:
    code = normalize_dejavu_code(code)
    if is_sub_group_code(code):
        return code[:2]
    return None


def sku_to_category_codes(sku: str) -> list[str]:
    """
    کدهای دسته برای یک SKU — به ترتیب اولویت (دقیق‌تر اول).
    مثال: 0301001 → ['0301', '03']
    """
    sku = normalize_dejavu_code(sku)
    codes: list[str] = []
    if len(sku) >= 4:
        sub = sku[:4]
        if is_sub_group_code(sub):
            codes.append(sub)
    if len(sku) >= 2:
        main = sku[:2]
        if is_main_group_code(main) and main not in codes:
            codes.append(main)
    return codes


def merge_category_map_with_slug_map(category_map: dict | None, slug_map: dict | None) -> dict[str, int]:
    """map محلی + Woo زنده — slug_map برنده (رفع ID قدیمی/stale)."""
    merged: dict[str, int] = {
        normalize_dejavu_code(k): int(v)
        for k, v in (category_map or {}).items()
        if normalize_dejavu_code(k) and v
    }
    for slug, entry in (slug_map or {}).items():
        code = extract_code_from_wc_slug(slug)
        if not code or not isinstance(entry, dict) or not entry.get("id"):
            continue
        merged[normalize_dejavu_code(code)] = int(entry["id"])
    return merged


def prepare_category_context(config, *, fetch_live: bool = True, timeout: int = 45) -> dict[str, Any]:
    """
    آماده‌سازی قبل sync محصول / اعمال دسته:
    - واکشی slug_map از Woo (اختیاری)
    - merge + ذخیره category_map.json اگر IDها عوض شده
    """
    cat_map = load_category_map()
    slug_map: dict = {}
    if fetch_live and config:
        try:
            from sync_app.core.integrations.commerce_provider import fetch_store_slug_map

            slug_map = fetch_store_slug_map(config, timeout=timeout)
        except Exception:
            slug_map = {}

    merged = merge_category_map_with_slug_map(cat_map, slug_map)
    stale: list[str] = []
    for code, old_id in cat_map.items():
        new_id = merged.get(normalize_dejavu_code(code))
        if new_id and int(old_id) != int(new_id):
            stale.append(f"{code}:{old_id}→{new_id}")

    if merged != cat_map:
        save_category_map(merged)

    return {
        "category_map": merged,
        "slug_map": slug_map,
        "stale_updates": stale,
    }


def live_dejavu_codes_in_woo(slug_map: dict | None) -> set[str]:
    """کدهای ERP که الان slug زنده در Woo دارند."""
    codes: set[str] = set()
    for slug in (slug_map or {}):
        code = extract_code_from_wc_slug(str(slug))
        if code:
            codes.add(normalize_dejavu_code(code))
    return codes


def categories_confirmed_on_woo(wanted_codes, slug_map: dict | None) -> bool:
    """همه کدهای خواسته‌شده باید روی Woo دیده شوند — نه فقط map محلی."""
    wanted = {normalize_dejavu_code(c) for c in (wanted_codes or []) if normalize_dejavu_code(c)}
    if not wanted:
        return False
    live = live_dejavu_codes_in_woo(slug_map)
    return wanted.issubset(live)


def resolve_category_id(
    code: str,
    category_map: dict | None = None,
    slug_map: dict | None = None,
) -> int | None:
    return resolve_wc_category_id(code, category_map, slug_map)


def resolve_product_categories(
    sku: str,
    category_map: dict | None = None,
    slug_map: dict | None = None,
    *,
    include_parent: bool = True,
) -> list[dict]:
    """
    payload categories برای PUT/POST محصول Woo.
    leaf = زیرگروه ۴ رقمی SKU؛ fallback گروه ۲ رقمی.
    """
    sku = normalize_dejavu_code(sku)
    if not sku:
        return []

    cat_map = category_map if category_map is not None else load_category_map()
    slug_map = slug_map or {}

    leaf_code = ""
    leaf_id = None
    for code in sku_to_category_codes(sku):
        cid = resolve_wc_category_id(code, cat_map, slug_map)
        if cid:
            leaf_code = code
            leaf_id = int(cid)
            break

    if not leaf_id:
        return []

    out: list[dict] = []
    if include_parent:
        parent_id = None
        if leaf_code and slug_map:
            entry = slug_map.get(dejavu_category_slug(leaf_code))
            if isinstance(entry, dict) and entry.get("parent"):
                parent_id = int(entry["parent"])
        if not parent_id:
            parent_code = parent_group_code(leaf_code) if leaf_code else None
            if parent_code:
                parent_id = resolve_wc_category_id(parent_code, cat_map, slug_map)
        if parent_id and parent_id != leaf_id:
            out.append({"id": int(parent_id)})

    out.append({"id": int(leaf_id)})

    seen: set[int] = set()
    unique: list[dict] = []
    for item in out:
        cid = int(item["id"])
        if cid in seen:
            continue
        seen.add(cid)
        unique.append({"id": cid})
    return unique


def primary_category_id(categories: list[dict]) -> int | None:
    if not categories:
        return None
    return int(categories[-1]["id"])


def explain_category_miss(sku: str, category_map: dict | None, slug_map: dict | None) -> str:
    codes = sku_to_category_codes(sku)
    if not codes:
        return f"SKU {sku} کوتاه است — کد ۴ رقمی زیرگروه لازم است."
    tried = ", ".join(codes)
    slug_hint = ", ".join(dejavu_category_slug(c) for c in codes)
    in_map = [c for c in codes if (category_map or {}).get(c)]
    in_slug = [c for c in codes if slug_map and dejavu_category_slug(c) in slug_map]
    if not in_map and not in_slug:
        return (
            f"دسته برای SKU {sku} پیدا نشد (کدها: {tried}). "
            f"ابتدا تب دسته‌بندی‌ها → همگام‌سازی (slug: {slug_hint})."
        )
    return f"دسته Woo برای {sku} resolve نشد — map/slug را بررسی کنید ({tried})."


def verify_product_categories(wc_product: dict, expected: list[dict]) -> bool:
    """آیا محصول Woo دسته‌های مورد انتظار را دارد؟"""
    if not expected:
        return True
    got_ids = {
        int(c.get("id"))
        for c in (wc_product or {}).get("categories") or []
        if isinstance(c, dict) and c.get("id")
    }
    need_ids = {int(c["id"]) for c in expected if c.get("id")}
    if not need_ids:
        return True
    if need_ids.issubset(got_ids):
        return True
    # Woo معمولاً فقط زیرگروه (leaf) را برمی‌گرداند، نه والد را هم.
    leaf_id = int(expected[-1]["id"])
    return leaf_id in got_ids


def resolve_live_product_categories(
    sku: str,
    slug_map: dict | None,
    *,
    include_parent: bool = True,
) -> tuple[list[dict], str]:
    """
    دسته‌های محصول فقط از دادهٔ زندهٔ Woo (slug_map) — نه map قدیمی.
    خروجی: (لیست {id} برای PUT، کد زیرگروه).
    یک قانون انتخاب واحد (build_code_index) تا resolve و verify هم‌خوان بمانند.
    """
    sku = normalize_dejavu_code(sku)
    code_index = build_code_index_from_slug_map(slug_map or {})
    if not sku or not code_index:
        return [], ""

    leaf_code = ""
    leaf_id = None
    for code in sku_to_category_codes(sku):
        entry = code_index.get(code)
        if isinstance(entry, dict) and entry.get("id"):
            leaf_code = code
            leaf_id = int(entry["id"])
            break
    if not leaf_id:
        return [], ""

    out: list[dict] = []
    if include_parent:
        parent_id = None
        leaf_entry = code_index.get(leaf_code) or {}
        if leaf_entry.get("parent"):
            parent_id = int(leaf_entry["parent"])
        if not parent_id:
            pcode = parent_group_code(leaf_code)
            pentry = code_index.get(pcode) if pcode else None
            if isinstance(pentry, dict) and pentry.get("id"):
                parent_id = int(pentry["id"])
        if parent_id and parent_id != leaf_id:
            out.append({"id": parent_id})

    out.append({"id": leaf_id})
    return out, leaf_code


def _slug_map_id_to_code(slug_map: dict | None) -> dict[int, str]:
    """نگاشت id دستهٔ زنده → کد ERP."""
    id_code: dict[int, str] = {}
    for slug, entry in (slug_map or {}).items():
        code = extract_code_from_wc_slug(str(slug))
        if not code or not isinstance(entry, dict) or not entry.get("id"):
            continue
        try:
            id_code[int(entry["id"])] = normalize_dejavu_code(code)
        except (TypeError, ValueError):
            continue
    return id_code


def verify_categories_by_code(
    wc_product: dict,
    leaf_code: str,
    slug_map: dict | None,
) -> bool:
    """
    آیا محصول کد زیرگروه مورد انتظار را دارد؟ مقایسه بر اساس «کد ERP» نه ID خام،
    تا دسته‌های تکراری Woo (cat-0301 و cat-0301-2) باعث خطای کاذب نشوند.
    """
    leaf_code = normalize_dejavu_code(leaf_code)
    if not leaf_code:
        return False
    id_code = _slug_map_id_to_code(slug_map)
    if not id_code:
        return False
    for c in (wc_product or {}).get("categories") or []:
        if isinstance(c, dict) and c.get("id"):
            try:
                if id_code.get(int(c["id"])) == leaf_code:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def format_category_verify_miss(wc_product: dict, expected: list[dict]) -> str:
    """متن کوتاه برای لاگ وقتی verify شکست خورد."""
    got_ids = sorted(
        int(c.get("id"))
        for c in (wc_product or {}).get("categories") or []
        if isinstance(c, dict) and c.get("id")
    )
    need_ids = sorted(int(c["id"]) for c in (expected or []) if c.get("id"))
    return f"خواستیم {need_ids} — Woo دارد {got_ids or '[]'}"


def sort_categories_for_sync(categories: list[dict]) -> list[dict]:
    """والد قبل از فرزند — برای ساخت درخت Woo."""
    items = list(categories or [])
    mains = [c for c in items if not c.get("parent_dejavu_id")]
    subs = [c for c in items if c.get("parent_dejavu_id")]
    return mains + subs


def product_skus_for_selected_groups(config) -> list[str]:
    """SKUهای Article در زیرگروه‌های انتخاب‌شده."""
    groups = [
        normalize_dejavu_code(g)
        for g in (config or {}).get("SELECTED_SUB_GROUPS", []) or []
        if normalize_dejavu_code(g)
    ]
    if not groups:
        return []

    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sql_connection_helper import open_sql_connection

    cfg = config or load_secure_config(None) or {}
    conn, _, _ = open_sql_connection(cfg, timeout=10)
    cursor = conn.cursor()
    like_clauses = " OR ".join(["A_Code LIKE ?"] * len(groups))
    patterns = [f"{g}%" for g in groups]
    cursor.execute(
        f"SELECT A_Code FROM Article WHERE LEN(A_Code) >= 4 AND ({like_clauses})",
        patterns,
    )
    skus = [normalize_dejavu_code(r[0]) for r in cursor.fetchall() if r and r[0]]
    conn.close()
    return skus
