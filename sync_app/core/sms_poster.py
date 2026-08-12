"""پیامکِ تبلیغاتیِ گروهی — وب‌سرویسِ HTTP-URL شرکتِ راه‌آفتاب (SunwaySMS)،
متدِ SendArray: یک متنِ یکسان به چند گیرنده در یک درخواست. مستقل از
دیتابیس/فروشگاه — دقیقاً هم‌الگویِ telegram_poster.py/bale_poster.py.

نامِ پارامترها و جدولِ کدهایِ خطا از مستنداتِ رسمیِ گیت‌هابِ سازنده
(github.com/sunwaysms/url — Methods/SendArray.md، Methods/GetCredit.md،
Errors.md) گرفته شده — نه حدس. اگه سرویس‌دهنده در آینده این مستندات رو
عوض کرد، همین آدرس‌ها مرجعِ به‌روزرسانی‌ان."""

from __future__ import annotations

import requests

SMS_PROVIDER_URL_KEY = "SMS_PROVIDER_URL"
SMS_USERNAME_KEY = "SMS_USERNAME"
SMS_PASSWORD_KEY = "SMS_PASSWORD"
SMS_SENDER_NUMBER_KEY = "SMS_SENDER_NUMBER"

DEFAULT_SMS_PROVIDER_URL = "http://sms.sunwaysms.com/smsws/HttpService.ashx"

# جدولِ کدهایِ خطایِ سرویسِ HTTP-URL سان‌وی (Errors.md رسمی) — فقط
# موردهایی که واقعاً ممکنه از این ماژول سر بزنه.
_ERROR_CODES = {
    "51": "نام کاربری یا رمز عبور اشتباه است.",
    "52": "نام کاربری یا رمز عبور خالی است.",
    "53": "تعدادِ شماره‌های گیرنده بیش از ۱۰۰۰ تاست.",
    "54": "شماره‌ی گیرنده ارسال نشده (RecipientNumber خالی است).",
    "55": "شماره‌ی گیرنده نامعتبر است.",
    "59": "متنِ پیامک خالی است.",
    "60": "ترافیکِ سرور بالاست — دوباره تلاش کنید.",
    "61": "شماره‌ی خطِ فرستنده (SpecialNumber) نامعتبر است.",
    "62": "شماره‌ی خطِ فرستنده (SpecialNumber) خالی است — در تنظیمات وارد کنید.",
    "63": "این IP اجازه‌ی دسترسی ندارد — از پنلِ سان‌وی IP را سفید کنید.",
    "70": "این حساب غیرفعال شده است.",
    "77": "این حساب دسترسیِ وب‌سرویس ندارد.",
    "78": "این حساب کاربرِ سامانه‌ی پیام‌کوتاه نیست.",
    "80": "وب‌سرویس توسطِ ادمینِ سان‌وی غیرفعال شده است.",
    "201": "فرمتِ شماره‌ی گیرنده اشتباه است.",
    "202": "اپراتورِ شماره‌ی گیرنده ناشناخته است.",
    "203": "اعتبارِ حساب برایِ این شماره کافی نیست.",
    "300": "ارسالِ پیامِ حاویِ لینک مجاز نیست.",
    "400": "تعدادِ درخواست‌ها از حدِ مجاز بیشتر است.",
    "666": "سرویس موقتاً غیرفعال است.",
    "777": "این IP مسدود شده است.",
    "888": "احرازِ هویتِ شماره‌ی فرستنده ثبت نشده است.",
    "999": "ارسالِ این پیامک مجاز نیست.",
}


def is_configured(config: dict | None) -> bool:
    cfg = config or {}
    return bool(str(cfg.get(SMS_USERNAME_KEY) or "").strip()) and bool(
        str(cfg.get(SMS_PASSWORD_KEY) or "").strip()
    )


def _base_url(config: dict | None) -> str:
    url = str((config or {}).get(SMS_PROVIDER_URL_KEY) or "").strip()
    return url or DEFAULT_SMS_PROVIDER_URL


def _describe_response(raw: str) -> tuple[bool, str]:
    """طبقِ Errors.md رسمی: پاسخِ موفق = یک یا چند شناسه‌یِ پیام (هرکدوم
    عددی بزرگ‌تر از ۱۰۰۰)، جدا با کاما. هر عددِ ۱۰۰۰ یا کمتر یعنی کدِ
    خطا. اگه پاسخ عددی نبود هم ناموفق در نظر گرفته می‌شه."""
    raw = (raw or "").strip()
    if not raw:
        return False, "پاسخِ خالی از سرویس دریافت شد."
    tokens = [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]
    if not tokens:
        return False, raw
    for t in tokens:
        try:
            n = int(t)
        except ValueError:
            return False, raw
        if n <= 1000:
            reason = _ERROR_CODES.get(str(n))
            return False, f"کدِ خطایِ {n}" + (f" — {reason}" if reason else "") + f"\n(پاسخِ خام: {raw})"
    return True, raw


def send_sms(config: dict | None, recipients: list, text: str, *, timeout: int = 25) -> tuple[bool, str]:
    """ارسالِ یک پیامِ یکسان به چند گیرنده (متدِ SendArray). خروجی:
    (موفقیت, پیامِ خوانا — شاملِ توضیحِ کدِ خطا در صورتِ ناموفق بودن)."""
    cfg = config or {}
    username = str(cfg.get(SMS_USERNAME_KEY) or "").strip()
    password = str(cfg.get(SMS_PASSWORD_KEY) or "").strip()
    sender = str(cfg.get(SMS_SENDER_NUMBER_KEY) or "").strip()
    if not username or not password:
        return False, "یوزرنیم/پسوردِ پیامک در تنظیمات وارد نشده."

    numbers = [str(n).strip() for n in (recipients or []) if str(n or "").strip()]
    if not numbers:
        return False, "هیچ شماره‌ی معتبری برای ارسال وجود ندارد."
    message = (text or "").strip()
    if not message:
        return False, "متنِ پیامک خالی است."

    # نامِ دقیقِ این پارامترها از Methods/SendArray.md رسمی — نه UserName/
    # RecipientNumber/Message/SpecialNumber (که کدِ خطایِ ۵۴ می‌داد چون
    # کلیدهاشون اشتباه بود).
    params = {
        "service": "SendArray",
        "username": username,
        "password": password,
        "to": ",".join(numbers),
        "message": message,
        "from": sender,
    }
    try:
        resp = requests.get(_base_url(cfg), params=params, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"خطا در اتصال به سرویسِ پیامک: {exc}"

    raw = (resp.text or "").strip()
    if resp.status_code != 200:
        return False, raw or f"HTTP {resp.status_code}"
    return _describe_response(raw)


def get_credit(config: dict | None, *, timeout: int = 15) -> tuple[bool, str]:
    """اعتبارِ باقی‌مانده — بدونِ ارسالِ پیامکِ واقعی و بدونِ هزینه؛ برایِ
    دکمه‌ی «تستِ اتصال» به‌جایِ ارسالِ یک پیامکِ آزمایشیِ واقعی."""
    cfg = config or {}
    username = str(cfg.get(SMS_USERNAME_KEY) or "").strip()
    password = str(cfg.get(SMS_PASSWORD_KEY) or "").strip()
    if not username or not password:
        return False, "یوزرنیم/پسوردِ پیامک در تنظیمات وارد نشده."

    params = {"service": "GetCredit", "username": username, "password": password}
    try:
        resp = requests.get(_base_url(cfg), params=params, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"خطا در اتصال به سرویسِ پیامک: {exc}"

    raw = (resp.text or "").strip()
    if resp.status_code != 200:
        return False, raw or f"HTTP {resp.status_code}"
    try:
        credit = int(raw)
    except ValueError:
        return False, raw
    if credit < 0:
        reason = _ERROR_CODES.get(str(-credit)) or _ERROR_CODES.get(raw)
        return False, f"کدِ خطا — {reason}" if reason else f"پاسخِ نامعتبر: {raw}"
    return True, f"متصل شد — اعتبارِ باقی‌مانده: {credit}"


def test_send(config: dict | None, phone: str) -> tuple[bool, str]:
    """ارسالِ واقعیِ یک پیامکِ آزمایشی به phone (هزینه دارد) — برایِ وقتی
    که کاربر می‌خواد کاملِ مسیرِ ارسال رو با چشمِ خودش رویِ گوشی ببینه،
    نه فقط تستِ اعتبار."""
    return send_sms(config, [phone], "پیامکِ آزمایشی از PeechaSync ✅")
