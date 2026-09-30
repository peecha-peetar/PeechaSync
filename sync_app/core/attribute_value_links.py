"""لینکِ دستیِ مقدارهایِ ویژگی بینِ نرم‌افزار (ERP) و فروشگاه.

وقتی مقدارِ یک ویژگی در دیتابیس و سایت هم‌معنی ولی هم‌نویسه نیستن (مثلاً
ERP «سرخ»، سایت «قرمز» یا «Red»)، تطبیقِ خودکار — که فقط تطبیقِ دقیقِ
متنی انجام می‌ده — این دو رو یکی تشخیص نمی‌ده: یا یک termِ تکراریِ جدید
با املایِ ERP ساخته می‌شه، یا (در مسیرِ سینکِ ویژگی‌ها) یک termِ کاملاً
نامرتبط بر اساسِ شباهتِ فازی به‌اشتباه rename می‌شه.

این ماژول یک نگاشتِ دستیِ ساده و site-scoped نگه می‌داره:
«این مقدارِ ERP دقیقاً همون این termِ سایته» — از اون به بعد، همه‌جایی که
مقدارِ یک واریانت یا یک term از ERP خونده می‌شه، اول از این نگاشت عبور
می‌کنه."""

from __future__ import annotations

import json
import os

from sync_app.core.sync_utils import log, site_scoped_path

_FILE = "attribute_value_links.json"

_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def _key(text) -> str:
    """کلیدِ نرمال برایِ مقایسه — همون الگویِ _match_key در Poshakproperties.py."""
    from sync_app.core.scripts.Poshakproperties import normalize_text

    return normalize_text(text).translate(_DIGITS).casefold()


def load_value_links() -> dict:
    """{attr_key: {erp_value_key: {"erp_label": str, "wc_label": str}}}"""
    try:
        path = site_scoped_path(_FILE)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_value_links(links: dict) -> None:
    try:
        path = site_scoped_path(_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(links or {}, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"⚠️ ذخیره attribute_value_links.json ناموفق: {exc}")


def set_value_link(attr_label: str, erp_value_label: str, wc_value_label: str) -> None:
    """ERPِ «attr_label: erp_value_label» را به termِ سایتِ «wc_value_label» گره می‌زند."""
    attr_key = _key(attr_label)
    erp_key = _key(erp_value_label)
    wc_label = str(wc_value_label or "").strip()
    if not attr_key or not erp_key or not wc_label:
        return
    links = load_value_links()
    links.setdefault(attr_key, {})[erp_key] = {
        "erp_label": str(erp_value_label or "").strip(),
        "wc_label": wc_label,
    }
    save_value_links(links)


def remove_value_link(attr_label: str, erp_value_label: str) -> None:
    attr_key = _key(attr_label)
    erp_key = _key(erp_value_label)
    links = load_value_links()
    bucket = links.get(attr_key)
    if bucket and erp_key in bucket:
        del bucket[erp_key]
        if not bucket:
            del links[attr_key]
        save_value_links(links)


def list_value_links_for_attr(attr_label: str) -> dict:
    links = load_value_links()
    return dict(links.get(_key(attr_label), {}))


def resolve_value_link(links: dict, attr_label: str, erp_value_label: str) -> str:
    """اگه لینکِ دستی موجود باشه نامِ termِ سایت رو برمی‌گردونه، وگرنه
    همون مقدارِ ERP خام رو بدونِ تغییر (تا بقیه‌یِ pipeline مثلِ قبل کار کنه)."""
    if not links:
        return erp_value_label
    entry = (links.get(_key(attr_label)) or {}).get(_key(erp_value_label))
    if entry and entry.get("wc_label"):
        return entry["wc_label"]
    return erp_value_label
