"""تطبیق sku محصول به id ووکامرس."""

from __future__ import annotations

import json

from sync_app.core.sync_utils import app_path, log
from sync_app.core.wc_sync_helper import wc_call, wc_parse_json
from sync_app.core.product_woo_map_meta import is_manual_product_link

_ACTIVE_WC_STATUSES = frozenset({"publish", "draft", "private", "pending"})


def _is_active_wc_product(info: dict | None) -> bool:
    if not isinstance(info, dict) or not info.get("id"):
        return False
    return str(info.get("status") or "").strip() in _ACTIVE_WC_STATUSES


def _current_platform() -> str:
    from sync_app.core.integrations.commerce_provider import store_platform
    from sync_app.core.secure_config_loader import load_secure_config

    return store_platform(load_secure_config(None))


def _platform_marker_path() -> str:
    return app_path("product_woo_map.platform")


def load_product_woo_map() -> dict[str, int]:
    # آی‌دی‌های عددی این فایل مخصوص یک پلتفرمن (ووکامرس یا پرستاشاپ) — اگه
    # از آخرین ذخیره، پلتفرم فعال عوض شده باشه، این IDها به‌کل بی‌ربطن؛
    # با نگاشت خالی شروع می‌کنیم تا هر SKU با جستجوی SKU دوباره resolve بشه.
    current_platform = _current_platform()
    try:
        with open(_platform_marker_path(), "r", encoding="utf-8") as f:
            saved_platform = (f.read() or "").strip()
        if saved_platform and saved_platform != current_platform:
            # این reset رو همین‌جا و فوراً ذخیره/قفل می‌کنیم (نه فقط در حافظه
            # برگردوندن {}) — چون قبلاً اگه این تشخیص به هر دلیلی (حتی یک
            # بار اشتباهی) دوباره تکرار می‌شد، save بعدیِ سینک با یه نگاشت
            # ناقص (فقط چند SKU همین دور) کل فایل رو برای همیشه جایگزین
            # می‌کرد و لینک بقیه‌ی محصولات از دست می‌رفت. با ذخیره‌ی فوری
            # نشانگر پلتفرم جدید + بکاپ از فایل قبلی، این reset دقیقاً یک‌بار
            # اتفاق می‌افته و دیتای قبلی هم گم نمی‌شه (قابل بازیابی از بکاپ).
            log.warning(
                f"⚠️ پلتفرم فروشگاه از «{saved_platform}» به «{current_platform}» عوض شده — "
                "نگاشت SKU↔ID قبلی نادیده گرفته می‌شود (بکاپ در product_woo_map.backup_*.json)."
            )
            try:
                import shutil
                import time as _time

                src = app_path("product_woo_map.json")
                backup = app_path(f"product_woo_map.backup_{saved_platform}_{int(_time.time())}.json")
                shutil.copyfile(src, backup)
            except Exception:
                pass
            try:
                with open(app_path("product_woo_map.json"), "w", encoding="utf-8") as f:
                    json.dump({}, f)
                with open(_platform_marker_path(), "w", encoding="utf-8") as f:
                    f.write(current_platform)
            except Exception as exc:
                log.warning(f"⚠️ ذخیره‌ی فوریِ reset پلتفرم ناموفق بود: {exc}")
            return {}
    except FileNotFoundError:
        pass
    except Exception:
        pass

    try:
        with open(app_path("product_woo_map.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {str(k).strip(): int(v) for k, v in data.items() if v}
    except Exception:
        pass
    return {}


def save_product_woo_map(product_map: dict) -> None:
    try:
        clean = {str(k).strip(): int(v) for k, v in (product_map or {}).items() if v}

        # محافظ داده: اگه فایل فعلی روی دیسک خیلی بزرگ‌تر از نگاشتیه که
        # داریم جایگزینش می‌کنیم (و پلتفرم واقعاً عوض نشده)، این خیلی
        # مشکوکه — یعنی یه جای دیگه با نگاشت ناقص شروع کرده. به‌جای سکوت،
        # لاگ برجسته می‌کنیم تا قابل ردیابی باشه (بدون متوقف‌کردن ذخیره،
        # چون حذف عمدیِ تک‌SKU هم از همین تابع رد می‌شه).
        try:
            with open(app_path("product_woo_map.json"), "r", encoding="utf-8") as f:
                existing = json.load(f) or {}
            with open(_platform_marker_path(), "r", encoding="utf-8") as f:
                marker_platform = (f.read() or "").strip()
            same_platform = marker_platform == _current_platform()
            if same_platform and isinstance(existing, dict) and len(existing) >= 5 and len(clean) < len(existing) / 2:
                log.warning(
                    f"⚠️ نگاشت SKU↔ID در حال ذخیره ({len(clean)} مورد) خیلی کوچیک‌تر از "
                    f"فایل فعلی روی دیسکه ({len(existing)} مورد) — پلتفرم عوض نشده، پس این "
                    "کاهش عمدی به نظر نمی‌رسه. لطفاً بعد از این عملیات تب محصولات رو چک کنید."
                )
        except Exception:
            pass

        with open(app_path("product_woo_map.json"), "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        with open(_platform_marker_path(), "w", encoding="utf-8") as f:
            f.write(_current_platform())
    except Exception as exc:
        log.warning(f"⚠️ ذخیره product_woo_map.json: {exc}")


def fetch_product_by_id(wcapi, product_id: int):
    def _get():
        resp = wcapi.get(
            f"products/{int(product_id)}",
            params={"_fields": "id,status,sku,name,type"},
        )
        data = wc_parse_json(resp, f"GET محصول #{product_id}")
        if isinstance(data, dict) and data.get("id"):
            return data
        return None

    try:
        return wc_call(wcapi, f"بررسی محصول #{product_id}", _get, retries=1)
    except Exception:
        return None


def find_product_by_sku(wcapi, sku: str):
    """sku رو تو woo پیدا کن، trash رو حساب نکن."""
    sku = str(sku or "").strip()
    if not sku:
        return None

    def _search():
        resp = wcapi.get(
            "products",
            params={
                "sku": sku,
                "status": "any",
                "per_page": 20,
                "_fields": "id,status,sku,name,type",
            },
        )
        data = wc_parse_json(resp, f"جستجوی SKU {sku}")
        if not isinstance(data, list):
            return None
        for row in data:
            if (
                isinstance(row, dict)
                and str(row.get("sku") or "").strip() == sku
                and _is_active_wc_product(row)
            ):
                return row
        return None

    try:
        return wc_call(wcapi, f"جستجوی محصول {sku}", _search, retries=2, backoff=(1.0, 2.0))
    except Exception:
        return None


def _find_trashed_products_by_sku(wcapi, sku: str) -> list[dict]:
    sku = str(sku or "").strip()
    if not sku:
        return []

    def _search():
        resp = wcapi.get(
            "products",
            params={
                "sku": sku,
                "status": "trash",
                "per_page": 20,
                "_fields": "id,status,sku,name,type",
            },
        )
        data = wc_parse_json(resp, f"جستجوی SKU {sku} در سطل‌زباله")
        if not isinstance(data, list):
            return []
        return [
            row for row in data
            if isinstance(row, dict)
            and str(row.get("sku") or "").strip() == sku
            and str(row.get("status") or "").strip() == "trash"
        ]

    try:
        return wc_call(wcapi, f"بررسی سطل‌زباله SKU {sku}", _search, retries=1) or []
    except Exception:
        return []


def _force_delete_trashed_product(wcapi, product_id: int, sku: str = "") -> None:
    pid = int(product_id)

    def _delete():
        resp = wcapi.delete(f"products/{pid}", params={"force": True})
        wc_parse_json(resp, f"حذف دائمی محصول #{pid}")
        return True

    wc_call(wcapi, f"حذف دائمی محصول حذف‌شده #{pid}", _delete, retries=1)
    note = f" (SKU {sku})" if sku else ""
    log.info(f"🗑️ محصول #{pid}{note} از سطل‌زباله حذف شد — محصول جدید ایجاد می‌شود")


def clear_trashed_sku_blockers(wcapi, sku: str, product_map: dict | None = None) -> dict:
    """قبل از ساخت محصول جدید، همون sku تو trash رو پاک کن."""
    sku = str(sku or "").strip()
    if product_map is None:
        product_map = load_product_woo_map()

    seen: set[int] = set()

    cached = product_map.get(sku)
    if cached:
        info = fetch_product_by_id(wcapi, int(cached))
        if info and str(info.get("status") or "").strip() == "trash":
            _force_delete_trashed_product(wcapi, int(cached), sku)
            seen.add(int(cached))
            product_map.pop(sku, None)
            save_product_woo_map(product_map)

    for row in _find_trashed_products_by_sku(wcapi, sku):
        pid = int(row.get("id") or 0)
        if pid and pid not in seen:
            _force_delete_trashed_product(wcapi, pid, sku)
            seen.add(pid)

    return product_map


def resolve_existing_product_id(wcapi, sku: str, product_map: dict | None = None):
    """محصول live بود id بده، نبود یا trash بود None.

    اگر در product_woo_map تطبیق دستی ثبت شده باشد، همان id اولویت دارد —
    حتی وقتی SKU محصول سایت با SKU نرم‌افزار یکی نباشد.
    """
    sku = str(sku or "").strip()
    if not sku:
        return None, product_map or load_product_woo_map()

    if product_map is None:
        product_map = load_product_woo_map()

    cached = product_map.get(sku)
    if cached:
        info = fetch_product_by_id(wcapi, int(cached))
        status = str((info or {}).get("status") or "").strip()
        if info and status == "trash":
            log.info(
                f"ℹ️ [{sku}] Woo #{cached} در سطل‌زباله است — restore نمی‌شود؛ محصول جدید ایجاد می‌شود"
            )
            product_map.pop(sku, None)
            save_product_woo_map(product_map)
        elif info and _is_active_wc_product(info):
            mapped_sku = str(info.get("sku") or "").strip()
            if mapped_sku != sku:
                log.info(
                    f"ℹ️ [{sku}] تطبیق دستی → Woo #{cached} "
                    f"(SKU سایت: {mapped_sku or '—'})"
                )
            return int(info["id"]), product_map
        else:
            product_map.pop(sku, None)
            save_product_woo_map(product_map)

    if is_manual_product_link(sku):
        log.warning(
            f"⚠️ [{sku}] تطبیق دستی ثبت شده اما Woo #{cached or '—'} "
            "در دسترس نیست — ارسال متوقف می‌شود (جستجو با SKU انجام نمی‌شود)."
        )
        return None, product_map

    hit = find_product_by_sku(wcapi, sku)
    if hit and hit.get("id") and _is_active_wc_product(hit):
        pid = int(hit["id"])
        mapped = product_map.get(sku)
        if mapped and int(mapped) != pid:
            log.warning(
                f"⚠️ [{sku}] تضاد SKU: فایل تطبیق → #{mapped}، "
                f"جستجوی SKU → #{pid} — فقط #{mapped} استفاده می‌شود."
            )
            mapped_info = fetch_product_by_id(wcapi, int(mapped))
            if mapped_info and _is_active_wc_product(mapped_info):
                return int(mapped), product_map
            return None, product_map
        product_map[sku] = pid
        save_product_woo_map(product_map)
        return pid, product_map

    return None, product_map


def verify_product_saved(wcapi, product_id: int, sku: str = "") -> dict:
    info = fetch_product_by_id(wcapi, int(product_id))
    if not info:
        raise RuntimeError(f"محصول #{product_id} ({sku}) بعد از sync در Woo یافت نشد")
    status = str(info.get("status") or "").strip()
    if status not in _ACTIVE_WC_STATUSES:
        raise RuntimeError(
            f"محصول #{product_id} ({sku}) وضعیت '{status}' — انتشار ناموفق بود"
        )
    return info


def resolve_wc_product_id(wcapi, sku: str, product_map: dict | None = None, *, log_step=None):
    """id فروشگاه (ووکامرس یا پرستاشاپ) برای sync واریانت."""
    from sync_app.core.integrations.commerce_provider import store_platform_label

    label = store_platform_label({"STORE_PLATFORM": _current_platform()})
    pid, _ = resolve_existing_product_id(wcapi, sku, product_map)
    if pid and log_step:
        log_step(f"محصول {sku} → {label} #{pid}")
    elif log_step:
        log_step(f"محصول {sku} در {label} نیست — ابتدا از تب «محصولات» ارسال کنید")
    return pid
