"""دیسپچرِ ارسالِ پست بر اساسِ platform — یک نقطه‌ی واحد که تقویمِ محتوا
(هم دستیِ «ارسالِ الان» و هم تایمرِ پس‌زمینه) ازش استفاده می‌کنه، تا
افزودنِ پلتفرمِ بعدی (ایتا/روبیکا) فقط یک شاخه‌ی جدید اینجا لازم داشته
باشه.

chat_id_override: اگه یک پست شناسه‌ی چتِ سفارشی داشته باشه (برای ارسال به
یک شخص/کانال/گروهِ خاص، به‌جای مقصدِ پیش‌فرضِ تنظیم‌شده در Settings)،
همین‌جا (نه توکنِ بات) عوض می‌شه — توکن همیشه از تنظیمات میاد."""

from __future__ import annotations

PLATFORM_LABELS = {
    "telegram": "تلگرام",
    "bale": "بله",
}


def _bot_token(platform: str, config: dict) -> str:
    if platform == "telegram":
        from sync_app.core.telegram_poster import TELEGRAM_BOT_TOKEN_KEY

        return str(config.get(TELEGRAM_BOT_TOKEN_KEY) or "").strip()
    if platform == "bale":
        from sync_app.core.bale_poster import BALE_BOT_TOKEN_KEY

        return str(config.get(BALE_BOT_TOKEN_KEY) or "").strip()
    return ""


def _configured_chat_id(platform: str, config: dict) -> str:
    if platform == "telegram":
        from sync_app.core.telegram_poster import TELEGRAM_CHAT_ID_KEY

        return str(config.get(TELEGRAM_CHAT_ID_KEY) or "").strip()
    if platform == "bale":
        from sync_app.core.bale_poster import BALE_CHAT_ID_KEY

        return str(config.get(BALE_CHAT_ID_KEY) or "").strip()
    return ""


def is_platform_configured(platform: str, config: dict, *, chat_id_override: str = "") -> bool:
    """token همیشه باید از تنظیمات باشه؛ chat_id یا از تنظیماته یا از override."""
    token = _bot_token(platform, config)
    if not token:
        return False
    chat_id = (chat_id_override or "").strip() or _configured_chat_id(platform, config)
    return bool(chat_id)


def send_post_for_platform(
    platform: str, config: dict, text: str, *,
    photo_path: str = "", photo_paths: list[str] | None = None, chat_id_override: str = "",
) -> tuple[bool, str]:
    """photo_paths (چند عکس => آلبوم) بر photo_path (تکی، برای سازگاری با کدِ قدیمی) اولویت داره.
    chat_id_override پر باشه، به‌جایِ مقصدِ تنظیم‌شده در Settings استفاده می‌شه."""
    token = _bot_token(platform, config)
    chat_id = (chat_id_override or "").strip() or _configured_chat_id(platform, config)

    if platform == "telegram":
        from sync_app.core.telegram_poster import TELEGRAM_PROXY_URL_KEY, send_post

        proxy_url = str(config.get(TELEGRAM_PROXY_URL_KEY) or "").strip()
        if not token or not chat_id:
            return False, "توکنِ بات یا شناسه‌ی چتِ تلگرام در تنظیمات وارد نشده."
        return send_post(
            token, chat_id, text, photo_path=photo_path, photo_paths=photo_paths, proxy_url=proxy_url
        )

    if platform == "bale":
        from sync_app.core.bale_poster import send_post

        if not token or not chat_id:
            return False, "توکنِ بات یا شناسه‌ی چتِ بله در تنظیمات وارد نشده."
        return send_post(token, chat_id, text, photo_path=photo_path, photo_paths=photo_paths)

    return False, f"پلتفرمِ ناشناخته: {platform}"
