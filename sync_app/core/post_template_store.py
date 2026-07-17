"""ذخیره‌سازیِ قالب‌های نام‌دارِ پستِ تصویری — تنظیماتِ رنگ/چیدمان/سایز که
با «طراحِ قالب» ساخته شده و قابلِ استفاده‌ی مجدد روی محصولاتِ مختلفه."""

from __future__ import annotations

import uuid

from sync_app.core.post_template_renderer import normalize_template

POST_TEMPLATES_KEY = "POST_TEMPLATES"


def _new_template_id() -> str:
    return uuid.uuid4().hex[:12]


def list_templates(config: dict | None) -> list[dict]:
    raw = (config or {}).get(POST_TEMPLATES_KEY)
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict) and item.get("id"):
            out.append(normalize_template(item))
    return out


def find_template(templates: list[dict], template_id: str) -> dict | None:
    tid = (template_id or "").strip()
    if not tid:
        return None
    for t in templates:
        if str(t.get("id") or "") == tid:
            return t
    return None


def save_template(config: dict, title: str, template_fields: dict, *, template_id: str = "") -> dict:
    """قالبِ جدید می‌سازه یا (اگه template_id موجود باشه) به‌روزش می‌کنه.
    کپیِ جدیدِ config با لیستِ قالب‌های به‌روزشده برمی‌گردونه."""
    cfg = dict(config or {})
    templates = list(list_templates(cfg))
    normalized = normalize_template({**template_fields, "title": (title or "").strip() or "بدون عنوان"})

    tid = (template_id or "").strip()
    if tid and find_template(templates, tid):
        normalized["id"] = tid
        for idx, t in enumerate(templates):
            if str(t.get("id")) == tid:
                templates[idx] = normalized
                break
    else:
        normalized["id"] = tid or _new_template_id()
        templates.append(normalized)

    cfg[POST_TEMPLATES_KEY] = templates
    return cfg


def delete_template(config: dict, template_id: str) -> dict:
    cfg = dict(config or {})
    tid = (template_id or "").strip()
    cfg[POST_TEMPLATES_KEY] = [t for t in list_templates(cfg) if str(t.get("id")) != tid]
    return cfg
