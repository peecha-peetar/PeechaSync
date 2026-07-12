"""
تب گروهی «دستیار هوشمند» — مرکز رسانه، انتشار هوشمند، سئو و سلامت سایت،
مدیریت بازاریابی و مشاور پیچا را به‌صورت زیرتب داخل یک تب اصلی نشان می‌دهد.
هر کلاس اصلی بدون تغییر و مستقل باقی می‌ماند — این فایل فقط آن‌ها را در
یک QTabWidget کنار هم می‌گذارد.

نکته‌ی مهم: قبلاً «مرکز رسانه» و «Smart Publish» از طریق یک تب واسط
(MediaHubTab) اینجا می‌آمدند که خودش هم یک زیرتب به‌نام «مرکز رسانه»
داشت — یعنی لیبل «مرکز رسانه» دوبار تکرار می‌شد. برای همین اینجا هردو
مستقیم (بدون واسط) به‌عنوان زیرتب مجزا اضافه شدن.

نکته‌ی سازگاری: get_sub_tab_refs() برای اینکه peecha_launcher.py بتونه
self.media_center_tab / self.smart_publish_tab / ... رو دقیقاً مثل قبل
تنظیم کنه.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import Qt

from sync_app.core.adaptive_tab_bar import AdaptiveTabBar
from sync_app.core.tabs.tab_media_center import MediaCenterTab
from sync_app.core.tabs.tab_smart_publish import SmartPublishSettingsTab
from sync_app.core.tabs.tab_seo_health import SeoHealthTab
from sync_app.core.tabs.tab_marketing import MarketingTab
from sync_app.core.tabs.tab_peecha_advisor import PeechaAdvisorTab


class SmartAssistantHubTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.sub_tabs = QTabWidget()
        self.sub_tabs.setLayoutDirection(Qt.RightToLeft)
        self.sub_tabs.setTabBar(AdaptiveTabBar(self.sub_tabs))
        self.sub_tabs.tabBar().setObjectName("hubSubTabBar")

        self.media_center_tab = MediaCenterTab()
        self.smart_publish_tab = SmartPublishSettingsTab()
        self.seo_health_tab = SeoHealthTab()
        self.marketing_tab = MarketingTab()
        self.peecha_advisor_tab = PeechaAdvisorTab()

        self.sub_tabs.addTab(self.media_center_tab, "🖼️ مرکز رسانه")
        self.sub_tabs.addTab(self.smart_publish_tab, "✨ انتشار هوشمند")
        self.sub_tabs.addTab(self.seo_health_tab, "🩺 سئو و سلامت سایت")
        self.sub_tabs.addTab(self.marketing_tab, "📈 مدیریت بازاریابی")
        self.sub_tabs.addTab(self.peecha_advisor_tab, "🧭 مشاور پیچا")

        layout.addWidget(self.sub_tabs)
        self.setLayout(layout)

    def get_sub_tab_refs(self) -> dict:
        return {
            "media_center_tab": self.media_center_tab,
            "smart_publish_tab": self.smart_publish_tab,
            "seo_health_tab": self.seo_health_tab,
            "marketing_tab": self.marketing_tab,
            "peecha_advisor_tab": self.peecha_advisor_tab,
        }

    def select_sub_tab(self, attr_name: str) -> bool:
        mapping = self.get_sub_tab_refs()
        widget = mapping.get(attr_name)
        if widget is None:
            return False
        idx = self.sub_tabs.indexOf(widget)
        if idx < 0:
            return False
        self.sub_tabs.setCurrentIndex(idx)
        return True

    def select_sub_tab_by_keyword(self, keyword: str) -> bool:
        for i in range(self.sub_tabs.count()):
            if keyword in self.sub_tabs.tabText(i):
                self.sub_tabs.setCurrentIndex(i)
                return True
        return False
