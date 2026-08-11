import requests
import pyodbc
import re
from collections import defaultdict

# ---------------------------------------------------------
# 📌 importهای پکیجی (سازگار با EXE)
# ---------------------------------------------------------
try:
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_utils import log
    from sync_app.core.customer_context import get_fixed_customer_code, resolve_order_customer_code
    from sync_app.core.sql_connection_helper import connect_with_fallback
    from sync_app.core.wc_api_helper import wc_endpoint, get_wc_auth
    from sync_app.core.currency_helper import wc_total_to_erp_amount
except ImportError:
    class MockLog:
        def info(self, msg): print("INFO:", msg)
        def error(self, msg): print("ERROR:", msg)
        def warning(self, msg): print("WARN:", msg)
    log = MockLog()
    def load_secure_config(_): return {}


# ---------------------------------------------------------
# 📌 تنظیمات زمان اجرا (برای جلوگیری از مشکل import زودهنگام)
# ---------------------------------------------------------
SQL_CONN_STRING = ""
WC_API_URL_BASE = ""
WC_CONSUMER_KEY = ""
WC_CONSUMER_SECRET = ""
WC_AUTH = ("", "")
WC_ORDERS_ENDPOINT = ""
DEFAULT_CUSTOMER_CODE = "00005"


def is_ps_mode(config=None) -> bool:
    from sync_app.core.integrations.commerce_provider import is_prestashop

    return is_prestashop(config or load_secure_config(None) or {})


def init_runtime_config():
    global SQL_CONN_STRING, WC_API_URL_BASE, WC_CONSUMER_KEY, WC_CONSUMER_SECRET
    global WC_AUTH, WC_ORDERS_ENDPOINT, DEFAULT_CUSTOMER_CODE

    config = load_secure_config(None) or {}

    SQL_CONN_STRING = config.get("SQL_CONN_STRING", "")
    WC_API_URL_BASE = config.get("WC_URL", "")
    WC_CONSUMER_KEY, WC_CONSUMER_SECRET = get_wc_auth(config)
    WC_AUTH = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
    WC_ORDERS_ENDPOINT = wc_endpoint(WC_API_URL_BASE, "orders")
    DEFAULT_CUSTOMER_CODE = get_fixed_customer_code(config)


# ---------------------------------------------------------
# 📌 اعتبارسنجی اولیه تنظیمات
# ---------------------------------------------------------
def validate_config():
    if not SQL_CONN_STRING:
        raise RuntimeError("SQL_CONN_STRING خالی است.")
    if not WC_API_URL_BASE or not WC_CONSUMER_KEY or not WC_CONSUMER_SECRET:
        raise RuntimeError("تنظیمات WooCommerce ناقص است.")


# ---------------------------------------------------------
# 📌 توابع کمکی SKU و واریانت
# ---------------------------------------------------------
def parse_sku(sku: str):
    sku = (sku or "").strip()
    if not sku:
        return None, None, None
    parts = sku.split("-")
    a_code = parts[0] if parts else None
    poshak_id_c = None
    if len(parts) >= 2 and parts[1].startswith("V"):
        try:
            poshak_id_c = int(parts[1][1:])
        except ValueError:
            poshak_id_c = None
    return a_code, poshak_id_c, parts


def resolve_variant_by_codes(cursor, a_code, poshak_id_c):
    cursor.execute("""
        SELECT PoshakID, PoshakId_C
        FROM ItemArticle
        WHERE A_Code = ? AND CAST(PoshakId_C AS INT) = ?
    """, (a_code, int(poshak_id_c)))
    row = cursor.fetchone()
    if row:
        return int(row[0]), int(row[1])
    return None, None


def resolve_variant_by_names(cursor, a_code, size_name, color_name):
    cursor.execute("""
        SELECT ia.PoshakID, ia.PoshakId_C
        FROM ((Poshak AS SizeTable 
            INNER JOIN Poshak AS RangTable ON SizeTable.ID = RangTable.ParentID)
            INNER JOIN ItemArticle AS ia ON RangTable.ID = ia.PoshakID)
        WHERE ia.A_Code = ? AND SizeTable.A_Name = ? AND RangTable.A_Name = ?
    """, (a_code, size_name, color_name))
    row = cursor.fetchone()
    if row:
        return int(row[0]), int(row[1])
    cursor.execute("""
        SELECT ia.PoshakID, ia.PoshakId_C
        FROM ItemArticle ia
        LEFT JOIN Poshak AS SizeTable ON ia.PoshakID = SizeTable.ID
        LEFT JOIN Poshak AS ColorTable ON CAST(ia.PoshakId_C AS INT) = ColorTable.ID
        WHERE ia.A_Code = ?
          AND ISNULL(SizeTable.A_Name, '') = ?
          AND ISNULL(ColorTable.A_Name, '') = ?
    """, (a_code, size_name, color_name))
    row = cursor.fetchone()
    if row:
        return int(row[0]), int(row[1])
    return None, None


def infer_line_item_sku(item):
    """اگر ووکامرس SKU خالی فرستاد، از نام خط یا product_id استخراج می‌کنیم."""
    sku = (item.get("sku") or "").strip()
    if sku:
        return sku

    name = (item.get("name") or "").strip()
    m = re.search(r"(\d{7})\s*[-_]?\s*(?:V|variant)\s*(\d+)", name, re.I)
    if m:
        return f"{m.group(1)}-V{m.group(2)}"
    m = re.search(r"(\d{7})-V(\d+)", name, re.I)
    if m:
        return f"{m.group(1)}-V{m.group(2)}"
    m = re.search(r"\b(\d{7})\b", name)
    if m:
        return m.group(1)

    product_id = int(item.get("product_id") or 0)
    if product_id > 0:
        try:
            from sync_app.core.wc_sync_helper import wc_rest_request

            cfg = load_secure_config(None) or {}
            resp = wc_rest_request(cfg, "GET", f"products/{product_id}", timeout=20)
            if resp.status_code == 200:
                return (resp.json().get("sku") or "").strip()
        except Exception:
            pass
    return ""


def resolve_line_item_variant(cursor, item):
    """تطبیق یک خط سفارش ووکامرس/پرستاشاپ به کد کالا و واریانت ERP."""
    # حالتِ ۱ از تبِ «تطبیقِ ساختاری»: این واریانتِ سایت در واقع یک SKUِ
    # سادهٔ ERPِ مستقله (نه واریانتِ خودِ محصول) — قبل از هر تلاشِ دیگه‌ای
    # چک می‌کنیم، چون SKUِ خودِ این واریانت رویِ سایت با کدِ ERP فرقی داره.
    try:
        site_parent_id = int(item.get("product_id") or 0)
        site_variation_id = int(item.get("variation_id") or 0)
    except (TypeError, ValueError):
        site_parent_id = site_variation_id = 0
    if site_parent_id and site_variation_id:
        from sync_app.core.structure_mismatch_override import find_erp_sku_for_site_variation

        forced_sku = find_erp_sku_for_site_variation(site_parent_id, site_variation_id)
        if forced_sku:
            return forced_sku, None, None, forced_sku

    sku = infer_line_item_sku(item)
    a_code, poshak_id_c, parts = parse_sku(sku)

    poshak_id_f = None
    r_arcode_c = None

    if a_code and poshak_id_c is not None:
        poshak_id_f, r_arcode_c = resolve_variant_by_codes(cursor, a_code, poshak_id_c)

    if (poshak_id_f is None or r_arcode_c is None) and a_code and len(parts) >= 3:
        size_name = parts[1]
        color_name = parts[2]
        poshak_id_f, r_arcode_c = resolve_variant_by_names(cursor, a_code, size_name, color_name)

    # واریانت از متادیتای خط سفارش (محصول متغیر ووکامرس)
    if (poshak_id_f is None or r_arcode_c is None) and a_code:
        meta = item.get("meta_data") or []
        size_name = ""
        color_name = ""
        for m in meta:
            key = (m.get("key") or "").lower()
            val = (m.get("value") or "").strip()
            if key in ("pa_size", "size", "سایز"):
                size_name = val
            elif key in ("pa_color", "color", "رنگ"):
                color_name = val
        if size_name or color_name:
            poshak_id_f, r_arcode_c = resolve_variant_by_names(
                cursor, a_code, size_name or "", color_name or ""
            )

    # حالتِ ۲ از تبِ «تطبیقِ ساختاری»: این کدِ ERP رویِ سایت به‌عنوانِ یک
    # محصولِ سادهٔ بدونِ انتخابِ رنگ/سایز فروخته می‌شه، پس خطِ سفارش هیچ
    # نشونه‌ای از زیرواریانت نداره — باید همون زیرواریانتِ ثابتی که کاربر
    # در تبِ «تطبیقِ ساختاری» به‌عنوانِ منبعِ قیمت/موجودی انتخاب کرده،
    # به فروش نسبت داده بشه.
    if (poshak_id_f is None or r_arcode_c is None) and a_code:
        from sync_app.core.structure_mismatch_override import get_force_simple_source

        source_sku = get_force_simple_source(a_code)
        if source_sku:
            _src_code, src_poshak_id_c, _src_parts = parse_sku(source_sku)
            if src_poshak_id_c is not None:
                poshak_id_f, r_arcode_c = resolve_variant_by_codes(cursor, a_code, src_poshak_id_c)

    return a_code, poshak_id_f, r_arcode_c, sku


def _format_qty(qty):
    qty = float(qty or 0)
    if qty <= 0:
        return "0"
    if abs(qty - round(qty)) < 1e-9:
        return str(int(round(qty)))
    return str(qty).rstrip("0").rstrip(".")


def build_r_commen(cursor, poshak_id_f, qty):
    """
    متن چاپ فاکتور: سایز-رنگ*تعداد (نام‌ها از جدول Poshak، مثل نمونه اکسل کارفرما).
    """
    if not poshak_id_f:
        return ""
    cursor.execute("""
        SELECT parent.A_Name AS size_name, child.A_Name AS color_name
        FROM Poshak AS child
        INNER JOIN Poshak AS parent ON child.ParentID = parent.ID
        WHERE child.ID = ?
    """, (int(poshak_id_f),))
    row = cursor.fetchone()
    if not row:
        return ""
    size_name = (row[0] or "").strip()
    color_name = (row[1] or "").strip()
    if not size_name and not color_name:
        return ""
    if size_name and color_name:
        return f"{size_name}-{color_name}*{_format_qty(qty)}"
    return f"{size_name or color_name}*{_format_qty(qty)}"


def _line_unit_price(item, config):
    qty = float(item.get("quantity", 0) or 0.0)
    if qty <= 0:
        return 0.0
    price_val = item.get("price")
    if price_val is None:
        subtotal = float(item.get("subtotal", 0) or 0.0)
        price_val = subtotal / qty if qty > 0 else subtotal
    return wc_total_to_erp_amount(price_val, config)


def _calculate_order_sum_price(order, config):
    """جمع خطوط سفارش (qty × unit)."""
    total = 0.0
    for item in order.get("line_items", []):
        qty = float(item.get("quantity", 0) or 0.0)
        if qty <= 0:
            continue
        total += _line_unit_price(item, config) * qty
    return total


# ---------------------------------------------------------
# 📌 به‌روزرسانی وضعیت سفارش در ووکامرس
# ---------------------------------------------------------
def mark_order_completed(order_id):
    if is_ps_mode():
        # طبق تصمیم کاربر: فعلاً وضعیت سفارش روی پرستاشاپ تغییر داده نمی‌شود —
        # فقط در ERP ثبت می‌شود.
        return
    try:
        url = f"{WC_ORDERS_ENDPOINT}/{order_id}"
        requests.put(url, auth=WC_AUTH, json={"status": "completed"})
        log.info(f"✅ وضعیت سفارش {order_id} در ووکامرس به 'completed' تغییر کرد.")
    except Exception as e:
        log.error(f"❌ خطا در آپدیت وضعیت سفارش {order_id} در ووکامرس: {e}")


# ---------------------------------------------------------
# 📌 درج سفارش در دژاوو
# ---------------------------------------------------------
def insert_order(order):
    order_id = order.get("id")
    config = load_secure_config(None) or {}
    total_price = _calculate_order_sum_price(order, config)
    log.info(f"💰 SumPrice سفارش {order_id}: {total_price:,.0f} (جمع خطوط)")
    conn = None
    try:
        conn, _auth_mode, _conn_str = connect_with_fallback(config, timeout=15)
        cursor = conn.cursor()

        cursor.execute("SELECT TOP 1 RqIndex FROM RqTitle WHERE RqIndex2 = ?", (order_id,))
        if cursor.fetchone():
            from sync_app.core.integrations.erp_provider import erp_provider_label

            log.info(f"ℹ️ سفارش {order_id} قبلاً در {erp_provider_label(config)} ثبت شده — رد شد.")
            mark_order_completed(order_id)
            return

        customer_code = resolve_order_customer_code(order, config, cursor)

        # درج در RqTitle و گرفتن RqIndex
        cursor.execute("""
            INSERT INTO RqTitle (
                RqIndex2, RqType, R_CusCode, R_Date, T_Date, T_Time, SumPrice,
                OkModir, UserName, ShowOrHide, R_Time
            )
            OUTPUT INSERTED.RqIndex
            VALUES (?, 'F', ?, GETDATE(), GETDATE(), GETDATE(),
                    ?, 0, 1, 1, GETDATE())
        """, (order_id, customer_code, total_price))
        rqindex_id = int(cursor.fetchone()[0])
        fac_code_str = f"{rqindex_id:06d}"

        # تجمیع خطوط بر اساس کد کالا — یک RQDetail + چند ItemFact
        groups = defaultdict(list)
        skipped = []

        for item in order.get("line_items", []):
            qty = float(item.get("quantity", 0) or 0.0)
            if qty <= 0:
                continue

            a_code, poshak_id_f, r_arcode_c, sku = resolve_line_item_variant(cursor, item)
            if not a_code or r_arcode_c is None or poshak_id_f is None:
                skipped.append(sku or item.get("name") or "?")
                log.warning(f"⚠️ تطبیق واریانت یافت نشد: order={order_id}, sku='{sku}'")
                continue

            unit_price = _line_unit_price(item, config)
            r_commen_part = build_r_commen(cursor, poshak_id_f, qty)
            groups[a_code].append({
                "poshak_id_f": poshak_id_f,
                "qty": qty,
                "unit_price": unit_price,
                "line_cost": unit_price * qty,
                "r_commen_part": r_commen_part,
                "item_name": (item.get("name") or "").strip(),
            })

        if not groups:
            conn.rollback()
            log.warning(f"⚠️ سفارش {order_id} هیچ ردیف معتبری نداشت، رول‌بک شد.")
            return

        detail_index = 0
        for a_code, variants in groups.items():
            detail_index += 1

            cursor.execute("SELECT A_code_c, A_name FROM Article WHERE A_code = ?", (a_code,))
            article_row = cursor.fetchone()
            a_code_c = article_row[0] if article_row else ""
            a_name = article_row[1] if article_row else (variants[0].get("item_name") or "")

            total_qty = sum(v["qty"] for v in variants)
            total_cost = sum(v["line_cost"] for v in variants)
            commen_parts = [v["r_commen_part"] for v in variants if v["r_commen_part"]]
            r_commen = "/".join(commen_parts)
            if not r_commen:
                r_commen = variants[0].get("item_name") or a_name or ""

            cursor.execute("""
                INSERT INTO RqDetail (
                    RqIndex, RqType,
                    R_ArCode, R_ArCode_C,
                    R_ArName, R_Few, R_FewAval,
                    R_Cost, R_Commen, Unit_Code,
                    OkReceive, Show_Or_Hide, IndexHlp
                )
                VALUES (?, 'F',
                        ?, ?,
                        ?, ?, ?,
                        ?, ?, 0,
                        0, NULL, ?)
            """, (
                rqindex_id,
                a_code, a_code_c,
                a_name, total_qty, total_qty,
                total_cost, r_commen, detail_index
            ))

            for variant in variants:
                cursor.execute("""
                    INSERT INTO ItemFact (
                        Fac_Code, Fac_Type, A_Code, A_Index,
                        PoshakIDF, Few, [Index], Price, SelPriceID
                    )
                    VALUES (?, 'J', ?, ?, ?, ?, 0, 0, 1)
                """, (
                    fac_code_str, a_code, detail_index,
                    variant["poshak_id_f"], variant["qty"]
                ))

        conn.commit()
        inserted_details = len(groups)
        inserted_facts = sum(len(v) for v in groups.values())
        log.info(
            f"✅ سفارش {order_id} ثبت شد. "
            f"(RqIndex={rqindex_id}, RQDetail={inserted_details}, ItemFact={inserted_facts})"
        )
        if skipped:
            log.warning(f"⚠️ خطوط ردشده سفارش {order_id}: {', '.join(skipped)}")

        mark_order_completed(order_id)

    except Exception as e:
        if conn:
            conn.rollback()
        log.error(f"❌ خطا در ثبت سفارش {order_id}: {e}")

    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------
# 📌 اجرای اصلی — پرستاشاپ
# ---------------------------------------------------------
def _main_prestashop():
    from sync_app.core.ps_order_helper import ps_list_paid_orders

    cfg = load_secure_config(None) or {}
    if not SQL_CONN_STRING:
        raise RuntimeError("SQL_CONN_STRING خالی است.")

    try:
        orders = ps_list_paid_orders(cfg, timeout=60)
    except Exception as e:
        log.error(f"❌ خطا در دریافت سفارش‌های پرستاشاپ: {e}")
        raise RuntimeError(f"خطا در ارتباط با پرستاشاپ: {e}") from e

    log.info(f"📦 تعداد سفارش‌های پرداخت‌شده (valid=1): {len(orders)}")
    if not orders:
        log.info("ℹ️ سفارش جدیدی یافت نشد.")
        return {"ok": True, "orders": 0}

    for order in orders:
        insert_order(order)

    log.info("✅ پایان عملیات همگام‌سازی سفارشات.")
    return {"ok": True, "orders": len(orders)}


# ---------------------------------------------------------
# 📌 اجرای اصلی
# ---------------------------------------------------------
def main():
    log.info("▶️ شروع همگام‌سازی سفارشات...")
    init_runtime_config()

    if is_ps_mode():
        return _main_prestashop()

    try:
        validate_config()
    except Exception as e:
        log.error(f"❌ خطا در تنظیمات: {e}")
        raise RuntimeError(f"خطا در تنظیمات: {e}") from e

    from sync_app.core.scripts.woocommerce_store_setup import (
        StorePagesNotReadyError,
        ensure_store_pages,
        store_pages_ready,
        store_setup_user_message,
    )
    from sync_app.core.wc_sync_helper import apply_network_overrides, format_wc_network_error

    cfg = load_secure_config(None) or {}
    apply_network_overrides(cfg)

    if not store_pages_ready(cfg):
        _log_store = "▸ بررسی صفحات Cart/Checkout..."
        log.info(_log_store)
        try:
            report = ensure_store_pages(cfg)
            if not report.get("ready"):
                raise StorePagesNotReadyError(store_setup_user_message())
        except StorePagesNotReadyError:
            raise
        except Exception as exc:
            raise StorePagesNotReadyError(
                f"{store_setup_user_message()}\n\n{format_wc_network_error(exc)}"
            ) from exc
    else:
        log.info("✅ صفحات Cart/Checkout آماده‌اند")

    try:
        from sync_app.core.wc_sync_helper import wc_rest_request, wc_http_error_message

        cfg = load_secure_config(None) or {}
        response = wc_rest_request(
            cfg,
            "GET",
            "orders",
            params={"status": "processing"},
            timeout=30,
        )
        log.info(f"📡 پاسخ ووکامرس: status={response.status_code}")

        if int(response.status_code or 0) >= 400:
            msg = wc_http_error_message(
                response,
                cfg,
                prefix="خطا در دریافت سفارشات",
            )
            log.error(f"❌ {msg}")
            raise RuntimeError(msg)

        orders = response.json()
        log.info(f"📦 تعداد سفارش‌های دریافتی: {len(orders)}")

        if not orders:
            log.info("ℹ️ سفارش جدیدی یافت نشد.")
            return {"ok": True, "orders": 0}

        for order in orders:
            insert_order(order)

    except StorePagesNotReadyError:
        raise
    except RuntimeError:
        raise
    except Exception as e:
        log.error(f"❌ خطا در ارتباط با ووکامرس: {e}")
        raise RuntimeError(f"خطا در ارتباط با ووکامرس: {e}") from e

    log.info("✅ پایان عملیات همگام‌سازی سفارشات.")
    return {"ok": True, "orders": len(orders)}


if __name__ == "__main__":
    main()
