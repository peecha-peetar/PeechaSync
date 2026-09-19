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


def _site_scope_key(*, include_family: bool = True) -> str:
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
    """مسیرِ فایلِ وضعیتِ سینکِ مخصوصِ سایت/پلتفرم/خانواده‌یِ ERPِ فعلی
    (namespaced) — برایِ category_map.json، product_woo_map.json و مشابه.

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
        except Exception:
            pass
    return target


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
