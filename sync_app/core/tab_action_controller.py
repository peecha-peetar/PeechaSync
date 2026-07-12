"""مدیریت یکپارچه دکمه‌های عملیاتی تب — توقف، قفل متقابل، قفل تعویض تب."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from sync_app.core.tab_operation_guard import lock_tab_navigation, unlock_tab_navigation


def make_stop_text(idle_text: str) -> str:
    """برچسب توقف: «توقف» + همان نام دکمه."""
    text = (idle_text or "").strip()
    if not text:
        return "⏹ توقف"
    if text.startswith("⏹"):
        return text
    return f"⏹ توقف {text}"


@dataclass
class ActionSpec:
    button: object
    idle_text: str
    stop_text: str = ""
    idle_style: str = ""
    stop_style: str = ""
    on_stop: Optional[Callable[[], None]] = None


class TabActionController:
    """یک عملیات فعال در هر زمان؛ دکمه فعال حالت توقف، بقیه غیرفعال."""

    def __init__(self, tab_widget):
        self._tab = tab_widget
        self._actions: Dict[str, ActionSpec] = {}
        self._active: Optional[str] = None
        self._extra_disable: list = []
        self._locked_nav = False

    @staticmethod
    def _is_compact_button(btn) -> bool:
        try:
            return bool(btn.property("compactActionBtn"))
        except Exception:
            return False

    def _apply_button_style(self, btn, style: str) -> None:
        if self._is_compact_button(btn):
            return
        btn.setStyleSheet(style or "")

    def register(self, op_id: str, spec: ActionSpec) -> None:
        if not (spec.stop_text or "").strip():
            spec.stop_text = make_stop_text(spec.idle_text)
        self._actions[op_id] = spec

    def register_extra_widgets(self, *widgets) -> None:
        self._extra_disable.extend(widgets)

    @property
    def busy(self) -> bool:
        return self._active is not None

    @property
    def active(self) -> Optional[str]:
        return self._active

    def begin(self, op_id: str, *, working_text: Optional[str] = None, lock_tabs: bool = True) -> bool:
        if self._active:
            return False
        spec = self._actions.get(op_id)
        if spec is None:
            return False
        self._active = op_id
        self._locked_nav = bool(lock_tabs)
        if self._locked_nav:
            lock_tab_navigation(self._tab)
        for oid, action in self._actions.items():
            btn = action.button
            if oid == op_id:
                btn.setEnabled(True)
                btn.setText(working_text or action.stop_text)
                self._apply_button_style(btn, action.stop_style)
            else:
                btn.setEnabled(False)
        for widget in self._extra_disable:
            try:
                widget.setEnabled(False)
            except Exception:
                pass
        return True

    def set_stopping(self, op_id: Optional[str] = None) -> None:
        oid = op_id or self._active
        if not oid:
            return
        spec = self._actions.get(oid)
        if spec is None:
            return
        spec.button.setText("⏳ در حال توقف...")
        spec.button.setEnabled(False)

    def end(self) -> None:
        if not self._active:
            return
        self._active = None
        if self._locked_nav:
            unlock_tab_navigation(self._tab)
        self._locked_nav = False
        for action in self._actions.values():
            btn = action.button
            btn.setEnabled(True)
            btn.setText(action.idle_text)
            self._apply_button_style(btn, action.idle_style)
        for widget in self._extra_disable:
            try:
                widget.setEnabled(True)
            except Exception:
                pass

    def handle_click(self, op_id: str, start_fn: Callable[[], None]) -> None:
        if self._active == op_id:
            spec = self._actions.get(op_id)
            if spec and spec.on_stop:
                spec.on_stop()
            return
        if self.busy:
            return
        start_fn()
