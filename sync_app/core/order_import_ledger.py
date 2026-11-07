"""دفترِ سفارش‌هایِ واردشده به ERP — به‌ازایِ هر سایت جدا.

مشکل: ERP فقط «شماره‌یِ سفارشِ سایت» رو نگه می‌داره (RqIndex2 در دژاوو،
کلیدِ sepidar_order_map.json در سپیدار). بعد از ریستِ سایت (یا وصل‌شدنِ
یک سایتِ دیگه به همون ERP) شماره‌ها از اول شروع می‌شن، پس سفارشِ تازه‌یِ
#۵ با سفارشِ قدیمیِ #۵ یکی گرفته می‌شد: «قبلاً ثبت شده — رد شد» و حتی
رویِ سایت «تکمیل‌شده» می‌شد، بدونِ اینکه هیچ‌وقت به ERP برسه.

این‌جا برایِ هر سفارشِ واردشده یک اثرِ انگشتِ تغییرناپذیر (order_key
ووکامرس / reference پرستاشاپ / تاریخِ ساخت) ثبت می‌شه تا «همون سفارش» از
«سفارشِ دیگه با همون شماره» قابلِ‌تشخیص باشه.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

LEDGER_FILE = "imported_orders_ledger.json"  # {order_id: {"fp": str, "at": iso}}

SAME = "same"
DIFFERENT = "different"
UNKNOWN = "unknown"


def _path() -> str:
    from sync_app.core.sync_utils import site_scoped_path

    return site_scoped_path(LEDGER_FILE)


def _load() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception as exc:
        from sync_app.core.sync_utils import log

        log.warning(f"⚠️ ذخیره {LEDGER_FILE}: {exc}")


def order_fingerprint(order: dict) -> str:
    order = order or {}
    for key in ("order_key", "reference"):
        value = str(order.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    created = str(order.get("date_created_gmt") or order.get("date_created") or "").strip()
    return f"date:{created}" if created else ""


def ledger_verdict(order_id, order: dict) -> str:
    """same: همون سفارشیه که قبلاً وارد شده | different: شماره تکراریه ولی
    سفارشِ دیگه‌ای‌ست | unknown: اثرِ انگشتی ثبت نشده (دادهٔ قبل از این نسخه)."""
    entry = _load().get(str(order_id))
    fp = order_fingerprint(order)
    if not isinstance(entry, dict) or not entry.get("fp") or not fp:
        return UNKNOWN
    return SAME if entry["fp"] == fp else DIFFERENT


def record_imported_order(order_id, order: dict) -> None:
    fp = order_fingerprint(order)
    if not fp or not str(order_id or "").strip():
        return
    data = _load()
    data[str(order_id)] = {"fp": fp, "at": datetime.now().isoformat(timespec="seconds")}
    _save(data)


def _parse_dt(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "").replace(" ", "T")).replace(tzinfo=None)
    except ValueError:
        return None


def erp_row_predates_order(erp_inserted_at, order: dict, *, margin_hours: int = 12) -> bool:
    """برایِ داده‌یِ قدیمیِ بدونِ اثرِ انگشت: ردیفِ ERP (زمانِ ثبت) خیلی قبل
    از ساختِ این سفارش رویِ سایت ثبت شده؟ یک سفارش نمی‌تونه قبل از به‌وجوداومدنش
    وارد ERP شده باشه — پس اون ردیف مالِ یک سفارشِ دیگه با همین شماره بوده.
    حاشیه‌یِ ۱۲ ساعته اختلافِ ساعتِ سرورِ SQL و سایت رو پوشش می‌ده."""
    erp_dt = _parse_dt(erp_inserted_at)
    order_dt = _parse_dt((order or {}).get("date_created") or (order or {}).get("date_created_gmt"))
    if not erp_dt or not order_dt:
        return False
    return erp_dt < order_dt - timedelta(hours=margin_hours)
