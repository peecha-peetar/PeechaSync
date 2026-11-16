# مسیرها، لاگ، چک SQL/Woo
import io
import logging
import logging.handlers
import pyodbc
import requests
import os
import sys
from typing import Iterable

def get_base_path():
    """ مسیر exe یا پروژه """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def resource_path(*parts):
    """ فایل read-only: فونت، qss، bin """
    base = getattr(sys, '_MEIPASS', get_base_path())
    return os.path.join(base, *parts)


def brand_icon_file() -> str:
    """مسیر آیکن رسمی برند — ICO روی ویندوز برای taskbar."""
    from sync_app.core.brand_assets import brand_icon_path

    return brand_icon_path()


def resolve_runnable_script(base_dir, script_name):
    """مسیر اجرای اسکript — در بسته portable فقط .pyc تحویل می‌شود."""
    if script_name.endswith(".py"):
        pyc_name = script_name[:-3] + ".pyc"
        pyc_path = os.path.join(base_dir, pyc_name)
        if os.path.isfile(pyc_path):
            return pyc_path
    return os.path.join(base_dir, script_name)

def app_dir():
    """پوشه دادهٔ قابل‌نوشتن — per-profile یا AppData (هرگز Program Files)."""
    try:
        from sync_app.core.user_profile import get_current_profile_id, ensure_profile_dir

        pid = get_current_profile_id()
        if pid:
            return ensure_profile_dir(pid)
    except Exception:
        pass

    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(local, "PeechaSync", "default")
    os.makedirs(path, exist_ok=True)
    return path


def app_path(*parts):
    """ فایل writable: log, json """
    return os.path.join(app_dir(), *parts)


def _database_scope_token(cfg=None) -> str:
    """شناسهٔ پایدار دیتابیس: سرور + نام دیتابیس.

    مسیر فایل MDF داخل شناسه نیست تا جابه‌جایی همان دیتابیس لینک‌ها را
    دور نیندازد. master هم نادیده گرفته می‌شود چون فقط برای Attach است.
    """
    if cfg is None:
        try:
            from sync_app.core.secure_config_loader import load_secure_config

            cfg = load_secure_config(None) or {}
        except Exception:
            cfg = {}
    server = str((cfg or {}).get("SQL_SERVER") or "").strip().lower().replace(" ", "")
    database = str((cfg or {}).get("SQL_DATABASE") or "").strip().lower()
    if database == "master":
        database = ""
    if not server and not database:
        return ""
    return f"{server}|{database}"


def _site_scope_key(*, include_family: bool = True, include_database: bool = True, include_provider: bool = True) -> str:
    """شناسه‌ی یکتا برایِ «کدوم سایت/پلتفرمِ فروشگاهی + کدوم خانواده‌یِ
    ERP الان فعاله» (پلتفرم + آدرسِ سایت + خانواده‌یِ schemaیِ ERP). برایِ
    namespace کردنِ فایل‌هایِ وضعیتِ سینک (نگاشتِ SKU↔ID، نگاشتِ
    دسته‌بندی و مانندِ آن) که وگرنه: (۱) وقتی یک پروفایل چند سایت/پلتفرمِ
    مختلف داره (چند پریست یا چند WC_SITES/PS_SITES)، بینِ اونا به‌اشتباه
    به اشتراک گذاشته می‌شن؛ (۲) وقتی همون یک سایت رو یک‌بار با یک ERP
    (مثلاً دژاوو) و بعداً با ERPِ دیگه‌ای با schemaیِ متفاوت (مثلاً سپیدار)
    سینک می‌کنن، کدِ کالایِ یک ERP به‌اشتباه به‌عنوانِ کدِ کالایِ ERPِ
    دیگه خونده می‌شه (چون فقط رشته‌کد یکسانه، نه معنا). `include_family`
    فقط برایِ محاسبه‌یِ مسیرِ legacy (پیش از افزودنِ خانواده‌یِ ERP به این
    شناسه) در مهاجرتِ site_scoped_path استفاده می‌شه."""
    try:
        from sync_app.core.secure_config_loader import load_secure_config
        from sync_app.core.integrations.commerce_provider import store_platform

        cfg = load_secure_config(None) or {}
        platform = store_platform(cfg)
        url_key = "PS_URL" if platform == "prestashop" else "WC_URL"
        raw_url = str(cfg.get(url_key) or "")
        url = _normalize_scope_url(raw_url, platform)
        raw = f"{platform}:{url}" if url else platform
        if include_family:
            from sync_app.core.integrations.erp_provider import erp_schema_family

            raw = f"{raw}:{erp_schema_family(cfg)}"
        if include_provider:
            from sync_app.core.integrations.erp_provider import normalize_erp_provider_key

            raw = f"{raw}:{normalize_erp_provider_key(cfg.get('ERP_PROVIDER'))}"
        if include_database:
            db_token = _database_scope_token(cfg)
            if db_token:
                raw = f"{raw}:{db_token}"
    except Exception:
        raw = "default"

    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _migrate_pre_database_scope_dir() -> None:
    """پوشهٔ لینکِ قبلی (بدون شناسهٔ دیتابیس) یک‌بار به پوشهٔ دیتابیسِ
    فعلی منتقل می‌شود. دیتابیسِ بعدی پوشهٔ خالی می‌گیرد."""
    if not _database_scope_token():
        return
    new_key = _site_scope_key(include_provider=False)
    old_key = _site_scope_key(include_database=False, include_provider=False)
    if new_key == old_key:
        return
    new_dir = os.path.join(app_dir(), "sites", new_key)
    old_dir = os.path.join(app_dir(), "sites", old_key)
    if os.path.isdir(new_dir) or not os.path.isdir(old_dir):
        return
    try:
        os.rename(old_dir, new_dir)
    except OSError:
        pass


def _migrate_pre_provider_scope_dir() -> None:
    """دژاوو، هلو، دشت و سپیدار پوشهٔ لینک جدا دارند.

    پوشهٔ قبلیِ خانواده (دژاوو/هلو با هم، دشت/سپیدار با هم) یک‌بار به
    نرم‌افزارِ الان منتقل می‌شود. نرم‌افزارِ بعدی پوشهٔ خالی می‌گیرد.
    """
    new_key = _site_scope_key()
    old_key = _site_scope_key(include_provider=False)
    if new_key == old_key:
        return
    new_dir = os.path.join(app_dir(), "sites", new_key)
    old_dir = os.path.join(app_dir(), "sites", old_key)
    if os.path.isdir(new_dir) or not os.path.isdir(old_dir):
        return
    try:
        os.rename(old_dir, new_dir)
    except OSError:
        pass


def _normalize_scope_url(raw_url: str, platform: str) -> str:
    """نرمال‌سازیِ آدرسِ سایت برایِ محاسبه‌یِ scope key — قبلاً فقط
    lower/rstrip('/')/حذفِ scheme انجام می‌شد؛ یعنی همون سایت با
    «www.» یا پسوندِ «/wp-json/wc/v3» (که برایِ خودِ اتصالِ API بی‌اثره،
    چون wc_api_helper.normalize_wc_store_url جداگانه حذفش می‌کنه) یک
    scope keyِ متفاوت می‌ساخت — یعنی همون سایت، بعدِ ویرایشِ جزئیِ آدرس
    در تنظیمات، یک پوشه‌یِ کاملاً خالی و بی‌ربط می‌گرفت و همه‌یِ
    لینک‌های قبلی گم به‌نظر می‌رسیدن (در حالی که فقط در پوشه‌یِ قبلی
    جا مونده بودن). حالا هم www./wp-json حذف می‌شن تا نوشتارهایِ
    مختلفِ یک آدرسِ یکسان به یک scope key برسن."""
    url = str(raw_url or "").strip().lower().rstrip("/")
    if platform != "prestashop" and url:
        from sync_app.core.wc_api_helper import normalize_wc_store_url

        url = normalize_wc_store_url(url).lower().rstrip("/")
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    if url.startswith("www."):
        url = url[4:]
    return url


def _legacy_unnormalized_site_scope_key(*, include_family: bool = True) -> str:
    """محاسبه‌یِ scope keyِ دقیقاً مثلِ قبل از افزودنِ نرمال‌سازیِ
    www./wp-json — فقط برایِ مهاجرتِ یک‌باره در site_scoped_path (پایین)
    استفاده می‌شه، تا اگه آدرسِ ذخیره‌شده‌یِ کاربر از قبل شاملِ www./
    wp-json بوده (و دیتایِ واقعی‌اش زیرِ اون hashِ قدیمی نشسته)، همون
    دیتا خودکار پیدا و منتقل بشه — بدونِ این تابع، نرمال‌سازیِ بالا برایِ
    این کاربرهایِ خاص باعثِ گم‌شدنِ دوباره‌یِ لینک‌ها می‌شد."""
    try:
        from sync_app.core.secure_config_loader import load_secure_config
        from sync_app.core.integrations.commerce_provider import store_platform

        cfg = load_secure_config(None) or {}
        platform = store_platform(cfg)
        url_key = "PS_URL" if platform == "prestashop" else "WC_URL"
        url = str(cfg.get(url_key) or "").strip().lower().rstrip("/")
        for prefix in ("https://", "http://"):
            if url.startswith(prefix):
                url = url[len(prefix):]
                break
        raw = f"{platform}:{url}" if url else platform
        if include_family:
            from sync_app.core.integrations.erp_provider import erp_schema_family

            raw = f"{raw}:{erp_schema_family(cfg)}"
    except Exception:
        raw = "default"

    import hashlib

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def site_scoped_path(*parts):
    """مسیرِ فایلِ وضعیتِ سینکِ مخصوصِ سایت/پلتفرم/خانواده‌یِ ERP و دیتابیسِ
    فعلی — برایِ category_map.json، product_woo_map.json و مشابه.

    دو مهاجرتِ یک‌باره‌یِ زنجیره‌ای، هر دو move (نه copy) با یک بکاپِ
    کنارِ فایلِ اصلی:
    ۱) از نسخه‌ی خیلی قدیمیِ مسطح (پیش از وجودِ site-scoping، وقتی این
       فایل‌ها بینِ همه‌ی سایت‌هایِ یک پروفایل مشترک بودن).
    ۲) از نسخه‌ی site-scopedِ بدونِ خانواده‌یِ ERP (پیش از افزودنِ
       erp_schema_family به‌شناسه — یعنی همون مسیری که تا نسخه‌ی ۲.۳۰.۱۳۳
       استفاده می‌شد). چون تا پیش از این، تنها ERPِ واقعاً پیاده‌شده
       دژاوو/هلو بود، این مهاجرت عملاً یعنی «دیتایِ قبلیِ هر سایت به
       خانواده‌ی دژاوو منتقل می‌شه» — دقیقاً همون چیزی که کاربرهایِ فعلی
       انتظار دارن (هیچ دیتایی گم نمی‌شه)."""
    _migrate_pre_database_scope_dir()
    _migrate_pre_provider_scope_dir()
    base = os.path.join(app_dir(), "sites", _site_scope_key())
    os.makedirs(base, exist_ok=True)
    target = os.path.join(base, *parts)
    if not os.path.exists(target):
        try:
            import shutil

            legacy = os.path.join(app_dir(), *parts)
            if os.path.isfile(legacy):
                shutil.copyfile(legacy, legacy + ".pre_site_scope_backup")
                shutil.move(legacy, target)
            else:
                legacy_scoped = os.path.join(
                    app_dir(), "sites", _site_scope_key(include_family=False), *parts
                )
                if os.path.isfile(legacy_scoped):
                    shutil.copyfile(legacy_scoped, legacy_scoped + ".pre_erp_family_scope_backup")
                    shutil.move(legacy_scoped, target)
                else:
                    # مهاجرتِ سوم: قبل از افزودنِ نرمال‌سازیِ www./wp-json به
                    # _site_scope_key، آدرسِ سایت خام هش می‌شد — اگه آدرسِ
                    # ذخیره‌شده‌یِ کاربر از قبل شاملِ www./wp-json بوده،
                    # دیتایِ واقعی‌اش زیرِ اون hashِ قدیمی‌تر نشسته. copy (نه
                    # move) تا اگه چندتا فایل با کلیدهایِ قدیمیِ مختلف باشن،
                    # فراخوانیِ بعدی هم بتونه دوباره بهش برسه.
                    legacy_unnormalized = os.path.join(
                        app_dir(), "sites", _legacy_unnormalized_site_scope_key(), *parts
                    )
                    if os.path.isfile(legacy_unnormalized) and legacy_unnormalized != target:
                        shutil.copyfile(legacy_unnormalized, target)
        except Exception:
            pass
    _ensure_site_scope_marker(base)
    return target


def _ensure_site_scope_marker(scope_dir: str) -> None:
    """یک فایلِ scope.json سبک کنارِ فایل‌هایِ سایت می‌نویسه (فقط یک‌بار،
    نه در هر فراخوانی) — پلتفرم/آدرس/خانواده‌یِ ERPِ صاحبِ این پوشه رو
    ثبت می‌کنه. هدف: اگه بعداً scope keyِ فعلی به هر دلیلی عوض بشه (مثلِ
    باگِ گزارش‌شده)، بشه از رویِ همین مارکر پوشه‌هایِ قدیمی رو در تبِ
    تنظیمات پیدا و بازیابی کرد — بدونِ این مارکر، پوشه فقط یک hashِ
    بی‌معنیه و هیچ‌جا ثبت نشده کدوم سایت/ERP بوده."""
    marker_path = os.path.join(scope_dir, "scope.json")
    try:
        import json
        import time

        from sync_app.core.secure_config_loader import load_secure_config
        from sync_app.core.integrations.commerce_provider import store_platform
        from sync_app.core.integrations.erp_provider import erp_schema_family, normalize_erp_provider_key

        cfg = load_secure_config(None) or {}
        platform = store_platform(cfg)
        url_key = "PS_URL" if platform == "prestashop" else "WC_URL"
        database = _database_scope_token(cfg)
        provider = normalize_erp_provider_key(cfg.get("ERP_PROVIDER"))
        if os.path.exists(marker_path):
            try:
                with open(marker_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = None
            if not isinstance(existing, dict):
                return
            changed = False
            if existing.get("database") != database:
                existing["database"] = database
                changed = True
            if existing.get("erp_provider") != provider:
                existing["erp_provider"] = provider
                changed = True
            if not changed:
                return
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            return
        data = {
            "platform": platform,
            "url": str(cfg.get(url_key) or "").strip(),
            "erp_family": erp_schema_family(cfg),
            "erp_provider": provider,
            "database": database,
            "created_at": time.time(),
        }
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


SOURCE_DB_META = "peecha_source_database"
SOURCE_ERP_META = "peecha_source_erp"
SOURCE_LABEL_META = "peecha_source_label"
PS_LOCATION_PREFIX = "PeechaDB:"
_SITE_SKU_LIMIT = 64
_ERP_FA = {"dejavu": "دژاوو", "holoo": "هلو", "sepidar": "سپیدار", "dasht": "دشت"}


def current_source_erp(config=None) -> str:
    """دژاوو، هلو، دشت و سپیدار هر کدام نرم‌افزار جدا هستند."""
    try:
        from sync_app.core.integrations.erp_provider import normalize_erp_provider_key
    except Exception:
        return ""
    if config is None:
        try:
            from sync_app.core.secure_config_loader import load_secure_config

            config = load_secure_config(None) or {}
        except Exception:
            config = {}
    return normalize_erp_provider_key((config or {}).get("ERP_PROVIDER"))


def remember_selected_groups(config: dict) -> dict:
    """گروه‌های انتخاب‌شدهٔ همین نرم‌افزار را جدا نگه می‌دارد."""
    if not isinstance(config, dict):
        return config
    provider = current_source_erp(config)
    groups = [str(g).strip() for g in (config.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]
    by = dict(config.get("SELECTED_SUB_GROUPS_BY_ERP") or {})
    if provider:
        by[provider] = groups
    config["SELECTED_SUB_GROUPS_BY_ERP"] = by
    config["SELECTED_SUB_GROUPS"] = groups
    return config


def swap_selected_groups_for_provider(config: dict, old_provider: str, new_provider: str) -> dict:
    """با عوض شدن نرم‌افزار، گروه‌های قبلی ذخیره و گروه‌های نرم‌افزار جدید بار می‌شود."""
    if not isinstance(config, dict):
        return config
    old_provider = str(old_provider or "").strip().lower()
    new_provider = str(new_provider or "").strip().lower()
    by = dict(config.get("SELECTED_SUB_GROUPS_BY_ERP") or {})
    current = [str(g).strip() for g in (config.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]
    if old_provider:
        by[old_provider] = current
    config["SELECTED_SUB_GROUPS"] = list(by.get(new_provider) or []) if new_provider != old_provider else current
    if new_provider:
        by[new_provider] = list(config["SELECTED_SUB_GROUPS"])
    config["SELECTED_SUB_GROUPS_BY_ERP"] = by
    return config


def erp_source_label(provider: str) -> str:
    return _ERP_FA.get(str(provider or "").strip().lower(), str(provider or "").strip() or "نرم‌افزار دیگر")


def _connection_names(config=None) -> tuple[str, str]:
    """نام سرور و دیتابیس همان‌طور که در تنظیم اتصال ذخیره شده."""
    if config is None:
        try:
            from sync_app.core.secure_config_loader import load_secure_config

            config = load_secure_config(None) or {}
        except Exception:
            config = {}
    server = str((config or {}).get("SQL_SERVER") or "").strip()
    database = str((config or {}).get("SQL_DATABASE") or "").strip()
    if database.lower() == "master":
        database = ""
    return server, database


def source_product_mark(config=None) -> str:
    """برچسب روی کالا: نام سرور - نام دیتابیس."""
    server, database = _connection_names(config)
    return " - ".join(part for part in (server, database) if part)


def site_sku_for_source(erp_sku, config=None, limit: int = _SITE_SKU_LIMIT) -> str:
    """کد سایت یکتا برای همین سرور و دیتابیس. کد نرم‌افزار در انتها می‌ماند."""
    raw = str(erp_sku or "").strip()
    mark = source_product_mark(config)
    if not raw or not mark:
        return raw
    prefix = f"{mark} - "
    if raw.startswith(prefix):
        raw = raw[len(prefix):].strip()
    full = f"{prefix}{raw}"
    if len(full) <= limit:
        return full
    room = limit - len(raw) - 3
    if room < 1:
        return raw[:limit]
    short = mark[:room].rstrip(" -")
    return f"{short} - {raw}"


def erp_code_from_site_sku(site_sku, config=None) -> str:
    """کد نرم‌افزار را از کد سایت همین سرور برمی‌گرداند."""
    text = str(site_sku or "").strip()
    if not text:
        return ""
    mark = source_product_mark(config)
    prefix = f"{mark} - " if mark else ""
    if prefix and text.startswith(prefix):
        return text[len(prefix):].strip()
    if " - " in text:
        tail = text.rsplit(" - ", 1)[-1].strip()
        if tail and site_sku_for_source(tail, config).casefold() == text.casefold():
            return tail
    return text


def site_sku_matches_erp(site_sku, erp_sku, config=None) -> bool:
    site = str(site_sku or "").strip()
    erp = str(erp_sku or "").strip()
    if not site or not erp:
        return False
    if site.casefold() == erp.casefold():
        return True
    return site.casefold() == site_sku_for_source(erp, config).casefold()


def order_line_erp_sku(site_sku, config=None) -> tuple[str, bool]:
    """کد خط سفارش برای دیتابیس وصل‌شده. خروجی دوم: خط مال سرور دیگری است."""
    text = str(site_sku or "").strip()
    if not text:
        return "", False
    code = erp_code_from_site_sku(text, config)
    if code != text:
        return code, False
    if source_product_mark(config) and text.count(" - ") >= 2:
        return "", True
    return text, False


def product_is_other_source(info, pid=None) -> bool:
    """کالای سایت مال سرور، دیتابیس یا نرم‌افزار دیگری است و نباید بازنویسی شود."""
    current_erp = current_source_erp()
    stamped_erp = source_erp_on_product(info)
    if current_erp and stamped_erp and stamped_erp != current_erp:
        return True
    current = _database_scope_token()
    stamped = source_database_on_product(info)
    if current and stamped and stamped.casefold() != current.casefold():
        return True
    if current and stamped and stamped.casefold() == current.casefold():
        return False
    try:
        pid_int = int(pid or (info or {}).get("id") or 0)
    except (TypeError, ValueError):
        pid_int = 0
    if pid_int and pid_int in product_ids_owned_by_other_databases():
        return True
    return False


def apply_source_product_identity(payload: dict, erp_sku, config=None) -> dict:
    """نام و کد سایت را با «سرور - دیتابیس» مشخص می‌کند تا کالای سرور دیگر بازنویسی نشود."""
    if not isinstance(payload, dict):
        return payload
    mark = source_product_mark(config)
    if "sku" in payload and str(payload.get("sku") or "").strip():
        raw = str(erp_sku or payload.get("sku") or "").strip()
        payload["sku"] = site_sku_for_source(raw, config)
    name = str(payload.get("name") or "").strip()
    if name and mark:
        prefix = f"{mark} - "
        if not name.startswith(prefix):
            payload["name"] = f"{prefix}{name}"
    payload = stamp_payload_source_database(payload, config)
    if mark:
        meta = [
            item for item in (payload.get("meta_data") or [])
            if not (isinstance(item, dict) and str(item.get("key") or "") == SOURCE_LABEL_META)
        ]
        meta.append({"key": SOURCE_LABEL_META, "value": mark})
        payload["meta_data"] = meta
    return payload


def stamp_payload_source_database(payload: dict, config=None) -> dict:
    """نام نرم‌افزار و دیتابیس فعلی را روی محصول سایت می‌نویسد."""
    if not isinstance(payload, dict):
        return payload
    token = _database_scope_token(config)
    provider = current_source_erp(config)
    if not token and not provider:
        return payload
    meta = [
        item for item in (payload.get("meta_data") or [])
        if not (
            isinstance(item, dict)
            and str(item.get("key") or "") in (SOURCE_DB_META, SOURCE_ERP_META)
        )
    ]
    if token:
        meta.append({"key": SOURCE_DB_META, "value": token})
    if provider:
        meta.append({"key": SOURCE_ERP_META, "value": provider})
    payload["meta_data"] = meta
    return payload


def _meta_value(info, key: str) -> str:
    for item in (info or {}).get("meta_data") or []:
        if isinstance(item, dict) and str(item.get("key") or "") == key:
            return str(item.get("value") or "").strip()
    return ""


def source_database_on_product(info) -> str:
    return _meta_value(info, SOURCE_DB_META)


def source_erp_on_product(info) -> str:
    return _meta_value(info, SOURCE_ERP_META).lower()


def ps_location_for_source_database(token: str, current_location: str = "") -> str:
    """مکان انبار پرستاشاپ فقط وقتی خالی یا مال خود پیچا باشد پر می‌شود."""
    current = str(current_location or "")
    if current and not current.startswith(PS_LOCATION_PREFIX):
        return current
    token = str(token or "").strip()
    if not token:
        return current
    stamp = f"{PS_LOCATION_PREFIX}{token}"
    if len(stamp) > 64:
        return current
    return stamp


def reject_foreign_product(sku: str, pid: int, info, *, manual: bool = False, check_other_map: bool = False) -> None:
    """تطبیق دستی همیشه مجاز است. ارسال خودکار روی کالای دیتابیس دیگر نوشته نمی‌شود."""
    if manual:
        return
    current_erp = current_source_erp()
    stamped_erp = source_erp_on_product(info)
    if current_erp and stamped_erp and stamped_erp != current_erp:
        raise RuntimeError(
            f"[{sku}] محصول #{int(pid)} روی سایت به نرم‌افزار «{erp_source_label(stamped_erp)}» وصل است. "
            "دژاوو، هلو، دشت و سپیدار روی کالای یکدیگر نوشته نمی‌شوند. "
            "اگر باید همین کالا وصل شود، از تطبیق دستی استفاده کنید."
        )
    current = _database_scope_token()
    stamped = source_database_on_product(info)
    if current and stamped and stamped != current:
        raise RuntimeError(
            f"[{sku}] محصول #{int(pid)} روی سایت به دیتابیس «{stamped}» وصل است. "
            "عنوان و قیمت دیتابیس فعلی روی آن نوشته نشد. "
            "اگر باید همین کالا وصل شود، از تطبیق دستی استفاده کنید."
        )
    if check_other_map and int(pid) in product_ids_owned_by_other_databases():
        raise RuntimeError(
            f"[{sku}] محصول #{int(pid)} روی این سایت قبلاً به دیتابیس دیگری وصل شده است. "
            "قیمت، موجودی و متغیر دیتابیس فعلی روی آن نوشته نشد تا قاطی نشود. "
            "اگر باید همین محصول وصل شود، از تطبیق دستی استفاده کنید."
        )


_other_db_product_ids: tuple[str, set[int]] | None = None


def product_ids_owned_by_other_databases() -> set[int]:
    """شناسهٔ محصولاتی که در نگاشتِ دیتابیسِ دیگری برای همین سایت ثبت شده‌اند."""
    global _other_db_product_ids
    current_key = _site_scope_key()
    if _other_db_product_ids and _other_db_product_ids[0] == current_key:
        return _other_db_product_ids[1]

    owned: set[int] = set()
    try:
        import json

        from sync_app.core.secure_config_loader import load_secure_config
        from sync_app.core.integrations.commerce_provider import store_platform
        from sync_app.core.integrations.erp_provider import erp_schema_family

        cfg = load_secure_config(None) or {}
        platform = store_platform(cfg)
        url_key = "PS_URL" if platform == "prestashop" else "WC_URL"
        current_site = (
            platform,
            _normalize_scope_url(str(cfg.get(url_key) or ""), platform),
        )
        current_db = _database_scope_token(cfg)
        current_erp = current_source_erp(cfg)
        current_family = erp_schema_family(cfg)
        legacy_keys = {
            _site_scope_key(include_provider=False),
            _site_scope_key(include_database=False, include_provider=False),
            _site_scope_key(include_database=False),
        }
        root = os.path.join(app_dir(), "sites")
        for name in os.listdir(root):
            if name == current_key or name in legacy_keys:
                continue
            scope_dir = os.path.join(root, name)
            marker_path = os.path.join(scope_dir, "scope.json")
            try:
                with open(marker_path, "r", encoding="utf-8") as f:
                    marker = json.load(f)
            except Exception:
                continue
            if not isinstance(marker, dict):
                continue
            marker_platform = str(marker.get("platform") or "")
            marker_site = (
                marker_platform,
                _normalize_scope_url(str(marker.get("url") or ""), marker_platform),
            )
            if marker_site != current_site:
                continue
            marker_provider = str(marker.get("erp_provider") or "").strip().lower()
            marker_family = str(marker.get("erp_family") or "")
            marker_db = str(marker.get("database") or "")
            same_db = bool(current_db) and marker_db == current_db
            if marker_provider:
                if marker_provider == current_erp and (same_db or not current_db):
                    continue
            elif marker_family == current_family and (same_db or not current_db):
                continue
            for filename in ("product_woo_map.json", "sepidar_product_map.json"):
                try:
                    with open(os.path.join(scope_dir, filename), "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                for value in data.values():
                    try:
                        owned.add(int(value))
                    except (TypeError, ValueError):
                        continue
    except Exception:
        owned = set()

    _other_db_product_ids = (current_key, owned)
    return owned


def reconfigure_app_logging():
    """بعد از تعویض پروفایل، مسیر sync.log به‌روز شود."""
    global LOG_FILE
    LOG_FILE = app_path("sync.log")
    logger = logging.getLogger("SyncApp")
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    for handler in list(logger.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass

BASE_DIR = get_base_path()
LOG_FILE = app_path("sync.log")


class SafeConsoleHandler(logging.StreamHandler):
    """ کنسول ویندوز encoding بد """

    def __init__(self, stream=None):
        stream = stream or sys.stderr or sys.stdout
        if stream is None:
            stream = io.StringIO()
        elif hasattr(stream, "buffer") and not isinstance(stream, io.TextIOBase):
            stream = io.TextIOWrapper(stream.buffer, encoding=getattr(stream, "encoding", None) or "utf-8", errors="replace")
        self._fallback_encoding = getattr(stream, "encoding", None) or "utf-8"
        super().__init__(stream)

    def emit(self, record):
        try:
            message = self.format(record)
            stream = self.stream
            try:
                stream.write(message + self.terminator)
            except UnicodeEncodeError:
                # encoding نداشت replace بزن
                safe_message = message.encode(self._fallback_encoding, errors="replace").decode(self._fallback_encoding, errors="replace")
                stream.write(safe_message + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

def setup_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    # duplicate log نشه
    logger.propagate = False

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass

    console_handler = SafeConsoleHandler()
    console_handler.setFormatter(formatter)
    exe = os.path.basename(sys.executable or "").lower()
    if "pythonw" not in exe and sys.stderr is not None:
        logger.addHandler(console_handler)

    return logger

log = setup_logger("SyncApp")


def clear_filtered_logs(tokens: Iterable[str]) -> int:
    """ خطوط sync.log که token دارن پاک می‌شن """
    token_list = [str(t).strip().lower() for t in (tokens or []) if str(t).strip()]
    log_path = app_path("sync.log")
    if not token_list or not os.path.exists(log_path):
        return 0

    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    kept = []
    removed = 0
    for line in lines:
        low = line.lower()
        if any(tok in low for tok in token_list):
            removed += 1
            continue
        kept.append(line)

    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(kept)

    return removed

def check_sql_connection(config=None, update_config_status=True):
    """ (ok, message) """
    if config is None:
        from secure_config_loader import load_secure_config
        config = load_secure_config(log)

    from sync_app.core.sql_connection_helper import open_sql_connection, format_db_error

    server = (config.get("SQL_SERVER") or "").strip()
    database = (config.get("SQL_DATABASE") or "").strip()
    if not server or not database:
        return (False, "تنظیمات SQL ناقص است (Server یا Database خالی است).")

    try:
        conn, auth_mode, _ = open_sql_connection(config, timeout=8)
        conn.close()
        return (True, f"اتصال برقرار شد ({auth_mode})")
    except Exception as e:
        return (False, format_db_error(e)[:300])

def check_woocommerce_connection(config=None, update_config_status=True):
    """ (ok, message, currency) """
    if config is None:
        from secure_config_loader import load_secure_config
        config = load_secure_config(log)

    WC_URL = config.get("WC_URL")
    WC_CONSUMER_KEY = config.get("WC_CONSUMER_KEY")
    WC_CONSUMER_SECRET = config.get("WC_CONSUMER_SECRET")
    WC_TIMEOUT = config.get("WC_TIMEOUT", 120)

    currency_code = "N/A"

    if not all([WC_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET]):
        return (False, "تنظیمات API ووکامرس کامل نیستند.", currency_code)

    try:
        from woocommerce import API

        wcapi = API(
            url=WC_URL,
            consumer_key=WC_CONSUMER_KEY,
            consumer_secret=WC_CONSUMER_SECRET,
            version="wc/v3",
            timeout=WC_TIMEOUT
        )

        status_response = wcapi.get("system_status").json()
        if not isinstance(status_response, dict) or 'database' not in status_response:
            error_message = status_response.get('message', 'خطای احراز هویت یا دسترسی. کلیدها را بررسی کنید.')
            return (False, error_message, currency_code)

        settings_response = wcapi.get("settings/general").json()
        for item in settings_response:
            if item.get("id") == "woocommerce_currency":
                currency_code = item.get("value", "N/A").upper()
                break

        return (True, f"اتصال موفق. سایت: {status_response.get('site_url')}", currency_code)

    except requests.exceptions.Timeout:
        return (False, "زمان اتصال به ووکامرس به پایان رسید (Timeout).", currency_code)
    except requests.exceptions.RequestException as req_err:
        return (False, f"خطای شبکه/پروتکل: {req_err}", currency_code)
    except Exception as e:
        return (False, f"خطای کلی اتصال ووکامرس: {e}", currency_code)
