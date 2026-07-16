import os
import sys
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMessageBox


_MESSAGEBOX_LOGGING_INSTALLED = False


def _get_log_path():
    from sync_app.core.sync_utils import app_path
    return app_path("sync.log")


def append_system_log(topic, message, level="INFO"):
    """ لاگ سیستمی """
    log_path = _get_log_path()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} - {level} - SYSTEM - [{topic}] {message}\n"

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # خطای لاگ نباید برنامه رو بخوابونه
        pass


def install_messagebox_logging():
    """ QMessageBoxها توی sync.log """
    global _MESSAGEBOX_LOGGING_INSTALLED

    if _MESSAGEBOX_LOGGING_INSTALLED:
        return

    def _wrap(method_name, level):
        original = getattr(QMessageBox, method_name, None)
        if original is None or getattr(original, "_peecha_logged", False):
            return

        def wrapped(parent, title, text, *args, **kwargs):
            append_system_log("system", f"{title}: {text}", level=level)
            return original(parent, title, text, *args, **kwargs)

        wrapped._peecha_logged = True
        setattr(QMessageBox, method_name, wrapped)

    _wrap("critical", "ERROR")
    _wrap("warning", "WARNING")
    _wrap("information", "INFO")
    _MESSAGEBOX_LOGGING_INSTALLED = True


def show_desktop_notification(title, message, timeout_ms=4500):
    """ نوتیف از system tray """
    app = QApplication.instance()
    if app is None:
        return False

    try:
        for widget in app.topLevelWidgets():
            tray = getattr(widget, "tray_icon", None)
            if tray is not None and isinstance(tray, QSystemTrayIcon) and tray.isVisible():
                tray.showMessage(title, message, QSystemTrayIcon.Information, timeout_ms)
                return True
    except Exception:
        return False

    return False


def notify_and_log(topic, title, message, timeout_ms=4500):
    """ لاگ + نوتیف """
    append_system_log(topic, message, level="INFO")
    show_desktop_notification(title, message, timeout_ms=timeout_ms)
