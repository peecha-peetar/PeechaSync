""" مشتری پیش‌فرض سفارش/sync """

from __future__ import annotations


def get_customer_mode(config):
    mode = (config or {}).get("DEFAULT_CUSTOMER_MODE", "website")
    return mode if mode in {"website", "fixed", "all"} else "website"


def get_fixed_customer_code(config):
    code = ((config or {}).get("DEFAULT_CUSTOMER_CODE") or "").strip()
    return code or "00005"


def _extract_mobile(billing: dict) -> str:
    """موبایلِ مشتری از فیلدِ phone بیرون می‌کشه — قراردادِ مشترکِ کلِ
    برنامه (هم ووکامرس هم پرستاشاپ، دقیقاً هم‌شکلِ sync_customer در
    customersync.py و _address_to_billing در ps_customer_helper.py):
    اگه phone به شکلِ «تلفن/موبایل» باشه، بخشِ دومی موبایله؛ اگه فقط
    یک شماره داده شده (بدونِ «/»)، همون رو موبایل حساب می‌کنیم — چون
    امروز اغلب چک‌اوت‌ها فقط یک شماره (که معمولاً موبایله) می‌گیرن."""
    raw = str(billing.get("phone") or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if not parts:
        return ""
    return parts[1] if len(parts) > 1 else parts[0]


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


def _next_customer_code(cursor) -> str | None:
    try:
        cursor.execute("SELECT MAX(CAST(C_Code_C AS INT)) FROM Customer")
        max_code = cursor.fetchone()[0]
        return str((max_code or 0) + 1).zfill(5)
    except Exception:
        return None


def _next_moien_code(cursor) -> str | None:
    try:
        cursor.execute("SELECT MAX(CAST(Moien_Code AS INT)) FROM SARFASL WHERE Col_Code = '103'")
        max_moien = cursor.fetchone()[0]
        return str((max_moien or 0) + 1).zfill(4)
    except Exception:
        return None


def _create_customer_from_billing(cursor, billing: dict) -> str | None:
    """ثبتِ مشتریِ جدید — دقیقاً هم‌ساختارِ sync_customer در
    customersync.py (SARFASL + Customersarfasl + Customer)، فقط رویِ
    همون کِرسِر/تراکنشِ مشترکِ درجِ سفارش (نه یک اتصالِ جدا) تا اگه
    ثبتِ سفارش شکست خورد، مشتریِ نصفه‌ساخته هم رول‌بک بشه."""
    from sync_app.core.sync_utils import log

    customer_code = _next_customer_code(cursor)
    new_moien = _next_moien_code(cursor)
    if not customer_code or not new_moien:
        log.warning("⚠️ کدِ مشتریِ جدید یا کدِ معین قابلِ‌محاسبه نبود — ثبتِ مشتریِ جدید لغو شد.")
        return None

    first = str(billing.get("first_name") or "").strip()
    last = str(billing.get("last_name") or "").strip()
    customer_name = f"{first} {last}".strip() or "مشتری ناشناس"

    email = str(billing.get("email") or "").strip()
    mobile = _extract_mobile(billing)
    tel = str(billing.get("phone") or "").split("/")[0].strip()
    sarfasl_code = f"103{new_moien}"

    try:
        cursor.execute(
            """
            INSERT INTO SARFASL
            (SarFasl_Name, Common, Col_Code, Moien_Code, Tafzili_Code, SarFasl_Code, [Group], Mahiat, Can_Delete, Type)
            VALUES (?, ?, '103', ?, '', ?, 1, 1, 0, 5)
            """,
            (customer_name, customer_code, new_moien, sarfasl_code),
        )
        cursor.execute(
            "INSERT INTO Customersarfasl (CustCode, SarBed, SarBes) VALUES (?, ?, '401')",
            (customer_code, sarfasl_code),
        )
        cursor.execute(
            """
            INSERT INTO Customer (
                C_Code, C_Name, C_Code_C, C_Address, C_Tel, C_Mobile,
                Email_Address, Economic_Code, Col_Code_Bed, Moien_Code_Bed,
                Kharid, Forosh, Cust_City, Cust_Mantagheh, Cust_Ostan,
                Zip_Code, National_Code
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_code, customer_name, customer_code,
                f"{billing.get('state', '')},{billing.get('city', '')},{billing.get('address_1', '')},",
                tel, mobile, email,
                billing.get("company", "123456789"),
                "103", new_moien,
                1, 1,
                billing.get("city", ""), "منطقه",
                billing.get("state", ""), billing.get("postcode", "0000000000"),
                billing.get("national_code", "0000000000"),
            ),
        )
    except Exception as exc:
        log.error(f"❌ خطا در ثبتِ مشتریِ جدید ({email or mobile or '—'}): {exc}")
        return None

    log.info(f"🆕 مشتریِ جدید از رویِ سفارش ثبت شد: {customer_name} (کد {customer_code})")
    return customer_code


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

    new_code = _create_customer_from_billing(cursor, billing)
    return new_code or fixed_code
