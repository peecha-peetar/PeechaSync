"""ثبتِ مشتریِ جدید در ERP (دژاوو/هلو) — سه روشِ واقعیِ خودِ دژاوو.

طبقِ بررسیِ Trace هایِ واقعیِ SQL Profiler روی دژاوو، سه روشِ متفاوت برای
تعریفِ یک طرف‌حساب (مشتری) وجود داره که هرکدوم SarFasl_Code/SarBes/
Tafzili_Code متفاوتی می‌سازن:

  ۱) خودکار (auto): کاربر هیچی انتخاب نمی‌کنه — کدِ کل ثابتِ «۱۰۳»،
     معین با MAX+1 اتوماتیک، تفضیلی خالی. SarBes خالی.
  ۲) انتخابِ کل (kol): کاربر کدِ کل رو از بینِ کل‌هایِ زیرمجموعهٔ
     بدهکاران (SARFASL با Type=5) انتخاب می‌کنه؛ معین همچنان با MAX+1
     اتوماتیک محاسبه می‌شه، تفضیلی خالی. SarBes='401'.
  ۳) انتخابِ کل و معین (tafzili): کاربر هم کدِ کل هم معینِ زیرِ همون کل
     رو انتخاب می‌کنه؛ یک ردیفِ تفضیلیِ جدید با MAX+1 زیرِ همون معین
     ساخته می‌شه. SarBes='401'.

در هر سه روش، بعدِ ساختِ ردیفِ SARFASL، فیلدِ Parent بایدی به آیدیِ
سرفصلِ سطحِ بالاتر وصل بشه (UPDATE sarfasl SET Parent=...) — این مرحله
در نسخه‌هایِ قبلیِ PeechaSync جا افتاده بود و بدونِ اون، مشتریِ ساخته‌شده
درستش زیرِ «زیرمجموعهٔ معینِ بدهکاران» در خودِ دژاوو نشون داده نمی‌شه."""

from __future__ import annotations

METHOD_AUTO = "auto"
METHOD_KOL = "kol"
METHOD_TAFZILI = "tafzili"

_VALID_METHODS = {METHOD_AUTO, METHOD_KOL, METHOD_TAFZILI}
_DEBTOR_SARFASL_TYPE = 5


def get_customer_creation_method(config: dict | None) -> str:
    method = str((config or {}).get("CUSTOMER_CREATION_METHOD") or METHOD_AUTO).strip()
    return method if method in _VALID_METHODS else METHOD_AUTO


def extract_mobile(billing: dict) -> str:
    """موبایلِ مشتری از فیلدِ phone بیرون می‌کشه — قراردادِ مشترکِ کلِ
    برنامه: اگه phone به شکلِ «تلفن/موبایل» باشه، بخشِ دومی موبایله؛ اگه
    فقط یک شماره داده شده (بدونِ «/»)، همون رو موبایل حساب می‌کنیم."""
    raw = str(billing.get("phone") or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if not parts:
        return ""
    return parts[1] if len(parts) > 1 else parts[0]


def list_debtor_kol_codes(cursor) -> list[tuple[str, str]]:
    """کدهایِ کل (سرفصلِ سطحِ بالا) که زیرمجموعهٔ بدهکارانن — یعنی در
    SARFASL نوعشون (Type) برابرِ ۵ است و خودشون سطحِ معین/تفضیلی ندارن.
    خروجی: [(کدِ کل, نام), ...]."""
    try:
        cursor.execute(
            """
            SELECT DISTINCT Col_Code, SarFasl_Name FROM SARFASL
            WHERE Type = ?
              AND (Moien_Code = '' OR Moien_Code IS NULL)
              AND (Tafzili_Code = '' OR Tafzili_Code IS NULL)
            ORDER BY Col_Code
            """,
            (_DEBTOR_SARFASL_TYPE,),
        )
        return [
            (str(r[0]).strip(), str(r[1] or "").strip())
            for r in cursor.fetchall() or []
            if r and str(r[0] or "").strip()
        ]
    except Exception:
        return []


def list_moien_codes_for_kol(cursor, col_code: str) -> list[tuple[str, str]]:
    """معین‌هایِ از‌قبل‌موجود زیرِ یک کدِ کلِ مشخص — برایِ کمبویِ دومِ
    روشِ «انتخابِ کل و معین». خروجی: [(کدِ معین, نام), ...]."""
    col_code = str(col_code or "").strip()
    if not col_code:
        return []
    try:
        cursor.execute(
            """
            SELECT DISTINCT Moien_Code, SarFasl_Name FROM SARFASL
            WHERE Type = ? AND Col_Code = ? AND Moien_Code <> ''
              AND (Tafzili_Code = '' OR Tafzili_Code IS NULL)
            ORDER BY Moien_Code
            """,
            (_DEBTOR_SARFASL_TYPE, col_code),
        )
        return [
            (str(r[0]).strip(), str(r[1] or "").strip())
            for r in cursor.fetchall() or []
            if r and str(r[0] or "").strip()
        ]
    except Exception:
        return []


def _next_padded_code(cursor, sql: str, params: tuple, width: int) -> str:
    cursor.execute(sql, params)
    row = cursor.fetchone()
    try:
        max_val = int(row[0]) if row and row[0] is not None else 0
    except (TypeError, ValueError):
        max_val = 0
    return str(max_val + 1).zfill(width)


def next_customer_code(cursor) -> str:
    return _next_padded_code(cursor, "SELECT MAX(CAST(C_Code_C AS INT)) FROM Customer", (), 5)


def next_moien_code(cursor, col_code: str) -> str:
    return _next_padded_code(
        cursor,
        "SELECT MAX(CAST(Moien_Code AS INT)) FROM SARFASL WHERE Col_Code = ? AND Moien_Code <> ''",
        (str(col_code or "").strip(),),
        4,
    )


def next_tafzili_code(cursor, col_code: str, moien_code: str) -> str:
    return _next_padded_code(
        cursor,
        "SELECT MAX(CAST(Tafzili_Code AS INT)) FROM SARFASL "
        "WHERE Col_Code = ? AND Moien_Code = ? AND Tafzili_Code <> ''",
        (str(col_code or "").strip(), str(moien_code or "").strip()),
        4,
    )


def _sarfasl_id(cursor, sarfasl_code: str) -> int | None:
    cursor.execute("SELECT [ID] FROM Sarfasl WHERE Sarfasl_Code = ?", (sarfasl_code,))
    row = cursor.fetchone()
    if row and row[0] is not None:
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return None
    return None


def _link_parent(cursor, col_code: str, moien_code: str, tafzili_code: str) -> None:
    """ردیفِ SARFASLِ تازه‌ساخته‌شده رو به سرفصلِ سطحِ بالاترِ خودش وصل
    می‌کنه (Parent) — دقیقاً همون مرحله‌ای که در هر سه روشِ واقعیِ دژاوو
    دیده شد. اگه سطحِ تفضیلی ساخته شده، والدش سطحِ معینه؛ وگرنه والدش
    خودِ کلِ (col_code) است."""
    parent_sarfasl_code = f"{col_code}{moien_code}" if tafzili_code else col_code
    parent_id = _sarfasl_id(cursor, parent_sarfasl_code)
    if parent_id is None:
        return
    cursor.execute(
        "UPDATE sarfasl SET Parent = ? WHERE Parent IS NULL AND Col_Code = ? "
        "AND Moien_Code = ? AND Tafzili_Code = ?",
        (parent_id, col_code, moien_code, tafzili_code or ""),
    )


def resolve_sarfasl_location(cursor, config: dict | None) -> tuple[str, str, str]:
    """بر اساسِ روشِ انتخاب‌شده در تنظیمات، (کدِ کل، کدِ معین، کدِ تفضیلی)
    را برمی‌گردونه — تفضیلی و/یا معین ممکنه خالی باشن، بسته به روش."""
    method = get_customer_creation_method(config)
    cfg = config or {}

    if method == METHOD_KOL:
        col_code = str(cfg.get("CUSTOMER_KOL_CODE") or "103").strip() or "103"
        return col_code, next_moien_code(cursor, col_code), ""

    if method == METHOD_TAFZILI:
        col_code = str(cfg.get("CUSTOMER_KOL_CODE") or "103").strip() or "103"
        moien_code = str(cfg.get("CUSTOMER_MOIEN_CODE") or "").strip()
        if not moien_code:
            # تنظیمِ ناقص (معین انتخاب نشده) — مثلِ روشِ «انتخابِ کل» رفتار کن
            return col_code, next_moien_code(cursor, col_code), ""
        return col_code, moien_code, next_tafzili_code(cursor, col_code, moien_code)

    # METHOD_AUTO
    col_code = "103"
    return col_code, next_moien_code(cursor, col_code), ""


def create_customer_record(cursor, billing: dict, config: dict | None) -> str | None:
    """ثبتِ یک مشتریِ جدید — SARFASL + Customersarfasl + Customer + وصل‌کردنِ
    Parent — رویِ همون cursor/تراکنشِ صدازننده (برایِ سازگاری با نوشتنِ
    تراکنشیِ سفارش، و هم برایِ همگام‌سازیِ دسته‌ایِ مشتریان با اتصالِ خودشون).
    فیلدهایِ جدولِ Customer نسبت به نسخه‌هایِ قبلی حذف نشدن، فقط
    Tafzili_Code_Bed برایِ روشِ «انتخابِ کل و معین» اضافه شده."""
    from sync_app.core.sync_utils import log

    col_code, moien_code, tafzili_code = resolve_sarfasl_location(cursor, config)
    method = get_customer_creation_method(config)
    sar_bes = "" if method == METHOD_AUTO else "401"

    customer_code = next_customer_code(cursor)
    sarfasl_code = f"{col_code}{moien_code}{tafzili_code}"

    first = str(billing.get("first_name") or "").strip()
    last = str(billing.get("last_name") or "").strip()
    customer_name = f"{first} {last}".strip() or str(billing.get("username") or "").strip() or "مشتری ناشناس"
    email = str(billing.get("email") or "").strip()
    mobile = extract_mobile(billing)
    tel = str(billing.get("phone") or "").split("/")[0].strip()
    national_code = billing.get("national_code", "0000000000")

    try:
        cursor.execute(
            """
            INSERT INTO SARFASL
            (SarFasl_Name, Common, Col_Code, Moien_Code, Tafzili_Code, SarFasl_Code, [Group], Mahiat, Can_Delete, Type)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, 0, ?)
            """,
            (customer_name, customer_code, col_code, moien_code, tafzili_code, sarfasl_code, _DEBTOR_SARFASL_TYPE),
        )
        cursor.execute(
            "INSERT INTO Customersarfasl (CustCode, SarBed, SarBes) VALUES (?, ?, ?)",
            (customer_code, sarfasl_code, sar_bes),
        )
        cursor.execute(
            """
            INSERT INTO Customer (
                C_Code, C_Name, C_Code_C, C_Address, C_Tel, C_Mobile,
                Email_Address, Economic_Code, Col_Code_Bed, Moien_Code_Bed, Tafzili_Code_Bed,
                Kharid, Forosh, Cust_City, Cust_Mantagheh, Cust_Ostan,
                Zip_Code, National_Code
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_code, customer_name, customer_code,
                f"{billing.get('state', '')},{billing.get('city', '')},{billing.get('address_1', '')},",
                tel, mobile, email,
                billing.get("company", "123456789"),
                col_code, moien_code, tafzili_code,
                1, 1,
                billing.get("city", ""), "منطقه",
                billing.get("state", ""), billing.get("postcode", "0000000000"),
                national_code,
            ),
        )
        _link_parent(cursor, col_code, moien_code, tafzili_code)
    except Exception as exc:
        log.error(f"❌ خطا در ثبتِ مشتریِ جدید ({email or mobile or '—'}): {exc}")
        return None

    log.info(f"🆕 مشتریِ جدید ثبت شد: {customer_name} (کد {customer_code}، سرفصل {sarfasl_code})")
    return customer_code
