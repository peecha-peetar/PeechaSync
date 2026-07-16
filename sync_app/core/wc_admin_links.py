"""لینک مستقیم به صفحات مدیریت فروشگاه — ووکامرس (wp-admin عمیق) یا پرستاشاپ
(فقط صفحه‌ی اصلی سایت).

⚠️ پرستاشاپ برخلاف ووکامرس، پوشه‌ی پنل مدیریت (BackOffice) رو معمولاً برای
امنیت به یک اسم تصادفی/دلخواه تغییر می‌ده (مثلاً adminXXXXX/) که هیچ‌جای
تنظیمات (PS_URL/PS_API_KEY) ثبت نشده و از Webservice هم قابل استخراج نیست —
پس نمی‌شه مثل ووکامرس یک لینک عمیق به بخش مشخص ساخت؛ فقط صفحه‌ی اصلی فروشگاه
باز می‌شه.
"""

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
    from sync_app.core.integrations.commerce_provider import is_prestashop

    cfg = config or {}
    if is_prestashop(cfg):
        return str(cfg.get("PS_URL") or "").strip().rstrip("/")

    label_path = WC_ADMIN_SECTIONS.get(section)
    if not label_path:
        return ""
    _, admin_path = label_path
    base = normalize_wc_store_url(cfg.get("WC_URL", ""))
    if not base:
        return ""
    return f"{base}/{admin_path.lstrip('/')}"


def open_wc_admin_section(parent, section: str, config: dict | None = None) -> bool:
    from sync_app.core.integrations.commerce_provider import is_prestashop, store_platform_label
    from sync_app.core.wc_sync_helper import open_external_url

    cfg = config or load_secure_config(None) or {}
    url = wc_wp_admin_url(cfg, section)
    label, _ = WC_ADMIN_SECTIONS.get(section, ("", ""))
    platform_label = store_platform_label(cfg)
    empty_msg = (
        f"ابتدا آدرس فروشگاه ({platform_label}) را در تب تنظیمات وارد کنید.\n"
        f"سپس دوباره «{label} در سایت» را بزنید."
    )
    return open_external_url(parent, url, empty_message=empty_msg)


def make_wc_admin_open_button(parent, section: str, *, button_factory=None) -> QPushButton:
    from sync_app.core.integrations.commerce_provider import is_prestashop, store_platform_label

    label, _ = WC_ADMIN_SECTIONS.get(section, ("صفحه سایت", ""))
    factory = button_factory or QPushButton
    btn = factory(f"🌐 {label} در سایت")
    cfg = load_secure_config(None) or {}
    if is_prestashop(cfg):
        btn.setToolTip(
            "باز کردن صفحه‌ی اصلی فروشگاه پرستاشاپ — چون آدرس پنل مدیریت پرستاشاپ "
            "معمولاً تصادفی/امنیتی‌شده و در تنظیمات ثبت نمی‌شه، لینک مستقیم به بخش "
            f"«{label}» ممکن نیست."
        )
    else:
        btn.setToolTip(
            f"باز کردن صفحه «{label}» در پنل {store_platform_label(cfg)} فروشگاهی که در تنظیمات ثبت شده است."
        )
    if button_factory is None:
        btn.setMinimumHeight(42)
    btn.clicked.connect(lambda _checked=False, s=section: open_wc_admin_section(parent, s))
    return btn
