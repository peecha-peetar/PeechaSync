from abc import ABC, abstractmethod


class BaseERPProvider(ABC):
    """ interface ERP """

    provider_name = "base"
    display_name = "ERP"

    @abstractmethod
    def health_check(self):
        """ health check """
        raise NotImplementedError

    @abstractmethod
    def get_provider_hint(self):
        """ وضعیت provider """
        raise NotImplementedError


class DejavuProvider(BaseERPProvider):
    provider_name = "dejavu"
    display_name = "دژاوو"

    def health_check(self):
        return True, "اتصال دژاوو فعال است."

    def get_provider_hint(self):
        return "Provider فعلی روی دژاوو تنظیم شده است."


class HolooProviderStub(BaseERPProvider):
    provider_name = "holoo"
    display_name = "هلو"

    def health_check(self):
        return False, "اتصال هلو هنوز پیاده‌سازی نهایی نشده است."

    def get_provider_hint(self):
        return "حالت پیش‌نمایشی هلو فعال است (فقط زیرساخت)."


class SepidarProviderStub(BaseERPProvider):
    provider_name = "sepidar"
    display_name = "سپیدار"

    def health_check(self):
        return False, "اتصال سپیدار هنوز پیاده‌سازی نهایی نشده است."

    def get_provider_hint(self):
        return "حالت پیش‌نمایشی سپیدار فعال است (فقط زیرساخت)."


class DashtProviderStub(BaseERPProvider):
    provider_name = "dasht"
    display_name = "دشت"

    def health_check(self):
        return False, "اتصال دشت هنوز پیاده‌سازی نهایی نشده است."

    def get_provider_hint(self):
        return "حالت پیش‌نمایشی دشت فعال است (فقط زیرساخت)."


class GhiaasProviderStub(BaseERPProvider):
    provider_name = "ghiaas"
    display_name = "قیاس"

    def health_check(self):
        return False, "اتصال قیاس هنوز پیاده‌سازی نهایی نشده است."

    def get_provider_hint(self):
        return "حالت پیش‌نمایشی قیاس فعال است (فقط زیرساخت)."


# ترتیبِ نمایش تو تنظیمات: دژاوو، هلو، سپیدار، دشت، قیاس.
ERP_PROVIDER_CHOICES = [
    ("dejavu", "دژاوو"),
    ("holoo", "هلو"),
    ("sepidar", "سپیدار"),
    ("dasht", "دشت"),
    ("ghiaas", "قیاس"),
]

_PROVIDER_CLASSES = {
    "dejavu": DejavuProvider,
    "holoo": HolooProviderStub,
    "sepidar": SepidarProviderStub,
    "dasht": DashtProviderStub,
    "ghiaas": GhiaasProviderStub,
    # سازگاری با مقدارِ قدیمیِ ذخیره‌شده تو کانفیگِ نصب‌های قبلی
    "sepidar_preview": SepidarProviderStub,
}


def normalize_erp_provider_key(provider_name) -> str:
    name = str(provider_name or "dejavu").strip().lower()
    if name not in _PROVIDER_CLASSES:
        return "dejavu"
    return "sepidar" if name == "sepidar_preview" else name


def get_provider(provider_name):
    key = normalize_erp_provider_key(provider_name)
    return _PROVIDER_CLASSES[key]()


def erp_provider_label(config) -> str:
    """نامِ نمایشیِ Providerِ ERP انتخاب‌شده (تو تنظیمات) — به‌جای کلمه‌ی
    ژنریکِ «ERP» یا «SQL» تو کلِ برنامه استفاده می‌شه، تا همه‌جا اسمِ
    نرم‌افزار/دیتابیسی که کاربر واقعاً بهش وصله نشون داده بشه."""
    key = normalize_erp_provider_key((config or {}).get("ERP_PROVIDER"))
    cls = _PROVIDER_CLASSES.get(key, DejavuProvider)
    return cls.display_name
