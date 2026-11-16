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


def _mark_order_completed(order_id, config: dict) -> bool:
    from sync_app.core.integrations.commerce_provider import is_prestashop
    from sync_app.core.sync_utils import log

    if is_prestashop(config):
        # طبقِ همون تصمیمِ ordersync.py دژاوو برایِ پرستاشاپ: وضعیتِ سفارش
        # روی پرستاشاپ تغییر داده نمی‌شود، فقط در ERP ثبت می‌شود.
        return True
    try:
        # قبلاً اینجا مستقیم requests.put می‌زد — بدونِ verify= (پس همیشه
        # SSL رو چک می‌کرد، حتی وقتی کاربر WC_VERIFY_SSL رو خاموش کرده
        # بود) و بدونِ timeout، و خطا رو کاملاً بی‌صدا قورت می‌داد
        # (except: pass) — دقیقاً همون الگویی که باعث می‌شد وضعیتِ سفارش
        # در سایت به completed تغییر نکنه بدونِ هیچ نشونه‌ای تو لاگ. الان
        # از همون wc_rest_requestِ مشترکِ کل برنامه استفاده می‌کنه (که
        # verify/timeout/User-Agent رو درست از config می‌خونه) و مثلِ
        # ordersync.py دژاوو نتیجه رو لاگ می‌کنه.
        from sync_app.core.wc_sync_helper import wc_rest_request

        resp = wc_rest_request(config, "PUT", f"orders/{order_id}", json_body={"status": "completed"})
        if int(getattr(resp, "status_code", 0) or 0) >= 400:
            log.error(f"❌ خطا در به‌روزرسانیِ وضعیتِ سفارش {order_id} در ووکامرس: HTTP {resp.status_code} — {resp.text[:300]}")
            return False
        log.info(f"✅ وضعیتِ سفارش {order_id} در ووکامرس به 'completed' تغییر کرد.")
        return True
    except Exception as exc:
        log.error(f"❌ خطا در به‌روزرسانیِ وضعیتِ سفارش {order_id} در ووکامرس: {exc}")
        return False


def _fetch_orders(config: dict) -> list[dict]:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    if is_prestashop(config):
        from sync_app.core.ps_order_helper import ps_list_paid_orders

        return ps_list_paid_orders(config, timeout=60)

    from sync_app.core.scripts.ordersync import fetch_wc_processing_orders

    return fetch_wc_processing_orders(config, timeout=30)


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
    from sync_app.core.split_order import plan_split

    plan = plan_split(order, config)
    order_map = load_sepidar_map(_ORDER_MAP_FILE)
    if str(order_id) in order_map:
        from sync_app.core.order_import_ledger import DIFFERENT, UNKNOWN, ledger_verdict, record_imported_order

        # شماره‌یِ سفارشِ سایت بعد از ریستِ سایت تکرار می‌شه — فقط اگه همون
        # سفارش باشه «قبلاً ثبت شده»، نه یک سفارشِ تازه با همون شماره.
        verdict = ledger_verdict(order_id, order)
        if verdict != DIFFERENT:
            if verdict == UNKNOWN:
                record_imported_order(order_id, order)
            from sync_app.core.scripts.ordersync import _order_sync_outcome

            if plan["active"]:
                from sync_app.core.split_order import record_split, split_closed

                state = record_split(
                    order, config,
                    own_mark=plan["own_mark"],
                    own_status="inserted",
                    own_skus=[],
                    own_amount=0,
                    own_invoice=str(order_map.get(str(order_id)) or ""),
                    others=plan["others"],
                    unassigned=[],
                    shipping_on=plan["shipping_on"],
                    shipping_amount=plan["shipping_amount"],
                )
                if split_closed(state):
                    if _mark_order_completed(order_id, config):
                        return _order_sync_outcome(order_id, "duplicate")
                    return _order_sync_outcome(order_id, "inserted_status_failed")
                log.info(f"ℹ️ سفارش {order_id} بخش این سرور را دارد؛ بخش سرور دیگر هنوز باز است.")
                return _order_sync_outcome(order_id, "split_pending", state.get("note") or "")
            log.info(f"ℹ️ سفارش {order_id} قبلاً به فاکتورِ سپیدار تبدیل شده — رد شد.")
            if _mark_order_completed(order_id, config):
                return _order_sync_outcome(order_id, "duplicate")
            return _order_sync_outcome(order_id, "inserted_status_failed")
        log.warning(
            f"⚠️ شماره‌یِ سفارشِ {order_id} قبلاً برایِ یک سفارشِ دیگه (قبل از ریستِ سایت) فاکتور شده بود — "
            "این یک سفارشِ تازه‌ست و فاکتور می‌شه."
        )

    conn = get_sepidar_connection(config)
    try:
        cursor = conn.cursor()

        billing = order.get("billing") or {}
        party_ref = resolve_party_ref(billing, config, cursor)
        if not party_ref:
            conn.rollback()
            log.warning(f"⚠️ سفارش {order_id}: طرف‌حساب شناسایی/ساخته نشد — رد شد.")
            from sync_app.core.scripts.ordersync import _order_sync_outcome

            return _order_sync_outcome(order_id, "failed", "طرف‌حساب شناسایی نشد")

        lines = []
        skipped = []
        for item in order.get("line_items", []):
            qty = float(item.get("quantity", 0) or 0.0)
            if qty <= 0:
                continue
            sku = str(item.get("sku") or "").strip()
            from sync_app.core.split_order import line_origin
            from sync_app.core.sync_utils import order_line_erp_sku

            if plan["active"]:
                kind, _mark, erp_code = line_origin(sku, config)
                if kind == "other":
                    continue
                sku = erp_code or sku
            else:
                erp_sku, other_source = order_line_erp_sku(sku, config)
                if other_source:
                    log.warning(f"⚠️ سفارش {order_id}: خط «{sku}» مال سرور/دیتابیس دیگری است.")
                    sku = ""
                else:
                    sku = erp_sku
            item_ref = _resolve_sepidar_item_id(cursor, sku) if sku else None
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
                skipped.append(sku or str(item.get("name") or "?"))
                log.warning(f"⚠️ سفارش {order_id}: کالایِ '{sku}' در سپیدار سینک نشده — این خط رد شد.")
                continue
            unit_price = _line_unit_price(item, config)
            lines.append({"item_ref": int(item_ref), "qty": qty, "unit_price": unit_price, "sku": sku})

        from sync_app.core.scripts.ordersync import _order_sync_outcome, order_payable_amount

        if skipped:
            conn.rollback()
            detail = ", ".join(skipped)
            if plan["active"]:
                from sync_app.core.split_order import record_split

                record_split(
                    order, config,
                    own_mark=plan["own_mark"],
                    own_status="pending",
                    own_skus=[],
                    own_amount=0,
                    others=plan["others"],
                    unassigned=skipped,
                    shipping_on=plan["shipping_on"],
                    shipping_amount=plan["shipping_amount"],
                )
            log.error(f"❌ سفارش {order_id} ناقص ماند و فاکتور نشد. خطوط بدون کالا: {detail}")
            return _order_sync_outcome(order_id, "incomplete", detail)

        if not lines:
            conn.rollback()
            if plan["active"]:
                from sync_app.core.split_order import record_split

                state = record_split(
                    order, config,
                    own_mark=plan["own_mark"],
                    own_status="",
                    own_skus=[],
                    own_amount=0,
                    others=plan["others"],
                    unassigned=[],
                    shipping_on=plan["shipping_on"],
                    shipping_amount=plan["shipping_amount"],
                )
                log.info(f"ℹ️ سفارش {order_id} کالای این سرور را ندارد و برای سرور دیگر باز می‌ماند.")
                return _order_sync_outcome(order_id, "split_pending", state.get("note") or "")
            log.warning(f"⚠️ سفارش {order_id} هیچ ردیفِ معتبری نداشت — رد شد.")
            return _order_sync_outcome(order_id, "empty")

        sepidar_apply_lock(cursor, "SaleInvoice")
        sale_invoice_id = next_int_code(cursor, "POS.SaleInvoice", "SaleInvoiceID")
        number = next_int_code(cursor, "POS.SaleInvoice", "Number")

        stock_ref = get_stock_ref(config)
        fiscal_period_ref = get_fiscal_period_ref(config)
        total_price = order_payable_amount(order, config)
        description = f"سفارشِ سایت #{order_id}"
        if plan["active"]:
            own_amount = sum(float(line["unit_price"]) * float(line["qty"]) for line in lines)
            total_price = own_amount + (plan["shipping_amount"] if plan["charge_shipping"] else 0)
            from sync_app.core.split_order import compose_state, invoice_description

            provisional = compose_state(
                order, config,
                own_mark=plan["own_mark"],
                own_status="inserted",
                own_skus=[str(line.get("sku") or line["item_ref"]) for line in lines],
                own_amount=own_amount,
                own_invoice="",
                others=plan["others"],
                unassigned=[],
                shipping_on=plan["shipping_on"],
                shipping_amount=plan["shipping_amount"],
            )
            description = invoice_description(order_id, provisional)
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
                description,
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
        from sync_app.core.order_import_ledger import record_imported_order

        record_imported_order(order_id, order)
        log.info(f"✅ سفارش {order_id} → فاکتورِ سپیدار #{sale_invoice_id} (Number {number}) ثبت شد.")
        if plan["active"]:
            from sync_app.core.split_order import record_split, split_closed

            own_amount = sum(float(line["unit_price"]) * float(line["qty"]) for line in lines)
            state = record_split(
                order, config,
                own_mark=plan["own_mark"],
                own_status="inserted",
                own_skus=[str(line.get("sku") or line["item_ref"]) for line in lines],
                own_amount=own_amount,
                own_invoice=str(sale_invoice_id),
                others=plan["others"],
                unassigned=[],
                shipping_on=plan["shipping_on"],
                shipping_amount=plan["shipping_amount"],
            )
            if not split_closed(state):
                log.info(f"ℹ️ سفارش {order_id} دو قسمتی است؛ بخش این سرور ثبت شد و سفارش سایت باز ماند.")
                return _order_sync_outcome(order_id, "split_pending", state.get("note") or "")
        if _mark_order_completed(order_id, config):
            return _order_sync_outcome(order_id, "inserted")
        return _order_sync_outcome(order_id, "inserted_status_failed")
    except Exception as exc:
        conn.rollback()
        log.error(f"❌ خطا در ثبتِ فاکتورِ سپیدار برایِ سفارش {order_id}: {exc}")
        from sync_app.core.scripts.ordersync import _order_sync_outcome

        return _order_sync_outcome(order_id, "failed", str(exc))
    finally:
        conn.close()


def sync_orders(config: dict | None = None, order_ids=None) -> dict:
    from sync_app.core.sync_utils import log

    config = config or {}
    orders = _fetch_orders(config)
    if order_ids is not None:
        orders = [o for o in orders if int(o.get("id") or 0) in order_ids]
    log.info(f"📦 تعدادِ سفارش‌هایِ processing: {len(orders)}")
    if not orders and not order_ids:
        log.info("ℹ️ سفارشِ جدیدی یافت نشد.")
        return {"ok": True, "orders": 0}
    from sync_app.core.scripts.ordersync import finish_order_batch

    outcomes = [insert_invoice(order, config) for order in orders]
    return finish_order_batch(orders, order_ids, outcomes)


def main(config: dict | None = None, order_ids=None) -> dict:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config or load_secure_config(None) or {}
    return sync_orders(cfg, order_ids=order_ids)


if __name__ == "__main__":
    main()
