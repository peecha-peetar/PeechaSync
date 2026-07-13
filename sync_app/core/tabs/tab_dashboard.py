"""
تب داشبورد - خلاصه sql و woo
"""
from __future__ import annotations

import os
import requests
from datetime import datetime, timedelta
from urllib.parse import urlparse

from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QProgressBar,
)

try:
    from sync_app.core.app_theme import (
        ALLOWED_THEMES,
        THEME_PALETTE,
        compute_responsive_font_size,
        resolve_user_font_pref,
    )
    from sync_app.core.jalali_log_formatter import format_datetime_jalali
    from sync_app.core.product_woo_map_helper import load_product_woo_map
    from sync_app.core.secure_config_loader import load_secure_config
    from sync_app.core.sql_connection_helper import connect_with_fallback
except ImportError:
    ALLOWED_THEMES = frozenset({"navy", "red", "green"})
    THEME_PALETTE = {}

    def resolve_user_font_pref(font_setting):
        return 14, False

    def compute_responsive_font_size(base_size, width, height):
        return base_size

    def load_product_woo_map():
        return {}

    def format_datetime_jalali(_dt=None):
        return datetime.now().strftime("%Y/%m/%d %H:%M")

    def load_secure_config(_):
        return {}

    def connect_with_fallback(*_args, **_kwargs):
        raise Exception("SQL helper unavailable")


STATUS_MAP = {
    "pending": "در انتظار",
    "processing": "در حال پردازش",
    "on-hold": "معلق",
    "completed": "تکمیل‌شده",
    "cancelled": "لغو‌شده",
    "refunded": "مسترد‌شده",
    "failed": "ناموفق",
}

DASH_THEME_MAP = {
    "navy": {
        "primary": "#1a2785",
        "hero_mid": "#312e81",
        "hero_end": "#4338ca",
        "panel_bg": "#ffffff",
        "panel_border": "#e2e8f0",
        "soft_bg": "#f1f5f9",
        "muted": "#64748b",
        "text": "#0f172a",
        "quick_hover": "#eef2ff",
        "quick_border_hover": "#818cf8",
    },
    "red": {
        "primary": "#a80f2d",
        "hero_mid": "#bf1a34",
        "hero_end": "#ce2e3f",
        "panel_bg": "#ffffff",
        "panel_border": "#f2d4d9",
        "soft_bg": "#f8fafc",
        "muted": "#6b7280",
        "text": "#3f1d24",
        "quick_hover": "#fff1f2",
        "quick_border_hover": "#e11d48",
    },
    "green": {
        "primary": "#0d7a39",
        "hero_mid": "#0f8a42",
        "hero_end": "#16a34a",
        "panel_bg": "#ffffff",
        "panel_border": "#cfe9d9",
        "soft_bg": "#f3f8f5",
        "muted": "#64748b",
        "text": "#0f2a1d",
        "quick_hover": "#ecfdf3",
        "quick_border_hover": "#22c55e",
    },
}


def _build_dash_palette(theme_name: str) -> dict:
    """پالت داشبورد — ترکیب تم سراسری با رنگ‌های gradient."""
    name = theme_name if theme_name in ALLOWED_THEMES else "navy"
    tp = THEME_PALETTE.get(name, THEME_PALETTE.get("navy", {}))
    legacy = DASH_THEME_MAP.get(name, DASH_THEME_MAP["navy"])
    if not tp:
        return dict(legacy)
    return {
        "primary": tp.get("primary", legacy["primary"]),
        "hero_mid": tp.get("hover", legacy["hero_mid"]),
        "hero_end": tp.get("hover", legacy["hero_end"]),
        "panel_bg": "#ffffff",
        "panel_border": tp.get("soft_border", legacy["panel_border"]),
        "soft_bg": tp.get("soft", legacy["soft_bg"]),
        "muted": legacy["muted"],
        "text": tp.get("pressed", legacy["text"]),
        "quick_hover": tp.get("soft", legacy["quick_hover"]),
        "quick_border_hover": tp.get("primary", legacy["quick_border_hover"]),
    }


def _resolve_font_base(config, width=0, height=0, runtime_base=None):
    if runtime_base is not None:
        return runtime_base
    base, _ = resolve_user_font_pref((config or {}).get("APP_FONT_SIZE", 14))
    if width > 0 and height > 0:
        return compute_responsive_font_size(base, width, height)
    return base


def _fmt_num(value):
    try:
        n = int(float(value))
        return f"{n:,}"
    except (TypeError, ValueError):
        return str(value) if value not in (None, "") else "—"


def _fmt_money(value, suffix="﷼"):
    if value in (None, "", "—"):
        return "—"
    try:
        n = float(value)
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M {suffix}"
        return f"{n:,.0f} {suffix}"
    except (TypeError, ValueError):
        return f"{value} {suffix}"


def _site_host(url):
    try:
        host = urlparse(url).netloc or urlparse(url).path
        return host.strip("/") or "—"
    except Exception:
        return "—"


# ──────────────────────────────────────────────────────────
class DashboardWorker(QObject):
    """بارگذاری آمار SQL و ووکامرس/وردپرس در پس‌زمینه."""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = dict(config or {})
        self.base_url = (self.config.get("WC_URL") or "").strip().rstrip("/")
        self.auth = (
            (self.config.get("WC_CONSUMER_KEY") or "").strip(),
            (self.config.get("WC_CONSUMER_SECRET") or "").strip(),
        )
        self.timeout = int(self.config.get("WC_TIMEOUT", 30) or 30)

    def _wc_url(self, endpoint):
        if "wp-json/wc/v3" in self.base_url:
            return f"{self.base_url}/{endpoint.lstrip('/')}"
        return f"{self.base_url}/wp-json/wc/v3/{endpoint.lstrip('/')}"

    def _wc_get(self, endpoint, params=None):
        resp = requests.get(
            self._wc_url(endpoint),
            auth=self.auth,
            params=params or {},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _load_sql(self, payload):
        sql = {"ok": False}
        try:
            conn, auth_mode, _conn_str = connect_with_fallback(self.config, timeout=8)
            cur = conn.cursor()

            cur.execute("SELECT DB_NAME(), @@SERVERNAME, SUSER_SNAME()")
            meta = cur.fetchone()
            sql.update({
                "ok": True,
                "auth_mode": auth_mode,
                "database": meta[0] if meta else "—",
                "server": meta[1] if meta and len(meta) > 1 else self.config.get("SQL_SERVER", "—"),
                "user": meta[2] if meta and len(meta) > 2 else "—",
            })

            queries = {
                "articles": "SELECT COUNT(*) FROM Article",
                "main_groups": "SELECT COUNT(*) FROM M_Group",
                "sub_groups": "SELECT COUNT(*) FROM S_Group",
            }
            for key, q in queries.items():
                try:
                    cur.execute(q)
                    sql[key] = int(cur.fetchone()[0])
                except Exception:
                    sql[key] = 0

            selected = self.config.get("SELECTED_SUB_GROUPS") or []
            sql["selected_groups"] = len(selected)

            try:
                if selected:
                    placeholders = ", ".join(["?"] * len(selected))
                    cur.execute(
                        f"SELECT COUNT(*) FROM Article WHERE LEFT(A_Code, 4) IN ({placeholders})",
                        list(selected),
                    )
                    sql["filtered_articles"] = int(cur.fetchone()[0])
                else:
                    sql["filtered_articles"] = sql.get("articles", 0)
            except Exception:
                sql["filtered_articles"] = 0

            try:
                cur.execute("SELECT SUM(CAST(ISNULL(Exist, 0) AS BIGINT)) FROM Article")
                sql["total_stock"] = int(cur.fetchone()[0] or 0)
            except Exception:
                sql["total_stock"] = 0

            conn.close()
        except Exception as exc:
            sql["error"] = str(exc)[:160]
        payload["sql"] = sql

    def _load_woo(self, payload):
        from sync_app.core.integrations.commerce_provider import is_prestashop

        if is_prestashop(self.config):
            self._load_ps_store(payload)
            return

        woo = {"ok": False, "configured": bool(self.base_url and self.auth[0] and self.auth[1])}
        if not woo["configured"]:
            woo["error"] = "تنظیمات ووکامرس ناقص است"
            payload["woo"] = woo
            return

        try:
            status = self._wc_get("system_status")
            env = status.get("environment", {}) if isinstance(status, dict) else {}
            woo.update({
                "ok": True,
                "wp_version": env.get("wp_version", "—"),
                "wc_version": env.get("version", "—"),
                "site_url": env.get("site_url") or self.base_url,
                "home_url": env.get("home_url", "—"),
                "currency": (status.get("settings", {}) or {}).get("currency", "") if isinstance(status, dict) else "",
            })
        except Exception as exc:
            woo["error"] = str(exc)[:120]

        try:
            sales = self._wc_get("reports/sales", {"period": "month"})
            woo["sales"] = sales[0] if isinstance(sales, list) and sales else {}
        except Exception:
            woo["sales"] = {}

        # فروش روزانه‌ی ۱۴ روز اخیر — برای نمودار روند فروش در داشبورد
        try:
            from datetime import datetime, timedelta
            date_max = datetime.now().date()
            date_min = date_max - timedelta(days=13)
            daily = self._wc_get(
                "reports/sales",
                {"date_min": date_min.isoformat(), "date_max": date_max.isoformat()},
            )
            totals = (daily[0] or {}).get("totals", {}) if isinstance(daily, list) and daily else {}
            daily_series = []
            for i in range(14):
                d = date_min + timedelta(days=i)
                key = d.isoformat()
                day_data = totals.get(key) or {}
                amount = float(day_data.get("sales") or 0)
                daily_series.append((d.strftime("%m/%d"), amount))
            woo["daily_sales"] = daily_series
        except Exception:
            woo["daily_sales"] = []

        for key, endpoint, params in [
            ("recent_orders", "orders", {"per_page": 8, "orderby": "date", "order": "desc"}),
            ("pending_orders", "orders", {"per_page": 6, "status": "processing"}),
            ("top_products", "reports/top_sellers", {"period": "month", "number": 6}),
        ]:
            try:
                woo[key] = self._wc_get(endpoint, params)
            except Exception:
                woo[key] = []

        for key, path in [("total_products", "products"), ("total_customers", "customers")]:
            try:
                resp = requests.get(
                    self._wc_url(path),
                    auth=self.auth,
                    params={"per_page": 1},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                woo[key] = int(resp.headers.get("X-WP-Total", 0))
            except Exception:
                woo[key] = 0

        payload["woo"] = woo

    def _ps_order_row_to_dashboard_shape(self, order, customer_names: dict):
        """پیش‌نمایش سفارش پرستاشاپ → همون شکل order (id/billing/status/total/date_created)
        که جدول‌های داشبورد (که اول برای ووکامرس نوشته شدن) انتظار دارن."""
        cid = int(order.get("customer_id") or 0)
        name = customer_names.get(cid)
        if name is None:
            name = ""
            if cid:
                try:
                    from sync_app.core.ps_customer_helper import ps_get_customer

                    customer = ps_get_customer(self.config, cid)
                    if customer:
                        billing = customer.get("billing") or {}
                        name = f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
                except Exception:
                    name = ""
            customer_names[cid] = name
        first_name, _, last_name = name.partition(" ")
        return {
            "id": order.get("id"),
            "billing": {"first_name": first_name, "last_name": last_name},
            "status": "پرداخت‌شده" if order.get("valid") else "در انتظار پرداخت",
            "total": order.get("total_paid"),
            "date_created": order.get("date_add", ""),
        }

    def _load_ps_store(self, payload):
        """معادل _load_woo برای پرستاشاپ — کلید payload["woo"] عمداً همون اسم قبلی
        مونده (فقط یک کلید داخلی، به کاربر نمایش داده نمی‌شه) تا رندر جدول‌ها/
        نمودارهای داشبورد بدون شاخه‌زدن اضافه، بین دو پلتفرم مشترک بمونه.

        ⚠️ پرستاشاپ resource گزارش‌گیری آماده (reports/sales و مشابه ووکامرس)
        نداره — گزارش فروش از خودِ sales_report_helper.build_sales_report ساخته
        می‌شه که برای این پلتفرم، همه‌ی سفارش‌های valid=1 رو می‌خونه و خودش جمع
        می‌بنده (نه یک endpoint آماده‌ی سرور). برای فروشگاه‌های با تاریخچه‌ی
        خیلی بزرگ ممکنه این بخش کند باشه.
        """
        from sync_app.core.ps_sync_helper import check_prestashop_connection, ps_count_products
        from sync_app.core.ps_customer_helper import ps_count_customers
        from sync_app.core.ps_order_helper import ps_list_recent_orders_preview
        from sync_app.core.sales_report_helper import build_sales_report

        ps_url = (self.config.get("PS_URL") or "").strip()
        ps_key = (self.config.get("PS_API_KEY") or "").strip()
        woo = {"ok": False, "configured": bool(ps_url and ps_key), "platform": "prestashop"}
        if not woo["configured"]:
            woo["error"] = "تنظیمات پرستاشاپ ناقص است"
            payload["woo"] = woo
            return

        try:
            ok, message, currency = check_prestashop_connection(self.config, update_config_status=False)
            woo["ok"] = ok
            woo["site_url"] = ps_url
            woo["home_url"] = ps_url
            woo["currency"] = "" if currency in (None, "N/A") else currency
            if not ok:
                woo["error"] = message
        except Exception as exc:
            woo["error"] = str(exc)[:120]

        try:
            report = build_sales_report(self.config, since_days=30)
            woo["sales"] = {"total_orders": report.total_orders, "net_revenue": report.total_revenue}
            date_max = datetime.now().date()
            date_min = date_max - timedelta(days=13)
            daily_series = []
            for i in range(14):
                d = date_min + timedelta(days=i)
                amount = float(report.daily_revenue.get(d.isoformat()) or 0)
                daily_series.append((d.strftime("%m/%d"), amount))
            woo["daily_sales"] = daily_series
            woo["top_products"] = [
                {"name": s.name or s.sku, "quantity": s.qty_sold, "total": s.revenue}
                for s in report.top_products(6)
            ]
        except Exception:
            woo["sales"] = {}
            woo["daily_sales"] = []
            woo["top_products"] = []

        customer_names: dict = {}
        try:
            recent = ps_list_recent_orders_preview(self.config, limit=8, timeout=self.timeout)
            woo["recent_orders"] = [
                self._ps_order_row_to_dashboard_shape(o, customer_names) for o in recent
            ]
        except Exception:
            woo["recent_orders"] = []

        try:
            candidates = ps_list_recent_orders_preview(self.config, limit=50, timeout=self.timeout)
            pending = [o for o in candidates if not o.get("valid")][:6]
            woo["pending_orders"] = [
                self._ps_order_row_to_dashboard_shape(o, customer_names) for o in pending
            ]
        except Exception:
            woo["pending_orders"] = []

        try:
            woo["total_products"] = ps_count_products(self.config, timeout=self.timeout)
        except Exception:
            woo["total_products"] = 0
        try:
            woo["total_customers"] = ps_count_customers(self.config, timeout=self.timeout)
        except Exception:
            woo["total_customers"] = 0

        payload["woo"] = woo

    def run(self):
        payload = {
            "loaded_at": format_datetime_jalali(),
            "config": {
                "erp_provider": self.config.get("ERP_PROVIDER", "dejavu"),
                "wc_host": _site_host(self.base_url),
                "sql_server": self.config.get("SQL_SERVER", "—"),
                "sql_database": self.config.get("SQL_DATABASE", "—"),
                "price_list": (self.config.get("PRICE_LIST_INDEX", 0) or 0) + 1,
                "selected_groups": len(self.config.get("SELECTED_SUB_GROUPS") or []),
            },
        }
        try:
            self._load_sql(payload)
            self._load_woo(payload)
            try:
                from sync_app.core.auto_sync_scope import compute_unlinked_counts
                payload["link_health"] = compute_unlinked_counts(self.config)
            except Exception:
                payload["link_health"] = None
            self.finished.emit(payload)
        except Exception as exc:
            self.error.emit(str(exc))


# ──────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, title, value="—", subtitle="", icon="", accent="#1a2785", parent=None):
        super().__init__(parent)
        self.setObjectName("dashStatCard")
        self.setMinimumHeight(108)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._accent = accent
        self.setStyleSheet("")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedWidth(32)
        icon_lbl.setStyleSheet(
            f"font-size: 18px; background: {accent}14; border-radius: 16px; padding: 4px;"
        )
        icon_lbl.setAlignment(Qt.AlignCenter)
        top.addWidget(icon_lbl)
        top.addStretch()
        layout.addLayout(top)

        self.value_label = QLabel(str(value))
        self.value_label.setStyleSheet(f"font-weight: 800; color: {accent};")
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.value_label)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("color: #64748b; font-weight: 600;")
        title_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(title_lbl)
        self.title_label = title_lbl

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setStyleSheet("color: #94a3b8;")
        self.subtitle_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.subtitle_label)

    def apply_theme(self, palette, font_base):
        accent = self._accent
        self.setStyleSheet(f"""
            QFrame#dashStatCard {{
                background: {palette['panel_bg']};
                border: 1px solid {palette['panel_border']};
                border-right: 4px solid {accent};
                border-radius: 14px;
            }}
        """)
        self.value_label.setStyleSheet(f"font-size: {max(18, font_base + 6)}px; font-weight: 800; color: {accent};")
        self.title_label.setStyleSheet(f"font-size: {max(11, font_base - 2)}px; color: {palette['muted']}; font-weight: 600;")
        self.subtitle_label.setStyleSheet(f"font-size: {max(10, font_base - 3)}px; color: #94a3b8;")

    def update_card(self, value, subtitle=""):
        self.value_label.setText(str(value))
        if subtitle:
            self.subtitle_label.setText(subtitle)


class HealthCard(QFrame):
    def __init__(self, title, icon, parent=None):
        super().__init__(parent)
        self.setObjectName("dashHealthCard")
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.icon_label = QLabel(icon)
        self.icon_label.setStyleSheet("font-size: 20px;")
        header.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: 700; color: #0f172a;")
        header.addWidget(self.title_label)
        header.addStretch()

        self.badge = QLabel("در انتظار")
        self.badge.setProperty("role", "badge-info")
        header.addWidget(self.badge)
        layout.addLayout(header)

        self.detail_label = QLabel("—")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: #475569; line-height: 1.4;")
        layout.addWidget(self.detail_label)

        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet("color: #94a3b8;")
        layout.addWidget(self.meta_label)

    def apply_theme(self, palette, font_base):
        self.title_label.setStyleSheet(f"font-size: {max(12, font_base - 1)}px; font-weight: 700; color: {palette['text']};")
        self.detail_label.setStyleSheet(f"font-size: {max(11, font_base - 2)}px; color: #475569; line-height: 1.4;")
        self.meta_label.setStyleSheet(f"font-size: {max(10, font_base - 3)}px; color: #94a3b8;")

    def set_status(self, ok, detail, meta="", warning=False):
        if ok:
            role = "badge-success"
            text = "آنلاین"
        elif warning:
            role = "badge-warning"
            text = "ناقص"
        else:
            role = "badge-error"
            text = "آفلاین"

        self.badge.setProperty("role", role)
        self.badge.setText(text)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.detail_label.setText(detail or "—")
        self.meta_label.setText(meta or "")


class DashboardTab(QWidget):
    def __init__(self, navigate_callback=None, parent=None):
        super().__init__(parent)
        self.setObjectName("dashTabRoot")
        self.navigate_callback = navigate_callback
        self.setLayoutDirection(Qt.RightToLeft)
        self._thread = None
        self._worker = None
        self._current_palette = _build_dash_palette("navy")
        self._quick_buttons = []
        self._section_labels = []
        self._kpi_cards = []
        self._kpi_grid = None
        self._is_kpi_compact = False
        self._initial_load_started = False
        self._runtime_font_base = None
        self._theme_signature = None
        self._init_ui()
        self._apply_dashboard_theme()

    def apply_runtime_font(self, effective_font_size: int, is_bold: bool = False):
        """همگام با تغییر فونت/سایز در تنظیمات."""
        self._runtime_font_base = effective_font_size
        self._theme_signature = None
        self._apply_dashboard_theme()

    def ensure_tab_data_loaded(self):
        if self._initial_load_started:
            return
        self._initial_load_started = True
        self.load_data()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("dashScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        container = QWidget()
        container.setObjectName("dashRoot")
        self._container = container
        self._root = QVBoxLayout(container)
        self._root.setContentsMargins(18, 18, 18, 22)
        self._root.setSpacing(16)
        scroll.setWidget(container)

        # ── هدر ───────────────────────────────────────
        hero = QFrame()
        hero.setObjectName("dashHero")
        self._hero = hero
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(8)

        hero_top = QHBoxLayout()
        hero_title = QLabel("📊 مرکز فرمان پیچا")
        hero_title.setObjectName("dashHeroTitle")
        hero_top.addWidget(hero_title)
        hero_title.setToolTip("نمای کلی وضعیت اتصال‌ها، داده‌های ERP و آمار ووکامرس در یک صفحه")
        hero_top.addStretch()

        self.refresh_btn = QPushButton("↻ بازخوانی")
        self.refresh_btn.setObjectName("dashRefreshBtn")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.setToolTip("بارگذاری دوباره وضعیت SQL، API ووکامرس، KPIها و جداول")
        self.refresh_btn.clicked.connect(self.load_data)
        hero_top.addWidget(self.refresh_btn)
        hero_layout.addLayout(hero_top)

        hero_sub = QLabel(
            "نمای یکپارچه دیتابیس ERP (SQL Server)، فروشگاه ووکامرس/وردپرس و وضعیت همگام‌سازی"
        )
        hero_sub.setWordWrap(True)
        hero_sub.setObjectName("dashHeroSub")
        hero_layout.addWidget(hero_sub)

        self.load_progress = QProgressBar()
        self.load_progress.setObjectName("dashLoadProgress")
        self.load_progress.setRange(0, 0)
        self.load_progress.setVisible(False)
        self.load_progress.setTextVisible(False)
        self.load_progress.setFixedHeight(6)
        hero_layout.addWidget(self.load_progress)

        self.status_label = QLabel("در انتظار بارگذاری...")
        self.status_label.setObjectName("dashHeroStatus")
        hero_layout.addWidget(self.status_label)
        self._root.addWidget(hero)

        # ── سلامت سیستم ───────────────────────────────
        health_title = QLabel("وضعیت اتصال‌ها")
        health_title.setProperty("role", "section-title")
        health_title.setToolTip("نتیجه اتصال زنده به SQL Server، API ووکامرس و وضعیت سایت")
        self._section_labels.append(health_title)
        self._root.addWidget(health_title)
        health_hint = QLabel(
            "راهنما: اگر هر کارت آفلاین بود، ابتدا تب تنظیمات را بررسی و اتصال همان سرویس را تست کنید."
        )
        health_hint.setObjectName("dashSectionHint")
        health_hint.setWordWrap(True)
        self._root.addWidget(health_hint)

        health_row = QHBoxLayout()
        health_row.setSpacing(12)
        self._health_sql = HealthCard("SQL Server — ERP", "🗄️")
        self._health_wc = HealthCard("ووکامرس API", "🛒")
        self._health_wp = HealthCard("وردپرس / فروشگاه", "🌐")
        for card in (self._health_sql, self._health_wc, self._health_wp):
            health_row.addWidget(card)
        self._root.addLayout(health_row)

        # ── KPI ───────────────────────────────────────
        kpi_title = QLabel("شاخص‌های کلیدی")
        kpi_title.setProperty("role", "section-title")
        kpi_title.setToolTip("خلاصه عددی دامنه همگام‌سازی: کالاها، مشتریان، سفارش و درآمد")
        self._section_labels.append(kpi_title)
        self._root.addWidget(kpi_title)
        kpi_hint = QLabel(
            "راهنما: کارت «دامنه همگام‌سازی» از گروه‌های انتخابی در تب دسته‌بندی "
            "و لیست قیمت تنظیمات خوانده می‌شود."
        )
        kpi_hint.setObjectName("dashSectionHint")
        kpi_hint.setWordWrap(True)
        self._root.addWidget(kpi_hint)

        self._kpi_grid = QGridLayout()
        self._kpi_grid.setSpacing(12)
        self._card_sql_products = StatCard("کالاهای ERP", "—", "کل رکوردهای Article", "📦", "#1a2785")
        self._card_sync_scope = StatCard("دامنه همگام‌سازی", "—", "گروه‌های انتخاب‌شده", "🎯", "#7c3aed")
        self._card_wc_products = StatCard("محصولات ووکامرس", "—", "منتشرشده در سایت", "🏷️", "#2563eb")
        self._card_customers = StatCard("مشتریان سایت", "—", "حساب‌های ووکامرس", "👥", "#0891b2")
        self._card_orders = StatCard("سفارشات ماه", "—", "گزارش فروش ماه جاری", "🧾", "#d97706")
        self._card_revenue = StatCard("درآمد ماه", "—", "خالص فروش ماه جاری", "💰", "#16a34a")
        self._card_sql_products.setToolTip("تعداد کل کالاهای موجود در ERP (جدول Article)")
        self._card_sync_scope.setToolTip("تعداد زیرگروه‌های انتخابی و کالاهای داخل دامنه همگام‌سازی")
        self._card_wc_products.setToolTip("تعداد محصولات ثبت‌شده در ووکامرس")
        self._card_customers.setToolTip("تعداد حساب‌های مشتری در سایت ووکامرس")
        self._card_orders.setToolTip("تعداد سفارشات ماه جاری بر اساس گزارش ووکامرس")
        self._card_revenue.setToolTip("فروش/درآمد ماه جاری از گزارش‌های WooCommerce")

        cards = [
            self._card_sql_products, self._card_sync_scope, self._card_wc_products,
            self._card_customers, self._card_orders, self._card_revenue,
        ]
        self._kpi_cards = cards
        self._arrange_kpi_cards(columns=3)
        self._root.addLayout(self._kpi_grid)

        # ── مدیریت سریع + خلاصه ERP/Woo ───────────────
        mid_row = QHBoxLayout()
        mid_row.setSpacing(12)

        quick_frame = QFrame()
        quick_frame.setObjectName("dashPanel")
        quick_layout = QVBoxLayout(quick_frame)
        quick_layout.setContentsMargins(14, 12, 14, 14)
        quick_title = QLabel("مدیریت سریع")
        quick_title.setObjectName("dashPanelTitle")
        quick_title.setToolTip("میانبر ورود به تب‌های عملیاتی اصلی")
        quick_layout.addWidget(quick_title)
        quick_hint = QLabel(
            "راهنما: برای هر عملیات ابتدا وارد تب مربوطه شوید و وضعیت لاگ همان تب را بررسی کنید."
        )
        quick_hint.setObjectName("dashSectionHint")
        quick_hint.setWordWrap(True)
        quick_layout.addWidget(quick_hint)

        quick_grid = QGridLayout()
        quick_grid.setSpacing(8)
        actions = [
            ("⚙️ تنظیمات اتصال", "تنظیمات"),
            ("⚖️ تطبیق ERP ↔ سایت", "تطبیق"),
            ("📊 تب شروع", "شروع"),
            ("📂 دسته‌بندی ERP", "دسته"),
            ("📦 محصولات", "محصول"),
            ("🎨 متغیرها", "متغیر"),
            ("👥 مشتریان", "مشتری"),
            ("🧾 سفارشات", "سفارش"),
            ("📄 لاگ‌ها", "لاگ"),
            ("⚡ همگام‌سازی خودکار", "خودکار"),
        ]
        for i, (label, kw) in enumerate(actions):
            btn = QPushButton(label)
            btn.setObjectName("dashQuickBtn")
            btn.setMinimumHeight(40)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"باز کردن بخش «{label}» برای تنظیم/اجرای عملیات مربوطه")
            self._quick_buttons.append(btn)
            btn.clicked.connect(lambda _c=False, k=kw: self._navigate(k))
            quick_grid.addWidget(btn, i // 2, i % 2)
        quick_layout.addLayout(quick_grid)


        insight_frame = QFrame()
        insight_frame.setObjectName("dashPanel")
        insight_frame.setLayoutDirection(Qt.RightToLeft)
        insight_layout = QVBoxLayout(insight_frame)
        insight_layout.setContentsMargins(14, 12, 14, 14)
        insight_title = QLabel("🗂️ خلاصه‌ی تنظیمات برنامه")
        insight_title.setObjectName("dashPanelTitle")
        insight_title.setLayoutDirection(Qt.RightToLeft)
        insight_title.setAlignment(Qt.AlignRight)
        insight_title.setToolTip("جمع‌بندی همه‌ی تنظیمات مهم فروشگاه در یک نگاه")
        insight_layout.addWidget(insight_title)
        insight_hint = QLabel("این خلاصه بر اساس تنظیمات ذخیره‌شده و آخرین اتصال ساخته می‌شود.")
        insight_hint.setObjectName("dashSectionHint")
        insight_hint.setLayoutDirection(Qt.RightToLeft)
        insight_hint.setAlignment(Qt.AlignRight)
        insight_hint.setWordWrap(True)
        insight_layout.addWidget(insight_hint)

        # هر ردیف یه QLabel جدا و کاملاً راست‌چین — عمداً از HTML پیچیده یا
        # قاطی‌کردن اعداد لاتین وسط جمله پرهیز شده تا ترتیب نمایش به‌هم نریزه.
        self._summary_lines = {
            "product_mode": QLabel("📦 نوع محصولات:  —"),
            "auto_sync": QLabel("⚡ همگام‌سازی خودکار:  —"),
            "license": QLabel("🔐 اعتبار لایسنس:  —"),
            "price_list": QLabel("💰 لیست قیمت انتخابی:  —"),
            "sale_price": QLabel("🏷️ قیمت ویژه:  —"),
            "currency": QLabel("💱 واحد پول سایت:  —"),
        }
        for key, lbl in self._summary_lines.items():
            lbl.setLayoutDirection(Qt.RightToLeft)
            lbl.setAlignment(Qt.AlignRight)
            lbl.setWordWrap(True)
            lbl.setObjectName("dashInsightLine")
            insight_layout.addWidget(lbl)

        self._insight_erp = QLabel("ERP: —")
        self._insight_wc = QLabel("ووکامرس: —")
        self._insight_recon = QLabel("تطبیق: —")
        self._insight_sync = QLabel("همگام‌سازی: —")
        self._insight_erp.setToolTip("اطلاعات سرور/دیتابیس ERP، تعداد گروه‌ها و لیست قیمت فعال")
        self._insight_wc.setToolTip("نسخه و آمار فروشگاه ووکامرس/وردپرس")
        self._insight_recon.setToolTip("تعداد جفت‌های ثبت‌شده در product_woo_map")
        self._insight_sync.setToolTip("بررسی آمادگی عملیات همگام‌سازی بر اساس اتصال‌ها و گروه‌های انتخابی")
        for lbl in (self._insight_erp, self._insight_wc, self._insight_recon, self._insight_sync):
            lbl.setWordWrap(True)
            lbl.setLayoutDirection(Qt.RightToLeft)
            lbl.setAlignment(Qt.AlignRight)
            lbl.setObjectName("dashInsightLine")
            insight_layout.addWidget(lbl)
        insight_layout.addStretch()
        mid_row.addWidget(insight_frame, 1)
        mid_row.addWidget(quick_frame, 2)
        self._root.addLayout(mid_row)

        # ── نمودارها ─────────────────────────────────
        from sync_app.core.widgets.mini_bar_chart import MiniBarChart

        charts_row = QHBoxLayout()
        charts_row.setSpacing(12)

        revenue_frame = QFrame()
        revenue_frame.setObjectName("dashTablePanel")
        revenue_layout = QVBoxLayout(revenue_frame)
        self._revenue_chart = MiniBarChart()
        revenue_layout.addWidget(self._revenue_chart)
        revenue_frame.setToolTip("روند فروش ۱۴ روز اخیر (تومان) — بر اساس گزارش فروش ووکامرس")
        charts_row.addWidget(revenue_frame, 1)

        topprod_frame = QFrame()
        topprod_frame.setObjectName("dashTablePanel")
        topprod_layout = QVBoxLayout(topprod_frame)
        self._topprod_chart = MiniBarChart()
        topprod_layout.addWidget(self._topprod_chart)
        topprod_frame.setToolTip("تعداد فروش پرفروش‌ترین محصولات ماه جاری")
        charts_row.addWidget(topprod_frame, 1)

        health_frame = QFrame()
        health_frame.setObjectName("dashTablePanel")
        health_layout = QVBoxLayout(health_frame)
        self._health_chart = MiniBarChart()
        health_layout.addWidget(self._health_chart)
        health_frame.setToolTip("تعداد محصولات لینک‌شده در برابر لینک‌نشده به ووکامرس")
        charts_row.addWidget(health_frame, 1)

        self._root.addLayout(charts_row)

        # ── جداول ────────────────────────────────────
        self._orders_table = self._build_table(
            "آخرین سفارشات ووکامرس",
            ["شناسه", "مشتری", "وضعیت", "مبلغ", "تاریخ"],
            min_h=200,
        )
        self._orders_table["frame"].setToolTip("آخرین سفارشات ثبت‌شده در ووکامرس برای پایش سریع وضعیت فروش")
        self._root.addWidget(self._orders_table["frame"])

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self._top_table = self._build_table(
            "پرفروش‌ترین محصولات (ماه)",
            ["محصول", "تعداد", "درآمد"],
            min_h=170,
        )
        self._pending_table = self._build_table(
            "سفارشات در حال پردازش",
            ["شناسه", "مشتری", "مبلغ"],
            min_h=170,
        )
        self._top_table["frame"].setToolTip("کالاهای پرفروش ماه جاری برای تصمیم‌گیری روی موجودی و قیمت")
        self._pending_table["frame"].setToolTip("سفارشات در وضعیت processing که معمولاً در صف انتقال به ERP هستند")
        bottom.addWidget(self._top_table["frame"], 1)
        bottom.addWidget(self._pending_table["frame"], 1)
        self._root.addLayout(bottom)
        self._root.addStretch()

        self.footer_status = QFrame()
        self.footer_status.setObjectName("reconStatusBar")
        self.footer_status.setProperty("state", "info")
        footer_row = QHBoxLayout(self.footer_status)
        footer_row.setContentsMargins(10, 6, 10, 6)
        self.footer_message = QLabel("💡 برای داده کامل، تنظیمات SQL و WooCommerce را کامل کنید سپس «بازخوانی» بزنید.")
        self.footer_message.setObjectName("reconStatusMessage")
        self.footer_message.setWordWrap(True)
        footer_row.addWidget(self.footer_message, 1)
        outer.addWidget(self.footer_status)

    def _resolve_theme_name(self):
        cfg = load_secure_config(None) or {}
        name = (cfg.get("APP_THEME") or "navy").strip().lower()
        return name if name in ALLOWED_THEMES else "navy"

    @staticmethod
    def _clear_grid_layout(grid):
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _arrange_kpi_cards(self, columns: int):
        if not self._kpi_grid or not self._kpi_cards:
            return
        self._clear_grid_layout(self._kpi_grid)
        for index, card in enumerate(self._kpi_cards):
            self._kpi_grid.addWidget(card, index // columns, index % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() <= 900
        if compact != self._is_kpi_compact:
            self._arrange_kpi_cards(2 if compact else 3)
            self._is_kpi_compact = compact
        if self._runtime_font_base is None:
            cfg = load_secure_config(None) or {}
            new_base = _resolve_font_base(cfg, self.width(), self.height())
            theme_name = self._resolve_theme_name()
            if (new_base, theme_name) != getattr(self, "_theme_signature", None):
                self._apply_dashboard_theme()

    def _set_footer_status(self, state: str, message: str):
        self.footer_status.setProperty("state", state)
        self.footer_message.setText(message)
        self.footer_status.style().unpolish(self.footer_status)
        self.footer_status.style().polish(self.footer_status)

    def update_connectivity_quick(self, sql_ok, wc_ok):
        """کارت‌های اتصال بدون api جدید."""
        if sql_ok:
            self._health_sql.set_status(True, "اتصال برقرار است")
        else:
            self._health_sql.set_status(False, "اتصال قطع شد")

        if wc_ok:
            self._health_wc.set_status(True, "API فعال")
            self._health_wp.set_status(True, "وردپرس در دسترس")
        else:
            self._health_wc.set_status(False, "اتصال قطع شد")
            self._health_wp.set_status(False, "نیاز به اتصال ووکامرس", warning=True)

    def _apply_dashboard_theme(self):
        cfg = load_secure_config(None) or {}
        font_base = _resolve_font_base(
            cfg,
            self.width(),
            self.height(),
            runtime_base=self._runtime_font_base,
        )
        theme_name = self._resolve_theme_name()
        theme_signature = (font_base, theme_name)
        if theme_signature == getattr(self, "_theme_signature", None):
            return
        self._theme_signature = theme_signature
        palette = _build_dash_palette(theme_name)
        self._current_palette = palette

        self._container.setStyleSheet(f"QWidget#dashRoot {{ background: {palette['soft_bg']}; }}")
        self._hero.setStyleSheet(
            "QFrame#dashHero {"
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {palette['primary']}, stop:0.55 {palette['hero_mid']}, stop:1 {palette['hero_end']});"
            "border-radius: 16px;"
            "}"
            "QLabel { background: transparent; }"
        )

        self.refresh_btn.setStyleSheet(
            "QPushButton#dashRefreshBtn {"
            "background: rgba(255,255,255,0.15);"
            "color: #ffffff;"
            "border: 1px solid rgba(255,255,255,0.35);"
            "border-radius: 10px;"
            f"padding: {max(7, font_base - 6)}px {max(14, font_base)}px;"
            "font-weight: 700;"
            "}"
            "QPushButton#dashRefreshBtn:hover { background: rgba(255,255,255,0.25); }"
            "QPushButton#dashRefreshBtn:disabled { color: #cbd5e1; }"
        )

        panel_css = (
            "QFrame#dashPanel {"
            f"background: {palette['panel_bg']};"
            f"border: 1px solid {palette['panel_border']};"
            "border-radius: 14px;"
            "}"
        )
        for frame in self.findChildren(QFrame, "dashPanel"):
            frame.setStyleSheet(panel_css)

        for frame in self.findChildren(QFrame, "dashTablePanel"):
            frame.setStyleSheet(panel_css)

        quick_css = (
            "QPushButton#dashQuickBtn {"
            f"background: {palette['panel_bg']};"
            f"border: 1px solid {palette['panel_border']};"
            "border-radius: 10px;"
            "text-align: right;"
            "padding: 8px 12px;"
            "font-weight: 600;"
            f"color: {palette['text']};"
            "}"
            "QPushButton#dashQuickBtn:hover {"
            f"background: {palette['quick_hover']};"
            f"border-color: {palette['quick_border_hover']};"
            "}"
        )
        for btn in self._quick_buttons:
            btn.setStyleSheet(quick_css)

        for section in self._section_labels:
            section.setStyleSheet(f"color: {palette['text']};")

        insight_css = f"color: {palette['text']}; padding: 4px 0;"
        for lbl in (self._insight_erp, self._insight_wc, self._insight_recon, self._insight_sync):
            lbl.setStyleSheet(insight_css)

        for card in [
            self._card_sql_products,
            self._card_sync_scope,
            self._card_wc_products,
            self._card_customers,
            self._card_orders,
            self._card_revenue,
        ]:
            card.apply_theme(palette, font_base)

        for health in [self._health_sql, self._health_wc, self._health_wp]:
            health.apply_theme(palette, font_base)

    def _build_table(self, title, headers, min_h=180):
        frame = QFrame()
        frame.setObjectName("dashTablePanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        lbl = QLabel(title)
        lbl.setObjectName("dashTableTitle")
        layout.addWidget(lbl)

        table = QTableWidget(0, len(headers))
        table.setObjectName("dashTable")
        table.setHorizontalHeaderLabels(headers)
        table.setLayoutDirection(Qt.RightToLeft)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.horizontalHeader().setLayoutDirection(Qt.RightToLeft)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(min_h)
        layout.addWidget(table)
        return {"frame": frame, "table": table}

    def _navigate(self, keyword):
        if callable(self.navigate_callback):
            self.navigate_callback(keyword)

    def load_data(self):
        self._apply_dashboard_theme()
        config = load_secure_config(None) or {}
        if self._thread and self._thread.isRunning():
            return

        needs_setup = (not config.get("SQL_CONN_STRING")) or (not config.get("WC_URL"))

        self.refresh_btn.setEnabled(False)
        self.load_progress.setVisible(True)
        if needs_setup:
            msg = "راهنما: برای داده کامل داشبورد، ابتدا تنظیمات SQL و WooCommerce را کامل کنید."
            self.status_label.setText(f"{msg} | در حال جمع‌آوری...")
            self._set_footer_status("warning", f"⚠ {msg}")
        else:
            self.status_label.setText("در حال جمع‌آوری داده از SQL و ووکامرس...")
            self._set_footer_status("loading", "⏳ در حال بارگذاری آمار ERP و ووکامرس...")

        self._worker = DashboardWorker(config)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_data_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_thread_finished(self):
        self._thread = None
        self._worker = None
        self.refresh_btn.setEnabled(True)
        self.load_progress.setVisible(False)

    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1500)
        super().closeEvent(event)

    def _on_error(self, msg):
        self.status_label.setText(f"خطا در بارگذاری: {msg[:100]}")
        self._set_footer_status("error", f"❌ خطا در بارگذاری داشبورد: {msg[:120]}")

    def _on_data_loaded(self, data):
        cfg = data.get("config", {})
        sql = data.get("sql", {})
        woo = data.get("woo", {})
        loaded_at = data.get("loaded_at", "")

        self.status_label.setText(f"آخرین بروزرسانی: {loaded_at}")

        map_count = len(load_product_woo_map() or {})
        if map_count > 0:
            recon_msg = f"{_fmt_num(map_count)} جفت محصول در product_woo_map ثبت شده است."
        else:
            recon_msg = "نگاشت محصول خالی است — برای سایت فعال، تب «تطبیق» را انجام دهید."
        self._insight_recon.setText(f"<b>تطبیق</b><br>{recon_msg}")

        # ── Health cards ─────────────────────────────
        if sql.get("ok"):
            self._health_sql.set_status(
                True,
                f"{sql.get('server', '—')}  →  {sql.get('database', '—')}",
                f"Auth: {sql.get('auth_mode', '—')} | User: {sql.get('user', '—')}",
            )
        else:
            self._health_sql.set_status(False, sql.get("error", "اتصال برقرار نشد"))

        wc_ok = woo.get("ok", False)
        if wc_ok:
            self._health_wc.set_status(
                True,
                f"API فعال | WC {woo.get('wc_version', '—')}",
                f"Host: {cfg.get('wc_host', '—')}",
            )
        elif woo.get("configured"):
            self._health_wc.set_status(False, woo.get("error", "خطای API"))
        else:
            self._health_wc.set_status(False, "کلید API یا URL وارد نشده", warning=True)

        if wc_ok and woo.get("platform") == "prestashop":
            # پرستاشاپ ویزارد راه‌اندازی صفحات cart/checkout ووکامرس رو نداره —
            # هر فروشگاه پرستاشاپ به‌طور پیش‌فرض cart/checkout فعال داره.
            self._health_wp.set_status(
                True,
                _site_host(woo.get("home_url") or woo.get("site_url", "")),
                f"پرستاشاپ | ارز: {woo.get('currency') or '—'}",
            )
        elif wc_ok:
            from sync_app.core.scripts.woocommerce_store_setup import store_pages_ready
            pages_ok = store_pages_ready(load_secure_config(None))
            if pages_ok:
                self._health_wp.set_status(
                    True,
                    _site_host(woo.get("home_url") or woo.get("site_url", "")),
                    f"WordPress {woo.get('wp_version', '—')} | Cart/Checkout ✓",
                )
            else:
                self._health_wp.set_status(
                    False,
                    _site_host(woo.get("home_url") or woo.get("site_url", "")),
                    "Cart/Checkout راه‌اندازی نشده — تنظیمات → راه‌اندازی Cart/Checkout",
                    warning=True,
                )
        else:
            self._health_wp.set_status(
                False,
                cfg.get("wc_host", "—"),
                "نیاز به اتصال ووکامرس",
                warning=not woo.get("configured"),
            )

        # ── KPI cards ────────────────────────────────
        self._card_sql_products.update_card(
            _fmt_num(sql.get("articles", "—")),
            f"موجودی کل: {_fmt_num(sql.get('total_stock', 0))}",
        )
        sel = sql.get("selected_groups", cfg.get("selected_groups", 0))
        filtered = sql.get("filtered_articles", "—")
        self._card_sync_scope.update_card(
            _fmt_num(sel),
            f"کالا در دامنه انتخاب: {_fmt_num(filtered)}",
        )
        self._card_wc_products.update_card(_fmt_num(woo.get("total_products", "—")))
        self._card_customers.update_card(_fmt_num(woo.get("total_customers", "—")))

        sales = woo.get("sales", {}) if wc_ok else {}
        self._card_orders.update_card(_fmt_num(sales.get("total_orders", "—")))
        self._card_revenue.update_card(_fmt_money(sales.get("net_revenue", sales.get("total_sales"))))

        # ── Insight panel ────────────────────────────
        self._refresh_settings_summary(cfg, woo)
        self._insight_erp.setText(
            f"<b>ERP ({cfg.get('erp_provider', 'dejavu')})</b><br>"
            f"گروه اصلی: {_fmt_num(sql.get('main_groups', '—'))} | "
            f"زیرگروه: {_fmt_num(sql.get('sub_groups', '—'))}<br>"
            f"لیست قیمت فعال: #{cfg.get('price_list', 1)}"
        )
        version_line = (
            f"ارز: {woo.get('currency') or '—'}" if woo.get("platform") == "prestashop"
            else f"نسخه WC: {woo.get('wc_version', '—')}"
        )
        self._insight_wc.setText(
            f"<b>فروشگاه</b><br>"
            f"محصولات: {_fmt_num(woo.get('total_products', '—'))} | "
            f"مشتریان: {_fmt_num(woo.get('total_customers', '—'))}<br>"
            f"{version_line}"
        )
        sync_ready = sql.get("ok") and wc_ok and sel > 0 and map_count > 0
        if sync_ready:
            sync_msg = "آماده همگام‌سازی — ERP و ووکامرس متصل، گروه‌ها انتخاب و تطبیق ثبت شده است."
            footer_state = "success"
            footer_msg = "✓ داشبورد به‌روز شد — سیستم برای همگام‌سازی آماده به نظر می‌رسد."
        elif sql.get("ok") and wc_ok and sel > 0 and map_count == 0:
            sync_msg = "اتصال‌ها و گروه‌ها آماده‌اند؛ قبل از همگام‌سازی خودکار، تب «تطبیق» را کامل کنید."
            footer_state = "warning"
            footer_msg = "⚠ نگاشت تطبیق خالی است — قبل از همگام‌سازی خودکار، تب تطبیق را انجام دهید."
        else:
            sync_msg = "برای همگام‌سازی کامل: اتصال SQL/ووکامرس را بررسی و در تب دسته‌بندی گروه انتخاب کنید."
            footer_state = "info"
            footer_msg = f"ℹ آخرین بروزرسانی: {loaded_at}"
        self._insight_sync.setText(f"<b>همگام‌سازی</b><br>{sync_msg}")
        self._set_footer_status(footer_state, footer_msg)

        # ── Tables ─────────────────────────────────
        self._fill_orders_table(woo.get("recent_orders", []))
        self._fill_top_products_table(woo.get("top_products", []))
        self._fill_pending_table(woo.get("pending_orders", []))

        # ── Charts ─────────────────────────────────
        daily_sales = woo.get("daily_sales") or []
        self._revenue_chart.set_data(
            daily_sales, title="📈 روند فروش (۱۴ روز اخیر)",
            value_formatter=lambda v: f"{v/1000:,.0f}K" if v >= 1000 else f"{v:,.0f}",
            colors=["#3B82F6"] * len(daily_sales),
        )

        top_products = woo.get("top_products") or []
        top_items = [
            (str(p.get("name") or p.get("title") or "—"), float(p.get("quantity") or p.get("total") or 0))
            for p in top_products[:6]
            if isinstance(p, dict)
        ]
        self._topprod_chart.set_data(
            top_items, title="🏆 پرفروش‌ترین محصولات (ماه)",
            value_formatter=lambda v: f"{v:,.0f}",
            colors=["#8B5CF6"] * len(top_items),
        )

        link_health = data.get("link_health")
        if link_health:
            product_map_count = len(load_product_woo_map() or {})
            health_items = [
                ("لینک‌شده", float(product_map_count)),
                ("لینک‌نشده", float(link_health.get("products", 0))),
            ]
            self._health_chart.set_data(
                health_items, title="🔗 سلامت لینک محصولات",
                value_formatter=lambda v: f"{v:,.0f}",
                colors=["#22C55E", "#EF4444"],
            )
        else:
            self._health_chart.set_data([], title="🔗 سلامت لینک محصولات")

    def _refresh_settings_summary(self, cfg, woo):
        full_config = load_secure_config(None) or {}

        # ۱) نوع محصولات — تا وقتی سوییچ سراسری «فقط ساده / دارای متغیر»
        # ساخته بشه، بر اساس همون تنظیم (PRODUCT_MODE) اگه موجود باشه نشون
        # می‌ده، وگرنه پیش‌فرض فعلی برنامه رو می‌گه.
        product_mode = str(full_config.get("PRODUCT_MODE", "")).strip()
        if product_mode == "simple_only":
            mode_text = "فقط محصولات ساده"
        else:
            mode_text = "دارای ویژگی و متغیر"
        self._summary_lines["product_mode"].setText(f"📦 نوع محصولات:  {mode_text}")

        # ۲) همگام‌سازی خودکار
        if full_config.get("AUTO_ENABLED"):
            interval = str(full_config.get("AUTO_INTERVAL", "۴ ساعت"))
            self._summary_lines["auto_sync"].setText(f"⚡ همگام‌سازی خودکار:  فعال (هر {interval})")
        else:
            self._summary_lines["auto_sync"].setText("⚡ همگام‌سازی خودکار:  غیرفعال")

        # ۳) اعتبار لایسنس
        license_text = "نامشخص"
        try:
            from sync_app.core.tabs.tab_license import license_file_path
            import json as _json
            path = license_file_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    raw = _json.load(f)
                remote_cache = raw.get("remote_cache") or {}
                expiry = remote_cache.get("license_expires")
                if expiry:
                    license_text = f"تا تاریخ {expiry}"
        except Exception:
            pass
        self._summary_lines["license"].setText(f"🔐 اعتبار لایسنس:  {license_text}")

        # ۴) لیست قیمت انتخابی
        price_list_num = full_config.get("PRICE_LIST_INDEX", 0)
        try:
            price_list_num = int(price_list_num) + 1
        except Exception:
            price_list_num = 1
        self._summary_lines["price_list"].setText(f"💰 لیست قیمت انتخابی:  شماره {_fmt_num(price_list_num)}")

        # ۵) قیمت ویژه
        sale_enabled = bool(full_config.get("SALE_PRICE_LIST_ENABLED"))
        sale_text = "دارد" if sale_enabled else "ندارد"
        self._summary_lines["sale_price"].setText(f"🏷️ قیمت ویژه:  {sale_text}")

        # ۶) واحد پول سایت — از خودِ داده‌ی همین بارگذاری (بدون کوئری اضافه)
        CURRENCY_FA = {
            "IRR": "ریال ایران", "IRT": "تومان ایران", "USD": "دلار آمریکا",
            "EUR": "یورو", "AED": "درهم امارات", "TRY": "لیر ترکیه", "GBP": "پوند انگلیس",
        }
        currency_code = str(woo.get("currency") or "").strip().upper()
        currency_text = CURRENCY_FA.get(currency_code, currency_code or "نامشخص")
        self._summary_lines["currency"].setText(f"💱 واحد پول سایت:  {currency_text}")

    def showEvent(self, event):
        self._apply_dashboard_theme()
        super().showEvent(event)

    def _fill_orders_table(self, orders):
        table = self._orders_table["table"]
        table.setRowCount(0)
        if not orders:
            table.setRowCount(1)
            item = QTableWidgetItem("داده‌ای یافت نشد")
            item.setForeground(QColor("#94a3b8"))
            table.setItem(0, 0, item)
            table.setSpan(0, 0, 1, 5)
            return

        for order in orders:
            row = table.rowCount()
            table.insertRow(row)
            billing = order.get("billing", {})
            customer = (
                f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
                or "مهمان"
            )
            status = STATUS_MAP.get(order.get("status", ""), order.get("status", ""))
            status_item = QTableWidgetItem(status)
            status_colors = {
                "تکمیل‌شده": "#16a34a",
                "در حال پردازش": "#2563eb",
                "لغو‌شده": "#dc2626",
            }
            if status in status_colors:
                status_item.setForeground(QColor(status_colors[status]))

            table.setItem(row, 0, QTableWidgetItem(str(order.get("id", ""))))
            table.setItem(row, 1, QTableWidgetItem(customer))
            table.setItem(row, 2, status_item)
            table.setItem(row, 3, QTableWidgetItem(_fmt_money(order.get("total", "—"))))
            table.setItem(row, 4, QTableWidgetItem((order.get("date_created") or "")[:10]))

    def _fill_top_products_table(self, products):
        table = self._top_table["table"]
        table.setRowCount(0)
        if not products:
            table.setRowCount(1)
            empty = QTableWidgetItem("—")
            empty.setForeground(QColor("#94a3b8"))
            table.setItem(0, 0, empty)
            table.setSpan(0, 0, 1, 3)
            return
        for p in products:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(p.get("name", "—")))
            table.setItem(row, 1, QTableWidgetItem(str(p.get("quantity", "—"))))
            table.setItem(row, 2, QTableWidgetItem(_fmt_money(p.get("total", "—"))))

    def _fill_pending_table(self, orders):
        table = self._pending_table["table"]
        table.setRowCount(0)
        if not orders:
            table.setRowCount(1)
            empty = QTableWidgetItem("سفارشی در پردازش نیست")
            empty.setForeground(QColor("#94a3b8"))
            table.setItem(0, 0, empty)
            table.setSpan(0, 0, 1, 3)
            return
        for order in orders:
            row = table.rowCount()
            table.insertRow(row)
            billing = order.get("billing", {})
            customer = (
                f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip()
                or "مهمان"
            )
            table.setItem(row, 0, QTableWidgetItem(str(order.get("id", ""))))
            table.setItem(row, 1, QTableWidgetItem(customer))
            table.setItem(row, 2, QTableWidgetItem(_fmt_money(order.get("total", "—"))))
