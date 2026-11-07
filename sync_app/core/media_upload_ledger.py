"""دفترِ «کدوم فایلِ تصویر برایِ کدوم کالا قبلاً به سایت رفته» — به‌ازایِ هر سایت.

مشکل: «ارسالِ تصاویر» (دکمه‌یِ تبِ محصولات) هر بار همه‌یِ فایل‌ها رو از نو
آپلود می‌کرد (در حالتِ «به گالری اضافه کن» گالری هر بار بزرگ‌تر می‌شد)، و
سینکِ خودکار هم چون از ارسالِ دستی خبر نداشت، همون تصاویرِ دیتابیس رو
دوباره آپلود و به گالری اضافه می‌کرد. این‌جا برایِ هر کالا، اثرِ انگشتِ
محتوایِ فایلِ اصلی (sha1) → شناسه‌یِ رسانه‌یِ سایت ثبت می‌شه؛ اگه همون
رسانه هنوز تویِ گالریِ محصول باشه، دوباره فرستاده نمی‌شه.
"""

from __future__ import annotations

import hashlib
import json
import os
import re

LEDGER_FILE = "uploaded_media_ledger.json"  # {platform: {sku: {sha1: media_id}}}
_HLO_RE = re.compile(r"_hlo(\d+)")


def _path() -> str:
    from sync_app.core.sync_utils import site_scoped_path

    return site_scoped_path(LEDGER_FILE)


def _load() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as exc:
        from sync_app.core.sync_utils import log

        log.warning(f"⚠️ ذخیره {LEDGER_FILE}: {exc}")


def file_digest(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return ""


def known_media_id(platform: str, sku: str, digest: str) -> int | None:
    if not digest:
        return None
    value = ((_load().get(platform) or {}).get(str(sku).strip()) or {}).get(digest)
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def remember_media(platform: str, sku: str, digest: str, media_id) -> None:
    if not digest or not media_id:
        return
    data = _load()
    data.setdefault(platform, {}).setdefault(str(sku).strip(), {})[digest] = int(media_id)
    _save(data)


def hlo_id_from_path(path: str) -> int | None:
    """فایل‌هایِ تصویرِ دیتابیس با نامِ «<کد>_hlo<شناسه>» ذخیره می‌شن."""
    match = _HLO_RE.search(os.path.basename(str(path or "")))
    return int(match.group(1)) if match else None


def gallery_has_hlo(gallery: list[dict], hlo_id: int) -> int | None:
    """برایِ تصاویری که قبل از این دفتر آپلود شدن: رسانه‌ای تویِ گالری هست که
    اسمِ فایلش همون «_hlo<شناسه>» رو داره؟ خروجی: شناسه‌یِ اون رسانه یا None."""
    if not hlo_id:
        return None
    for img in gallery or []:
        if not isinstance(img, dict) or not img.get("id"):
            continue
        text = f"{img.get('src') or ''} {img.get('name') or ''}"
        if any(int(m.group(1)) == int(hlo_id) for m in _HLO_RE.finditer(text)):
            return int(img["id"])
    return None


def unique_ids(ids) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for value in ids or []:
        try:
            iv = int(value)
        except (TypeError, ValueError):
            continue
        if iv and iv not in seen:
            seen.add(iv)
            out.append(iv)
    return out
