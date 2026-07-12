"""قبل از sync سفارش، cart/checkout باید آماده باشه."""

from PyQt5.QtWidgets import QMessageBox

from sync_app.core.connectivity_guard import find_peecha_launcher
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.scripts.woocommerce_store_setup import (
    store_pages_ready,
    store_setup_user_message,
)


def open_store_setup(parent):
    launcher = find_peecha_launcher(parent)
    if launcher is None:
        return
    if hasattr(launcher, "open_store_setup"):
        launcher.open_store_setup()
    elif hasattr(launcher, "_open_settings_section"):
        launcher._open_settings_section("woo")


def ensure_store_pages_ready(parent, config=None, *, silent=False) -> bool:
    """
    اگر Cart/Checkout در cache تنظیم نشده باشد، پیام راهنما نشان می‌دهد.
    silent=True برای همگام‌سازی خودکار — بدون popup.
    """
    cfg = config or load_secure_config(None) or {}
    if store_pages_ready(cfg):
        return True

    if silent:
        return False

    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Warning)
    msg.setWindowTitle("راه‌اندازی فروشگاه لازم است")
    msg.setText(store_setup_user_message())
    go_btn = msg.addButton("رفتن به تنظیمات", QMessageBox.AcceptRole)
    msg.addButton("بستن", QMessageBox.RejectRole)
    msg.exec_()
    if msg.clickedButton() == go_btn:
        open_store_setup(parent)
    return False
