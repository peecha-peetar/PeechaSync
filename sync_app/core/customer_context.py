""" مشتری پیش‌فرض سفارش/sync """

from __future__ import annotations


def get_customer_mode(config):
    mode = (config or {}).get("DEFAULT_CUSTOMER_MODE", "website")
    return mode if mode in {"website", "fixed", "all"} else "website"


def get_fixed_customer_code(config):
    code = ((config or {}).get("DEFAULT_CUSTOMER_CODE") or "").strip()
    return code or "00005"


def _extract_mobile(billing: dict) -> str:
    """موبایلِ مشتری از فیلدِ phone — قراردادِ مشترکِ کلِ برنامه (هم
    ووکامرس هم پرستاشاپ). پیاده‌سازیِ واقعی حالا در customer_creation.py
    است (چون آنجا هم برایِ ساختِ مشتری لازمه)؛ این‌جا فقط برایِ سازگاریِ
    کدهایِ قدیمی‌تر که این نام را صدا می‌زنند نگه داشته شده."""
    from sync_app.core.customer_creation import extract_mobile

    return extract_mobile(billing)


def _find_customer_by_contact(cursor, email: str, mobile: str) -> str | None:
    """جستجوی مشتریِ ازقبل‌ثبت‌شده با ایمیل یا موبایل — قبلاً فقط ایمیل
    چک می‌شد، الان هر دو (کافیه یکی مطابقت داشته باشه، چون مشتری ممکنه
    تویِ یک سفارش ایمیلِ دیگه‌ای وارد کرده باشه ولی موبایلش ثابت مونده)."""
    conditions = []
    params: list = []
    if email:
        conditions.append("LOWER(LTRIM(RTRIM(Email_Address))) = ?")
        params.append(email)
    if mobile:
        conditions.append("LTRIM(RTRIM(C_Mobile)) = ?")
        params.append(mobile)
    if not conditions:
        return None
    sql = f"SELECT TOP 1 C_Code FROM Customer WHERE {' OR '.join(conditions)}"
    try:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if row and row[0]:
            return str(row[0]).strip()
    except Exception:
        pass
    return None


def _create_customer_from_billing(cursor, billing: dict, config: dict | None = None) -> str | None:
    """ثبتِ مشتریِ جدید — رویِ همون کِرسِر/تراکنشِ مشترکِ درجِ سفارش (نه
    یک اتصالِ جدا) تا اگه ثبتِ سفارش شکست خورد، مشتریِ نصفه‌ساخته هم
    رول‌بک بشه. منطقِ واقعیِ ساخت (هر سه روشِ دژاوو + Parent-linking) در
    customer_creation.py است — این‌جا فقط delegate می‌کنه."""
    from sync_app.core.customer_creation import create_customer_record

    return create_customer_record(cursor, billing, config)


def resolve_order_customer_code(order, config, cursor):
    """کد مشتری ERP برای سفارش: fixed/website/all.

    برایِ «fixed» همیشه همون کدِ ثابته. برایِ «website»/«all»: اول با
    ایمیل یا موبایلِ سفارش دنبالِ مشتریِ ازقبل‌ثبت‌شده می‌گرده؛ اگه پیدا
    نشد (و اطلاعاتِ تماس کافی بود)، یک مشتریِ جدید در ERP ثبت می‌کنه —
    نه اینکه فقط بی‌صدا به کدِ ثابت برگرده."""
    fixed_code = get_fixed_customer_code(config)
    mode = get_customer_mode(config)

    if mode == "fixed":
        return fixed_code

    billing = order.get("billing") or {}
    email = (billing.get("email") or "").strip().lower()
    mobile = _extract_mobile(billing)
    customer_id = int(order.get("customer_id") or 0)

    if mode == "website" and customer_id <= 0:
        return fixed_code

    if cursor is None or not (email or mobile):
        return fixed_code

    existing_code = _find_customer_by_contact(cursor, email, mobile)
    if existing_code:
        return existing_code

    new_code = _create_customer_from_billing(cursor, billing, config)
    return new_code or fixed_code
