"""سفارش دو قسمتی بین دو سرور.

وضعیت هر بخش روی خود سفارش سایت و یک فایل مشترک روی همین رایانه می‌ماند.
تا هر دو بخش ثبت نشود، سفارش ووکامرس باز می‌ماند تا سرور دیگر هنوز آن را ببیند.
"""

from __future__ import annotations

import hashlib
import json
import os

SPLIT_META = "peecha_split_order"


def _config(config):
    if config is not None:
        return config
    try:
        from sync_app.core.secure_config_loader import load_secure_config

        return load_secure_config(None) or {}
    except Exception:
        return {}


def line_origin(site_sku, config=None) -> tuple[str, str, str]:
    """own / other / plain ، برچسب سرور - دیتابیس، کد نرم‌افزار."""
    from sync_app.core.sync_utils import order_line_erp_sku, source_product_mark

    config = _config(config)
    text = str(site_sku or "").strip()
    own_mark = source_product_mark(config) or "این سرور"
    code, foreign = order_line_erp_sku(text, config)
    if foreign:
        mark = text.rsplit(" - ", 1)[0].strip() or "سرور دیگر"
        erp = text.rsplit(" - ", 1)[-1].strip()
        return "other", mark, erp or text
    if code and code != text:
        return "own", own_mark, code
    return "plain", own_mark, text


def _line_amount(item, config) -> float:
    from sync_app.core.scripts.ordersync import _line_unit_price

    qty = float(item.get("quantity", 0) or 0.0)
    if qty <= 0:
        return 0.0
    return float(_line_unit_price(item, config) or 0) * qty


def extra_charges(order, config) -> float:
    from sync_app.core.scripts.ordersync import _as_amount
    from sync_app.core.currency_helper import wc_total_to_erp_amount

    extra = _as_amount((order or {}).get("shipping_total")) + _as_amount((order or {}).get("shipping_tax"))
    for fee in (order or {}).get("fee_lines") or []:
        if isinstance(fee, dict):
            extra += _as_amount(fee.get("total")) + _as_amount(fee.get("total_tax"))
    return float(wc_total_to_erp_amount(extra, config) or 0)


def plan_split(order, config=None) -> dict:
    """اگر خطی مال سرور دیگری باشد، سفارش دو قسمتی است."""
    config = _config(config)
    from sync_app.core.sync_utils import source_product_mark

    own_mark = source_product_mark(config) or "این سرور"
    others: dict[str, dict] = {}
    own_preview = 0.0
    for item in (order or {}).get("line_items") or []:
        if float(item.get("quantity", 0) or 0) <= 0:
            continue
        kind, mark, erp = line_origin(item.get("sku"), config)
        amount = _line_amount(item, config)
        if kind == "other":
            bucket = others.setdefault(mark, {"skus": [], "amount": 0.0})
            if erp and erp not in bucket["skus"]:
                bucket["skus"].append(erp)
            bucket["amount"] += amount
        else:
            own_preview += amount
    amounts = {own_mark: own_preview}
    for mark, info in others.items():
        amounts[mark] = float(info["amount"])
    winner = _shipping_owner(amounts) or own_mark
    charges = extra_charges(order, config)
    return {
        "active": bool(others),
        "own_mark": own_mark,
        "others": others,
        "shipping_amount": charges,
        "shipping_on": winner if others else own_mark,
        "charge_shipping": (not others) or winner == own_mark,
    }


def _shipping_owner(amounts: dict) -> str:
    """سرور با بیشترین مبلغ کالا. اگر برابر باشند، نام ثابت انتخاب می‌شود تا هر اتصال همان یکی را برگزیند."""
    if not amounts:
        return ""
    top = max(round(float(amount or 0), 2) for amount in amounts.values())
    tied = sorted(
        str(mark) for mark, amount in amounts.items() if round(float(amount or 0), 2) == top
    )
    return tied[0] if tied else ""


def _money(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if abs(number - round(number)) < 0.001:
        return f"{int(round(number)):,}"
    return f"{number:,.2f}"


def render_note(order_id, state: dict) -> str:
    parts = state.get("parts") or {}
    count = len(parts)
    if count >= 2:
        opening = f"سفارش سایت شماره {order_id} به {count} بخش تقسیم شده است."
    else:
        opening = f"سفارش سایت شماره {order_id} بین چند سرور تقسیم شده است."
    lines = [
        opening + " تا وقتی همهٔ بخش‌ها ثبت نشود، سفارش باز می‌ماند و چیزی از قلم نمی‌افتد."
    ]
    for mark, part in sorted(parts.items(), key=lambda item: str(item[0])):
        done = str(part.get("status") or "") == "inserted"
        flag = "ثبت شد" if done else "هنوز ثبت نشده"
        invoice = f" فاکتور {part.get('invoice')}." if done and part.get("invoice") else ""
        skus = "، ".join(str(sku) for sku in (part.get("skus") or []) if str(sku).strip()) or "—"
        lines.append(
            f"بخش {mark}: {flag}.{invoice} کالاها: {skus}. مبلغ کالا: {_money(part.get('amount'))}."
        )
    if float(state.get("shipping_amount") or 0) > 0:
        lines.append(
            f"ارسال و هزینه‌های اضافه ({_money(state.get('shipping_amount'))}) "
            f"فقط روی فاکتور {state.get('shipping_on') or '—'} می‌نشیند."
        )
    missing = [str(sku) for sku in (state.get("unassigned") or []) if str(sku).strip()]
    if missing:
        lines.append("از قلم افتاده و تا حل نشدن، سفارش بسته نمی‌شود: " + "، ".join(missing))
    return "\n".join(lines)


def split_closed(state: dict) -> bool:
    parts = state.get("parts") or {}
    if len(parts) < 2:
        return False
    if state.get("unassigned"):
        return False
    return all(str(part.get("status") or "") == "inserted" for part in parts.values())


def _board_path(config) -> str:
    from sync_app.core.integrations.commerce_provider import store_platform
    from sync_app.core.sync_utils import _normalize_scope_url

    config = _config(config)
    platform = store_platform(config)
    url_key = "PS_URL" if platform == "prestashop" else "WC_URL"
    site = _normalize_scope_url(str(config.get(url_key) or ""), platform)
    digest = hashlib.sha256(f"{platform}|{site}".encode("utf-8")).hexdigest()[:16]
    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(local, "PeechaSync", "split_orders")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{digest}.json")


def _load_board(config) -> dict:
    try:
        with open(_board_path(config), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_board(config, data: dict) -> None:
    try:
        with open(_board_path(config), "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
    except Exception as exc:
        from sync_app.core.sync_utils import log

        log.warning(f"⚠️ ذخیرهٔ وضعیت سفارش دو قسمتی: {exc}")


def _parse_state(value) -> dict:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _state_from_order(order) -> dict:
    for item in (order or {}).get("meta_data") or []:
        if isinstance(item, dict) and str(item.get("key") or "") == SPLIT_META:
            return _parse_state(item.get("value"))
    return {}


def _merge_parts(base: dict, incoming: dict) -> dict:
    parts = dict(base.get("parts") or {})
    for mark, part in (incoming.get("parts") or {}).items():
        prev = parts.get(mark) or {}
        merged = dict(prev)
        merged.update(part or {})
        if str(prev.get("status") or "") == "inserted" and str((part or {}).get("status") or "") != "inserted":
            merged["status"] = "inserted"
            merged["invoice"] = prev.get("invoice") or merged.get("invoice") or ""
        parts[mark] = merged
    out = dict(base)
    out.update(incoming)
    out["parts"] = parts
    if base.get("unassigned") and not incoming.get("unassigned"):
        out["unassigned"] = []
    return out


def load_state(order, config=None) -> dict:
    config = _config(config)
    local = _parse_state((_load_board(config).get(str((order or {}).get("id"))) or {}))
    remote = _state_from_order(order)
    return _merge_parts(local, remote)


def compose_state(
    order,
    config,
    *,
    own_mark: str,
    own_status: str,
    own_skus: list,
    own_amount: float,
    own_invoice: str = "",
    others: dict | None = None,
    unassigned: list | None = None,
    shipping_on: str = "",
    shipping_amount: float = 0,
) -> dict:
    state = load_state(order, config)
    parts = dict(state.get("parts") or {})
    for mark, info in (others or {}).items():
        prev = parts.get(mark) or {}
        status = "inserted" if str(prev.get("status") or "") == "inserted" else "pending"
        parts[mark] = {
            "status": status,
            "skus": list((info or {}).get("skus") or prev.get("skus") or []),
            "amount": float((info or {}).get("amount") if info else prev.get("amount") or 0),
            "invoice": str(prev.get("invoice") or ""),
        }
    if own_mark and own_status:
        prev = parts.get(own_mark) or {}
        status = own_status
        invoice = str(own_invoice or "")
        if str(prev.get("status") or "") == "inserted" and status != "inserted":
            status = "inserted"
            invoice = str(prev.get("invoice") or invoice)
        elif status == "inserted" and not invoice:
            invoice = str(prev.get("invoice") or "")
        if own_skus:
            amount = float(own_amount or 0)
            skus = list(own_skus)
        else:
            amount = float(prev.get("amount") or own_amount or 0)
            skus = list(prev.get("skus") or [])
        parts[own_mark] = {
            "status": status,
            "skus": skus,
            "amount": amount,
            "invoice": invoice,
        }
    state["parts"] = parts
    state["unassigned"] = [str(sku) for sku in (unassigned or []) if str(sku).strip()]
    state["shipping_on"] = shipping_on or state.get("shipping_on") or ""
    state["shipping_amount"] = float(shipping_amount or 0)
    state["note"] = render_note((order or {}).get("id"), state)
    return state


def _publish_woocommerce(order, config, state: dict) -> None:
    from sync_app.core.sync_utils import log
    from sync_app.core.wc_sync_helper import wc_rest_request

    order_id = int((order or {}).get("id") or 0)
    if not order_id:
        return
    fresh = order
    try:
        response = wc_rest_request(
            config, "GET", f"orders/{order_id}", params={"_fields": "id,meta_data"}, timeout=30,
        )
        if int(getattr(response, "status_code", 0) or 0) < 400:
            payload = response.json()
            if isinstance(payload, dict):
                fresh = payload
    except Exception:
        fresh = order
    merged = _merge_parts(_parse_state(_state_from_order(fresh)), state)
    merged["note"] = render_note(order_id, merged)
    meta_id = None
    for item in (fresh or {}).get("meta_data") or []:
        if isinstance(item, dict) and str(item.get("key") or "") == SPLIT_META:
            meta_id = item.get("id")
            break
    meta = {"key": SPLIT_META, "value": json.dumps(merged, ensure_ascii=False)}
    if meta_id:
        meta["id"] = meta_id
    try:
        wc_rest_request(
            config, "PUT", f"orders/{order_id}", json_body={"meta_data": [meta]}, timeout=30,
        )
    except Exception as exc:
        log.warning(f"⚠️ سفارش {order_id}: نوشتن وضعیت دو قسمتی روی سایت ناموفق بود: {exc}")
    previous = str(_state_from_order(fresh).get("note") or "")
    if merged["note"] and merged["note"] != previous:
        try:
            wc_rest_request(
                config,
                "POST",
                f"orders/{order_id}/notes",
                json_body={"note": merged["note"], "customer_note": False},
                timeout=30,
            )
            log.info(f"📝 سفارش {order_id}: یادداشت دو قسمتی روی سایت نوشته شد.")
        except Exception as exc:
            log.warning(f"⚠️ سفارش {order_id}: یادداشت سفارش نوشته نشد: {exc}")
    state.clear()
    state.update(merged)


def _publish_prestashop(order, config, state: dict) -> None:
    from sync_app.core.sync_utils import log

    order_id = int((order or {}).get("id") or 0)
    customer_id = int((order or {}).get("customer_id") or 0)
    cart_id = int((order or {}).get("id_cart") or 0)
    note = str(state.get("note") or "")
    if not order_id or not customer_id or not cart_id or not note:
        return
    if str(state.get("ps_note") or "") == note:
        return
    try:
        from sync_app.core.ps_sync_helper import _build_xml, _set_text, ps_call, ps_rest_request

        def _build(node, text=note):
            _set_text(node, "id_order", order_id)
            _set_text(node, "id_cart", cart_id)
            _set_text(node, "id_customer", customer_id)
            _set_text(node, "message", text)
            _set_text(node, "private", 1)

        ps_call(
            f"یادداشت سفارش دو قسمتی #{order_id}",
            lambda: ps_rest_request(
                config, "POST", "messages", xml_body=_build_xml("message", _build), timeout=30,
            ),
        )
        state["ps_note"] = note
        log.info(f"📝 سفارش {order_id}: پیام خصوصی دو قسمتی در پرستاشاپ ثبت شد.")
    except Exception as exc:
        log.warning(f"⚠️ سفارش {order_id}: پیام دو قسمتی پرستاشاپ نوشته نشد: {exc}")


def publish_state(order, config, state: dict) -> dict:
    config = _config(config)
    order_id = str((order or {}).get("id") or "")
    board = _load_board(config)
    previous = _parse_state(board.get(order_id) or {})
    merged = _merge_parts(previous, state)
    merged["note"] = render_note(order_id, merged)
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        merged["ps_note"] = previous.get("ps_note") or ""
        _publish_prestashop(order, config, merged)
    else:
        _publish_woocommerce(order, config, merged)
    if order_id:
        board[order_id] = merged
        _save_board(config, board)
    return merged


def record_split(order, config, **kwargs) -> dict:
    state = compose_state(order, config, **kwargs)
    return publish_state(order, config, state)


def invoice_description(order_id, state: dict, limit: int = 500) -> str:
    text = render_note(order_id, state).replace("\n", " | ")
    return text[:limit]
