"""
توکن‌های رنگی سیستم طراحی پیچا — یک منبع واحد برای همه‌ی رنگ‌ها.
پیش‌فرض: تم روشن (Light) — طبق آخرین درخواست. تم تیره هم نگه داشته شده
و در دسترس است، ولی روشن پیش‌فرض و اصلی است.
"""

from __future__ import annotations

BRAND = {
    "primary": "#3B82F6",
    "primary_hover": "#2563EB",
    "primary_pressed": "#1D4ED8",
    "secondary": "#8B5CF6",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "danger_hover": "#DC2626",
}

LIGHT = {
    **BRAND,
    "bg_base": "#F8FAFC",
    "bg_surface": "#FFFFFF",
    "bg_surface_alt": "#F1F5F9",
    "bg_elevated": "#FFFFFF",
    "bg_hover": "#F1F5F9",
    "bg_pressed": "#E2E8F0",
    "bg_input": "#FFFFFF",
    "border": "#E2E8F0",
    "border_focus": "#3B82F6",
    "text_primary": "#0F172A",
    "text_secondary": "#475569",
    "text_muted": "#94A3B8",
    "text_on_primary": "#FFFFFF",
    "sidebar_bg": "#FFFFFF",
    "sidebar_border": "#E2E8F0",
    "sidebar_text": "#475569",
    "sidebar_text_active": "#3B82F6",
    "sidebar_item_hover": "#F1F5F9",
    "sidebar_item_active": "#EFF6FF",
    "sidebar_item_active_border": "#3B82F6",
    "sidebar_section_label": "#94A3B8",
    "scrollbar": "#E2E8F0",
    "scrollbar_hover": "#CBD5E1",
    "shadow": "rgba(15, 23, 42, 30)",
    "toolbar_bg": "#FFFFFF",
    "statusbar_bg": "#FFFFFF",
}

DARK = {
    **BRAND,
    "bg_base": "#0F1117",
    "bg_surface": "#161922",
    "bg_surface_alt": "#1C202B",
    "bg_elevated": "#20242F",
    "bg_hover": "#252A37",
    "bg_pressed": "#2B303D",
    "bg_input": "#1A1E28",
    "border": "#2A2F3D",
    "border_focus": "#3B82F6",
    "text_primary": "#F3F4F6",
    "text_secondary": "#9CA3AF",
    "text_muted": "#6B7280",
    "text_on_primary": "#FFFFFF",
    "sidebar_bg": "#12141C",
    "sidebar_border": "#2A2F3D",
    "sidebar_text": "#9CA3AF",
    "sidebar_text_active": "#60A5FA",
    "sidebar_item_hover": "#1C202B",
    "sidebar_item_active": "#1E2A47",
    "sidebar_item_active_border": "#3B82F6",
    "sidebar_section_label": "#6B7280",
    "scrollbar": "#2A2F3D",
    "scrollbar_hover": "#3B4152",
    "shadow": "rgba(0, 0, 0, 120)",
    "toolbar_bg": "#12141C",
    "statusbar_bg": "#12141C",
}

THEMES = {"light": LIGHT, "dark": DARK}

RADIUS = {"sm": "6px", "md": "10px", "lg": "14px", "xl": "18px", "pill": "999px"}
SPACE = {"xs": "4px", "sm": "8px", "md": "12px", "lg": "16px", "xl": "24px"}

FONT_FA = "Vazirmatn"
FONT_EN = "Inter"


def get_theme(name: str) -> dict:
    return THEMES.get(name, LIGHT)
