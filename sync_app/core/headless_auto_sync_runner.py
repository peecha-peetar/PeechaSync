"""اجرایِ همگام‌سازیِ خودکار برایِ یک (یا همه‌ی) پروفایل‌ها، بدونِ رابطِ
گرافیکی — برایِ کسانی که چند فروشگاه/پروفایل (با دیتابیس و سایتِ متفاوت)
دارن و می‌خوان همگام‌سازیِ خودکارِ هرکدوم کاملاً مستقل از بقیه و بدونِ نیاز
به بازنگه‌داشتنِ برنامه یا لاگین‌بودن با اون پروفایلِ خاص انجام بشه.

هر پروفایل تنظیماتِ خودش (AUTO_ENABLED/AUTO_INTERVAL/AUTO_<job>/
AUTO_NEXT_RUN_AT) رو در secure_config.bin خودش داره — دقیقاً همونی که از
تبِ «همگام‌سازیِ خودکار» ذخیره می‌شه. این اسکریپت فقط از بیرونِ برنامه،
به‌جایِ QTimerِ داخلِ اون تب، همون منطق رو اجرا می‌کنه.

اجرا (از طریقِ زمان‌بندِ ویندوز/Task Scheduler، یا دستی برایِ تست):
    python -m sync_app.core.headless_auto_sync_runner --profile <profile_id>
    python -m sync_app.core.headless_auto_sync_runner --all-profiles

هر اجرا فقط اگه طبقِ تنظیماتِ همون پروفایل موعدش رسیده باشه، کارهایِ
تیک‌خورده رو واقعاً اجرا می‌کنه؛ وگرنه بی‌صدا (با یه خطِ لاگ) رد می‌شه —
یعنی کافیه Task Scheduler هر چند دقیقه یک‌بار صداش بزنه (مثلاً هر ۱۵
دقیقه)، خودِ اسکریپت تشخیص می‌ده کِی واقعاً وقتِ اجراست.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta


def _log(msg: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def _lock_path(profile_id: str) -> str:
    from sync_app.core.user_profile import ensure_profile_dir

    return os.path.join(ensure_profile_dir(profile_id), "auto_sync_headless.lock")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_lock(profile_id: str) -> bool:
    """اگه دورِ قبلیِ همینِ پروفایل هنوز در حالِ اجراست، False برمی‌گردونه
    (رد شدنِ این اجرا، نه کشتنِ دورِ قبلی — کارهایِ نیمه‌تموم نباید قطع بشن)."""
    path = _lock_path(profile_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                old_pid = int((f.read() or "0").strip())
        except (OSError, ValueError):
            old_pid = 0
        if old_pid and _pid_alive(old_pid):
            return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True


def _release_lock(profile_id: str) -> None:
    try:
        os.remove(_lock_path(profile_id))
    except OSError:
        pass


def _is_due(cfg: dict) -> bool:
    if not cfg.get("AUTO_ENABLED"):
        return False
    next_at_raw = str(cfg.get("AUTO_NEXT_RUN_AT") or "").strip()
    if not next_at_raw:
        return True
    try:
        next_at = datetime.fromisoformat(next_at_raw)
    except Exception:
        return True
    return datetime.now() >= next_at


def _interval_ms(cfg: dict) -> int:
    from sync_app.core.tabs.tab_auto_sync import AUTO_INTERVAL_MS, _normalize_auto_interval

    interval_text = _normalize_auto_interval(str(cfg.get("AUTO_INTERVAL") or "4 ساعت"))
    return AUTO_INTERVAL_MS.get(interval_text, AUTO_INTERVAL_MS["4 ساعت"])


def _selected_job_keys(cfg: dict) -> list[str]:
    from sync_app.core.tabs.tab_auto_sync import AUTO_SYNC_JOB_BY_KEY

    return [key for key in AUTO_SYNC_JOB_BY_KEY if cfg.get(f"AUTO_{key}")]


def run_profile_auto_sync(profile_id: str) -> int:
    """یک دورِ همگام‌سازیِ خودکار برایِ این پروفایل، فقط اگه موعدش رسیده
    باشه. برمی‌گردونه: 0 = موفق یا به‌درستی رد شده، 1 = حداقل یک ماژول خطا داد."""
    from sync_app.core.user_profile import activate_profile, load_secure_config_after_profile
    from sync_app.core.secure_config_loader import save_secure_config

    activate_profile(profile_id)
    cfg = load_secure_config_after_profile(log=None) or {}

    if not cfg or len(cfg) < 5:
        _log(f"[{profile_id}] تنظیماتِ این پروفایل پیدا/خونده نشد — رد شد.")
        return 1

    if not _is_due(cfg):
        _log(f"[{profile_id}] موعدِ اجرا نرسیده — رد شد.")
        return 0

    selected = _selected_job_keys(cfg)
    if not selected:
        _log(f"[{profile_id}] هیچ ماژولی برایِ همگام‌سازیِ خودکار تیک نخورده — رد شد.")
        return 0

    if not _acquire_lock(profile_id):
        _log(f"[{profile_id}] یک دورِ قبلی هنوز در حالِ اجراست — این اجرا رد شد.")
        return 0

    try:
        cfg["AUTO_NEXT_RUN_AT"] = (datetime.now() + timedelta(milliseconds=_interval_ms(cfg))).isoformat()
        save_secure_config(cfg)

        from sync_app.core.auto_sync_preflight import preflight_batch_silent

        runnable = preflight_batch_silent(cfg, selected)
        if not runnable:
            _log(f"[{profile_id}] پیش‌نیازها (اتصال/نگاشت/راه‌اندازیِ فروشگاه) برقرار نبود — رد شد.")
            return 0

        from sync_app.core.auto_sync_scope import run_job_with_scope
        from sync_app.core.tabs.tab_auto_sync import AUTO_SYNC_JOB_BY_KEY
        from sync_app.core.event_notifier import append_system_log

        ok_count = 0
        fail_count = 0
        append_system_log(
            "auto_sync",
            f"[{profile_id}] شروعِ دورِ همگام‌سازیِ خودکارِ بدونِ رابط ({len(runnable)} ماژول)",
        )
        for key in runnable:
            job = AUTO_SYNC_JOB_BY_KEY.get(key)
            if job is None:
                continue
            _log(f"[{profile_id}] در حال اجرا: {job.title}")
            try:
                run_job_with_scope(key, job.runner)
                ok_count += 1
            except Exception as exc:
                fail_count += 1
                _log(f"[{profile_id}] خطا در {job.title}: {exc}")

        append_system_log(
            "auto_sync",
            f"[{profile_id}] پایانِ دور: {ok_count} موفق، {fail_count} ناموفق",
            level="WARNING" if fail_count else "INFO",
        )
        _log(f"[{profile_id}] پایان — {ok_count} موفق، {fail_count} ناموفق")
        return 0 if fail_count == 0 else 1
    finally:
        _release_lock(profile_id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="اجرایِ بدونِ رابطِ همگام‌سازیِ خودکار برایِ یک یا همه‌ی پروفایل‌ها"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile", help="شناسه‌ی پروفایل (همون نامِ پوشه در profiles/)")
    group.add_argument(
        "--all-profiles", action="store_true", help="اجرا برایِ همه‌ی پروفایل‌هایِ موجود، یکی‌یکی"
    )
    args = parser.parse_args(argv)

    from sync_app.core.user_profile import list_profile_ids

    profile_ids = list_profile_ids() if args.all_profiles else [args.profile]
    if not profile_ids:
        _log("هیچ پروفایلی پیدا نشد.")
        return 1

    worst = 0
    for pid in profile_ids:
        try:
            rc = run_profile_auto_sync(pid)
        except Exception as exc:
            _log(f"[{pid}] خطایِ غیرمنتظره: {exc}")
            rc = 1
        worst = max(worst, rc)
    return worst


if __name__ == "__main__":
    sys.exit(main())
