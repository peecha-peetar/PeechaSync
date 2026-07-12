"""کش attributeهای woo تا هر بار sync دوباره نخونه."""

from __future__ import annotations

import json
import time
from typing import Any

from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

WC_ATTR_CACHE_KEY = "WC_ATTR_CACHE"
WC_PRODUCT_ATTR_FP_KEY = "WC_PRODUCT_ATTR_FP"
DEFAULT_TTL_SEC = 1800


def _now() -> float:
    return time.time()


def _dim_labels_key(dim_labels: list[str]) -> str:
    payload = [str(x or "").strip() for x in (dim_labels or []) if str(x or "").strip()]
    return json.dumps(payload, ensure_ascii=False)


def load_wc_attr_cache(
    dim_labels: list[str] | None = None,
    *,
    size_label: str = "",
    color_label: str = "",
    dim3_label: str = "",
    ttl_sec: int = DEFAULT_TTL_SEC,
) -> tuple[dict | None, dict | None]:
    labels = list(dim_labels or [])
    if not labels and size_label:
        labels = [size_label, color_label]
        if dim3_label:
            labels.append(dim3_label)
    labels = [x for x in labels if x]
    labels_key = _dim_labels_key(labels)
    try:
        cfg = load_secure_config(None) or {}
        raw = cfg.get(WC_ATTR_CACHE_KEY) or {}
        if not isinstance(raw, dict):
            return None, None
        if _now() - float(raw.get("at") or 0) > max(60, int(ttl_sec)):
            return None, None
        if raw.get("dim_labels_key") != labels_key:
            return None, None
        global_ids = raw.get("global_ids")
        term_lookup = raw.get("term_lookup")
        if isinstance(global_ids, dict) and isinstance(term_lookup, dict):
            return global_ids, term_lookup
    except Exception:
        pass
    return None, None


def save_wc_attr_cache(
    global_ids: dict,
    term_lookup: dict,
    dim_labels: list[str] | None = None,
    *,
    size_label: str = "",
    color_label: str = "",
    dim3_label: str = "",
) -> None:
    labels = list(dim_labels or [])
    if not labels and size_label:
        labels = [size_label, color_label]
        if dim3_label:
            labels.append(dim3_label)
    labels = [x for x in labels if x]
    try:
        cfg = load_secure_config(None) or {}
        cfg[WC_ATTR_CACHE_KEY] = {
            "at": _now(),
            "dim_labels_key": _dim_labels_key(labels),
            "global_ids": global_ids,
            "term_lookup": term_lookup,
        }
        save_secure_config(cfg)
    except Exception:
        pass


def attrs_fingerprint(attr_map: dict) -> str:
    payload = sorted(
        (str(k), sorted(str(x) for x in (v or [])))
        for k, v in (attr_map or {}).items()
    )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def load_product_attrs_fingerprint(product_id: int) -> str | None:
    try:
        cfg = load_secure_config(None) or {}
        fps = cfg.get(WC_PRODUCT_ATTR_FP_KEY) or {}
        if isinstance(fps, dict):
            return fps.get(str(int(product_id)))
    except Exception:
        pass
    return None


def save_product_attrs_fingerprint(product_id: int, fingerprint: str) -> None:
    try:
        cfg = load_secure_config(None) or {}
        fps = dict(cfg.get(WC_PRODUCT_ATTR_FP_KEY) or {})
        fps[str(int(product_id))] = str(fingerprint or "")
        cfg[WC_PRODUCT_ATTR_FP_KEY] = fps
        save_secure_config(cfg)
    except Exception:
        pass
