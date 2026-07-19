"""ویجتِ گربه‌ی متحرکِ «پیچا» — روی هدرِ برنامه از راست به چپ و برعکس راه
می‌ره، با یه واکِ لِی‌لِی (bounce) و در هر گوشه چند تا ادا (چرخش/پرش) درمیاره.

اگه sync_app/core/Peecha.png موجود نباشه، این ویجت کاملاً غیرفعال و مخفی
می‌مونه — هیچ اثری روی ظاهر یا عملکردِ بقیه‌ی هدر نداره."""
from __future__ import annotations

import math
import os

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import QLabel

_TICK_MS = 20
_MARGIN = 14
_PIXELS_PER_MS = 0.085
_BOUNCE_AMPLITUDE = 5.0
_BOUNCE_CYCLES_PER_LEG = 7.0
_GESTURE_HOLD_TICKS = 8
# هر فریمِ ادا: (جابه‌جاییِ افقی، جابه‌جاییِ عمودی، زاویه‌ی چرخش) نسبت به
# موقعیتِ ایستادهٔ گربه در انتهای مسیر
_GESTURE_FRAMES = [
    (0, -10, -12),
    (0, -2, 10),
    (0, -9, -12),
    (0, -2, 10),
    (0, -6, 0),
    (0, 0, 0),
]


def _load_peecha_circle(size: int) -> QPixmap:
    from sync_app.core.sync_utils import resource_path

    path = resource_path("Peecha.png")
    if not path or not os.path.isfile(path):
        return QPixmap()
    src = QPixmap(path)
    if src.isNull():
        return QPixmap()
    src = src.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (src.width() - size) // 2)
    y = max(0, (src.height() - size) // 2)
    src = src.copy(x, y, size, size)

    rounded = QPixmap(size, size)
    rounded.fill(Qt.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size, size)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, src)
    painter.setClipping(False)
    pen = painter.pen()
    pen.setColor(Qt.white)
    pen.setWidthF(2.0)
    painter.setPen(pen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return rounded


def _rotated(pixmap: QPixmap, angle: float) -> QPixmap:
    if not angle:
        return pixmap
    size = pixmap.size()
    result = QPixmap(size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(size.width() / 2, size.height() / 2)
    painter.rotate(angle)
    painter.translate(-size.width() / 2, -size.height() / 2)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


class PeechaMascotWidget(QLabel):
    """گربه‌ای که رویِ هدر، بینِ لبه‌ی راست و چپ، پیوسته در رفت‌وآمده."""

    SIZE = 46

    def __init__(self, header_frame):
        super().__init__(header_frame)
        self._header = header_frame
        self._base_pixmap = _load_peecha_circle(self.SIZE)
        self._enabled = not self._base_pixmap.isNull()
        if not self._enabled:
            self.hide()
            return

        self._flipped_pixmap = QPixmap.fromImage(self._base_pixmap.toImage().mirrored(True, False))
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        self.setToolTip("پیچا 🐾")
        self.setPixmap(self._flipped_pixmap)

        self._state = "idle"
        self._started = False
        self._going_left = True
        self._start_x = 0
        self._end_x = 0
        self._base_y = 4
        self._leg_progress_ms = 0
        self._leg_duration_ms = 1
        self._gesture_frame = 0
        self._gesture_tick = 0

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

        self._header.installEventFilter(self)
        QTimer.singleShot(1200, self._begin)

    def eventFilter(self, obj, event):
        if self._enabled and obj is self._header and event.type() == QEvent.Resize and not self._started:
            QTimer.singleShot(0, self._begin)
        return False

    def _begin(self):
        if not self._enabled or self._started:
            return
        if self._header.width() < self.SIZE * 3:
            QTimer.singleShot(800, self._begin)
            return
        self._started = True
        self._base_y = max(4, (self._header.height() - self.SIZE) // 2)
        self._start_leg()

    def _start_leg(self):
        header_w = self._header.width()
        right_x = header_w - self.SIZE - _MARGIN
        left_x = _MARGIN
        if right_x <= left_x:
            QTimer.singleShot(1000, self._start_leg)
            return

        self._start_x = right_x if self._going_left else left_x
        self._end_x = left_x if self._going_left else right_x
        self.setPixmap(self._flipped_pixmap if self._going_left else self._base_pixmap)
        self.move(self._start_x, self._base_y)
        self.show()
        self.raise_()

        distance = abs(self._end_x - self._start_x)
        self._leg_duration_ms = max(1800, int(distance / _PIXELS_PER_MS))
        self._leg_progress_ms = 0
        self._state = "walking"
        self._timer.start()

    def _tick(self):
        if self._state == "walking":
            self._leg_progress_ms += _TICK_MS
            t = min(1.0, self._leg_progress_ms / self._leg_duration_ms)
            eased = t * t * (3 - 2 * t)  # smoothstep
            x = self._start_x + (self._end_x - self._start_x) * eased
            bounce = abs(math.sin(t * _BOUNCE_CYCLES_PER_LEG * math.pi)) * _BOUNCE_AMPLITUDE
            self.move(int(x), int(self._base_y - bounce))
            if t >= 1.0:
                self.move(int(self._end_x), self._base_y)
                self._state = "gesture"
                self._gesture_frame = 0
                self._gesture_tick = 0
            return

        if self._state == "gesture":
            self._gesture_tick += 1
            if self._gesture_tick < _GESTURE_HOLD_TICKS:
                return
            self._gesture_tick = 0
            step = self._gesture_frame
            if step >= len(_GESTURE_FRAMES):
                self._timer.stop()
                self._state = "idle"
                self.setPixmap(self._flipped_pixmap if self._going_left else self._base_pixmap)
                self.move(int(self._end_x), self._base_y)
                self._going_left = not self._going_left
                QTimer.singleShot(500, self._start_leg)
                return
            dx, dy, angle = _GESTURE_FRAMES[step]
            base = self._flipped_pixmap if self._going_left else self._base_pixmap
            self.setPixmap(_rotated(base, angle))
            self.move(int(self._end_x + dx), int(self._base_y + dy))
            self._gesture_frame += 1
