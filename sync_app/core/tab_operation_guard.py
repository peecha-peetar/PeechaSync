"""قفل تعویض تب هنگام عملیات جاری در یک تب."""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox


def find_peecha_launcher(widget):
    from sync_app.core.connectivity_guard import find_peecha_launcher as _find

    return _find(widget)


def lock_tab_navigation(widget, *, message: str = "") -> None:
    launcher = find_peecha_launcher(widget)
    if launcher is None:
        return
    lock_fn = getattr(launcher, "lock_tab_navigation", None)
    if callable(lock_fn):
        lock_fn(source_widget=widget, message=message)


def unlock_tab_navigation(widget) -> None:
    launcher = find_peecha_launcher(widget)
    if launcher is None:
        return
    unlock_fn = getattr(launcher, "unlock_tab_navigation", None)
    if callable(unlock_fn):
        unlock_fn(source_widget=widget)


def tab_navigation_locked(widget) -> bool:
    launcher = find_peecha_launcher(widget)
    if launcher is None:
        return False
    return bool(getattr(launcher, "is_tab_navigation_locked", lambda: False)())


def is_tab_active(tab) -> bool:
    """
    آیا این تب الان واقعاً روی صفحه دیده می‌شه؟ چون بعضی تب‌ها (محصولات،
    دسته‌بندی‌ها و...) الان داخل یک تب گروهی (مثل «همگام‌سازی») تودرتو شدن،
    این تابع از QTabWidget اصلی برنامه شروع می‌کنه و با دنبال‌کردن
    currentWidget() پایین می‌ره — تا هر عمق تودرتویی که تب‌های گروهی
    (که هرکدوم یک self.sub_tabs از نوع QTabWidget دارن) داشته باشن.

    نکته: عمداً از بالا به پایین طراحی شده، نه با گشتن روی widget.parent()
    از پایین به بالا — چون QTabWidget داخلش یک QStackedWidget واسط داره
    و parent() واقعیِ هر زیرتب، خودِ QTabWidget نیست؛ گشتن از بالا با
    attribute قراردادیِ «sub_tabs» این مشکل رو کلاً نداره.
    """
    launcher = find_peecha_launcher(tab)
    if launcher is None or tab is None:
        return False

    from PyQt5.QtWidgets import QTabWidget

    def _search(widget) -> bool:
        if widget is tab:
            return True
        sub_tabs = getattr(widget, "sub_tabs", None)
        if isinstance(sub_tabs, QTabWidget):
            return _search(sub_tabs.currentWidget())
        return False

    return _search(launcher.tabs.currentWidget())


def mark_sql_reload_pending(tab) -> None:
    if tab is not None:
        tab._pending_sql_reload = True


def run_sql_reload_if_active(tab, load_fn) -> None:
    if tab is None:
        return
    if is_tab_active(tab):
        load_fn()
    else:
        mark_sql_reload_pending(tab)


def consume_pending_sql_reload(tab, load_fn) -> None:
    if tab is None:
        return
    if getattr(tab, "_pending_sql_reload", False):
        tab._pending_sql_reload = False
        load_fn()


def warn_tab_switch_blocked(parent) -> None:
  QMessageBox.information(
    parent,
    "عملیات در جریان",
    "تا پایان همگام‌سازی یا زدن «توقف»، امکان تعویض تب وجود ندارد.",
  )
