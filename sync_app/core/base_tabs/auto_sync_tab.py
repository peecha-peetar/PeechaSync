# auto sync tab (legacy — use sync_app.core.tabs.tab_auto_sync)

import subprocess
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QComboBox, QLabel, QTextEdit, QMessageBox
)
from PyQt5.QtCore import QTimer, Qt
from sync_app.core.jalali_log_formatter import format_log_lines_jalali

LOG_FILE = "sync.log"
BRAND_COLOR = "#020025"

class AutoSyncTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)

        self.scripts = [
            "ProductCategoriesSync.py",
            "Poshakproperties.py",
            "sync_fullproduct.py",
            "update_variations.py",
            "customersync.py",
            "ordersync.py",
        ]

        self.checkboxes = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.run_auto)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # scripts checkbox
        for script in self.scripts:
            cb = QCheckBox(script)
            cb.setChecked(False)
            self.checkboxes.append(cb)
            layout.addWidget(cb)

        # interval
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("⏱ فاصله زمانی اجرای اتوماتیک:"))
        self.interval_box = QComboBox()
        self.interval_box.addItems(["5 دقیقه", "10 دقیقه", "30 دقیقه"])
        interval_layout.addWidget(self.interval_box)
        layout.addLayout(interval_layout)

        # buttons
        btn_layout = QHBoxLayout()

        manual_btn = QPushButton("🔄 اجرای دستی")
        manual_btn.setStyleSheet(f"background-color:{BRAND_COLOR}; color:white; font-weight:bold;")
        manual_btn.clicked.connect(self.run_manual)
        btn_layout.addWidget(manual_btn)

        start_auto_btn = QPushButton("▶️ شروع اتوماتیک")
        start_auto_btn.clicked.connect(self.start_auto)
        btn_layout.addWidget(start_auto_btn)

        stop_auto_btn = QPushButton("⏹ توقف اتوماتیک")
        stop_auto_btn.clicked.connect(self.stop_auto)
        btn_layout.addWidget(stop_auto_btn)

        layout.addLayout(btn_layout)

        # status + log
        self.status_label = QLabel("وضعیت: آماده")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        layout.addWidget(self.status_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setAlignment(Qt.AlignRight)
        self.log_view.setStyleSheet("background-color:#f8f9fa; font-family:Consolas; font-size:10pt;")
        layout.addWidget(self.log_view)

        self.setLayout(layout)
        self.refresh_logs()

    # manual
        selected = [cb.text() for cb in self.checkboxes if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "هشدار", "هیچ اسکریپتی انتخاب نشده.")
            return
        for script in selected:
            self.run_script(script)
        self.refresh_logs()

    # start auto
    def start_auto(self):
        text = self.interval_box.currentText()
        if "5" in text:
            interval = 5 * 60 * 1000
        elif "10" in text:
            interval = 10 * 60 * 1000
        else:
            interval = 30 * 60 * 1000
        self.timer.start(interval)
        self.status_label.setText("▶️ اجرای اتوماتیک فعال شد.")
        self.status_label.setStyleSheet("color: orange; font-weight: bold;")

    def stop_auto(self):
        self.timer.stop()
        self.status_label.setText("⏹ اجرای اتوماتیک متوقف شد.")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

    # auto run
    def run_auto(self):
        selected = [cb.text() for cb in self.checkboxes if cb.isChecked()]
        for script in selected:
            self.run_script(script)
        self.refresh_logs()

    # run one script
    def run_script(self, script_name):
        try:
            subprocess.run(["python", script_name], check=True)
            self.status_label.setText(f"✅ اجرا شد: {script_name}")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        except Exception as e:
            self.status_label.setText(f"❌ خطا در اجرای {script_name}: {e}")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")

    def refresh_logs(self):
        try:
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    self.log_view.setPlainText(format_log_lines_jalali(lines[-100:]))
                    self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
            else:
                self.log_view.setPlainText("فایل لاگ یافت نشد.")
        except Exception as e:
            self.log_view.setPlainText(f"خطا در خواندن لاگ: {e}")
