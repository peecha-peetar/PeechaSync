"""پیش‌تنظیم‌های نام‌دارِ کلِ تنظیمات — امکانِ ذخیره‌ی چند مجموعه تنظیماتِ
کامل (دیتابیس + پلتفرمِ فروشگاه + سایت‌ها + تم و بقیه‌ی تب تنظیمات)
زیرِ یک عنوان، و بازگردانیِ سریعِ همه‌شون از بالای تب تنظیمات — بدونِ
نیاز به تعویضِ پروفایل یا راه‌اندازیِ مجددِ برنامه.

هر پیش‌تنظیم کاملاً مستقل و مکتفی‌به‌خودشه: یک snapshot از کلِ دیکشنریِ
config در لحظه‌ی ذخیره (شاملِ WC_SITES/PS_SITES و همه‌چیزِ دیگه).
"""

from __future__ import annotations

import copy
import uuid

CONFIG_PRESETS_KEY = "CONFIG_PRESETS"
ACTIVE_CONFIG_PRESET_ID_KEY = "ACTIVE_CONFIG_PRESET_ID"

_EXCLUDED_KEYS = {"_CONFIG_PATH", "_KEY_PATH", CONFIG_PRESETS_KEY, ACTIVE_CONFIG_PRESET_ID_KEY}


def _new_preset_id() -> str:
    return uuid.uuid4().hex[:12]


def list_presets(config: dict | None) -> list[dict]:
    raw = (config or {}).get(CONFIG_PRESETS_KEY)
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict) and item.get("id") and isinstance(item.get("snapshot"), dict):
            out.append(item)
    return out


def find_preset(presets: list[dict], preset_id: str) -> dict | None:
    pid = (preset_id or "").strip()
    if not pid:
        return None
    for p in presets:
        if str(p.get("id") or "") == pid:
            return p
    return None


def snapshot_current_config(config: dict) -> dict:
    """کپیِ کاملِ کانفیگِ فعلی، بدونِ کلیدهای داخلی/خودِ لیستِ پیش‌تنظیم‌ها."""
    return {k: copy.deepcopy(v) for k, v in (config or {}).items() if k not in _EXCLUDED_KEYS}


def save_preset(config: dict, title: str, *, preset_id: str = "") -> dict:
    """پیش‌تنظیمِ جدید می‌سازه یا (اگه preset_id یکی از پیش‌تنظیم‌های موجود باشه)
    همون رو آپدیت می‌کنه. یه کپیِ جدید از config با لیستِ پیش‌تنظیم‌های
    به‌روزشده برمی‌گردونه — config ورودی دست‌نخورده می‌مونه."""
    cfg = dict(config or {})
    presets = list(list_presets(cfg))
    snapshot = snapshot_current_config(cfg)
    title = (title or "").strip() or "بدون عنوان"

    pid = (preset_id or "").strip()
    if pid and find_preset(presets, pid):
        for idx, p in enumerate(presets):
            if str(p.get("id")) == pid:
                presets[idx] = {"id": pid, "title": title, "snapshot": snapshot}
                break
    else:
        pid = pid or _new_preset_id()
        presets.append({"id": pid, "title": title, "snapshot": snapshot})

    cfg[CONFIG_PRESETS_KEY] = presets
    return cfg


def delete_preset(config: dict, preset_id: str) -> dict:
    cfg = dict(config or {})
    pid = (preset_id or "").strip()
    cfg[CONFIG_PRESETS_KEY] = [p for p in list_presets(cfg) if str(p.get("id")) != pid]
    return cfg


def apply_preset(config: dict, preset: dict) -> dict:
    """اسنپ‌شاتِ پیش‌تنظیم رو به‌عنوانِ کانفیگِ فعال برمی‌گردونه — لیستِ خودِ
    پیش‌تنظیم‌ها (که جزوِ اسنپ‌شات نیست) از config فعلی حفظ می‌شه تا با
    اعمالِ یک پیش‌تنظیم، بقیه‌ی پیش‌تنظیم‌ها گم نشن."""
    presets = list_presets(config)
    new_cfg = dict((preset or {}).get("snapshot") or {})
    new_cfg[CONFIG_PRESETS_KEY] = presets
    return new_cfg
