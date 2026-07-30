"""لایه‌ی مشترکِ «مقاله» — بسته به پلتفرمِ فروشگاه (ووکامرس/وردپرس یا
پرستاشاپ)، درخواست‌ها رو به wp_posts_helper.py یا ps_cms_helper.py
هدایت می‌کنه، تا کدِ بالادستیِ UI فقط با یه شکلِ یکسان از «مقاله» کار
کنه.

⚠️ برایِ پرستاشاپ، «مقاله» یعنی صفحه‌ی CMS (نزدیک‌ترین معادلِ بومی و
پایدارِ Webserviceِ core — نه ماژولِ Blog که API استانداردی نداره).
تفاوت‌هایِ مهم بینِ دو پلتفرم:
  - تصویرِ شاخص: فقط ووکامرس/وردپرس پشتیبانی می‌کنه.
  - دسته‌بندی: وردپرس چندتایی، پرستاشاپ فقط یک دسته‌یِ CMS.
  - متا-کلمات‌کلیدی/عنوانِ سئو: پرستاشاپ بومی داره؛ وردپرس بسته به
    افزونه‌ی سئو فرق می‌کنه (این‌جا فقط پیشنهادی/محلی محاسبه می‌شه)."""

from __future__ import annotations

from sync_app.core.integrations.commerce_provider import is_prestashop


def supports_featured_image(config) -> bool:
    return not is_prestashop(config)


def supports_multi_category(config) -> bool:
    return not is_prestashop(config)


def _backend(config):
    if is_prestashop(config):
        from sync_app.core import ps_cms_helper as backend
    else:
        from sync_app.core import wp_posts_helper as backend
    return backend


def list_articles(config, *, page: int = 1, per_page: int = 20, search: str = "") -> tuple[list[dict], int]:
    return _backend(config).list_posts(config, page=page, per_page=per_page, search=search)


def get_article(config, article_id: int) -> dict:
    return _backend(config).get_post(config, article_id)


def create_article(config, article: dict) -> dict:
    return _backend(config).create_post(config, article)


def update_article(config, article_id: int, article: dict) -> dict:
    return _backend(config).update_post(config, article_id, article)


def delete_article(config, article_id: int) -> bool:
    return _backend(config).delete_post(config, article_id)


def list_categories(config) -> list[dict]:
    return _backend(config).list_categories(config)


def create_category(config, name: str, parent: int = 0) -> dict:
    return _backend(config).create_category(config, name, parent)


def update_category(config, category_id: int, *, name: str | None = None, parent: int | None = None) -> dict:
    return _backend(config).update_category(config, category_id, name=name, parent=parent)


def delete_category(config, category_id: int) -> bool:
    return _backend(config).delete_category(config, category_id)


def upload_image(config, image_data: bytes, filename: str) -> tuple[bool, int, str, str]:
    """آپلودِ عکس به کتابخانه‌ی رسانه — هم برایِ تصویرِ شاخص هم برایِ
    عکسِ داخلِ محتوا استفاده می‌شه. خروجی: (ok, media_id, source_url, error)."""
    if is_prestashop(config):
        return False, 0, "", "آپلودِ عکس فقط برایِ سایت‌هایِ ووکامرس پشتیبانی می‌شه — برایِ پرستاشاپ، لینکِ عکس رو دستی وارد کنید."
    from sync_app.core.wp_posts_helper import upload_featured_image as _upload

    return _upload(config, image_data, filename)


# نامِ قدیمی — برایِ سازگاری با کدِ قبلی که این اسم رو صدا می‌زنه.
upload_featured_image = upload_image
