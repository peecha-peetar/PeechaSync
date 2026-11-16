"""
لایه‌ی پایه‌ی اتصال به پرستاشاپ — فاز ۱ (فقط تست اتصال).

نکته‌ی مهم برای هر کسی که این کد رو می‌خونه/توسعه می‌ده: این ماژول بر
اساس مستندات رسمی PrestaShop Webservice API نوشته شده، نه با تست روی
یه فروشگاه واقعی (چون در زمان نوشتن این کد، به فروشگاه پرستاشاپِ واقعی
دسترسی نبود). قبل از اعتماد کامل، حتماً با یه فروشگاه واقعی تست بشه.

مرجع: https://devdocs.prestashop-project.org/9/webservice/
- Base URL: https://{دامنه}/api
- احراز هویت: HTTP Basic Auth — کلید API به‌عنوان username، پسورد خالی
- فرمت پیش‌فرض: XML — ولی با پارامتر output_format=JSON می‌شه JSON گرفت
"""

from __future__ import annotations

import requests


def build_ps_base_url(shop_url: str) -> str:
    url = str(shop_url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    return f"{url}/api"


def test_ps_connection(shop_url: str, api_key: str, *, timeout: int = 15) -> tuple[bool, str]:
    """
    اتصال واقعی به /api می‌زنه (بدون هیچ resource خاصی) — اگه کلید درست
    باشه، یه لیست از resourceهای مجازِ همون کلید برمی‌گرده. خروجی:
    (موفق بود یا نه, پیام برای نمایش به کاربر)
    """
    base = build_ps_base_url(shop_url)
    if not base:
        return False, "آدرس فروشگاه پرستاشاپ وارد نشده."
    if not str(api_key or "").strip():
        return False, "کلید API پرستاشاپ وارد نشده."

    try:
        resp = requests.get(
            base,
            params={"output_format": "JSON"},
            auth=(str(api_key).strip(), ""),
            timeout=timeout,
            verify=True,
            headers={
                # خیلی از هاست‌ها (مخصوصاً با فایروال/WAF مثل آروان‌کلود) درخواست‌های
                # بدون User-Agent مرورگری رو مسدود می‌کنن — پیش‌فرض کتابخانه‌ی
                # requests («python-requests/X.X») اغلب همین باعث ۴۰۳ می‌شه.
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/xml,*/*",
            },
        )
    except requests.exceptions.SSLError:
        return False, "خطای SSL — آدرس سایت رو با https:// درست بررسی کنید."
    except requests.exceptions.ConnectionError:
        return False, "اتصال به آدرس داده‌شده برقرار نشد — آدرس فروشگاه رو چک کنید."
    except requests.exceptions.Timeout:
        return False, "سرور پرستاشاپ به‌موقع جواب نداد (Timeout)."
    except Exception as exc:
        return False, f"خطای غیرمنتظره: {exc}"

    if resp.status_code == 401:
        return False, "کلید API رد شد (401) — کلید یا دسترسی‌هاش رو تو Advanced Parameters > Webservice چک کنید."
    if resp.status_code == 403:
        return False, (
            "خطای ۴۰۳ — این معمولاً یعنی خودِ کلید API رد نشده، بلکه یه فایروال/WAF "
            "بین راه (مثلاً آروان‌کلود یا امنیت هاست) درخواست رو مسدود کرده. "
            "چیزهایی که می‌تونید چک کنید:\n"
            "۱. تنظیمات امنیتی/فایروال هاست (WAF) رو برای مسیر /api یه استثنا بذارید.\n"
            "۲. مطمئن بشید Webservice تو Advanced Parameters > Webservice واقعاً «فعال» باشه.\n"
            "۳. اگه از CDN مثل آروان‌کلود استفاده می‌کنید، حالت امنیتی (Security Level) رو موقتاً پایین بیارید و دوباره تست کنید."
        )
    if resp.status_code == 503:
        # ۵۰۳ رو خیلی وقتا خودِ سرور PrestaShop نمی‌ده — یه CDN/WAF (مثل
        # آروان‌کلود) داره یه صفحه‌ی «چالش امنیتی» (JS Challenge/Captcha)
        # نشون می‌ده، چون این درخواست از مرورگر واقعی نیومده و نمی‌تونه
        # اون چالش جاوااسکریپتی رو حل کنه. با نگاه به متن پاسخ می‌شه فهمید.
        body_snippet = (resp.text or "")[:2000].lower()
        challenge_markers = ["arvancloud", "checking your browser", "just a moment", "captcha", "cf-browser-verification", "attack mode"]
        if any(marker in body_snippet for marker in challenge_markers):
            return False, (
                "خطای ۵۰۳ — ولی این از خودِ پرستاشاپ نیست: یه سرویس امنیتی/CDN جلوی "
                "سایت (مثل آروان‌کلود) داره یه «چالش مرورگر» (JS Challenge) نشون می‌ده که "
                "فقط مرورگر واقعی می‌تونه حلش کنه، نه یه برنامه مثل این. باید تو پنل "
                "همون سرویس (آروان‌کلود/CDN)، حالت امنیتی رو برای مسیر /api کاهش بدید "
                "یا IP این کامپیوتر رو تو Allowlist بذارید."
            )
        return False, (
            "خطای ۵۰۳ (سرویس در دسترس نیست) — یا سایت موقتاً از دسترس خارجه، یا حالت "
            "«تعمیر/نگهداری» (Maintenance Mode) پرستاشاپ فعاله، یا یه فایروال/CDN "
            "بین راه درخواست رو مسدود کرده. چند دقیقه‌ی دیگه دوباره امتحان کنید؛ "
            "اگه ادامه داشت، حالت Maintenance رو تو تنظیمات پرستاشاپ چک کنید."
        )
    if resp.status_code == 404:
        return False, "مسیر /api پیدا نشد (404) — مطمئن بشید Webservice تو تنظیمات پرستاشاپ فعاله."
    if resp.status_code >= 400:
        return False, f"خطای سرور پرستاشاپ: کد {resp.status_code}"

    try:
        data = resp.json()
        resource_names = list((data.get("api") or {}).keys())
        if resource_names:
            return True, f"اتصال موفق ✅ — دسترسی به {len(resource_names)} نوع منبع تأیید شد."
        return True, "اتصال موفق ✅ (ولی هیچ resourceای برای این کلید فعال نیست — دسترسی‌ها رو تو پرستاشاپ چک کنید)."
    except Exception:
        # اگه JSON پارس نشد ولی status_code موفق بود، حداقل خودِ اتصال درسته
        if resp.status_code == 200:
            return True, "اتصال موفق ✅ (پاسخ سرور XML بود، نه JSON — عجیب نیست، فقط یعنی output_format نادیده گرفته شده)."
        return False, "پاسخ سرور قابل تفسیر نبود."
