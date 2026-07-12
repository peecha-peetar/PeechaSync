"""
تعریف مرکزی فیلدهای قابل‌انتخاب برای همگام‌سازی (SQL → WooCommerce).

هر ورودی: (کلید_تنظیمات, برچسب فارسی برای UI, مقدار پیش‌فرض).
پیش‌فرض همه True است تا رفتار فعلی برنامه (ارسال همه‌ی فیلدها) حفظ شود
و کسی که این نسخه را از قبل نصب کرده با آپدیت، رفتار غیرمنتظره نبیند.

توجه: قیمت عادی (regular_price) و قیمت ویژه (sale_price) عمداً اینجا نیستند —
قیمت عادی همیشه ارسال می‌شود و قیمت ویژه کلید تنظیمات جدای خودش را دارد
(SALE_PRICE_LIST_ENABLED) که از قبل در تب تنظیمات وجود دارد.
"""

# محصول
PRODUCT_FIELDS = [
    ("SYNC_FIELD_PRODUCT_NAME", "نام محصول", True),
    ("SYNC_FIELD_PRODUCT_DESCRIPTION", "توضیحات محصول", True),
    ("SYNC_FIELD_PRODUCT_CATEGORIES", "دسته‌بندی محصول", True),
    ("SYNC_FIELD_PRODUCT_STOCK", "موجودی محصول", True),
    ("SYNC_FIELD_PRODUCT_VISIBILITY", "وضعیت نمایش محصول (Visibility)", True),
]

# دسته‌بندی
CATEGORY_FIELDS = [
    ("SYNC_FIELD_CATEGORY_NAME", "نام دسته‌بندی", True),
    ("SYNC_FIELD_CATEGORY_SLUG", "Slug دسته‌بندی", True),
    ("SYNC_FIELD_CATEGORY_PARENT", "دسته‌ی والد (Parent)", True),
]

# ویژگی / ترم
ATTRIBUTE_FIELDS = [
    ("SYNC_FIELD_ATTRIBUTE_NAME", "نام ویژگی / ترم", True),
    ("SYNC_FIELD_ATTRIBUTE_SLUG", "Slug ویژگی / ترم", True),
]

# متغیر (واریانت)
VARIATION_FIELDS = [
    ("SYNC_FIELD_VARIATION_STOCK", "موجودی متغیر (Variation Stock)", True),
]

ALL_FIELD_GROUPS = [
    ("محصول", PRODUCT_FIELDS),
    ("دسته‌بندی", CATEGORY_FIELDS),
    ("ویژگی / ترم", ATTRIBUTE_FIELDS),
    ("متغیر", VARIATION_FIELDS),
]


def default_for(key: str) -> bool:
    for _, fields in ALL_FIELD_GROUPS:
        for cfg_key, _label, default in fields:
            if cfg_key == key:
                return default
    return True


def is_field_enabled(config: dict, key: str) -> bool:
    """آیا این فیلد باید همگام‌سازی شود — پیش‌فرض True (رفتار فعلی برنامه)."""
    cfg = config or {}
    value = cfg.get(key)
    if value is None:
        return default_for(key)
    return bool(value)


def all_field_keys():
    keys = []
    for _, fields in ALL_FIELD_GROUPS:
        for cfg_key, _label, _default in fields:
            keys.append(cfg_key)
    return keys
