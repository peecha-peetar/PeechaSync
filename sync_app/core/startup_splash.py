"""اسپلش سبک — فقط PyQt5 برای نمایش فوری قبل از importهای سنگین."""

from __future__ import annotations

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class StartupSplash(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedSize(420, 100)
        self.setStyleSheet("background-color: #020025;")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 6, 6, 10)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.addStretch(1)
        close_btn = QPushButton("×")
        close_btn.setFixedSize(26, 26)
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip("بستن")
        close_btn.setStyleSheet(
            "QPushButton { color: #ffffff; font-size: 18px; border: none; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.18); }"
        )
        close_btn.clicked.connect(self._quit_app)
        top.addWidget(close_btn)
        root.addLayout(top)

        self._message = QLabel("در حال بارگذاری PeechaSync...\nLoading PeechaSync...")
        self._message.setAlignment(Qt.AlignCenter)
        self._message.setStyleSheet("color: #ffffff; font-family: 'Segoe UI'; font-size: 10pt;")
        root.addWidget(self._message, 1)

    def _quit_app(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _center(self) -> None:
        app = QApplication.instance()
        if app is not None and app.primaryScreen() is not None:
            geo = app.primaryScreen().availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )

    def showMessage(self, text, alignment=Qt.AlignCenter, color=None) -> None:
        self._message.setText(str(text or ""))
        if color is not None:
            self._message.setStyleSheet(
                f"color: {color.name()}; font-family: 'Segoe UI'; font-size: 10pt;"
            )
        if alignment is not None:
            self._message.setAlignment(alignment)

    def finish(self, window) -> None:
        self.close()

    def show(self) -> None:
        self._center()
        super().show()


def ensure_startup_splash(argv=None):
    """QApplication + splash — قبل از import peecha_launcher."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv or sys.argv)
    splash = getattr(app, "_peecha_splash", None)
    if splash is None:
        splash = StartupSplash()
        splash.setFont(QFont("Segoe UI", 10))
        splash.show()
        app.processEvents()
        app._peecha_splash = splash
    return app, splash
