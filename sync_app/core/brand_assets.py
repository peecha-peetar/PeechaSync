"""لوگو و آیکن برند — PNG شفاف برای هدر، نسخه تیره برای پس‌زمینه روشن."""

from __future__ import annotations

import os
import sys

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QImage, QPixmap

from sync_app.core.sync_utils import resource_path

BRAND_NAVY = (26, 39, 133)
APP_USER_MODEL_ID = "Mydejavu.PeechaSync"


def _install_root_icon() -> str:
    try:
        from sync_app.core.app_update import app_install_root

        path = os.path.join(app_install_root(), "PeechaSync.ico")
        if os.path.isfile(path):
            return path
    except Exception:
        pass
    return ""


def _icon_candidates() -> tuple[str, ...]:
    # روی ویندوز taskbar فقط ICO درست کار می‌کند؛ PNG معمولاً thumbnail عمومی می‌دهد.
    if sys.platform == "win32":
        return ("PeechaSync.ico", "Peecha_logo.ico", "Peecha_logo_app.png", "Peecha_logo.png")
    return ("Peecha_logo_app.png", "PeechaSync.ico", "Peecha_logo.ico", "Peecha_logo.png")


def brand_icon_path() -> str:
    root_ico = _install_root_icon()
    if root_ico:
        return root_ico
    for name in _icon_candidates():
        path = resource_path(name)
        if path and os.path.isfile(path):
            return path
    return ""


def apply_windows_app_id() -> None:
    """AppUserModelID — قبل از QApplication صدا زده شود."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def apply_windows_taskbar_icon(widget) -> None:
    """ست کردن آیکن native برای taskbar ویندوز."""
    if sys.platform != "win32":
        return
    ico_path = _install_root_icon() or resource_path("PeechaSync.ico") or resource_path("Peecha_logo.ico")
    if not ico_path or not os.path.isfile(ico_path):
        ico_path = brand_icon_path()
    if not ico_path or not ico_path.lower().endswith(".ico"):
        return
    try:
        wid = int(widget.winId())
    except Exception:
        return
    if not wid:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        ico_abs = os.path.abspath(ico_path)
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        IMAGE_ICON = 1
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        hicon = user32.LoadImageW(
            None,
            ico_abs,
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        if not hicon:
            hicon = user32.LoadImageW(None, ico_abs, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if hicon:
            user32.SendMessageW(wid, WM_SETICON, ICON_BIG, hicon)
            user32.SendMessageW(wid, WM_SETICON, ICON_SMALL, hicon)
    except Exception:
        pass


def _logo_path(light_background: bool) -> str:
    if light_background:
        dark = resource_path("Peecha_logo_dark.png")
        if os.path.isfile(dark):
            return dark
    path = resource_path("Peecha_logo.png")
    return path if os.path.isfile(path) else ""


HEADER_LOGO_HEIGHT = 40
HEADER_FRAME_HEIGHT = 72


def _alpha_content_bbox(image: QImage, *, threshold: int = 8) -> tuple[int, int, int, int] | None:
    w, h = image.width(), image.height()
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            if image.pixelColor(x, y).alpha() > threshold:
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if not found:
        return None
    return min_x, min_y, max_x - min_x + 1, max_y - min_y + 1


def _trim_transparent_pixmap(pixmap: QPixmap) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    bbox = _alpha_content_bbox(image)
    if bbox is None:
        return pixmap
    x, y, cw, ch = bbox
    if x == 0 and y == 0 and cw == image.width() and ch == image.height():
        return pixmap
    return QPixmap.fromImage(image.copy(x, y, cw, ch))


def brand_logo_pixmap(height: int = HEADER_LOGO_HEIGHT, *, light_background: bool = False) -> QPixmap:
    path = _logo_path(light_background)
    if not path:
        return QPixmap()
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return pixmap
    pixmap = _trim_transparent_pixmap(pixmap)
    return pixmap.scaledToHeight(max(24, int(height)), Qt.SmoothTransformation)


def brand_app_icon() -> QIcon:
    for candidate in (_install_root_icon(), resource_path("PeechaSync.ico"), resource_path("Peecha_logo.ico")):
        if sys.platform == "win32" and candidate and os.path.isfile(candidate):
            icon = QIcon(candidate)
            if not icon.isNull():
                for size in (16, 24, 32, 48, 64, 128, 256):
                    icon.addFile(candidate, QSize(size, size), QIcon.Normal, QIcon.Off)
                return icon

    for name in _icon_candidates():
        path = resource_path(name)
        if not path or not os.path.isfile(path):
            continue
        icon = QIcon(path)
        if not icon.isNull():
            return icon
    pm = brand_logo_pixmap(64, light_background=False)
    return QIcon(pm) if not pm.isNull() else QIcon()


def apply_brand_window_icon(widget) -> None:
    icon = brand_app_icon()
    if not icon.isNull():
        widget.setWindowIcon(icon)
    apply_windows_taskbar_icon(widget)
