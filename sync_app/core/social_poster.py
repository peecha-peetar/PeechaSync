"""دیسپچرِ ارسالِ پست بر اساسِ platform — یک نقطه‌ی واحد که تقویمِ محتوا
(هم دستیِ «ارسالِ الان» و هم تایمرِ پس‌زمینه) ازش استفاده می‌کنه، تا
افزودنِ پلتفرمِ بعدی (ایتا/روبیکا) فقط یک شاخه‌ی جدید اینجا لازم داشته
باشه."""

from __future__ import annotations

PLATFORM_LABELS = {
    "telegram": "تلگرام",
    "bale": "بله",
}


def is_platform_configured(platform: str, config: dict) -> bool:
    if platform == "telegram":
        from sync_app.core.telegram_poster import is_configured

        return is_configured(config)
    if platform == "bale":
        from sync_app.core.bale_poster import is_configured

        return is_configured(config)
    return False


def send_post_for_platform(
    platform: str, config: dict, text: str, *, photo_path: str = ""
) -> tuple[bool, str]:
    if platform == "telegram":
        from sync_app.core.telegram_poster import (
            TELEGRAM_BOT_TOKEN_KEY,
            TELEGRAM_CHAT_ID_KEY,
            TELEGRAM_PROXY_URL_KEY,
            send_post,
        )

        token = str(config.get(TELEGRAM_BOT_TOKEN_KEY) or "").strip()
        chat_id = str(config.get(TELEGRAM_CHAT_ID_KEY) or "").strip()
        proxy_url = str(config.get(TELEGRAM_PROXY_URL_KEY) or "").strip()
        if not token or not chat_id:
            return False, "توکنِ بات یا شناسه‌ی چتِ تلگرام در تنظیمات وارد نشده."
        return send_post(token, chat_id, text, photo_path=photo_path, proxy_url=proxy_url)

    if platform == "bale":
        from sync_app.core.bale_poster import BALE_BOT_TOKEN_KEY, BALE_CHAT_ID_KEY, send_post

        token = str(config.get(BALE_BOT_TOKEN_KEY) or "").strip()
        chat_id = str(config.get(BALE_CHAT_ID_KEY) or "").strip()
        if not token or not chat_id:
            return False, "توکنِ بات یا شناسه‌ی چتِ بله در تنظیمات وارد نشده."
        return send_post(token, chat_id, text, photo_path=photo_path)

    return False, f"پلتفرمِ ناشناخته: {platform}"
