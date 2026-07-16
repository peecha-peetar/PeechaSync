"""ممیزی یکپارچگی تنظیمات — آیا مقادیر تب تنظیمات در runtime استفاده می‌شوند؟"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# کلیدهایی که در save_config نوشته می‌شوند
SETTINGS_KEYS = {
  # SQL
  "SQL_CONN_STRING": {
      "group": "sql",
      "used_by": ["sql_connection_helper", "ProductCategoriesSync", "sync_fullproduct", "ordersync", "customersync", "Poshakproperties", "tab_*"],
      "notes": "رشته اتصال از فیلدهای SQL در تنظیمات ساخته می‌شود",
  },
  "SQL_SERVER": {"group": "sql", "used_by": ["settings_tab", "sql_windows_probe", "diagnostics"]},
  "SQL_DATABASE": {"group": "sql", "used_by": ["header badge", "attach", "tabs"]},
  "SQL_AUTH_MODE": {"group": "sql", "used_by": ["sql_connection_helper"]},
  "SQL_USERNAME": {"group": "sql", "used_by": ["conn string builder"]},
  "SQL_PASSWORD": {"group": "sql", "used_by": ["conn string builder"]},
  "SQL_MDF_PATH": {"group": "sql", "used_by": ["attach database"]},
  # WooCommerce — flat keys از سایت فعال (WC_SITES)
  "WC_URL": {"group": "woocommerce", "used_by": ["wc_endpoint", "wc_rest_request", "probe_wc", "همه تب‌های sync"]},
  "WC_CONSUMER_KEY": {"group": "woocommerce", "used_by": ["get_wc_auth", "wc_rest_request"]},
  "WC_CONSUMER_SECRET": {"group": "woocommerce", "used_by": ["get_wc_auth"]},
  "WP_USERNAME": {"group": "woocommerce", "used_by": ["wp media upload", "category images"]},
  "WP_APP_PASSWORD": {"group": "woocommerce", "used_by": ["wp media upload"]},
  "WC_TIMEOUT": {"group": "woocommerce", "used_by": ["wc_timeout_pair"]},
  "WC_CURRENCY_IS_TOMAN": {"group": "woocommerce", "used_by": ["currency_helper", "tab_products", "tab_variations"]},
  "WC_SITES": {"group": "woocommerce", "used_by": ["wc_site_profiles", "settings_tab"]},
  "ACTIVE_WC_SITE_ID": {"group": "woocommerce", "used_by": ["wc_site_profiles"]},
  # کاتالوگ / ERP
  "PRICE_LIST_INDEX": {"group": "catalog", "used_by": ["article_price", "tab_products"]},
  "PRICE_LIST_COLUMN": {"group": "catalog", "used_by": ["sync_fullproduct", "tab_products", "tab_variations", "reconciliation"]},
  "SALE_PRICE_LIST_ENABLED": {"group": "catalog", "used_by": ["article_price"]},
  "SALE_PRICE_LIST_INDEX": {"group": "catalog", "used_by": ["article_price"]},
  "SALE_PRICE_LIST_COLUMN": {"group": "catalog", "used_by": ["article_price"]},
  "ERP_PICTURE_ROOT": {"group": "catalog", "used_by": ["erp_image_helper", "product images"]},
  "ERP_PROVIDER": {"group": "catalog", "used_by": ["erp_provider.get_provider", "tab_dashboard"]},
  # مشتری
  "DEFAULT_CUSTOMER_MODE": {"group": "customer", "used_by": ["customer_context", "customersync", "ordersync"]},
  "DEFAULT_CUSTOMER_CODE": {"group": "customer", "used_by": ["customer_context", "tab_customers"]},
  # ظاهر / ورود
  "APP_THEME": {"group": "ui", "used_by": ["app_theme", "peecha_launcher"]},
  "APP_FONT_SIZE": {"group": "ui", "used_by": ["launcher", "license tab"]},
  "APP_LOGIN_USERNAME": {"group": "auth", "used_by": ["login_window", "user_profile"]},
  "APP_LOGIN_PASSWORD": {"group": "auth", "used_by": ["login_window"]},
  "APP_SHOW_LOGIN_SCREEN": {"group": "auth", "used_by": ["peecha_launcher bootstrap"]},
  # لایسنس / بروزرسانی
  "LICENSE_SERVER_URL": {"group": "license", "used_by": ["license_remote", "app_update"]},
  "LICENSE_API_KEY": {"group": "license", "used_by": ["license_remote", "app_update"]},
  "AUTO_UPDATE_ENABLED": {"group": "license", "used_by": ["peecha_launcher startup"]},
}

# هاردکدهای مجاز (فقط وقتی config خالی است — نصب اول)
ALLOWED_INSTALL_DEFAULTS = {
    "SQL_SERVER": ["localhost", ".\\SQLEXPRESS"],
    "SQL_DATABASE": ["DejavuDB3", "DejavuDB"],
    "APP_LOGIN_USERNAME": ["admin"],
    "LICENSE_SERVER_URL": ["https://peecha.ir"],
}

# هاردکدهای مشکل‌دار در مسیر runtime (نباید URL/سرور ثابت بزنند)
_RUNTIME_HARDCODE_PATTERNS = [
    (re.compile(r'wc_endpoint\([^)]*["\']https?://[^"\']+peecha', re.I), "wc_endpoint با URL ثابت"),
    (re.compile(r'requests\.(get|post)\([^)]*peecha\.ir', re.I), "HTTP مستقیم به peecha در مسیر sync"),
    (re.compile(r'get\(["\']WC_URL["\']\)\s+or\s+["\']https?://peecha', re.I), "fallback WC_URL به peecha"),
    (re.compile(r'pyodbc\.connect\([^)]*SERVER=localhost', re.I), "SQL connect بدون config"),
]


@dataclass
class AuditFinding:
    level: str  # ok | warn | issue
    group: str
    message: str


def audit_config_values(config: dict | None) -> list[AuditFinding]:
    cfg = config or {}
    findings: list[AuditFinding] = []

    for key, meta in SETTINGS_KEYS.items():
        val = cfg.get(key)
        empty = val is None or (isinstance(val, str) and not str(val).strip())
        if key in ("WC_SITES", "SQL_LDF_PATH"):
            continue
        if empty and key in ("WC_URL", "WC_CONSUMER_KEY", "SQL_CONN_STRING"):
            findings.append(AuditFinding("warn", meta["group"], f"{key} خالی — عملیات مرتبط خطا می‌دهد"))
        elif not empty:
            findings.append(AuditFinding("ok", meta["group"], f"{key} = {str(val)[:60]}"))

    sites = cfg.get("WC_SITES")
    if isinstance(sites, list) and sites:
        active = cfg.get("ACTIVE_WC_SITE_ID", "")
        findings.append(AuditFinding("ok", "woocommerce", f"WC_SITES: {len(sites)} پروفایل، فعال={active}"))

    wc = str(cfg.get("WC_URL") or "")
    lic = str(cfg.get("LICENSE_SERVER_URL") or "")
    if wc and lic and "peecha.ir" in wc.lower() and "peecha.ir" not in lic.lower():
        findings.append(AuditFinding("ok", "woocommerce", "فروشگاه و سرور لایسنس جدا هستند"))

    return findings


def scan_runtime_hardcodes(project_root: Path) -> list[str]:
    issues: list[str] = []
    scan_dirs = [project_root / "sync_app" / "core"]
    skip_files = {"settings_audit.py", "license_remote.py", "update_ui.py", "license_welcome.py", "tab_license.py"}
    for base in scan_dirs:
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path.name in skip_files:
                continue
            rel = path.relative_to(project_root).as_posix()
            if any(x in rel for x in ("/integrations/", "/diagnostics/rules_")):
                continue
            text = path.read_text(encoding="utf-8")
            for pat, label in _RUNTIME_HARDCODE_PATTERNS:
                for m in pat.finditer(text):
                    line = text[: m.start()].count("\n") + 1
                    issues.append(f"{rel}:{line} — {label}")
    return issues


def format_settings_audit_report(config: dict | None, *, project_root: Path | None = None) -> str:
    root = project_root or Path(__file__).resolve().parents[2]
    lines = ["═══ ممیزی یکپارچگی تنظیمات PeechaSync ═══", ""]

    groups = ("sql", "woocommerce", "catalog", "customer", "ui", "auth", "license")
    findings = audit_config_values(config)
    for g in groups:
        items = [f for f in findings if f.group == g]
        if not items:
            continue
        lines.append(f"── {g.upper()} ──")
        for f in items:
            icon = {"ok": "✅", "warn": "⚠️", "issue": "❌"}.get(f.level, "•")
            lines.append(f"  {icon} {f.message}")
        lines.append("")

    code_issues = scan_runtime_hardcodes(root)
    if code_issues:
        lines.append("── اسکن هاردکد مشکوک در کد ──")
        for item in code_issues[:15]:
            lines.append(f"  ❌ {item}")
        if len(code_issues) > 15:
            lines.append(f"  ... و {len(code_issues) - 15} مورد دیگر")
    else:
        lines.append("✅ اسکن کد: مسیر sync/SQL/Woo بدون URL ثابت غیرمجاز")

    lines.extend([
        "",
        "── تفکیک عمدی (نه باگ) ──",
        "  • LICENSE_SERVER_URL: پیش‌فرض peecha.ir فقط اگر فیلد خالی باشد",
        "  • متن راهنمای UI لایسنس/بروزرسانی: از LICENSE_SERVER_URL خوانده می‌شود",
        "  • placeholder نصب اول: localhost / DejavuDB3 تا کاربر ذخیره کند",
        "",
        "── قانون طلایی runtime ──",
        "  • همگام‌سازی: load_secure_config() → WC_URL / SQL_CONN_STRING",
        "  • سایت Woo: WC_SITES + ACTIVE_WC_SITE_ID → flat keys",
        "  • تغییر سایت فعال: ذخیره فوری + reload_wc_dependent_tabs",
    ])
    return "\n".join(lines)
