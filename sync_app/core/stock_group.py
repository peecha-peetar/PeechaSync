"""
گروه موجودی مشترک — وقتی چند کد کالای مشابه (مثلاً همون کالا تو چند
دسته‌بندی مختلف ثبت شده) داریم، ولی فقط یکی («اصلی») باید واقعاً به
ووکامرس منتقل بشه. بقیه («فرعی») اصلاً به سایت ارسال نمی‌شن — فقط
موجودی‌شون با موجودی محصول اصلی جمع می‌شه و مجموع، به‌عنوان موجودی
محصول اصلی روی ووکامرس اعمال می‌شه.

ذخیره‌سازی: یه دیکشنری ساده {کد_فرعی: کد_اصلی} — این‌طوری هم می‌شه
سریع فهمید یه SKU فرعیه یا نه (و مال کدوم اصلیه)، هم می‌شه از روش
معکوس همه‌ی فرعی‌های یه اصلی رو پیدا کرد.
"""

from __future__ import annotations

STOCK_GROUP_KEY = "STOCK_GROUP_SECONDARY_OF"  # {secondary_sku: primary_sku}


def get_primary_of(config: dict, sku: str) -> str | None:
    """اگه sku یه محصول «فرعی»ه، کد محصول اصلی‌اش رو برمی‌گردونه؛ وگرنه None."""
    links = (config or {}).get(STOCK_GROUP_KEY) or {}
    primary = str(links.get(str(sku).strip()) or "").strip()
    return primary or None


def is_secondary(config: dict, sku: str) -> bool:
    return get_primary_of(config, sku) is not None


def get_secondaries_of(config: dict, primary_sku: str) -> list[str]:
    """همه‌ی کدهای فرعی‌ای که به این محصول اصلی وصل شدن."""
    links = (config or {}).get(STOCK_GROUP_KEY) or {}
    primary_sku = str(primary_sku).strip()
    return [sec for sec, prim in links.items() if str(prim).strip() == primary_sku]


def set_secondary_link(secondary_sku: str, primary_sku: str | None) -> None:
    """
    primary_sku=None یعنی این محصول دیگه فرعی هیچی نیست (لینک حذف بشه).
    محدودیت‌های منطقی رعایت می‌شه: یه محصول نمی‌تونه هم اصلی یه گروه باشه
    هم فرعی گروه دیگه (چرخه/تناقض)، و یه محصول نمی‌تونه فرعی خودش باشه.
    """
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    secondary_sku = str(secondary_sku).strip()
    cfg = load_secure_config(None) or {}
    links = dict(cfg.get(STOCK_GROUP_KEY) or {})

    if not primary_sku:
        links.pop(secondary_sku, None)
    else:
        primary_sku = str(primary_sku).strip()
        if primary_sku == secondary_sku:
            return  # یه محصول نمی‌تونه فرعی خودش باشه
        if secondary_sku in links.values():
            return  # این SKU خودش الان «اصلیِ» یه گروهه — نمی‌تونه هم‌زمان فرعی هم بشه
        if primary_sku in links:
            return  # اون یکی که می‌خوایم اصلی‌اش کنیم، خودش الان فرعی یه گروه دیگه‌ست
        links[secondary_sku] = primary_sku

    cfg[STOCK_GROUP_KEY] = links
    save_secure_config(cfg)


def combined_stock_for_primary(primary_sku: str, own_stock: int, config: dict, stock_lookup) -> int:
    """
    موجودی محصول اصلی + مجموع موجودی همه‌ی فرعی‌هاش. stock_lookup یه
    تابعه که یه SKU می‌گیره و موجودیش تو ERP رو برمی‌گردونه (چون خودِ
    این ماژول به دیتابیس دسترسی نداره — جدا نگه داشته شده تا قابل‌تست
    باشه).
    """
    total = int(own_stock or 0)
    for sec_sku in get_secondaries_of(config, primary_sku):
        try:
            total += int(stock_lookup(sec_sku) or 0)
        except Exception:
            pass
    return total
