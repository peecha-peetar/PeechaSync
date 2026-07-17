"""ارسالِ پیام/عکس به کانال/گروهِ «بله» (Bale) از طریقِ Bot API رسمی —
دقیقاً هم‌ساختار با telegram_poster.py (چون Bale API خودش عیناً از شکلِ
Telegram Bot API الگو گرفته: tapi.bale.ai/bot<token>/METHOD). برخلافِ
تلگرام، بله در ایران فیلتر نیست — نیازی به پراکسی نداره."""

from __future__ import annotations

import os

import requests

BALE_BOT_TOKEN_KEY = "BALE_BOT_TOKEN"
BALE_CHAT_ID_KEY = "BALE_CHAT_ID"

_API_BASE = "https://tapi.bale.ai/bot{token}"


def is_configured(config: dict | None) -> bool:
    cfg = config or {}
    return bool(str(cfg.get(BALE_BOT_TOKEN_KEY) or "").strip()) and bool(
        str(cfg.get(BALE_CHAT_ID_KEY) or "").strip()
    )


def _parse_error(resp: requests.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("description"):
            return str(data["description"])
    except Exception:
        pass
    return f"HTTP {resp.status_code}"


def test_connection(bot_token: str, *, timeout: int = 15) -> tuple[bool, str]:
    """getMe — فقط برای سنجشِ صحتِ توکن، بدون نیاز به chat_id."""
    token = (bot_token or "").strip()
    if not token:
        return False, "توکنِ بات خالی است."
    try:
        resp = requests.get(_API_BASE.format(token=token) + "/getMe", timeout=timeout)
    except requests.RequestException as exc:
        return False, f"خطای اتصال: {exc}"
    if resp.status_code != 200:
        return False, _parse_error(resp)
    data = resp.json() or {}
    if not data.get("ok"):
        return False, _parse_error(resp)
    username = str((data.get("result") or {}).get("username") or "")
    return True, f"متصل شد — bot: @{username}" if username else "متصل شد."


def send_text_message(bot_token: str, chat_id: str, text: str, *, timeout: int = 20) -> tuple[bool, str]:
    token = (bot_token or "").strip()
    chat = (chat_id or "").strip()
    if not token or not chat:
        return False, "توکنِ بات یا شناسه‌ی چت خالی است."
    try:
        resp = requests.post(
            _API_BASE.format(token=token) + "/sendMessage",
            data={"chat_id": chat, "text": text or ""},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return False, f"خطای اتصال: {exc}"
    if resp.status_code != 200:
        return False, _parse_error(resp)
    data = resp.json() or {}
    if not data.get("ok"):
        return False, _parse_error(resp)
    return True, "ارسال شد."


def send_photo_message(
    bot_token: str, chat_id: str, photo_path: str, *, caption: str = "", timeout: int = 60
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
                data={"chat_id": chat, "caption": caption or ""},
                files={"photo": f},
                timeout=timeout,
            )
    except requests.RequestException as exc:
        return False, f"خطای اتصال: {exc}"
    except OSError as exc:
        return False, f"خطای خواندنِ فایلِ تصویر: {exc}"
    if resp.status_code != 200:
        return False, _parse_error(resp)
    data = resp.json() or {}
    if not data.get("ok"):
        return False, _parse_error(resp)
    return True, "ارسال شد."


def send_post(bot_token: str, chat_id: str, text: str, *, photo_path: str = "", timeout: int = 60) -> tuple[bool, str]:
    """ارسالِ یک پستِ زمان‌بندی‌شده — اگه عکس داشته باشه به‌عنوانِ caption، وگرنه پیامِ متنیِ ساده."""
    if (photo_path or "").strip():
        return send_photo_message(bot_token, chat_id, photo_path, caption=text, timeout=timeout)
    return send_text_message(bot_token, chat_id, text, timeout=timeout)
