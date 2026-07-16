""" مشتری پیش‌فرض سفارش/sync """

from __future__ import annotations


def get_customer_mode(config):
    mode = (config or {}).get("DEFAULT_CUSTOMER_MODE", "website")
    return mode if mode in {"website", "fixed", "all"} else "website"


def get_fixed_customer_code(config):
    code = ((config or {}).get("DEFAULT_CUSTOMER_CODE") or "").strip()
    return code or "00005"


def resolve_order_customer_code(order, config, cursor):
    """ کد مشتری ERP برای سفارش: fixed/website/all """
    fixed_code = get_fixed_customer_code(config)
    mode = get_customer_mode(config)

    if mode == "fixed":
        return fixed_code

    billing = order.get("billing") or {}
    email = (billing.get("email") or "").strip().lower()
    customer_id = int(order.get("customer_id") or 0)

    if mode == "website" and customer_id <= 0:
        return fixed_code

    if email and cursor is not None:
        try:
            cursor.execute(
                "SELECT TOP 1 C_Code FROM Customer WHERE LOWER(LTRIM(RTRIM(Email_Address))) = ?",
                (email,),
            )
            row = cursor.fetchone()
            if row and row[0]:
                return str(row[0]).strip()
        except Exception:
            pass

    return fixed_code
