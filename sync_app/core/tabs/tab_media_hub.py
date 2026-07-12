"""
تب ترکیبی «مرکز رسانه» — مرکز رسانه (فاز ۱) و Smart Publish (فاز ۳) را
به‌صورت زیرتب داخل یک تب اصلی نشان می‌دهد تا تعداد تب‌های برنامه شلوغ نشود.
هر دو کلاس اصلی (MediaCenterTab, SmartPublishSettingsTab) بدون تغییر و
مستقل باقی می‌مانند — این فایل فقط آن‌ها را در یک QTabWidget کنار هم می‌گذارد.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import Qt

from sync_app.core.tabs.tab_media_center import MediaCenterTab
from sync_app.core.tabs.tab_smart_publish import SmartPublishSettingsTab


class MediaHubTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.sub_tabs = QTabWidget()
        self.sub_tabs.setLayoutDirection(Qt.RightToLeft)

        self.media_center_tab = MediaCenterTab()
        self.smart_publish_tab = SmartPublishSettingsTab()

        self.sub_tabs.addTab(self.media_center_tab, "🖼️ مرکز رسانه")
        self.sub_tabs.addTab(self.smart_publish_tab, "✨ Smart Publish")

        layout.addWidget(self.sub_tabs)
        self.setLayout(layout)
