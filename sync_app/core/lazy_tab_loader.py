"""ساخت تنبل تب‌ها — import ماژول فقط هنگام اولین باز شدن."""

from __future__ import annotations

import importlib
from typing import Any, Callable


def import_tab_class(module_path: str, class_name: str):
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def tab_factory(module_path: str, class_name: str, **init_kwargs: Any) -> Callable[[], Any]:
    def factory() -> Any:
        cls = import_tab_class(module_path, class_name)
        return cls(**init_kwargs) if init_kwargs else cls()

    return factory
