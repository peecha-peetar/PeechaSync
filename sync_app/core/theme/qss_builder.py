"""
سازنده‌ی QSS مدرن — استایل‌شیت کامل و مستقل (پیش‌فرض: روشن) بر پایه‌ی
sync_app/core/theme/colors.py. کاملاً جدا از سیستم قدیمی رنگ‌های لهجه‌ای
(navy/red/green) — فقط جایگزین ظاهری آن می‌شود، منطق برنامه دست‌نخورده می‌ماند.
"""

from __future__ import annotations

from sync_app.core.theme.colors import get_theme, RADIUS, FONT_FA


def build_modern_stylesheet(mode: str = "light", *, font_size: int = 14) -> str:
    c = get_theme(mode)
    r = RADIUS
    fs = font_size

    return f"""
* {{
    font-family: "{FONT_FA}", "Segoe UI", "Inter", sans-serif;
}}

QWidget {{
    background-color: {c['bg_base']};
    color: {c['text_primary']};
    font-size: {fs}px;
    selection-background-color: {c['primary']};
    selection-color: {c['text_on_primary']};
}}

QMainWindow, QDialog {{ background-color: {c['bg_base']}; }}

QToolTip {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: {r['sm']};
    padding: 6px 10px;
}}

/* ---------------- دکمه‌ها ---------------- */
QPushButton {{
    background-color: {c['primary']};
    color: {c['text_on_primary']};
    border: none;
    border-radius: {r['md']};
    padding: 10px 18px;
    font-weight: 600;
    min-height: 20px;
}}
QPushButton:hover {{ background-color: {c['primary_hover']}; }}
QPushButton:pressed {{ background-color: {c['primary_pressed']}; }}
QPushButton:disabled {{ background-color: {c['bg_pressed']}; color: {c['text_muted']}; }}

QPushButton[flat="true"], QPushButton#secondaryBtn {{
    background-color: {c['bg_surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
}}
QPushButton[flat="true"]:hover, QPushButton#secondaryBtn:hover {{
    background-color: {c['bg_hover']};
    border-color: {c['primary']};
}}

QPushButton#btn_success, QPushButton[syncAction="true"] {{ background-color: {c['success']}; }}
QPushButton#btn_success:hover, QPushButton[syncAction="true"]:hover {{ background-color: #16A34A; }}
QPushButton#btn_danger {{ background-color: {c['danger']}; }}
QPushButton#btn_danger:hover {{ background-color: {c['danger_hover']}; }}
QPushButton#btn_warning {{ background-color: {c['warning']}; }}

/* ---------------- ورودی‌ها ---------------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {c['bg_input']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: {r['sm']};
    padding: 8px 12px;
    selection-background-color: {c['primary']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1.5px solid {c['border_focus']};
}}
QLineEdit:disabled, QTextEdit:disabled {{
    background-color: {c['bg_pressed']};
    color: {c['text_muted']};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: {r['sm']};
    selection-background-color: {c['primary']};
    selection-color: {c['text_on_primary']};
    outline: none;
}}

QCheckBox, QRadioButton {{ color: {c['text_primary']}; spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px; height: 18px;
    border: 1.5px solid {c['border']};
    border-radius: 5px;
    background: {c['bg_input']};
}}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {c['primary']};
    border-color: {c['primary']};
}}

/* ---------------- تب‌ها (افقی، بالای صفحه — موقعیت واقعی دست‌نخورده) ---------------- */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: {r['md']};
    background: {c['bg_surface']};
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    color: {c['text_secondary']};
    border: none;
    border-bottom: 3px solid transparent;
    padding: 10px 18px;
    margin-left: 2px;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {c['text_primary']};
    background: {c['bg_hover']};
    border-top-left-radius: {r['sm']};
    border-top-right-radius: {r['sm']};
}}
QTabBar::tab:selected {{
    color: {c['primary']};
    border-bottom: 3px solid {c['primary']};
    font-weight: 700;
}}
QTabBar::tab:disabled {{ color: {c['text_muted']}; }}

/* ---------------- جداول/لیست‌ها ---------------- */
QTableWidget, QTreeWidget, QListWidget {{
    background-color: {c['bg_surface']};
    alternate-background-color: {c['bg_surface_alt']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: {r['md']};
    gridline-color: {c['border']};
    outline: none;
}}
QHeaderView::section {{
    background-color: {c['bg_surface_alt']};
    color: {c['text_secondary']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: 8px 10px;
    font-weight: 700;
}}
QTableWidget::item, QTreeWidget::item, QListWidget::item {{ padding: 6px; border: none; }}
QTableWidget::item:hover, QTreeWidget::item:hover, QListWidget::item:hover {{
    background-color: {c['bg_hover']};
}}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {c['sidebar_item_active']};
    color: {c['text_primary']};
}}

/* ---------------- گروه/کارت ---------------- */
QGroupBox {{
    background-color: {c['bg_surface']};
    border: 1px solid {c['border']};
    border-radius: {r['lg']};
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    right: 12px;
    padding: 0 8px;
    color: {c['primary']};
    background: {c['bg_base']};
}}

/* ---------------- اسکرول‌بار ---------------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['scrollbar']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['scrollbar_hover']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['scrollbar']}; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {c['scrollbar_hover']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ---------------- پراگرس‌بار ---------------- */
QProgressBar {{
    background-color: {c['bg_surface_alt']};
    border: none;
    border-radius: {r['pill']};
    text-align: center;
    color: {c['text_primary']};
    min-height: 10px;
    max-height: 10px;
}}
QProgressBar::chunk {{ background-color: {c['primary']}; border-radius: {r['pill']}; }}

/* ---------------- منو ---------------- */
QMenu {{
    background-color: {c['bg_elevated']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: {r['md']};
    padding: 6px;
}}
QMenu::item {{ padding: 8px 16px; border-radius: {r['sm']}; }}
QMenu::item:selected {{ background-color: {c['bg_hover']}; color: {c['primary']}; }}

/* ---------------- برچسب‌های وضعیت ---------------- */
QLabel[role="badge-success"] {{
    background-color: {c['success']}; color: white; font-weight: 700;
    padding: 4px 10px; border-radius: {r['pill']};
}}
QLabel[role="badge-error"] {{
    background-color: {c['danger']}; color: white; font-weight: 700;
    padding: 4px 10px; border-radius: {r['pill']};
}}
QLabel[role="badge-warning"] {{
    background-color: {c['warning']}; color: white; font-weight: 700;
    padding: 4px 10px; border-radius: {r['pill']};
}}
QLabel[role="section-title"] {{ font-size: {fs + 3}px; font-weight: 800; color: {c['text_primary']}; }}
QLabel[role="caption"] {{ color: {c['text_secondary']}; font-size: {fs - 2}px; }}

/* ---------------- تولبار/استاتوس‌بار مدرن ---------------- */
QWidget#modernToolbar {{
    background-color: {c['toolbar_bg']};
    border-bottom: 1px solid {c['border']};
}}
QWidget#modernStatusbar {{
    background-color: {c['statusbar_bg']};
    border-top: 1px solid {c['border']};
}}
"""
