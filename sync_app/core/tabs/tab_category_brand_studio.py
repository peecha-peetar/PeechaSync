"""تبِ «دسته‌بندی و برند» — ابزارِ گروهی برایِ الصاقِ دسته‌بندی/برندِ واقعیِ
سایت (نه ERP) به چند محصولِ فیلترشده هم‌زمان: فیلترِ محصولات، انتخابِ
دسته‌بندیِ موجود یا ساختِ دسته‌بندیِ جدید، انتخابِ برندِ موجود یا ساختِ برندِ
جدید، اعمالِ گروهی، و بازگردانیِ محصول به منطقِ خودکارِ (ERP→دسته‌بندی).

این تب رویِ همون مکانیزمِ override دستیِ per-SKU (product_category_override)
که تبِ محصولات از قبل داره سوار می‌شه — فقط نسخه‌ی گروهی/فیلترپذیرِ همون
کاره، به‌همراهِ ساختِ دسته‌بندی/برندِ جدید و مدیریتِ برند (که قبلاً اصلاً
جایی تویِ برنامه نبود)."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from sync_app.core.secure_config_loader import load_secure_config

log = logging.getLogger("SyncApp")


class MultiCheckFilterButton(QToolButton):
    """دکمه‌ای که با کلیک، منویی با چک‌باکسِ چندتایی باز می‌کنه — برایِ
    فیلترهایی که باید بشه هم‌زمان چند مقدار (مثلاً چند دسته‌بندیِ ERP) رو
    با هم انتخاب کرد، نه فقط یکی مثلِ QComboBoxِ معمولی."""

    selectionChanged = pyqtSignal()

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._checkboxes: dict[str, QCheckBox] = {}
        self._labels: dict[str, str] = {}
        self.setPopupMode(QToolButton.InstantPopup)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._menu = QMenu(self)
        self._menu.setLayoutDirection(Qt.RightToLeft)
        self.setMenu(self._menu)
        self._update_text()

    def set_options(self, options: list[tuple[str, str]]):
        """options: [(code, label), ...] — منو رو کامل بازمی‌سازه؛ انتخاب‌هایِ
        قبلی (بر اساسِ code) اگه هنوز تویِ لیستِ جدید باشن حفظ می‌شن."""
        prev_checked = {code for code, cb in self._checkboxes.items() if cb.isChecked()}
        self._menu.clear()
        self._checkboxes = {}
        self._labels = {}
        select_all_action = self._menu.addAction("✅ انتخابِ همه")
        select_all_action.triggered.connect(lambda: self._set_all(True))
        clear_action = self._menu.addAction("◻️ پاک‌کردنِ انتخاب")
        clear_action.triggered.connect(lambda: self._set_all(False))
        self._menu.addSeparator()
        for code, label in options:
            cb = QCheckBox(label)
            cb.setLayoutDirection(Qt.RightToLeft)
            cb.setChecked(code in prev_checked)
            cb.toggled.connect(self._on_toggled)
            action = QWidgetAction(self._menu)
            action.setDefaultWidget(cb)
            self._menu.addAction(action)
            self._checkboxes[code] = cb
            self._labels[code] = label
        self._update_text()

    def _set_all(self, checked: bool):
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        self._update_text()
        self.selectionChanged.emit()

    def _on_toggled(self, _checked=False):
        self._update_text()
        self.selectionChanged.emit()

    def _update_text(self):
        codes = self.selected_codes()
        if not codes:
            self.setText(self._placeholder)
        elif len(codes) == 1:
            code = next(iter(codes))
            self.setText(self._labels.get(code, code))
        else:
            self.setText(f"{len(codes)} موردِ انتخاب‌شده ▾")

    def selected_codes(self) -> set[str]:
        return {code for code, cb in self._checkboxes.items() if cb.isChecked()}


class SiteTaxonomyLoader(QThread):
    """دریافتِ لیستِ زنده‌ی دسته‌بندی‌ها و برندهایِ سایت — تویِ ترد جدا."""

    done = pyqtSignal(list, list, str)  # categories, brands, error

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            from sync_app.core.integrations.commerce_provider import is_prestashop

            if is_prestashop(self.cfg):
                from sync_app.core.ps_sync_helper import ps_list_categories, ps_list_manufacturers

                cats = ps_list_categories(self.cfg, timeout=45)
                brands = ps_list_manufacturers(self.cfg, timeout=45)
            else:
                from sync_app.core.wc_sync_helper import fetch_wc_brands
                from sync_app.core.category_resolver import fetch_wc_slug_map

                cats = list(fetch_wc_slug_map(self.cfg, timeout=45).values())
                brands = fetch_wc_brands(self.cfg, timeout=45)
            self.done.emit(cats, brands, "")
        except Exception as exc:
            self.done.emit([], [], str(exc))


class CategoryBrandStudioTab(QWidget):
    def __init__(self, product_tab_ref=None, category_tab_ref=None):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self.product_tab_ref = product_tab_ref
        self.category_tab_ref = category_tab_ref
        self._categories: list[dict] = []
        self._brands: list[dict] = []
        self._slug_map: dict = {}
        self._id_to_name: dict = {}
        self._brand_id_to_name: dict = {}
        self._erp_code_index: dict = {}
        self._loader = None
        self.init_ui()

    # ------------------------------------------------------------------
    def init_ui(self):
        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label = erp_provider_label(self.config)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        hint = QLabel(
            "دسته‌بندی/برندِ واقعیِ سایت رو به چند محصولِ فیلترشده هم‌زمان الصاق کنید — "
            f"این کار جایگزینِ منطقِ خودکارِ «{erp_label} → دسته‌بندی» می‌شه، مگر با دکمه‌ی "
            "«بازگردانی» دوباره پاک بشه."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        root.addWidget(hint)

        # --- فیلتر ---
        filter_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("جستجو در نام/کدِ محصول...")
        self.search_input.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_input, 2)

        self.erp_category_filter = MultiCheckFilterButton(f"— همه‌ی دسته‌بندی‌هایِ {erp_label} —")
        self.erp_category_filter.selectionChanged.connect(self._apply_filters)
        filter_row.addWidget(self.erp_category_filter, 1)

        self.link_filter_combo = QComboBox()
        self.link_filter_combo.addItem("— همه —", "all")
        self.link_filter_combo.addItem("✅ لینک‌شده به سایت", "linked")
        self.link_filter_combo.addItem("⭕ لینک‌نشده", "unlinked")
        self.link_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.link_filter_combo, 1)

        self.override_filter_combo = QComboBox()
        self.override_filter_combo.addItem("— همه —", "all")
        self.override_filter_combo.addItem("🏷️ با دسته‌بندیِ دستی", "manual")
        self.override_filter_combo.addItem(f"⚙️ فقط خودکار ({erp_label})", "auto")
        self.override_filter_combo.addItem("🚫 بدونِ دسته‌بندیِ سایت", "no_category")
        self.override_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.override_filter_combo, 1)

        self.brand_filter_combo = QComboBox()
        self.brand_filter_combo.addItem("— همه —", "all")
        self.brand_filter_combo.addItem("🚫 بدونِ برند", "no_brand")
        self.brand_filter_combo.addItem("🏢 دارایِ برند", "has_brand")
        self.brand_filter_combo.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.brand_filter_combo, 1)

        self.refresh_products_btn = QPushButton("🔄 بروزرسانیِ لیست")
        self.refresh_products_btn.setToolTip("خواندنِ دوباره‌ی لیستِ محصولات از تبِ «محصولات»")
        self.refresh_products_btn.clicked.connect(self._reload_products)
        filter_row.addWidget(self.refresh_products_btn)

        self.refresh_taxonomy_btn = QPushButton("🔄 دریافتِ دوباره‌یِ دسته‌بندی/برندِ سایت")
        self.refresh_taxonomy_btn.setToolTip(
            "اگه اسمِ دسته‌بندی/برند به‌جایِ نمایش دادن فقط کد نشون می‌ده (مثلاً چون دریافتِ اولیه "
            "ناموفق بوده یا هنوز کامل نشده)، این دکمه رو بزنید تا دوباره از سایت دریافت بشه."
        )
        self.refresh_taxonomy_btn.clicked.connect(self._load_site_taxonomy)
        filter_row.addWidget(self.refresh_taxonomy_btn)
        root.addLayout(filter_row)

        select_row = QHBoxLayout()
        self.select_all_btn = QPushButton("✅ انتخابِ همه (نتایجِ فیلترشده)")
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn = QPushButton("◻️ لغوِ انتخابِ همه")
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.count_label = QLabel("")
        select_row.addWidget(self.select_all_btn)
        select_row.addWidget(self.select_none_btn)
        select_row.addStretch(1)
        select_row.addWidget(self.count_label)
        root.addLayout(select_row)

        self.product_list = QListWidget()
        self.product_list.setLayoutDirection(Qt.RightToLeft)
        self.product_list.itemChanged.connect(lambda _=None: self._update_count_label())
        root.addWidget(self.product_list, 1)

        root.addWidget(self._build_action_panel())

        self._reload_products()
        self._load_site_taxonomy()

    # ------------------------------------------------------------------
    def _build_action_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        v = QVBoxLayout(panel)

        # --- دسته‌بندی ---
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("دسته‌بندیِ سایت:"))
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.NoInsert)
        self.category_combo.setMinimumWidth(220)
        cat_row.addWidget(self.category_combo, 1)

        new_cat_btn = QPushButton("+ دسته‌بندیِ جدید")
        new_cat_btn.clicked.connect(self._create_new_category)
        cat_row.addWidget(new_cat_btn)

        apply_cat_btn = QPushButton("📌 الصاق به انتخاب‌شده‌ها")
        apply_cat_btn.clicked.connect(self._apply_category_to_selected)
        cat_row.addWidget(apply_cat_btn)

        from sync_app.core.integrations.erp_provider import erp_provider_label

        revert_btn = QPushButton("↩️ بازگردانی به حالتِ خودکار")
        revert_btn.setToolTip(
            f"حذفِ کاملِ override — دوباره از منطقِ خودکارِ {erp_provider_label(self.config)}→"
            "دسته‌بندی استفاده می‌شه"
        )
        revert_btn.clicked.connect(self._revert_selected_to_auto)
        cat_row.addWidget(revert_btn)
        v.addLayout(cat_row)

        # --- برند ---
        brand_row = QHBoxLayout()
        brand_row.addWidget(QLabel("برندِ سایت:"))
        self.brand_combo = QComboBox()
        self.brand_combo.setEditable(True)
        self.brand_combo.setInsertPolicy(QComboBox.NoInsert)
        self.brand_combo.setMinimumWidth(220)
        brand_row.addWidget(self.brand_combo, 1)

        new_brand_btn = QPushButton("+ برندِ جدید")
        new_brand_btn.clicked.connect(self._create_new_brand)
        brand_row.addWidget(new_brand_btn)

        apply_brand_btn = QPushButton("📌 الصاق به انتخاب‌شده‌ها")
        apply_brand_btn.clicked.connect(self._apply_brand_to_selected)
        brand_row.addWidget(apply_brand_btn)
        v.addLayout(brand_row)

        self.status_label = QLabel("در حالِ دریافتِ دسته‌بندی/برندِ سایت...")
        self.status_label.setStyleSheet("color:#64748b; font-size:12px;")
        v.addWidget(self.status_label)

        return panel

    # ------------------------------------------------------------------
    # نامِ دسته‌بندیِ ERP — مستقیم از درختِ خودِ تبِ دسته‌بندی‌ها
    # ------------------------------------------------------------------
    def _erp_code_name_map(self) -> dict[str, str]:
        """کد → نامِ دسته‌بندیِ ERP، مستقیم از درختِ SQL‌محورِ خودِ تبِ
        دسته‌بندی‌ها (نه با حدس‌زدن از رویِ اسلاگِ دسته‌بندیِ سایت — که از وقتی
        دسته‌بندیِ سایت مستقل از ERP شده، دیگه لزوماً کدِ ERP رو تویِ خودش
        نداره و همیشه فقط کد رو نشون می‌داد، نه اسم)."""
        out: dict[str, str] = {}
        tree = getattr(self.category_tab_ref, "tree", None)
        if tree is None:
            return out
        for i in range(tree.topLevelItemCount()):
            parent = tree.topLevelItem(i)
            m_code = str(parent.data(0, Qt.UserRole + 1) or "").strip()
            m_name = str(parent.data(0, Qt.UserRole) or "").strip()
            if m_code and m_name:
                out[m_code] = m_name
            for j in range(parent.childCount()):
                child = parent.child(j)
                s_code = str(child.data(0, Qt.UserRole + 1) or "").strip()
                s_name = str(child.data(0, Qt.UserRole) or "").strip()
                if s_code and s_name:
                    out[m_code + s_code] = s_name
        return out

    # ------------------------------------------------------------------
    # بارگذاریِ محصولات (از خودِ تبِ محصولات — بدونِ کوئریِ دوباره‌ی SQL)
    # ------------------------------------------------------------------
    def _reload_products(self):
        from sync_app.core.product_woo_map_helper import load_product_woo_map
        from sync_app.core.product_category_override import load_category_overrides
        from sync_app.core.product_brand_override import load_brand_overrides
        from sync_app.core.category_rules import resolve_product_categories, sku_to_category_codes
        from sync_app.core.category_resolver import load_category_map

        self.product_list.blockSignals(True)
        self.product_list.clear()

        product_map = load_product_woo_map()
        overrides = load_category_overrides()
        brand_overrides = load_brand_overrides()
        cat_map = load_category_map()
        self._erp_code_index = self._erp_code_name_map()

        erp_codes_seen: set[str] = set()
        source_list = getattr(self.product_tab_ref, "product_list", None)
        if source_list is None:
            self.status_label.setText("⚠️ ابتدا یک‌بار تبِ «محصولات» را باز/بروزرسانی کنید.")
            self.product_list.blockSignals(False)
            return

        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label_prefix = erp_provider_label(self.config)

        for i in range(source_list.count()):
            src_item = source_list.item(i)
            sku = src_item.data(Qt.UserRole)
            if not sku:
                continue
            sku = str(sku)
            name = str(src_item.data(Qt.UserRole + 4) or "")
            is_linked = bool(src_item.data(Qt.UserRole + 12))
            manual_ids = overrides.get(sku)
            has_override = bool(manual_ids)
            codes = sku_to_category_codes(sku)
            erp_codes_seen.update(codes)
            leaf_code = codes[0] if codes else ""
            erp_name = self._erp_code_index.get(leaf_code)
            if leaf_code and erp_name:
                erp_label = f"{erp_name} (کدِ {leaf_code})"
            elif leaf_code:
                erp_label = f"کدِ {leaf_code}"
            else:
                erp_label = "—"

            if manual_ids:
                effective_ids = list(manual_ids)
            else:
                effective_ids = [
                    int(c["id"]) for c in resolve_product_categories(sku, cat_map, self._slug_map)
                ]
            if effective_ids:
                cat_names = [self._id_to_name.get(cid, f"#{cid}") for cid in effective_ids]
                site_cat_label = "، ".join(cat_names)
            else:
                site_cat_label = "بدونِ دسته‌بندیِ سایت"

            brand_id = brand_overrides.get(sku)
            if brand_id:
                brand_name = self._brand_id_to_name.get(brand_id)
                brand_label = f"{brand_name} (#{brand_id})" if brand_name else f"#{brand_id}"
            else:
                brand_label = "بدونِ برند"

            label_bits = []
            label_bits.append("✅" if is_linked else "⭕")
            if has_override:
                label_bits.append("🏷️")
            label_bits.append(
                f"{name} — کد: {sku} | {erp_label_prefix}: {erp_label} | سایت: {site_cat_label} | "
                f"برند: {brand_label}"
            )
            item = QListWidgetItem(" ".join(label_bits))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, sku)
            item.setData(Qt.UserRole + 1, name)
            item.setData(Qt.UserRole + 2, is_linked)
            item.setData(Qt.UserRole + 3, has_override)
            item.setData(Qt.UserRole + 4, codes)
            item.setData(Qt.UserRole + 5, (name + " " + sku).lower())
            item.setData(Qt.UserRole + 6, bool(effective_ids))  # دارایِ دسته‌بندیِ سایت (مؤثر)
            item.setData(Qt.UserRole + 7, bool(brand_id))  # دارایِ برند
            self.product_list.addItem(item)

        erp_options = []
        for code in sorted(erp_codes_seen):
            entry_name = self._erp_code_index.get(code)
            label = f"{entry_name} (کدِ {code})" if entry_name else f"کدِ {code}"
            erp_options.append((code, label))
        self.erp_category_filter.set_options(erp_options)

        self.product_list.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self, *_args):
        needle = (self.search_input.text() or "").strip().lower()
        erp_codes_selected = self.erp_category_filter.selected_codes()
        link_mode = self.link_filter_combo.currentData() or "all"
        override_mode = self.override_filter_combo.currentData() or "all"
        brand_mode = self.brand_filter_combo.currentData() or "all"

        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            visible = True
            if needle and needle not in (item.data(Qt.UserRole + 5) or ""):
                visible = False
            if visible and erp_codes_selected and not (erp_codes_selected & set(item.data(Qt.UserRole + 4) or [])):
                visible = False
            if visible and link_mode == "linked" and not item.data(Qt.UserRole + 2):
                visible = False
            if visible and link_mode == "unlinked" and item.data(Qt.UserRole + 2):
                visible = False
            if visible and override_mode == "manual" and not item.data(Qt.UserRole + 3):
                visible = False
            if visible and override_mode == "auto" and item.data(Qt.UserRole + 3):
                visible = False
            if visible and override_mode == "no_category" and item.data(Qt.UserRole + 6):
                visible = False
            if visible and brand_mode == "no_brand" and item.data(Qt.UserRole + 7):
                visible = False
            if visible and brand_mode == "has_brand" and not item.data(Qt.UserRole + 7):
                visible = False
            item.setHidden(not visible)
        self._update_count_label()

    def _update_count_label(self):
        total_visible = 0
        checked = 0
        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            if item.isHidden():
                continue
            total_visible += 1
            if item.checkState() == Qt.Checked:
                checked += 1
        self.count_label.setText(f"{checked} انتخاب‌شده از {total_visible} نتیجه")

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        self.product_list.blockSignals(True)
        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            if not item.isHidden():
                item.setCheckState(state)
        self.product_list.blockSignals(False)
        self._update_count_label()

    def _checked_skus(self) -> list[str]:
        out = []
        for i in range(self.product_list.count()):
            item = self.product_list.item(i)
            if not item.isHidden() and item.checkState() == Qt.Checked:
                out.append(str(item.data(Qt.UserRole)))
        return out

    # ------------------------------------------------------------------
    # دسته‌بندی/برندِ سایت (زنده)
    # ------------------------------------------------------------------
    def _load_site_taxonomy(self):
        site_url = str(self.config.get("WC_URL") or self.config.get("PS_URL") or "").strip()
        if not site_url:
            self.status_label.setText("⚠️ ابتدا آدرسِ فروشگاه را در تبِ تنظیمات وارد کنید.")
            return
        self.status_label.setText("⏳ در حالِ دریافتِ دسته‌بندی/برندِ سایت...")
        self._loader = SiteTaxonomyLoader(self.config)
        self._loader.done.connect(self._on_taxonomy_loaded)
        self._loader.start()

    def _on_taxonomy_loaded(self, categories, brands, error):
        if error:
            self.status_label.setText(f"⚠️ دریافتِ دسته‌بندی/برند ناموفق بود: {error}")
            return
        self._categories = categories or []
        self._brands = brands or []
        self._slug_map = {c.get("slug"): c for c in self._categories if c.get("slug")}
        self._id_to_name = {
            int(c["id"]): str(c.get("name") or f"#{c['id']}")
            for c in self._categories
            if c.get("id")
        }
        self._brand_id_to_name = {
            int(b["id"]): str(b.get("name") or f"#{b['id']}")
            for b in self._brands
            if b.get("id")
        }
        # نکته: self._erp_code_index دیگه اینجا ساخته نمی‌شه — از درختِ خودِ
        # تبِ دسته‌بندی‌ها (SQL) میاد، تویِ _reload_products (که چند خط
        # پایین‌تر صدا زده می‌شه)، نه از حدس‌زدن رویِ اسلاگِ دسته‌بندیِ سایت.

        self.category_combo.clear()
        for cat in sorted(self._categories, key=lambda c: str(c.get("name") or "")):
            cid = int(cat.get("id") or 0)
            if cid:
                self.category_combo.addItem(f"{cat.get('name')} ({cid})", cid)

        self.brand_combo.clear()
        for b in sorted(self._brands, key=lambda c: str(c.get("name") or "")):
            bid = int(b.get("id") or 0)
            if bid:
                self.brand_combo.addItem(f"{b.get('name')} ({bid})", bid)

        self.status_label.setText(
            f"✅ {len(self._categories)} دسته‌بندی و {len(self._brands)} برند از سایت دریافت شد."
        )
        # حالا که اسم‌هایِ واقعیِ دسته‌بندی‌هایِ سایت در دسترسه، لیستِ محصولات
        # رو دوباره بساز تا ستونِ «سایت: ...» و فیلترِ دژاوو، به‌جایِ idِ خام،
        # اسمِ واقعی نشون بدن.
        self._reload_products()

    # ------------------------------------------------------------------
    # دسته‌بندی: ساخت/اعمال/بازگردانی
    # ------------------------------------------------------------------
    def _create_new_category(self):
        name, ok = QInputDialog.getText(self, "دسته‌بندیِ جدید", "نامِ دسته‌بندیِ جدید:")
        if not ok or not (name or "").strip():
            return
        name = name.strip()
        try:
            from sync_app.core.integrations.commerce_provider import is_prestashop

            if is_prestashop(self.config):
                from sync_app.core.ps_sync_helper import ps_create_category

                slug = name.replace(" ", "-")
                created = ps_create_category(self.config, name=name, slug=slug)
            else:
                from sync_app.core.wc_sync_helper import create_wc_category

                created = create_wc_category(self.config, name)
        except Exception as exc:
            QMessageBox.critical(self, "خطا", f"ساختِ دسته‌بندیِ جدید ناموفق بود:\n{exc}")
            return
        cid = int(created.get("id") or 0)
        if not cid:
            QMessageBox.critical(self, "خطا", "دسته‌بندی ساخته نشد.")
            return
        self._categories.append(created)
        self.category_combo.addItem(f"{created.get('name')} ({cid})", cid)
        self.category_combo.setCurrentIndex(self.category_combo.count() - 1)
        QMessageBox.information(self, "انجام شد", f"دسته‌بندیِ «{name}» ساخته شد.")

    def _apply_category_to_selected(self):
        cat_id = self.category_combo.currentData()
        if not cat_id:
            QMessageBox.warning(self, "توجه", "یک دسته‌بندی از لیست انتخاب کنید.")
            return
        skus = self._checked_skus()
        if not skus:
            QMessageBox.warning(self, "توجه", "حداقل یک محصول را تیک بزنید.")
            return
        answer = QMessageBox.question(
            self, "الصاقِ دسته‌بندی",
            f"دسته‌بندیِ انتخاب‌شده به {len(skus)} محصول اضافه بشه؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._bulk_apply_category(skus, int(cat_id))

    def _bulk_apply_category(self, skus: list[str], category_id: int):
        from sync_app.core.product_category_override import get_manual_category_ids, set_manual_category_ids
        from sync_app.core.product_woo_map_helper import load_product_woo_map
        from sync_app.core.category_rules import resolve_product_categories
        from sync_app.core.category_resolver import load_category_map
        from sync_app.core.integrations.commerce_provider import is_prestashop

        product_map = load_product_woo_map()
        ps_mode = is_prestashop(self.config)
        cat_map = load_category_map() if not ps_mode else {}
        ok_count, fail_count = 0, 0
        for sku in skus:
            try:
                baseline = get_manual_category_ids(sku)
                if baseline is None:
                    baseline = [
                        int(c["id"]) for c in resolve_product_categories(sku, cat_map, {})
                    ]
                merged = sorted({*baseline, int(category_id)})
                set_manual_category_ids(sku, merged)

                pid = product_map.get(sku)
                if pid:
                    pid = int(pid)
                    if ps_mode:
                        from sync_app.core.ps_sync_helper import ps_update_product

                        ps_update_product(self.config, pid, category_ids=merged)
                    else:
                        from sync_app.core.wc_sync_helper import set_wc_product_categories

                        ok, _resp, err = set_wc_product_categories(self.config, pid, merged)
                        if not ok:
                            raise RuntimeError(err)
                ok_count += 1
            except Exception as exc:
                fail_count += 1
                log.warning(f"⚠️ الصاقِ دسته‌بندی برایِ {sku} ناموفق بود: {exc}")
        self._reload_products()
        QMessageBox.information(
            self, "نتیجه", f"دسته‌بندی برایِ {ok_count} محصول اعمال شد" + (f" — {fail_count} ناموفق." if fail_count else ".")
        )

    def _revert_selected_to_auto(self):
        from sync_app.core.integrations.erp_provider import erp_provider_label

        skus = self._checked_skus()
        if not skus:
            QMessageBox.warning(self, "توجه", "حداقل یک محصول را تیک بزنید.")
            return
        answer = QMessageBox.question(
            self, "بازگردانی",
            f"دسته‌بندیِ دستیِ {len(skus)} محصول حذف بشه و دوباره از منطقِ خودکارِ "
            f"{erp_provider_label(self.config)}→دسته‌بندی استفاده بشه؟ (اعمالِ واقعی رویِ سایت با "
            "سینکِ بعدی انجام می‌شه)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        from sync_app.core.product_category_override import set_manual_category_ids

        for sku in skus:
            set_manual_category_ids(sku, None)
        self._reload_products()
        QMessageBox.information(self, "انجام شد", "دسته‌بندیِ دستیِ محصولاتِ انتخاب‌شده پاک شد.")

    # ------------------------------------------------------------------
    # برند: ساخت/اعمال
    # ------------------------------------------------------------------
    def _create_new_brand(self):
        name, ok = QInputDialog.getText(self, "برندِ جدید", "نامِ برندِ جدید:")
        if not ok or not (name or "").strip():
            return
        name = name.strip()
        try:
            from sync_app.core.integrations.commerce_provider import is_prestashop

            if is_prestashop(self.config):
                from sync_app.core.ps_sync_helper import ps_create_manufacturer

                created = ps_create_manufacturer(self.config, name=name)
            else:
                from sync_app.core.wc_sync_helper import create_wc_brand

                created = create_wc_brand(self.config, name)
        except Exception as exc:
            QMessageBox.critical(self, "خطا", f"ساختِ برندِ جدید ناموفق بود:\n{exc}")
            return
        bid = int(created.get("id") or 0)
        if not bid:
            QMessageBox.critical(self, "خطا", "برند ساخته نشد.")
            return
        self._brands.append(created)
        self.brand_combo.addItem(f"{created.get('name')} ({bid})", bid)
        self.brand_combo.setCurrentIndex(self.brand_combo.count() - 1)
        QMessageBox.information(self, "انجام شد", f"برندِ «{name}» ساخته شد.")

    def _apply_brand_to_selected(self):
        brand_id = self.brand_combo.currentData()
        if not brand_id:
            QMessageBox.warning(self, "توجه", "یک برند از لیست انتخاب کنید.")
            return
        skus = self._checked_skus()
        if not skus:
            QMessageBox.warning(self, "توجه", "حداقل یک محصول را تیک بزنید.")
            return
        answer = QMessageBox.question(
            self, "الصاقِ برند",
            f"برندِ انتخاب‌شده برایِ {len(skus)} محصول تنظیم بشه؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._bulk_apply_brand(skus, int(brand_id))

    def _bulk_apply_brand(self, skus: list[str], brand_id: int):
        from sync_app.core.product_woo_map_helper import load_product_woo_map
        from sync_app.core.product_brand_override import set_manual_brand_id
        from sync_app.core.integrations.commerce_provider import is_prestashop

        product_map = load_product_woo_map()
        ps_mode = is_prestashop(self.config)
        ok_count, fail_count = 0, 0
        for sku in skus:
            pid = product_map.get(sku)
            if not pid:
                fail_count += 1
                log.warning(f"⚠️ محصول {sku} به سایت لینک نشده — رد شد.")
                continue
            pid = int(pid)
            try:
                if ps_mode:
                    from sync_app.core.ps_sync_helper import ps_update_product

                    ps_update_product(self.config, pid, manufacturer_id=brand_id)
                else:
                    from sync_app.core.wc_sync_helper import set_wc_product_brands

                    ok, _resp, err = set_wc_product_brands(self.config, pid, [brand_id])
                    if not ok:
                        raise RuntimeError(err)
                # برایِ اینکه لیستِ قیمتِ مخصوصِ این برند (تبِ «لیستِ قیمت») موقعِ
                # سینکِ بعدی بتونه محلی resolve بشه — بدونِ نیاز به یه فراخوانیِ
                # زنده‌ی API برایِ «برندِ فعلیِ این SKU چیه». هم‌زمان روی خودِ
                # ردیفِ محصول تویِ همین تب هم نشون داده می‌شه.
                set_manual_brand_id(sku, brand_id)
                ok_count += 1
            except Exception as exc:
                fail_count += 1
                log.warning(f"⚠️ الصاقِ برند برایِ {sku} ناموفق بود: {exc}")
        self._reload_products()
        QMessageBox.information(
            self, "نتیجه", f"برند برایِ {ok_count} محصول اعمال شد" + (f" — {fail_count} ناموفق." if fail_count else ".")
        )

    # ------------------------------------------------------------------
    def ensure_tab_data_loaded(self):
        # اگه لیست هنوز خالیه (اولین‌بار قبل از لودشدنِ تبِ محصولات ساخته
        # شده)، حالا که تبِ محصولات قطعاً موجوده، دوباره بارگذاری کن.
        if self.product_list.count() == 0:
            self._reload_products()
