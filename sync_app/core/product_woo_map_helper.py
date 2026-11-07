"""تطبیق sku محصول به id ووکامرس."""

from __future__ import annotations

import json

from sync_app.core.sync_utils import site_scoped_path, log
from sync_app.core.wc_sync_helper import wc_call, wc_parse_json

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
    return site_scoped_path("product_woo_map.platform")


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

                src = site_scoped_path("product_woo_map.json")
                backup = site_scoped_path(f"product_woo_map.backup_{saved_platform}_{int(_time.time())}.json")
                shutil.copyfile(src, backup)
            except Exception:
                pass
            try:
                with open(site_scoped_path("product_woo_map.json"), "w", encoding="utf-8") as f:
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
        with open(site_scoped_path("product_woo_map.json"), "r", encoding="utf-8") as f:
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
            with open(site_scoped_path("product_woo_map.json"), "r", encoding="utf-8") as f:
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

        with open(site_scoped_path("product_woo_map.json"), "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        with open(_platform_marker_path(), "w", encoding="utf-8") as f:
            f.write(_current_platform())
    except Exception as exc:
        log.warning(f"⚠️ ذخیره product_woo_map.json: {exc}")


_PRODUCT_FIELDS = "id,status,sku,name,type,parent_id,date_created_gmt"


def fetch_product_by_id(wcapi, product_id: int):
    def _get():
        resp = wcapi.get(
            f"products/{int(product_id)}",
            params={"_fields": _PRODUCT_FIELDS},
        )
        data = wc_parse_json(resp, f"GET محصول #{product_id}")
        if isinstance(data, dict) and data.get("id"):
            return data
        return None

    try:
        return wc_call(wcapi, f"بررسی محصول #{product_id}", _get, retries=1)
    except Exception:
        return None


def fetch_product_state(wcapi, product_id: int) -> tuple[str, dict | None]:
    """مثلِ fetch_product_by_id ولی «حذف‌شده» رو از «خطایِ شبکه» جدا می‌کنه:
    ("ok", info) | ("missing", None) | ("error", None). قبلاً هر دو None
    بودن، پس یک قطعیِ کوتاهِ اینترنت عینِ «محصول حذف شده» رفتار می‌شد و
    لینک پاک و محصولِ تکراری ساخته می‌شد."""
    pid = int(product_id or 0)
    if not pid:
        return "missing", None

    from sync_app.core.integrations.commerce_provider import PrestaShopAPIAdapter

    if isinstance(wcapi, PrestaShopAPIAdapter):
        from sync_app.core.ps_sync_helper import ps_get_product

        try:
            info = ps_get_product(wcapi.config, pid)
        except Exception as exc:
            log.warning(f"⚠️ بررسیِ محصولِ #{pid} رویِ سایت ناموفق بود: {exc}")
            return "error", None
        return ("ok", info) if isinstance(info, dict) and info.get("id") else ("missing", None)

    def _get():
        resp = wcapi.get(f"products/{pid}", params={"_fields": _PRODUCT_FIELDS})
        status_code = int(getattr(resp, "status_code", 200) or 200)
        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"GET محصول #{pid}: پاسخ JSON نامعتبر (HTTP {status_code})") from exc
        if isinstance(data, dict) and data.get("id"):
            return "ok", data
        err_code = str(data.get("code") or "") if isinstance(data, dict) else ""
        if status_code in (404, 410) or err_code.endswith("_invalid_id"):
            return "missing", None
        message = data.get("message") if isinstance(data, dict) else data
        raise RuntimeError(f"GET محصول #{pid}: {message or err_code} (HTTP {status_code})")

    try:
        return wc_call(wcapi, f"بررسی محصول #{pid}", _get, retries=1)
    except Exception as exc:
        log.warning(f"⚠️ بررسیِ محصولِ #{pid} رویِ سایت ناموفق بود: {exc}")
        return "error", None


def check_mapped_product_identity(sku: str, info: dict | None, link_meta: dict | None = None) -> tuple[bool, str]:
    """آیا این محصولِ سایت واقعاً همونیه که SKUِ ERP بهش لینک شده؟

    بعد از ریستِ سایت (یا حذف و ساختِ دوباره)، وردپرس/پرستاشاپ شناسه‌ها رو
    از نو به محصولاتِ دیگه می‌ده — پس «شناسه هنوز رویِ سایت هست» کافی نیست.
    قانون: یا SKUِ محصولِ سایت با SKUِ ERP یکیه، یا یک تطبیقِ دستیِ آگاهانه
    به همین شناسه ثبت شده و اثرِ انگشتِ همون محصول (تاریخِ ساخت، وگرنه SKUِ
    سایت در لحظه‌یِ تطبیق) هنوز می‌خونه. لینکِ دستیِ قدیمیِ بدونِ اثرِ انگشت
    یک‌بار پذیرفته می‌شه (و اثرِ انگشتش ثبت می‌شه)."""
    if not isinstance(info, dict) or not info.get("id"):
        return False, "رویِ سایت پیدا نشد"
    pid = int(info["id"])
    if str(info.get("type") or "").strip() == "variation":
        return False, f"شناسه‌یِ #{pid} الان یک واریانت است، نه محصول"
    erp_sku = str(sku or "").strip()
    site_sku = str(info.get("sku") or "").strip()

    meta = link_meta if isinstance(link_meta, dict) else None
    manual = bool(meta and meta.get("manual") and int(meta.get("wc_id") or 0) == pid)
    if manual:
        rec_created = str(meta.get("wc_created") or "").strip()
        live_created = str(info.get("date_created_gmt") or "").strip()
        if rec_created and live_created:
            if rec_created == live_created:
                return True, ""
            return False, (
                f"محصولِ #{pid} بعد از تطبیقِ دستی دوباره ساخته شده (تاریخِ ساخت عوض شده) — "
                "این شناسه الان مالِ محصولِ دیگری‌ست"
            )
        if "wc_sku" in meta:
            rec_sku = str(meta.get("wc_sku") or "").strip()
            if site_sku.casefold() in (rec_sku.casefold(), erp_sku.casefold()):
                return True, ""
            return False, (
                f"SKUِ محصولِ #{pid} رویِ سایت «{site_sku or '—'}» است، "
                f"ولی موقعِ تطبیقِ دستی «{rec_sku or '—'}» بود"
            )
        return True, ""

    if erp_sku and site_sku.casefold() == erp_sku.casefold():
        return True, ""
    return False, f"محصولِ #{pid} رویِ سایت SKUِ «{site_sku or '—'}» دارد، نه «{erp_sku}»"


def forget_product_site_state(sku: str, product_map: dict | None = None, *, clear_manual: bool = True) -> None:
    """هر چیزی که به «محصولِ قبلیِ این SKU رویِ سایت» گره خورده پاک می‌شه —
    نگاشت، لینکِ دستی، هشِ تشخیصِ تغییر و سابقه‌یِ «تصاویر منتقل شد» — تا
    محصولِ جدید/درستِ بعدی از صفر و کامل (با تصاویر) سینک بشه."""
    sku = str(sku or "").strip()
    if not sku:
        return
    if product_map is not None:
        product_map.pop(sku, None)
        save_product_woo_map(product_map)
    from sync_app.core.product_woo_map_meta import clear_product_link_meta
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sync_change_cache import clear_hash_cache_entry
    from sync_app.core.erp_image_helper import forget_transferred_images

    if clear_manual:
        clear_product_link_meta(sku)
    config = load_secure_config(None)
    clear_hash_cache_entry("products", sku, config)
    forget_transferred_images(sku, _current_platform())


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
                and str(row.get("type") or "").strip() != "variation"
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

    from sync_app.core.product_woo_map_meta import get_product_link_meta, record_product_link_fingerprint

    link_meta = get_product_link_meta(sku)
    cached = product_map.get(sku)
    if not cached and link_meta and link_meta.get("manual") and link_meta.get("wc_id"):
        # نگاشت گم شده ولی لینکِ دستی هنوز ثبته — به‌جایِ ساختِ محصولِ
        # تکراری، همون محصولِ لینک‌شده (بعد از تاییدِ هویت) دوباره استفاده می‌شه.
        cached = int(link_meta["wc_id"])

    if cached:
        state, info = fetch_product_state(wcapi, int(cached))
        if state == "error":
            raise RuntimeError(
                f"[{sku}] بررسیِ محصولِ لینک‌شده‌یِ سایت (#{cached}) به‌خاطرِ خطایِ ارتباط ممکن نشد — "
                "این کالا این دور رد شد تا به‌اشتباه محصولِ تکراری ساخته نشه یا رویِ محصولِ دیگری نوشته نشه."
            )
        status = str((info or {}).get("status") or "").strip()
        if state == "missing" or status == "trash":
            reason = "در سطل‌زباله است" if status == "trash" else "رویِ سایت حذف شده"
            log.info(f"ℹ️ [{sku}] محصولِ لینک‌شده‌یِ سایت (#{cached}) {reason} — لینکِ قدیمی پاک و از نو بررسی می‌شه.")
            forget_product_site_state(sku, product_map)
        elif not _is_active_wc_product(info):
            forget_product_site_state(sku, product_map, clear_manual=False)
        else:
            ok, why = check_mapped_product_identity(sku, info, link_meta)
            if ok:
                mapped_sku = str(info.get("sku") or "").strip()
                if link_meta and link_meta.get("manual"):
                    record_product_link_fingerprint(
                        sku, int(info["id"]), wc_sku=mapped_sku, wc_created=info.get("date_created_gmt"),
                    )
                if mapped_sku != sku:
                    log.info(f"ℹ️ [{sku}] تطبیق دستی → Woo #{cached} (SKU سایت: {mapped_sku or '—'})")
                if int(product_map.get(sku) or 0) != int(info["id"]):
                    product_map[sku] = int(info["id"])
                    save_product_woo_map(product_map)
                return int(info["id"]), product_map
            log.warning(
                f"⚠️ [{sku}] لینکِ ذخیره‌شده به #{cached} دیگه معتبر نیست ({why}) — "
                "به این محصول دست زده نمی‌شه؛ لینکِ قدیمی پاک شد و از نو بررسی می‌شه."
            )
            forget_product_site_state(sku, product_map)

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


_LEGACY_LINK_MIGRATION_FLAG = "identity_check_migrated.flag"


def _norm_product_name(name) -> str:
    text = str(name or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    return " ".join(text.split()).casefold()


def grandfather_legacy_links(
    product_map: dict, live_index: dict | None, erp_names: dict, *, name_sync_enabled: bool = True,
) -> int:
    """یک‌بار، اولین سینکِ بعد از این نسخه: لینک‌هایِ قدیمی‌ای که به محصولی با
    SKUِ متفاوت اشاره می‌کنن ولی هیچ سابقه‌یِ «تطبیقِ دستی» ندارن (مثلاً لینکِ
    والدِ واریانت‌ها از تبِ تطبیق در نسخه‌هایِ قبل) به‌عنوانِ لینکِ دستی با
    اثرِ انگشتِ فعلی ثبت می‌شن — تا قانونِ جدیدِ هویت (check_mapped_product_identity)
    تطبیق‌هایِ درست و قدیمیِ مشتری رو نشکنه و محصولِ تکراری نسازه.

    erp_names: {SKUِ ERP: نامِ کالا در ERP}.
    ثبت نمی‌شه (تا سینک اصلاحش کنه) وقتی:
    - SKUِ محصولِ سایت خودش کدِ یک کالایِ دیگه‌یِ ERP باشه؛ یا
    - همگام‌سازیِ «نام» روشنه ولی نامِ محصولِ سایت با نامِ کالا در ERP یکی
      نیست — یعنی سینک هیچ‌وقت واقعاً رویِ این محصول نمی‌نوشته و این شناسه
      بعد از ریستِ سایت به یک محصولِ بی‌ربط رسیده.
    live_index باید کامل باشه (fetch_live_wc_ids موفق)."""
    if live_index is None:
        return 0
    flag_path = site_scoped_path(_LEGACY_LINK_MIGRATION_FLAG)
    import os

    if os.path.isfile(flag_path):
        return 0
    from sync_app.core.product_woo_map_meta import load_product_woo_map_meta, save_product_woo_map_meta
    from datetime import datetime, timezone

    erp_set = {str(x).strip().casefold() for x in (erp_names or {}) if str(x).strip()}
    meta = load_product_woo_map_meta()
    links = meta.setdefault("links", {})
    added = 0
    for sku, pid in (product_map or {}).items():
        sku = str(sku or "").strip()
        if not sku or sku in links:
            continue
        live = live_index.get(int(pid or 0))
        if not live:
            continue
        site_sku = str(live.get("sku") or "").strip()
        if site_sku.casefold() == sku.casefold():
            continue
        if site_sku and site_sku.casefold() in erp_set:
            continue
        if name_sync_enabled and _norm_product_name(live.get("name")) != _norm_product_name((erp_names or {}).get(sku)):
            continue
        links[sku] = {
            "wc_id": int(pid),
            "wc_label": "",
            "manual": True,
            "sku_conflict_wc_id": None,
            "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "wc_sku": site_sku,
            "wc_created": str(live.get("date_created_gmt") or ""),
            "grandfathered": True,
        }
        added += 1
    if added:
        save_product_woo_map_meta(meta)
        log.info(f"ℹ️ {added} لینکِ قدیمی با SKUِ متفاوت به‌عنوانِ «تطبیقِ دستی» حفظ شد (یک‌بار، بعد از به‌روزرسانی).")
    try:
        with open(flag_path, "w", encoding="utf-8") as f:
            f.write("1")
    except Exception:
        pass
    return added


def fetch_live_wc_ids(wcapi, config=None) -> dict[int, dict] | None:
    """{id: {"id", "sku", "date_created_gmt"}} برایِ همه‌ی محصولاتِ زنده‌یِ
    سایت (برایِ ووکامرس: هر وضعیتی جز trash؛ پرستاشاپ زباله‌دان نداره، هر چی
    برگرده زنده‌ست) — یک واکشیِ سبکِ یک‌جا در ابتدایِ سینکِ کامل. SKU و
    تاریخِ ساخت هم برمی‌گردن تا فراخوان بتونه «شناسه هنوز هست ولی مالِ
    محصولِ دیگری‌ست» (بعد از ریستِ سایت) رو هم تشخیص بده
    (check_mapped_product_identity)، نه فقط «حذف شده».

    چرا لازمه: تشخیصِ‌تغییرِ سینک (should_skip_unchanged) وقتی SKU در
    product_woo_map.json باشه و دادهٔ ERP از آخرین‌بار عوض نشده باشه،
    بی‌صدا رد می‌کنه — بدونِ این‌که هیچ‌وقت با سایت چک کنه اون محصول
    هنوز زنده‌ست یا نه. اگه کاربر محصول رو مستقیم رویِ سایت پاک کرده
    باشه، این یعنی سینکِ بعدی هیچ‌وقت متوجه نمی‌شه و محصولِ جدید هم
    نمی‌سازه. با این مجموعه، فراخوان می‌تونه قبل از تصمیمِ رد/نرد،
    نگاشتِ محلی رو با واقعیتِ سایت تطبیق بده — بدونِ نیازِ به یک
    درخواستِ جدا به‌ازایِ هر SKU (که کندی رو کاملاً نقض می‌کرد).

    خروجی None یعنی خودِ واکشی ناموفق بود (نه اینکه فروشگاه خالیه) —
    فراخوان باید در این حالت به رفتارِ قبلی (اعتماد به نگاشتِ محلی)
    برگرده؛ وگرنه یک قطعیِ موقتِ شبکه می‌تونه باعثِ ساختِ محصولاتِ
    تکراری برایِ صدها SKUِ کاملاً معتبر بشه."""
    from sync_app.core.integrations.commerce_provider import is_prestashop

    cfg = config or {}
    if is_prestashop(cfg):
        from sync_app.core.ps_sync_helper import ps_list_products

        try:
            products = ps_list_products(cfg)
        except Exception as exc:
            log.warning(f"⚠️ واکشیِ idهایِ زندهٔ محصولاتِ پرستاشاپ ناموفق بود: {exc}")
            return None
        return {
            int(p["id"]): {
                "id": int(p["id"]), "sku": str(p.get("sku") or ""), "name": str(p.get("name") or ""),
                "date_created_gmt": str(p.get("date_created_gmt") or ""),
            }
            for p in products if isinstance(p, dict) and p.get("id")
        }

    ids: dict[int, dict] = {}
    page = 1
    while True:
        try:
            resp = wcapi.get(
                "products",
                params={"_fields": "id,status,sku,name,date_created_gmt", "status": "any", "per_page": 100, "page": page},
            )
            data = wc_parse_json(resp, "واکشیِ idهایِ زندهٔ محصولات")
        except Exception as exc:
            log.warning(f"⚠️ واکشیِ idهایِ زندهٔ محصولاتِ ووکامرس ناموفق بود (صفحه {page}): {exc}")
            return None
        if not isinstance(data, list) or not data:
            break
        for row in data:
            if isinstance(row, dict) and row.get("id") and _is_active_wc_product(row):
                ids[int(row["id"])] = {
                    "id": int(row["id"]),
                    "sku": str(row.get("sku") or ""),
                    "name": str(row.get("name") or ""),
                    "date_created_gmt": str(row.get("date_created_gmt") or ""),
                }
        if len(data) < 100:
            break
        page += 1
    return ids


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
