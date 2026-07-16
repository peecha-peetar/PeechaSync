"""دیالوگ گزارش زنده عملیات SQL (بارگذاری، Attach، تست)"""
from datetime import datetime

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class SqlOperationLogDialog(QDialog):
    action_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sqlOperationLogDialog")
        self.setWindowTitle("گزارش عملیات SQL")
        self.setMinimumSize(620, 460)
        self.setLayoutDirection(Qt.RightToLeft)
        self._operation_blocking = False
        self._action_id = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._status_label = QLabel("آماده")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(
            "color: #1e3a8a; font-weight: 700; font-size: 13px; padding: 6px 8px;"
            "background: #eff6ff; border-radius: 8px;"
        )
        root.addWidget(self._status_label)

        self._hint_label = QLabel(
            "این پنجره مراحل پشت‌صحنه را نشان می‌دهد. می‌توانید با «بستن» آن را مخفی کنید."
        )
        self._hint_label.setWordWrap(True)
        self._hint_label.setStyleSheet("color: #64748b; font-size: 11px;")
        root.addWidget(self._hint_label)

        self._action_row = QHBoxLayout()
        self._action_row.setSpacing(8)
        self._action_hint = QLabel("")
        self._action_hint.setWordWrap(True)
        self._action_hint.setStyleSheet(
            "color: #9a3412; font-size: 12px; font-weight: 600; padding: 4px 2px;"
        )
        self._action_btn = QPushButton("")
        self._action_btn.setMinimumHeight(40)
        self._action_btn.setStyleSheet(
            "background-color: #ea580c; color: white; border-radius: 8px; "
            "padding: 8px 14px; font-weight: 700; font-size: 12px;"
        )
        self._action_btn.clicked.connect(self._on_action_clicked)
        self._action_row.addWidget(self._action_hint, 1)
        self._action_row.addWidget(self._action_btn)
        root.addLayout(self._action_row)
        self._hide_action_row()

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setObjectName("log_view")
        self._log_view.setLayoutDirection(Qt.LeftToRight)
        self._log_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._log_view.document().setMaximumBlockCount(800)
        self._log_view.setFont(QFont("Consolas", 10))
        self._log_view.setPlaceholderText("گزارش عملیات اینجا ظاهر می‌شود...")
        root.addWidget(self._log_view, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._copy_btn = QPushButton("کپی لاگ")
        self._copy_btn.clicked.connect(self.copy_logs)
        btn_row.addWidget(self._copy_btn)

        clear_btn = QPushButton("پاکسازی")
        clear_btn.setFlat(True)
        clear_btn.clicked.connect(self.clear_logs)
        btn_row.addWidget(clear_btn)

        btn_row.addStretch()

        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(self.hide)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)
        self._apply_window_mode()

    def _hide_action_row(self):
        self._action_id = ""
        self._action_hint.setText("")
        self._action_btn.setText("")
        self._action_btn.setVisible(False)
        self._action_hint.setVisible(False)

    def show_action(self, action_id: str, label: str, hint: str = ""):
        self._action_id = (action_id or "").strip()
        self._action_btn.setText(label or "اقدام")
        self._action_hint.setText(hint or "")
        self._action_btn.setVisible(bool(self._action_id))
        self._action_hint.setVisible(bool(hint))
        self.raise_()

    def hide_action(self):
        self._hide_action_row()

    def _on_action_clicked(self):
        if not self._action_id:
            return
        self.action_requested.emit(self._action_id)

    def _apply_window_mode(self):
        was_visible = self.isVisible()
        if was_visible:
            self.hide()

        if self._operation_blocking:
            self.setWindowModality(Qt.ApplicationModal)
            self.setWindowFlags(
                Qt.Dialog
                | Qt.WindowTitleHint
                | Qt.WindowCloseButtonHint
            )
            self._hint_label.setText(
                "لطفاً تا پایان عملیات صبر کنید — تنظیمات تا بستن این پنجره قابل تغییر نیست."
            )
        else:
            self.setWindowModality(Qt.NonModal)
            self.setWindowFlags(
                Qt.Dialog
                | Qt.WindowTitleHint
                | Qt.WindowCloseButtonHint
                | Qt.WindowMinimizeButtonHint
            )
            self._hint_label.setText(
                "این پنجره مراحل پشت‌صحنه را نشان می‌دهد. می‌توانید با «بستن» آن را مخفی کنید."
            )

        if was_visible:
            self.show()

    def set_operation_blocking(self, blocking: bool):
        if self._operation_blocking == bool(blocking):
            return
        self._operation_blocking = bool(blocking)
        self._apply_window_mode()

    def begin_operation(self, title: str, *, clear: bool = True):
        from sync_app.core.app_version import APP_VERSION

        already_open = self.isVisible() and self._operation_blocking
        if clear and not already_open:
            self._log_view.clear()
        self.setWindowTitle(f"{title} — {APP_VERSION}")
        self._status_label.setText(f"⏳ در حال اجرا — {title}")
        self._status_label.setStyleSheet(
            "color: #b45309; font-weight: 700; font-size: 13px; padding: 6px 8px;"
            "background: #fffbeb; border-radius: 8px;"
        )
        self.append_line(f"--- {title} ---")
        if not already_open:
            self.set_operation_blocking(True)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setWindowState(
            (self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive
        )

    def append_line(self, message: str):
        text = (message or "").strip()
        if not text:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"[{ts}] {text}")
        self._log_view.verticalScrollBar().setValue(
            self._log_view.verticalScrollBar().maximum()
        )

    def set_finished(self, ok: bool, summary: str):
        self.set_operation_blocking(False)
        if ok:
            self._status_label.setText(f"✅ {summary}")
            self._status_label.setStyleSheet(
                "color: #166534; font-weight: 700; font-size: 13px; padding: 6px 8px;"
                "background: #ecfdf5; border-radius: 8px;"
            )
            self.hide_action()
        else:
            self._status_label.setText(f"❌ {summary}")
            self._status_label.setStyleSheet(
                "color: #b91c1c; font-weight: 700; font-size: 13px; padding: 6px 8px;"
                "background: #fef2f2; border-radius: 8px;"
            )
        self.append_line(summary)
        self.raise_()
        self.activateWindow()

    def clear_logs(self):
        self._log_view.clear()
        self._status_label.setText("گزارش پاک شد")
        self.append_line("گزارش پاکسازی شد.")

    def copy_logs(self):
        text = self._log_view.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "کپی لاگ", "گزارشی برای کپی وجود ندارد.")
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            QMessageBox.warning(self, "کپی لاگ", "دسترسی به کلیپبورد میسر نشد.")
            return
        clipboard.setText(text)
        QMessageBox.information(self, "کپی لاگ", "گزارش در کلیپبورد کپی شد.")
