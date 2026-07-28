"""بازنویسیِ دستیِ دسته‌بندیِ محصول — وقتی سایت از قبل ساختارِ دسته‌بندیِ
خودش رو داره (فرق با دسته‌بندیِ ERP)، می‌شه هر محصول رو مستقیم به یک یا
چند دسته‌یِ واقعیِ سایت وصل کرد. این override رویِ منطقِ خودکارِ
resolve_product_categories اولویت داره و در سینک‌هایِ بعدی هم دست‌نخورده
می‌مونه، مگر خودِ کاربر دوباره تغییرش بده یا حذفش کنه.

فایل site-scoped ذخیره می‌شه (نه فقط per-profile) چون idِ دسته‌بندی مالِ
یک سایتِ مشخصه — همون idِ عددی رویِ سایتِ دیگه (حتی با همون پلتفرم) کاملاً
بی‌ربطه."""

from __future__ import annotations

import json

OVERRIDE_FILE = "product_category_override.json"


def _path() -> str:
    from sync_app.core.sync_utils import site_scoped_path

    return site_scoped_path(OVERRIDE_FILE)


def load_category_overrides() -> dict[str, list[int]]:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {
                    str(k).strip(): [int(i) for i in (v or []) if str(i).strip()]
                    for k, v in data.items()
                }
    except Exception:
        pass
    return {}


def save_category_overrides(overrides: dict) -> None:
    try:
        clean = {
            str(k).strip(): sorted({int(i) for i in (v or []) if str(i).strip()})
            for k, v in (overrides or {}).items()
            if v
        }
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        try:
            from sync_app.core.sync_utils import log

            log.warning(f"⚠️ ذخیره {OVERRIDE_FILE}: {exc}")
        except Exception:
            pass


def get_manual_category_ids(sku: str) -> list[int] | None:
    """اگه این SKU دستی به دسته‌ی(هایِ) سایت وصل شده، همون idها رو
    برمی‌گردونه؛ وگرنه None (یعنی از منطقِ خودکارِ ERP→دسته‌بندی استفاده
    بشه — همون رفتارِ فعلی)."""
    sku = str(sku or "").strip()
    if not sku:
        return None
    ids = load_category_overrides().get(sku)
    return list(ids) if ids else None


def set_manual_category_ids(sku: str, category_ids: list[int] | None) -> None:
    """category_ids=None یا [] یعنی حذفِ override — دوباره از منطقِ
    خودکارِ (ERP→دسته‌بندیِ سایت) استفاده می‌شه."""
    sku = str(sku or "").strip()
    if not sku:
        return
    overrides = load_category_overrides()
    if category_ids:
        overrides[sku] = [int(i) for i in category_ids]
    else:
        overrides.pop(sku, None)
    save_category_overrides(overrides)


def is_manual_category_override(sku: str) -> bool:
    return get_manual_category_ids(sku) is not None
