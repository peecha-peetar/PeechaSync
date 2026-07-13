"""
مشتریان پرستاشاپ — نگاشت به همون شکل customer/billing که customersync.py
برای ووکامرس انتظار داره، تا منطق درج/بروزرسانی مشتری در ERP بین دو
پلتفرم مشترک بمونه.

پرستاشاپ برخلاف ووکامرس، آدرس/تلفن رو داخل خودِ customer برنمی‌گردونه —
یک resource جدا به اسم addresses داره (فیلتر با id_customer). برای هر
مشتری، اولین آدرسش رو می‌گیریم و به شکل billing ووکامرس تبدیل می‌کنیم.
"""

from __future__ import annotations

from sync_app.core.ps_sync_helper import (
    _response_json,
    _unwrap_dict,
    _unwrap_list,
    ps_call,
    ps_rest_request,
)


def _address_to_billing(addr: dict) -> dict:
    phone = str(addr.get("phone") or "").strip()
    mobile = str(addr.get("phone_mobile") or "").strip()
    phone_combined = "/".join(p for p in (phone, mobile) if p)
    return {
        "first_name": str(addr.get("firstname") or "").strip(),
        "last_name": str(addr.get("lastname") or "").strip(),
        "company": str(addr.get("company") or "").strip(),
        "address_1": str(addr.get("address1") or "").strip(),
        "address_2": str(addr.get("address2") or "").strip(),
        "city": str(addr.get("city") or "").strip(),
        "state": "",
        "postcode": str(addr.get("postcode") or "").strip(),
        "phone": phone_combined,
        "national_code": str(addr.get("dni") or "").strip(),
    }


def ps_get_customer_address(config, customer_id: int, *, timeout=None) -> dict:
    """اولین آدرس ثبت‌شده‌ی مشتری — برای billing."""
    cfg = config or {}
    resp = ps_call(
        f"دریافت آدرس مشتری #{customer_id}",
        lambda: ps_rest_request(
            cfg, "GET", "addresses",
            params={
                "filter[id_customer]": f"[{int(customer_id)}]",
                "display": "full",
                "limit": "0,1",
            },
            timeout=timeout,
        ),
    )
    data = _response_json(resp, f"دریافت آدرس مشتری #{customer_id}")
    rows = _unwrap_list(data, "addresses")
    return rows[0] if rows and isinstance(rows[0], dict) else {}


def ps_get_customer(config, customer_id: int, *, timeout=None) -> dict | None:
    cfg = config or {}
    resp = ps_call(
        f"دریافت مشتری #{customer_id}",
        lambda: ps_rest_request(cfg, "GET", f"customers/{int(customer_id)}", timeout=timeout),
    )
    if getattr(resp, "status_code", 0) == 404:
        return None
    data = _response_json(resp, f"دریافت مشتری #{customer_id}")
    entry = _unwrap_dict(data, "customer")
    if not entry.get("id"):
        return None

    email = str(entry.get("email") or "").strip()
    first = str(entry.get("firstname") or "").strip()
    last = str(entry.get("lastname") or "").strip()

    try:
        address = ps_get_customer_address(cfg, customer_id, timeout=timeout)
    except Exception:
        address = {}
    billing = _address_to_billing(address)
    billing["email"] = email
    if not billing.get("first_name"):
        billing["first_name"] = first
    if not billing.get("last_name"):
        billing["last_name"] = last

    return {
        "id": int(entry.get("id") or 0),
        "email": email,
        "first_name": first,
        "last_name": last,
        "username": email,
        "billing": billing,
    }


def ps_list_customers(config, *, max_customers: int = 0, timeout=None) -> list[dict]:
    """همه مشتریان — هر رکورد شکل ps_get_customer، paginate شده."""
    cfg = config or {}
    out: list[dict] = []
    offset = 0
    page_size = 100
    while True:
        resp = ps_call(
            f"دریافت مشتریان offset={offset}",
            lambda o=offset: ps_rest_request(
                cfg, "GET", "customers",
                params={"limit": f"{o},{page_size}"},
                timeout=timeout,
            ),
        )
        data = _response_json(resp, "دریافت مشتریان")
        rows = _unwrap_list(data, "customers")
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            full = ps_get_customer(cfg, int(row["id"]), timeout=timeout)
            if full:
                out.append(full)
            if max_customers and len(out) >= max_customers:
                return out[:max_customers]
        if len(rows) < page_size:
            break
        offset += page_size
    return out


def ps_list_customer_ids_with_paid_orders(config, *, timeout=None) -> set[int]:
    """id مشتریانی که حداقل یک سفارش پرداخت‌شده (valid=1) دارن."""
    from sync_app.core.ps_order_helper import ps_list_paid_order_customer_ids

    return ps_list_paid_order_customer_ids(config, timeout=timeout)
