"""مدیریتِ مقالاتِ وردپرس (wp-json/wp/v2/posts) — برایِ سایت‌هایِ ووکامرس
(که رویِ وردپرسن). از همون زیرساختِ Application Password که برایِ آپلودِ
رسانه (wc_sync_helper.py) استفاده می‌شه، دوباره‌استفاده می‌کنه.

⚠️ متا-دیسکریپشن/کلمه‌ی کلیدیِ فوکوس تویِ خودِ وردپرس فیلدِ استانداردی
ندارن — این‌ها بسته به افزونه‌ی سئو (یاست/رنک‌مث/AIOSEO و...) فرق می‌کنن
و این ماژول مستقیم بهشون دسترسی نداره. به‌جاش از فیلدِ استانداردِ
«excerpt» به‌عنوانِ جایگزینِ متا-دیسکریپشن استفاده می‌شه."""

from __future__ import annotations

import requests

from sync_app.core.wc_sync_helper import (
    apply_network_overrides,
    get_wp_media_credentials,
    wc_timeout_pair,
    wp_basic_auth_header,
    wp_media_base_url,
    wp_media_common_headers,
    wp_password_variants,
    wp_requests_verify,
    wp_upload_media_ex,
)


class WpPostsError(RuntimeError):
    pass


def _auth_headers(config, user, pwd):
    from sync_app.core.wc_sync_helper import _wp_media_site_headers

    return wp_media_common_headers({**wp_basic_auth_header(user, pwd), **_wp_media_site_headers(config)})


def _posts_endpoint(config, path: str = "") -> str:
    base = wp_media_base_url(config)
    if not base:
        return ""
    tail = f"/{path.lstrip('/')}" if path else ""
    return f"{base}/wp-json/wp/v2{tail}"


def _request(config, method: str, path: str, *, params=None, json_body=None):
    apply_network_overrides(config)
    user, pwd_raw = get_wp_media_credentials(config)
    if not user or not pwd_raw:
        raise WpPostsError("WP Username یا Application Password خالی است — تنظیمات را کامل کنید.")

    url = _posts_endpoint(config, path)
    if not url:
        raise WpPostsError("WC URL در تنظیمات خالی است.")

    timeout = wc_timeout_pair(config)
    verify = wp_requests_verify(config)
    last_err = None
    for pwd in wp_password_variants(pwd_raw):
        try:
            resp = requests.request(
                method.upper(), url,
                headers=_auth_headers(config, user, pwd),
                params=params, json=json_body,
                timeout=timeout, verify=verify,
            )
        except Exception as e:
            last_err = str(e)
            continue
        if resp.status_code in (401, 403):
            last_err = f"HTTP {resp.status_code}"
            continue
        return resp
    raise WpPostsError(last_err or "اتصال به وردپرس ناموفق بود.")


def _raise_for_status(resp, label: str):
    if 200 <= resp.status_code < 300:
        return
    try:
        data = resp.json()
        msg = data.get("message") or str(data)
    except Exception:
        msg = resp.text[:300]
    raise WpPostsError(f"{label}: HTTP {resp.status_code} — {msg}")


def _post_to_article(row: dict) -> dict:
    title = (row.get("title") or {}).get("rendered") or (row.get("title") or {}).get("raw") or ""
    content = (row.get("content") or {}).get("raw")
    if content is None:
        content = (row.get("content") or {}).get("rendered") or ""
    excerpt = (row.get("excerpt") or {}).get("raw")
    if excerpt is None:
        excerpt = (row.get("excerpt") or {}).get("rendered") or ""
    featured_media = row.get("featured_media") or 0
    embedded = row.get("_embedded") or {}
    featured_url = ""
    media_list = embedded.get("wp:featuredmedia") or []
    if media_list and isinstance(media_list, list):
        featured_url = (media_list[0] or {}).get("source_url") or ""
    return {
        "id": row.get("id"),
        "title": title,
        "content_html": content,
        "excerpt": excerpt,
        "status": row.get("status") or "draft",
        "category_ids": list(row.get("categories") or []),
        "featured_media_id": int(featured_media) if featured_media else None,
        "featured_image_url": featured_url,
        "link": row.get("link") or "",
        "meta_title": title,
        "meta_keywords": "",
        "date": row.get("date") or "",
    }


def list_posts(config, *, page: int = 1, per_page: int = 20, search: str = "") -> tuple[list[dict], int]:
    """برمی‌گردونه (لیستِ مقاله‌ها، تعدادِ کلِ صفحات)."""
    params = {
        "page": page, "per_page": per_page, "status": "publish,draft,pending,private",
        "_embed": 1, "context": "edit", "orderby": "date", "order": "desc",
    }
    if search:
        params["search"] = search
    resp = _request(config, "GET", "posts", params=params)
    _raise_for_status(resp, "دریافتِ لیستِ مقاله‌ها")
    rows = resp.json() or []
    total_pages = int(resp.headers.get("X-WP-TotalPages") or 1)
    return [_post_to_article(r) for r in rows], total_pages


def get_post(config, post_id: int) -> dict:
    resp = _request(config, "GET", f"posts/{int(post_id)}", params={"_embed": 1, "context": "edit"})
    _raise_for_status(resp, "دریافتِ مقاله")
    return _post_to_article(resp.json() or {})


def _build_post_body(article: dict) -> dict:
    body = {
        "title": article.get("title") or "",
        "content": article.get("content_html") or "",
        "status": article.get("status") or "draft",
    }
    if article.get("excerpt") is not None:
        body["excerpt"] = article.get("excerpt") or ""
    if article.get("category_ids"):
        body["categories"] = [int(c) for c in article["category_ids"]]
    if article.get("featured_media_id"):
        body["featured_media"] = int(article["featured_media_id"])
    return body


def create_post(config, article: dict) -> dict:
    resp = _request(config, "POST", "posts", json_body=_build_post_body(article))
    _raise_for_status(resp, "ایجادِ مقاله")
    return _post_to_article(resp.json() or {})


def update_post(config, post_id: int, article: dict) -> dict:
    resp = _request(config, "POST", f"posts/{int(post_id)}", json_body=_build_post_body(article))
    _raise_for_status(resp, "به‌روزرسانیِ مقاله")
    return _post_to_article(resp.json() or {})


def delete_post(config, post_id: int) -> bool:
    resp = _request(config, "DELETE", f"posts/{int(post_id)}", params={"force": "true"})
    _raise_for_status(resp, "حذفِ مقاله")
    return True


def list_categories(config) -> list[dict]:
    resp = _request(config, "GET", "categories", params={"per_page": 100, "orderby": "name", "order": "asc"})
    _raise_for_status(resp, "دریافتِ دسته‌بندی‌هایِ مقاله")
    rows = resp.json() or []
    return [{"id": r.get("id"), "name": r.get("name") or "", "parent": r.get("parent") or 0} for r in rows]


def create_category(config, name: str, parent: int = 0) -> dict:
    body = {"name": name}
    if parent:
        body["parent"] = int(parent)
    resp = _request(config, "POST", "categories", json_body=body)
    _raise_for_status(resp, "ایجادِ دسته‌بندیِ مقاله")
    r = resp.json() or {}
    return {"id": r.get("id"), "name": r.get("name") or "", "parent": r.get("parent") or 0}


def update_category(config, category_id: int, *, name: str | None = None, parent: int | None = None) -> dict:
    body = {}
    if name is not None:
        body["name"] = name
    if parent is not None:
        body["parent"] = int(parent)
    resp = _request(config, "POST", f"categories/{int(category_id)}", json_body=body)
    _raise_for_status(resp, f"به‌روزرسانیِ دسته‌بندی #{category_id}")
    r = resp.json() or {}
    return {"id": r.get("id"), "name": r.get("name") or "", "parent": r.get("parent") or 0}


def delete_category(config, category_id: int) -> bool:
    resp = _request(config, "DELETE", f"categories/{int(category_id)}", params={"force": "true"})
    _raise_for_status(resp, f"حذفِ دسته‌بندی #{category_id}")
    return True


def upload_featured_image(config, image_data: bytes, filename: str) -> tuple[bool, int, str, str]:
    """آپلودِ عکسِ شاخص — از همون آپلودرِ رسانه‌ی موجود استفاده می‌کنه.
    خروجی: (ok, media_id, source_url, error)"""
    return wp_upload_media_ex(config, image_data, filename, fallback_stem="article", label="عکسِ شاخصِ مقاله")
