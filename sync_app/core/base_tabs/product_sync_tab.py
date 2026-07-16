import subprocess
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QTextEdit, QHBoxLayout, QComboBox
from PyQt5.QtCore import Qt
from secure_config_loader import load_secure_config, save_secure_config
import os
import sys
from sync_app.core.jalali_log_formatter import format_log_lines_jalali


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # exe
    except Exception:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


from sync_app.core.sync_utils import app_path


def get_log_path():
    return app_path("sync.log")


class ProductSyncTab(QWidget):
    def __init__(self, script_name, tab_title):
        super().__init__()
        self.script_name = script_name
        self.tab_title = tab_title
        self.setLayoutDirection(Qt.RightToLeft)

        try:
            self.config = load_secure_config(None)
        except:
            self.config = {}

        self.init_ui()

    def init_ui(self):
        base_layout = QVBoxLayout()

        price_layout = QHBoxLayout()
        price_label = QLabel("💰 لیست قیمت انتخابی:")
        self.price_list_combo = QComboBox()
        price_options = [f"لیست قیمت {i}" for i in range(1, 11)]
        self.price_list_combo.addItems(price_options)
        default_index = self.config.get("PRICE_LIST_INDEX", 0)
        self.price_list_combo.setCurrentIndex(default_index)
        price_layout.addWidget(price_label)
        price_layout.addWidget(self.price_list_combo)
        price_layout.addStretch()
        base_layout.addLayout(price_layout)

        self.status_label = QLabel("وضعیت: آماده")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        base_layout.addWidget(self.status_label)

        self.run_button = QPushButton(f"شروع همگام‌سازی {self.tab_title}")
        self.run_button.setStyleSheet("background-color: #020025; color: white; font-weight: bold;")
        self.run_button.clicked.connect(self.run_script)
        base_layout.addWidget(self.run_button)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAlignment(Qt.AlignRight)
        base_layout.addWidget(self.log_view)

        self.setLayout(base_layout)
        self.refresh_logs()

    def run_script(self):
        self.status_label.setText("وضعیت: در حال اجرا...")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

        try:
            selected_index = self.price_list_combo.currentIndex()
            list_number = selected_index + 1
            column_suffix = "" if list_number == 1 else str(list_number)
            column_name = f"Sel_Price{column_suffix}"

            config_to_save = load_secure_config(None)
            config_to_save["PRICE_LIST_COLUMN"] = column_name
            config_to_save["PRICE_LIST_INDEX"] = selected_index
            save_secure_config(config_to_save)

            from sync_app.core.sync_utils import resolve_runnable_script

            script_base = resource_path(os.path.join("scripts", os.path.basename(self.script_name)))
            script_path = resolve_runnable_script(
                os.path.dirname(script_base),
                os.path.basename(script_base),
            )

            subprocess.run([sys.executable, script_path], check=True)

            self.status_label.setText("✅ عملیات با موفقیت انجام شد.")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        except subprocess.CalledProcessError:
            self.status_label.setText("❌ خطا در اجرای اسکریپت.")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
        except Exception as e:
            self.status_label.setText(f"❌ خطا در ذخیره تنظیمات قیمت: {e}")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")

        self.refresh_logs()

    def refresh_logs(self):
        log_path = get_log_path()
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()[-10:]
                self.log_view.setText(format_log_lines_jalali(lines))
        except Exception as e:
            self.log_view.setText(f"❌ خطا در خواندن لاگ‌ها: {e}")
