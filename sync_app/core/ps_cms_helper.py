"""مدیریتِ صفحاتِ محتواییِ پرستاشاپ (CMS pages، منبعِ وب‌سرویسِ
content_management_system) — نزدیک‌ترین معادلِ بومی و پایدارِ «مقاله»
که پرستاشاپِ core (بدونِ ماژولِ خاص) از طریقِ Webservice API پشتیبانی
می‌کنه (برخلافِ ماژولِ Blog که API عمومیِ استانداردی نداره).

⚠️ برخلافِ وردپرس، صفحاتِ CMS پرستاشاپ فیلدِ «تصویرِ شاخص» ندارن —
عکس‌ها باید مستقیم داخلِ محتوا embed بشن (لینک به یه عکسِ از قبل
آپلودشده، چون Webservice پرستاشاپ آپلودِ عکسِ آزاد/عمومی نداره)."""

from __future__ import annotations

import re

from sync_app.core.ps_sync_helper import (
    _build_xml,
    _lang_value,
    _raise_for_status,
    _response_json,
    _response_xml_id,
    _set_lang_text,
    _set_text,
    _unwrap_dict,
    _unwrap_list,
    ps_all_lang_ids,
    ps_call,
    ps_rest_request,
)
from sync_app.core.ps_api_helper import ps_lang_id

PS_DEFAULT_CMS_CATEGORY_ID = 1  # ریشه‌ی «Home» در نصبِ استانداردِ CMS


def _slugify(text: str) -> str:
    ascii_slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "").strip()).strip("-").lower()
    return ascii_slug or "article"


def _cms_to_article(entry: dict, lang_id: int) -> dict:
    active = str(entry.get("active", "1"))
    return {
        "id": int(entry.get("id") or 0),
        "title": _lang_value(entry.get("meta_title"), lang_id),
        "content_html": _lang_value(entry.get("content"), lang_id),
        "excerpt": _lang_value(entry.get("meta_description"), lang_id),
        "status": "publish" if active in ("1", "true") else "draft",
        "category_ids": [int(entry.get("id_cms_category") or 0)] if entry.get("id_cms_category") else [],
        "featured_media_id": None,
        "featured_image_url": "",
        "link": "",
        "meta_title": _lang_value(entry.get("meta_title"), lang_id),
        "meta_keywords": _lang_value(entry.get("meta_keywords"), lang_id),
        "slug": _lang_value(entry.get("link_rewrite"), lang_id),
        "date": "",
    }


def list_posts(config, *, page: int = 1, per_page: int = 20, search: str = "") -> tuple[list[dict], int]:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    offset = (max(page, 1) - 1) * per_page
    params = {"limit": f"{offset},{per_page}", "display": "full"}
    if search:
        params["filter[meta_title]"] = f"%[{search}]%"
    resp = ps_call(
        "دریافتِ لیستِ مقاله‌ها (CMS)",
        lambda: ps_rest_request(cfg, "GET", "content_management_system", params=params),
    )
    data = _response_json(resp, "دریافتِ لیستِ مقاله‌ها (CMS)")
    rows = _unwrap_list(data, "content_management_system")
    articles = [_cms_to_article(r, lang_id) for r in rows if isinstance(r, dict) and r.get("id")]
    # پرستاشاپ توی این نسخه‌ی کلاینت هدرِ تعدادِ کلِ صفحات نمی‌ده — عملاً
    # همیشه صفحه‌ی اول کافیه چون per_page معمولاً کلِ صفحاتِ CMS رو پوشش می‌ده.
    return articles, 1


def get_post(config, article_id: int) -> dict:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        f"دریافتِ مقاله #{article_id}",
        lambda: ps_rest_request(cfg, "GET", f"content_management_system/{int(article_id)}"),
    )
    data = _response_json(resp, f"دریافتِ مقاله #{article_id}")
    entry = _unwrap_dict(data, "content_management_system")
    return _cms_to_article(entry, lang_id)


def _build_cms_xml(article: dict, all_lang_ids, *, existing_id: int | None = None):
    category_ids = article.get("category_ids") or []
    cms_category = int(category_ids[0]) if category_ids else PS_DEFAULT_CMS_CATEGORY_ID
    title = article.get("title") or article.get("meta_title") or ""
    slug = article.get("slug") or _slugify(title)
    active = 1 if (article.get("status") or "draft") == "publish" else 0

    def _build(node):
        if existing_id is not None:
            _set_text(node, "id", int(existing_id))
        _set_text(node, "id_cms_category", cms_category)
        _set_text(node, "position", 1)
        _set_text(node, "indexation", 1)
        _set_text(node, "active", active)
        _set_lang_text(node, "meta_title", title, all_lang_ids)
        _set_lang_text(node, "meta_description", article.get("excerpt") or "", all_lang_ids)
        _set_lang_text(node, "meta_keywords", article.get("meta_keywords") or "", all_lang_ids)
        _set_lang_text(node, "link_rewrite", slug, all_lang_ids)
        _set_lang_text(node, "content", article.get("content_html") or "", all_lang_ids)

    return _build_xml("content", _build)


def create_post(config, article: dict) -> dict:
    cfg = config or {}
    all_lang_ids = ps_all_lang_ids(cfg)
    body = _build_cms_xml(article, all_lang_ids)
    resp = ps_call(
        "ایجادِ مقاله (CMS)",
        lambda: ps_rest_request(cfg, "POST", "content_management_system", xml_body=body),
    )
    new_id = _response_xml_id(resp, "ایجادِ مقاله (CMS)")
    return get_post(cfg, new_id)


def update_post(config, article_id: int, article: dict) -> dict:
    cfg = config or {}
    all_lang_ids = ps_all_lang_ids(cfg)
    body = _build_cms_xml(article, all_lang_ids, existing_id=int(article_id))
    resp = ps_call(
        f"به‌روزرسانیِ مقاله #{article_id}",
        lambda: ps_rest_request(cfg, "PUT", f"content_management_system/{int(article_id)}", xml_body=body),
    )
    _raise_for_status(resp, f"به‌روزرسانیِ مقاله #{article_id}")
    return get_post(cfg, article_id)


def delete_post(config, article_id: int) -> bool:
    cfg = config or {}
    resp = ps_call(
        f"حذفِ مقاله #{article_id}",
        lambda: ps_rest_request(cfg, "DELETE", f"content_management_system/{int(article_id)}"),
    )
    if getattr(resp, "status_code", 0) == 404:
        return True
    _raise_for_status(resp, f"حذفِ مقاله #{article_id}")
    return True


def _cms_category_to_dict(entry: dict, lang_id: int) -> dict:
    return {
        "id": int(entry.get("id") or 0),
        "name": _lang_value(entry.get("name"), lang_id),
        "parent": int(entry.get("id_parent") or 0),
    }


def list_categories(config) -> list[dict]:
    cfg = config or {}
    lang_id = ps_lang_id(cfg)
    resp = ps_call(
        "دریافتِ دسته‌بندی‌هایِ CMS",
        lambda: ps_rest_request(cfg, "GET", "cms_categories", params={"display": "full", "limit": "0,200"}),
    )
    data = _response_json(resp, "دریافتِ دسته‌بندی‌هایِ CMS")
    rows = _unwrap_list(data, "cms_categories")
    return [_cms_category_to_dict(r, lang_id) for r in rows if isinstance(r, dict) and r.get("id")]


def create_category(config, name: str, parent: int = 0) -> dict:
    cfg = config or {}
    all_lang_ids = ps_all_lang_ids(cfg)
    parent_id = int(parent or PS_DEFAULT_CMS_CATEGORY_ID)
    slug = _slugify(name)

    def _build(node):
        _set_text(node, "id_parent", parent_id)
        _set_text(node, "active", 1)
        _set_lang_text(node, "name", name, all_lang_ids)
        _set_lang_text(node, "link_rewrite", slug, all_lang_ids)
        _set_lang_text(node, "meta_title", name, all_lang_ids)

    body = _build_xml("cms_category", _build)
    resp = ps_call(
        f"ایجادِ دسته‌بندیِ CMS '{name}'",
        lambda: ps_rest_request(cfg, "POST", "cms_categories", xml_body=body),
    )
    new_id = _response_xml_id(resp, f"ایجادِ دسته‌بندیِ CMS '{name}'")
    return {"id": new_id, "name": name, "parent": parent_id}
