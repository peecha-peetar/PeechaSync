""" کد دسته دژاوو ↔ ووکامرس """

from __future__ import annotations

import json
import re
from urllib.parse import unquote

try:
    from sync_app.core.sync_utils import site_scoped_path
except ImportError:
    import os

    def site_scoped_path(name):
        return os.path.join(os.getcwd(), name)


def dejavu_category_slug(dejavu_id: str) -> str:
    """ slug بدون فارسی """
    code = str(dejavu_id or "").strip()
    return f"cat-{code}" if code else "cat-unknown"


def extract_code_from_wc_slug(slug: str) -> str | None:
    """ کد ERP از slug ووکامرس """
    slug = unquote((slug or "").strip().lower())
    if slug.startswith("cat-"):
        tail = slug[4:].strip()
        if not tail:
            return None
        # Woo برای slug تکراری پسوند -2/-3 می‌زند؛ کد اصلی قبل از آن است
        head = tail.split("-", 1)[0]
        if head.isdigit():
            return head
        return tail
    match = re.search(r"-(\d+)$", slug)
    return match.group(1) if match else None


def load_category_map() -> dict:
    path = site_scoped_path("category_map.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {str(k): int(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_category_map(category_map: dict) -> None:
    try:
        from sync_app.core.sync_utils import log

        clean = {str(k).strip(): int(v) for k, v in (category_map or {}).items() if v}
        with open(site_scoped_path("category_map.json"), "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        try:
            from sync_app.core.sync_utils import log

            log.warning(f"⚠️ ذخیره category_map.json: {exc}")
        except Exception:
            pass


def build_code_index_from_slug_map(slug_map: dict) -> dict:
    """ کد به {id, name, slug} از slug_map """
    index = {}
    for slug, entry in (slug_map or {}).items():
        code = extract_code_from_wc_slug(slug)
        if not code or not isinstance(entry, dict):
            continue
        # چند slug یک کد؛ id معتبر بمونه
        if code not in index or entry.get("id"):
            index[code] = entry
    return index


def live_category_ids(slug_map: dict | None) -> set[int]:
    """ id دسته‌هایی که الان واقعاً روی Woo هستند (از slug_map زنده) """
    ids: set[int] = set()
    for entry in (slug_map or {}).values():
        if isinstance(entry, dict) and entry.get("id"):
            try:
                ids.add(int(entry["id"]))
            except (TypeError, ValueError):
                continue
    return ids


def _wc_id_from_slug_map(code: str, slug_map: dict) -> int | None:
    expected = dejavu_category_slug(code)
    entry = slug_map.get(expected)
    if isinstance(entry, dict) and entry.get("id"):
        return int(entry["id"])
    for slug, item in slug_map.items():
        if extract_code_from_wc_slug(slug) == code and isinstance(item, dict) and item.get("id"):
            return int(item["id"])
    return None


def resolve_wc_category_id(full_code, category_map=None, slug_map=None) -> int | None:
    """ id دسته ووکامرس از کد ERP """
    code = str(full_code or "").strip()
    if not code:
        return None

    category_map = category_map if category_map is not None else load_category_map()
    slug_map = slug_map or {}

    # slug_map از API جدیدتر از category_map.json است
    if slug_map:
        live_id = _wc_id_from_slug_map(code, slug_map)
        if live_id:
            return live_id

    wc_id = category_map.get(code)
    if wc_id:
        return int(wc_id)
    return None


def resolve_product_wc_categories(
    sku,
    category_map=None,
    slug_map=None,
    *,
    include_parent: bool = True,
) -> list[dict]:
    from sync_app.core.category_rules import resolve_product_categories

    return resolve_product_categories(
        sku,
        category_map,
        slug_map,
        include_parent=include_parent,
    )


def fetch_wc_slug_map(config, timeout=60, cancel_check=None) -> dict:
    """ همه دسته‌ها؛ slug به metadata """
    from sync_app.core.wc_sync_helper import wc_rest_json

    all_cats = []
    page = 1
    while True:
        if cancel_check:
            cancel_check()
        batch = wc_rest_json(
            config,
            "GET",
            "products/categories",
            params={"per_page": 100, "page": page},
            label=f"واکشی categories صفحه {page}",
            timeout=timeout if isinstance(timeout, (int, float)) else None,
        )
        if not batch:
            break
        all_cats.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    slug_map = {}
    for cat in all_cats:
        slug = unquote((cat.get("slug") or "").strip().lower())
        if not slug:
            continue
        slug_map[slug] = {
            "id": cat.get("id"),
            "name": cat.get("name", ""),
            "slug": slug,
            "parent": cat.get("parent", 0),
        }
    return slug_map
