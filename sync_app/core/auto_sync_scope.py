"""
کنترل محدوده‌ی «همگام‌سازی خودکار» برای هر نوع کار (محصولات/دسته‌بندی/متغیرها).
این ماژول هیچ خطی از منطق خودِ اسکریپت‌های سینک (sync_fullproduct.py و...)
را تغییر نمی‌دهد — فقط قبل از اجرای خودکار، چند کلید تنظیمات (که خودِ آن
اسکریپت‌ها از قبل می‌خوانند: SELECTED_SUB_GROUPS و DISABLED_PRODUCT_SKUS)
را موقتاً بازتعریف می‌کند، و بعد از اجرا دقیقاً همان مقدار اصلی را برمی‌گرداند.
"""

from __future__ import annotations

from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.product_woo_map_helper import load_product_woo_map
from sync_app.core.category_resolver import load_category_map

SCOPE_KEY_PREFIX = "AUTO_SCOPE_"

# فقط برای کارهایی که واقعاً از SELECTED_SUB_GROUPS/DISABLED_PRODUCT_SKUS
# استفاده می‌کنند (طبق بررسی خودِ کد هرکدوم) — Poshakproperties و ordersync
# اصلاً چنین مفهومی ندارند، برای همین اینجا نیستند.
SCOPE_CAPABLE_JOBS = {"sync_fullproduct", "ProductCategoriesSync", "update_variations"}

SCOPE_LABELS = {
    "matched": "فقط مواردی که از قبل به ووکامرس لینک‌اند",
    "selected_groups": "فقط زیرگروه‌های دسته‌بندی انتخابی (تب دسته‌بندی‌ها)",
    "all_checked": "همه‌ی تیک‌خورده‌ها (بدون محدودیت گروه)",
    "all": "همه — حتی موارد تیک‌نخورده",
}
SCOPE_ORDER = ["selected_groups", "matched", "all_checked", "all"]

# «all_checked» فقط برای محصولات و متغیرها معنا دارد (طبق درخواست) — چون
# برای دسته‌بندی‌ها، حالت «selected_groups» خودش همان چیزیه که تیک خورده،
# بحث «بدون محدودیت گروه» برای خودِ گروه‌ها بی‌معناست.
SCOPE_ALL_CHECKED_JOBS = {"sync_fullproduct", "update_variations"}


def get_job_scope(job_key: str, config: dict | None = None) -> str:
    # متغیرها تنظیم جدای خودشون رو ندارن — همیشه دقیقاً همون مقیاسی که
    # برای محصولات انتخاب شده رو ارث می‌برن (چون واریانت‌ها همیشه زیرمجموعه‌ی
    # همون محصولاتی هستن که سینک می‌شن، تنظیم جدا فقط گیج‌کننده بود).
    effective_key = "sync_fullproduct" if job_key == "update_variations" else job_key
    cfg = config if config is not None else (load_secure_config(None) or {})
    mode = str(cfg.get(f"{SCOPE_KEY_PREFIX}{effective_key}", "selected_groups")).strip()
    return mode if mode in SCOPE_ORDER else "selected_groups"


def set_job_scope(job_key: str, mode: str) -> None:
    if mode not in SCOPE_ORDER:
        return
    cfg = load_secure_config(None) or {}
    if not isinstance(cfg, dict) or len(cfg) < 5:
        return  # تنظیمات مشکوک به خالی/ناقص — دست‌کاریش نکن، امن‌تره
    cfg[f"{SCOPE_KEY_PREFIX}{job_key}"] = mode
    save_secure_config(cfg)


def _all_article_codes(config: dict) -> list[str]:
    """همه‌ی کدهای موجود در ERP (بدون فیلتر گروه) — فقط برای محاسبه‌ی حالت «matched»."""
    from sync_app.core.sql_connection_helper import open_sql_connection

    conn, _, _ = open_sql_connection(config, timeout=8)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT A_Code FROM Article")
        return [str(r[0]).strip() for r in cursor.fetchall() if str(r[0] or "").strip()]
    finally:
        conn.close()


def compute_temp_overrides(job_key: str, mode: str, config: dict) -> dict:
    """
    مقادیر موقتی که باید قبل از اجرای این job جایگزین بشن (کلید: مقدار جدید).
    اگر خالی برگردونه یعنی نیازی به تغییری نیست (رفتار پیش‌فرض همون selected_groups است).
    """
    if job_key not in SCOPE_CAPABLE_JOBS or mode == "selected_groups":
        return {}

    if mode == "all_checked":
        if job_key not in SCOPE_ALL_CHECKED_JOBS:
            return {}
        # فقط فیلتر گروه برداشته می‌شه — تیک‌های دستی کاربر (DISABLED_PRODUCT_SKUS)
        # دقیقاً همون‌طور که هست باقی می‌مونه، یعنی هرچی تیک‌خورده ارسال می‌شه.
        return {"SELECTED_SUB_GROUPS": [""]}

    if mode == "all":
        # همه — حتی مواردی که دستی تیک‌نخورده‌ان (هم فیلتر گروه هم فیلتر تیک برداشته می‌شه)
        return {"SELECTED_SUB_GROUPS": [""], "DISABLED_PRODUCT_SKUS": []}

    if mode == "matched":
        try:
            all_codes = set(_all_article_codes(config))
        except Exception:
            return {}  # اگه SQL در دسترس نبود، امن‌تره کاری نکنیم تا رفتار پیش‌فرض حفظ بشه

        if job_key == "ProductCategoriesSync":
            linked_codes = set(load_category_map().keys())
        else:
            linked_codes = set(load_product_woo_map().keys())

        unmatched = all_codes - linked_codes
        current_disabled = set(config.get("DISABLED_PRODUCT_SKUS", []) or [])
        return {
            "SELECTED_SUB_GROUPS": [""],
            "DISABLED_PRODUCT_SKUS": sorted(current_disabled | unmatched),
        }

    return {}


def _selected_group_codes(config: dict) -> list[str]:
    return [str(g).strip() for g in (config.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]


def _sub_group_codes(config: dict) -> set[str]:
    """کد کامل هر زیرگروه دسته‌بندی (M_Groupcode + S_Groupcode) — از جدول واقعی، نه Article."""
    from sync_app.core.sql_connection_helper import open_sql_connection

    conn, _, _ = open_sql_connection(config, timeout=8)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT M_Groupcode, S_Groupcode FROM S_Group")
        return {f"{str(m).strip()}{str(s).strip()}" for m, s in cursor.fetchall()}
    finally:
        conn.close()


def compute_unlinked_counts(config: dict) -> dict:
    """
    تعداد محصولات/دسته‌بندی‌هایی که هنوز به ووکامرس لینک نشده‌اند — فقط در
    محدوده‌ی زیرگروه‌های انتخابی کاربر. فقط خواندنی، هیچ نوشتنی انجام نمی‌شود.

    نکته‌ی صادقانه: «متغیرها» عمداً اینجا نیست — چون هیچ نگاشت محلی
    اختصاصیِ «این واریانت خاص به کدوم ID ووکامرس وصله» وجود نداره (فقط
    محصول و دسته‌بندی چنین نگاشتی دارن). قبلاً این رو با «وضعیت محصول
    والد» حدس می‌زدیم که در عمل گمراه‌کننده بود (کاربر واقعی گزارش داد
    که هیچ واریانت لینک‌نشده‌ای نداشت ولی هشدار غلط نشون می‌داد) — برای
    همین حذف شد؛ حدس‌زدن بدتر از نگفتنه.

    نکته‌ی مهم: اگه SQL در دسترس نبود، این تابع بی‌صدا {۰,۰} برنمی‌گردونه
    (چون اون حالت با «واقعاً همه لینکه» قابل تشخیص نبود) — خطای واقعی رو بالا
    می‌ده تا صدا زننده (_refresh_link_warning) بتونه لاگش کنه و badge رو مخفی
    کنه، نه اینکه با یه «۰ مورد» گمراه‌کننده نشونش بده.
    """
    result = {"products": 0, "categories": 0}
    groups = _selected_group_codes(config)
    if not groups:
        return result

    all_codes = set(_all_article_codes(config))  # اگه SQL خطا بده، همینجا بالا میره

    in_scope_articles = {c for c in all_codes if any(c.startswith(g) for g in groups)}
    product_map = load_product_woo_map()
    result["products"] = len(in_scope_articles - set(product_map.keys()))

    sub_codes = _sub_group_codes(config)  # این هم اگه خطا بده، بالا میره
    in_scope_categories = {c for c in sub_codes if any(c.startswith(g) for g in groups)}
    category_map = load_category_map()
    result["categories"] = len(in_scope_categories - set(category_map.keys()))
    return result



def _is_config_healthy(cfg: dict) -> bool:
    """
    چک سلامت پایه‌ی تنظیمات قبل از هر ذخیره‌ی خودکار — یه فایل تنظیمات
    واقعی همیشه ده‌ها کلید داره (SQL، ووکامرس، تم، و...). اگه به هر دلیلی
    (رقابت فایل، خطای لحظه‌ای خواندن) این عدد خیلی کم بود، یعنی به‌جای
    تنظیمات واقعی، یه دیکشنری خالی/ناقص لود شده و نباید هرگز ذخیره بشه —
    وگرنه دقیقاً همون چیزی که تنظیمات واقعی رو پاک می‌کنه اتفاق می‌افته.
    """
    return isinstance(cfg, dict) and len(cfg) >= 5


def _safe_save_config(cfg: dict, *, context: str) -> bool:
    """جایگزین امن save_secure_config — اگه cfg مشکوک به خالی/ناقص بودن باشه، ذخیره نمی‌کنه و لاگ می‌کنه."""
    if not _is_config_healthy(cfg):
        try:
            from sync_app.core.sync_utils import log
            log.error(
                f"❌ جلوگیری از ذخیره‌ی تنظیمات مشکوک (فقط {len(cfg) if isinstance(cfg, dict) else 0} "
                f"کلید) در «{context}» — برای جلوگیری از پاک شدن تنظیمات واقعی، ذخیره لغو شد."
            )
        except Exception:
            pass
        return False
    save_secure_config(cfg)
    return True


def run_job_with_scope(job_key: str, runner) -> None:
    """
    runner (job.runner) را با محدوده‌ی انتخابی کاربر برای این job اجرا می‌کند —
    قبل از اجرا مقادیر لازم را موقتاً عوض می‌کند، بعد از اجرا (چه موفق چه
    ناموفق) دقیقاً مقدار اصلی را برمی‌گرداند تا تنظیمات دستی کاربر برای
    تب‌های دیگر (محصولات/دسته‌بندی‌ها/متغیرها) دست‌نخورده بماند.
    """
    config = load_secure_config(None) or {}
    if not _is_config_healthy(config):
        # اگه همین اول تنظیمات به‌درستی لود نشد، اصلاً وارد بازی override
        # نشو — فقط runner رو مستقیم صدا بزن (رفتار پیش‌فرض قبلی همین بود).
        runner()
        return

    mode = get_job_scope(job_key, config)
    overrides = compute_temp_overrides(job_key, mode, config)

    if not overrides:
        runner()
        return

    original_values = {key: config.get(key) for key in overrides}
    try:
        cfg = load_secure_config(None) or {}
        if not _is_config_healthy(cfg):
            runner()
            return
        cfg.update(overrides)
        _safe_save_config(cfg, context=f"run_job_with_scope[{job_key}] (تنظیم موقت)")
        runner()
    finally:
        cfg = load_secure_config(None) or {}
        if _is_config_healthy(cfg):
            for key, original in original_values.items():
                if original is None:
                    cfg.pop(key, None)
                else:
                    cfg[key] = original
            _safe_save_config(cfg, context=f"run_job_with_scope[{job_key}] (بازگردانی)")
        # اگه تنظیمات مشکوک بود، عمداً هیچ‌کاری نمی‌کنیم — نه بازگردانی، نه
        # ذخیره — چون دست‌کاری تنظیماتی که خودشون درست خونده نشدن، امن نیست.
