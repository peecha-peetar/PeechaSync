"""ویجتِ ویدئوی زنده‌ی «پیچا» — یه کلیپِ کوتاهِ واقعی از گربه رو تویِ یه
پنجره‌ی کوچیکِ گردشده رویِ هدر پخش می‌کنه (بی‌صدا، لوپ) و بینِ لبه‌ی راست
و چپِ هدر جابه‌جا می‌شه؛ همون رفتاری که برای «پیچای متحرکِ عکسی» ساخته
شده بود (PeechaMascotWidget)، ولی این‌بار به‌جایِ یه عکسِ ثابت، خودِ
ویدئوی واقعی نمایش داده می‌شه — چون تصویرِ زنده خودش رفتار/ادا رو داره،
نیازی به شبیه‌سازیِ ژستِ مصنوعی نیست.

اگه sync_app/core/Peecha.mp4 موجود نباشه، این ویجت کاملاً غیرفعال و
مخفی می‌مونه."""
from __future__ import annotations

import math
import os

from PyQt5.QtCore import QEvent, QRectF, Qt, QTimer, QUrl
from PyQt5.QtGui import QPainterPath, QRegion
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsView

_TICK_MS = 20
_MARGIN = 14
_PIXELS_PER_MS = 0.07
_BOUNCE_AMPLITUDE = 4.0
_BOUNCE_CYCLES_PER_LEG = 6.0
_PAUSE_MS = 900


def _video_path() -> str:
    from sync_app.core.sync_utils import resource_path

    path = resource_path("Peecha.mp4")
    return path if path and os.path.isfile(path) else ""


class PeechaVideoMascotWidget(QGraphicsView):
    """کلیپِ زنده‌ی پیچا که رویِ هدر، بینِ لبه‌ی راست و چپ در رفت‌وآمده."""

    WIDTH = 76
    HEIGHT = 54
    RADIUS = 14

    def __init__(self, header_frame):
        super().__init__(header_frame)
        self._header = header_frame

        video_file = _video_path()
        self._enabled = bool(video_file)
        if not self._enabled:
            self.hide()
            return

        self.setFrameShape(QGraphicsView.NoFrame)
        self.setStyleSheet("background: transparent; border: none;")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self._apply_rounded_mask()

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, self.WIDTH, self.HEIGHT)
        self.setScene(self._scene)

        self._video_item = QGraphicsVideoItem()
        self._video_item.setSize(QRectF(0, 0, self.WIDTH, self.HEIGHT).size())
        self._video_item.setAspectRatioMode(Qt.KeepAspectRatioByExpanding)
        self._scene.addItem(self._video_item)

        self._player = QMediaPlayer(self, QMediaPlayer.VideoSurface)
        self._player.setVideoOutput(self._video_item)
        self._player.setMuted(True)
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(video_file)))
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.play()

        self._state = "idle"
        self._started = False
        self._going_left = True
        self._start_x = 0
        self._end_x = 0
        self._base_y = 4
        self._leg_progress_ms = 0
        self._leg_duration_ms = 1
        self._pause_ms = 0

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)

        self._header.installEventFilter(self)
        QTimer.singleShot(1200, self._begin)

    def _apply_rounded_mask(self):
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.WIDTH, self.HEIGHT, self.RADIUS, self.RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _on_media_status(self, status):
        # لوپِ بی‌درزِ ویدئو: به‌محضِ رسیدن به انتها، از اول پخش می‌شه
        if status == QMediaPlayer.EndOfMedia:
            self._player.setPosition(0)
            self._player.play()

    def eventFilter(self, obj, event):
        if self._enabled and obj is self._header and event.type() == QEvent.Resize and not self._started:
            QTimer.singleShot(0, self._begin)
        return False

    def _begin(self):
        if not self._enabled or self._started:
            return
        if self._header.width() < self.WIDTH * 3:
            QTimer.singleShot(800, self._begin)
            return
        self._started = True
        self._base_y = max(4, (self._header.height() - self.HEIGHT) // 2)
        self._start_leg()

    def _start_leg(self):
        header_w = self._header.width()
        right_x = header_w - self.WIDTH - _MARGIN
        left_x = _MARGIN
        if right_x <= left_x:
            QTimer.singleShot(1000, self._start_leg)
            return

        self._start_x = right_x if self._going_left else left_x
        self._end_x = left_x if self._going_left else right_x
        self.move(self._start_x, self._base_y)
        self.show()
        self.raise_()

        distance = abs(self._end_x - self._start_x)
        self._leg_duration_ms = max(2200, int(distance / _PIXELS_PER_MS))
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
                self._state = "pause"
                self._pause_ms = 0
            return

        if self._state == "pause":
            self._pause_ms += _TICK_MS
            if self._pause_ms >= _PAUSE_MS:
                self._timer.stop()
                self._state = "idle"
                self._going_left = not self._going_left
                QTimer.singleShot(300, self._start_leg)
