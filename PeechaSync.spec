# -*- mode: python ; coding: utf-8 -*-
# Bytecode bundled inside one-file EXE (no .py shipped to customers).

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# پکیج‌های پردازش تصویر (مرکز رسانه) — پلاگین‌های PIL باید صراحتاً جمع‌آوری
# شوند، وگرنه PyInstaller خیلی از فرمت‌ها/HEIC را جا می‌اندازد.
_image_hidden = (
    collect_submodules("PIL")
    + collect_submodules("pillow_heif")
    + collect_submodules("imagehash")
    + collect_submodules("arabic_reshaper")
    + collect_submodules("openpyxl")
    + collect_submodules("bidi")
    + collect_submodules("qrcode")
)
_image_datas = collect_data_files("pillow_heif") + collect_data_files("arabic_reshaper")

a = Analysis(
    ['sync_app/core/peecha_launcher.py'],   # فایل اصلی لانچر
    pathex=[],
    binaries=[],
    datas=[
        ('sync_app/core/Peecha_logo.ico', '.'),
        ('sync_app/core/Peecha_logo_app.png', '.'),
        ('sync_app/core/Peecha_logo.png', '.'),
        ('sync_app/core/style.qss', '.'),
        ('sync_app/core/IRANSans.ttf', '.'),
        ('sync_app/core/license.json.example', '.'),
        ('sync_app/core/Peecha.gif', '.'),
        ('sync_app/core/mobile_pwa', 'mobile_pwa'),
    ] + _image_datas,
    hiddenimports=[
        # تب‌ها
        "sync_app.core.tabs.tab_home",
        "sync_app.core.tabs.tab_dashboard",
        "sync_app.core.tabs.tab_reconciliation",
        "sync_app.core.reconciliation_export",
        "sync_app.core.tabs.tab_categories",
        "sync_app.core.tabs.tab_properties",
        "sync_app.core.tabs.tab_products",
        "sync_app.core.tabs.tab_variations",
        "sync_app.core.tabs.tab_media_center",
        "sync_app.core.tabs.tab_media_hub",
        "sync_app.core.tabs.tab_seo_health",
        "sync_app.core.tabs.tab_sync_hub",
        "sync_app.core.tabs.tab_smart_assistant_hub",
        "sync_app.core.tabs.tab_articles",
        "sync_app.core.article_provider",
        "sync_app.core.article_seo_helper",
        "sync_app.core.wp_posts_helper",
        "sync_app.core.ps_cms_helper",
        "sync_app.core.adaptive_tab_bar",
        "sync_app.core.tabs.tab_marketing",
        "sync_app.core.tabs.tab_peecha_advisor",
        "sync_app.core.tabs.tab_smart_publish",
        "sync_app.core.tabs.tab_customers",
        "sync_app.core.tabs.tab_orders",
        "sync_app.core.tabs.tab_logs",
        "sync_app.core.tabs.tab_settings",
        "sync_app.core.tabs.tab_license",
        "sync_app.core.tabs.tab_auto_sync",
        "sync_app.core.login_window",
        "sync_app.core.user_profile",
        "sync_app.core.app_theme",
        "sync_app.core.reconciliation_service",
        "sync_app.core.reconciliation_link_guard",
        "sync_app.core.log_catalog",
        "sync_app.core.connectivity_service",

        # فایل‌های پایه
        "sync_app.core.secure_config_loader",
        "sync_app.core.sync_utils",
        "sync_app.core.wc_sync_helper",
        "sync_app.core.wc_api_helper",
        "sync_app.core.product_woo_map_helper",
        "sync_app.core.media_center",
        "sync_app.core.seo_helper",
        "sync_app.core.sales_report_helper",
        "sync_app.core.marketing_helper",
        "sync_app.core.site_health_helper",
        "sync_app.core.auto_sync_scope",
        "sync_app.core.content_studio_helper",
        "sync_app.core.smart_publish",

        # base_tabs
        "sync_app.core.base_tabs.sync_tab",
        "sync_app.core.base_tabs.log_viewer_tab",
        "sync_app.core.base_tabs.settings_tab",
        "sync_app.core.base_tabs.product_sync_tab",

        # اسکریپت‌ها
        "sync_app.core.scripts.ProductCategoriesSync",
        "sync_app.core.scripts.Poshakproperties",
        "sync_app.core.scripts.sync_fullproduct",
        "sync_app.core.scripts.update_variations",
        "sync_app.core.scripts.customersync",
        "sync_app.core.scripts.ordersync",
        "sync_app.core.scripts.woocommerce_store_setup",
    ] + _image_hidden,
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PeechaSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # اگر پنجرهٔ سیاه نمی‌خواهی False بگذار
    icon='sync_app/core/Peecha_logo.ico'  # اگر آیکون داری
)
