"""متادیتای تطبیق محصول — جفت‌های دستی و ثبت audit."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sync_app.core.sync_utils import app_path, log

META_FILE = "product_woo_map_meta.json"


def _empty_meta() -> dict:
    return {"links": {}}


def load_product_woo_map_meta() -> dict:
    try:
        with open(app_path(META_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                links = data.get("links")
                if isinstance(links, dict):
                    return {"links": dict(links)}
    except Exception:
        pass
    return _empty_meta()


def save_product_woo_map_meta(meta: dict) -> None:
    try:
        links = (meta or {}).get("links") or {}
        clean = {
            "links": {
                str(k).strip(): v
                for k, v in links.items()
                if isinstance(v, dict) and v.get("wc_id")
            }
        }
        with open(app_path(META_FILE), "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"⚠️ ذخیره {META_FILE}: {exc}")


def get_product_link_meta(erp_sku: str) -> dict | None:
    sku = str(erp_sku or "").strip()
    if not sku:
        return None
    entry = (load_product_woo_map_meta().get("links") or {}).get(sku)
    return dict(entry) if isinstance(entry, dict) else None


def is_manual_product_link(erp_sku: str) -> bool:
    entry = get_product_link_meta(erp_sku)
    return bool(entry and entry.get("manual"))


def register_product_link(
    erp_sku: str,
    wc_id: int,
    *,
    wc_label: str = "",
    manual: bool = False,
    sku_conflict_wc_id: int | None = None,
) -> None:
    sku = str(erp_sku or "").strip()
    wc_id = int(wc_id or 0)
    if not sku or not wc_id:
        return
    meta = load_product_woo_map_meta()
    links = meta.setdefault("links", {})
    links[sku] = {
        "wc_id": wc_id,
        "wc_label": str(wc_label or "").strip(),
        "manual": bool(manual),
        "sku_conflict_wc_id": int(sku_conflict_wc_id) if sku_conflict_wc_id else None,
        "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_product_woo_map_meta(meta)
    kind = "دستی" if manual else "خودکار"
    from sync_app.core.integrations.erp_provider import erp_provider_label
    from sync_app.core.secure_config_loader import load_secure_config

    log.info(f"📌 تطبیق {kind} ثبت شد: {erp_provider_label(load_secure_config(None))} {sku} → Woo #{wc_id}")


def clear_product_link_meta(erp_sku: str) -> None:
    sku = str(erp_sku or "").strip()
    if not sku:
        return
    meta = load_product_woo_map_meta()
    links = meta.get("links") or {}
    if sku in links:
        del links[sku]
        save_product_woo_map_meta(meta)


def clear_product_link_meta_for_wc_id(wc_id: int) -> None:
    wc_id = int(wc_id or 0)
    if not wc_id:
        return
    meta = load_product_woo_map_meta()
    links = meta.get("links") or {}
    to_drop = [k for k, v in links.items() if int((v or {}).get("wc_id") or 0) == wc_id]
    if not to_drop:
        return
    for key in to_drop:
        del links[key]
    save_product_woo_map_meta(meta)
