"""POS.Party + PartyPhone + PartyAddress — طرف‌حسابِ سپیدار/دشت، از
مشتریِ سایت (billing سفارش/مشتریِ ووکامرس یا پرستاشاپ).

پیاده‌سازیِ کاملاً مستقل از customer_creation.py/customer_context.py دژاوو
(schemaِ سپیدار کاملاً فرقی داره، هیچ importی از اون‌ها نداریم). INSERT
دقیقاً مطابقِ ترِیسِ واقعیِ سپیدار (Customer.txt / Customer_with_Address.txt).
آدرس فقط وقتی ذخیره می‌شه که هم LocationRefِ پیش‌فرض در تنظیمات ست شده
باشه و هم متنِ آدرسِ سایت خالی نباشه — طبقِ تصمیمِ کاربر."""

from __future__ import annotations

from sync_app.core.scripts.sepidar.sepidar_common import (
    get_default_location_ref,
    load_sepidar_map,
    next_int_code,
    save_sepidar_map,
    sepidar_party_row_lock,
)

_MAP_FILE = "sepidar_customer_map.json"
_PARTY_CODE_WIDTH = 2
_PARTY_ADDRESS_TYPE = 8  # مطابقِ ترِیسِ واقعی (Customer_with_Address.txt)


def extract_mobile(billing: dict) -> str:
    raw = str((billing or {}).get("phone") or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if not parts:
        return ""
    return parts[1] if len(parts) > 1 else parts[0]


def _find_party_by_contact(cursor, email: str, mobile: str) -> int | None:
    conditions = []
    params: list = []
    if email:
        conditions.append("LOWER(LTRIM(RTRIM(Email))) = ?")
        params.append(email)
    if mobile:
        conditions.append("LTRIM(RTRIM(Phone)) = ?")
        params.append(mobile)
    if not conditions:
        return None
    sql = f"SELECT TOP 1 PartyId FROM POS.vwParty WHERE {' OR '.join(conditions)}"
    try:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except Exception:
        pass
    return None


def _next_party_code(cursor) -> tuple[int, str]:
    """PartyId بعدی + کدِ ۲رقمیِ آزاد — مطابقِ چکِ یکتاییِ ترِیسِ واقعی
    (Select Count(1) from POS.[vwParty] where [PartyId] <> @id And [Code] = @num)."""
    party_id = next_int_code(cursor, "POS.Party", "PartyId")
    candidate = 0
    while True:
        candidate += 1
        code = str(candidate).zfill(_PARTY_CODE_WIDTH)
        cursor.execute(
            "SELECT COUNT(1) FROM POS.vwParty WHERE PartyId <> ? AND Code = ?",
            (party_id, code),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return party_id, code


def create_party_record(cursor, billing: dict, config: dict | None = None) -> int | None:
    from sync_app.core.sync_utils import log

    billing = billing or {}
    first = str(billing.get("first_name") or "").strip()
    last = str(billing.get("last_name") or "").strip()
    name = first or str(billing.get("username") or "").strip() or "مشتری"
    last_name = last or "سایت"
    email = str(billing.get("email") or "").strip()
    mobile = extract_mobile(billing)

    try:
        sepidar_party_row_lock(cursor)
        party_id, code = _next_party_code(cursor)

        cursor.execute(
            """
            INSERT INTO POS.[Party]
                ([Code], [HasCredit], [CustomerCredit], [CreditCheckingType], [AcceptCustomerCheque],
                 [CustomerCategoryForTax], [FatherName], [PlaceOfIssueRef], [IdentityCardNumber],
                 [IdentitySerialNumber], [UserRef], [UserName], [DLRef], [Guid],
                 [AutoSendMarriageAnniversaryMessage], [AutoSendBirthdayMessage], [AutoSendMessage],
                 [PartyId], [Type], [Name], [LastName], [IdentificationCode], [CustomerCategoryForTax96],
                 [EconomicCode], [VendorCategoryForTax96], [Email], [IsActive], [IsVendor],
                 [IsApiEnabled], [IsCustomer], [IsSeller], [Sex], [BirthDate], [MarriageDate], [Version],
                 [Creator], [CreationDate], [LastModifier], [LastModificationDate], [ExtraData])
            VALUES
                (?, 0, NULL, 1, 1, 2, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, 1, 1, ?, 1, ?, ?,
                 NULL, 0, NULL, 0, ?, 1, 0, 0, 1, 0, 0, NULL, NULL, 1, ?, GETDATE(), ?, GETDATE(), NULL)
            """,
            (code, party_id, name, last_name, email or None, 1, 1),
        )

        party_phone_id = next_int_code(cursor, "POS.PartyPhone", "PartyPhoneId")
        cursor.execute(
            """
            INSERT INTO POS.[PartyPhone] ([PartyPhoneId], [PartyRef], [Type], [Phone], [Version], [IsMain])
            VALUES (?, ?, 1, ?, 1, 1)
            """,
            (party_phone_id, party_id, mobile or None),
        )

        location_ref = get_default_location_ref(config)
        address_text = str(billing.get("address_1") or "").strip()
        if not address_text:
            address_text = ", ".join(
                p for p in (billing.get("state"), billing.get("city"), billing.get("address_2")) if p
            )
        if location_ref is not None and address_text:
            party_address_id = next_int_code(cursor, "POS.PartyAddress", "PartyAddressId")
            cursor.execute(
                """
                INSERT INTO POS.[PartyAddress]
                    ([LocationRef], [Guid], [PartyAddressId], [PartyRef], [IsMain], [Type], [Address],
                     [ZipCode], [BranchCode], [Version])
                VALUES (?, NULL, ?, ?, 1, ?, ?, ?, NULL, 1)
                """,
                (location_ref, party_address_id, party_id, _PARTY_ADDRESS_TYPE, address_text, billing.get("postcode") or None),
            )
    except Exception as exc:
        log.error(f"❌ خطا در ثبتِ طرف‌حسابِ سپیدار ({email or mobile or '—'}): {exc}")
        return None

    log.info(f"🆕 طرف‌حسابِ سپیدار ثبت شد: {name} {last_name} (کد {code}, PartyId {party_id})")
    return party_id


def resolve_party_ref(billing: dict, config: dict | None, cursor) -> int | None:
    """PartyIdِ موجود از نگاشت/دیتابیس، وگرنه یک طرف‌حسابِ جدید می‌سازه."""
    billing = billing or {}
    email = str(billing.get("email") or "").strip().lower()
    mobile = extract_mobile(billing)
    key = email or mobile
    if not key:
        return None

    customer_map = load_sepidar_map(_MAP_FILE)
    cached = customer_map.get(key)
    if cached:
        try:
            return int(cached)
        except (TypeError, ValueError):
            pass

    if cursor is None:
        return None

    existing = _find_party_by_contact(cursor, email, mobile)
    if existing:
        customer_map[key] = existing
        save_sepidar_map(_MAP_FILE, customer_map)
        return existing

    new_party_id = create_party_record(cursor, billing, config)
    if new_party_id:
        customer_map[key] = new_party_id
        save_sepidar_map(_MAP_FILE, customer_map)
    return new_party_id


def sync_customers(config: dict | None = None) -> dict:
    """سینکِ دسته‌ایِ مشتریانِ ثبت‌نامیِ سایت — علاوه بر ساختِ خودکارِ
    ضمنِ فاکتور در sepidar_ordersync.py."""
    from sync_app.core.sync_utils import log
    from sync_app.core.scripts.sepidar.sepidar_common import get_sepidar_connection
    from sync_app.core.integrations.commerce_provider import is_prestashop

    config = config or {}
    if is_prestashop(config):
        log.info(
            "ℹ️ سینکِ مستقلِ مشتریانِ سپیدار برایِ پرستاشاپ فعلاً پشتیبانی نمی‌شود — "
            "مشتریان ضمنِ فاکتور ساخته می‌شوند."
        )
        return {"created": 0, "total": 0}

    from sync_app.core.wc_sync_helper import build_wcapi, wc_parse_json

    wcapi = build_wcapi(config)
    customers: list[dict] = []
    page = 1
    while True:
        resp = wcapi.get("customers", params={"per_page": 100, "page": page})
        data = wc_parse_json(resp, "دریافتِ مشتریانِ سایت (سپیدار)")
        if not isinstance(data, list) or not data:
            break
        customers.extend([c for c in data if isinstance(c, dict) and c.get("id")])
        if len(data) < 100:
            break
        page += 1

    if not customers:
        log.info("ℹ️ هیچ مشتریِ ثبت‌نامی در سایت یافت نشد.")
        return {"created": 0, "total": 0}

    created = 0
    conn = get_sepidar_connection(config)
    try:
        cursor = conn.cursor()
        for c in customers:
            billing = dict(c.get("billing") or {})
            billing.setdefault("first_name", c.get("first_name") or "")
            billing.setdefault("last_name", c.get("last_name") or "")
            billing.setdefault("email", c.get("email") or "")
            party_ref = resolve_party_ref(billing, config, cursor)
            if party_ref:
                created += 1
        conn.commit()
    except Exception as exc:
        conn.rollback()
        log.error(f"❌ خطا در سینکِ مشتریانِ سپیدار: {exc}")
        raise
    finally:
        conn.close()

    log.info(f"✅ مشتریانِ سپیدار: {created} مورد بررسی/ساخته شد.")
    return {"created": created, "total": len(customers)}


def main(config: dict | None = None) -> dict:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = config or load_secure_config(None) or {}
    return sync_customers(cfg)


if __name__ == "__main__":
    main()
