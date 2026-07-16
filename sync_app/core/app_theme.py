"""پالت تم‌های مجاز و helper برای دیالوگ‌ها."""

from __future__ import annotations

ALLOWED_THEMES = frozenset({"navy", "red", "green"})

THEME_PALETTE: dict[str, dict[str, str]] = {
    "navy": {
        "primary": "#020025",
        "hover": "#17134f",
        "pressed": "#010016",
        "soft": "#ecebff",
        "soft_border": "#c9c7ff",
    },
    "red": {
        "primary": "#C60040",
        "hover": "#c31635",
        "pressed": "#8e0c24",
        "soft": "#ffe9eb",
        "soft_border": "#f2b6bd",
    },
    "green": {
        "primary": "#008030",
        "hover": "#0b9440",
        "pressed": "#006326",
        "soft": "#e7f8ef",
        "soft_border": "#b9e8ce",
    },
}


def get_active_theme_palette() -> tuple[str, dict[str, str]]:
    from sync_app.core.secure_config_loader import load_secure_config

    cfg = load_secure_config(None) or {}
    name = str(cfg.get("APP_THEME", "navy")).strip()
    if name not in ALLOWED_THEMES:
        name = "navy"
    return name, THEME_PALETTE[name]


def resolve_user_font_pref(font_setting) -> tuple[int, bool]:
    """تبدیل مقدار ذخیره‌شده فونت (تنظیمات) به سایز و ضخامت."""
    if str(font_setting) == "18bold":
        return 18, True
    try:
        return int(font_setting), False
    except (TypeError, ValueError):
        return 14, False


def compute_responsive_font_size(base_size: int, width: int, height: int) -> int:
    """مقیاس فونت در پنجره‌های کوچک — همان منطق لانچر."""
    w = max(width, 1)
    h = max(height, 1)
    if w <= 760 or h <= 480:
        scale = 0.78
    elif w <= 980 or h <= 620:
        scale = 0.88
    else:
        scale = 1.0
    return max(10, int(round(base_size * scale)))


def build_last_tab_restore_stylesheet(palette: dict[str, str]) -> str:
    primary = palette["primary"]
    hover = palette["hover"]
    pressed = palette["pressed"]
    soft = palette["soft"]
    soft_border = palette["soft_border"]
    return f"""
QDialog#lastTabRestoreDialog {{
    background-color: #ffffff;
}}

QDialog#lastTabRestoreDialog QFrame#lastTabRestoreInfo {{
    background-color: {soft};
    border: 1.5px solid {soft_border};
    border-radius: 10px;
}}

QDialog#lastTabRestoreDialog QLabel#lastTabRestoreInfoTitle {{
    color: {primary};
    font-size: 15px;
    font-weight: 800;
    background: transparent;
}}

QDialog#lastTabRestoreDialog QLabel#lastTabRestoreInfoMessage {{
    color: {pressed};
    font-size: 13px;
    background: transparent;
}}

QDialog#lastTabRestoreDialog QLabel#lastTabRestoreHint {{
    color: #64748b;
    font-size: 12px;
    background: transparent;
}}

QDialog#lastTabRestoreDialog QCheckBox {{
    color: #334155;
    font-size: 12px;
    font-weight: 600;
}}

QDialog#lastTabRestoreDialog QPushButton#lastTabRestoreNo {{
    background-color: #e2e8f0;
    color: #0f172a;
    border-radius: 8px;
    font-weight: 700;
    padding: 8px 14px;
    min-height: 40px;
}}

QDialog#lastTabRestoreDialog QPushButton#lastTabRestoreNo:hover {{
    background-color: #cbd5e1;
}}

QDialog#lastTabRestoreDialog QPushButton#lastTabRestoreYes {{
    background-color: {primary};
    color: #ffffff;
    border-radius: 8px;
    font-weight: 700;
    padding: 8px 14px;
    min-height: 40px;
}}

QDialog#lastTabRestoreDialog QPushButton#lastTabRestoreYes:hover {{
    background-color: {hover};
}}

QDialog#lastTabRestoreDialog QPushButton#lastTabRestoreYes:pressed {{
    background-color: {pressed};
}}
"""


def build_reconciliation_link_warning_stylesheet(palette: dict[str, str]) -> str:
    primary = palette["primary"]
    hover = palette["hover"]
    pressed = palette["pressed"]
    soft = palette["soft"]
    soft_border = palette["soft_border"]
    return f"""
QDialog#reconLinkWarningDialog {{
    background-color: #ffffff;
}}

QDialog#reconLinkWarningDialog QFrame#reconLinkWarningBanner {{
    background-color: {soft};
    border: 1.5px solid {soft_border};
    border-radius: 10px;
}}

QDialog#reconLinkWarningDialog QLabel#reconLinkWarningIconBadge {{
    background-color: #ffffff;
    color: #b45309;
    font-size: 24px;
    font-weight: 800;
    min-width: 48px;
    max-width: 48px;
    min-height: 48px;
    max-height: 48px;
    border-radius: 24px;
    border: 2px solid {soft_border};
}}

QDialog#reconLinkWarningDialog QLabel#reconLinkWarningTitle {{
    color: {primary};
    font-size: 16px;
    font-weight: 800;
    background: transparent;
}}

QDialog#reconLinkWarningDialog QLabel#reconLinkWarningSubtitle {{
    color: {pressed};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}

QDialog#reconLinkWarningDialog QScrollArea#reconLinkWarningScroll {{
    background: transparent;
    border: none;
}}

QDialog#reconLinkWarningDialog QFrame#reconLinkWarningCard {{
    background-color: #ffffff;
    border: 1.5px solid {soft_border};
    border-radius: 10px;
}}

QDialog#reconLinkWarningDialog QLabel#reconLinkWarningCardHead {{
    color: {primary};
    font-size: 13px;
    font-weight: 800;
    background: transparent;
}}

QDialog#reconLinkWarningDialog QLabel#reconLinkWarningCardLine {{
    color: #334155;
    font-size: 13px;
    background: transparent;
}}

QDialog#reconLinkWarningDialog QLabel#reconLinkWarningCardWarn {{
    color: {pressed};
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}}

QDialog#reconLinkWarningDialog QPushButton#reconLinkWarningCancel {{
    background-color: #e2e8f0;
    color: #0f172a;
    border-radius: 8px;
    font-weight: 700;
    padding: 8px 14px;
    min-height: 40px;
}}

QDialog#reconLinkWarningDialog QPushButton#reconLinkWarningCancel:hover {{
    background-color: #cbd5e1;
}}

QDialog#reconLinkWarningDialog QPushButton#reconLinkWarningConfirm {{
    background-color: {primary};
    color: #ffffff;
    border-radius: 8px;
    font-weight: 700;
    padding: 8px 14px;
    min-height: 40px;
}}

QDialog#reconLinkWarningDialog QPushButton#reconLinkWarningConfirm:hover {{
    background-color: {hover};
}}

QDialog#reconLinkWarningDialog QPushButton#reconLinkWarningConfirm:pressed {{
    background-color: {pressed};
}}
"""


def build_live_site_backup_stylesheet(palette: dict[str, str]) -> str:
    primary = palette["primary"]
    hover = palette["hover"]
    pressed = palette["pressed"]
    soft = palette["soft"]
    soft_border = palette["soft_border"]
    return f"""
QDialog#liveSiteBackupDialog {{
    background-color: #ffffff;
    border: 2px solid #f87171;
}}

QDialog#liveSiteBackupDialog QFrame#liveSiteBackupDangerStrip {{
    background-color: #dc2626;
    border: none;
    border-radius: 3px;
    min-height: 5px;
    max-height: 5px;
}}

QDialog#liveSiteBackupDialog QFrame#liveSiteBackupBanner {{
    background-color: {primary};
    border: 2px solid #fbbf24;
    border-right: 5px solid #dc2626;
    border-radius: 10px;
}}

QDialog#liveSiteBackupDialog QLabel#liveSiteBackupIconBadge {{
    background-color: #ffffff;
    color: #dc2626;
    font-size: 26px;
    font-weight: 800;
    min-width: 52px;
    max-width: 52px;
    min-height: 52px;
    max-height: 52px;
    border-radius: 26px;
    border: 3px solid #fbbf24;
}}

QDialog#liveSiteBackupDialog QLabel#liveSiteBackupBannerTitle {{
    color: #ffffff;
    font-size: 16px;
    font-weight: 800;
    background: transparent;
}}

QDialog#liveSiteBackupDialog QLabel#liveSiteBackupBannerSub {{
    color: #fef3c7;
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}}

QDialog#liveSiteBackupDialog QFrame#liveSiteBackupRiskCallout {{
    background-color: #fff7ed;
    border: 2px solid #f97316;
    border-radius: 8px;
}}

QDialog#liveSiteBackupDialog QLabel#liveSiteBackupRiskText {{
    color: #9a3412;
    font-size: 13px;
    font-weight: 800;
    background: transparent;
    padding: 2px 0;
}}

QDialog#liveSiteBackupDialog QFrame#liveSiteBackupInfo {{
    background-color: {soft};
    border: 2px solid #fdba74;
    border-radius: 10px;
}}

QDialog#liveSiteBackupDialog QLabel#liveSiteBackupLead {{
    color: {pressed};
    font-size: 14px;
    background: transparent;
}}

QDialog#liveSiteBackupDialog QFrame#liveSiteBackupChecklist {{
    background-color: #ffffff;
    border: 1.5px solid {soft_border};
    border-radius: 8px;
}}

QDialog#liveSiteBackupDialog QLabel#liveSiteBackupCheckItem {{
    color: {primary};
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}}

QDialog#liveSiteBackupDialog QFrame#liveSiteBackupActionBox {{
    background-color: #fef2f2;
    border: 1.5px solid #fca5a5;
    border-radius: 8px;
}}

QDialog#liveSiteBackupDialog QLabel#liveSiteBackupAction {{
    color: #991b1b;
    font-size: 13px;
    font-weight: 800;
    background: transparent;
}}

QDialog#liveSiteBackupDialog QCheckBox {{
    color: #7f1d1d;
    font-size: 13px;
    font-weight: 800;
    spacing: 8px;
    background: transparent;
}}

QDialog#liveSiteBackupDialog QCheckBox::indicator {{
    width: 18px;
    height: 18px;
}}

QDialog#liveSiteBackupDialog QLabel#liveSiteBackupHint {{
    color: #b45309;
    font-size: 12px;
    font-weight: 700;
    background: transparent;
}}

QDialog#liveSiteBackupDialog QPushButton#liveSiteBackupCancel {{
    background-color: #e2e8f0;
    color: #0f172a;
    border-radius: 8px;
    font-weight: 700;
    padding: 8px 14px;
    min-height: 44px;
}}

QDialog#liveSiteBackupDialog QPushButton#liveSiteBackupCancel:hover {{
    background-color: #cbd5e1;
}}

QDialog#liveSiteBackupDialog QPushButton#liveSiteBackupContinue {{
    background-color: #f1f5f9;
    color: #94a3b8;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    font-weight: 700;
    padding: 8px 14px;
    min-height: 44px;
}}

QDialog#liveSiteBackupDialog QPushButton#liveSiteBackupContinue:enabled {{
    background-color: #dc2626;
    color: #ffffff;
    border: 1px solid #b91c1c;
}}

QDialog#liveSiteBackupDialog QPushButton#liveSiteBackupContinue:hover:enabled {{
    background-color: #b91c1c;
}}

QDialog#liveSiteBackupDialog QPushButton#liveSiteBackupContinue:pressed:enabled {{
    background-color: #991b1b;
}}
"""


def build_connectivity_wait_stylesheet(
    palette: dict[str, str],
    font_size: int = 14,
    is_bold: bool = False,
) -> str:
    primary = palette["primary"]
    hover = palette["hover"]
    pressed = palette["pressed"]
    soft = palette["soft"]
    soft_border = palette["soft_border"]
    safe = max(11, int(font_size))
    title_size = max(17, safe + 4)
    body_size = max(12, safe - 1)
    small_size = max(10, safe - 3)
    weight_title = "800" if is_bold else "700"
    weight_body = "700" if is_bold else "600"
    return f"""
QDialog#connectivityWaitDialog {{
    background: transparent;
}}

QDialog#connectivityWaitDialog QFrame#waitCard {{
    background-color: #ffffff;
    border: 1.5px solid {soft_border};
    border-radius: 14px;
}}

QDialog#connectivityWaitDialog QFrame#waitLogPanel {{
    background-color: {pressed};
    border: 1px solid {soft_border};
    border-radius: 12px;
}}

QDialog#connectivityWaitDialog QLabel#waitLogTitle {{
    color: #e2e8f0;
    font-size: {small_size}px;
    font-weight: {weight_body};
    background: transparent;
}}

QDialog#connectivityWaitDialog QTextEdit#waitLog {{
    background: transparent;
    color: #bbf7d0;
    border: none;
    font-family: Consolas, 'Courier New', monospace;
    font-size: {small_size}px;
    padding: 4px 2px;
}}

QDialog#connectivityWaitDialog QLabel#waitTitle {{
    color: {primary};
    font-size: {title_size}px;
    font-weight: {weight_title};
    background: transparent;
}}

QDialog#connectivityWaitDialog QLabel#waitTitleAccent {{
    color: {hover};
    font-size: {small_size}px;
    font-weight: {weight_body};
    background: transparent;
}}

QDialog#connectivityWaitDialog QFrame#waitTitleRule {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(0,0,0,0), stop:0.2 {soft_border}, stop:0.8 {soft_border}, stop:1 rgba(0,0,0,0));
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

QDialog#connectivityWaitDialog QLabel#waitSubtitle {{
    color: #64748b;
    font-size: {body_size}px;
    font-weight: 500;
    background: transparent;
}}

QDialog#connectivityWaitDialog QLabel#waitStatusLine {{
    color: {pressed};
    font-size: {body_size}px;
    font-weight: {weight_body};
    background: transparent;
}}

QDialog#connectivityWaitDialog QLabel#waitHint {{
    color: #64748b;
    font-size: {small_size}px;
    background: transparent;
}}

QDialog#connectivityWaitDialog QLabel#waitBadgeCaption {{
    color: #94a3b8;
    font-size: {small_size}px;
    font-weight: {weight_body};
    background: transparent;
}}

QDialog#connectivityWaitDialog QLabel#waitPulseDot {{
    color: {hover};
    font-size: {body_size}px;
    font-weight: {weight_body};
    min-width: 18px;
    background: transparent;
}}

QDialog#connectivityWaitDialog QPushButton#waitStopBtn {{
    background-color: #e2e8f0;
    color: {pressed};
    border: 1px solid #cbd5e1;
    border-radius: 9px;
    font-size: {body_size}px;
    font-weight: {weight_body};
    padding: 9px 28px;
    min-width: 96px;
}}

QDialog#connectivityWaitDialog QPushButton#waitStopBtn:hover {{
    background-color: #cbd5e1;
    color: {primary};
}}

QDialog#connectivityWaitDialog QPushButton#waitStopBtn:pressed {{
    background-color: {soft};
}}
"""


def build_license_tab_stylesheet(
    palette: dict[str, str],
    font_size: int = 14,
    is_bold: bool = False,
) -> str:
    primary = palette["primary"]
    hover = palette["hover"]
    pressed = palette["pressed"]
    soft = palette["soft"]
    soft_border = palette["soft_border"]
    safe = max(11, int(font_size))
    title_size = max(18, safe + 5)
    section_size = max(14, safe + 1)
    body_size = max(12, safe - 1)
    caption_size = max(10, safe - 3)
    weight_title = "800" if is_bold else "700"
    weight_section = "700" if is_bold else "600"
    return f"""
QWidget#licenseRoot {{
    background: #f8fafc;
}}

QScrollArea#licenseScroll {{
    background: transparent;
    border: none;
}}

QFrame#licenseStatusHero {{
    border-radius: 14px;
    border: 1px solid {soft_border};
    background: #ffffff;
}}

QFrame#licenseStatusHero[licenseStatus="active"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ecfdf5, stop:1 #ffffff);
    border-color: #86efac;
}}

QFrame#licenseStatusHero[licenseStatus="warning"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #fffbeb, stop:1 #ffffff);
    border-color: #fcd34d;
}}

QFrame#licenseStatusHero[licenseStatus="expired"],
QFrame#licenseStatusHero[licenseStatus="invalid"],
QFrame#licenseStatusHero[licenseStatus="missing"],
QFrame#licenseStatusHero[licenseStatus="revoked"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #fef2f2, stop:1 #ffffff);
    border-color: #fca5a5;
}}

QLabel#licenseStatusPill {{
    padding: 5px 14px;
    border-radius: 20px;
    font-size: {caption_size}px;
    font-weight: {weight_section};
}}

QLabel#licenseStatusPill[licenseStatus="active"] {{
    background: #16a34a;
    color: #ffffff;
}}

QLabel#licenseStatusPill[licenseStatus="warning"] {{
    background: #d97706;
    color: #ffffff;
}}

QLabel#licenseStatusPill[licenseStatus="expired"],
QLabel#licenseStatusPill[licenseStatus="invalid"],
QLabel#licenseStatusPill[licenseStatus="missing"],
QLabel#licenseStatusPill[licenseStatus="revoked"] {{
    background: #dc2626;
    color: #ffffff;
}}

QLabel#licenseHeroTitle {{
    color: {primary};
    font-size: {title_size}px;
    font-weight: {weight_title};
    background: transparent;
}}

QLabel#licenseHeroSubtitle {{
    color: #64748b;
    font-size: {body_size}px;
    font-weight: 500;
    background: transparent;
}}

QProgressBar#licenseValidityBar {{
    border: none;
    border-radius: 6px;
    background: #e2e8f0;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
}}

QProgressBar#licenseValidityBar::chunk {{
    border-radius: 6px;
    background: {primary};
}}

QFrame#licenseInfoTile {{
    background: #ffffff;
    border: 1px solid {soft_border};
    border-radius: 12px;
}}

QLabel#licenseInfoCaption {{
    color: #94a3b8;
    font-size: {caption_size}px;
    font-weight: 600;
    background: transparent;
}}

QLabel#licenseInfoValue {{
    color: {pressed};
    font-size: {body_size}px;
    font-weight: {weight_section};
    background: transparent;
}}

QLabel#licenseSectionTitle {{
    color: {primary};
    font-size: {section_size}px;
    font-weight: {weight_section};
    background: transparent;
}}

QFrame#licenseActivationCard {{
    background: #ffffff;
    border: 1px solid {soft_border};
    border-radius: 14px;
}}

QLineEdit#licenseHwidDisplay,
QLineEdit#licenseKeyInput {{
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: {body_size}px;
    background: #f8fafc;
}}

QLineEdit#licenseKeyInput:focus,
QLineEdit#licenseHwidDisplay:focus {{
    border: 1.5px solid {primary};
    background: #ffffff;
}}

QPushButton#licenseCopyHwidBtn,
QPushButton#licenseActivateBtn {{
    background-color: {primary};
    color: #ffffff;
    border: none;
    border-radius: 9px;
    font-size: {body_size}px;
    font-weight: {weight_section};
    padding: 10px 18px;
}}

QPushButton#licenseCopyHwidBtn:hover,
QPushButton#licenseActivateBtn:hover {{
    background-color: {hover};
}}

QPushButton#licenseCopyHwidBtn:pressed,
QPushButton#licenseActivateBtn:pressed {{
    background-color: {pressed};
}}

QPushButton#licenseCopyHwidBtn {{
    background-color: #ffffff;
    color: {primary};
    border: 1px solid {soft_border};
}}

QPushButton#licenseCopyHwidBtn:hover {{
    background-color: {soft};
}}
"""


def build_license_welcome_stylesheet(
    palette: dict[str, str],
    font_size: int = 14,
    is_bold: bool = False,
) -> str:
    primary = palette["primary"]
    hover = palette["hover"]
    pressed = palette["pressed"]
    soft = palette["soft"]
    soft_border = palette["soft_border"]
    safe = max(11, int(font_size))
    title_size = max(22, safe + 7)
    section_size = max(15, safe + 2)
    body_size = max(13, safe - 1)
    caption_size = max(11, safe - 2)
    weight_title = "800" if is_bold else "700"
    weight_section = "700" if is_bold else "600"
    return f"""
QWidget#licenseWelcomeRoot {{
    background: #f1f5f9;
}}

QScrollArea#licenseWelcomeScroll {{
    background: transparent;
    border: none;
}}

QLabel#licenseWelcomeBrand {{
    color: {primary};
    font-size: {title_size}px;
    font-weight: {weight_title};
    background: transparent;
}}

QLabel#licenseWelcomeTagline {{
    color: #64748b;
    font-size: {body_size}px;
    font-weight: 500;
    background: transparent;
}}

QFrame#licenseWelcomeHero {{
    border-radius: 16px;
    border: 1px solid {soft_border};
    background: #ffffff;
}}

QFrame#licenseWelcomeHero[licenseStatus="missing"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #eef2ff, stop:1 #ffffff);
    border-color: #a5b4fc;
}}

QFrame#licenseWelcomeHero[licenseStatus="expired"],
QFrame#licenseWelcomeHero[licenseStatus="invalid"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #fff7ed, stop:1 #ffffff);
    border-color: #fdba74;
}}

QLabel#licenseWelcomeHeroTitle {{
    color: {primary};
    font-size: {max(18, safe + 4)}px;
    font-weight: {weight_title};
    background: transparent;
}}

QLabel#licenseWelcomeHeroSubtitle {{
    color: #475569;
    font-size: {body_size}px;
    font-weight: 500;
    background: transparent;
}}

QFrame#licenseWelcomeSteps,
QFrame#licenseWelcomeHwidCard,
QFrame#licenseWelcomeActivateCard {{
    background: #ffffff;
    border: 1px solid {soft_border};
    border-radius: 14px;
}}

QLabel#licenseWelcomeSectionTitle {{
    color: {primary};
    font-size: {section_size}px;
    font-weight: {weight_section};
    background: transparent;
}}

QLabel#licenseWelcomeCaption {{
    color: #94a3b8;
    font-size: {caption_size}px;
    font-weight: 600;
    background: transparent;
}}

QLabel#licenseWelcomeStepBadge {{
    background: {primary};
    color: #ffffff;
    border-radius: 15px;
    font-size: {body_size}px;
    font-weight: {weight_section};
}}

QLabel#licenseWelcomeStepText {{
    color: #334155;
    font-size: {body_size}px;
    font-weight: 500;
    background: transparent;
}}

QLineEdit#licenseWelcomeHwid,
QLineEdit#licenseWelcomeKeyInput {{
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: {body_size}px;
    background: #f8fafc;
}}

QLineEdit#licenseWelcomeKeyInput:focus,
QLineEdit#licenseWelcomeHwid:focus {{
    border: 1.5px solid {primary};
    background: #ffffff;
}}

QPushButton#licenseWelcomePrimaryBtn,
QPushButton#licenseWelcomeActivateBtn {{
    background-color: {primary};
    color: #ffffff;
    border: none;
    border-radius: 10px;
    font-size: {body_size}px;
    font-weight: {weight_section};
    padding: 10px 18px;
}}

QPushButton#licenseWelcomePrimaryBtn:hover,
QPushButton#licenseWelcomeActivateBtn:hover {{
    background-color: {hover};
}}

QPushButton#licenseWelcomePrimaryBtn:pressed,
QPushButton#licenseWelcomeActivateBtn:pressed {{
    background-color: {pressed};
}}

QPushButton#licenseWelcomeSecondaryBtn,
QPushButton#licenseWelcomeCopyBtn {{
    background-color: #ffffff;
    color: {primary};
    border: 1px solid {soft_border};
    border-radius: 10px;
    font-size: {body_size}px;
    font-weight: {weight_section};
    padding: 10px 18px;
}}

QPushButton#licenseWelcomeSecondaryBtn:hover,
QPushButton#licenseWelcomeCopyBtn:hover {{
    background-color: {soft};
}}
"""
