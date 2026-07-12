""" ذخیره/بازیابی geometry پنجره """
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtWidgets import QApplication

DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 800
MIN_VISIBLE = 100


def _available_geometries():
    app = QApplication.instance()
    if app is None:
        return []
    return [screen.availableGeometry() for screen in app.screens()]


def _has_saved_geometry(config):
    keys = ("APP_WINDOW_X", "APP_WINDOW_Y", "APP_WINDOW_WIDTH", "APP_WINDOW_HEIGHT")
    return all(k in (config or {}) for k in keys)


def is_geometry_usable(x, y, width, height, min_visible=MIN_VISIBLE):
    """ نوار عنوان باید روی مانیتور دیده بشه """
    try:
        x = int(x)
        y = int(y)
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return False

    if width < 200 or height < 150:
        return False

    geos = _available_geometries()
    if not geos:
        return True

    window = QRect(x, y, width, height)
    title_bar = QRect(x, y, width, min(48, height))

    for geo in geos:
        body = window.intersected(geo)
        title = title_bar.intersected(geo)
        if body.width() >= min_visible and body.height() >= min_visible:
            if title.width() >= min_visible:
                return True
    return False


def center_on_primary(width, height):
    app = QApplication.instance()
    screen = app.primaryScreen() if app else None
    if screen is None:
        return 100, 100, int(width), int(height)

    geo = screen.availableGeometry()
    w = min(int(width), geo.width())
    h = min(int(height), geo.height())
    x = geo.x() + max(0, (geo.width() - w) // 2)
    y = geo.y() + max(0, (geo.height() - h) // 2)
    return x, y, w, h


def clamp_geometry(x, y, width, height):
    geos = _available_geometries()
    if not geos:
        return int(x), int(y), int(width), int(height)

    bounds = geos[0]
    for geo in geos[1:]:
        bounds = bounds.united(geo)

    w = min(int(width), bounds.width())
    h = min(int(height), bounds.height())
    x = max(bounds.x(), min(int(x), bounds.x() + bounds.width() - w))
    y = max(bounds.y(), min(int(y), bounds.y() + bounds.height() - h))
    return x, y, w, h


def save_window_geometry(widget, config):
    """ geometry فعلی توی config """
    cfg = dict(config or {})
    if widget is None:
        return cfg

    maximized = bool(widget.windowState() & Qt.WindowMaximized)
    rect = widget.normalGeometry() if maximized else widget.geometry()

    cfg["APP_WINDOW_MAXIMIZED"] = maximized
    cfg["APP_WINDOW_X"] = rect.x()
    cfg["APP_WINDOW_Y"] = rect.y()
    cfg["APP_WINDOW_WIDTH"] = rect.width()
    cfg["APP_WINDOW_HEIGHT"] = rect.height()
    return cfg


def apply_window_geometry(widget, config):
    """ geometry از config؛ خارج صفحه بود وسط """
    cfg = config or {}

    if not _has_saved_geometry(cfg):
        widget.showMaximized()
        return

    try:
        x = int(cfg.get("APP_WINDOW_X"))
        y = int(cfg.get("APP_WINDOW_Y"))
        w = int(cfg.get("APP_WINDOW_WIDTH"))
        h = int(cfg.get("APP_WINDOW_HEIGHT"))
    except (TypeError, ValueError):
        widget.showMaximized()
        return

    maximized = bool(cfg.get("APP_WINDOW_MAXIMIZED"))

    if is_geometry_usable(x, y, w, h):
        x, y, w, h = clamp_geometry(x, y, w, h)
    else:
        x, y, w, h = center_on_primary(w, h)

    widget.setGeometry(x, y, w, h)
    if maximized:
        widget.showMaximized()
    else:
        widget.showNormal()
