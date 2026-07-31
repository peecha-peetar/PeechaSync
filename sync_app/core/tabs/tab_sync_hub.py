"""
تب گروهی «همگام‌سازی» — دسته‌بندی‌ها، ویژگی‌ها، محصولات، متغیرها، مشتریان
و سفارشات را به‌صورت زیرتب داخل یک تب اصلی نشان می‌دهد تا فهرست تب‌های
برنامه شلوغ نشود. هر کلاس اصلی بدون تغییر و مستقل باقی می‌ماند — این فایل
فقط آن‌ها را در یک QTabWidget کنار هم می‌گذارد.

نکته‌ی مهم سازگاری: چون کد دیگری در peecha_launcher.py (مثل
_link_tab_dependencies و reload_sql_dependent_tabs) مستقیماً به
self.category_tab / self.product_tab / ... رجوع می‌کند، این تب متد
get_sub_tab_refs() را دارد تا peecha_launcher بتواند بعد از ساخت این
تب گروهی، همان ارجاعات قبلی را دقیقاً مثل قبل روی self تنظیم کند —
یعنی هیچ کد دیگری در برنامه نیازی به تغییر ندارد.
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import Qt

from sync_app.core.adaptive_tab_bar import AdaptiveTabBar
from sync_app.core.product_mode import is_simple_only
from sync_app.core.tabs.tab_categories import CategoryTab
from sync_app.core.tabs.tab_category_brand_studio import CategoryBrandStudioTab
from sync_app.core.tabs.tab_properties import PropertiesTab
from sync_app.core.tabs.tab_products import ProductTab
from sync_app.core.tabs.tab_variations import VariationsTab
from sync_app.core.tabs.tab_customers import CustomerTab
from sync_app.core.tabs.tab_orders import OrderTab


class SyncHubTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.sub_tabs = QTabWidget()
        self.sub_tabs.setLayoutDirection(Qt.RightToLeft)
        self.sub_tabs.setTabBar(AdaptiveTabBar(self.sub_tabs))
        self.sub_tabs.tabBar().setObjectName("hubSubTabBar")

        self.category_tab = CategoryTab()
        self.properties_tab = PropertiesTab()
        self.product_tab = ProductTab()
        self.variation_tab = VariationsTab()
        self.customer_tab = CustomerTab()
        self.order_tab = OrderTab()
        self.category_brand_studio_tab = CategoryBrandStudioTab(product_tab_ref=self.product_tab)

        # اگه فروشگاه فقط محصول ساده داره (بدون ویژگی/متغیر)، این دو زیرتب
        # رو اصلاً نشون نده — نمونه‌شون همچنان ساخته می‌شه (برای سازگاری با
        # کدی که به self.properties_tab/self.variation_tab رجوع می‌کنه)،
        # فقط به این QTabWidget قابل‌مشاهده اضافه نمی‌شن.
        simple_only = is_simple_only()

        self.sub_tabs.addTab(self.category_tab, "📂 دسته‌بندی‌ها")
        if not simple_only:
            self.sub_tabs.addTab(self.properties_tab, "🎯 ویژگی‌ها")
        self.sub_tabs.addTab(self.product_tab, "📦 محصولات")
        if not simple_only:
            self.sub_tabs.addTab(self.variation_tab, "🎨 متغیرها")
        self.sub_tabs.addTab(self.customer_tab, "👥 مشتریان")
        self.sub_tabs.addTab(self.order_tab, "🧾 سفارشات")
        self.sub_tabs.addTab(self.category_brand_studio_tab, "🏷️ دسته‌بندی و برند")

        layout.addWidget(self.sub_tabs)
        self.setLayout(layout)

    def get_sub_tab_refs(self) -> dict:
        """برای سازگاری با کدی که مستقیم self.category_tab/self.product_tab/... را می‌خواند."""
        return {
            "category_tab": self.category_tab,
            "properties_tab": self.properties_tab,
            "product_tab": self.product_tab,
            "variation_tab": self.variation_tab,
            "customer_tab": self.customer_tab,
            "order_tab": self.order_tab,
            "category_brand_studio_tab": self.category_brand_studio_tab,
        }

    def select_sub_tab(self, attr_name: str) -> bool:
        """رفتن به یکی از زیرتب‌ها با نام ویژگی (مثلاً «product_tab»). خروجی: پیدا شد یا نه."""
        mapping = {
            "category_tab": self.category_tab,
            "properties_tab": self.properties_tab,
            "product_tab": self.product_tab,
            "variation_tab": self.variation_tab,
            "customer_tab": self.customer_tab,
            "order_tab": self.order_tab,
            "category_brand_studio_tab": self.category_brand_studio_tab,
        }
        widget = mapping.get(attr_name)
        if widget is None:
            return False
        idx = self.sub_tabs.indexOf(widget)
        if idx < 0:
            return False
        self.sub_tabs.setCurrentIndex(idx)
        return True

    def select_sub_tab_by_keyword(self, keyword: str) -> bool:
        """رفتن به یکی از زیرتب‌ها با جستجوی متن عنوان (برای دکمه‌های میانبر تب شروع)."""
        for i in range(self.sub_tabs.count()):
            if keyword in self.sub_tabs.tabText(i):
                self.sub_tabs.setCurrentIndex(i)
                return True
        return False
