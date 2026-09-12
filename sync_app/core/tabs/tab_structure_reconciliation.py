"""تبِ «تطبیقِ ساختاری» — برایِ وقتی ساختارِ یک محصول رویِ سایت با ساختارش
در ERP یکی نیست. دقیقاً هم‌الگویِ تبِ «تطبیق»: دو لیستِ قابلِ‌جستجو
(سایت در راست، ERP در چپ)، یک آیتم از هر طرف انتخاب می‌کنید و دکمه‌ی
«🔗 تطبیق» وسط رو می‌زنید.

۱) سایت محصولِ متغیر داره (چند واریانت)، ولی در ERP هر واریانت یک کالایِ
   سادهٔ مستقل تعریف شده — لیستِ راست واریانت‌هایِ سایت (با جستجویِ نامِ
   محصول)، لیستِ چپ SKUهایِ سادهٔ ERP.

۲) ERP محصول رو متغیر (با چند زیرواریانت) می‌بینه، ولی رویِ سایت این یک
   محصولِ ساده‌ست — لیستِ راست محصولاتِ سادهٔ سایت (با جستجویِ نام)، لیستِ
   چپ زیرواریانت‌هایِ کدهایِ متغیرِ ERP (با جستجویِ نام/کد)."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.secure_config_loader import load_secure_config

log = logging.getLogger("SyncApp")

_SEARCH_PAGE_SIZE = 20
_COLOR_MATCHED = QColor("#dcfce7")  # هم‌رنگِ «قبلاً تطبیق داده شده» در تبِ تطبیقِ معمولی
_COLOR_RECONCILED = QColor("#dbeafe")  # لینک‌شده از «تطبیق» معمولی (نه تطبیقِ ساختاری)

_LINK_FILTER_ALL = "all"
_LINK_FILTER_LINKED = "linked"
_LINK_FILTER_UNLINKED = "unlinked"

_MATCH_NONE = "none"
_MATCH_STRUCTURAL = "structural"
_MATCH_RECONCILED = "reconciled"


# ----------------------------------------------------------------------
# Loaderهایِ پس‌زمینه — سمتِ سایت
# ----------------------------------------------------------------------
def _search_site_products(cfg, query: str) -> list[dict]:
    """جستجویِ محصولاتِ سایت با نام/کد — شکلِ خروجی هم‌الگویِ WC:
    [{"id", "sku", "name", "type"}, ...]."""
    from sync_app.core.integrations.commerce_provider import is_prestashop

    query = str(query or "").strip()
    if is_prestashop(cfg):
        from sync_app.core.ps_sync_helper import ps_rest_request, _response_json, _unwrap_list

        params = {"display": "full", "limit": f"0,{_SEARCH_PAGE_SIZE}"}
        if query:
            params["filter[name]"] = f"%{query}%"
        resp = ps_rest_request(cfg, "GET", "products", params=params, timeout=30)
        data = _response_json(resp, "جستجویِ محصولاتِ سایت")
        rows = _unwrap_list(data, "products")
        out = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            name = row.get("name")
            if isinstance(name, list):
                name = next((n.get("value") for n in name if isinstance(n, dict)), "") or ""
            elif isinstance(name, dict):
                name = name.get("value") or ""
            out.append({
                "id": int(row["id"]), "sku": str(row.get("reference") or ""),
                "name": str(name or ""), "type": "simple",
            })
        return out

    from sync_app.core.wc_sync_helper import apply_network_overrides, build_wcapi

    apply_network_overrides(cfg)
    wcapi = build_wcapi(cfg)
    params = {"per_page": _SEARCH_PAGE_SIZE}
    if query:
        params["search"] = query
    resp = wcapi.get("products", params=params)
    data = resp.json()
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        out.append({
            "id": int(row["id"]), "sku": str(row.get("sku") or ""),
            "name": str(row.get("name") or ""), "type": str(row.get("type") or "simple"),
        })
    return out


def _list_site_variations_for_product(cfg, product: dict) -> list[dict]:
    """واریانت‌هایِ یک محصولِ سایت — شکلِ خروجی: [{"id", "label"}, ...]
    (خالی اگه محصول واریانت نداشته باشه — چه ساده باشه چه متغیر). لیبل
    ترجیحاً نامِ خودِ واریانت (مثلِ «قرمز، L») هست، نه فقط کدش — تا کنارِ
    نامِ محصول قابلِ‌تشخیص باشه."""
    from sync_app.core.integrations.commerce_provider import is_prestashop

    pid = int(product["id"])
    if is_prestashop(cfg):
        from sync_app.core.ps_variation_helper import ps_list_combinations, ps_get_attribute_value

        combos = ps_list_combinations(cfg, pid)
        out = []
        for c in combos:
            if not c.get("id"):
                continue
            names = []
            for value_id in c.get("option_value_ids") or []:
                try:
                    value = ps_get_attribute_value(cfg, int(value_id))
                except Exception:
                    value = None
                if value and value.get("name"):
                    names.append(str(value["name"]))
            variant_name = "، ".join(names)
            reference = str(c.get("reference") or "")
            if variant_name and reference:
                label = f"{variant_name} ({reference})"
            else:
                label = variant_name or reference or f"ترکیب #{c['id']}"
            out.append({"id": int(c["id"]), "label": label})
        return out

    from sync_app.core.wc_sync_helper import apply_network_overrides, build_wcapi

    apply_network_overrides(cfg)
    wcapi = build_wcapi(cfg)
    resp = wcapi.get(f"products/{pid}/variations", params={"per_page": 100})
    data = resp.json()
    if not isinstance(data, list):
        return []
    out = []
    for v in data:
        if not isinstance(v, dict) or not v.get("id"):
            continue
        attrs = "، ".join(str(a.get("option") or "") for a in (v.get("attributes") or []) if a.get("option"))
        sku = str(v.get("sku") or "")
        if attrs and sku:
            label = f"{attrs} ({sku})"
        else:
            label = attrs or sku or f"واریانت #{v['id']}"
        out.append({"id": int(v["id"]), "label": label})
    return out


class _SiteProductSearchLoader(QThread):
    """جستجویِ محصولاتِ سادهٔ سایت — برایِ حالتِ «ERP متغیر / سایت ساده»."""

    done = pyqtSignal(list, str)  # [(id, label, sku), ...], error

    def __init__(self, cfg, query: str):
        super().__init__()
        self.cfg = cfg
        self.query = query

    def run(self):
        try:
            products = _search_site_products(self.cfg, self.query)
            out = [
                (p["id"], f"{p['name']} — {p['sku'] or 'بدونِ SKU'} (#{p['id']})", p["sku"])
                for p in products
            ]
            self.done.emit(out, "")
        except Exception as exc:
            self.done.emit([], str(exc))


class _SiteVariationSearchLoader(QThread):
    """جستجویِ محصولات با نام و بازکردنِ واریانت‌هایِ همه‌یِ نتایج — برایِ
    حالتِ «سایت متغیر / ERP ساده». هر ردیفِ خروجی یک واریانتِ مشخصه."""

    done = pyqtSignal(list, str)  # [(parent_id, variation_id, label), ...], error

    def __init__(self, cfg, query: str):
        super().__init__()
        self.cfg = cfg
        self.query = query

    def run(self):
        try:
            products = _search_site_products(self.cfg, self.query)
            out = []
            for p in products:
                variations = _list_site_variations_for_product(self.cfg, p)
                for v in variations:
                    label = f"{p['name']} — {v['label']} (#محصول {p['id']} / #واریانت {v['id']})"
                    out.append((p["id"], v["id"], label))
            self.done.emit(out, "")
        except Exception as exc:
            self.done.emit([], str(exc))


# ----------------------------------------------------------------------
# Loaderهایِ پس‌زمینه — سمتِ ERP
# ----------------------------------------------------------------------
class _ErpSimpleSkuLoader(QThread):
    """لیستِ SKUهایِ سادهٔ ERP (در گروه‌هایِ انتخاب‌شده) با فیلترِ نام/کد —
    برایِ حالتِ «سایت متغیر / ERP ساده»."""

    done = pyqtSignal(list, str)  # [(sku, label), ...], error

    def __init__(self, cfg, query: str):
        super().__init__()
        self.cfg = cfg
        self.query = query

    def run(self):
        try:
            from sync_app.core.sql_connection_helper import open_sql_connection

            groups = [str(g).strip() for g in (self.cfg.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]
            conn, _, _ = open_sql_connection(self.cfg, timeout=10)
            try:
                cursor = conn.cursor()
                where_bits = ["LEN(A_Code) >= 4"]
                params: list = []
                if groups:
                    where_bits.append("(" + " OR ".join("A_Code LIKE ?" for _ in groups) + ")")
                    params.extend(f"{g}%" for g in groups)
                needle = str(self.query or "").strip()
                if needle:
                    where_bits.append("(A_Code LIKE ? OR A_Name LIKE ?)")
                    params.extend([f"%{needle}%", f"%{needle}%"])
                sql = f"SELECT TOP 200 A_Code, A_Name FROM Article WHERE {' AND '.join(where_bits)}"
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                cursor.close()
            finally:
                conn.close()
            out = [(str(r[0]).strip(), f"{str(r[0]).strip()} — {str(r[1] or '').strip()}") for r in rows]
            self.done.emit(out, "")
        except Exception as exc:
            self.done.emit([], str(exc))


class _ErpVariantSkuLoader(QThread):
    """لیستِ زیرواریانت‌هایِ کدهایِ متغیرِ ERP که با نام/کد جستجو تطبیق
    دارن — برایِ حالتِ «ERP متغیر / سایت ساده». هر ردیفِ خروجی یک
    زیرواریانتِ مشخصه (نه خودِ کدِ والد)."""

    done = pyqtSignal(list, str)  # [(parent_sku, variant_sku, label), ...], error

    def __init__(self, cfg, query: str):
        super().__init__()
        self.cfg = cfg
        self.query = query

    def run(self):
        try:
            from sync_app.core.sql_connection_helper import open_sql_connection
            from sync_app.core.variation_rules import product_is_variable
            from sync_app.core.scripts.update_variations import fetch_variations_from_db, _fetch_attribute_labels
            from sync_app.core.category_price_list import resolve_article_price_column

            groups = [str(g).strip() for g in (self.cfg.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]
            conn, _, _ = open_sql_connection(self.cfg, timeout=10)
            try:
                cursor = conn.cursor()
                where_bits = ["LEN(A_Code) >= 4"]
                params: list = []
                if groups:
                    where_bits.append("(" + " OR ".join("A_Code LIKE ?" for _ in groups) + ")")
                    params.extend(f"{g}%" for g in groups)
                needle = str(self.query or "").strip()
                if needle:
                    where_bits.append("(A_Code LIKE ? OR A_Name LIKE ?)")
                    params.extend([f"%{needle}%", f"%{needle}%"])
                sql = f"SELECT TOP 30 A_Code, A_Name FROM Article WHERE {' AND '.join(where_bits)}"
                cursor.execute(sql, params)
                candidates = cursor.fetchall()

                out = []
                size_label, color_label, dim3_label = _fetch_attribute_labels(conn)
                for a_code, a_name in candidates:
                    a_code = str(a_code).strip()
                    if not product_is_variable(cursor, a_code):
                        continue
                    price_col = resolve_article_price_column(a_code, "", self.cfg)
                    cursor.execute(f"SELECT TOP 1 {price_col} FROM Article WHERE A_Code = ?", (a_code,))
                    price_row = cursor.fetchone()
                    raw_price = float(price_row[0] or 0) if price_row else 0.0
                    variations, _attr_map = fetch_variations_from_db(
                        conn, a_code, raw_price, size_label, color_label, dim3_label, config=self.cfg,
                    )
                    for v in variations or []:
                        v_sku = str(v.get("sku") or "").strip()
                        if not v_sku:
                            continue
                        attrs = "، ".join(
                            str(a.get("option") or "") for a in (v.get("attributes") or []) if a.get("option")
                        )
                        label = f"{a_name} ({a_code}) — {attrs or v_sku}"
                        out.append((a_code, v_sku, label))
                cursor.close()
            finally:
                conn.close()
            self.done.emit(out, "")
        except Exception as exc:
            self.done.emit([], str(exc))


class StructureReconciliationTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self._loaders: list[QThread] = []
        self._syncing_selection = False

        from sync_app.core.integrations.erp_provider import erp_provider_label

        self.erp_label = erp_provider_label(self.config)

        self.init_ui()
        self._refresh_sv_table()
        self._refresh_fs_table()

    # ------------------------------------------------------------------
    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        sub_tabs = QTabWidget()
        sub_tabs.setLayoutDirection(Qt.RightToLeft)
        # پدینگِ سراسریِ QTabBar::tab برایِ لیبل‌هایِ ایموجی+فارسیِ این دو
        # زیرتب کافی نیست و متن نصفه دیده می‌شه — همون مشکلی که برایِ
        # زیرتب‌هایِ «همگام‌سازی»/«دستیار هوشمند» با همین objectName رفع شد.
        sub_tabs.tabBar().setObjectName("hubSubTabBar")
        sub_tabs.addTab(self._build_site_variation_section(), f"🧩 سایت متغیر / {self.erp_label} ساده")
        sub_tabs.addTab(self._build_force_simple_section(), f"📦 {self.erp_label} متغیر / سایت ساده")
        root.addWidget(sub_tabs)

    def _keep_loader(self, loader: QThread):
        self._loaders.append(loader)
        loader.finished.connect(lambda l=loader: self._loaders.remove(l) if l in self._loaders else None)

    def _build_link_filter_combo(self, on_change) -> QComboBox:
        """کمبویِ «همه/فقط لینک‌شده/فقط لینک‌نشده» — بالایِ هر دو لیستِ
        یک بخش، تا نتیجه‌هایِ قبلاً‌تطبیق‌داده‌شده از تطبیق‌نشده‌ها جدا
        دیده بشن (وگرنه با زیاد شدنِ کالاها همه قاطی به نظر می‌رسن)."""
        combo = QComboBox()
        combo.setLayoutDirection(Qt.RightToLeft)
        combo.addItem("همه", _LINK_FILTER_ALL)
        combo.addItem("✅ فقط لینک‌شده", _LINK_FILTER_LINKED)
        combo.addItem("⭕ فقط لینک‌نشده", _LINK_FILTER_UNLINKED)
        combo.setMinimumWidth(140)
        combo.currentIndexChanged.connect(on_change)
        return combo

    def _populate_list_with_matches(self, list_widget: QListWidget, entries: list, filter_state: str) -> int:
        """entries: [(text, data, state, tooltip: str), ...] — state یکی از
        _MATCH_NONE/_MATCH_STRUCTURAL/_MATCH_RECONCILED. رندرِ لیست با توجه
        به فیلترِ لینک‌شده/لینک‌نشده (STRUCTURAL و RECONCILED هر دو «لینک‌شده»
        حساب می‌شن). خروجی: تعدادِ نمایش‌داده‌شده."""
        list_widget.clear()
        shown = 0
        for text, data, state, tooltip in entries:
            linked = state != _MATCH_NONE
            if filter_state == _LINK_FILTER_LINKED and not linked:
                continue
            if filter_state == _LINK_FILTER_UNLINKED and linked:
                continue
            if state == _MATCH_STRUCTURAL:
                item = QListWidgetItem(f"✅ {text}")
                item.setBackground(_COLOR_MATCHED)
            elif state == _MATCH_RECONCILED:
                item = QListWidgetItem(f"🔗 {text}")
                item.setBackground(_COLOR_RECONCILED)
            else:
                item = QListWidgetItem(text)
            item.setData(Qt.UserRole, data)
            if tooltip:
                item.setToolTip(tooltip)
            list_widget.addItem(item)
            shown += 1
        return shown

    def _select_item_by_data(self, list_widget: QListWidget, matches_fn) -> bool:
        """اولین آیتمِ لیست که matches_fn رویِ دیتاش True برگردونه رو
        انتخاب/اسکرول می‌کنه — برایِ نشون‌دادنِ نظیرِ لینک‌شده در طرفِ دیگه."""
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            try:
                if matches_fn(item.data(Qt.UserRole)):
                    list_widget.setCurrentItem(item)
                    list_widget.scrollToItem(item)
                    return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------------
    # حالتِ ۱: سایت متغیر داره، ERP ساده می‌بینه
    # ------------------------------------------------------------------
    def _build_site_variation_section(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        panel = QWidget()
        scroll.setWidget(panel)
        v = QVBoxLayout(panel)
        v.setSpacing(6)

        hint = QLabel(
            f"سایت این محصول رو متغیر نشون می‌ده، ولی هر واریانت در {self.erp_label} یک کالایِ سادهٔ جداست — "
            f"از راست واریانتِ سایت، از چپ SKUِ سادهٔ {self.erp_label} رو انتخاب و «🔗 تطبیق» را بزنید.\n"
            "⚠️ فقط قیمت/موجودی منتقل می‌شه؛ تصویر/دسته‌بندی/برند را رویِ محصولِ اصلیِ سایت مدیریت کنید."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:11px;")
        v.addWidget(hint)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("نمایش:"))
        self.sv_link_filter = self._build_link_filter_combo(self._on_sv_link_filter_changed)
        filter_row.addWidget(self.sv_link_filter)
        filter_row.addStretch(1)
        v.addLayout(filter_row)

        columns = QHBoxLayout()

        # راست: واریانت‌هایِ سایت (RTL → اولین ویجتِ افزوده‌شده راست دیده می‌شه)
        site_col = QVBoxLayout()
        site_search_row = QHBoxLayout()
        self.sv_site_search = QLineEdit()
        self.sv_site_search.setPlaceholderText("جستجویِ نامِ محصولِ سایت...")
        self.sv_site_search.returnPressed.connect(self._sv_search_site)
        site_search_row.addWidget(self.sv_site_search, 1)
        sv_search_btn = QPushButton("🔍")
        sv_search_btn.clicked.connect(self._sv_search_site)
        site_search_row.addWidget(sv_search_btn)
        site_col.addLayout(site_search_row)
        site_col.addWidget(QLabel("واریانت‌هایِ سایت:"))
        self.sv_site_list = QListWidget()
        self.sv_site_list.setLayoutDirection(Qt.RightToLeft)
        self.sv_site_list.setMinimumHeight(240)
        site_col.addWidget(self.sv_site_list, 1)
        columns.addLayout(site_col, 1)

        # وسط: دکمه‌ی تطبیق
        mid_col = QVBoxLayout()
        mid_col.addStretch(1)
        self.sv_match_btn = QPushButton("🔗 تطبیق")
        self.sv_match_btn.clicked.connect(self._sv_save)
        mid_col.addWidget(self.sv_match_btn)
        mid_col.addStretch(1)
        columns.addLayout(mid_col)

        # چپ: SKUهایِ سادهٔ ERP
        erp_col = QVBoxLayout()
        erp_search_row = QHBoxLayout()
        self.sv_erp_search = QLineEdit()
        self.sv_erp_search.setPlaceholderText(f"جستجویِ کد/نامِ کالایِ {self.erp_label}...")
        self.sv_erp_search.returnPressed.connect(self._sv_search_erp)
        erp_search_row.addWidget(self.sv_erp_search, 1)
        sv_erp_btn = QPushButton("🔍")
        sv_erp_btn.clicked.connect(self._sv_search_erp)
        erp_search_row.addWidget(sv_erp_btn)
        erp_col.addLayout(erp_search_row)
        erp_col.addWidget(QLabel(f"کالاهایِ سادهٔ {self.erp_label}:"))
        self.sv_erp_list = QListWidget()
        self.sv_erp_list.setLayoutDirection(Qt.RightToLeft)
        self.sv_erp_list.setMinimumHeight(240)
        erp_col.addWidget(self.sv_erp_list, 1)
        columns.addLayout(erp_col, 1)

        v.addLayout(columns)

        self.sv_status_label = QLabel("")
        self.sv_status_label.setStyleSheet("color:#64748b; font-size:12px;")
        v.addWidget(self.sv_status_label)

        v.addWidget(QLabel("تطبیق‌هایِ ثبت‌شده:"))
        self.sv_table = QTableWidget(0, 3)
        self.sv_table.setLayoutDirection(Qt.RightToLeft)
        self.sv_table.setHorizontalHeaderLabels(["نام کالا و متغیرِ سایت", f"کالای سادهٔ {self.erp_label}", ""])
        self.sv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.sv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.sv_table.verticalHeader().setVisible(False)
        self.sv_table.setMinimumHeight(140)
        self.sv_table.setMaximumHeight(220)
        v.addWidget(self.sv_table)

        self.sv_site_list.itemSelectionChanged.connect(self._on_sv_site_selection_changed)
        self.sv_erp_list.itemSelectionChanged.connect(self._on_sv_erp_selection_changed)

        return scroll

    def _reload_config(self):
        """کانفیگ رو تازه از دیسک می‌خونه — قبل از هر عملیاتِ شبکه/دیتابیس.
        وگرنه اگه کاربر تویِ تبِ تنظیمات دیتابیس/سایت رو عوض کنه، این تب
        (که کانفیگش فقط یک‌بار در __init__ لود شده بود) همچنان با تنظیماتِ
        قدیمی به دیتابیس/سایتِ قبلی وصل می‌شد."""
        self.config = load_secure_config(None) or {}
        from sync_app.core.integrations.erp_provider import erp_provider_label

        self.erp_label = erp_provider_label(self.config)

    def _sv_search_site(self):
        self._reload_config()
        self.sv_status_label.setText("⏳ در حالِ جستجویِ محصولاتِ سایت...")
        loader = _SiteVariationSearchLoader(self.config, self.sv_site_search.text())
        self._keep_loader(loader)
        loader.done.connect(self._on_sv_site_results)
        loader.start()

    def _on_sv_site_results(self, options, error):
        if error:
            self.sv_status_label.setText(f"⚠️ جستجویِ سایت ناموفق بود: {error}")
            return
        from sync_app.core.structure_mismatch_override import find_erp_sku_for_site_variation

        matched_count = 0
        entries = []
        for parent_id, variation_id, label in options:
            matched_sku = find_erp_sku_for_site_variation(parent_id, variation_id)
            state = _MATCH_STRUCTURAL if matched_sku else _MATCH_NONE
            if matched_sku:
                matched_count += 1
            tooltip = f"قبلاً به SKUِ «{matched_sku}» تطبیق داده شده" if matched_sku else ""
            entries.append((label, (parent_id, variation_id, label), state, tooltip))
        self._sv_site_entries = entries
        self._render_sv_site_list()
        self.sv_status_label.setText(
            f"✅ {len(options)} واریانتِ سایت پیدا شد — {matched_count} تا قبلاً تطبیق داده شده."
        )

    def _render_sv_site_list(self):
        filter_state = self.sv_link_filter.currentData()
        self._populate_list_with_matches(self.sv_site_list, getattr(self, "_sv_site_entries", []), filter_state)

    def _sv_search_erp(self):
        self._reload_config()
        self.sv_status_label.setText(f"⏳ در حالِ جستجویِ کالاهایِ {self.erp_label}...")
        loader = _ErpSimpleSkuLoader(self.config, self.sv_erp_search.text())
        self._keep_loader(loader)
        loader.done.connect(self._on_sv_erp_results)
        loader.start()

    def _on_sv_erp_results(self, options, error):
        if error:
            self.sv_status_label.setText(f"⚠️ جستجویِ {self.erp_label} ناموفق بود: {error}")
            return
        from sync_app.core.structure_mismatch_override import get_site_variation_target
        from sync_app.core.product_woo_map_helper import load_product_woo_map

        # کالاهایِ سادهٔ ERP که از قبل با «تطبیق» معمولی (نه این ابزار) به یک
        # محصولِ سایت لینک شدن — اینا مشکلی ندارن، محصولِ ساده‌ی معمولی‌اند و
        # نیازی به تطبیقِ ساختاری ندارن؛ نباید کنارِ کالاهایِ واقعاً بی‌لینک
        # تویِ «فقط لینک‌نشده» بیفتن.
        product_map = load_product_woo_map()

        structural_count = 0
        reconciled_count = 0
        entries = []
        for sku, label in options:
            if get_site_variation_target(sku) is not None:
                state = _MATCH_STRUCTURAL
                tooltip = "قبلاً تطبیق داده شده"
                structural_count += 1
            elif product_map.get(sku):
                state = _MATCH_RECONCILED
                tooltip = "قبلاً از «تطبیق» معمولی به یک محصولِ سایت لینک شده — نیازی به تطبیقِ ساختاری نداره"
                reconciled_count += 1
            else:
                state = _MATCH_NONE
                tooltip = ""
            entries.append((label, sku, state, tooltip))
        self._sv_erp_entries = entries
        self._render_sv_erp_list()
        self.sv_status_label.setText(
            f"✅ {len(options)} کالایِ {self.erp_label} پیدا شد — {structural_count} تطبیقِ ساختاری، "
            f"{reconciled_count} قبلاً لینکِ عادی."
        )

    def _render_sv_erp_list(self):
        filter_state = self.sv_link_filter.currentData()
        self._populate_list_with_matches(self.sv_erp_list, getattr(self, "_sv_erp_entries", []), filter_state)

    def _on_sv_link_filter_changed(self):
        self._render_sv_site_list()
        self._render_sv_erp_list()

    def _on_sv_site_selection_changed(self):
        """اگه واریانتِ انتخاب‌شده قبلاً تطبیق داده شده، SKUِ نظیرش رو هم در
        لیستِ چپ فعال/انتخاب می‌کنه — تا معلوم بشه به کدوم کالا لینکه."""
        if self._syncing_selection:
            return
        items = self.sv_site_list.selectedItems()
        if not items:
            return
        parent_id, variation_id, _label = items[0].data(Qt.UserRole)
        from sync_app.core.structure_mismatch_override import find_erp_sku_for_site_variation

        matched_sku = find_erp_sku_for_site_variation(parent_id, variation_id)
        if not matched_sku:
            return
        self._syncing_selection = True
        try:
            self._select_item_by_data(self.sv_erp_list, lambda data: data == matched_sku)
        finally:
            self._syncing_selection = False

    def _on_sv_erp_selection_changed(self):
        if self._syncing_selection:
            return
        items = self.sv_erp_list.selectedItems()
        if not items:
            return
        sku = items[0].data(Qt.UserRole)
        from sync_app.core.structure_mismatch_override import get_site_variation_target

        target = get_site_variation_target(sku)
        if not target:
            return
        self._syncing_selection = True
        try:
            self._select_item_by_data(
                self.sv_site_list,
                lambda data: data[0] == target["parent_product_id"] and data[1] == target["variation_id"],
            )
        finally:
            self._syncing_selection = False

    def _sv_save(self):
        site_selected = self.sv_site_list.selectedItems()
        erp_selected = self.sv_erp_list.selectedItems()
        if not site_selected or not erp_selected:
            QMessageBox.warning(self, "توجه", f"یک واریانتِ سایت و یک SKUِ {self.erp_label} را از لیست‌ها انتخاب کنید.")
            return
        site_item = site_selected[0]
        erp_item = erp_selected[0]
        parent_id, variation_id, label = site_item.data(Qt.UserRole)
        sku = erp_item.data(Qt.UserRole)
        erp_label = erp_item.text()

        from sync_app.core.structure_mismatch_override import set_site_variation_target
        from sync_app.core.product_woo_map_helper import load_product_woo_map, save_product_woo_map
        from sync_app.core.product_woo_map_meta import register_product_link

        set_site_variation_target(sku, parent_id, variation_id, label=label, erp_label=erp_label)
        # همین SKU رو در product_woo_map هم به محصولِ والدِ سایت وصل می‌کنیم —
        # نه برایِ اینکه سینکِ عادی ازش استفاده کنه (سینک برایِ این SKU زودتر
        # از این طریق رد می‌شه: get_site_variation_target)، بلکه فقط برایِ
        # اینکه تبِ «محصولات» این SKU رو «لینک‌شده» نشون بده، نه «لینک‌نشده» —
        # وگرنه کاربر گمون می‌کنه هنوز تطبیق نشده.
        product_map = load_product_woo_map()
        product_map[sku] = int(parent_id)
        save_product_woo_map(product_map)
        register_product_link(sku, int(parent_id), wc_label=label, manual=True)

        self._refresh_sv_table()
        QMessageBox.information(self, "انجام شد", f"SKUِ «{sku}» به واریانتِ سایت وصل شد.")

    def _refresh_sv_table(self):
        from sync_app.core.structure_mismatch_override import list_site_variation_targets

        table = list_site_variation_targets()
        self.sv_table.setRowCount(0)
        for sku, entry in table.items():
            row = self.sv_table.rowCount()
            self.sv_table.insertRow(row)
            site_label = entry.get("label") or f"محصول #{entry.get('parent_product_id')} / واریانت #{entry.get('variation_id')}"
            self.sv_table.setItem(row, 0, QTableWidgetItem(str(site_label)))
            erp_display = entry.get("erp_label") or sku
            self.sv_table.setItem(row, 1, QTableWidgetItem(str(erp_display)))
            del_btn = QPushButton("🗑 حذف")
            del_btn.clicked.connect(lambda _checked=False, s=sku: self._sv_delete(s))
            self.sv_table.setCellWidget(row, 2, del_btn)

    def _sv_delete(self, sku: str):
        from sync_app.core.structure_mismatch_override import clear_site_variation_target
        from sync_app.core.product_woo_map_helper import load_product_woo_map, save_product_woo_map
        from sync_app.core.product_woo_map_meta import clear_product_link_meta

        clear_site_variation_target(sku)
        product_map = load_product_woo_map()
        if sku in product_map:
            product_map.pop(sku, None)
            save_product_woo_map(product_map)
        clear_product_link_meta(sku)
        self._refresh_sv_table()

    # ------------------------------------------------------------------
    # حالتِ ۲: ERP متغیر می‌بینه، سایت ساده داره
    # ------------------------------------------------------------------
    def _build_force_simple_section(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        panel = QWidget()
        scroll.setWidget(panel)
        v = QVBoxLayout(panel)
        v.setSpacing(6)

        hint = QLabel(
            f"{self.erp_label} این کد رو متغیر می‌بینه، ولی رویِ سایت یک محصولِ ساده‌ست — از راست محصولِ "
            f"سایت، از چپ زیرواریانتِ {self.erp_label}ای که منبعِ قیمت/موجودی باشه رو انتخاب و «🔗 تطبیق» را بزنید.\n"
            "✅ بعد از تطبیق، این کد کاملاً مثلِ یک محصولِ سادهٔ معمولی سینک می‌شه (قیمت/موجودی/تصویر/دسته‌بندی)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:11px;")
        v.addWidget(hint)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("نمایش:"))
        self.fs_link_filter = self._build_link_filter_combo(self._on_fs_link_filter_changed)
        filter_row.addWidget(self.fs_link_filter)
        filter_row.addStretch(1)
        v.addLayout(filter_row)

        columns = QHBoxLayout()

        # راست: محصولاتِ سادهٔ سایت
        site_col = QVBoxLayout()
        site_search_row = QHBoxLayout()
        self.fs_site_search = QLineEdit()
        self.fs_site_search.setPlaceholderText("جستجویِ نامِ محصولِ سایت...")
        self.fs_site_search.returnPressed.connect(self._fs_search_site)
        site_search_row.addWidget(self.fs_site_search, 1)
        fs_search_btn = QPushButton("🔍")
        fs_search_btn.clicked.connect(self._fs_search_site)
        site_search_row.addWidget(fs_search_btn)
        site_col.addLayout(site_search_row)
        site_col.addWidget(QLabel("محصولاتِ سایت:"))
        self.fs_site_list = QListWidget()
        self.fs_site_list.setLayoutDirection(Qt.RightToLeft)
        self.fs_site_list.setMinimumHeight(240)
        site_col.addWidget(self.fs_site_list, 1)
        columns.addLayout(site_col, 1)

        # وسط: دکمه‌ی تطبیق
        mid_col = QVBoxLayout()
        mid_col.addStretch(1)
        self.fs_match_btn = QPushButton("🔗 تطبیق")
        self.fs_match_btn.clicked.connect(self._fs_save)
        mid_col.addWidget(self.fs_match_btn)
        mid_col.addStretch(1)
        columns.addLayout(mid_col)

        # چپ: زیرواریانت‌هایِ ERP
        erp_col = QVBoxLayout()
        erp_search_row = QHBoxLayout()
        self.fs_erp_search = QLineEdit()
        self.fs_erp_search.setPlaceholderText(f"جستجویِ کد/نامِ کالایِ والدِ {self.erp_label}...")
        self.fs_erp_search.returnPressed.connect(self._fs_search_erp)
        erp_search_row.addWidget(self.fs_erp_search, 1)
        fs_erp_btn = QPushButton("🔍")
        fs_erp_btn.clicked.connect(self._fs_search_erp)
        erp_search_row.addWidget(fs_erp_btn)
        erp_col.addLayout(erp_search_row)
        erp_col.addWidget(QLabel(f"زیرواریانت‌هایِ {self.erp_label}:"))
        self.fs_erp_list = QListWidget()
        self.fs_erp_list.setLayoutDirection(Qt.RightToLeft)
        self.fs_erp_list.setMinimumHeight(240)
        erp_col.addWidget(self.fs_erp_list, 1)
        columns.addLayout(erp_col, 1)

        v.addLayout(columns)

        self.fs_status_label = QLabel("")
        self.fs_status_label.setStyleSheet("color:#64748b; font-size:12px;")
        v.addWidget(self.fs_status_label)

        v.addWidget(QLabel("تطبیق‌هایِ ثبت‌شده:"))
        self.fs_table = QTableWidget(0, 3)
        self.fs_table.setLayoutDirection(Qt.RightToLeft)
        self.fs_table.setHorizontalHeaderLabels([f"نام کالا و متغیرِ {self.erp_label}", "کالای سادهٔ سایت", ""])
        self.fs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.fs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.fs_table.verticalHeader().setVisible(False)
        self.fs_table.setMinimumHeight(140)
        self.fs_table.setMaximumHeight(220)
        v.addWidget(self.fs_table)

        self.fs_site_list.itemSelectionChanged.connect(self._on_fs_site_selection_changed)
        self.fs_erp_list.itemSelectionChanged.connect(self._on_fs_erp_selection_changed)

        return scroll

    def _fs_search_site(self):
        self._reload_config()
        self.fs_status_label.setText("⏳ در حالِ جستجویِ محصولاتِ سایت...")
        loader = _SiteProductSearchLoader(self.config, self.fs_site_search.text())
        self._keep_loader(loader)
        loader.done.connect(self._on_fs_site_results)
        loader.start()

    def _on_fs_site_results(self, options, error):
        if error:
            self.fs_status_label.setText(f"⚠️ جستجویِ سایت ناموفق بود: {error}")
            return
        from sync_app.core.structure_mismatch_override import list_force_simple_sources
        from sync_app.core.product_woo_map_helper import load_product_woo_map

        product_map = load_product_woo_map()
        matched_ids = set()
        for parent_sku in list_force_simple_sources():
            mapped_id = product_map.get(parent_sku)
            if mapped_id:
                try:
                    matched_ids.add(int(mapped_id))
                except (TypeError, ValueError):
                    continue

        matched_count = 0
        entries = []
        tooltip = f"این محصول الان منبعِ قیمت/موجودیش از یک کدِ {self.erp_label} تعیین شده"
        for pid, label, sku in options:
            matched = int(pid) in matched_ids
            state = _MATCH_STRUCTURAL if matched else _MATCH_NONE
            if matched:
                matched_count += 1
            entries.append((label, (pid, label, sku), state, tooltip if matched else ""))
        self._fs_site_entries = entries
        self._render_fs_site_list()
        self.fs_status_label.setText(
            f"✅ {len(options)} محصولِ سایت پیدا شد — {matched_count} تا قبلاً تطبیق داده شده."
        )

    def _render_fs_site_list(self):
        filter_state = self.fs_link_filter.currentData()
        self._populate_list_with_matches(self.fs_site_list, getattr(self, "_fs_site_entries", []), filter_state)

    def _fs_search_erp(self):
        self._reload_config()
        self.fs_status_label.setText(f"⏳ در حالِ جستجویِ زیرواریانت‌هایِ {self.erp_label}...")
        loader = _ErpVariantSkuLoader(self.config, self.fs_erp_search.text())
        self._keep_loader(loader)
        loader.done.connect(self._on_fs_erp_results)
        loader.start()

    def _on_fs_erp_results(self, options, error):
        if error:
            self.fs_status_label.setText(f"⚠️ جستجویِ {self.erp_label} ناموفق بود: {error}")
            return
        from sync_app.core.structure_mismatch_override import get_force_simple_source

        matched_count = 0
        entries = []
        for parent_sku, variant_sku, label in options:
            matched = get_force_simple_source(parent_sku) == variant_sku
            state = _MATCH_STRUCTURAL if matched else _MATCH_NONE
            if matched:
                matched_count += 1
            entries.append((label, (parent_sku, variant_sku), state, "این زیرواریانت الان منبعِ فعاله" if matched else ""))
        self._fs_erp_entries = entries
        self._render_fs_erp_list()
        self.fs_status_label.setText(
            f"✅ {len(options)} زیرواریانت پیدا شد — {matched_count} تا قبلاً تطبیق داده شده."
        )

    def _render_fs_erp_list(self):
        filter_state = self.fs_link_filter.currentData()
        self._populate_list_with_matches(self.fs_erp_list, getattr(self, "_fs_erp_entries", []), filter_state)

    def _on_fs_link_filter_changed(self):
        self._render_fs_site_list()
        self._render_fs_erp_list()

    def _on_fs_site_selection_changed(self):
        """اگه محصولِ سایتِ انتخاب‌شده قبلاً منبعِ زیرواریانتی داشته، همون
        زیرواریانت رو در لیستِ چپ فعال/انتخاب می‌کنه."""
        if self._syncing_selection:
            return
        items = self.fs_site_list.selectedItems()
        if not items:
            return
        pid, _label, _sku = items[0].data(Qt.UserRole)
        from sync_app.core.structure_mismatch_override import list_force_simple_sources
        from sync_app.core.product_woo_map_helper import load_product_woo_map

        product_map = load_product_woo_map()
        match = None
        for parent_sku, entry in list_force_simple_sources().items():
            mapped_id = product_map.get(parent_sku)
            try:
                if mapped_id is not None and int(mapped_id) == int(pid):
                    match = (parent_sku, str(entry.get("source_variation_sku") or ""))
                    break
            except (TypeError, ValueError):
                continue
        if not match:
            return
        self._syncing_selection = True
        try:
            self._select_item_by_data(self.fs_erp_list, lambda data: data == match)
        finally:
            self._syncing_selection = False

    def _on_fs_erp_selection_changed(self):
        if self._syncing_selection:
            return
        items = self.fs_erp_list.selectedItems()
        if not items:
            return
        parent_sku, variant_sku = items[0].data(Qt.UserRole)
        from sync_app.core.structure_mismatch_override import get_force_simple_source

        if get_force_simple_source(parent_sku) != variant_sku:
            return
        from sync_app.core.product_woo_map_helper import load_product_woo_map

        mapped_id = load_product_woo_map().get(parent_sku)
        if mapped_id is None:
            return
        try:
            mapped_id = int(mapped_id)
        except (TypeError, ValueError):
            return
        self._syncing_selection = True
        try:
            self._select_item_by_data(self.fs_site_list, lambda data: int(data[0]) == mapped_id)
        finally:
            self._syncing_selection = False

    def _fs_save(self):
        site_selected = self.fs_site_list.selectedItems()
        erp_selected = self.fs_erp_list.selectedItems()
        if not site_selected or not erp_selected:
            QMessageBox.warning(self, "توجه", f"یک محصولِ سایت و یک زیرواریانتِ {self.erp_label} را از لیست‌ها انتخاب کنید.")
            return
        site_item = site_selected[0]
        erp_item = erp_selected[0]
        site_id, site_label, _site_sku = site_item.data(Qt.UserRole)
        parent_sku, variant_sku = erp_item.data(Qt.UserRole)
        erp_label = erp_item.text()

        from sync_app.core.structure_mismatch_override import set_force_simple_source
        from sync_app.core.product_woo_map_helper import load_product_woo_map, save_product_woo_map
        from sync_app.core.product_woo_map_meta import register_product_link

        set_force_simple_source(parent_sku, variant_sku, erp_label=erp_label, site_label=site_label)
        # محصولِ سایتِ انتخاب‌شده رو صریح به همین کدِ والدِ ERP وصل می‌کنیم —
        # وگرنه اگه SKUِ رویِ سایت با کدِ ERP یکی نباشه، سینک نمی‌تونه خودش
        # تشخیص بده این همون محصوله (دقیقاً همون مکانیزمِ تبِ «تطبیق» برایِ
        # جفت‌هایِ دستی: product_woo_map + register_product_link(manual=True)).
        product_map = load_product_woo_map()
        product_map[parent_sku] = int(site_id)
        save_product_woo_map(product_map)
        register_product_link(parent_sku, int(site_id), wc_label=site_label, manual=True)

        self._refresh_fs_table()
        QMessageBox.information(
            self, "انجام شد",
            f"محصولِ «{parent_sku}» از این به بعد به‌عنوانِ محصولِ سادهٔ سایت (همین محصولِ انتخاب‌شده) سینک می‌شه.",
        )

    def _refresh_fs_table(self):
        from sync_app.core.structure_mismatch_override import list_force_simple_sources
        from sync_app.core.product_woo_map_meta import get_product_link_meta

        table = list_force_simple_sources()
        self.fs_table.setRowCount(0)
        for sku, entry in table.items():
            row = self.fs_table.rowCount()
            self.fs_table.insertRow(row)
            source_sku = str(entry.get("source_variation_sku") or "")
            erp_display = entry.get("erp_label") or f"{sku} — {source_sku}"
            self.fs_table.setItem(row, 0, QTableWidgetItem(str(erp_display)))
            site_display = entry.get("site_label")
            if not site_display:
                link_meta = get_product_link_meta(sku)
                site_display = (link_meta or {}).get("wc_label") or ""
            self.fs_table.setItem(row, 1, QTableWidgetItem(str(site_display)))
            del_btn = QPushButton("🗑 حذف")
            del_btn.clicked.connect(lambda _checked=False, s=sku: self._fs_delete(s))
            self.fs_table.setCellWidget(row, 2, del_btn)

    def _fs_delete(self, sku: str):
        from sync_app.core.structure_mismatch_override import clear_force_simple_source
        from sync_app.core.product_woo_map_helper import load_product_woo_map, save_product_woo_map
        from sync_app.core.product_woo_map_meta import clear_product_link_meta

        clear_force_simple_source(sku)
        product_map = load_product_woo_map()
        if sku in product_map:
            product_map.pop(sku, None)
            save_product_woo_map(product_map)
        clear_product_link_meta(sku)
        self._refresh_fs_table()

    # ------------------------------------------------------------------
    def ensure_tab_data_loaded(self):
        pass
