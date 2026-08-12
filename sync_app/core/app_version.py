"""شماره نسخه."""

import os
import sys

_BUILTIN_VERSION = "2.30.100"


def _install_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    if os.path.isfile(os.path.join(root, "main.pyc")) or os.path.isfile(os.path.join(root, "main.py")):
        return root
    return root


def _load_version() -> str:
    ver_file = os.path.join(_install_root(), "VERSION.txt")
    if os.path.isfile(ver_file):
        try:
            with open(ver_file, encoding="utf-8") as f:
                v = (f.read() or "").strip()
            if v:
                return v
        except OSError:
            pass
    return _BUILTIN_VERSION


APP_VERSION = _load_version()


def app_version_label() -> str:
    return f"نسخه {APP_VERSION}"


def app_version_display() -> str:
    return APP_VERSION
