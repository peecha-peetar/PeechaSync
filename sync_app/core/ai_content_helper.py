"""تولیدِ خودکارِ متنِ مقاله با هوشِ مصنوعی (Google Gemini — سرویسِ رایگان،
کلید از aistudio.google.com/apikey). فقط برایِ تبِ «مقالاتِ سایت» استفاده
می‌شه؛ کاربر باید کلیدِ API خودش رو در تنظیمات وارد کنه — این ماژول از
هیچ سرویسِ/حسابِ داخلیِ دیگه‌ای استفاده نمی‌کنه."""

from __future__ import annotations

import json

import requests

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
REQUEST_TIMEOUT = 60

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "content_html": {
            "type": "STRING",
            "description": "متنِ کاملِ مقاله به زبانِ فارسی، به‌صورتِ HTML سادہ فقط با تگ‌هایِ h2/h3/p/ul/li",
        },
        "excerpt": {
            "type": "STRING",
            "description": "خلاصه‌ای ۱۰۰ تا ۱۶۰ کاراکتری مناسبِ متا-دیسکریپشن",
        },
    },
    "required": ["content_html", "excerpt"],
}


class AiContentError(RuntimeError):
    pass


def _prompt_for(title: str, extra_instructions: str = "") -> str:
    extra = f"\nنکاتِ اضافه از کاربر: {extra_instructions.strip()}" if extra_instructions.strip() else ""
    return (
        f'یک مقاله‌ی کامل، خوش‌ساختار و سئوپسند به زبانِ فارسی با عنوانِ «{title}» بنویس.\n'
        "قوانین:\n"
        "- حداقل ۴۰۰ کلمه.\n"
        "- از تگ‌هایِ HTML سادہ استفاده کن: <h2>/<h3> برایِ زیرعنوان‌ها، <p> برایِ پاراگراف‌ها، "
        "<ul><li> برایِ لیست — هیچ تگِ دیگه‌ای (نه <html>، نه <body>، نه style) استفاده نکن.\n"
        "- حداقل دو زیرعنوانِ H2 داشته باش.\n"
        "- لحن: ساده، روان و طبیعی — نه تبلیغاتیِ اغراق‌آمیز.\n"
        f"{extra}"
    )


def generate_article(config, title: str, *, extra_instructions: str = "") -> dict:
    """خروجی: {"ok": bool, "content_html": str, "excerpt": str, "error": str}"""
    title = (title or "").strip()
    if not title:
        return {"ok": False, "content_html": "", "excerpt": "", "error": "عنوانِ مقاله خالیه — اول عنوان رو بنویسید."}

    api_key = str((config or {}).get("AI_API_KEY") or "").strip()
    if not api_key:
        return {
            "ok": False, "content_html": "", "excerpt": "",
            "error": "کلیدِ API هوشِ مصنوعی تنظیم نشده — تنظیمات > بخشِ «هوشِ مصنوعی» یه کلیدِ رایگانِ "
            "Gemini از aistudio.google.com/apikey وارد کنید.",
        }

    body = {
        "contents": [{"parts": [{"text": _prompt_for(title, extra_instructions)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }

    try:
        resp = requests.post(
            GEMINI_URL, params={"key": api_key}, json=body, timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        return {"ok": False, "content_html": "", "excerpt": "", "error": f"اتصال به سرویسِ هوشِ مصنوعی ناموفق بود: {e}"}

    if resp.status_code == 400:
        return {"ok": False, "content_html": "", "excerpt": "", "error": "کلیدِ API نامعتبره — دوباره چک کنید."}
    if resp.status_code == 403:
        return {"ok": False, "content_html": "", "excerpt": "", "error": "کلیدِ API مجوزِ لازم رو نداره (۴۰۳)."}
    if resp.status_code == 429:
        return {
            "ok": False, "content_html": "", "excerpt": "",
            "error": "سهمیه‌ی رایگانِ امروز تموم شده (۴۲۹) — کمی بعد دوباره امتحان کنید.",
        }
    if resp.status_code != 200:
        return {"ok": False, "content_html": "", "excerpt": "", "error": f"خطایِ سرویسِ هوشِ مصنوعی: HTTP {resp.status_code}"}

    try:
        data = resp.json()
        candidates = data.get("candidates") or []
        text = candidates[0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        content_html = str(parsed.get("content_html") or "").strip()
        excerpt = str(parsed.get("excerpt") or "").strip()
    except Exception as e:
        return {"ok": False, "content_html": "", "excerpt": "", "error": f"پاسخِ سرویس قابلِ خوندن نبود: {e}"}

    if not content_html:
        return {"ok": False, "content_html": "", "excerpt": "", "error": "سرویس محتوایی برنگردوند."}

    return {"ok": True, "content_html": content_html, "excerpt": excerpt, "error": ""}
