from abc import ABC, abstractmethod


class BaseERPProvider(ABC):
    """ interface ERP """

    provider_name = "base"

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

    def health_check(self):
        return True, "اتصال Dejavu فعال است."

    def get_provider_hint(self):
        return "Provider فعلی روی SQL/Dejavu تنظیم شده است."


class SepidarProviderStub(BaseERPProvider):
    provider_name = "sepidar_preview"

    def health_check(self):
        return False, "اتصال سپیدار هنوز پیاده سازی نهایی نشده است."

    def get_provider_hint(self):
        return "حالت پیش نمایشی سپیدار فعال است (فقط زیرساخت)."


def get_provider(provider_name):
    name = (provider_name or "dejavu").strip().lower()
    if name == "sepidar_preview":
        return SepidarProviderStub()
    return DejavuProvider()
