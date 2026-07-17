import logging
import sys
import os
import shutil

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QTabBar,
    QSystemTrayIcon, QMenu, QAction, QStyle, QFrame, QSizePolicy, QPushButton
)
from PyQt5.QtGui import QPixmap, QIcon, QFont, QFontMetrics, QFontDatabase, QLinearGradient, QColor, QPainter, QPalette
from PyQt5.QtCore import Qt, QSize, QThread, QTimer, QObject, pyqtSignal
from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.event_notifier import install_messagebox_logging
from sync_app.core.message_boxes_fa import install_persian_message_boxes
from sync_app.core.single_instance import SingleInstanceManager


# ---------------------------------------------------------
# مسیر داینامیک منابع (لوگو، qss، کانفیگ و ...)
# ---------------------------------------------------------
def resource_path(filename):
    """مسیر فایل‌های read-only (qss، لوگو، فونت) — در one-file EXE از _MEIPASS."""
    from sync_app.core.sync_utils import resource_path as _rp

    return _rp(filename)


# تنظیمات برند
LOGO_PATH = resource_path("Peecha_logo.png")
ICON_PATH = resource_path("Peecha_logo.ico")
BRAND_COLOR = "#020025"


def brand_icon() -> QIcon:
    from sync_app.core.brand_assets import brand_app_icon

    return brand_app_icon()


def apply_brand_window_icon(widget) -> None:
    from sync_app.core.brand_assets import apply_brand_window_icon as _apply

    _apply(widget)


def apply_windows_taskbar_branding() -> None:
    """آیکن taskbar ویندوز — جدا از pythonw.exe"""
    from sync_app.core.brand_assets import apply_windows_app_id

    apply_windows_app_id()


def _scale_brand_logo(pixmap: QPixmap, height: int) -> QPixmap:
    if pixmap is None or pixmap.isNull():
        return pixmap
    return pixmap.scaledToHeight(max(24, int(height)), Qt.SmoothTransformation)
FONT_FAMILY = "IranSans"

# حداقل ابعاد قابل‌قبول برای حالت موبایل افقی
MOBILE_LANDSCAPE_MIN_WIDTH = 640
MOBILE_LANDSCAPE_MIN_HEIGHT = 360
LAST_ACTIVE_TAB_KEY = "LAST_ACTIVE_TAB"
AUTO_RESTORE_LAST_TAB_KEY = "AUTO_RESTORE_LAST_TAB"
AUTO_UPDATE_ENABLED_KEY = "AUTO_UPDATE_ENABLED"
SKIP_RECON_STARTUP_PROMPT_KEY = "SKIP_RECON_STARTUP_PROMPT"
# عرض کافی برای نام دیتابیس ERP (مثلاً DejavuDB_14050302)
SQL_HEADER_MIN_WIDTH = 172


def resolve_user_font_pref(font_setting):
    """تبدیل مقدار ذخیره‌شده فونت به سایز و وضعیت ضخامت"""
    if str(font_setting) == "18bold":
        return 18, True
    try:
        return int(font_setting), False
    except Exception:
        return 14, False


def build_item_view_theme(surface, surface_alt, border, text, hover, selected, header_bg):
    return f"""
QListWidget, QTreeWidget, QTableWidget {{
    background-color: {surface};
    color: {text};
    border: 1px solid {border};
    alternate-background-color: {surface_alt};
}}
QListWidget::item, QTreeWidget::item, QTableWidget::item {{
    color: {text};
    background-color: transparent;
}}
QListWidget::item:hover, QTreeWidget::item:hover, QTableWidget::item:hover {{
    background-color: {hover};
    color: {text};
}}
QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
    background-color: {selected};
    color: #ffffff;
}}
QListView, QTreeView, QTableView, QAbstractItemView {{
    background-color: {surface};
    color: {text};
    alternate-background-color: {surface_alt};
    selection-background-color: {selected};
    selection-color: #ffffff;
    outline: none;
}}
QHeaderView::section {{
    background-color: {header_bg};
    color: {text};
    border: 1px solid {border};
}}
QTableCornerButton::section {{
    background-color: {header_bg};
    border: 1px solid {border};
}}
QTreeWidget::branch, QTreeView::branch {{
    background: transparent;
}}
QTreeWidget::indicator, QTreeView::indicator, QListWidget::indicator, QListView::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {border};
    background: {surface_alt};
}}
QTreeWidget::indicator:checked, QTreeView::indicator:checked, QListWidget::indicator:checked, QListView::indicator:checked {{
    background: {selected};
    border: 1px solid {selected};
}}
QFrame#licenseCard {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 12px;
}}
"""


DARK_VIEW_OVERRIDES = build_item_view_theme(
    surface="#0f172a",
    surface_alt="#162033",
    border="#334155",
    text="#e5e7eb",
    hover="#1b2a41",
    selected="#1e40af",
    header_bg="#1a2742",
)

NAVY_MODERN_VIEW_OVERRIDES = build_item_view_theme(
    surface="#162940",
    surface_alt="#1b314d",
    border="#3a5273",
    text="#e6eefc",
    hover="#22405f",
    selected="#2a5e9f",
    header_bg="#223953",
)

EMERALD_VIEW_OVERRIDES = build_item_view_theme(
    surface="#102f29",
    surface_alt="#154038",
    border="#2f5f54",
    text="#daf7ee",
    hover="#18473e",
    selected="#189a75",
    header_bg="#19443b",
)

SUNSET_VIEW_OVERRIDES = build_item_view_theme(
    surface="#311f18",
    surface_alt="#3a251d",
    border="#6a4639",
    text="#ffe9de",
    hover="#4a2d22",
    selected="#d67742",
    header_bg="#442a20",
)

BLACK_LUXE_VIEW_OVERRIDES = build_item_view_theme(
    surface="#0f1115",
    surface_alt="#171b22",
    border="#343a47",
    text="#f3f4f7",
    hover="#1f2430",
    selected="#2f3541",
    header_bg="#171b22",
)

# تم‌های مجاز و قطعی کارفرما
ALLOWED_THEMES = {"navy", "red", "green", "modern"}

THEME_PALETTE = {
    "navy": {"primary": "#020025", "hover": "#17134f", "pressed": "#010016", "soft": "#ecebff", "soft_border": "#c9c7ff"},
    "red": {"primary": "#C60040", "hover": "#c31635", "pressed": "#8e0c24", "soft": "#ffe9eb", "soft_border": "#f2b6bd"},
    "green": {"primary": "#008030", "hover": "#0b9440", "pressed": "#006326", "soft": "#e7f8ef", "soft_border": "#b9e8ce"},
    # «modern» — طراحی جدید (آبی برند طبق درخواست) — فقط رنگ اضافه می‌شود،
    # همان مکانیزم قدیمی (Dashboard و بقیه‌ی جاهایی که از این دیکشنری رنگ
    # می‌گیرند) بدون هیچ تغییر منطقی، خودکار از این رنگ استفاده می‌کند.
    "modern": {"primary": "#3B82F6", "hover": "#2563EB", "pressed": "#1D4ED8", "soft": "#EFF6FF", "soft_border": "#BFDBFE"},
}


def _build_theme_override(primary, hover, pressed, soft, soft_border):
    # رنگ سبز برای دکمه‌های sync (تابع تم)
    sync_green = "#16a34a"
    sync_green_hover = "#15803d"
    
    return f"""
QWidget {{ background-color: #ffffff; }}
QMainWindow, QDialog {{ background-color: #ffffff; }}
QTabWidget::pane {{ border-top: 2px solid {primary}; background: #ffffff; }}
QTabBar {{ background: #ffffff; }}
QTabBar::tab {{ color: #334155; background: #ffffff; border: 1px solid #e2e8f0; border-bottom: 2px solid transparent; border-top-left-radius: 10px; border-top-right-radius: 10px; }}
QTabBar::tab:selected {{ color: #ffffff; border: 1px solid {primary}; border-bottom: 3px solid {primary}; background: {primary}; }}
QTabBar::tab:hover {{ color: {primary}; border-bottom: 3px solid {soft_border}; background: {soft}; }}
QPushButton {{ background-color: {primary}; color: white; }}
QPushButton:hover {{ background-color: {hover}; }}
QPushButton:pressed {{ background-color: {pressed}; }}
QPushButton[syncAction="true"] {{ background-color: {sync_green}; color: white; font-weight: bold; }}
QPushButton[syncAction="true"]:hover {{ background-color: {sync_green_hover}; }}
QPushButton[syncAction="true"]:pressed {{ background-color: #15803d; }}
QPushButton[flat="true"] {{ color: {primary}; border: 1px solid {primary}; background: transparent; }}
QPushButton[flat="true"]:hover {{ background-color: {soft}; }}
QPushButton[compactActionBtn="true"] {{ background-color: {primary}; color: #ffffff; }}
QPushButton[compactActionBtn="true"]:hover,
QPushButton[compactActionBtn="true"][compactExpanded="true"] {{ background-color: {hover}; }}
QPushButton[compactActionBtn="true"]:pressed {{ background-color: {pressed}; }}
QPushButton[compactActionBtn="true"][compactActionRole="images"] {{ background-color: {sync_green}; }}
QPushButton[compactActionBtn="true"][compactActionRole="images"]:hover,
QPushButton[compactActionBtn="true"][compactActionRole="images"][compactExpanded="true"] {{ background-color: {sync_green_hover}; }}
QPushButton[compactActionBtn="true"][compactActionRole="upload"] {{ background-color: {hover}; }}
QPushButton[compactActionBtn="true"][compactActionRole="upload"]:hover,
QPushButton[compactActionBtn="true"][compactActionRole="upload"][compactExpanded="true"] {{ background-color: {primary}; }}
QLineEdit:focus {{ border: 1.5px solid {primary}; background-color: #ffffff; }}
QComboBox:focus {{ border: 1.5px solid {primary}; }}
QComboBox QAbstractItemView {{ selection-background-color: {soft}; selection-color: {primary}; }}
QListWidget::item:hover {{ background-color: {soft}; color: {primary}; }}
QListWidget::item:selected {{ background-color: {primary}; color: #ffffff; }}
QTreeWidget::item:selected, QTableWidget::item:selected {{ background-color: {primary}; color: #ffffff; }}
QGroupBox::title {{ color: {primary}; background: {soft}; border: 1px solid {soft_border}; }}
QFrame#licenseCard {{ border: 1px solid {soft_border}; }}

QLabel[role="badge-success"] {{
    background-color: #22c55e;
    color: white;
    font-weight: bold;
    padding: 6px 12px;
    border-radius: 4px;
}}

QLabel[role="badge-error"] {{
    background-color: #ef4444;
    color: white;
    font-weight: bold;
    padding: 6px 12px;
    border-radius: 4px;
}}

QLabel[role="badge-info"] {{
    background-color: #3b82f6;
    color: white;
    font-weight: bold;
    padding: 6px 12px;
    border-radius: 4px;
}}

QFrame#homeHeroCard {{
    background: #ffffff;
    border-radius: 14px;
    border: 1px solid {soft_border};
}}

QFrame#homeHeroHeader {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 {soft});
    border-bottom: 1px solid {soft_border};
}}

QLabel#homeHeroBadge {{
    color: {pressed};
    border-color: {soft_border};
    background: rgba(255, 255, 255, 0.9);
}}

QFrame#homeHeroCard QLabel#homeHeroTitle {{
    color: {primary};
    font-weight: 800;
}}

QFrame#homeHeroCard QLabel#homeHeroSubtitle {{
    color: {pressed};
    font-weight: 600;
}}

QLabel#homeHeroTip {{
    border-color: {soft_border};
    background: {soft};
    color: {pressed};
}}

QFrame#homeFlowCard,
QFrame#homeInfoCard,
QFrame#homeQuickCard {{
    border-color: {soft_border};
}}

QFrame#homeStepRow {{
    border-color: {soft_border};
    background: #ffffff;
}}

QFrame#homeStepRow:hover {{
    border-color: {primary};
    background: {soft};
}}

QLabel#homeStepNumber {{
    background: {primary};
    color: #ffffff;
}}

QPushButton#homeStepBtn {{
    border-color: {soft_border};
    color: {primary};
}}

QPushButton#homeStepBtn:hover {{
    background: {primary};
    color: #ffffff;
    border-color: {primary};
}}

QLabel#homeSectionTitle,
QLabel#homeCardTitle {{
    color: {primary};
}}

QPushButton#homeQuickBtn {{
    background-color: {primary};
    color: white;
}}

QPushButton#homeQuickBtn:hover {{
    background-color: {hover};
}}

QPushButton#homeQuickBtn:pressed {{
    background-color: {pressed};
}}

QWidget#dashRoot {{
    background: {soft};
}}

QFrame#dashPanel,
QFrame#dashStatCard,
QFrame#dashHealthCard,
QFrame#dashTablePanel {{
    border-color: {soft_border};
}}

QPushButton#dashQuickBtn:hover {{
    background: {soft};
    border-color: {primary};
}}

QFrame#reconHeroCard {{
    background: {soft};
    border: 1px solid {soft_border};
    border-radius: 14px;
}}

QFrame#reconHeroHeader {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #ffffff,
        stop: 1 {soft}
    );
    border-bottom: 1px solid {soft_border};
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}}

QFrame#reconHeroCard QLabel#reconHeroToolLabel {{
    color: {pressed};
}}

QFrame#reconHeroToolSep {{
    background: {soft_border};
}}

QFrame#reconHeroSegment {{
    border-color: {soft_border};
    background: #ffffff;
}}

QFrame#reconHeroCard QPushButton[reconHeroSeg="true"] {{
    color: {pressed};
    border-left-color: {soft_border};
}}

QFrame#reconHeroCard QPushButton[reconHeroSeg="true"]:hover {{
    background: {soft};
    color: {primary};
}}

QFrame#reconHeroCard QPushButton[reconHeroSeg="true"][active="true"],
QFrame#reconHeroCard QPushButton[reconHeroSeg="true"][active="true"]:hover {{
    background: {primary};
    color: #ffffff;
}}

QFrame#reconHeroFontFloat {{
    background: rgba(255, 255, 255, 0.98);
    border: 1px solid {soft_border};
}}

QFrame#reconHeroFontFloat QPushButton[reconHeroFloatBtn="true"] {{
    color: {primary};
    border-color: {soft_border};
}}

QFrame#reconHeroFontFloat QPushButton[reconHeroFloatBtn="true"]:hover {{
    background: {soft};
    border-color: {primary};
}}

QFrame#reconHeroFontFloat QPushButton[reconHeroCloseBtn="true"] {{
    color: #dc2626;
    background: #fff1f2;
    border-color: #fecaca;
}}

QFrame#reconHeroFontFloat QPushButton[reconHeroCloseBtn="true"]:hover {{
    background: #fee2e2;
    border-color: #dc2626;
    color: #b91c1c;
}}

QFrame#reconHeroCard QLabel#reconHeroTitle {{
    color: {primary};
    font-weight: 800;
}}

QFrame#reconHeroCard QLabel#reconHeroHint {{
    color: {pressed};
}}

QFrame#autoSyncInfoCard,
QFrame#autoSyncJobsCard {{
    background: {soft};
    border: 1px solid {soft_border};
}}

QFrame#autoSyncInfoCard QLabel#autoSyncInfoTitle,
QFrame#autoSyncJobsCard QLabel#autoSyncJobsTitle {{
    color: {primary};
}}

QFrame#autoSyncInfoCard QLabel#autoSyncInfoBody {{
    color: {pressed};
}}

QFrame#autoSyncJobRow {{
    border-color: {soft_border};
    background: #ffffff;
}}

QFrame#autoSyncJobRow:hover {{
    border-color: {primary};
    background: {soft};
}}

QFrame#autoSyncJobRow[jobSelected="true"] {{
    border-color: {primary};
    background: {soft};
}}

QFrame#autoSyncJobRow QLabel#autoSyncJobTitle {{
    color: {primary};
}}

QFrame#autoSyncJobRow QLabel#autoSyncJobHint {{
    color: {pressed};
}}

QWidget#autoSyncRoot QCheckBox#autoSyncJobCheck::indicator:checked {{
    background: {primary};
    border-color: {primary};
}}

QWidget#autoSyncRoot QCheckBox#autoSyncJobCheck::indicator:hover {{
    border-color: {primary};
}}

QPushButton#autoSyncJobsSelectAll:hover,
QPushButton#autoSyncJobsClearAll:hover {{
    background: {soft};
    border-color: {primary};
}}

QFrame#logsInfoCard {{
    background: {soft};
    border: 1px solid {soft_border};
}}

QFrame#logsInfoCard QLabel#logsInfoTitle {{
    color: {primary};
}}

QFrame#logsInfoCard QLabel#logsInfoBody,
QLabel#logsStatsLabel,
QLabel#logsPathLabel {{
    color: {pressed};
}}

QLabel#reconPairCountBar {{
    color: {primary};
    background: {soft};
    border: 1px solid {soft_border};
}}

QFrame#reconColumnCard,
QFrame#reconMiddlePanel {{
    border-color: {soft_border};
}}

QFrame#reconStatusBar[state="ready"],
QFrame#reconStatusBar[state="success"] {{
    background-color: {soft};
    border-color: {soft_border};
}}

QFrame#reconStatusBar[state="ready"] QLabel#reconStatusMessage,
QFrame#reconStatusBar[state="success"] QLabel#reconStatusMessage {{
    color: {primary};
}}

QFrame#reconStatusBar[state="info"] {{
    background-color: {soft};
    border-color: {soft_border};
}}

QFrame#reconStatusBar[state="info"] QLabel#reconStatusMessage {{
    color: {primary};
}}

QFrame#reconStatusBar QPushButton#reconStatusSearchToggle {{
    background-color: #ffffff;
    color: {primary};
    border: 1.5px solid {soft_border};
}}

QFrame#reconStatusBar QPushButton#reconStatusSearchToggle:hover {{
    background-color: {soft};
    border-color: {primary};
}}

QFrame#reconStatusBar QPushButton#reconStatusSearchClose {{
    background-color: #ffffff;
    color: #dc2626;
    border: 2px solid #f87171;
    font-size: 22px;
    font-weight: 800;
}}

QFrame#reconStatusBar QPushButton#reconStatusSearchClose:hover {{
    background-color: #fee2e2;
    color: #991b1b;
    border-color: #ef4444;
}}

QFrame#reconStatusBar QPushButton#reconTablesFullscreenBtn {{
    background-color: #ffffff;
    color: {primary};
    border: 1.5px solid {soft_border};
    font-weight: 700;
    padding: 4px 12px;
}}

QFrame#reconStatusBar QPushButton#reconTablesFullscreenBtn:hover {{
    background-color: {soft};
    border-color: {primary};
}}

QFrame#reconStatusBar QPushButton#reconTablesFullscreenBtn[active="true"] {{
    background-color: {soft};
    border-color: {primary};
    color: {pressed};
}}

QFrame#reconMiddleGroupManual {{
    background: {soft};
    border-color: {soft_border};
    border-right: 4px solid {primary};
}}

QFrame#reconMiddleGroupHeader[reconGroupRole="manual"] {{
    background: {soft};
    border-color: {soft_border};
}}

QLabel#reconMiddleStepBadge[reconGroupRole="manual"] {{
    background: {primary};
}}

QFrame#reconMiddlePanel QLabel#reconMiddleGroupTitle[reconGroupRole="manual"] {{
    color: {primary};
}}

QFrame#reconMiddlePanel QLabel#reconMiddleGroupHint[reconGroupRole="manual"] {{
    color: {pressed};
}}

QSplitter#reconTopSplitter::handle {{
    background: {soft_border};
}}

QSplitter#reconTopSplitter::handle:hover {{
    background: {primary};
}}

QWidget#reconRoot QLabel#reconTopSplitterGrip:hover {{
    color: {primary};
    border-color: {soft_border};
    background: {soft};
}}

QScrollArea#reconTopScroll,
QScrollArea#reconMiddleScroll {{
    background: transparent;
    border: none;
}}

QListWidget#reconList {{
    border-color: {soft_border};
}}

QListWidget#reconList::item:selected {{
    background-color: {primary};
    color: #ffffff;
}}

QListWidget#reconList::item:hover {{
    background-color: {soft};
    color: {primary};
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn {{
    background-color: #ffffff;
    color: {primary};
    border: 1.5px solid {soft_border};
    font-weight: 700;
    font-size: 11px;
    min-height: 38px;
    padding: 6px 8px;
    border-radius: 6px;
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn:hover {{
    background-color: {soft};
    color: {pressed};
    border-color: {primary};
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn:disabled {{
    background-color: #f8fafc;
    color: #64748b;
    border-color: #e2e8f0;
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn[reconBtnRole="primary"] {{
    background-color: {primary};
    color: #ffffff;
    border: none;
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn[reconBtnRole="primary"]:hover {{
    background-color: {hover};
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn[reconBtnRole="primary"]:disabled {{
    background-color: {soft};
    color: #64748b;
    border: 1.5px solid {soft_border};
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn[reconBtnRole="action"] {{
    background-color: #ffffff;
    color: {primary};
    border: 2px solid {primary};
    font-weight: 800;
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn[reconBtnRole="action"]:hover {{
    background-color: {soft};
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn[reconBtnRole="danger"] {{
    background-color: #fff1f2;
    color: #be123c;
    border: 1.5px solid #fecdd3;
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn[reconBtnRole="danger"]:hover {{
    background-color: #ffe4e6;
    border-color: #fda4af;
}}

QWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn[reconBtnRole="danger"]:disabled {{
    background-color: #f8fafc;
    color: #cbd5e1;
    border-color: #e2e8f0;
}}

QWidget#reconRoot QPushButton#reconMiddleBtn {{
    background-color: #ffffff;
    color: {primary};
    border: 1.5px solid {soft_border};
    font-weight: 700;
    font-size: 11px;
    min-height: 32px;
    padding: 4px 6px;
    border-radius: 6px;
}}

QWidget#reconRoot QPushButton#reconMiddleBtn:hover {{
    background-color: {soft};
    color: {pressed};
    border-color: {primary};
}}

QWidget#reconRoot QPushButton#reconMiddleBtn:disabled {{
    background-color: #f8fafc;
    color: #64748b;
    border-color: #e2e8f0;
}}

QWidget#reconRoot QPushButton#reconMiddleBtn[syncAction="true"] {{
    background-color: {sync_green};
    color: #ffffff;
    border: none;
}}

QWidget#reconRoot QPushButton#reconMiddleBtn[syncAction="true"]:hover {{
    background-color: {sync_green_hover};
}}

QWidget#reconRoot QPushButton#reconMiddleBtn[syncAction="true"]:disabled {{
    background-color: {soft};
    color: #64748b;
    border: 1.5px solid {soft_border};
}}

QWidget#reconRoot QPushButton#reconRefreshBtn {{
    background-color: transparent;
    color: {primary};
    border: 1.5px solid {primary};
    font-weight: 600;
}}

QWidget#reconRoot QPushButton#reconRefreshBtn:hover {{
    background-color: {soft};
    color: {primary};
}}

QWidget#reconRoot QPushButton#reconRefreshBtn:disabled {{
    background-color: #f1f5f9;
    color: #94a3b8;
    border-color: #e2e8f0;
}}

QWidget#reconRoot QPushButton#reconRefreshBtn[reconLoadMode="stop"] {{
    background-color: #ffffff;
    color: {primary};
    border: 2px solid {primary};
    border-radius: 10px;
    font-weight: 700;
    padding: 8px 14px;
}}

QWidget#reconRoot QPushButton#reconRefreshBtn[reconLoadMode="stop"]:hover {{
    background-color: {soft};
    color: {pressed};
}}

QWidget#reconRoot QPushButton#reconQuickSkuBtn,
QWidget#reconRoot QPushButton#reconCommitBtn {{
    background-color: {primary};
    color: #ffffff;
    border: none;
    border-radius: 10px;
    font-weight: 700;
    padding: 8px 14px;
}}

QWidget#reconRoot QPushButton#reconQuickSkuBtn:hover,
QWidget#reconRoot QPushButton#reconCommitBtn:hover {{
    background-color: {hover};
}}

QWidget#reconRoot QPushButton#reconQuickSkuBtn:pressed,
QWidget#reconRoot QPushButton#reconCommitBtn:pressed {{
    background-color: {pressed};
}}

QWidget#reconRoot QPushButton#reconQuickSkuBtn:disabled,
QWidget#reconRoot QPushButton#reconCommitBtn:disabled {{
    background-color: {soft};
    color: #64748b;
    border: 1.5px solid {soft_border};
}}
"""


THEME_OVERRIDES = {
    key: _build_theme_override(**value)
    for key, value in THEME_PALETTE.items()
}


# ---------------------------------------------------------
# تب‌ها — import تنبل هنگام اولین باز شدن (startup سریع‌تر)
# ---------------------------------------------------------
from sync_app.core.tabs.tab_home import HomeTab
from sync_app.core.tabs.tab_license import LicenseTab
from sync_app.core.lazy_tab_loader import tab_factory
from sync_app.core.connectivity_service import (
    BADGE_OFFLINE_STYLE,
    BADGE_OFFLINE_STYLE_TALL,
    BADGE_ONLINE_STYLE,
    BADGE_ONLINE_STYLE_TALL,
    BADGE_PENDING_STYLE,
    BADGE_PENDING_STYLE_TALL,
    connectivity_age_label_fa,
    load_connectivity_cache,
    wc_badge_offline_lines,
)

HEADER_BADGE_HEIGHT = 44
HEADER_BADGE_SUB_ELIDE = 168
from sync_app.core.app_site_config import (
    get_app_header_subtitle,
    get_app_window_title,
    get_store_display_name,
)
from sync_app.core.window_geometry_helper import apply_window_geometry, save_window_geometry
from sync_app.core.user_profile import (
    activate_profile,
    get_current_profile_display_name,
    load_last_profile_id,
    load_secure_config_after_profile,
    migrate_legacy_profiles,
)
from sync_app.core.sync_utils import log, reconfigure_app_logging


from sync_app.core.adaptive_tab_bar import AdaptiveTabBar


class PeechaLauncher(QWidget):
    def __init__(self):
        super().__init__()
        self._allow_close = False
        self._applied_style_signature = None
        self._header_check_thread = None
        self._header_check_worker = None
        self._wc_check_thread = None
        self._wc_check_worker = None
        self._sql_check_thread = None
        self._sql_check_worker = None
        self._header_probe_pending = False
        self._wc_probe_pending = False
        self._offline_blink_timers = {}   # label -> QTimer
        self._last_sql_ok = None          # None = هنوز بررسی نشده
        self._last_wc_ok = None
        self._sql_display_ok = None
        self._wc_display_ok = None
        self._sql_fail_streak = 0
        self._wc_fail_streak = 0
        self._wc_last_ms = 0.0
        self._wc_last_probe_at = 0.0
        self._wc_last_msg = ""
        self._sql_tooltip = ""
        self._wc_tooltip = ""
        self._sql_db_name = ""
        self.dashboard_tab = None
        self.sync_hub_tab = None
        self.smart_assistant_hub_tab = None
        self.product_tab = None
        self.variation_tab = None
        self.category_tab = None
        self.reconciliation_tab = None
        self.config_tab = None
        self.auto_sync_tab = None
        self.properties_tab = None
        self.customer_tab = None
        self.order_tab = None
        self.logs_tab = None
        self.license_tab = None
        self._license_renewal_required = False
        self._license_sync_silent = False
        self._lazy_tabs = []
        self._restoring_active_tab = False
        self._tab_persistence_ready = False
        self._startup_dialogs_pending = True
        self._tab_nav_lock_count = 0
        self._tab_nav_locked_index = -1
        from sync_app.core.app_version import app_version_label
        from sync_app.core.brand_assets import HEADER_FRAME_HEIGHT, HEADER_LOGO_HEIGHT, brand_logo_pixmap

        self.setWindowTitle(get_app_window_title())
        apply_brand_window_icon(self)
        self.setLayoutDirection(Qt.RightToLeft)
        # جلوگیری از کوچک‌تر شدن پنجره از حد یک موبایل افقی
        self.setMinimumSize(MOBILE_LANDSCAPE_MIN_WIDTH, MOBILE_LANDSCAPE_MIN_HEIGHT)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ─── هدر حرفه‌ای با گرادیان ───
        self.header_frame = QWidget()

        self.header_frame.setFixedHeight(HEADER_FRAME_HEIGHT)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(16, 0, 20, 0)
        header_layout.setSpacing(14)
        header_layout.setAlignment(Qt.AlignVCenter)

        # لوگو
        self.logo_label = QLabel()
        self.logo_label.setObjectName("headerLogo")
        self.logo_label.setStyleSheet("background: transparent;")
        self.logo_label.setAlignment(Qt.AlignCenter)
        self._logo_source_pixmap = None

        header_logo = brand_logo_pixmap(HEADER_LOGO_HEIGHT, light_background=False)
        if not header_logo.isNull():
            self._logo_source_pixmap = header_logo
            self.logo_label.setPixmap(header_logo)
            self.logo_label.setFixedSize(
                max(header_logo.width(), HEADER_LOGO_HEIGHT),
                HEADER_FRAME_HEIGHT,
            )
        elif os.path.exists(LOGO_PATH):
            self._logo_source_pixmap = QPixmap(LOGO_PATH)
            pixmap = _scale_brand_logo(self._logo_source_pixmap, HEADER_LOGO_HEIGHT)
            self.logo_label.setPixmap(pixmap)
            self.logo_label.setFixedSize(
                max(pixmap.width(), HEADER_LOGO_HEIGHT),
                HEADER_FRAME_HEIGHT,
            )
        else:
            self.logo_label.setFixedSize(HEADER_LOGO_HEIGHT, HEADER_FRAME_HEIGHT)
            self.logo_label.setText("P")

        self.header_title = QLabel("همگام‌ساز پیچا")
        self.header_title.setObjectName("headerTitle")
        self.header_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.header_title.setMinimumHeight(HEADER_FRAME_HEIGHT)

        self.brand_block = QWidget()
        self.brand_block.setObjectName("headerBrandBlock")
        self.brand_block.setStyleSheet("background: transparent;")
        brand_layout = QHBoxLayout(self.brand_block)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(10)
        brand_layout.setAlignment(Qt.AlignVCenter)
        self.brand_block.setFixedHeight(HEADER_FRAME_HEIGHT)
        brand_layout.addWidget(self.logo_label, 0, Qt.AlignVCenter)
        brand_layout.addWidget(self.header_title, 0, Qt.AlignVCenter)
        header_layout.addWidget(self.brand_block, 0, Qt.AlignVCenter)

        # نام کاربر — جدا از سایت فعال، تا دیگه تکراری نباشه
        from sync_app.core.user_profile import get_current_profile_display_name
        profile_name = get_current_profile_display_name() or "—"
        self.header_username_label = QLabel(f"👤 {profile_name}")
        self.header_username_label.setObjectName("headerUsername")
        self.header_username_label.setStyleSheet("color: #ffffff;")
        header_layout.addWidget(self.header_username_label, 0, Qt.AlignVCenter)

        # سایت فعال — فقط یه‌بار نشون داده می‌شه
        self.header_subtitle = QLabel(f"🌐 {get_store_display_name()}")
        self.header_subtitle.setObjectName("headerSubtitle")
        header_layout.addWidget(self.header_subtitle, 0, Qt.AlignVCenter)

        self.header_license_expiry = QLabel()
        self.header_license_expiry.setObjectName("headerLicenseExpiry")
        self._refresh_header_license_expiry()
        header_layout.addWidget(self.header_license_expiry, 0, Qt.AlignVCenter)

        self.header_version_label = QLabel(app_version_label())
        self.header_version_label.setObjectName("headerVersionLabel")
        self.header_version_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

        self.header_version_latest = QLabel("آخرین نسخه")
        self.header_version_latest.setObjectName("headerVersionLatest")
        self.header_version_latest.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        self.header_version_latest.setVisible(False)

        self.header_update_btn = QPushButton("بروزرسانی")
        self.header_update_btn.setObjectName("headerUpdateBtn")
        self.header_update_btn.setCursor(Qt.PointingHandCursor)
        self.header_update_btn.setVisible(False)
        self.header_update_btn.clicked.connect(self._on_header_update_btn_clicked)

        self.header_version_wrap = QWidget()
        self.header_version_wrap.setObjectName("headerVersionWrap")
        self.header_version_wrap.setStyleSheet("background: transparent;")
        version_wrap_layout = QHBoxLayout(self.header_version_wrap)
        version_wrap_layout.setContentsMargins(0, 0, 0, 0)
        version_wrap_layout.setSpacing(8)
        version_wrap_layout.addWidget(self.header_version_label)
        version_wrap_layout.addWidget(self.header_version_latest)
        version_wrap_layout.addWidget(self.header_update_btn)
        header_layout.addWidget(self.header_version_wrap, 0, Qt.AlignVCenter)

        from sync_app.core.update_ui import HeaderUpdateSpinner

        self.header_update_spinner = HeaderUpdateSpinner(self.header_frame)
        header_layout.addWidget(self.header_update_spinner, 0, Qt.AlignVCenter)

        self._header_update_state = "unknown"

        header_layout.addStretch()

        # نشانگر وضعیت همگام‌سازی خودکار (فعال/غیرفعال + چقدر مونده به اجرای بعدی)
        self.header_autosync_badge = QLabel("")
        self.header_autosync_badge.setObjectName("headerAutosyncBadge")
        self.header_autosync_badge.setAlignment(Qt.AlignCenter)
        self.header_autosync_badge.setMinimumHeight(HEADER_BADGE_HEIGHT)
        self.header_autosync_badge.setStyleSheet(
            "background:#DBEAFE; color:#1D4ED8; border-radius:8px; padding:2px 10px; font-weight:700;"
        )
        self.header_autosync_badge.setVisible(False)
        header_layout.addWidget(self.header_autosync_badge, alignment=Qt.AlignVCenter)

        self._header_autosync_timer = QTimer(self)
        self._header_autosync_timer.setInterval(30000)  # هر ۳۰ ثانیه کافیه، لازم نیست لحظه‌ای باشه
        self._header_autosync_timer.timeout.connect(self._refresh_header_autosync_badge)
        self._header_autosync_timer.start()
        QTimer.singleShot(1000, self._refresh_header_autosync_badge)

        # نشانگر هشدار موارد لینک‌نشده (محصول/دسته‌بندی/متغیر) — فقط خواندنی
        self.link_warning_badge = QLabel("")
        self.link_warning_badge.setObjectName("headerLinkWarning")
        self.link_warning_badge.setProperty("role", "header-badge")
        self.link_warning_badge.setAlignment(Qt.AlignCenter)
        self.link_warning_badge.setCursor(Qt.PointingHandCursor)
        self.link_warning_badge.setToolTip("کلیک کنید برای جزئیات بیشتر")
        self.link_warning_badge.setMinimumHeight(HEADER_BADGE_HEIGHT)
        self.link_warning_badge.setStyleSheet(
            "background:#FEF3C7; color:#92400E; border-radius:8px; padding:2px 10px; font-weight:700;"
        )
        self.link_warning_badge.setVisible(False)
        self.link_warning_badge.installEventFilter(self)
        header_layout.addWidget(self.link_warning_badge, alignment=Qt.AlignVCenter)

        # نشانگر SQL — وضعیت + نام DB داخل یک badge
        self.sql_status_indicator = QLabel("SQL\n...")
        self.sql_status_indicator.setObjectName("headerSqlStatus")
        self.sql_status_indicator.setProperty("role", "header-badge")
        self.sql_status_indicator.setAlignment(Qt.AlignCenter)
        self.sql_status_indicator.setCursor(Qt.PointingHandCursor)
        self.sql_status_indicator.setToolTip("کلیک کنید تا به تنظیمات SQL بروید")
        self.sql_status_indicator.setMinimumHeight(HEADER_BADGE_HEIGHT)
        self.sql_status_indicator.installEventFilter(self)
        header_layout.addWidget(self.sql_status_indicator, alignment=Qt.AlignVCenter)

        self.wc_status_indicator = QLabel("...\n...")
        self.wc_status_indicator.setObjectName("headerWooStatus")
        self.wc_status_indicator.setProperty("role", "header-badge")
        self.wc_status_indicator.setAlignment(Qt.AlignCenter)
        self.wc_status_indicator.setCursor(Qt.PointingHandCursor)
        self.wc_status_indicator.setToolTip("کلیک کنید تا به تنظیمات فروشگاه بروید")
        self.wc_status_indicator.setMinimumHeight(HEADER_BADGE_HEIGHT)
        self.wc_status_indicator.installEventFilter(self)
        header_layout.addWidget(self.wc_status_indicator, alignment=Qt.AlignVCenter)

        layout.addWidget(self.header_frame)

        self._pending_update_info = None

        # خط جداکننده ظریف
        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.HLine)
        self.separator.setFixedHeight(2)
        self.separator.setStyleSheet("background: #dde3f0; border: none;")
        layout.addWidget(self.separator)

        # تب‌ها
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        adaptive_tab_bar = AdaptiveTabBar(self.tabs)
        self.tabs.setTabBar(adaptive_tab_bar)
        self.tabs.currentChanged.connect(self._on_tab_index_changed)

        self.home_tab = HomeTab(navigate_callback=self.go_to_tab_by_keyword)
        self.tabs.addTab(self.home_tab, "🏠 شروع")

        # ترتیب تب‌ها: مسیر کاری روزانه، سپس ابزارهای کم‌کاربرد
        # طبق درخواست: تب‌ها جمع‌وجورتر شدن — محصولات/دسته‌بندی‌ها/ویژگی‌ها/
        # متغیرها/مشتریان/سفارشات همه زیر یک تب گروهی «همگام‌سازی» رفتن، و
        # مرکز رسانه/سئو/بازاریابی/مشاور پیچا زیر «دستیار هوشمند».
        self._register_lazy_tab(
            "📊 داشبورد",
            "dashboard_tab",
            lambda: tab_factory(
                "sync_app.core.tabs.tab_dashboard",
                "DashboardTab",
                navigate_callback=self.go_to_tab_by_keyword,
            )(),
        )
        self._register_lazy_tab(
            "🔄 همگام‌سازی",
            "sync_hub_tab",
            tab_factory("sync_app.core.tabs.tab_sync_hub", "SyncHubTab"),
            tooltip="دسته‌بندی‌ها، ویژگی‌ها، محصولات، متغیرها، مشتریان و سفارشات",
        )
        self._register_lazy_tab(
            "🧠 دستیار هوشمند",
            "smart_assistant_hub_tab",
            tab_factory("sync_app.core.tabs.tab_smart_assistant_hub", "SmartAssistantHubTab"),
            tooltip="مرکز رسانه، سئو و سلامت سایت، مدیریت بازاریابی و مشاور پیچا",
        )
        from sync_app.core.integrations.erp_provider import erp_provider_label

        self._register_lazy_tab(
            "⚖️ تطبیق",
            "reconciliation_tab",
            tab_factory("sync_app.core.tabs.tab_reconciliation", "ReconciliationTab"),
            tooltip=f"مقایسه و تطبیق {erp_provider_label(load_secure_config(None))} با فروشگاه — برای فروشگاه‌های از قبل فعال",
        )
        self._register_lazy_tab(
            "📄 لاگ‌ها",
            "logs_tab",
            tab_factory("sync_app.core.tabs.tab_logs", "LogsTab"),
        )
        self._register_lazy_tab(
            "⚡ همگام‌سازی خودکار",
            "auto_sync_tab",
            tab_factory("sync_app.core.tabs.tab_auto_sync", "AutoSyncTab"),
            tooltip="همگام‌سازی خودکار محصولات، موجودی و سایر همگام‌سازی‌ها",
        )
        self._register_lazy_tab(
            "⚙️ تنظیمات",
            "config_tab",
            tab_factory("sync_app.core.tabs.tab_settings", "ConfigTab"),
        )
        self._register_lazy_tab(
            "🔐 فعال‌سازی",
            "license_tab",
            tab_factory("sync_app.core.tabs.tab_license", "LicenseTab"),
            tooltip="فعال‌سازی لایسنس نرم‌افزار پیچا",
        )

        layout.addWidget(self.tabs)
        self.setLayout(layout)

        cfg = load_secure_config(None) or {}
        QTimer.singleShot(0, lambda t=cfg.get("APP_THEME", "navy"): self.apply_theme(t))
        self._restore_connectivity_from_cache(cfg)
        self._header_wc_timer = QTimer(self)
        self._header_wc_timer.setInterval(10000)
        self._header_wc_timer.timeout.connect(self.refresh_wc_connectivity)
        self._header_sql_timer = QTimer(self)
        self._header_sql_timer.setInterval(28000)
        self._header_sql_timer.timeout.connect(self.refresh_sql_connectivity)
        self._header_sql_timer.start()

        self._link_warning_counts = {}
        self._link_warning_timer = QTimer(self)
        self._link_warning_timer.setInterval(600000)  # هر ۱۰ دقیقه — کوئری SQL داره، نباید مکرر باشه
        self._link_warning_timer.timeout.connect(self._refresh_link_warning)
        self._link_warning_timer.start()
        # نکته‌ی مهم (بعد از یک ریگرشن جدی): قبلاً اینجا قبل از هشدار، ۵ تب
        # (دسته‌بندی/محصول/متغیر/مشتری/سفارش) رو به‌زور می‌ساخت و لود می‌کرد،
        # با این فرض که این کار نگاشت‌های محلی (لینک به ووکامرس) رو تازه
        # می‌کنه. این فرض غلط بود — آن نگاشت‌ها فقط حین سینک واقعی نوشته
        # می‌شن، نه با صرفاً دیدن/لود کردن تب. آن زنجیره‌ی سنگین SQL هم فایده‌ی
        # واقعی نداشت و هم با تایمرهای وضعیت اتصال (SQL/Woo) تداخل پیدا می‌کرد
        # و باعث می‌شد اونا اشتباهاً «قطع» نشون بدن. برای همین کاملاً حذف شد.
        QTimer.singleShot(9000, self._refresh_link_warning)
        QTimer.singleShot(5000, lambda: self.refresh_wc_connectivity(
            show_pending=self._wc_display_ok is None,
            fast=True,
        ))
        QTimer.singleShot(6000, self._header_wc_timer.start)
        QTimer.singleShot(2500, lambda: self.refresh_sql_connectivity(
            show_pending=self._sql_display_ok is None,
        ))
        QTimer.singleShot(3000, self._prompt_restore_last_active_tab)
        QTimer.singleShot(400, lambda: self._schedule_license_remote_sync(silent=False))
        QTimer.singleShot(2500, self._schedule_startup_update_check)
        self._license_remote_timer = QTimer(self)
        self._license_remote_timer.setInterval(180000)
        self._license_remote_timer.timeout.connect(lambda: self._schedule_license_remote_sync(silent=True))
        QTimer.singleShot(60000, self._license_remote_timer.start)
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setInterval(4 * 60 * 60 * 1000)
        self._update_check_timer.timeout.connect(self._schedule_startup_update_check)
        QTimer.singleShot(120000, self._update_check_timer.start)
        QTimer.singleShot(200, self._setup_tray_icon)

        self._content_calendar_timer = QTimer(self)
        self._content_calendar_timer.setInterval(60000)
        self._content_calendar_timer.timeout.connect(self._send_due_content_calendar_posts)
        QTimer.singleShot(15000, self._content_calendar_timer.start)

    def _refresh_header_update_ui(self) -> None:
        from sync_app.core.app_version import app_version_label

        label = getattr(self, "header_version_label", None)
        latest_lbl = getattr(self, "header_version_latest", None)
        btn = getattr(self, "header_update_btn", None)
        if label is None:
            return

        label.setText(app_version_label())
        state = getattr(self, "_header_update_state", "unknown")
        info = getattr(self, "_pending_update_info", None)

        if latest_lbl is not None:
            latest_lbl.setVisible(state == "latest")
        if btn is not None:
            if state == "available" and isinstance(info, dict) and info.get("update_available"):
                latest_ver = str(info.get("latest_version") or "").strip()
                btn.setText(f"⬇ بروزرسانی {latest_ver}" if latest_ver else "⬇ بروزرسانی")
                btn.setVisible(True)
            else:
                btn.setVisible(False)

    def _set_header_update_state(self, state: str, info: dict | None = None) -> None:
        if state == "available" and isinstance(info, dict):
            self._pending_update_info = info
        elif state == "latest":
            self._pending_update_info = None
        self._header_update_state = state
        self._refresh_header_update_ui()

    def _on_header_update_btn_clicked(self) -> None:
        info = getattr(self, "_pending_update_info", None)
        if not isinstance(info, dict) or not info.get("update_available"):
            return
        self._show_update_available_prompt(info)

    def _show_update_available_prompt(self, info: dict) -> None:
        from sync_app.core.update_ui import UpdateAvailableDialog

        self._set_header_update_state("available", info)
        dlg = UpdateAvailableDialog(self, info)
        if dlg.exec_() == dlg.Accepted:
            self._run_update_download(manual=True)

    def _schedule_license_remote_sync(self, *, silent: bool = True) -> None:
        if getattr(self, "_startup_remote_thread", None) is not None:
            return
        self._license_sync_silent = silent
        if not silent:
            self._set_header_update_state("unknown")
            if hasattr(self, "header_update_spinner"):
                self.header_update_spinner.start()

        thread = QThread(self)
        worker = StartupRemoteWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.finished.connect(lambda: setattr(self, "_startup_remote_thread", None))
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(self._on_license_remote_sync_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._startup_remote_thread = thread
        self._startup_remote_worker = worker
        thread.start()

    def _schedule_startup_remote_sync(self) -> None:
        self._schedule_license_remote_sync(silent=False)

    def _on_license_remote_sync_done(self, result: dict) -> None:
        silent = getattr(self, "_license_sync_silent", True)
        self._on_startup_remote_done(result, silent=silent)
        if LicenseTab._load_license_key():
            QTimer.singleShot(800, self._schedule_startup_update_check)

    def _schedule_startup_update_check(self) -> None:
        if not LicenseTab._load_license_key():
            return
        if getattr(self, "_startup_update_thread", None) is not None:
            return
        if getattr(self, "_startup_remote_thread", None) is not None:
            QTimer.singleShot(2000, self._schedule_startup_update_check)
            return

        if hasattr(self, "header_update_spinner"):
            self.header_update_spinner.start()

        thread = QThread(self)
        worker = StartupUpdateWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        thread.finished.connect(lambda: setattr(self, "_startup_update_thread", None))
        thread.finished.connect(thread.deleteLater)
        worker.finished.connect(self._on_startup_update_done)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        self._startup_update_thread = thread
        self._startup_update_worker = worker
        thread.start()

    def _on_startup_update_done(self, result: dict) -> None:
        self._startup_update_worker = None
        if hasattr(self, "header_update_spinner"):
            self.header_update_spinner.stop()
        if not isinstance(result, dict):
            return
        info = result.get("update_info")
        if isinstance(info, dict):
            if info.get("update_available"):
                self._set_header_update_state("available", info)
                from sync_app.core.app_update import reconcile_update_state_on_startup, should_block_update_apply

                reconcile_update_state_on_startup()
                cfg = load_secure_config(None) or {}
                auto_on = cfg.get(AUTO_UPDATE_ENABLED_KEY)
                if auto_on is None:
                    auto_on = False
                if auto_on and not getattr(self, "_auto_update_started", False):
                    blocked, _msg = should_block_update_apply()
                    if not blocked:
                        self._auto_update_started = True
                        QTimer.singleShot(3000, self._run_update_download)
            else:
                self._set_header_update_state("latest")
        self._refresh_header_license_expiry()

    def _on_startup_remote_done(self, result: dict, *, silent: bool = False) -> None:
        self._startup_remote_worker = None
        if hasattr(self, "header_update_spinner"):
            self.header_update_spinner.stop()
        self._refresh_header_license_expiry()
        if not isinstance(result, dict):
            return

        if result.get("license_ok") is True:
            if not LicenseTab.is_license_server_denied():
                self._clear_license_renewal_lock()
            lic_tab = getattr(self, "license_tab", None)
            if lic_tab is not None and hasattr(lic_tab, "refresh_license_display"):
                lic_tab.refresh_license_display()
            return

        if result.get("license_ok") is False and LicenseTab._load_license_key():
            err = str(result.get("license_err") or "").strip()
            if err and err not in ("connection_error", "timeout", "no_license_key"):
                from PyQt5.QtWidgets import QMessageBox

                from sync_app.core.license_remote import (
                    humanize_license_error,
                    is_server_denied_status,
                    license_server_host,
                )

                self._refresh_header_license_expiry()
                lic_tab = getattr(self, "license_tab", None)
                if lic_tab is not None and hasattr(lic_tab, "refresh_license_display"):
                    lic_tab.refresh_license_display()

                if is_server_denied_status(err):
                    self._enter_license_renewal_mode(err, show_dialog=not silent)
                    return

                if silent:
                    return

                human = humanize_license_error(err)
                lic_host = license_server_host()
                if "api key" in err.lower() or "forbidden" in err.lower():
                    human = (
                        "کلید API لایسنس در تنظیمات برنامه با wp-admin یکی نیست.\n\n"
                        f"تنظیمات -> آدرس سرور لایسنس ({lic_host}) -> کلید API لایسنس.\n"
                        "بدون این کلید، دستگاه در لیست افزونه ثبت نمی‌شود."
                    )
                QMessageBox.warning(
                    self,
                    "لایسنس",
                    f"ثبت آنلاین روی {lic_host} انجام نشد:\n{human}",
                )

    def _run_update_download(self, *, manual: bool = False) -> None:
        info = getattr(self, "_pending_update_info", None)
        if not isinstance(info, dict):
            return
        if getattr(self, "_update_thread", None) is not None:
            return

        from sync_app.core.tabs.tab_license import LicenseTab
        from sync_app.core.update_ui import run_update_download

        ok, msg, restart = run_update_download(
            self,
            info,
            LicenseTab.get_hwid(),
            ask_cached=manual,
            ignore_apply_block=manual,
        )
        self._on_update_download_done(ok, msg, restart)

    def _on_update_download_done(self, ok: bool, msg: str, restart: bool) -> None:
        import os

        from PyQt5.QtWidgets import QMessageBox

        from sync_app.core.update_ui import humanize_update_error

        self._update_worker = None
        if ok and restart:
            self._force_exit_for_update()
            return

        if ok:
            return

        err_text = humanize_update_error(msg) if msg else "بروزرسانی ناموفق بود."
        QMessageBox.warning(self, "بروزرسانی", err_text)

    def _force_exit_for_update(self) -> None:
        import os

        from sync_app.core.app_update import _kill_peecha_processes

        self._allow_close = True
        tray = getattr(self, "tray_icon", None)
        if tray is not None:
            try:
                tray.hide()
            except Exception:
                pass
        _kill_peecha_processes()
        os._exit(0)

    def _refresh_license_remote_cache(self):
        self._schedule_startup_remote_sync()

    def _restore_connectivity_from_cache(self, cfg):
        cached = load_connectivity_cache(cfg)
        if not cached:
            self._paint_sql_badge(None, pending=True)
            self._paint_wc_badge(None, pending=True)
            return

        sql_ok = cached.get("sql_ok")
        wc_ok = cached.get("wc_ok")
        self._sql_display_ok = sql_ok
        self._wc_display_ok = wc_ok
        self._last_sql_ok = sql_ok
        self._last_wc_ok = wc_ok
        self._wc_last_ms = float(cached.get("wc_ms") or 0)
        self._wc_last_probe_at = float(cached.get("at") or 0)
        self._sql_tooltip = self._build_sql_tooltip(bool(sql_ok), str(cached.get("sql_msg") or ""))
        self._wc_tooltip = self._build_wc_tooltip(bool(wc_ok), str(cached.get("wc_msg") or ""))

        import re as _re
        _db_match = _re.search(r"DB=([^|]+)", self._sql_tooltip or "")
        db_name = _db_match.group(1).strip() if _db_match else ""
        self._set_sql_db_display(db_name if sql_ok else "")
        self._paint_wc_badge(wc_ok, pending=False, tooltip=self._wc_tooltip)

    def _set_sql_db_display(self, db_name: str):
        self._sql_db_name = (db_name or "").strip()
        self._paint_sql_badge(
            self._sql_display_ok,
            pending=self._sql_display_ok is None,
            tooltip=self._sql_tooltip or self._sql_db_name or "نام دیتابیس SQL",
        )

    def set_sql_header_database(self, db_name: str, *, sql_ok=None):
        """نام DB در badge — بدون انتظار برای probe اتصال"""
        db_name = (db_name or "").strip()
        self._sql_db_name = db_name
        if sql_ok is not None:
            self._sql_display_ok = bool(sql_ok)
            self._last_sql_ok = bool(sql_ok)
        if db_name:
            self._sql_tooltip = f"DB={db_name}"
        self._paint_sql_badge(
            self._sql_display_ok,
            pending=self._sql_display_ok is None,
            tooltip=self._sql_tooltip or db_name or "نام دیتابیس SQL",
        )

    def _make_tab_placeholder(self):
        """صفحه موقت هنگام ساخت تنبل تب"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        label = QLabel("⏳ در حال آماده‌سازی...")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #64748b; font-size: 14px; padding: 24px;")
        layout.addWidget(label)
        return widget

    def _register_lazy_tab(self, title, attr_name, factory, tooltip=None):
        placeholder = self._make_tab_placeholder()
        index = self.tabs.addTab(placeholder, title)
        if tooltip:
            self.tabs.setTabToolTip(index, tooltip)
        self._lazy_tabs.append({
            "attr": attr_name,
            "title": title,
            "placeholder": placeholder,
            "factory": factory,
            "loaded": False,
            "building": False,
        })

    def _materialize_lazy_tab(self, spec):
        if spec.get("loaded"):
            return
        index = self._find_tab_index_by_attr(spec["attr"])
        if index < 0:
            spec["building"] = False
            return

        try:
            new_widget = spec["factory"]()
        except Exception:
            import traceback

            spec["building"] = False
            log.error(
                "Tab build failed (%s):\n%s",
                spec.get("attr", "?"),
                traceback.format_exc(),
            )
            return

        title = self.tabs.tabText(index)
        current_idx = self.tabs.currentIndex()
        self.tabs.blockSignals(True)
        try:
            self.tabs.removeTab(index)
            self.tabs.insertTab(index, new_widget, title)
            if current_idx == index:
                self.tabs.setCurrentIndex(index)
        finally:
            self.tabs.blockSignals(False)

        spec["loaded"] = True
        spec["building"] = False
        spec["placeholder"] = None
        setattr(self, spec["attr"], new_widget)
        # سازگاری با تب‌های گروهی جدید (مثل SyncHubTab/SmartAssistantHubTab):
        # اگه این ویجت خودش چندتا زیرتب رو نمایندگی می‌کنه، همون ارجاعات
        # قدیمی (self.category_tab, self.product_tab, ...) رو هم دقیقاً
        # مثل قبل تنظیم کن — تا کد دیگه‌ای که مستقیم بهشون رجوع می‌کنه
        # (مثل _link_tab_dependencies و reload_sql_dependent_tabs) نیازی
        # به تغییر نداشته باشه.
        if hasattr(new_widget, "get_sub_tab_refs"):
            for sub_attr, sub_widget in new_widget.get_sub_tab_refs().items():
                setattr(self, sub_attr, sub_widget)
                if hasattr(sub_widget, "ensure_tab_data_loaded"):
                    sub_widget.ensure_tab_data_loaded()
        self._link_tab_dependencies()
        if hasattr(new_widget, "ensure_tab_data_loaded"):
            new_widget.ensure_tab_data_loaded()

    def _pregenerate_lazy_tab(self, attr_name):
        """ساخت تب در فرصت بیکاری تا کلیک کاربر معطل نشود."""
        for spec in self._lazy_tabs:
            if spec.get("attr") != attr_name or spec.get("loaded") or spec.get("building"):
                continue
            spec["building"] = True
            QTimer.singleShot(0, lambda s=spec: self._materialize_lazy_tab(s))
            return

    def _ensure_tab_at_index(self, index):
        if index < 0:
            return None

        widget = self.tabs.widget(index)
        if widget is None:
            return None

        for spec in self._lazy_tabs:
            if spec["loaded"] or spec["placeholder"] is not widget:
                continue
            if spec.get("building"):
                return spec["placeholder"]
            spec["building"] = True
            QTimer.singleShot(0, lambda s=spec: self._materialize_lazy_tab(s))
            return spec["placeholder"]

        return widget

    def _link_tab_dependencies(self):
        """اتصال ارجاعات بین تب‌ها بعد از ساخت تنبل"""
        if self.category_tab:
            if self.product_tab:
                self.category_tab.product_tab_ref = self.product_tab
            if self.variation_tab:
                self.category_tab.variation_tab_ref = self.variation_tab

        if self.config_tab:
            self.config_tab.set_theme_callback(self.apply_theme)
            self.config_tab.set_font_size_callback(self.apply_font_size)
            if self.product_tab:
                self.config_tab.product_tab_ref = self.product_tab
            if self.variation_tab:
                self.config_tab.variation_tab_ref = self.variation_tab
            if self.category_tab:
                self.config_tab.category_tab_ref = self.category_tab
            if self.dashboard_tab:
                self.config_tab.dashboard_tab_ref = self.dashboard_tab
            if self.reconciliation_tab:
                self.config_tab.reconciliation_tab_ref = self.reconciliation_tab
            if self.properties_tab:
                self.config_tab.properties_tab_ref = self.properties_tab
            if self.customer_tab:
                self.config_tab.customer_tab_ref = self.customer_tab
            if self.order_tab:
                self.config_tab.order_tab_ref = self.order_tab

    def reload_sql_dependent_tabs(self, log_callback=None):
        """بارگذاری مجدد داده SQL در تب‌های ساخته‌شده."""
        from sync_app.core.secure_config_loader import load_secure_config
        from sync_app.core.tab_operation_guard import is_tab_active, mark_sql_reload_pending

        cfg = load_secure_config(None) or {}

        def log(msg):
            if log_callback:
                log_callback(msg)

        def run_tab(attr, label, fn):
            tab = getattr(self, attr, None)
            if tab is None:
                log(f"• {label}: هنوز باز نشده — با اولین باز کردن از دیتابیس جدید لود می‌شود")
                return
            if hasattr(tab, "config"):
                tab.config = cfg
            if is_tab_active(tab):
                fn(tab)
                log(f"• {label}: بارگذاری شروع شد")
            else:
                mark_sql_reload_pending(tab)
                log(f"• {label}: با باز کردن تب بارگذاری می‌شود")

        run_tab("product_tab", "محصولات", lambda t: t.load_products())
        run_tab("variation_tab", "متغیرها", lambda t: t.load_variations())
        run_tab("category_tab", "دسته‌بندی", lambda t: t.load_groups(silent=False, manual=False))
        run_tab("dashboard_tab", "داشبورد", lambda t: t.load_data())

        def load_properties(tab):
            tab.load_properties_preview()

        run_tab("properties_tab", "ویژگی‌ها", load_properties)
        run_tab(
            "customer_tab",
            "مشتریان",
            lambda t: t.load_site_customers(silent=True) if hasattr(t, "load_site_customers") else None,
        )
        run_tab(
            "order_tab",
            "سفارشات",
            lambda t: t.load_site_orders(silent=True) if hasattr(t, "load_site_orders") else None,
        )

        tab = getattr(self, "reconciliation_tab", None)
        if tab is None:
            log("• تطبیق: هنوز باز نشده — با اولین باز کردن از دیتابیس جدید لود می‌شود")
        elif hasattr(tab, "invalidate_stale_sql_data"):
            tab.config = cfg
            tab.invalidate_stale_sql_data()
            log("• تطبیق: داده قبلی باطل شد")

    def reload_wc_dependent_tabs(self, log_callback=None):
        """اعمال WC_URL و کلیدهای سایت فعال در همه تب‌های باز."""
        from sync_app.core.secure_config_loader import load_secure_config

        cfg = load_secure_config(None) or {}

        def log(msg):
            if log_callback:
                log_callback(msg)

        store_name = get_store_display_name(cfg)
        for attr, label in (
            ("product_tab", "محصولات"),
            ("variation_tab", "متغیرها"),
            ("category_tab", "دسته‌بندی"),
            ("dashboard_tab", "داشبورد"),
            ("properties_tab", "ویژگی‌ها"),
            ("customer_tab", "مشتریان"),
            ("order_tab", "سفارشات"),
            ("reconciliation_tab", "تطبیق"),
        ):
            tab = getattr(self, attr, None)
            if tab is None:
                continue
            if hasattr(tab, "config"):
                tab.config = dict(cfg)
            host = store_name
            log(f"• {label}: سایت فعال → {host}")

        self.refresh_header_branding()
        self.refresh_wc_connectivity(show_pending=True)

    def _tab_attr_for_widget(self, widget):
        if widget is None:
            return None
        if widget is self.home_tab:
            return "home_tab"
        for spec in self._lazy_tabs:
            attr = spec["attr"]
            if widget is getattr(self, attr, None):
                return attr
            if spec.get("placeholder") is widget:
                return attr
        return None

    def _find_tab_index_by_attr(self, attr_name: str) -> int:
        target = (attr_name or "").strip()
        if not target:
            return -1
        for idx in range(self.tabs.count()):
            if self._tab_attr_for_widget(self.tabs.widget(idx)) == target:
                return idx
        return -1

    def _save_last_active_tab(self):
        index = self.tabs.currentIndex()
        attr = self._tab_attr_for_widget(self.tabs.widget(index))
        if not attr:
            return
        try:
            cfg = load_secure_config(None) or {}
            cfg[LAST_ACTIVE_TAB_KEY] = attr
            save_secure_config(cfg)
        except Exception:
            pass

    def _schedule_save_last_active_tab(self):
        if self._restoring_active_tab or not self._tab_persistence_ready:
            return
        timer = getattr(self, "_last_tab_save_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(self._save_last_active_tab)
            self._last_tab_save_timer = timer
        timer.start()

    def _tab_label_for_attr(self, attr: str) -> str:
        if attr == "home_tab":
            return "شروع"
        for spec in self._lazy_tabs:
            if spec.get("attr") == attr:
                return str(spec.get("title") or attr).strip()
        return attr

    def _go_to_tab_attr(self, attr: str):
        index = self._find_tab_index_by_attr(attr)
        if index < 0:
            return
        if self.is_tab_navigation_locked() and index != self._tab_nav_locked_index:
            return
        if index == self.tabs.currentIndex():
            widget = self._ensure_tab_at_index(index)
            if widget is not None and hasattr(widget, "ensure_tab_data_loaded"):
                widget.ensure_tab_data_loaded()
            return
        self._restoring_active_tab = True
        try:
            self.tabs.setCurrentIndex(index)
        finally:
            self._restoring_active_tab = False

    def _prompt_restore_last_active_tab(self):
        try:
            cfg = load_secure_config(None) or {}
            saved_attr = str(cfg.get(LAST_ACTIVE_TAB_KEY) or "").strip()
            self._run_startup_prompts(cfg, saved_attr)
        except Exception as exc:
            log.warning(f"⚠️ شروع برنامه: {exc}")
            self._complete_startup_flow(None)

    def _run_startup_prompts(self, cfg, saved_attr: str):
        # پیام تطبیق قبل از باز کردن تب سنگین (مثل متغیرها) تا UI قفل نشود
        if not cfg.get(SKIP_RECON_STARTUP_PROMPT_KEY):
            from sync_app.core.reconciliation_startup_prompt import ask_reconciliation_startup

            choice = ask_reconciliation_startup(self)

            if choice.skip_prompt_next_time:
                cfg = load_secure_config(None) or {}
                cfg[SKIP_RECON_STARTUP_PROMPT_KEY] = True
                save_secure_config(cfg)

            if choice.go_to_reconciliation:
                self._complete_startup_flow("reconciliation_tab")
                return

        self._prompt_last_tab_restore(cfg, saved_attr)

    def _prompt_last_tab_restore(self, cfg, saved_attr: str):
        if not saved_attr or saved_attr == "home_tab":
            self._complete_startup_flow(None)
            return

        if cfg.get(AUTO_RESTORE_LAST_TAB_KEY):
            self._complete_startup_flow(saved_attr)
            return

        from sync_app.core.last_tab_restore_prompt import ask_restore_last_tab

        tab_label = self._tab_label_for_attr(saved_attr)
        choice = ask_restore_last_tab(self, tab_label)

        if choice.skip_prompt_next_time:
            cfg = load_secure_config(None) or {}
            cfg[AUTO_RESTORE_LAST_TAB_KEY] = True
            save_secure_config(cfg)

        if choice.go_to_last_tab:
            self._complete_startup_flow(saved_attr)
        else:
            self._complete_startup_flow(None)

    def _complete_startup_flow(self, attr_to_open: str | None):
        self._startup_dialogs_pending = False
        self._tab_persistence_ready = True

        if attr_to_open:
            self._go_to_tab_attr(attr_to_open)
        else:
            index = self.tabs.currentIndex()
            current_attr = self._tab_attr_for_widget(self.tabs.widget(index))
            saved_attr = str((load_secure_config(None) or {}).get(LAST_ACTIVE_TAB_KEY) or "").strip()
            if not (current_attr == "home_tab" and saved_attr and saved_attr != "home_tab"):
                if current_attr:
                    self._save_last_active_tab()

    def _restore_last_active_tab(self):
        """بازگردانی مستقیم — فقط برای سازگاری داخلی."""
        cfg = load_secure_config(None) or {}
        attr = str(cfg.get(LAST_ACTIVE_TAB_KEY) or "").strip()
        if not attr:
            return
        self._go_to_tab_attr(attr)

    def is_tab_navigation_locked(self) -> bool:
        return self._tab_nav_lock_count > 0

    def lock_tab_navigation(self, source_widget=None, message: str = ""):
        self._tab_nav_lock_count += 1
        if self._tab_nav_lock_count == 1:
            self._tab_nav_locked_index = self.tabs.currentIndex()
            self.tabs.tabBar().setEnabled(False)

    def unlock_tab_navigation(self, source_widget=None):
        self._tab_nav_lock_count = max(0, self._tab_nav_lock_count - 1)
        if self._tab_nav_lock_count == 0:
            self._tab_nav_locked_index = -1
            self.tabs.tabBar().setEnabled(True)

    def _on_tab_index_changed(self, index):
        if index < 0:
            return
        if getattr(self, "_license_renewal_required", False):
            lic_idx = self._find_tab_index_by_attr("license_tab")
            if lic_idx >= 0 and index != lic_idx:
                self.tabs.blockSignals(True)
                try:
                    self.tabs.setCurrentIndex(lic_idx)
                finally:
                    self.tabs.blockSignals(False)
                return
        if (
            self.is_tab_navigation_locked()
            and self._tab_nav_locked_index >= 0
            and index != self._tab_nav_locked_index
        ):
            self.tabs.blockSignals(True)
            try:
                self.tabs.setCurrentIndex(self._tab_nav_locked_index)
            finally:
                self.tabs.blockSignals(False)
            from sync_app.core.tab_operation_guard import warn_tab_switch_blocked
            warn_tab_switch_blocked(self)
            return
        widget = self._ensure_tab_at_index(index)
        if widget is None:
            return
        if hasattr(widget, "ensure_tab_data_loaded"):
            widget.ensure_tab_data_loaded()
        self.on_tab_changed(index)
        self._schedule_save_last_active_tab()

    def on_tab_changed(self, index):
        current_widget = self.tabs.widget(index)
        if hasattr(current_widget, 'check_license'):
            current_widget.check_license()
        if getattr(self, '_startup_dialogs_pending', False):
            return
        if hasattr(current_widget, 'ensure_initial_variations_loaded'):
            current_widget.ensure_initial_variations_loaded()

    # نگاشت کلیدواژه‌های شناخته‌شده به تب گروهی‌ای که الان توش هستن — بعد از
    # جمع‌وجورسازی تب‌ها، این تب‌ها دیگه سطح اول نیستن.
    _HUB_KEYWORD_MAP = {
        "sync_hub_tab": ["دسته", "محصول", "ویژگی", "متغیر", "مشتری", "سفارش"],
        "smart_assistant_hub_tab": ["رسانه", "انتشار", "سئو", "بازاریاب", "مشاور"],
    }

    def go_to_tab_by_keyword(self, keyword):
        target = (keyword or "").strip()
        if not target:
            return
        if self.is_tab_navigation_locked():
            from sync_app.core.tab_operation_guard import warn_tab_switch_blocked
            warn_tab_switch_blocked(self)
            return

        for idx in range(self.tabs.count()):
            title = self.tabs.tabText(idx)
            if target in title:
                self.tabs.setCurrentIndex(idx)
                return

        # پیدا نشد در سطح اول — طبق نگاشت شناخته‌شده، تب گروهی مربوطه رو باز کن
        for hub_attr, keywords in self._HUB_KEYWORD_MAP.items():
            if not any(kw in target or target in kw for kw in keywords):
                continue
            idx = self._find_tab_index_by_attr(hub_attr)
            if idx is None:
                continue
            self._ensure_tab_at_index(idx)
            self.tabs.setCurrentIndex(idx)

            def _select_inner(i=idx, t=target):
                inner = self.tabs.widget(i)
                fn = getattr(inner, "select_sub_tab_by_keyword", None)
                if callable(fn):
                    fn(t)

            QTimer.singleShot(80, _select_inner)
            return

    def apply_theme(self, theme_name):
        self._apply_runtime_styles(theme_name=theme_name)

    def apply_font_size(self, font_size):
        # اعمال سایز فونت جدید بدون تغییر تم فعلی
        self._apply_runtime_styles(font_setting=font_size)

    def _compute_responsive_font_size(self, base_size):
        # در ابعاد خیلی کوچک، فونت کمی کوچک‌تر می‌شود تا UI نشکند
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        if w <= 760 or h <= 480:
            scale = 0.78
        elif w <= 980 or h <= 620:
            scale = 0.88
        else:
            scale = 1.0
        return max(10, int(round(base_size * scale)))

    def _apply_runtime_styles(self, theme_name=None, font_setting=None):
        cfg = load_secure_config(None) or {}

        selected_theme = theme_name if theme_name in ALLOWED_THEMES else cfg.get("APP_THEME", "navy")
        if selected_theme not in ALLOWED_THEMES:
            selected_theme = "navy"

        raw_font_setting = cfg.get("APP_FONT_SIZE", 14) if font_setting is None else font_setting
        base_font_size, is_bold = resolve_user_font_pref(raw_font_setting)
        effective_font_size = self._compute_responsive_font_size(base_font_size)

        signature = (selected_theme, effective_font_size, is_bold)
        if signature == self._applied_style_signature:
            return

        self.setStyleSheet(build_theme_stylesheet(selected_theme, effective_font_size, is_bold))

        tab_bar = self.tabs.tabBar()
        if isinstance(tab_bar, AdaptiveTabBar):
            tab_bar.configure(effective_font_size)
        else:
            tab_bar.setMinimumHeight(max(58, effective_font_size + 46))
        tab_bar.style().unpolish(tab_bar)
        tab_bar.style().polish(tab_bar)
        tab_bar.update()
        self._normalize_button_ui(effective_font_size)
        from sync_app.core.compact_icon_action_bar import CompactIconActionBar, CompactCaptionButton

        for bar in self.findChildren(CompactIconActionBar):
            bar.refresh_theme_styles()
        for btn in self.findChildren(CompactCaptionButton):
            btn.refresh_theme_styles()
        self._apply_header_theme(selected_theme)
        self._apply_header_typography(selected_theme, effective_font_size, is_bold)
        self._repaint_connectivity_badges()
        if self.dashboard_tab is not None and hasattr(self.dashboard_tab, "apply_runtime_font"):
            self.dashboard_tab.apply_runtime_font(effective_font_size, is_bold)
        self._applied_style_signature = signature

    def _normalize_button_ui(self, effective_font_size):
        # یکپارچه‌سازی دکمه‌ها در کل برنامه
        primary_h = max(40, effective_font_size + 26)
        flat_h = max(32, effective_font_size + 16)

        for btn in self.findChildren(QPushButton):
            if btn.property("compactActionBtn"):
                btn.setMinimumHeight(max(44, effective_font_size + 22))
                btn.setProperty("appUnifiedButton", False)
                btn.setStyleSheet("")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()
                continue
            if btn.objectName() == "reconMiddleBtn":
                btn.setMinimumHeight(max(38, effective_font_size + 12))
                btn.setProperty("appUnifiedButton", False)
                btn.setProperty("flat", False)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()
                continue
            if btn.objectName() in {"reconRefreshBtn", "reconQuickSkuBtn", "reconCommitBtn"}:
                btn.setMinimumHeight(max(44, effective_font_size + 22))
                btn.setProperty("appUnifiedButton", False)
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()
                continue
            if btn.isFlat():
                btn.setMinimumHeight(flat_h)
                btn.setProperty("appUnifiedButton", False)
            else:
                btn.setMinimumHeight(primary_h)
                btn.setProperty("appUnifiedButton", True)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_runtime_styles()

    def _apply_header_theme(self, theme_name):
        palette = THEME_PALETTE.get(theme_name, THEME_PALETTE["navy"])
        primary = palette["primary"]
        hover = palette["hover"]
        pressed = palette["pressed"]
        accent = "#4ade80" if theme_name == "green" else "#60a5fa"
        if theme_name == "red":
            accent = "#fca5a5"
            bg = (
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                " stop:0 #7d1020, stop:0.5 #a80f2d, stop:1 #bf1a34);"
            )
        else:
            bg = (
                "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                f" stop:0 {pressed}, stop:0.5 {primary}, stop:1 {hover});"
            )
        self.header_frame.setStyleSheet(
            bg
            + f" QLabel#headerVersionLatest {{"
            f"  color: {accent}; font-size: 10px; font-weight: 600; background: transparent;"
            f" }}"
            f" QPushButton#headerUpdateBtn {{"
            f"  background: #f59e0b; color: #1e1b4b; border: 2px solid #ffffff;"
            f"  border-radius: 10px; padding: 4px 14px; font-size: 12px; font-weight: 800;"
            f"  min-height: 28px;"
            f" }}"
            f" QPushButton#headerUpdateBtn:hover {{ background: #fbbf24; color: #0f172a; }}"
        )
        self.separator.setStyleSheet(f"background: {palette['soft_border']}; border: none;")

    def _refresh_header_license_expiry(self, *, subtitle_size: int | None = None) -> None:
        label = getattr(self, "header_license_expiry", None)
        if label is None:
            return
        text, expired, days_left = LicenseTab.get_license_expiry_header()
        label.setText(text)
        label.setVisible(bool(text))
        size = subtitle_size
        if size is None:
            cfg = load_secure_config(None) or {}
            size, _ = resolve_user_font_pref(cfg.get("APP_FONT_SIZE", 14))
            size = max(12, size - 1)
        if not text:
            return
        if expired:
            color = "#fecaca"
        elif days_left is not None and days_left <= 30:
            color = "#fde68a"
        else:
            color = "rgba(255,255,255,0.82)"
        label.setStyleSheet(
            f"color: {color}; font-size: {size}px; font-weight: 600; background: transparent;"
        )
        if LicenseTab.is_license_server_denied():
            if not getattr(self, "_license_renewal_required", False):
                cache_status = "expired"
                try:
                    details = LicenseTab.get_license_details()
                    cache_status = str(details.get("status") or "expired")
                except Exception:
                    pass
                self._enter_license_renewal_mode(cache_status, show_dialog=False)
        elif getattr(self, "_license_renewal_required", False) and not LicenseTab.is_license_server_denied():
            self._clear_license_renewal_lock()

    def _enter_license_renewal_mode(self, reason: str = "expired", *, show_dialog: bool = True) -> None:
        if getattr(self, "_license_renewal_required", False) and not show_dialog:
            self._stop_background_tab_work()
            self._go_to_tab_attr("license_tab")
            return
        if getattr(self, "_license_renewal_required", False):
            return
        self._license_renewal_required = True
        self._stop_background_tab_work()
        self._go_to_tab_attr("license_tab")
        lic_tab = getattr(self, "license_tab", None)
        if lic_tab is not None and hasattr(lic_tab, "refresh_license_display"):
            lic_tab.refresh_license_display()
        if show_dialog:
            from PyQt5.QtWidgets import QMessageBox

            from sync_app.core.license_remote import humanize_license_error

            QMessageBox.critical(
                self,
                "تمدید لایسنس",
                humanize_license_error(reason),
            )

    def _clear_license_renewal_lock(self) -> None:
        self._license_renewal_required = False

    def _stop_background_tab_work(self) -> None:
        stops = (
            ("category_tab", "_stop_groups_load", "_loading_groups"),
            ("product_tab", "_stop_products_load", "_loading_products"),
            ("variation_tab", "_stop_variations_load", "_loading_variations"),
            ("properties_tab", "_stop_properties_load", "_loading_properties"),
        )
        for attr, stop_fn, flag in stops:
            tab = getattr(self, attr, None)
            if tab is None:
                continue
            if getattr(tab, flag, False) and hasattr(tab, stop_fn):
                getattr(tab, stop_fn)()

    def _apply_header_typography(self, theme_name, effective_font_size, is_bold):
        title_size = max(18, effective_font_size + 8)
        subtitle_size = max(12, effective_font_size - 1)
        badge_size = max(11, effective_font_size - 2)
        title_weight = 900 if is_bold else 800

        self.header_title.setStyleSheet(
            f"color: #ffffff; font-size: {title_size}px; font-weight: {title_weight}; "
            "letter-spacing: 0.5px; background: transparent;"
        )
        self.header_subtitle.setStyleSheet(
            f"color: rgba(255,255,255,0.88); font-size: {subtitle_size}px; font-weight: 600; "
            "background: transparent;"
        )
        self.header_username_label.setStyleSheet(
            f"color: #ffffff; font-size: {subtitle_size}px; font-weight: 600; "
            "background: transparent;"
        )
        self._refresh_header_license_expiry(subtitle_size=subtitle_size)
        version_size = max(11, effective_font_size - 2)
        self.header_version_label.setStyleSheet(
            f"color: #ffffff; font-size: {version_size}px; font-weight: 700; "
            "background: transparent; padding: 0 4px;"
        )
        if hasattr(self, "header_update_spinner"):
            self.header_update_spinner.apply_style(max(11, effective_font_size - 2))
        self._refresh_header_update_ui()
        from sync_app.core.brand_assets import HEADER_FRAME_HEIGHT, HEADER_LOGO_HEIGHT, brand_logo_pixmap

        self.header_frame.setFixedHeight(HEADER_FRAME_HEIGHT)
        logo_size = HEADER_LOGO_HEIGHT
        header_logo = brand_logo_pixmap(logo_size, light_background=False)
        if not header_logo.isNull():
            self._logo_source_pixmap = header_logo
            self.logo_label.setPixmap(header_logo)
            self.logo_label.setFixedSize(
                max(header_logo.width(), HEADER_LOGO_HEIGHT),
                HEADER_FRAME_HEIGHT,
            )
        elif self._logo_source_pixmap is not None:
            pixmap = _scale_brand_logo(self._logo_source_pixmap, logo_size)
            self.logo_label.setPixmap(pixmap)
            self.logo_label.setFixedSize(
                max(pixmap.width(), HEADER_LOGO_HEIGHT),
                HEADER_FRAME_HEIGHT,
            )
        elif (self.logo_label.text() or "").strip():
            self.logo_label.setFixedSize(HEADER_LOGO_HEIGHT, HEADER_FRAME_HEIGHT)
            self.logo_label.setStyleSheet(
                f"color: white; font-size: {max(18, effective_font_size + 4)}px; font-weight: 900;"
                " background: rgba(255,255,255,0.18); border-radius: 10px;"
                " padding: 4px;"
            )
        else:
            self.logo_label.setFixedSize(HEADER_LOGO_HEIGHT, HEADER_FRAME_HEIGHT)

        self.brand_block.setFixedHeight(HEADER_FRAME_HEIGHT)
        self.header_title.setMinimumHeight(HEADER_FRAME_HEIGHT)

        self.wc_status_indicator.setMinimumHeight(HEADER_BADGE_HEIGHT)
        self.sql_status_indicator.setMinimumHeight(HEADER_BADGE_HEIGHT)

    def _store_badge_prefix(self) -> str:
        from sync_app.core.integrations.commerce_provider import is_prestashop

        cfg = load_secure_config(None) or {}
        return "PS" if is_prestashop(cfg) else "Woo"

    def _wc_host_short(self) -> str:
        from urllib.parse import urlparse

        from sync_app.core.integrations.commerce_provider import is_prestashop
        from sync_app.core.wc_api_helper import normalize_wc_store_url

        cfg = load_secure_config(None) or {}
        if is_prestashop(cfg):
            base = str(cfg.get("PS_URL") or "").strip().rstrip("/")
        else:
            base = normalize_wc_store_url(cfg.get("WC_URL", ""))
        if not base:
            return "تنظیم نشده"
        host = urlparse(base).netloc
        if host:
            return host
        return base.replace("https://", "").replace("http://", "").split("/")[0]

    def _wc_badge_lines(self, ok, *, pending=False) -> tuple[str, str]:
        prefix = self._store_badge_prefix()
        if pending or ok is None:
            return f"{prefix} ...", "در حال بررسی..."
        if ok:
            host = self._wc_host_short()
            if self._wc_last_ms > 0:
                return f"{prefix} آنلاین", f"{host} · {self._wc_last_ms:.0f}ms"
            return f"{prefix} آنلاین", host
        return wc_badge_offline_lines(self._wc_last_msg or "", prefix=prefix)

    def _build_wc_tooltip(self, wc_ok: bool, wc_msg: str) -> str:
        from sync_app.core.integrations.commerce_provider import is_prestashop, store_platform_label

        cfg = load_secure_config(None) or {}
        ps_mode = is_prestashop(cfg)
        platform_label = store_platform_label(cfg)

        lines = []
        msg = (wc_msg or "").strip()
        if msg:
            lines.append(msg)
        if not wc_ok and msg:
            from sync_app.core.connectivity_service import wc_offline_tooltip

            host_key = "PS_URL" if ps_mode else "WC_URL"
            hint = wc_offline_tooltip(
                msg, host=(cfg.get(host_key) or "").strip(),
                target="PrestaShop" if ps_mode else "WooCommerce",
            )
            if hint and hint not in lines:
                lines.append(hint)
        age = connectivity_age_label_fa()
        if age:
            lines.append(f"آخرین بررسی: {age}")
        lines.append(f"کلیک: تنظیمات {platform_label}")
        lines.append("دوبار کلیک: بررسی فوری")
        return "\n".join(lines)

    def _build_sql_tooltip(self, sql_ok: bool, sql_msg: str) -> str:
        lines = []
        msg = (sql_msg or "").strip()
        if msg:
            lines.append(msg)
        age = connectivity_age_label_fa()
        if age:
            lines.append(f"آخرین بررسی: {age}")
        lines.append("کلیک: تنظیمات SQL")
        lines.append("دوبار کلیک: بررسی فوری")
        return "\n".join(lines)

    def _paint_header_badge(self, label, ok, prefix, sub_line, *, pending=False, tooltip="", status_line=None):
        """badge بالای صفحه sql/woo."""
        timer = self._offline_blink_timers.pop(label, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

        sub_raw = (sub_line or "").strip()
        if status_line:
            status = status_line.strip()
        elif pending or ok is None:
            status = f"{prefix} ..."
            if not sub_raw:
                sub_raw = "در حال بررسی..."
        elif ok:
            status = f"{prefix} آنلاین"
            if not sub_raw:
                sub_raw = "—"
        else:
            status = f"{prefix} آفلاین"
            if not sub_raw:
                sub_raw = "—"

        if pending or ok is None:
            label.setStyleSheet(BADGE_PENDING_STYLE_TALL)
            label.setProperty("role", "header-badge")
            label.setProperty("connState", "checking")
        elif ok:
            label.setStyleSheet(BADGE_ONLINE_STYLE_TALL)
            label.setProperty("role", "header-badge")
            label.setProperty("connState", "online")
        else:
            label.setStyleSheet(BADGE_OFFLINE_STYLE_TALL)
            label.setProperty("role", "header-badge")
            label.setProperty("connState", "offline")

        sub = label.fontMetrics().elidedText(sub_raw, Qt.ElideMiddle, HEADER_BADGE_SUB_ELIDE)
        label.setTextFormat(Qt.RichText)
        label.setText(
            f'<div style="text-align:center;line-height:1.15;">'
            f'<span style="font-size:12px;font-weight:700;">{status}</span><br>'
            f'<span style="font-size:10px;font-weight:600;">{sub}</span>'
            f"</div>"
        )
        label.setMinimumHeight(HEADER_BADGE_HEIGHT)

        if tooltip:
            label.setToolTip(tooltip)
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _paint_sql_badge(self, ok, *, pending=False, tooltip=""):
        db = (self._sql_db_name or "").strip()
        if not db and pending:
            db = "..."
        self._paint_header_badge(
            self.sql_status_indicator, ok, "SQL", db, pending=pending, tooltip=tooltip
        )

    def _paint_wc_badge(self, ok, *, pending=False, tooltip=""):
        status_line, sub = self._wc_badge_lines(ok, pending=pending)
        self._paint_header_badge(
            self.wc_status_indicator,
            ok,
            self._store_badge_prefix(),
            sub,
            pending=pending,
            tooltip=tooltip,
            status_line=status_line,
        )

    def _paint_connectivity_badge(self, label, ok, prefix, *, pending=False, tooltip=""):
        timer = self._offline_blink_timers.pop(label, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

        if pending or ok is None:
            label.setText(f"{prefix}: ...")
            label.setStyleSheet(BADGE_PENDING_STYLE)
            label.setProperty("role", "badge-pending")
        elif ok:
            label.setText(f"{prefix} آنلاین")
            label.setStyleSheet(BADGE_ONLINE_STYLE)
            label.setProperty("role", "badge-success")
        else:
            label.setText(f"{prefix} آفلاین")
            label.setStyleSheet(BADGE_OFFLINE_STYLE)
            label.setProperty("role", "badge-error")

        if tooltip:
            label.setToolTip(tooltip)
        label.style().unpolish(label)
        label.style().polish(label)
        label.update()

    def _repaint_connectivity_badges(self):
        self._paint_sql_badge(
            self._sql_display_ok,
            pending=self._sql_display_ok is None,
            tooltip=self._sql_tooltip,
        )
        self._paint_wc_badge(
            self._wc_display_ok,
            pending=self._wc_display_ok is None,
            tooltip=self._wc_tooltip,
        )

    def _debounce_status(self, ok, streak_attr, was_ok):
        if ok:
            setattr(self, streak_attr, 0)
            return True
        streak = getattr(self, streak_attr) + 1
        setattr(self, streak_attr, streak)
        if was_ok is True and streak < 2:
            return True
        return False

    def _set_connectivity_badge(self, label, ok, online_text, offline_text):
        """سازگاری با کد قدیمی."""
        if label is self.sql_status_indicator:
            self._paint_sql_badge(ok)
        else:
            self._paint_wc_badge(ok)

    def refresh_header_branding(self):
        """نام‌کاربر و سایت فعال هدر — عنوان اصلی («همگام‌ساز پیچا») ثابت می‌ماند."""
        from sync_app.core.user_profile import get_current_profile_display_name

        name = get_store_display_name()
        self.header_subtitle.setText(f"🌐 {name}")
        profile_name = get_current_profile_display_name() or "—"
        self.header_username_label.setText(f"👤 {profile_name}")
        self.setWindowTitle(get_app_window_title())
        tray = getattr(self, "tray_icon", None)
        if tray is not None:
            tray.setToolTip(f"{name} — همگام‌سازی فعال")

    def refresh_header_connectivity(self):
        """پروب کامل SQL + Woo — برای سازگاری با کدهای قدیمی."""
        self.refresh_wc_connectivity(show_pending=False)
        self.refresh_sql_connectivity(show_pending=False)

    def refresh_wc_connectivity(self, *, show_pending=True, fast=False):
        if self._wc_check_thread is not None:
            self._wc_probe_pending = True
            return
        if show_pending:
            from sync_app.core.integrations.commerce_provider import store_platform_label

            platform_label = store_platform_label(load_secure_config(None) or {})
            self._paint_wc_badge(None, pending=True, tooltip=f"در حال بررسی اتصال {platform_label}...")
        cfg = load_secure_config(None) or {}
        from sync_app.core.login_window import ConnectivityWorker

        self._wc_check_thread = QThread(self)
        self._wc_check_worker = ConnectivityWorker(cfg, mode="wc", fast=fast)
        self._wc_check_worker.moveToThread(self._wc_check_thread)
        self._wc_check_thread.started.connect(self._wc_check_worker.run)
        self._wc_check_worker.finished.connect(self._on_wc_probe_finished)
        self._wc_check_worker.finished.connect(self._wc_check_thread.quit)
        self._wc_check_worker.finished.connect(self._wc_check_worker.deleteLater)
        self._wc_check_thread.finished.connect(self._wc_check_thread.deleteLater)
        self._wc_check_thread.finished.connect(self._on_wc_probe_thread_finished)
        self._wc_check_thread.start()

    def refresh_sql_connectivity(self, *, show_pending=True):
        if self._sql_check_thread is not None:
            return
        if show_pending:
            self._paint_sql_badge(None, pending=True, tooltip="در حال بررسی اتصال SQL...")
        cfg = load_secure_config(None) or {}
        from sync_app.core.login_window import ConnectivityWorker

        self._sql_check_thread = QThread(self)
        self._sql_check_worker = ConnectivityWorker(cfg, mode="sql")
        self._sql_check_worker.moveToThread(self._sql_check_thread)
        self._sql_check_thread.started.connect(self._sql_check_worker.run)
        self._sql_check_worker.finished.connect(self._on_sql_probe_finished)
        self._sql_check_worker.finished.connect(self._sql_check_thread.quit)
        self._sql_check_worker.finished.connect(self._sql_check_worker.deleteLater)
        self._sql_check_thread.finished.connect(self._sql_check_thread.deleteLater)
        self._sql_check_thread.finished.connect(self._on_sql_probe_thread_finished)
        self._sql_check_thread.start()

    def _on_wc_probe_finished(self, _sql_ok, _sql_msg, wc_ok, wc_msg):
        self._apply_wc_probe_result(bool(wc_ok), str(wc_msg or ""))

    def _on_sql_probe_finished(self, sql_ok, sql_msg, _wc_ok, _wc_msg):
        self._apply_sql_probe_result(bool(sql_ok), str(sql_msg or ""))

    def _apply_wc_probe_result(self, wc_ok: bool, wc_msg: str):
        cached = load_connectivity_cache()
        self._wc_last_ms = float(cached.get("wc_ms") or 0)
        self._wc_last_probe_at = float(cached.get("at") or 0)
        self._wc_last_msg = str(wc_msg or "")
        self._wc_display_ok = bool(wc_ok)
        self._last_wc_ok = bool(wc_ok)
        self._wc_fail_streak = 0 if wc_ok else self._wc_fail_streak + 1
        self._wc_tooltip = self._build_wc_tooltip(wc_ok, wc_msg)
        self._paint_wc_badge(self._wc_display_ok, pending=False, tooltip=self._wc_tooltip)

        if self.dashboard_tab is not None:
            sql_show = self._sql_display_ok if self._sql_display_ok is not None else bool(self._last_sql_ok)
            self.dashboard_tab.update_connectivity_quick(bool(sql_show), bool(self._wc_display_ok))

        interval = 18000 if wc_ok else 8000
        if self._header_wc_timer.interval() != interval:
            self._header_wc_timer.setInterval(interval)
            self._header_wc_timer.start()

    def _apply_sql_probe_result(self, sql_ok: bool, sql_msg: str):
        sql_show = self._debounce_status(sql_ok, "_sql_fail_streak", self._sql_display_ok)
        self._sql_display_ok = sql_show
        self._last_sql_ok = bool(sql_ok)
        self._sql_tooltip = self._build_sql_tooltip(bool(sql_show), sql_msg if sql_ok or not sql_show else f"{sql_msg}\n(یک timeout — در حال بررسی مجدد)")

        import re as _re
        _db_match = _re.search(r"DB=([^|]+)", sql_msg or "")
        _db_name = _db_match.group(1).strip() if _db_match else ""
        self._sql_db_name = _db_name if sql_show else ""
        self._set_sql_db_display(self._sql_db_name)

        if self.dashboard_tab is not None:
            wc_show = self._wc_display_ok if self._wc_display_ok is not None else bool(self._last_wc_ok)
            self.dashboard_tab.update_connectivity_quick(bool(sql_show), bool(wc_show))

        interval = 60000 if sql_show else 20000
        if self._header_sql_timer.interval() != interval:
            self._header_sql_timer.setInterval(interval)
            self._header_sql_timer.start()

    def _on_wc_probe_thread_finished(self):
        self._wc_check_thread = None
        self._wc_check_worker = None
        if self._wc_probe_pending:
            self._wc_probe_pending = False
            QTimer.singleShot(80, lambda: self.refresh_wc_connectivity(show_pending=False))

    def _on_sql_probe_thread_finished(self):
        self._sql_check_thread = None
        self._sql_check_worker = None

    def _on_header_connectivity_finished(self, sql_ok, sql_msg, wc_ok, wc_msg):
        self._apply_sql_probe_result(bool(sql_ok), str(sql_msg or ""))
        self._apply_wc_probe_result(bool(wc_ok), str(wc_msg or ""))

    def _on_header_connectivity_thread_finished(self):
        self._header_check_thread = None
        self._header_check_worker = None
        if self._header_probe_pending:
            self._header_probe_pending = False
            QTimer.singleShot(80, self.refresh_header_connectivity)

    def _badge_connectivity_state(self, label, cached_ok):
        """وضعیت badge: online/offline/pending."""
        if label is self.sql_status_indicator and self._sql_display_ok is not None:
            cached_ok = self._sql_display_ok
        elif label is self.wc_status_indicator and self._wc_display_ok is not None:
            cached_ok = self._wc_display_ok

        if cached_ok is True:
            return "online"
        if cached_ok is False:
            return "offline"
        return "pending"

    def sql_connectivity_state(self):
        return self._badge_connectivity_state(self.sql_status_indicator, self._last_sql_ok)

    def wc_connectivity_state(self):
        return self._badge_connectivity_state(self.wc_status_indicator, self._last_wc_ok)

    def apply_connectivity_probe(self, sql_ok, sql_msg, wc_ok, wc_msg):
        """به‌روزرسانی badge بعد از پروب زنده (قبل از sync)."""
        self._apply_sql_probe_result(bool(sql_ok), str(sql_msg or ""))
        self._apply_wc_probe_result(bool(wc_ok), str(wc_msg or ""))

    def is_sql_online(self):
        return self.sql_connectivity_state() == "online"

    def is_wc_online(self):
        return self.wc_connectivity_state() == "online"

    def paint_connectivity_badge_clone(self, label, which: str) -> None:
        """همان ظاهر badge هدر — بدون پروب جدید."""
        which = (which or "").strip().lower()
        if which == "sql":
            self._paint_header_badge(
                label,
                self._sql_display_ok,
                "SQL",
                (self._sql_db_name or "").strip(),
                pending=self.sql_connectivity_state() == "pending",
                tooltip=getattr(self, "_sql_tooltip", ""),
            )
        else:
            pending = self.wc_connectivity_state() == "pending"
            status_line, sub = self._wc_badge_lines(self._wc_display_ok, pending=pending)
            self._paint_header_badge(
                label,
                self._wc_display_ok,
                self._store_badge_prefix(),
                sub,
                pending=pending,
                tooltip=getattr(self, "_wc_tooltip", ""),
                status_line=status_line if not pending else None,
            )

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.MouseButtonDblClick:
            if obj is self.wc_status_indicator:
                self.refresh_wc_connectivity()
                return True
            if obj is self.sql_status_indicator:
                self.refresh_sql_connectivity()
                return True
        if event.type() == QEvent.MouseButtonPress:
            if obj is self.sql_status_indicator:
                self._open_settings_section("sql")
                return True
            elif obj is self.wc_status_indicator:
                self._open_settings_section("woo")
                return True
            elif obj is self.link_warning_badge:
                self._show_link_warning_details()
                return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        from PyQt5.QtCore import QEvent
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(120, lambda: self.refresh_wc_connectivity(show_pending=False))

    def _refresh_header_autosync_badge(self):
        try:
            cfg = load_secure_config(None) or {}
        except Exception:
            self.header_autosync_badge.setVisible(False)
            return

        if not cfg.get("AUTO_ENABLED"):
            self.header_autosync_badge.setVisible(False)
            return

        if cfg.get("AUTO_SYNC_RUNNING"):
            from datetime import datetime
            is_stale = False
            since_raw = str(cfg.get("AUTO_SYNC_RUNNING_SINCE") or "").strip()
            if since_raw:
                try:
                    since_at = datetime.fromisoformat(since_raw)
                    if (datetime.now() - since_at).total_seconds() > 2 * 3600:
                        is_stale = True
                except Exception:
                    is_stale = True
            else:
                # پرچمی که زمان ثبت نداره، حتماً از یه نسخه‌ی قدیمی‌تر یا
                # یه بستن ناگهانی مونده — قابل‌اعتماد نیست.
                is_stale = True

            if not is_stale:
                self.header_autosync_badge.setText("⚡ همگام‌سازی خودکار در حال انجام...")
                self.header_autosync_badge.setVisible(True)
                return
            else:
                # پاک‌کردن پرچم گیرکرده تا دفعه‌ی بعد دوباره این چک لازم نشه
                try:
                    cfg["AUTO_SYNC_RUNNING"] = False
                    cfg.pop("AUTO_SYNC_RUNNING_SINCE", None)
                    save_secure_config(cfg)
                except Exception:
                    pass

        next_at_raw = str(cfg.get("AUTO_NEXT_RUN_AT") or "").strip()
        if not next_at_raw:
            self.header_autosync_badge.setText("⚡ همگام‌سازی خودکار فعال")
            self.header_autosync_badge.setVisible(True)
            return

        try:
            from datetime import datetime
            next_at = datetime.fromisoformat(next_at_raw)
            remaining = (next_at - datetime.now()).total_seconds()
        except Exception:
            self.header_autosync_badge.setText("⚡ همگام‌سازی خودکار فعال")
            self.header_autosync_badge.setVisible(True)
            return

        if remaining <= 0:
            text = "⚡ همگام‌سازی خودکار: در حال اجرا..."
        else:
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            if hours > 0:
                text = f"⚡ همگام‌سازی خودکار: {hours} ساعت و {minutes} دقیقه مانده"
            else:
                text = f"⚡ همگام‌سازی خودکار: {minutes} دقیقه مانده"
        self.header_autosync_badge.setText(text)
        self.header_autosync_badge.setVisible(True)

    def _send_due_content_calendar_posts(self):
        """چکِ پس‌زمینه‌ی پست‌های زمان‌بندی‌شده‌ی سررسیده — هر ارسالِ واقعی
        در Threadِ جدا انجام می‌شه تا UI هیچ‌وقت قفل نشه."""
        from sync_app.core.content_calendar_store import due_posts, update_post_status, STATUS_SENT, STATUS_FAILED

        try:
            posts = due_posts()
        except Exception:
            return
        if not posts:
            return

        try:
            cfg = load_secure_config(None) or {}
        except Exception:
            return

        from sync_app.core.telegram_poster import (
            TELEGRAM_BOT_TOKEN_KEY,
            TELEGRAM_CHAT_ID_KEY,
            TELEGRAM_PROXY_URL_KEY,
            send_post,
        )

        token = str(cfg.get(TELEGRAM_BOT_TOKEN_KEY) or "").strip()
        chat_id = str(cfg.get(TELEGRAM_CHAT_ID_KEY) or "").strip()
        proxy_url = str(cfg.get(TELEGRAM_PROXY_URL_KEY) or "").strip()
        if not token or not chat_id:
            for post in posts:
                update_post_status(
                    post.get("id"), STATUS_FAILED,
                    error="توکن بات یا شناسه‌ی چتِ تلگرام در تنظیمات وارد نشده.",
                )
            return

        from sync_app.core.threading_helper import run_in_thread

        def _worker(posts_to_send):
            results = []
            for post in posts_to_send:
                ok, msg = send_post(
                    token, chat_id, post.get("text") or "", photo_path=post.get("image_path") or "",
                    proxy_url=proxy_url,
                )
                results.append((post.get("id"), ok, msg))
            return results

        def on_complete(results):
            for post_id, ok, msg in results:
                update_post_status(post_id, STATUS_SENT if ok else STATUS_FAILED, error=None if ok else msg)

        run_in_thread(_worker, posts, on_complete=on_complete)

    def _refresh_link_warning(self):
        """محاسبه‌ی تعداد موارد لینک‌نشده در پس‌زمینه — فقط خواندنی، UI را قفل نمی‌کند."""
        try:
            cfg = load_secure_config(None) or {}
        except Exception:
            return
        if not cfg.get("SELECTED_SUB_GROUPS"):
            self.link_warning_badge.setVisible(False)
            return

        # فوراً یه نشونه‌ی «در حال بررسی» بده — تا معلوم بشه داره کار می‌کنه،
        # نه اینکه انگار هیچ‌اتفاقی نیفتاده.
        self.link_warning_badge.setText("⏳ در حال بررسی لینک‌ها...")
        self.link_warning_badge.setVisible(True)

        def _worker():
            from sync_app.core.auto_sync_scope import compute_unlinked_counts
            return compute_unlinked_counts(cfg)

        def _done(counts):
            self._link_warning_counts = counts
            total = sum(counts.values())
            try:
                from sync_app.core.sync_utils import log
                log.info(f"ℹ️ بررسی موارد لینک‌نشده انجام شد: {counts} (جمع={total})")
            except Exception:
                pass
            if total <= 0:
                self.link_warning_badge.setVisible(False)
                return
            self.link_warning_badge.setText(f"⚠️ {total:,} مورد بدون لینک")
            self.link_warning_badge.setVisible(True)

        def _fail(msg):
            try:
                from sync_app.core.sync_utils import log
                log.warning(f"⚠️ بررسی موارد لینک‌نشده (هشدار هدر) ناموفق بود: {msg}")
            except Exception:
                pass
            self.link_warning_badge.setVisible(False)

        try:
            from sync_app.core.threading_helper import run_in_thread
            run_in_thread(_worker, on_complete=_done, on_error=_fail)
        except Exception:
            self.link_warning_badge.setVisible(False)

    def _show_link_warning_details(self):
        from PyQt5.QtWidgets import QMessageBox
        counts = getattr(self, "_link_warning_counts", None) or {}
        lines = []
        if counts.get("products"):
            lines.append(f"📦 {counts['products']:,} محصول لینک نشده")
        if counts.get("categories"):
            lines.append(f"📂 {counts['categories']:,} دسته‌بندی لینک نشده")
        body = "\n".join(lines) if lines else "موردی یافت نشد."
        QMessageBox.information(
            self, "موارد بدون لینک به فروشگاه",
            body + "\n\n(متغیرها عمداً اینجا نیست چون نگاشت دقیقی براشون نداریم — "
            "برای بررسی متغیرها، خودِ تب «متغیرها» و فیلتر لینک‌نشده رو ببینید.)\n\n"
            "برای دیدن ردیف‌های دقیق، از فیلتر «لینک‌نشده» در تب‌های محصولات/دسته‌بندی‌ها استفاده کنید.",
        )

    def _go_to_config_tab(self):
        """رفتن به تب تنظیمات — حتی اگر هنوز lazy-load نشده باشد."""
        for idx in range(self.tabs.count()):
            if "تنظیمات" in self.tabs.tabText(idx):
                self.tabs.setCurrentIndex(idx)
                self._ensure_tab_at_index(idx)
                return self.config_tab
        return None

    def _blink_widget_stylesheet(self, widget, original_style, highlight_style, *, blinks=6, interval_ms=300):
        blink_count = [0]

        def _blink():
            if blink_count[0] % 2 == 0:
                widget.setStyleSheet(highlight_style)
            else:
                widget.setStyleSheet(original_style)
            blink_count[0] += 1
            if blink_count[0] >= blinks:
                widget.setStyleSheet(original_style)
                timer.stop()
                timer.deleteLater()

        timer = QTimer(self)
        timer.timeout.connect(_blink)
        timer.start(interval_ms)
        _blink()

    def _open_settings_section(self, section):
        """رفتن به تنظیمات و highlight کردن بخش SQL یا WooCommerce"""
        config = self._go_to_config_tab()
        if config is None:
            return

        if section == "sql":
            group = getattr(config, "sql_group", None)
            test_btn = getattr(config, "sql_test_button", None)
        else:
            from sync_app.core.integrations.commerce_provider import is_prestashop

            group = getattr(config, "wc_group", None)
            if is_prestashop(load_secure_config(None) or {}):
                test_btn = getattr(config, "ps_test_button", None)
            else:
                test_btn = getattr(config, "wc_test_button", None)

        if group is None:
            return

        scroll = getattr(config, "scroll_area", None)
        scroll_target = test_btn or group
        if scroll and scroll_target:
            QTimer.singleShot(80, lambda w=scroll_target: scroll.ensureWidgetVisible(w))

        original_group_style = group.styleSheet()
        self._blink_widget_stylesheet(
            group,
            original_group_style,
            "QGroupBox { border: 3px solid #f59e0b; border-radius: 8px; }",
        )

        if test_btn is not None:
            original_btn_style = test_btn.styleSheet()
            QTimer.singleShot(
                120,
                lambda: self._blink_widget_stylesheet(
                    test_btn,
                    original_btn_style,
                    "QPushButton { border: 3px solid #f59e0b; border-radius: 6px; font-weight: bold; }",
                ),
            )
            test_btn.setFocus(Qt.OtherFocusReason)

    def open_wp_username_settings(self):
        """تنظیمات WooCommerce → هایلایت فیلد WP Username."""
        config = self._go_to_config_tab()
        if config is None:
            return
        self._open_settings_section("woo")
        focus = getattr(config, "focus_wp_username_field", None) or getattr(
            config, "_focus_wp_username_field", None
        )
        if callable(focus):
            QTimer.singleShot(150, focus)
        wp_input = getattr(config, "wp_username_input", None)
        scroll = getattr(config, "scroll_area", None)
        if scroll and wp_input is not None:
            QTimer.singleShot(180, lambda w=wp_input: scroll.ensureWidgetVisible(w, 40, 40))

    def open_store_setup(self):
        """رفتن به تنظیمات WooCommerce و highlight دکمه راه‌اندازی Cart/Checkout"""
        config = self._go_to_config_tab()
        if config is None:
            return
        self._open_settings_section("woo")
        btn = getattr(config, "wc_setup_button", None)
        scroll = getattr(config, "scroll_area", None)
        if scroll and btn:
            QTimer.singleShot(120, lambda: scroll.ensureWidgetVisible(btn))
        if btn:
            original = btn.styleSheet()
            self._blink_widget_stylesheet(
                btn,
                original,
                "QPushButton { border: 3px solid #f59e0b; border-radius: 6px; font-weight: bold; }",
            )

    def _setup_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return

        icon = brand_icon()
        if icon.isNull() and os.path.exists(LOGO_PATH):
            icon = QIcon(LOGO_PATH)
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(f"{get_store_display_name()} — همگام‌سازی فعال")

        menu = QMenu()
        restore_action = QAction("باز کردن برنامه", self)
        restore_action.triggered.connect(self.restore_from_tray)
        menu.addAction(restore_action)

        quit_action = QAction("خروج کامل", self)
        quit_action.triggered.connect(self.quit_from_tray)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.restore_from_tray()

    def restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_from_tray(self):
        self._persist_window_geometry()
        self._allow_close = True
        QApplication.instance().quit()

    def _persist_window_geometry(self):
        try:
            cfg = load_secure_config(None) or {}
            cfg = save_window_geometry(self, cfg)
            index = self.tabs.currentIndex()
            attr = self._tab_attr_for_widget(self.tabs.widget(index))
            if attr:
                cfg[LAST_ACTIVE_TAB_KEY] = attr
            save_secure_config(cfg)
        except Exception:
            pass

    def _shutdown_background_threads(self):
        # توقف امن همه QThread های فعال قبل از بسته شدن برنامه
        all_threads = []
        if self._header_check_thread is not None:
            all_threads.append(self._header_check_thread)

        for thread in self.findChildren(QThread):
            if thread not in all_threads:
                all_threads.append(thread)

        for thread in all_threads:
            try:
                if thread is not None and thread.isRunning():
                    thread.requestInterruption()
                    thread.quit()
            except Exception:
                continue

        for thread in all_threads:
            try:
                if thread is not None and thread.isRunning() and not thread.wait(1500):
                    thread.terminate()
                    thread.wait(500)
            except Exception:
                continue

    def showEvent(self, event):
        super().showEvent(event)
        apply_brand_window_icon(self)

    def closeEvent(self, event):
        if self._allow_close or self.tray_icon is None:
            self._persist_window_geometry()
            self._shutdown_background_threads()
            event.accept()
            return

        self.hide()
        self._persist_window_geometry()
        self.tray_icon.showMessage(
            get_store_display_name(),
            "برنامه بسته نشد و در System Tray فعال ماند.",
            QSystemTrayIcon.Information,
            2500,
        )
        event.ignore()


# شیء گلوبال برای جلوگیری از بسته شدن پنجره فعال‌سازی توسط Garbage Collector
activation_win = None
login_win = None
main_win = None


def load_base_stylesheet():
    style_path = resource_path("style.qss")
    if not os.path.exists(style_path):
        return ""

    with open(style_path, "r", encoding="utf-8") as f:
        return f.read()


def build_theme_stylesheet(theme_name, font_size=14, is_bold=False):
    base_qss = load_base_stylesheet()
    selected_theme = theme_name if theme_name in ALLOWED_THEMES else "navy"
    override_qss = THEME_OVERRIDES.get(selected_theme, THEME_OVERRIDES["navy"])
    safe_size = int(font_size) if int(font_size) > 0 else 14
    # در خروج از حالت bold باید وزن فونت صریحا به normal برگردد
    weight_rule = "font-weight: 700;" if is_bold else "font-weight: 400;"
    tab_size = max(14, safe_size + 2)
    tab_vpad = max(10, safe_size - 3)
    tab_hpad = max(14, safe_size + 1)
    log_size = max(12, safe_size)
    list_size = max(12, safe_size)
    home_btn_size = max(12, safe_size + 1)
    home_btn_min_h = max(44, safe_size + 30)
    weight_bold = "800" if is_bold else "700"
    weight_semi = "700" if is_bold else "600"
    home_dash_typography = (
        f"\nQWidget#homeRoot QLabel#homeHeroTitle {{ font-size: {max(18, safe_size + 8)}px; font-weight: {weight_bold}; }}"
        f"\nQWidget#homeRoot QLabel#homeHeroSubtitle {{ font-size: {max(12, safe_size)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#homeRoot QLabel#homeHeroBadge {{ font-size: {max(11, safe_size - 2)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#homeRoot QLabel#homeHeroTip {{ font-size: {max(12, safe_size - 1)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#homeRoot QLabel#homeSectionTitle,"
        f"\nQWidget#homeRoot QLabel#homeCardTitle {{ font-size: {max(14, safe_size + 1)}px; font-weight: {weight_bold}; }}"
        f"\nQWidget#homeRoot QLabel#homeSectionHint {{ font-size: {max(11, safe_size - 2)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#homeRoot QLabel#homeStepTitle {{ font-size: {max(13, safe_size)}px; font-weight: {weight_bold}; }}"
        f"\nQWidget#homeRoot QLabel#homeStepDesc {{ font-size: {max(11, safe_size - 2)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#homeRoot QLabel#homeStepNumber {{ font-size: {max(12, safe_size - 1)}px; font-weight: {weight_bold}; }}"
        f"\nQWidget#homeRoot QLabel#homeCardText {{ font-size: {max(12, safe_size - 1)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#homeRoot QPushButton#homeStepBtn {{ font-size: {max(11, safe_size - 2)}px; font-weight: {weight_semi}; min-height: {max(32, safe_size + 18)}px; }}"
        f"\nQWidget#dashTabRoot QLabel#dashHeroTitle {{ font-size: {max(18, safe_size + 6)}px; font-weight: {weight_bold}; }}"
        f"\nQWidget#dashTabRoot QLabel#dashHeroSub {{ font-size: {max(12, safe_size - 1)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#dashTabRoot QLabel#dashHeroStatus {{ font-size: {max(11, safe_size - 2)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#dashTabRoot QLabel[role=\"section-title\"] {{ font-size: {max(13, safe_size + 1)}px; font-weight: {weight_bold}; }}"
        f"\nQWidget#dashTabRoot QLabel#dashSectionHint {{ font-size: {max(11, safe_size - 2)}px; font-weight: {weight_semi}; }}"
        f"\nQWidget#dashTabRoot QLabel#dashPanelTitle {{ font-size: {max(13, safe_size)}px; font-weight: {weight_bold}; }}"
        f"\nQWidget#dashTabRoot QLabel#dashTableTitle {{ font-size: {max(12, safe_size - 1)}px; font-weight: {weight_bold}; }}"
        f"\nQWidget#dashTabRoot QLabel#dashInsightLine {{ font-size: {max(12, safe_size - 1)}px; }}"
        f"\nQWidget#dashTabRoot QPushButton#dashQuickBtn {{ font-size: {max(11, safe_size - 1)}px; min-height: {max(36, safe_size + 24)}px; }}"
        f"\nQWidget#dashTabRoot QPushButton#dashRefreshBtn {{ font-size: {max(12, safe_size - 1)}px; min-height: {max(34, safe_size + 20)}px; }}"
        f"\nQWidget#autoSyncRoot QFrame#autoSyncJobRow QLabel#autoSyncJobTitle {{ font-size: {max(13, safe_size)}px; }}"
        f"\nQWidget#autoSyncRoot QFrame#autoSyncJobRow QLabel#autoSyncJobHint {{ font-size: {max(11, safe_size - 2)}px; }}"
        f"\nQWidget#autoSyncRoot QLabel#autoSyncJobsHint {{ font-size: {max(11, safe_size - 2)}px; }}"
    )
    font_override = (
        f"\nQWidget {{ font-size: {safe_size}px; {weight_rule} }}"
        f"\nQTabBar::tab {{ font-size: {tab_size}px; font-weight: 700; padding: {tab_vpad}px {tab_hpad}px; margin: 0 1px; }}"
        # تب‌بار زیرتب‌های داخل تب‌های گروهی (همگام‌سازی/دستیار هوشمند) —
        # اینا از AdaptiveTabBar استفاده می‌کنن که خودش عرض دقیق رو حساب
        # می‌کنه، ولی قانون سراسری بالا با یه پدینگ ثابت می‌تونست باعث بشه
        # متن لیبل (باتوجه به ایموجی + فارسی) نصفه دیده بشه. این‌جا با یه
        # انتخاب‌گر مشخص‌تر (objectName)، پدینگ سخاوتمندانه‌تری می‌دیم.
        f"\nQTabBar#hubSubTabBar::tab {{ font-size: {max(13, tab_size - 1)}px; font-weight: 700; padding: {max(10, tab_vpad)}px {max(18, tab_hpad + 6)}px; margin: 0 2px; }}"
        f"\nQPlainTextEdit#log_view, QTextEdit#log_view {{ font-size: {log_size}px; font-weight: 500; }}"
        f"\nQListWidget, QTreeWidget, QTableWidget, QComboBox QAbstractItemView {{ font-size: {list_size}px; }}"
        f"\nQPushButton[appUnifiedButton=\"true\"] {{ border-radius: 10px; padding: 8px 14px; font-size: {safe_size}px; font-weight: 700; }}"
        f"\nQPushButton[flat=\"true\"] {{ font-size: {max(11, safe_size - 1)}px; font-weight: 600; }}"
        f"\nQPushButton#homeQuickBtn {{ font-size: {home_btn_size}px; min-height: {home_btn_min_h}px; padding: 10px 16px; }}"
        f"\nQWidget#reconRoot QFrame#reconMiddlePanel QPushButton#reconMiddleBtn {{ font-size: {max(10, safe_size - 2)}px; min-height: 34px; max-height: 44px; padding: 4px 8px; }}"
        f"\nQWidget#reconRoot QPushButton#reconMiddleBtn {{ font-size: {max(10, safe_size - 2)}px; min-height: 32px; max-height: 44px; padding: 4px 8px; }}"
        f"\nQWidget#reconRoot QPushButton#reconQuickSkuBtn, "
        f"QWidget#reconRoot QPushButton#reconCommitBtn {{ min-height: {max(40, safe_size + 24)}px; }}"
        f"{home_dash_typography}"
    )
    return base_qss + "\n" + override_qss + font_override


def ensure_iransans_font_loaded(app):
    """بارگذاری اجباری ایران‌سنس و تلاش برای نصب فونت در فضای کاربر ویندوز"""
    font_path = resource_path("IRANSans.ttf")
    if not os.path.exists(font_path):
        return

    family = FONT_FAMILY
    if family not in QFontDatabase().families():
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                family = families[0]

    app.setFont(QFont(family, 10))

    if os.name != "nt":
        return

    try:
        user_fonts_dir = os.path.join(os.getenv("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
        if user_fonts_dir:
            os.makedirs(user_fonts_dir, exist_ok=True)
            dest_path = os.path.join(user_fonts_dir, "IRANSans.ttf")
            if not os.path.exists(dest_path):
                shutil.copy2(font_path, dest_path)
    except Exception:
        # خطای نصب فونت نباید اجرای برنامه را متوقف کند
        pass


def _bootstrap_active_profile_config():
    """بارگذاری و تعمیر تنظیمات SQL برای پروفایل فعال."""
    cfg = load_secure_config_after_profile(log) or {}
    try:
        from sync_app.core.sql_connection_helper import auto_heal_sql_connection

        healed, ok, _summary = auto_heal_sql_connection(cfg, timeout=4)
        if ok and healed != cfg:
            save_secure_config(healed)
        cfg = healed if ok else cfg
    except Exception:
        pass
    try:
        from sync_app.core.sql_attach_helper import ensure_config_database_attached

        cfg, attached = ensure_config_database_attached(cfg, timeout=5)
        if attached:
            save_secure_config(cfg)
    except Exception:
        pass
    try:
        from sync_app.core.sql_connection_helper import auto_repair_sql_config

        repaired, _summary = auto_repair_sql_config(cfg, timeout=4)
        if repaired != cfg:
            save_secure_config(repaired)
        cfg = repaired
    except Exception:
        pass
    return cfg


class StartupRemoteWorker(QObject):
    finished = pyqtSignal(object)

    def run(self):
        try:
            from sync_app.core.license_remote import startup_remote_sync
            from sync_app.core.user_profile import load_secure_config_after_profile

            self.finished.emit(
                startup_remote_sync(config=load_secure_config_after_profile(), include_update_check=False)
            )
        except Exception as exc:
            self.finished.emit(
                {
                    "license_ok": False,
                    "license_err": str(exc),
                    "update_info": None,
                    "update_err": str(exc),
                }
            )


class StartupUpdateWorker(QObject):
    finished = pyqtSignal(object)

    def run(self):
        try:
            from sync_app.core.app_update import lookup_update_info
            from sync_app.core.tabs.tab_license import LicenseTab

            key = LicenseTab._load_license_key()
            if not key:
                self.finished.emit({"update_info": None, "update_err": "no_license_key"})
                return
            hwid = LicenseTab.get_hwid()
            ok, info, err = lookup_update_info(license_key=key, hwid=hwid)
            if ok:
                self.finished.emit({"update_info": info, "update_err": ""})
            else:
                self.finished.emit({"update_info": None, "update_err": err or ""})
        except Exception as exc:
            self.finished.emit({"update_info": None, "update_err": str(exc)})


class UpdateDownloadWorker(QObject):
    finished = pyqtSignal(bool, str, bool)

    def __init__(self, info: dict):
        super().__init__()
        self.info = info

    def run(self):
        try:
            from sync_app.core.app_update import download_and_apply_update

            ok, msg, restart = download_and_apply_update(self.info)
            self.finished.emit(ok, msg, restart)
        except Exception as exc:
            self.finished.emit(False, str(exc), False)


class ProfileBootstrapWorker(QObject):
    finished = pyqtSignal(object)

    def run(self):
        try:
            cfg = _bootstrap_active_profile_config()
        except Exception:
            cfg = load_secure_config_after_profile(log) or {}
        self.finished.emit(cfg)


def _schedule_profile_bootstrap(parent) -> None:
    if parent is None or getattr(parent, "_bootstrap_thread", None) is not None:
        return

    thread = QThread(parent)
    worker = ProfileBootstrapWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(lambda cfg: _on_profile_bootstrap_done(parent, cfg))
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(lambda: setattr(parent, "_bootstrap_thread", None))
    thread.finished.connect(thread.deleteLater)
    parent._bootstrap_thread = thread
    parent._bootstrap_worker = worker
    thread.start()


def _on_profile_bootstrap_done(parent, cfg) -> None:
    parent._bootstrap_worker = None
    if not cfg:
        return
    try:
        parent.apply_theme(cfg.get("APP_THEME", "navy"))
        parent.apply_font_size(cfg.get("APP_FONT_SIZE", 14))
        if hasattr(parent, "refresh_sql_connectivity"):
            parent.refresh_sql_connectivity(show_pending=False)
    except Exception as exc:
        _startup_log.warning("SQL bootstrap UI update: %s", exc)
    if hasattr(parent, "_pregenerate_lazy_tab"):
        QTimer.singleShot(1500, lambda: parent._pregenerate_lazy_tab("config_tab"))


_startup_log = logging.getLogger("peecha.startup")


def _install_crash_logger():
    """خطاهای بدون catch در thread/timer — لاگ + پیام به کاربر"""
    import traceback

    def _hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Unhandled exception:\n%s", text)
        _startup_log.error("Unhandled exception:\n%s", text)
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(
                    None,
                    "خطای برنامه",
                    "برنامه با خطا متوقف شد.\n"
                    "فایل sync.log را برای ما بفرستید.\n\n"
                    f"{exc_type.__name__}: {exc}",
                )
        except Exception:
            pass

    sys.excepthook = _hook


class _LoadingSplash(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedSize(420, 100)
        self.setStyleSheet("background-color: #020025;")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 6, 6, 10)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.addStretch(1)
        close_btn = QPushButton("×")
        close_btn.setFixedSize(26, 26)
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip("بستن")
        close_btn.setStyleSheet(
            "QPushButton { color: #ffffff; font-size: 18px; border: none; border-radius: 4px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.18); }"
        )
        close_btn.clicked.connect(self._quit_app)
        top.addWidget(close_btn)
        root.addLayout(top)

        self._message = QLabel("در حال بارگذاری PeechaSync...\nLoading PeechaSync...")
        self._message.setAlignment(Qt.AlignCenter)
        self._message.setStyleSheet("color: #ffffff; font-family: 'Segoe UI'; font-size: 10pt;")
        root.addWidget(self._message, 1)

    def _quit_app(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _center(self) -> None:
        app = QApplication.instance()
        if app is not None and app.primaryScreen() is not None:
            geo = app.primaryScreen().availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )

    def showMessage(self, text, alignment=Qt.AlignCenter, color=None) -> None:
        self._message.setText(str(text or ""))
        if color is not None:
            self._message.setStyleSheet(
                f"color: {color.name()}; font-family: 'Segoe UI'; font-size: 10pt;"
            )
        if alignment is not None:
            self._message.setAlignment(alignment)

    def finish(self, window) -> None:
        self.close()

    def show(self) -> None:
        self._center()
        super().show()


def _present_startup_window(window, label: str) -> None:
    app = QApplication.instance()
    splash = getattr(app, "_peecha_splash", None) if app is not None else None
    if splash is not None:
        try:
            splash.finish(window)
        except Exception:
            try:
                splash.close()
            except Exception:
                pass
        app._peecha_splash = None

    if app is not None and app.primaryScreen() is not None:
        geo = app.primaryScreen().availableGeometry()
        frame = window.frameGeometry()
        frame.moveCenter(geo.center())
        window.move(frame.topLeft())

    window.setWindowModality(Qt.NonModal)

    # پنجره‌های بی‌فریم (مثل فرم ورود) رو نباید با تغییرِ windowFlag بعد از
    # نمایش، دوباره‌ساخت کرد — روی ویندوز این کار باعث می‌شد handleِ
    # نیتیوِ پنجره در وسطِ رندر دوباره ساخته بشه و فرم «نصفه باز» بمونه
    # (گزارشِ تکراریِ کاربر). برای این پنجره‌ها فقط یک بار show/raise/
    # activate کافیه، بدون بازی با WindowStaysOnTopHint.
    is_frameless = bool(window.windowFlags() & Qt.FramelessWindowHint)

    if is_frameless:
        window.show()
        window.raise_()
        window.activateWindow()
        if app is not None:
            app.processEvents()
    else:
        was_on_top = bool(window.windowFlags() & Qt.WindowStaysOnTopHint)
        if not was_on_top:
            window.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        window.show()
        window.raise_()
        window.activateWindow()

        if app is not None:
            app.processEvents()

        if not was_on_top:
            window.setWindowFlag(Qt.WindowStaysOnTopHint, False)
            window.show()
            if app is not None:
                app.processEvents()

    _startup_log.info("%s opened", label)
    if os.environ.get("PEECHA_DEBUG_CONSOLE", "").strip().lower() in ("1", "true", "yes"):
        print(f"[INFO] {label} opened - check taskbar or Alt+Tab", flush=True)


def main(existing_app=None):
    global activation_win, login_win, main_win
    
    # UTF-8 برای کنسول (در EXE بدون console، stdout/stderr ممکن است None باشد)
    import io
    for _name in ("stdout", "stderr"):
        _stream = getattr(sys, _name, None)
        if _stream is None:
            setattr(sys, _name, io.StringIO())
        elif hasattr(_stream, "buffer") and not isinstance(_stream, io.TextIOBase):
            try:
                setattr(sys, _name, io.TextIOWrapper(_stream.buffer, encoding="utf-8", errors="replace"))
            except Exception:
                pass
    
    instance_manager = SingleInstanceManager("peecha_launcher")
    instance_manager.ensure_single_instance()
    _startup_log.info("Loading PeechaSync UI...")

    apply_windows_taskbar_branding()
    app = existing_app or QApplication(sys.argv)
    app._peecha_splash = getattr(app, "_peecha_splash", None)
    if app._peecha_splash is None:
        splash = _LoadingSplash()
        splash.setFont(QFont("Segoe UI", 10))
        splash.show()
        app.processEvents()
        app._peecha_splash = splash
    _install_crash_logger()
    app.setQuitOnLastWindowClosed(False)
    app_icon = brand_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    install_persian_message_boxes()
    install_messagebox_logging()
    QTimer.singleShot(0, lambda: ensure_iransans_font_loaded(app))

    migrate_legacy_profiles(log)
    last_profile = load_last_profile_id()
    if last_profile:
        activate_profile(last_profile)
    else:
        reconfigure_app_logging()

    cfg = load_secure_config_after_profile(log) or {}

    selected_theme = cfg.get("APP_THEME", "navy")
    if selected_theme not in ALLOWED_THEMES:
        selected_theme = "navy"
    raw_font_setting = cfg.get("APP_FONT_SIZE", 14)
    font_size, is_bold = resolve_user_font_pref(raw_font_setting)
    app.setStyleSheet(build_theme_stylesheet(selected_theme, font_size, is_bold))

    def show_main_launcher():
        global main_win
        _startup_log.info("Opening main window...")
        cfg_local = load_secure_config_after_profile(log) or {}
        main_win = PeechaLauncher()
        apply_window_geometry(main_win, cfg_local)
        _present_startup_window(main_win, "Main window")
        apply_brand_window_icon(main_win)
        QTimer.singleShot(0, lambda: main_win.apply_theme(cfg_local.get("APP_THEME", "navy")))
        QTimer.singleShot(0, lambda: main_win.apply_font_size(cfg_local.get("APP_FONT_SIZE", 14)))
        QTimer.singleShot(3000, lambda: _schedule_profile_bootstrap(main_win))

    def show_login_window():
        global login_win
        from sync_app.core.login_window import LoginWindow

        _startup_log.info("Creating login window...")
        bootstrap = {"APP_LOGIN_USERNAME": load_last_profile_id() or "admin"}
        login_win = LoginWindow(config=bootstrap, on_login_success=show_main_launcher)
        _present_startup_window(login_win, "Login window")

    def _block_on_license_scope(message):
        from PyQt5.QtWidgets import QMessageBox

        _startup_log.info("License scope violation - blocking launch: %s", message)
        QMessageBox.critical(None, "محدودیت لایسنس", message)
        instance_manager.cleanup()
        sys.exit(1)

    if LicenseTab.is_license_valid_for_launch():
        scope_ok, scope_msg = LicenseTab.check_license_scope(cfg)
        if not scope_ok:
            _block_on_license_scope(scope_msg)
        _startup_log.info("License OK - opening app...")
        show_login = cfg.get("APP_SHOW_LOGIN_SCREEN", True)
        _startup_log.info("Login screen: %s", "on" if show_login else "off")
        if show_login:
            show_login_window()
        else:
            _startup_log.info("Skipping login (disabled in settings)")
            if not get_current_profile_display_name():
                activate_profile(last_profile or "default")
                reconfigure_app_logging()
            show_main_launcher()
    else:
        _startup_log.info("License required - opening activation window...")
        from sync_app.core.license_welcome import LicenseWelcomeWindow

        activation_win = LicenseWelcomeWindow(on_activated=show_login_window)
        from sync_app.core.app_site_config import get_store_display_name

        activation_win.setWindowTitle(f"فعال‌سازی — {get_store_display_name()}")
        apply_brand_window_icon(activation_win)
        activation_win.resize(540, 720)
        activation_win.setMinimumSize(480, 620)
        _present_startup_window(activation_win, "License activation")

    exit_code = app.exec_()
    
    # 🧹 پاکسازی
    instance_manager.cleanup()
    
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        raise
