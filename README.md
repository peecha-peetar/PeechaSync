PeechaSync — همگام‌سازی ERP با WooCommerce (ویندوز)
نسخه 2.3.0

اجرا روی سیستم توسعه
- پایتون 3.11 یا 3.12
- run.bat (اولین بار .venv می‌سازد)
- تب تنظیمات: SQL و WooCommerce را وصل کن

نصب آفلاین برای کاربر
مسیر release\installer\templates
Install PeechaSync.bat — گزینه ۱ نصب، ۲ عیب‌یابی
جزئیات: release\installer\templates\README.txt

ساخت بسته نصب
tools\Run_Build_SetupPackage.bat

انتشار نسخه‌ی جدید (کد + GitHub + سایت)
RELEASE_GUIDE.md را ببینید — یک دستور: tools\Run_Release_All.bat

دیتابیس ERP
فایل MDF/LDF را جدا نگه دار (داخل مخزن نیست).
اتصال از تب تنظیمات -> Attach

افزونه لایسنس وردپرس
wordpress-plugin\peecha-license-manager

فایل‌های نگاشت (بعد از اولین اجرا ساخته می‌شوند)
product_woo_map.json، category_map.json و پوشه‌های تصاویر

لاگ برنامه
%LOCALAPPDATA%\PeechaSync\

https://peecha.ir

---

PeechaSync — ERP to WooCommerce sync (Windows)
Version 2.3.0

Dev setup: Python 3.11/3.12, run run.bat, configure SQL + Woo in Settings.

Offline installer: release\installer\templates\Install PeechaSync.bat
Build setup ZIP: tools\Run_Build_SetupPackage.bat

WordPress license plugin: wordpress-plugin\peecha-license-manager
Logs: %LOCALAPPDATA%\PeechaSync\

https://peecha.ir
