from PyQt5.QtCore import QObject, QVariantAnimation, QEasingCurve, Qt, QRect
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QPushButton, QSizePolicy, QStyleOptionButton, QStyle, QWidget, QVBoxLayout

LOG_PANEL_WIDTHS_KEY = "LOG_PANEL_WIDTHS"


def _load_log_panel_width(storage_key: str, default_width: int) -> int:
    try:
        from sync_app.core.secure_config_loader import load_secure_config

        cfg = load_secure_config(None) or {}
        widths = cfg.get(LOG_PANEL_WIDTHS_KEY) or {}
        if isinstance(widths, dict):
            raw = widths.get(storage_key)
            if raw is not None:
                width = int(raw)
                if width >= LogPanelController.LOG_MIN_OPEN:
                    return width
    except Exception:
        pass
    return default_width


def _save_log_panel_width(storage_key: str, width: int) -> None:
    try:
        from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

        cfg = load_secure_config(None) or {}
        widths = dict(cfg.get(LOG_PANEL_WIDTHS_KEY) or {})
        widths[storage_key] = int(width)
        cfg[LOG_PANEL_WIDTHS_KEY] = widths
        save_secure_config(cfg)
    except Exception:
        pass


class VerticalTextButton(QPushButton):
    """دکمه با متن عمودی واقعی (چرخش ۹۰ درجه)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumWidth(50)
        self.setMaximumWidth(50)
        self.setMinimumHeight(120)

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self.style().drawControl(QStyle.CE_PushButtonBevel, option, painter, self)

        painter.save()
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-90)

        text_rect = QRect(
            int(-self.height() / 2),
            int(-self.width() / 2),
            int(self.height()),
            int(self.width()),
        )
        painter.setPen(option.palette.buttonText().color())
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignCenter, self.text())
        painter.restore()


class LogActionRail(QWidget):
    """ریل عمودی دکمه‌های کنترل لاگ (نمایش/مخفی + حذف لاگ‌ها)"""

    def __init__(self, clear_text="حذف لاگ‌ها", parent=None):
        super().__init__(parent)
        self.setObjectName("logActionRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setFixedWidth(54)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 6, 2, 6)
        layout.setSpacing(8)

        self.toggle_button = VerticalTextButton(self)
        self.toggle_button.setFlat(True)
        self.toggle_button.setObjectName("logDockToggle")
        self.toggle_button.setCursor(Qt.PointingHandCursor)
        self.toggle_button.setProperty("logDockButton", True)
        self.toggle_button.setProperty("logDockRole", "toggle")
        self.toggle_button.setToolTip("نمایش یا مخفی‌سازی پنل لاگ")

        self.clear_button = VerticalTextButton(self)
        self.clear_button.setFlat(True)
        self.clear_button.setText(clear_text)
        self.clear_button.setObjectName("logDockClear")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.setProperty("logDockButton", True)
        self.clear_button.setProperty("logDockRole", "clear")
        self.clear_button.setToolTip("حذف لاگ‌های همین تب")

        layout.addWidget(self.toggle_button, 1)
        layout.addWidget(self.clear_button, 1)

    def bind_toggle(self, slot):
        self.toggle_button.clicked.connect(slot)

    def bind_clear(self, slot):
        self.clear_button.clicked.connect(slot)


class LogPanelController(QObject):
    """
    کنترل پنل لاگ:
    - قبل از بستن، عرض فعلی ذخیره می‌شود
    - با «نمایش لاگ» همان عرض قبلی برمی‌گردد
    """

    COLLAPSE_THRESHOLD = 40
    MIN_RIGHT_WIDTH = 160
    LOG_MIN_OPEN = 260

    def __init__(
        self,
        splitter,
        button,
        open_size=380,
        duration_ms=160,
        log_widget=None,
        storage_key="shared",
        parent=None,
    ):
        super().__init__(parent)
        self.splitter = splitter
        self.button = button
        self.log_widget = log_widget
        self.storage_key = str(storage_key or "shared")
        self.open_size = max(self.LOG_MIN_OPEN, int(open_size))
        self.duration_ms = max(80, int(duration_ms))
        self._is_open = False
        self._saved_open_width = _load_log_panel_width(self.storage_key, self.open_size)
        self._anim = None
        self._animating = False

        self.button.setObjectName("logDockToggle")
        self.button.setCursor(Qt.PointingHandCursor)

        self._configure_splitter()
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self._set_button_text(False)

    def _configure_splitter(self):
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(1, False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setHandleWidth(8)

    def _prepare_log_constraints(self, opening):
        if self.log_widget is None:
            return
        self.log_widget.setMinimumWidth(self.LOG_MIN_OPEN if opening else 0)

    def _read_open_state(self):
        sizes = self.splitter.sizes() or [0, 0]
        left = int(sizes[0])
        return left > self.COLLAPSE_THRESHOLD, left

    def _remember_open_width(self, left_width):
        width = max(int(left_width), self.LOG_MIN_OPEN)
        self._saved_open_width = width

    def _persist_saved_width(self):
        _save_log_panel_width(self.storage_key, self._saved_open_width)

    def _sync_ui_from_splitter(self):
        is_open, left = self._read_open_state()
        self._is_open = is_open
        self._prepare_log_constraints(is_open)
        self._set_button_text(is_open)
        if is_open:
            self._remember_open_width(left)

    def collapse_initial(self):
        self._stop_animation()
        self._prepare_log_constraints(False)
        self._apply_left_width(0, sync_button=True)
        self._is_open = False
        self._set_button_text(False)

    def expand_initial(self):
        self._stop_animation()
        is_open, left = self._read_open_state()
        if is_open:
            self._remember_open_width(left)
            self._sync_ui_from_splitter()
            return
        self._prepare_log_constraints(True)
        self._apply_left_width(self._saved_open_width, sync_button=True)

    def ensure_visible(self):
        is_open, left = self._read_open_state()
        if is_open and left > self.COLLAPSE_THRESHOLD:
            self._remember_open_width(left)
            self._sync_ui_from_splitter()
            return
        self._stop_animation()
        self._prepare_log_constraints(True)
        self._apply_left_width(self._saved_open_width, sync_button=True)

    def toggle(self):
        is_open, left = self._read_open_state()
        if is_open:
            self._remember_open_width(left)
            self._persist_saved_width()
        self._animate_to(not is_open)

    def _set_button_text(self, is_open):
        self.button.setText("مخفی کردن لاگ" if is_open else "نمایش لاگ")

    def _splitter_total_width(self):
        width = self.splitter.width()
        if width > 0:
            return width
        sizes = self.splitter.sizes() or [0, 0]
        total = sum(sizes)
        if total > 0:
            return total
        return self.open_size + 700

    def _apply_left_width(self, left, *, sync_button=False):
        total = self._splitter_total_width()
        opening = int(left) > self.COLLAPSE_THRESHOLD
        self._prepare_log_constraints(opening)

        max_left = max(0, total - self.MIN_RIGHT_WIDTH)
        left = max(0, min(int(left), max_left))
        right = max(self.MIN_RIGHT_WIDTH, total - left)
        if left + right != total and total > 0:
            right = total - left
        self.splitter.setSizes([left, right])
        if sync_button:
            self._sync_ui_from_splitter()

    def _stop_animation(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._animating = False

    def _on_splitter_moved(self, _pos, _index):
        if self._animating:
            return

        is_open, left = self._read_open_state()
        if self._is_open and left <= self.COLLAPSE_THRESHOLD:
            self._animating = True
            self._prepare_log_constraints(True)
            self._apply_left_width(self._saved_open_width)
            self._animating = False
            self._sync_ui_from_splitter()
            return

        if left > self.COLLAPSE_THRESHOLD:
            self._remember_open_width(left)
        self._sync_ui_from_splitter()

    def _animate_to(self, target_open):
        self._stop_animation()
        _, start_size = self._read_open_state()
        end_size = self._saved_open_width if target_open else 0

        if target_open:
            self._prepare_log_constraints(True)
        else:
            self._prepare_log_constraints(False)

        self._animating = True
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.duration_ms)
        self._anim.setStartValue(start_size)
        self._anim.setEndValue(end_size)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        def on_value_changed(value):
            self._apply_left_width(int(value))

        def on_finished():
            self._animating = False
            self._anim = None
            self._apply_left_width(end_size, sync_button=True)
            if target_open:
                self._remember_open_width(end_size)

        self._anim.valueChanged.connect(on_value_changed)
        self._anim.finished.connect(on_finished)
        self._anim.start()
