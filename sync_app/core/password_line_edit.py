""" فیلد رمز با دکمه show/hide """

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QFont, QFontInfo, QColor
from PyQt5.QtWidgets import QLineEdit, QToolButton


class PasswordLineEdit(QLineEdit):
    """ رمز با آیکن سمت راست """

    TOGGLE_BTN_SIZE = 28
    TOGGLE_ICON_SIZE = 20
    TOGGLE_MARGIN_RIGHT = 10

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._password_visible = False

        # RTL نذار آیکن جابه‌جا بشه
        self.setLayoutDirection(Qt.LeftToRight)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._toggle_btn = QToolButton(self)
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setAutoRaise(True)
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._apply_toggle_button_style()
        self._toggle_btn.clicked.connect(self._toggle_visibility)

        self.setEchoMode(QLineEdit.Password)
        self._apply_text_margins()
        self._refresh_toggle_icon()
        self._position_toggle()

        self.textChanged.connect(self._position_toggle)

    def set_toggle_dark_theme(self, enabled=True):
        """ استایل تیره برای لاگین """
        self._toggle_dark = enabled
        self._apply_toggle_button_style()

    def _apply_toggle_button_style(self):
        hover_bg = "rgba(255, 255, 255, 0.1)" if getattr(self, "_toggle_dark", False) else "rgba(15, 23, 42, 0.06)"
        self._toggle_btn.setStyleSheet(
            "QToolButton { border: none; background: transparent; padding: 0; }"
            f"QToolButton:hover {{ background: {hover_bg}; border-radius: 6px; }}"
        )

    @staticmethod
    def build_visibility_icon(is_visible):
        symbol = "☀" if is_visible else "☁"
        size = 28
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        font = QFont("Segoe UI Emoji", 17)
        if not QFontInfo(font).exactMatch():
            font = QFont("Segoe UI Symbol", 17)
        painter.setFont(font)
        painter.setPen(QColor("#f59e0b") if is_visible else QColor("#94a3b8"))
        painter.drawText(0, 0, size, size, Qt.AlignCenter, symbol)
        painter.end()
        return QIcon(pixmap)

    def _apply_text_margins(self):
        right_space = self.TOGGLE_BTN_SIZE + self.TOGGLE_MARGIN_RIGHT + 4
        self.setTextMargins(12, 0, right_space, 0)

    def _refresh_toggle_icon(self):
        self._toggle_btn.setIcon(self.build_visibility_icon(self._password_visible))
        self._toggle_btn.setIconSize(QSize(self.TOGGLE_ICON_SIZE, self.TOGGLE_ICON_SIZE))
        tooltip = "مخفی کردن" if self._password_visible else "نمایش"
        custom = getattr(self, "_toggle_tooltip_base", None)
        if custom:
            tooltip = f"{tooltip} {custom}"
        else:
            tooltip = "مخفی کردن رمز" if self._password_visible else "نمایش رمز"
        self._toggle_btn.setToolTip(tooltip)

    def set_toggle_tooltip_base(self, label: str):
        """مثلاً «کلید API» برای Consumer Key/Secret."""
        self._toggle_tooltip_base = (label or "").strip()
        self._refresh_toggle_icon()

    def _toggle_visibility(self):
        self._password_visible = not self._password_visible
        self.setEchoMode(QLineEdit.Normal if self._password_visible else QLineEdit.Password)
        self._refresh_toggle_icon()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_toggle()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_toggle()

    def _position_toggle(self):
        side = self.TOGGLE_BTN_SIZE
        self._toggle_btn.setFixedSize(side, side)
        x = max(0, self.width() - side - self.TOGGLE_MARGIN_RIGHT)
        y = max(0, (self.height() - side) // 2)
        self._toggle_btn.move(x, y)
        self._toggle_btn.raise_()
