"""POS.SaleInvoice + POS.SaleInvoiceItem — فاکتورِ فروشِ مستقیمِ سپیدار/دشت،
از سفارشِ سایت (بدونِ مرحلهٔ «سفارش» جدا — سپیدار سفارش نداره، مستقیم
فاکتور صادر می‌کنه، دقیقاً مثلِ اینکه RqTitle+RqDetailِ دژاوو هم «سفارش»
جدایی ندارن).

فقط سفارش‌هایِ ووکامرسِ processing سینک می‌شن (تصمیمِ کاربر). هرگز
POS.Receipt/POS.PartySettlement/POS.PartySettlementItem نمی‌سازه — فقط
SaleInvoice+SaleInvoiceItem، دقیقاً مطابقِ ترِیسِ واقعی (Invoice.txt):
IsSettled=0، تسویه کاملاً دستی در خودِ سپیدار می‌مونه."""

from __future__ import annotations

from sync_app.core.scripts.sepidar.sepidar_common import (
    get_fiscal_period_ref,
    get_sepidar_connection,
    get_stock_ref,
    load_sepidar_map,
    next_int_code,
    save_sepidar_map,
    sepidar_apply_lock,
)
from sync_app.core.scripts.sepidar.sepidar_customersync import resolve_party_ref

_ORDER_MAP_FILE = "sepidar_order_map.json"


def _resolve_sepidar_item_id(cursor, sku: str) -> int | None:
    """ItemIDِ سپیدار مستقیم از POS.Item — عمداً از sepidar_product_map.json
    استفاده نمی‌کنه، چون از فازِ ۲ (بازگشتِ جهتِ سینکِ محصول) اون فایل
    sku→idِ سایت رو ذخیره می‌کنه، نه ItemIDِ داخلیِ سپیدار؛ استفاده‌ش این‌جا
    باعثِ نقضِ FK_SaleInvoiceItem_Item می‌شد (idِ سایت به‌جایِ ItemID پاس
    داده می‌شد)."""
    if not sku:
        return None
    cursor.execute("SELECT TOP 1 ItemID FROM POS.Item WHERE Code = ?", (sku,))
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _mark_order_completed(order_id, config: dict) -> None:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        # طبقِ همون تصمیمِ ordersync.py دژاوو برایِ پرستاشاپ: وضعیتِ سفارش
        # روی پرستاشاپ تغییر داده نمی‌شود، فقط در ERP ثبت می‌شود.
        return
    try:
        import requests
        from sync_app.core.wc_api_helper import wc_endpoint, get_wc_auth

        ck, cs = get_wc_auth(config)
        url = f"{wc_endpoint(config.get('WC_URL', ''), 'orders')}/{order_id}"
        requests.put(url, auth=(ck, cs), json={"status": "completed"})
    except Exception:
        pass


def _fetch_orders(config: dict) -> list[dict]:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        from sync_app.core.ps_order_helper import ps_list_paid_orders

        return ps_list_paid_orders(config, timeout=60)

    from sync_app.core.wc_sync_helper import wc_rest_request, wc_http_error_message

    response = wc_rest_request(config, "GET", "orders", params={"status": "processing"}, timeout=30)
    if int(getattr(response, "status_code", 0) or 0) >= 400:
        raise RuntimeError(wc_http_error_message(response, config, prefix="خطا در دریافتِ سفارش‌ها"))
    data = response.json()
    return data if isinstance(data, list) else []


def _line_unit_price(item: dict, config: dict) -> float:
    from sync_app.core.currency_helper import wc_total_to_erp_amount

    qty = float(item.get("quantity", 0) or 0.0)
    if qty <= 0:
        return 0.0
    price_val = item.get("price")
    if price_val is None:
        subtotal = float(item.get("subtotal", 0) or 0.0)
        price_val = subtotal / qty if qty > 0 else subtotal
    return wc_total_to_erp_amount(price_val, config)


def insert_invoice(order: dict, config: dict) -> None:
    from sync_app.core.sync_utils import log

    order_id = order.get("id")
    order_map = load_sepidar_map(_ORDER_MAP_FILE)
    if str(order_id) in order_map:
        log.info(f"ℹ️ سفارش {order_id} قبلاً به فاکتورِ سپیدار تبدیل شده — رد شد.")
        _mark_order_completed(order_id, config)
        return

    conn = get_sepidar_connection(config)
    try:
        cursor = conn.cursor()

        billing = order.get("billing") or {}
        party_ref = resolve_party_ref(billing, config, cursor)
        if not party_ref:
            conn.rollback()
            log.warning(f"⚠️ سفارش {order_id}: طرف‌حساب شناسایی/ساخته نشد — رد شد.")
            return

        lines = []
        for item in order.get("line_items", []):
            qty = float(item.get("quantity", 0) or 0.0)
            if qty <= 0:
                continue
            sku = str(item.get("sku") or "").strip()
            item_ref = _resolve_sepidar_item_id(cursor, sku)
            if not item_ref:
                # تطبیقِ ساختاری («سایت متغیر / سپیدار ساده»): اگه این خط
                # مستقیم با SKUِ خودش پیدا نشد، شاید این واریانت با SKUِ
                # دیگه‌ای در سپیدار تطبیق داده شده باشه — دقیقاً مثلِ
                # ordersync.py دژاوو (resolve_line_item_variant).
                try:
                    site_parent_id = int(item.get("product_id") or 0)
                    site_variation_id = int(item.get("variation_id") or 0)
                except (TypeError, ValueError):
                    site_parent_id = site_variation_id = 0
                if site_parent_id and site_variation_id:
                    from sync_app.core.structure_mismatch_override import find_erp_sku_for_site_variation

                    overridden_sku = find_erp_sku_for_site_variation(site_parent_id, site_variation_id)
                    if overridden_sku:
                        item_ref = _resolve_sepidar_item_id(cursor, overridden_sku)
            if not item_ref:
                log.warning(f"⚠️ سفارش {order_id}: کالایِ '{sku}' در سپیدار سینک نشده — این خط رد شد.")
                continue
            unit_price = _line_unit_price(item, config)
            lines.append({"item_ref": int(item_ref), "qty": qty, "unit_price": unit_price})

        if not lines:
            conn.rollback()
            log.warning(f"⚠️ سفارش {order_id} هیچ ردیفِ معتبری نداشت — رد شد.")
            return

        sepidar_apply_lock(cursor, "SaleInvoice")
        sale_invoice_id = next_int_code(cursor, "POS.SaleInvoice", "SaleInvoiceID")
        number = next_int_code(cursor, "POS.SaleInvoice", "Number")

        stock_ref = get_stock_ref(config)
        fiscal_period_ref = get_fiscal_period_ref(config)
        total_price = sum(l["unit_price"] * l["qty"] for l in lines)
        mobile = str(billing.get("phone") or "").split("/")[0].strip()

        cursor.execute(
            """
            INSERT INTO POS.[SaleInvoice]
                ([PartyPhone], [SettlementValue], [SellerPartyRef], [IsSettled], [AddressRef],
                 [SettlementDeadLine], [VoucherRef], [CostVoucherRef], [TaxPayerBillIssueDateTime],
                 [SettlementType], [SnappMarketOrderInvoiceRef], [SaleInvoiceID], [Number], [Date],
                 [PartyRef], [SaleType], [TotalDiscount], [TotalLoyaltyDiscount], [StockRef],
                 [TotalTax], [TotalPrice], [TotalDuty], [ChangeReduction], [RemainingPrice],
                 [TotalNetPrice], [FiscalPeriodRef], [State], [Creator], [CreationDate],
                 [LastModifier], [LastModificationDate], [Version], [IsEdited],
                 [OriginalSaleInvoiceRef], [Description], [PartyRealName], [Guid])
            VALUES
                (?, 0, NULL, 0, NULL, NULL, NULL, NULL, GETDATE(), 1, NULL, ?, ?, GETDATE(), ?, 0, 0, 0,
                 ?, 0, ?, 0, 0, 0, ?, ?, 1, ?, GETDATE(), ?, GETDATE(), 1, 0, NULL, ?, NULL, NULL)
            """,
            (
                mobile or None, sale_invoice_id, number, party_ref, stock_ref,
                total_price, total_price, fiscal_period_ref, 1, 1,
                f"سفارشِ سایت #{order_id}",
            ),
        )

        for row_number, line in enumerate(lines, start=1):
            sale_invoice_item_id = next_int_code(cursor, "POS.SaleInvoiceItem", "SaleInvoiceItemID")
            line_price = line["unit_price"] * line["qty"]
            cursor.execute(
                """
                INSERT INTO POS.[SaleInvoiceItem]
                    ([StockRef], [MainUnitFee], [SaleInvoiceItemID], [SaleInvoiceRef], [RowNumber],
                     [ItemRef], [Quantity], [Fee], [Discount], [LoyaltyDiscount], [Tax], [Duty],
                     [Price], [Version], [ScaleQuantity], [VoucherItemQuantity])
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, 1, 0, ?)
                """,
                (
                    stock_ref, line["unit_price"], sale_invoice_item_id, sale_invoice_id, row_number,
                    line["item_ref"], line["qty"], line["unit_price"], line_price, line["qty"],
                ),
            )

        conn.commit()
        order_map[str(order_id)] = sale_invoice_id
        save_sepidar_map(_ORDER_MAP_FILE, order_map)
        log.info(f"✅ سفارش {order_id} → فاکتورِ سپیدار #{sale_invoice_id} (Number {number}) ثبت شد.")
        _mark_order_completed(order_id, config)
    except Exception as exc:
        conn.rollback()
        log.error(f"❌ خطا در ثبتِ فاکتورِ سپیدار برایِ سفارش {order_id}: {exc}")
    finally:
        conn.close()


def sync_orders(config: dict | None = None, order_ids=None) -> dict:
    from sync_app.core.sync_utils import log

    config = config or {}
    orders = _fetch_orders(config)
    if order_ids is not None:
        orders = [o for o in orders if int(o.get("id") or 0) in order_ids]
    log.info(f"📦 تعدادِ سفارش‌هایِ processing: {len(orders)}")
    if not orders:
        log.info("ℹ️ سفارشِ جدیدی یافت نشد.")
        return {"ok": True, "orders": 0}
    for order in orders:
        insert_invoice(order, config)
    log.info("✅ پایانِ عملیاتِ همگام‌سازیِ فاکتورِ سپیدار.")
    return {"ok": True, "orders": len(orders)}


def main(config: dict | None = None, order_ids=None) -> dict:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config or load_secure_config(None) or {}
    return sync_orders(cfg, order_ids=order_ids)


if __name__ == "__main__":
    main()
