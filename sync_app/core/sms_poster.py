"""پیامکِ تبلیغاتیِ گروهی — وب‌سرویسِ HTTP-URL شرکتِ راه‌آفتاب (SunwaySMS)،
متدِ SendArray: یک متنِ یکسان به چند گیرنده در یک درخواست. مستقل از
دیتابیس/فروشگاه — دقیقاً هم‌الگویِ telegram_poster.py/bale_poster.py.

⚠️ این سرویس‌دهنده مستنداتِ عمومیِ دقیقی برایِ فرمتِ پاسخ نداره — طبقِ
مستنداتِ در دسترس، هر شناسه‌ی پیامِ موفق عددی بزرگ‌تر از ۱۰۰۰ است و
عددهایِ کوچیک‌تر یعنی کدِ خطا. برای همین متنِ خامِ پاسخ همیشه برگردونده
می‌شه تا کاربر (نه فقط یک ✅/❌ ساده) خودش هم ببینتش."""

from __future__ import annotations

import requests

SMS_PROVIDER_URL_KEY = "SMS_PROVIDER_URL"
SMS_USERNAME_KEY = "SMS_USERNAME"
SMS_PASSWORD_KEY = "SMS_PASSWORD"
SMS_SENDER_NUMBER_KEY = "SMS_SENDER_NUMBER"

DEFAULT_SMS_PROVIDER_URL = "http://sms.sunwaysms.com/smsws/HttpService.ashx"


def is_configured(config: dict | None) -> bool:
    cfg = config or {}
    return bool(str(cfg.get(SMS_USERNAME_KEY) or "").strip()) and bool(
        str(cfg.get(SMS_PASSWORD_KEY) or "").strip()
    )


def _base_url(config: dict | None) -> str:
    url = str((config or {}).get(SMS_PROVIDER_URL_KEY) or "").strip()
    return url or DEFAULT_SMS_PROVIDER_URL


def _looks_successful(raw: str) -> bool:
    """پاسخ رو با الگویِ «هر شناسه بزرگ‌تر از ۱۰۰۰» می‌سنجه؛ اگه پاسخ
    عددی نبود یا حتی یکی از توکن‌ها زیرِ ۱۰۰۰ بود، ناموفق در نظر می‌گیره."""
    raw = (raw or "").strip()
    if not raw:
        return False
    tokens = [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]
    if not tokens:
        return False
    for t in tokens:
        try:
            if int(t) <= 1000:
                return False
        except ValueError:
            return False
    return True


def send_sms(config: dict | None, recipients: list, text: str, *, timeout: int = 25) -> tuple[bool, str]:
    """ارسالِ یک پیامِ یکسان به چند گیرنده (متدِ SendArray). خروجی:
    (احتمالِ موفقیت بر اساسِ الگویِ پاسخ, متنِ خامِ پاسخِ سرویس)."""
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

    params = {
        "service": "SendArray",
        "UserName": username,
        "Password": password,
        "RecipientNumber": ",".join(numbers),
        "Message": message,
        "SpecialNumber": sender,
    }
    try:
        resp = requests.get(_base_url(cfg), params=params, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"خطا در اتصال به سرویسِ پیامک: {exc}"

    raw = (resp.text or "").strip()
    if resp.status_code != 200:
        return False, raw or f"HTTP {resp.status_code}"
    return _looks_successful(raw), raw


def test_send(config: dict | None, phone: str) -> tuple[bool, str]:
    """چون این سرویس متدِ مستندِ «فقط تست اتصال، بدونِ ارسالِ واقعی»
    نداره، این تابع واقعاً یک پیامکِ آزمایشی به phone می‌فرسته."""
    return send_sms(config, [phone], "پیامکِ آزمایشی از PeechaSync ✅")
