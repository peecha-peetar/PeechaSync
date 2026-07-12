import pyodbc
import requests
from datetime import datetime

# imports
try:
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_utils import log, app_path
    from sync_app.core.customer_context import get_customer_mode
    from sync_app.core.wc_api_helper import wc_endpoint, get_wc_auth, wc_rest_base
except ImportError:
    class MockLog:
        def info(self, msg): print("INFO:", msg)
        def error(self, msg): print("ERROR:", msg)
        def warning(self, msg): print("WARN:", msg)
    log = MockLog()
    def load_secure_config(_): return {}
    def app_path(name): return name


# runtime config
SQL_CONN_STRING = ""
WC_API_URL = ""
WC_CONSUMER_KEY = ""
WC_CONSUMER_SECRET = ""
WC_TIMEOUT = 120
WC_CUSTOMERS_ENDPOINT = ""
WC_AUTH = ("", "")


def init_runtime_config():
    global SQL_CONN_STRING, WC_API_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET
    global WC_TIMEOUT, WC_CUSTOMERS_ENDPOINT, WC_AUTH

    config = load_secure_config(None) or {}
    SQL_CONN_STRING = config.get("SQL_CONN_STRING", "")
    WC_API_URL = config.get("WC_URL", "")
    WC_CONSUMER_KEY = config.get("WC_CONSUMER_KEY", "")
    WC_CONSUMER_SECRET = config.get("WC_CONSUMER_SECRET", "")
    WC_TIMEOUT = config.get("WC_TIMEOUT", 120)
    WC_CUSTOMERS_ENDPOINT = wc_endpoint(WC_API_URL, "customers")
    WC_AUTH = get_wc_auth(config)


def _wc_runtime_config():
    return load_secure_config(None) or {}


def _wc_get_json(path, *, params=None, timeout=None, config=None):
    from sync_app.core.wc_sync_helper import wc_rest_request, wc_http_error_message

    cfg = dict(config or _wc_runtime_config())
    resp = wc_rest_request(cfg, "GET", path, params=params, timeout=timeout)
    if int(resp.status_code or 0) >= 400:
        raise RuntimeError(
            wc_http_error_message(resp, cfg, prefix=f"دریافت {path} ناموفق")
        )
    data = resp.json()
    return data


# validate
def validate_config():
    if not SQL_CONN_STRING:
        raise RuntimeError("SQL_CONN_STRING خالی است.")
    if not WC_API_URL or not WC_CONSUMER_KEY or not WC_CONSUMER_SECRET:
        raise RuntimeError("تنظیمات WooCommerce ناقص است.")


# SQL connect
def get_db_connection():
    try:
        conn = pyodbc.connect(SQL_CONN_STRING, timeout=10)
        return conn, conn.cursor()
    except Exception as ex:
        log.error(f"❌ خطای اتصال دیتابیس: {ex}")
        return None, None


# کد جدید
def get_next_customer_code():
    conn, cursor = get_db_connection()
    if not conn:
        return "00001"
    try:
        cursor.execute("SELECT MAX(CAST(C_Code_C AS INT)) FROM Customer")
        max_code = cursor.fetchone()[0]
        return str((max_code or 0) + 1).zfill(5)
    except:
        return "00001"
    finally:
        conn.close()


def get_last_moien_code():
    conn, cursor = get_db_connection()
    if not conn:
        return "0001"
    try:
        cursor.execute("""
            SELECT MAX(CAST(Moien_Code AS INT))
            FROM SARFASL
            WHERE Col_Code = '103'
        """)
        max_moien = cursor.fetchone()[0]
        return str((max_moien or 0) + 1).zfill(4)
    except:
        return "0001"
    finally:
        conn.close()


# مشتریان Woo (با سفارش)
def get_customer_ids_from_orders():
    """ customer idهای با سفارش """
    customer_ids = set()
    page = 1
    had_error = False

    while True:
        try:
            orders = _wc_get_json(
                "orders",
                params={"per_page": 100, "page": page, "status": "any"},
                timeout=WC_TIMEOUT,
            )
            if not orders:
                break

            for order in orders:
                cid = order.get("customer_id", 0)
                if cid and cid > 0:  # صفر یعنی خرید مهمان، نادیده گرفته می‌شود
                    customer_ids.add(cid)

            # آخرین صفحه
            if len(orders) < 100:
                break
            page += 1

        except Exception as e:
            had_error = True
            log.error(f"❌ خطای دریافت سفارشات (صفحه {page}): {e}")
            break

    if had_error:
        return None

    log.info(f"📦 {len(customer_ids)} مشتری دارای سفارش یافت شد.")
    return customer_ids


def _fetch_all_orders():
    """ همه سفارش‌ها paginate """
    all_orders = []
    page = 1
    while True:
        batch = _wc_get_json(
            "orders",
            params={"per_page": 100, "page": page, "status": "any"},
            timeout=WC_TIMEOUT,
        )
        if not batch:
            break
        all_orders.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return all_orders


def _fetch_orders_preview(*, max_orders=50, timeout=None):
    """فقط چند سفارش اخیر — برای پیش‌نمایش تب مشتریان."""
    timeout = timeout or WC_TIMEOUT
    per_page = max(1, min(int(max_orders or 50), 100))
    batch = _wc_get_json(
        "orders",
        params={
            "per_page": per_page,
            "page": 1,
            "status": "any",
            "orderby": "date",
            "order": "desc",
        },
        timeout=timeout,
    )
    return batch if isinstance(batch, list) else []


def get_buyers_preview_from_orders(*, max_orders=50, max_customer_lookups=30, timeout=None):
    """
    لیست خریداران دارای سفارش برای نمایش در تب مشتریان.
    شامل ثبت‌نام‌شده (customer_id>0) و مهمان (خرید بدون حساب کاربری).
    """
    request_timeout = timeout or WC_TIMEOUT
    try:
        orders = _fetch_orders_preview(max_orders=max_orders, timeout=request_timeout)
    except Exception as e:
        log.error(f"❌ خطای دریافت سفارشات برای پیش‌نمایش مشتری: {e}")
        raise RuntimeError("دریافت سفارشات ووکامرس ناموفق بود (مشکل شبکه/Timeout).") from e

    registered_ids = set()
    guests_by_email = {}

    for order in orders:
        cid = int(order.get("customer_id") or 0)
        if cid > 0:
            registered_ids.add(cid)
            continue
        billing = order.get("billing") or {}
        email = (billing.get("email") or "").strip().lower()
        if not email:
            continue
        first = (billing.get("first_name") or "").strip()
        last = (billing.get("last_name") or "").strip()
        guests_by_email[email] = {
            "id": 0,
            "email": email,
            "first_name": first,
            "last_name": last,
            "username": "",
            "billing": billing,
            "_guest": True,
        }

    customers = []
    lookup_limit = max(1, int(max_customer_lookups or 30))
    for cid in sorted(registered_ids)[:lookup_limit]:
        try:
            customer = _wc_get_json(f"customers/{cid}", timeout=request_timeout)
            if customer and not customer.get("code"):
                customers.append(customer)
        except Exception as e:
            log.error(f"❌ خطا در دریافت مشتری {cid}: {e}")

    customers.extend(guests_by_email.values())
    log.info(
        f"📦 پیش‌نمایش خریداران: {len(registered_ids)} ثبت‌نام‌شده، "
        f"{len(guests_by_email)} مهمان"
    )
    return customers


def get_woo_customers():
    """ فقط با سفارش """
    customer_ids = get_customer_ids_from_orders()
    if customer_ids is None:
        raise RuntimeError("دریافت سفارشات ووکامرس ناموفق بود (مشکل شبکه/Timeout).")

    if not customer_ids:
        log.warning("⚠️ هیچ مشتری دارای سفارشی یافت نشد.")
        return []

    customers = []
    for cid in customer_ids:
        try:
            customer = _wc_get_json(f"customers/{cid}", timeout=WC_TIMEOUT)
            if customer and not customer.get("code"):  # code نشانه خطاست
                customers.append(customer)
        except Exception as e:
            log.error(f"❌ خطا در دریافت مشتری {cid}: {e}")

    log.info(f"✅ {len(customers)} مشتری آماده همگام‌سازی.")
    return customers


def get_all_woo_customers(*, max_customers=0, timeout=None):
    """ همه مشتریان paginate — max_customers>0 برای پیش‌نمایش تب """
    customers = []
    request_timeout = timeout or WC_TIMEOUT
    per_page = 100 if not max_customers else max(1, min(int(max_customers), 100))
    page = 1
    while True:
        try:
            batch = _wc_get_json(
                "customers",
                params={"per_page": per_page, "page": page},
                timeout=request_timeout,
            )
            if not batch:
                break
            customers.extend(batch)
            if max_customers and len(customers) >= max_customers:
                customers = customers[:max_customers]
                break
            if len(batch) < per_page:
                break
            page += 1
        except Exception as exc:
            log.error(f"❌ خطا در دریافت مشتریان (صفحه {page}): {exc}")
            break
    log.info(f"📦 {len(customers)} مشتری از ووکامرس دریافت شد.")
    return customers


def fetch_customers_for_sync(config=None):
    """ منبع از DEFAULT_CUSTOMER_MODE """
    config = config or load_secure_config(None) or {}
    mode = get_customer_mode(config)
    if mode == "fixed":
        log.info("حالت مشتری ثابت: همگام‌سازی مشتریان سایت غیرفعال است.")
        return []
    if mode == "all":
        return get_all_woo_customers()
    return get_woo_customers()


# exists check
def customer_exists(email):
    conn, cursor = get_db_connection()
    if not conn:
        return None
    try:
        cursor.execute("""
            SELECT C_Code, Moien_Code_Bed
            FROM Customer
            WHERE Email_Address = ?
        """, (email,))
        row = cursor.fetchone()
        return (row[0], row[1]) if row else None
    except Exception as e:
        log.error(f"❌ خطا در بررسی مشتری: {e}")
        return None
    finally:
        conn.close()


# insert
def sync_customer(customer_data, new_moien):
    conn, cursor = get_db_connection()
    if not conn:
        return

    try:
        customer_code = get_next_customer_code()

        first = customer_data.get("first_name", "")
        last = customer_data.get("last_name", "")
        customer_name = (first + " " + last).strip() or customer_data.get("username", "مشتری ناشناس")

        billing = customer_data.get("billing", {})
        phone_parts = billing.get("phone", "").split("/")
        tel = phone_parts[0].strip() if phone_parts else ""
        mobile = phone_parts[1].strip() if len(phone_parts) > 1 else ""

        email_value = customer_data.get("email", "")
        national_code = billing.get("national_code", "0000000000")

        sarfasl_code = f"103{new_moien}"

        # insert SARFASL
        cursor.execute("""
            INSERT INTO SARFASL
            (SarFasl_Name, Common, Col_Code, Moien_Code, Tafzili_Code, SarFasl_Code, [Group], Mahiat, Can_Delete, Type)
            VALUES (?, ?, '103', ?, '', ?, 1, 1, 0, 5)
        """, (customer_name, customer_code, new_moien, sarfasl_code))

        # Customersarfasl
        cursor.execute("""
            INSERT INTO Customersarfasl (CustCode, SarBed, SarBes)
            VALUES (?, ?, '401')
        """, (customer_code, sarfasl_code))

        # Customer
        cursor.execute("""
            INSERT INTO Customer (
                C_Code, C_Name, C_Code_C, C_Address, C_Tel, C_Mobile,
                Email_Address, Economic_Code, Col_Code_Bed, Moien_Code_Bed,
                Kharid, Forosh, Cust_City, Cust_Mantagheh, Cust_Ostan,
                Zip_Code, National_Code
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            customer_code, customer_name, customer_code,
            f"{billing.get('state','')},{billing.get('city','')},{billing.get('address_1','')},",
            tel, mobile, email_value,
            billing.get("company", "123456789"),
            "103", new_moien,
            1, 1,
            billing.get("city", ""), "منطقه",
            billing.get("state", ""), billing.get("postcode", "0000000000"),
            national_code
        ))

        conn.commit()
        log.info(f"🆕 مشتری جدید ثبت شد: {customer_name}")

    except Exception as e:
        log.error(f"❌ خطا در درج مشتری {email_value}: {e}")

    finally:
        conn.close()


# update
def update_customer(customer_data, customer_code, moien_code):
    conn, cursor = get_db_connection()
    if not conn:
        return

    try:
        first = customer_data.get("first_name", "")
        last = customer_data.get("last_name", "")
        customer_name = (first + " " + last).strip() or customer_data.get("username", "مشتری ناشناس")

        billing = customer_data.get("billing", {})
        phone_parts = billing.get("phone", "").split("/")
        tel = phone_parts[0].strip() if phone_parts else ""
        mobile = phone_parts[1].strip() if len(phone_parts) > 1 else ""

        national_code = billing.get("national_code", "0000000000")
        sarfasl_code = f"103{moien_code}"

        # update SARFASL
        cursor.execute("""
            UPDATE SARFASL
            SET SarFasl_Name = ?
            WHERE SarFasl_Code = ?
        """, (customer_name, sarfasl_code))

        # update Customer
        cursor.execute("""
            UPDATE Customer
            SET C_Name=?, C_Address=?, C_Tel=?, C_Mobile=?, Economic_Code=?,
                Cust_City=?, Cust_Ostan=?, Zip_Code=?, National_Code=?
            WHERE C_Code=?
        """, (
            customer_name,
            f"{billing.get('state','')},{billing.get('city','')},{billing.get('address_1','')},",
            tel, mobile,
            billing.get("company", "123456789"),
            billing.get("city", ""), billing.get("state", ""),
            billing.get("postcode", "0000000000"),
            national_code,
            customer_code
        ))

        conn.commit()
        log.info(f"🛠️ مشتری آپدیت شد: {customer_name}")

    except Exception as e:
        log.error(f"❌ خطا در آپدیت مشتری {customer_code}: {e}")

    finally:
        conn.close()


# main
def main():
    log.info("▶️ شروع همگام‌سازی مشتریان...")
    init_runtime_config()

    try:
        validate_config()
    except Exception as e:
        log.error(f"❌ خطا در تنظیمات: {e}")
        return

    config = load_secure_config(None) or {}
    try:
        customers = fetch_customers_for_sync(config)
    except Exception as e:
        log.error(f"❌ توقف همگام‌سازی مشتریان: {e}")
        return

    if not customers:
        log.warning("⚠️ هیچ مشتری‌ای یافت نشد.")
        return

    try:
        last_moien = int(get_last_moien_code()) - 1
    except:
        log.error("❌ خطا در تعیین کد معین.")
        return

    for customer in customers:
        email = customer.get("email", "")
        if not email:
            log.warning("⚠️ مشتری بدون ایمیل رد شد.")
            continue

        exists = customer_exists(email)

        if exists:
            customer_code, moien_code = exists
            update_customer(customer, customer_code, moien_code)
        else:
            last_moien += 1
            new_moien = str(last_moien).zfill(4)
            sync_customer(customer, new_moien)

    log.info("🎉 همگام‌سازی مشتریان با موفقیت پایان یافت.")


if __name__ == "__main__":
    main()
