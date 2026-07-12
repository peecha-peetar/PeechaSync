"""توقف sync از طرف کاربر."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_cancel_event = threading.Event()


class SyncCancelled(Exception):
    """کاربر همگام‌سازی را متوقف کرد."""


def begin_sync() -> None:
    with _lock:
        _cancel_event.clear()


def request_cancel() -> None:
    with _lock:
        _cancel_event.set()


def is_cancelled() -> bool:
    return _cancel_event.is_set()


def check_cancelled() -> None:
    if _cancel_event.is_set():
        raise SyncCancelled("همگام‌سازی توسط کاربر متوقف شد.")
