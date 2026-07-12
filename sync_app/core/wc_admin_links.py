"""لینک مستقیم به صفحات مدیریت ووکامرس — آدرس از WC_URL تنظیمات."""

from __future__ import annotations

from PyQt5.QtWidgets import QPushButton

from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.wc_api_helper import normalize_wc_store_url

# section -> (عنوان فارسی، مسیر نسبی wp-admin)
WC_ADMIN_SECTIONS: dict[str, tuple[str, str]] = {
    "categories": (
        "دسته‌بندی‌ها",
        "wp-admin/edit-tags.php?taxonomy=product_cat&post_type=product",
    ),
    "products": ("محصولات", "wp-admin/edit.php?post_type=product"),
    "attributes": (
        "ویژگی‌ها",
        "wp-admin/edit.php?post_type=product&page=product_attributes",
    ),
    "variations": ("محصولات", "wp-admin/edit.php?post_type=product"),
    "orders": ("سفارشات", "wp-admin/admin.php?page=wc-orders"),
    "customers": ("مشتریان", "wp-admin/admin.php?page=wc-admin&path=/customers"),
}


def wc_wp_admin_url(config: dict | None, section: str) -> str:
    label_path = WC_ADMIN_SECTIONS.get(section)
    if not label_path:
        return ""
    _, admin_path = label_path
    base = normalize_wc_store_url((config or {}).get("WC_URL", ""))
    if not base:
        return ""
    return f"{base}/{admin_path.lstrip('/')}"


def open_wc_admin_section(parent, section: str, config: dict | None = None) -> bool:
    from sync_app.core.wc_sync_helper import open_external_url

    cfg = config or load_secure_config(None) or {}
    url = wc_wp_admin_url(cfg, section)
    label, _ = WC_ADMIN_SECTIONS.get(section, ("", ""))
    empty_msg = (
        f"ابتدا آدرس فروشگاه (WC URL) را در تب تنظیمات وارد کنید.\n"
        f"سپس دوباره «{label} در سایت» را بزنید."
    )
    return open_external_url(parent, url, empty_message=empty_msg)


def make_wc_admin_open_button(parent, section: str, *, button_factory=None) -> QPushButton:
    label, _ = WC_ADMIN_SECTIONS.get(section, ("صفحه سایت", ""))
    factory = button_factory or QPushButton
    btn = factory(f"🌐 {label} در سایت")
    btn.setToolTip(
        f"باز کردن صفحه «{label}» در پنل ووکامرس فروشگاهی که در تنظیمات ثبت شده است."
    )
    if button_factory is None:
        btn.setMinimumHeight(42)
    btn.clicked.connect(lambda _checked=False, s=section: open_wc_admin_section(parent, s))
    return btn
