"""ذخیره‌سازیِ پست‌های زمان‌بندی‌شده‌ی تقویمِ محتوا — یک فایلِ JSON محلی
(مخصوصِ همین پروفایل)، مستقل از secure_config چون این لیست با گذشتِ زمان
بزرگ می‌شه و رکوردهای تاریخی (ارسال‌شده) هم نگه‌داری می‌شن."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sync_app.core.sync_utils import app_path

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

_FILE_NAME = "scheduled_posts.json"


def _store_path() -> str:
    return app_path(_FILE_NAME)


def _new_post_id() -> str:
    return uuid.uuid4().hex[:12]


def load_scheduled_posts() -> list[dict]:
    try:
        with open(_store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_scheduled_posts(posts: list[dict]) -> None:
    with open(_store_path(), "w", encoding="utf-8") as f:
        json.dump(posts or [], f, ensure_ascii=False, indent=2)


def add_scheduled_post(
    *,
    sku: str,
    product_name: str,
    platform: str,
    text: str,
    scheduled_at: str,
    image_path: str = "",
    image_paths: list[str] | None = None,
) -> dict:
    """scheduled_at: ISO 8601 میلادی (مثلاً از datetime.isoformat()).
    image_paths (چند عکس/آلبوم) روی image_path (تکی، برای سازگاری با رکوردهای
    قدیمی) اولویت داره؛ image_path هم برای نمایش/سازگاریِ عقب‌رو نگه داشته می‌شه."""
    paths = [p for p in (image_paths or []) if p]
    post = {
        "id": _new_post_id(),
        "sku": sku,
        "product_name": product_name,
        "platform": platform,
        "text": text,
        "image_path": image_path or (paths[0] if paths else ""),
        "image_paths": paths,
        "scheduled_at": scheduled_at,
        "status": STATUS_PENDING,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sent_at": None,
        "error": None,
    }
    posts = load_scheduled_posts()
    posts.append(post)
    save_scheduled_posts(posts)
    return post


def post_image_paths(post: dict) -> list[str]:
    """همه‌ی مسیرهای عکسِ یک پست — برای رکوردهای قدیمی (فقط image_path) هم کار می‌کنه."""
    paths = [p for p in (post.get("image_paths") or []) if p]
    if paths:
        return paths
    single = str(post.get("image_path") or "").strip()
    return [single] if single else []


def update_post_status(post_id: str, status: str, *, error: str | None = None) -> None:
    posts = load_scheduled_posts()
    changed = False
    for post in posts:
        if str(post.get("id")) == post_id:
            post["status"] = status
            post["error"] = error
            if status == STATUS_SENT:
                post["sent_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
            break
    if changed:
        save_scheduled_posts(posts)


def delete_scheduled_post(post_id: str) -> None:
    posts = load_scheduled_posts()
    posts = [p for p in posts if str(p.get("id")) != post_id]
    save_scheduled_posts(posts)


def due_posts(now: datetime | None = None) -> list[dict]:
    """پست‌هایی که وضعیتشون pending و زمانِ ارسالشون رسیده یا گذشته."""
    now = now or datetime.now()
    out = []
    for post in load_scheduled_posts():
        if post.get("status") != STATUS_PENDING:
            continue
        try:
            scheduled_at = datetime.fromisoformat(str(post.get("scheduled_at") or ""))
        except ValueError:
            continue
        if scheduled_at <= now:
            out.append(post)
    return out
