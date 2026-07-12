from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton
from PyQt5.QtCore import Qt

from sync_app.core.jalali_log_formatter import format_log_lines_jalali
from sync_app.core.log_catalog import get_sync_log_path, read_sync_log_lines


class LogViewerTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.log_file_path = get_sync_log_path()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAlignment(Qt.AlignRight)
        layout.addWidget(self.log_view)

        refresh_button = QPushButton("🔄 بازخوانی لاگ‌ها")
        refresh_button.clicked.connect(self.refresh_logs)
        layout.addWidget(refresh_button)

        self.setLayout(layout)
        self.refresh_logs()

    def refresh_logs(self):
        self.log_file_path = get_sync_log_path()
        try:
            lines = read_sync_log_lines()
            if lines:
                self.log_view.setText(format_log_lines_jalali(lines))
            else:
                self.log_view.setText(
                    "هنوز لاگی ایجاد نشده است.\n"
                    "برای ایجاد لاگ، یکی از عملیات‌های همگام‌سازی را اجرا کنید."
                )
        except Exception as exc:
            self.log_view.setText(f"❌ خطا در خواندن لاگ‌ها: {exc}")
