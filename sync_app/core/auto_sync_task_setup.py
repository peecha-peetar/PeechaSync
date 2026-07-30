"""اجرایِ خودکارِ setup-auto-sync-tasks.ps1 از داخلِ خودِ برنامه — تا کاربر
مجبور نباشه دستی فایل رو پیدا کنه و با پاورشل اجرا کنه. فقط یک لایه‌ی نازکِ
subprocess روی همون اسکریپت؛ منطقِ ساختِ تسک‌ها کاملاً همون‌جا (در
setup-auto-sync-tasks.ps1) می‌مونه."""

from __future__ import annotations

import os
import subprocess
import sys


def find_setup_script() -> str:
    here = os.path.dirname(os.path.abspath(__file__))  # sync_app/core
    root = os.path.dirname(os.path.dirname(here))  # ریشه‌ی نصب (کنارِ main.py)
    candidate = os.path.join(root, "setup-auto-sync-tasks.ps1")
    return candidate if os.path.isfile(candidate) else ""


def run_setup_script(interval_minutes: int = 15) -> tuple[bool, str]:
    """setup-auto-sync-tasks.ps1 رو اجرا می‌کنه و (موفقیت، خروجیِ متنی) رو برمی‌گردونه."""
    if sys.platform != "win32":
        return False, "این قابلیت (زمان‌بندِ ویندوز) فقط روی ویندوز کار می‌کند."

    script_path = find_setup_script()
    if not script_path:
        return False, "فایلِ setup-auto-sync-tasks.ps1 کنارِ برنامه پیدا نشد."

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script_path,
                "-IntervalMinutes",
                str(int(interval_minutes)),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return False, "powershell.exe پیدا نشد."
    except subprocess.TimeoutExpired:
        return False, "اجرایِ اسکریپت بیش از حد طول کشید (timeout)."
    except Exception as exc:
        return False, f"خطا در اجرایِ اسکریپت: {exc}"

    output = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    combined = output + (("\n" + err) if err else "")
    return result.returncode == 0, combined.strip()
