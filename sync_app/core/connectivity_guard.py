"""چک اتصال sql/woo قبل sync."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from sync_app.core.secure_config_loader import load_secure_config


def find_peecha_launcher(widget):
    w = widget
    while w is not None:
        if w.__class__.__name__ == "PeechaLauncher":
            return w
        w = w.parent()

    app = QApplication.instance()
    if app is None:
        return None
    for top in app.topLevelWidgets():
        if top.__class__.__name__ == "PeechaLauncher":
            return top
    return None


def _apply_probe_to_launcher(launcher, result: dict) -> None:
    if launcher is None or not isinstance(result, dict):
        return
    apply_fn = getattr(launcher, "apply_connectivity_probe", None)
    if callable(apply_fn):
        apply_fn(
            bool(result.get("sql_ok")),
            str(result.get("sql_msg") or ""),
            bool(result.get("wc_ok")),
            str(result.get("wc_msg") or ""),
        )


def _wc_target_name(config) -> str:
    from sync_app.core.wc_sync_helper import wc_store_label

    return wc_store_label(config)


def _offline_message(name: str, category: str, detail: str) -> str:
    from sync_app.core.connectivity_service import network_error_user_hint

    hint = network_error_user_hint(category, target=name)
    detail_line = (detail or "").strip()
    if detail_line and detail_line not in hint:
        return f"{hint}\n\nجزئیات: {detail_line[:220]}"
    return hint


def ensure_connectivity(parent, *, need_sql=True, need_wc=False, live=False, wait=False) -> bool:
    """
    قبل از sync:
    - live=False: badge هدر (سریع — مناسب سیم‌کارت کند)
    - live=True: پروب واقعی + اجازه ادامه روی timeout اگر badge سبز است
    - wait=True: به‌جای خطا، دیالوگ انتظار تا آنلاین شدن (با دکمه توقف)
    """
    if live and (need_sql or need_wc):
        return _ensure_connectivity_live(parent, need_sql=need_sql, need_wc=need_wc)
    return _ensure_connectivity_from_badges(
        parent, need_sql=need_sql, need_wc=need_wc, wait=wait,
    )


def _ensure_connectivity_from_badges(parent, *, need_sql=True, need_wc=False, wait=False) -> bool:
    from sync_app.core.connectivity_wait import connectivity_ready, wait_for_connectivity_dialog

    launcher = find_peecha_launcher(parent)
    if launcher is None:
        return True

    if connectivity_ready(launcher, need_sql=need_sql, need_wc=need_wc):
        return True

    if wait:
        return wait_for_connectivity_dialog(parent, need_sql=need_sql, need_wc=need_wc)

    pending = []
    offline = []

    if need_sql:
        state = launcher.sql_connectivity_state()
        if state == "pending":
            pending.append("SQL")
        elif state == "offline":
            offline.append("SQL")

    if need_wc:
        state = launcher.wc_connectivity_state()
        if state == "pending":
            pending.append("WooCommerce")
        elif state == "offline":
            offline.append("WooCommerce")

    if pending:
        QMessageBox.information(
            parent,
            "در حال بررسی اتصال",
            f"وضعیت {' و '.join(pending)} هنوز مشخص نشده.\n"
            "چند ثانیه صبر کنید تا دکمه‌های بالای صفحه سبز شوند.",
        )
        return False

    if offline:
        names = " و ".join(offline)
        QMessageBox.warning(
            parent,
            "اتصال برقرار نیست",
            f"دکمه {names} در هدر برنامه آفلاین است (قرمز).\n\n"
            "ابتدا اتصال را برقرار کنید، سپس دوباره تلاش کنید.\n"
            "برای تنظیمات روی همان دکمه در بالای صفحه کلیک کنید.",
        )
        return False

    return True


def _ensure_connectivity_live(parent, *, need_sql=True, need_wc=False) -> bool:
    from sync_app.core.connectivity_service import probe_all_robust, classify_network_error

    launcher = find_peecha_launcher(parent)
    config = load_secure_config(None) or {}

    # اگر badge سبز است — پروب سبک؛ sync خودش retry می‌کند
    badge_wc_online = (
        launcher is not None
        and need_wc
        and launcher.wc_connectivity_state() == "online"
    )
    wc_attempts = 2 if badge_wc_online else 3

    app = QApplication.instance()
    try:
        if app is not None:
            app.setOverrideCursor(Qt.WaitCursor)
        result = probe_all_robust(
            config,
            wc_attempts=wc_attempts if need_wc else 1,
            sql_attempts=2 if need_sql else 1,
            pause_sec=1.0,
        )
    finally:
        if app is not None:
            app.restoreOverrideCursor()

    _apply_probe_to_launcher(launcher, result)

    if need_sql and not result.get("sql_ok"):
        QMessageBox.warning(
            parent,
            "SQL در دسترس نیست",
            _offline_message("SQL Server", result.get("sql_category", "unknown"), result.get("sql_msg", "")),
        )
        return False

    if need_wc and not result.get("wc_ok"):
        wc_cat = str(result.get("wc_category") or classify_network_error(result.get("wc_msg", "")))
        wc_name = _wc_target_name(config)

        if wc_cat == "timeout" and badge_wc_online:
            answer = QMessageBox.question(
                parent,
                "اتصال کند",
                f"شبکه به {wc_name} کند است (timeout در تست).\n\n"
                "برنامه خودش چند بار retry می‌کند.\n"
                "همگام‌سازی را شروع کنیم؟",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            return answer == QMessageBox.Yes

        if wc_cat in ("dns", "vpn_tunnel", "forbidden"):
            title = "VPN/تونل ناقص" if wc_cat == "vpn_tunnel" else "ووکامرس در دسترس نیست"
            if wc_cat == "forbidden":
                title = "دسترسی API رد شد (403)"
            QMessageBox.warning(
                parent,
                title,
                _offline_message(wc_name, wc_cat, result.get("wc_msg", "")),
            )
            return False

        answer = QMessageBox.question(
            parent,
            "اتصال ناپایدار",
            f"{_offline_message(wc_name, wc_cat, result.get('wc_msg', ''))}\n\n"
            "با این حال همگام‌سازی را امتحان کنیم؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    return True
