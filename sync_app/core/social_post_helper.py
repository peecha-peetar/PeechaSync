"""
ساخت پست شبکه‌های اجتماعی از روی الگوی کاربر و اطلاعات محصول.
فاز اول: فقط تلگرام — از طریق لینک اشتراک‌گذاری رسمی تلگرام
(t.me/share/url) که خودِ تلگرام کاربر را باز می‌کند و اجازه می‌دهد
گروه/کانال مقصد را از داخل اکانت خودش انتخاب کند. هیچ توکن یا API
جداگانه‌ای لازم نیست.
"""

from __future__ import annotations

from urllib.parse import quote

TELEGRAM_TEMPLATE_CONFIG_KEY = "SOCIAL_TELEGRAM_TEMPLATE"

DEFAULT_TELEGRAM_TEMPLATE = (
    "🔥 {نام}\n"
    "قیمت: {قیمت} تومان\n"
    "{توضیحات}"
)

# نگاشت جای‌خالی الگو -> کلید داخلی داده‌ی محصول
PLACEHOLDER_KEYS = {
    "{نام}": "name",
    "{قیمت}": "price",
    "{قیمت_ویژه}": "sale_price",
    "{موجودی}": "stock",
    "{کد}": "sku",
    "{توضیحات}": "description",
}


def placeholder_help_text() -> str:
    """متن راهنما برای نمایش در تب — لیست جای‌خالی‌های قابل استفاده."""
    return "جای‌خالی‌های قابل استفاده: " + "، ".join(PLACEHOLDER_KEYS.keys())


def get_telegram_template(config: dict | None) -> str:
    cfg = config or {}
    raw = cfg.get(TELEGRAM_TEMPLATE_CONFIG_KEY)
    if isinstance(raw, str) and raw.strip():
        return raw
    return DEFAULT_TELEGRAM_TEMPLATE


def _fmt_number(value) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value or "")


def render_template(template: str, product: dict) -> str:
    """جایگزینی جای‌خالی‌های الگو با مقادیر واقعی محصول.

    product می‌تواند شامل: name, price, sale_price, stock, sku, description باشد.
    قیمت ویژه اگر صفر/خالی باشد، خط مربوطه در الگو با رشته‌ی خالی جایگزین می‌شود
    (نه اینکه عدد صفر نمایش داده شود).
    """
    text = template or ""
    data = product or {}

    replacements = {
        "{نام}": str(data.get("name") or "").strip(),
        "{قیمت}": _fmt_number(data.get("price")),
        "{قیمت_ویژه}": _fmt_number(data.get("sale_price")) if data.get("sale_price") else "",
        "{موجودی}": str(int(data.get("stock") or 0)),
        "{کد}": str(data.get("sku") or "").strip(),
        "{توضیحات}": str(data.get("description") or "").strip(),
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def build_telegram_share_url(caption_text: str, product_url: str) -> str:
    """
    لینک اشتراک‌گذاری رسمی تلگرام.
    caption_text = متن ساخته‌شده از الگوی کاربر (بدون لینک).
    product_url = لینک واقعی صفحه محصول روی ووکامرس — تلگرام خودش
    آن را انتهای پیام اضافه می‌کند (طبق درخواست: لینک انتهای الگو).
    """
    text_q = quote((caption_text or "").strip())
    url_q = quote((product_url or "").strip(), safe="")
    return f"https://t.me/share/url?url={url_q}&text={text_q}"


def fetch_wc_product_permalink(wcapi, product_id: int) -> str:
    """لینک زنده‌ی صفحه محصول از ووکامرس — برای پیوست به پست تلگرام."""
    from sync_app.core.wc_sync_helper import wc_call, wc_parse_json

    def _get():
        resp = wcapi.get(
            f"products/{int(product_id)}",
            params={"_fields": "id,permalink"},
        )
        data = wc_parse_json(resp, f"دریافت لینک محصول #{product_id}")
        if isinstance(data, dict):
            return str(data.get("permalink") or "").strip()
        return ""

    try:
        return wc_call(wcapi, f"دریافت لینک محصول #{product_id}", _get, retries=1) or ""
    except Exception:
        return ""
