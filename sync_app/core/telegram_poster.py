"""ارسالِ پیام/عکس به کانال/گروهِ تلگرام از طریقِ Bot API — برای انتشارِ
پست‌های زمان‌بندی‌شده‌ی تقویمِ محتوا. مستقل از دیتابیس/فروشگاه است."""

from __future__ import annotations

import os

import requests

TELEGRAM_BOT_TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_KEY = "TELEGRAM_CHAT_ID"
TELEGRAM_PROXY_URL_KEY = "TELEGRAM_PROXY_URL"

_API_BASE = "https://api.telegram.org/bot{token}"


def is_configured(config: dict | None) -> bool:
    cfg = config or {}
    return bool(str(cfg.get(TELEGRAM_BOT_TOKEN_KEY) or "").strip()) and bool(
        str(cfg.get(TELEGRAM_CHAT_ID_KEY) or "").strip()
    )


def _proxies_dict(proxy_url: str | None) -> dict | None:
    """api.telegram.org در ایران معمولاً فیلتره — بدونِ پراکسی، درخواست‌ها
    با «Connection refused» شکست می‌خورن. proxy_url می‌تونه http://, https://
    یا socks5:// باشه (برای socks5 پکیجِ PySocks لازمه، در requirements هست)."""
    url = (proxy_url or "").strip()
    if not url:
        return None
    return {"http": url, "https": url}


def _connection_error_hint(exc: Exception) -> str:
    text = str(exc)
    if "actively refused" in text or "10061" in text or "Max retries exceeded" in text:
        return (
            f"خطای اتصال: {text}\n\n"
            "به نظر می‌رسه api.telegram.org از اینترنتِ شما در دسترس نیست (فیلترینگ) — "
            "یک پراکسی (VPN محلی/socks5) در همین بخش وارد کنید."
        )
    return f"خطای اتصال: {text}"


def _parse_error(resp: requests.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("description"):
            return str(data["description"])
    except Exception:
        pass
    return f"HTTP {resp.status_code}"


def test_connection(bot_token: str, *, proxy_url: str = "", timeout: int = 15) -> tuple[bool, str]:
    """getMe — فقط برای سنجشِ صحتِ توکن، بدون نیاز به chat_id."""
    token = (bot_token or "").strip()
    if not token:
        return False, "توکنِ بات خالی است."
    try:
        resp = requests.get(
            _API_BASE.format(token=token) + "/getMe", timeout=timeout, proxies=_proxies_dict(proxy_url)
        )
    except requests.RequestException as exc:
        return False, _connection_error_hint(exc)
    if resp.status_code != 200:
        return False, _parse_error(resp)
    data = resp.json() or {}
    if not data.get("ok"):
        return False, _parse_error(resp)
    username = str((data.get("result") or {}).get("username") or "")
    return True, f"متصل شد — bot: @{username}" if username else "متصل شد."


def send_text_message(
    bot_token: str, chat_id: str, text: str, *, proxy_url: str = "", timeout: int = 20
) -> tuple[bool, str]:
    token = (bot_token or "").strip()
    chat = (chat_id or "").strip()
    if not token or not chat:
        return False, "توکنِ بات یا شناسه‌ی چت خالی است."
    try:
        resp = requests.post(
            _API_BASE.format(token=token) + "/sendMessage",
            data={"chat_id": chat, "text": text or "", "parse_mode": "HTML"},
            timeout=timeout,
            proxies=_proxies_dict(proxy_url),
        )
    except requests.RequestException as exc:
        return False, _connection_error_hint(exc)
    if resp.status_code != 200:
        return False, _parse_error(resp)
    data = resp.json() or {}
    if not data.get("ok"):
        return False, _parse_error(resp)
    return True, "ارسال شد."


def send_photo_message(
    bot_token: str, chat_id: str, photo_path: str, *, caption: str = "", proxy_url: str = "", timeout: int = 60
) -> tuple[bool, str]:
    token = (bot_token or "").strip()
    chat = (chat_id or "").strip()
    if not token or not chat:
        return False, "توکنِ بات یا شناسه‌ی چت خالی است."
    if not photo_path or not os.path.isfile(photo_path):
        return False, "فایلِ تصویر یافت نشد."
    try:
        with open(photo_path, "rb") as f:
            resp = requests.post(
                _API_BASE.format(token=token) + "/sendPhoto",
                data={"chat_id": chat, "caption": caption or "", "parse_mode": "HTML"},
                files={"photo": f},
                timeout=timeout,
                proxies=_proxies_dict(proxy_url),
            )
    except requests.RequestException as exc:
        return False, _connection_error_hint(exc)
    except OSError as exc:
        return False, f"خطای خواندنِ فایلِ تصویر: {exc}"
    if resp.status_code != 200:
        return False, _parse_error(resp)
    data = resp.json() or {}
    if not data.get("ok"):
        return False, _parse_error(resp)
    return True, "ارسال شد."


def send_post(
    bot_token: str, chat_id: str, text: str, *, photo_path: str = "", proxy_url: str = "", timeout: int = 60
) -> tuple[bool, str]:
    """ارسالِ یک پستِ زمان‌بندی‌شده — اگه عکس داشته باشه به‌عنوانِ caption، وگرنه پیامِ متنیِ ساده."""
    if (photo_path or "").strip():
        return send_photo_message(bot_token, chat_id, photo_path, caption=text, proxy_url=proxy_url, timeout=timeout)
    return send_text_message(bot_token, chat_id, text, proxy_url=proxy_url, timeout=timeout)
