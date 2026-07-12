import os
import sys
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal, QTimer, QPoint
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QFrame,
)
from PyQt5.QtGui import QPixmap, QPainter, QFont, QColor, QLinearGradient, QIcon
from sync_app.core.password_line_edit import PasswordLineEdit


def _login_resource_path(filename):
    """مسیر داینامیک برای EXE و سورس (همان مسیر لوگوی هدر برنامه)"""
    from sync_app.core.sync_utils import resource_path

    return resource_path(filename)


class ConnectivityWorker(QObject):
    finished = pyqtSignal(bool, str, bool, str)

    def __init__(self, config, mode="all", *, fast=False):
        super().__init__()
        self.config = config or {}
        self.mode = (mode or "all").strip().lower()
        self.fast = bool(fast)

    def run(self):
        from sync_app.core.connectivity_service import (
            load_connectivity_cache,
            probe_all,
            probe_sql,
            probe_wc,
            save_connectivity_cache,
        )

        if self.mode == "wc":
            cache = load_connectivity_cache(self.config)
            sql_ok = bool(cache.get("sql_ok", False))
            sql_msg = str(cache.get("sql_msg") or "")
            sql_ms = float(cache.get("sql_ms") or 0)
            wc_ok, wc_msg, wc_ms = probe_wc(self.config, attempts=1 if self.fast else 2, fast=self.fast)
            save_connectivity_cache(
                sql_ok, sql_msg, wc_ok, wc_msg, sql_ms=sql_ms, wc_ms=wc_ms
            )
            self.finished.emit(sql_ok, sql_msg, wc_ok, wc_msg)
            return

        if self.mode == "sql":
            cache = load_connectivity_cache(self.config)
            wc_ok = bool(cache.get("wc_ok", False))
            wc_msg = str(cache.get("wc_msg") or "")
            wc_ms = float(cache.get("wc_ms") or 0)
            sql_ok, sql_msg, sql_ms = probe_sql(self.config)
            save_connectivity_cache(
                sql_ok, sql_msg, wc_ok, wc_msg, sql_ms=sql_ms, wc_ms=wc_ms
            )
            self.finished.emit(sql_ok, sql_msg, wc_ok, wc_msg)
            return

        result = probe_all(self.config)
        self.finished.emit(
            result["sql_ok"],
            result["sql_msg"],
            result["wc_ok"],
            result["wc_msg"],
        )


class LoginWindow(QDialog):
    def __init__(self, config, on_login_success=None):
        super().__init__()
        self.config = config or {}
        self.on_login_success = on_login_success
        self._check_thread = None
        self._check_worker = None
        self._drag_position = None

        self.setWindowTitle("ورود به نرم افزار پیچا")
        from sync_app.core.brand_assets import apply_brand_window_icon

        apply_brand_window_icon(self)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(460, 610)
        if sys.platform == "win32":
            self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        else:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
            self.setAttribute(Qt.WA_TranslucentBackground)

        self._init_ui()
        QTimer.singleShot(1500, self.refresh_connectivity_status)

    def _init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: transparent;
            }
            QFrame#card {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1e1b4b, stop:0.5 #1a1035, stop:1 #0f0a1e);
                border: 1.5px solid rgba(99, 102, 241, 0.6);
                border-radius: 24px;
            }
            QLabel {
                background: transparent;
                color: #d1d5db;
            }
            QLabel#title {
                color: #ffffff;
                font-size: 20px;
                font-weight: 800;
            }
            QLabel#subtitle {
                color: #818cf8;
                font-size: 11px;
                font-weight: 500;
            }
            QLabel#fieldLabel {
                color: #a5b4fc;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#statusLabel {
                color: #6b7280;
                font-size: 10px;
            }
            QLineEdit {
                background-color: rgba(15, 20, 40, 0.85);
                border: 1px solid rgba(99, 102, 241, 0.35);
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 13px;
                color: #e5e7eb;
                selection-background-color: #4f46e5;
            }
            QLineEdit:focus {
                border: 1.5px solid #818cf8;
                background-color: rgba(10, 12, 30, 0.95);
            }
            QPushButton#loginBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4f46e5, stop:1 #7c3aed);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
                padding: 11px;
                letter-spacing: 1px;
            }
            QPushButton#loginBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4338ca, stop:1 #6d28d9);
            }
            QPushButton#loginBtn:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3730a3, stop:1 #581c87);
            }
            QPushButton#refreshBtn {
                background-color: transparent;
                color: #6366f1;
                border: 1px solid rgba(99, 102, 241, 0.4);
                border-radius: 8px;
                font-size: 10px;
                font-weight: 600;
                padding: 7px;
            }
            QPushButton#refreshBtn:hover {
                background-color: rgba(79, 70, 229, 0.12);
                color: #a5b4fc;
                border-color: rgba(99, 102, 241, 0.7);
            }
            QPushButton#closeBtn {
                background-color: transparent;
                color: rgba(129, 140, 248, 0.6);
                border: none;
                font-size: 18px;
                min-width: 28px;
                min-height: 28px;
                border-radius: 14px;
            }
            QPushButton#closeBtn:hover {
                background-color: rgba(239, 68, 68, 0.2);
                color: #f87171;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(0)
        root.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 12, 32, 20)
        card_layout.setSpacing(0)

        # ردیف بالا: دکمه بستن
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addStretch()
        self.close_btn = QPushButton("\u00d7")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setAutoDefault(False)
        self.close_btn.setDefault(False)
        self.close_btn.clicked.connect(self.reject)
        top_row.addWidget(self.close_btn)
        card_layout.addLayout(top_row)

        # لوگو
        logo_container = QLabel()
        logo_container.setAlignment(Qt.AlignCenter)
        logo_container.setFixedHeight(80)
        logo_container.setContentsMargins(0, 0, 0, 0)
        logo_container.setStyleSheet("background: transparent;")
        from sync_app.core.brand_assets import brand_logo_pixmap

        pixmap = brand_logo_pixmap(72, light_background=True)
        if not pixmap.isNull():
            logo_container.setPixmap(pixmap)
        else:
            logo_container.setPixmap(self._generate_gradient_logo())
        card_layout.addWidget(logo_container)
        card_layout.addSpacing(6)

        # عنوان
        title = QLabel("\u067e\u06cc\u0686\u0627")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("background: transparent; margin: 0; padding: 0;")
        card_layout.addWidget(title)
        card_layout.addSpacing(4)

        # زیرعنوان
        subtitle = QLabel("\u0647\u0645\u06af\u0627\u0645\u200c\u0633\u0627\u0632\u06cc \u0647\u0648\u0634\u0645\u0646\u062f \u0641\u0631\u0648\u0634\u06af\u0627\u0647")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("background: transparent; margin: 0; padding: 0;")
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(14)

        # خط جداکننده
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(99, 102, 241, 0.2); border: none; margin: 0 8px;")
        card_layout.addWidget(divider)
        card_layout.addSpacing(12)

        # نام کاربری
        lbl_user = QLabel("\u0646\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631\u06cc")
        lbl_user.setObjectName("fieldLabel")
        lbl_user.setAlignment(Qt.AlignRight)
        lbl_user.setStyleSheet("background: transparent; margin: 0; padding: 0;")
        card_layout.addWidget(lbl_user)
        card_layout.addSpacing(5)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("\u0646\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631\u06cc \u062e\u0648\u062f \u0631\u0627 \u0648\u0627\u0631\u062f \u06a9\u0646\u06cc\u062f")
        from sync_app.core.user_profile import load_last_profile_id

        prefill = (
            load_last_profile_id()
            or (self.config.get("APP_LOGIN_USERNAME") or "").strip()
            or "admin"
        )
        self.username_input.setText(prefill)
        self.username_input.setFixedHeight(42)
        self.username_input.returnPressed.connect(self.try_login)
        card_layout.addWidget(self.username_input)
        card_layout.addSpacing(10)

        # رمز عبور
        lbl_pass = QLabel("\u0631\u0645\u0632 \u0639\u0628\u0648\u0631")
        lbl_pass.setObjectName("fieldLabel")
        lbl_pass.setAlignment(Qt.AlignRight)
        lbl_pass.setStyleSheet("background: transparent; margin: 0; padding: 0;")
        card_layout.addWidget(lbl_pass)
        card_layout.addSpacing(5)

        self.password_input = PasswordLineEdit()
        self.password_input.set_toggle_dark_theme(True)
        self.password_input.setPlaceholderText("\u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u062e\u0648\u062f \u0631\u0627 \u0648\u0627\u0631\u062f \u06a9\u0646\u06cc\u062f")
        self.password_input.setFixedHeight(42)
        self.password_input.returnPressed.connect(self.try_login)
        card_layout.addWidget(self.password_input)
        card_layout.addSpacing(14)

        # دکمه ورود
        self.login_btn = QPushButton("\u2192  \u0648\u0631\u0648\u062f")
        self.login_btn.setObjectName("loginBtn")
        self.login_btn.setDefault(True)
        self.login_btn.setAutoDefault(True)
        self.login_btn.setFixedHeight(44)
        self.login_btn.clicked.connect(self.try_login)
        card_layout.addWidget(self.login_btn)
        card_layout.addSpacing(10)

        # وضعیت اتصالات
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        self.sql_status = QLabel("\U0001f535 SQL")
        self.sql_status.setObjectName("statusLabel")
        self.sql_status.setAlignment(Qt.AlignCenter)
        self.sql_status.setStyleSheet("background: transparent; color: #6b7280; font-size: 10px;")
        self.wc_status = QLabel("\U0001f535 WooCommerce")
        self.wc_status.setObjectName("statusLabel")
        self.wc_status.setAlignment(Qt.AlignCenter)
        self.wc_status.setStyleSheet("background: transparent; color: #6b7280; font-size: 10px;")
        status_row.addWidget(self.wc_status)
        status_row.addWidget(self.sql_status)
        card_layout.addLayout(status_row)
        card_layout.addSpacing(3)

        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        self.details_label.setObjectName("statusLabel")
        self.details_label.setAlignment(Qt.AlignCenter)
        self.details_label.setStyleSheet("background: transparent; margin: 0; padding: 0; font-size: 9px; color: #6b7280;")
        self.details_label.setMaximumHeight(32)
        card_layout.addWidget(self.details_label)
        card_layout.addSpacing(6)

        # دکمه بازبینی
        self.refresh_btn = QPushButton("\U0001f504 \u0628\u0627\u0632\u0628\u06cc\u0646\u06cc \u0627\u062a\u0635\u0627\u0644\u0627\u062a")
        self.refresh_btn.setObjectName("refreshBtn")
        self.refresh_btn.setFixedHeight(34)
        self.refresh_btn.clicked.connect(self.refresh_connectivity_status)
        card_layout.addWidget(self.refresh_btn)

        root.addWidget(card)

    def _generate_gradient_logo(self):
        """تولید لوگو رنگی gradient"""
        size = 80
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0, QColor(79, 70, 229))     # Indigo
        gradient.setColorAt(1, QColor(139, 92, 246))    # Purple

        painter.setBrush(gradient)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, size, size)

        painter.setPen(Qt.white)
        painter.setFont(QFont("Arial", 32, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "P")

        painter.end()
        return pixmap

    def refresh_connectivity_status(self):
        if self._check_thread is not None:
            return

        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("درحال بررسی...")
        self.details_label.setText("")

        from sync_app.core.user_profile import activate_profile, load_secure_config_after_profile

        username = (self.username_input.text() or "").strip() or "admin"
        activate_profile(username)
        probe_config = load_secure_config_after_profile() or self.config

        self._check_thread = QThread(self)
        self._check_worker = ConnectivityWorker(probe_config)
        self._check_worker.moveToThread(self._check_thread)
        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.finished.connect(self._on_connectivity_finished)
        self._check_worker.finished.connect(self._check_thread.quit)
        self._check_worker.finished.connect(self._check_worker.deleteLater)
        self._check_thread.finished.connect(self._check_thread.deleteLater)
        self._check_thread.finished.connect(self._on_connectivity_thread_finished)
        self._check_thread.start()

    def _on_connectivity_finished(self, sql_ok, sql_msg, wc_ok, wc_msg):
        if sql_ok:
            self.sql_status.setText("🟢 SQL")
            self.sql_status.setStyleSheet("color: #4ade80; font-size: 10px; font-weight: 600;")
        else:
            self.sql_status.setText("🔴 SQL")
            self.sql_status.setStyleSheet("color: #f87171; font-size: 10px; font-weight: 600;")

        if wc_ok:
            self.wc_status.setText("🟢 WooCommerce")
            self.wc_status.setStyleSheet("color: #4ade80; font-size: 10px; font-weight: 600;")
        else:
            self.wc_status.setText("🔴 WooCommerce")
            self.wc_status.setStyleSheet("color: #f87171; font-size: 10px; font-weight: 600;")

        if not sql_ok or not wc_ok:
            short_msg = []
            if not sql_ok:
                short_msg.append(sql_msg[:50])
            if not wc_ok:
                short_msg.append(wc_msg[:50])
            self.details_label.setText("\n".join(short_msg))

    def _on_connectivity_thread_finished(self):
        self._check_thread = None
        self._check_worker = None
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("بازبینی وضعیت")

    def try_login(self):
        from sync_app.core.user_profile import (
            activate_profile,
            initialize_new_profile_config,
            load_secure_config_after_profile,
            save_last_profile_id,
        )

        entered_user = (self.username_input.text() or "").strip()
        entered_pass = self.password_input.text() or ""

        if not entered_user:
            QMessageBox.warning(self, "خطا", "نام کاربری را وارد کنید.")
            return

        activate_profile(entered_user)
        cfg = load_secure_config_after_profile()

        if not cfg.get("APP_LOGIN_PASSWORD"):
            initialize_new_profile_config(entered_user, entered_pass or "123456")
        else:
            expected_user = (cfg.get("APP_LOGIN_USERNAME") or entered_user).strip()
            expected_pass = str(cfg.get("APP_LOGIN_PASSWORD") or "")
            if entered_user != expected_user or entered_pass != expected_pass:
                QMessageBox.warning(self, "خطا", "نام کاربری یا رمز عبور اشتباه است.")
                return

        save_last_profile_id(entered_user)
        if callable(self.on_login_success):
            self.on_login_success()
        self.accept()

    def closeEvent(self, event):
        if self._check_thread is not None and self._check_thread.isRunning():
            self._check_thread.quit()
            self._check_thread.wait()
        event.accept()

    def mousePressEvent(self, event):
        """شروع drag فرم"""
        if event.button() == Qt.LeftButton:
            self._drag_position = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        """جابجایی فرم هنگام drag"""
        if event.buttons() == Qt.LeftButton and self._drag_position is not None:
            self.move(event.globalPos() - self._drag_position)
