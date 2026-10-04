"""تاریخچهٔ سادهٔ همگام‌سازیِ هر آیتم (دسته‌بندی/ویژگی/متغیر/محصول) —
هر بار که یک آیتم واقعاً با موفقیت سینک می‌شه (نه هر بار که فقط بررسی
می‌شه و بدونِ تغییر رد می‌شه)، یک رویدادِ ساده با نام + زمان ثبت می‌شه.

هدف: جایگزینِ خواندنِ لاگِ خام و پیچیده با یک گزارشِ تمیزِ «چه‌کسی،
کِی» برایِ هر بخش — جداگانه، قابلِ‌فیلتر بر اساسِ تاریخ، و قابلِ‌پرینت."""

from __future__ import annotations

import datetime
import json
import os
import time

from sync_app.core.sync_utils import log, site_scoped_path

_MAX_EVENTS_PER_ENTITY = 20000

_ENTITY_FILES = {
    "category": "sync_history_category.jsonl",
    "attribute": "sync_history_attribute.jsonl",
    "variation": "sync_history_variation.jsonl",
    "product": "sync_history_product.jsonl",
}

ENTITY_LABELS = {
    "category": "دسته‌بندی",
    "attribute": "ویژگی",
    "variation": "متغیر",
    "product": "محصول",
}


def record_sync_event(entity_type: str, name: str, *, code: str = "") -> None:
    """یک رویدادِ سینکِ موفق را append می‌کند — هیچ‌وقت نباید جریانِ سینکِ
    اصلی را بشکند، پس هر خطایی بی‌صدا نادیده گرفته می‌شود."""
    fn = _ENTITY_FILES.get(entity_type)
    name = str(name or "").strip()
    if not fn or not name:
        return
    try:
        path = site_scoped_path(fn)
        event = {"name": name, "code": str(code or "").strip(), "ts": time.time()}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        _maybe_prune(path)
    except Exception as exc:
        log.warning(f"⚠️ ثبتِ تاریخچهٔ همگام‌سازی ({entity_type}) ناموفق: {exc}")


def _maybe_prune(path: str) -> None:
    """اگر تعدادِ خط‌ها از سقف رد شد، قدیمی‌ترین‌ها حذف می‌شوند — جلویِ
    رشدِ بی‌نهایتِ فایل را می‌گیرد."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > _MAX_EVENTS_PER_ENTITY:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-_MAX_EVENTS_PER_ENTITY:])
    except Exception:
        pass


def query_sync_history(
    entity_type: str, *, date_from: datetime.date | None = None, date_to: datetime.date | None = None
) -> list[dict]:
    """[{"name", "code", "ts"}, ...] مرتب‌شده از جدیدترین به قدیمی‌ترین —
    date_from/date_to از نوعِ datetime.date (میلادی) یا None (بدونِ محدودیت)."""
    fn = _ENTITY_FILES.get(entity_type)
    if not fn:
        return []
    path = site_scoped_path(fn)
    if not os.path.exists(path):
        return []

    ts_from = (
        datetime.datetime.combine(date_from, datetime.time.min).timestamp()
        if date_from is not None else None
    )
    ts_to = (
        datetime.datetime.combine(date_to, datetime.time.max).timestamp()
        if date_to is not None else None
    )

    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                ts = event.get("ts")
                if not isinstance(ts, (int, float)):
                    continue
                if ts_from is not None and ts < ts_from:
                    continue
                if ts_to is not None and ts > ts_to:
                    continue
                out.append(event)
    except Exception:
        return out

    out.sort(key=lambda e: e.get("ts") or 0, reverse=True)
    return out
