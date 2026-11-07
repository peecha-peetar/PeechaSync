"""کدِ دستیِ کالا (Article.A_Code_C دژاوو/هلو) — برایِ نمایش کنارِ کدِ اتوماتیک.

در همه‌یِ تب‌ها کدِ اتوماتیک (A_Code) نمایش داده می‌شد؛ این ماژول نگاشتِ
«کدِ اتوماتیک → کدِ دستی» رو یک‌بار از دیتابیس می‌خونه و چند دقیقه کش
می‌کنه تا هر تب بتونه بدونِ کوئریِ اضافه کدِ دستی رو هم کنارش نشون بده.

سپیدار/دشت جدولِ Article ندارن و «کدِ کالا»یِ اونا (POS.Item.Code) خودش
همون کدیه که کاربر وارد می‌کنه — پس برایِ اونا نگاشت خالیه.
"""

from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_CACHE: dict = {"key": None, "at": 0.0, "map": {}}
_MAX_AGE = 300.0


def _cache_key(config: dict | None) -> tuple:
    cfg = config or {}
    return (
        str(cfg.get("SQL_SERVER") or cfg.get("SQL_HOST") or "").strip().lower(),
        str(cfg.get("SQL_DATABASE") or cfg.get("SQL_DB") or "").strip().lower(),
    )


def is_manual_code_supported(config: dict | None) -> bool:
    try:
        from sync_app.core.scripts.sepidar.sepidar_common import is_sepidar_provider

        return not is_sepidar_provider(config or {})
    except Exception:
        return True


def fetch_manual_codes(cursor) -> dict[str, str]:
    """{A_Code: A_Code_C} فقط برایِ کالاهایی که کدِ دستی دارن."""
    try:
        cursor.execute("SELECT A_Code, A_Code_C FROM Article")
        rows = cursor.fetchall()
    except Exception:
        return {}
    out: dict[str, str] = {}
    for row in rows or []:
        code = str(row[0] or "").strip()
        manual = str(row[1] or "").strip() if len(row) > 1 else ""
        if code and manual:
            out[code] = manual
    return out


def _store(config: dict | None, mapping: dict[str, str]) -> None:
    with _LOCK:
        _CACHE["key"] = _cache_key(config)
        _CACHE["at"] = time.monotonic()
        _CACHE["map"] = dict(mapping)


def load_manual_codes(config: dict | None, *, cursor=None, max_age: float = _MAX_AGE) -> dict[str, str]:
    """نگاشتِ کش‌شده؛ اگه کهنه بود (یا cursor داده شد) از دیتابیس تازه می‌شه.

    هیچ‌وقت خطا نمی‌ده — در بدترین حالت {} برمی‌گردونه (نمایشِ کدِ دستی
    هیچ‌وقت نباید جلویِ بارگذاریِ یک تب رو بگیره)."""
    if not is_manual_code_supported(config):
        return {}
    key = _cache_key(config)
    with _LOCK:
        fresh = _CACHE["key"] == key and (time.monotonic() - _CACHE["at"]) < max_age
        if fresh and cursor is None:
            return dict(_CACHE["map"])
    if cursor is not None:
        mapping = fetch_manual_codes(cursor)
        _store(config, mapping)
        return mapping
    try:
        from sync_app.core.sql_connection_helper import open_sql_connection
    except Exception:
        return {}
    try:
        conn, _, _ = open_sql_connection(config or {}, timeout=3)
    except Exception:
        _store(config, {})  # تا چند دقیقه دوباره برایِ دیتابیسِ قطع تلاش نکن
        return {}
    try:
        mapping = fetch_manual_codes(conn.cursor())
    finally:
        try:
            conn.close()
        except Exception:
            pass
    _store(config, mapping)
    return mapping


def cached_manual_codes() -> dict[str, str]:
    """فقط کش — بدونِ دسترسی به دیتابیس (برایِ نخِ رابط کاربری)."""
    with _LOCK:
        return dict(_CACHE["map"])


def manual_code_text(manual: str | None) -> str:
    return str(manual or "").strip() or "—"


def codes_label(code: str, manual: str | None) -> str:
    """«کد: X | کد دستی: Y» — کدِ اتوماتیک دست نمی‌خوره، کدِ دستی کنارش میاد."""
    return f"کد: {code} | کد دستی: {manual_code_text(manual)}"
