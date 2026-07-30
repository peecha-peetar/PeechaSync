#!/usr/bin/env python3
"""ورود برنامه - python main.py"""

import os
import sys
import traceback
from datetime import datetime

# Embedded Python does not always put the install folder on sys.path when running main.pyc.
_INSTALL_ROOT = os.path.dirname(os.path.abspath(__file__))
if _INSTALL_ROOT and _INSTALL_ROOT not in sys.path:
    sys.path.insert(0, _INSTALL_ROOT)


def _boot_log(msg: str) -> None:
    try:
        base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "PeechaSync")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "startup-errors.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%a %m/%d/%Y %H:%M:%S.%f}] boot {msg}\n")
    except Exception:
        pass


def _bootstrap_win32_dll_paths():
    if sys.platform != "win32":
        return
    base = os.path.dirname(os.path.abspath(sys.executable))
    if hasattr(os, "add_dll_directory"):
        for rel in (
            "",
            os.path.join("Lib", "site-packages", "PyQt5", "Qt5", "bin"),
        ):
            path = base if not rel else os.path.join(base, rel)
            if os.path.isdir(path):
                try:
                    os.add_dll_directory(path)
                except OSError:
                    pass
    plugins = os.path.join(base, "Lib", "site-packages", "PyQt5", "Qt5", "plugins")
    if os.path.isdir(plugins):
        os.environ.setdefault("QT_PLUGIN_PATH", plugins)
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")


if __name__ == "__main__":
    # اجرایِ بدونِ رابطِ گرافیکی برایِ زمان‌بندِ ویندوز/Task Scheduler — مثلاً
    # PeechaSync.exe --profile shop-a . قبل از هر importِ PyQt5/ساختِ splash
    # چک می‌شه تا این مسیر اصلاً نیازی به display نداشته باشه (برایِ
    # چندین پروفایل/فروشگاهِ مستقل که هرکدوم زمان‌بندِ خودشون رو دارن).
    if "--profile" in sys.argv or "--all-profiles" in sys.argv:
        _boot_log("headless auto-sync mode")
        from sync_app.core.headless_auto_sync_runner import main as _headless_main

        raise SystemExit(_headless_main(sys.argv[1:]))

    _boot_log(f"main start exe={sys.executable}")
    _bootstrap_win32_dll_paths()
    try:
        import PyQt5  # noqa: F401

        _boot_log("PyQt5 import ok")
    except ImportError:
        _boot_log("PyQt5 missing")
        print("PyQt5 is not installed. Run: .\\run.bat")
        raise SystemExit(1)

    from sync_app.core.startup_splash import ensure_startup_splash

    app, _splash = ensure_startup_splash(sys.argv)
    _boot_log("early splash shown")

    try:
        from sync_app.core.peecha_launcher import main

        _boot_log("peecha_launcher import ok")
        main(existing_app=app)
        _boot_log("main() returned")
    except Exception as exc:
        _boot_log(f"FATAL {exc}")
        _boot_log(traceback.format_exc())
        raise
