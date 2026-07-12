"""موضوعات و helperهای مشترک برای فیلتر و نمایش sync.log."""

from __future__ import annotations

import os
import re
from typing import Iterable

from sync_app.core.sync_utils import app_path

LOG_TOPIC_CHOICES: tuple[tuple[str, str], ...] = (
    ("همه موضوعات", "all"),
    ("تطبیق", "reconciliation"),
    ("سفارشات", "orders"),
    ("مشتریان", "customers"),
    ("محصولات", "products"),
    ("متغیرها", "variations"),
    ("دسته‌بندی‌ها", "categories"),
    ("ویژگی‌ها", "properties"),
    ("آپدیت خودکار", "auto_sync"),
    ("تنظیمات", "settings"),
    ("اتصال / شبکه", "connectivity"),
    ("بکاپ / ایمنی", "backup"),
    ("ورود / لایسنس", "login"),
    ("سیستم", "system"),
    ("خطاها", "errors"),
)

LOG_TOPIC_ALIASES: dict[str, str] = {
    "orders": "orders",
    "order": "orders",
    "customers": "customers",
    "customer": "customers",
    "products": "products",
    "product": "products",
    "categories": "categories",
    "category": "categories",
    "properties": "properties",
    "property": "properties",
    "variations": "variations",
    "variation": "variations",
    "settings": "settings",
    "auto_sync": "auto_sync",
    "reconciliation": "reconciliation",
    "recon": "reconciliation",
    "connectivity": "connectivity",
    "backup": "backup",
    "login": "login",
    "license": "login",
    "system": "system",
}

LOG_TOPIC_TOKEN_MAP: dict[str, tuple[str, ...]] = {
    "reconciliation": (
        "reconciliation",
        "reconcil",
        "تطبیق",
        "نگاشت",
        "link_manual",
        "auto_link",
        "product_woo_map",
        "category_map",
        "بارگذاری مقایسه",
        "ثبت نهایی",
        "لغو تطبیق",
        "مقایسه",
    ),
    "orders": ("order", "ordersync", "سفارش"),
    "customers": ("customer", "customersync", "مشتری"),
    "products": ("product", "sync_fullproduct", "محصول", "ارسال محصول"),
    "variations": ("variation", "update_variations", "متغیر", "واریانت"),
    "categories": ("category", "productcategoriessync", "دسته", "category_map"),
    "properties": ("poshakproperties", "attribute", "ویژگی"),
    "settings": ("config", "setting", "تنظیم", "profile", "پروفایل"),
    "auto_sync": (
        "auto_sync",
        "آپدیت خودکار",
        "productcategoriessync",
        "poshakproperties",
        "sync_fullproduct",
        "update_variations",
        "customersync",
        "ordersync",
        "همگام‌سازی آغاز",
    ),
    "connectivity": (
        "connectivity",
        "اتصال",
        "sql server",
        "woocommerce",
        "ووکامرس",
        "check_sql",
        "check_wc",
    ),
    "backup": ("backup", "بکاپ", "live_site", "live site"),
    "login": ("login", "signin", "ورود", "auth", "license", "لایسنس", "فعال‌سازی"),
    "system": (
        "system",
        "single_instance",
        "launcher",
        "messagebox",
        "startup",
        "restore",
    ),
}

_LEVEL_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*-\s*([A-Z]+)\s*-"
)
_STRUCTURED_TOPIC_RE = re.compile(
    r"-\s*SYSTEM\s*-\s*\[([a-zA-Z_]+)\]"
)


def get_sync_log_path() -> str:
    return app_path("sync.log")


def iter_sync_log_paths() -> list[str]:
    """فایل فعلی + rotate شده‌ها (قدیمی → جدید)."""
    candidates = [app_path("sync.log.2"), app_path("sync.log.1"), app_path("sync.log")]
    return [path for path in candidates if os.path.isfile(path)]


def read_sync_log_lines() -> list[str]:
    lines: list[str] = []
    for path in iter_sync_log_paths():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                lines.extend(handle.readlines())
        except OSError:
            continue
    return lines


def extract_log_level(raw_line: str) -> str:
    match = _LEVEL_PREFIX_RE.match(raw_line)
    if match:
        return match.group(1).lower()
    low = raw_line.lower()
    if " error " in low or "❌" in raw_line:
        return "error"
    if " warning " in low or "⚠️" in raw_line:
        return "warning"
    return "info"


def extract_structured_topic(raw_line: str) -> str:
    match = _STRUCTURED_TOPIC_RE.search(raw_line)
    if match:
        return match.group(1).strip().lower()
    return ""


def line_matches_topic(raw_line: str, topic: str) -> bool:
    if topic == "all":
        return True
    if topic == "errors":
        return extract_log_level(raw_line) == "error"

    structured = extract_structured_topic(raw_line)
    if structured:
        normalized = LOG_TOPIC_ALIASES.get(structured, structured)
        return normalized == topic

    tokens = LOG_TOPIC_TOKEN_MAP.get(topic, ())
    line_lower = raw_line.lower()
    return any(token.lower() in line_lower for token in tokens)


def filter_log_lines(
    lines: Iterable[str],
    *,
    from_date,
    to_date,
    topic: str = "all",
    level: str = "all",
    text_filter: str = "",
) -> list[str]:
    from datetime import datetime

    text_filter = (text_filter or "").strip().lower()
    out: list[str] = []

    for line in lines:
        date_ok = True
        try:
            dt = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
            date_ok = from_date <= dt.date() <= to_date
        except Exception:
            date_ok = True
        if not date_ok:
            continue

        if level != "all" and extract_log_level(line) != level:
            continue
        if not line_matches_topic(line, topic):
            continue
        if text_filter and text_filter not in line.lower():
            continue
        out.append(line)

    return out


def clear_all_sync_logs() -> int:
    cleared = 0
    log_dir = os.path.dirname(get_sync_log_path()) or "."
    paths: set[str] = set()
    if os.path.isdir(log_dir):
        for name in os.listdir(log_dir):
            if name == "sync.log" or name.startswith("sync.log."):
                paths.add(os.path.join(log_dir, name))
    for path in sorted(paths):
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("")
            cleared += 1
        except OSError:
            continue
    return cleared
