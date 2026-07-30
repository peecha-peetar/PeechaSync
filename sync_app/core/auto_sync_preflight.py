"""پیش‌نیازهای اجرا پیش از هر دورِ همگام‌سازیِ خودکار، به‌صورتِ کاملاً
بی‌صدا (بدونِ QMessageBox/رابطِ گرافیکی) — هم از تبِ «همگام‌سازیِ خودکار»ی
که داخلِ برنامه (با QTimer) اجرا می‌شه قابلِ استفاده‌ست، هم از اجرایِ
بدونِ رابط (headless_auto_sync_runner.py) که مستقل از بازبودنِ برنامه،
از طریقِ زمان‌بندِ ویندوز صدا زده می‌شه — تا رفتارِ هر دو یکی باشه."""

from __future__ import annotations

RECON_AWARE_KEYS = frozenset({"sync_fullproduct", "update_variations"})


def resolve_runnable_scripts_silent(selected: list[str]) -> list[str]:
    """اگه ماژول‌هایِ محصول/متغیر انتخاب شده‌ن ولی نگاشتِ محصول (product_woo_map)
    هنوز خالیه، اون دوتا رو بی‌صدا از لیست حذف می‌کنه (به‌جایِ پرسیدنِ تأییدیه)."""
    from sync_app.core.product_woo_map_helper import load_product_woo_map

    if not RECON_AWARE_KEYS.intersection(selected):
        return list(selected)
    if load_product_woo_map():
        return list(selected)
    return [key for key in selected if key not in RECON_AWARE_KEYS]


def check_connectivity_silent(config: dict, *, need_sql: bool = True, need_wc: bool = True) -> bool:
    from sync_app.core.connectivity_service import probe_all_robust

    result = probe_all_robust(
        config,
        wc_attempts=2 if need_wc else 1,
        sql_attempts=2 if need_sql else 1,
        pause_sec=1.0,
    )
    if need_sql and not result.get("sql_ok"):
        return False
    if need_wc and not result.get("wc_ok"):
        return False
    return True


def preflight_batch_silent(config: dict, selected: list[str]) -> list[str]:
    """معادلِ بی‌صدایِ AutoSyncTab._preflight_batch(interactive=False) — بدونِ
    هیچ popup‌ای. لیستِ نهاییِ ماژول‌هایِ واقعاً قابلِ اجرا رو برمی‌گردونه
    (ممکنه خالی باشه، یعنی این دور کلاً رد بشه)."""
    if not selected:
        return []
    if not check_connectivity_silent(config, need_sql=True, need_wc=True):
        return []
    runnable = resolve_runnable_scripts_silent(selected)
    if not runnable:
        return []
    if "ordersync" in runnable:
        from sync_app.core.store_setup_guard import ensure_store_pages_ready

        if not ensure_store_pages_ready(None, config=config, silent=True):
            runnable = [key for key in runnable if key != "ordersync"]
    return runnable
