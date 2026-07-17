"""راه‌اندازیِ مجددِ برنامه — برای اعمالِ تعویضِ پروفایل بدون آپدیت/زیپ."""

from __future__ import annotations

import os
import subprocess
import sys


def restart_application() -> None:
    """یک نمونه‌ی تازه از برنامه اجرا می‌کند و پردازشِ فعلی را می‌بندد."""
    try:
        if getattr(sys, "frozen", False):
            install_root = os.path.dirname(sys.executable)
            launch_bat = os.path.join(install_root, "Run-PeechaSync.bat")
            if os.path.isfile(launch_bat):
                subprocess.Popen(
                    ["cmd", "/c", "start", "", launch_bat],
                    cwd=install_root,
                    close_fds=True,
                )
            else:
                subprocess.Popen([sys.executable], cwd=install_root, close_fds=True)
        else:
            repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            main_py = os.path.join(repo_root, "main.py")
            if not os.path.isfile(main_py):
                main_py = os.path.join(os.getcwd(), "main.py")
            subprocess.Popen([sys.executable, main_py], cwd=repo_root, close_fds=True)
    finally:
        os._exit(0)
