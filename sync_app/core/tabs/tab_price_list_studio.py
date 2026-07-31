"""تبِ «لیستِ قیمت» — تنظیمِ لیستِ قیمتِ عادی/ویژه و مارک‌آپِ مخصوصِ هر
دسته‌بندی یا برندِ سایت (جدا از تبِ «دسته‌بندی و برند» تا اونجا شلوغ نشه).

همه‌ی قاعده‌هایِ ثبت‌شده (چه رویِ دسته‌بندی، چه رویِ برند) پایینِ صفحه به‌صورتِ
یه لیست/جدول دیده می‌شن — با کلیک رویِ هر ردیف می‌شه ویرایشش کرد، یا حذفش
کرد.

اولویتِ نهایی موقعِ سینک: override رویِ خودِ محصول (اگه از قبل جایی ست
شده باشه) → برندِ دستیِ سایتِ محصول → دسته‌بندیِ دستیِ سایتِ محصول → لیستِ
قیمتِ دژاوو/ERP → پیش‌فرضِ سراسریِ تبِ تنظیمات."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.tabs.tab_category_brand_studio import SiteTaxonomyLoader

log = logging.getLogger("SyncApp")

_RULES_COLUMNS = [
    "نوع", "نام", "لیستِ عادی", "٪ عادی", "مبلغِ عادی",
    "ویژه", "لیستِ ویژه", "٪ ویژه", "مبلغِ ویژه",
]


def _index_label(idx) -> str:
    if idx is None:
        return "—"
    return f"لیست {int(idx) + 1}"


def _num_label(val) -> str:
    val = float(val or 0)
    if not val:
        return "—"
    return f"{val:g}"


class PriceListStudioTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self._categories: list[dict] = []
        self._brands: list[dict] = []
        self._loader = None
        self.init_ui()
        self._load_site_taxonomy()

    # ------------------------------------------------------------------
    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        hint = QLabel(
            "یه دسته‌بندی یا برندِ سایت رو انتخاب کنید و لیستِ قیمت/مارک‌آپِ مخصوصِ اون رو ثبت "
            "کنید — همه‌ی محصولاتی که الان یا بعداً به همون دسته‌بندی/برند وصل بشن (از تبِ «دسته‌بندی "
            "و برند»)، با سینکِ بعدی خودکار همینو می‌گیرن. اگه یه محصول هم برندِ قیمت‌دار داشته باشه هم "
            "دسته‌بندیِ قیمت‌دار، برند اولویت داره."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        root.addWidget(hint)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("دسته‌بندیِ سایت:"))
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.NoInsert)
        self.category_combo.setMinimumWidth(240)
        self.category_combo.currentIndexChanged.connect(self._load_price_fields_for_current_category)
        target_row.addWidget(self.category_combo, 1)

        target_row.addWidget(QLabel("برندِ سایت:"))
        self.brand_combo = QComboBox()
        self.brand_combo.setEditable(True)
        self.brand_combo.setInsertPolicy(QComboBox.NoInsert)
        self.brand_combo.setMinimumWidth(240)
        self.brand_combo.currentIndexChanged.connect(self._load_price_fields_for_current_brand)
        target_row.addWidget(self.brand_combo, 1)

        refresh_btn = QPushButton("🔄 بروزرسانی")
        refresh_btn.setToolTip("دریافتِ دوباره‌ی لیستِ دسته‌بندی/برندِ سایت")
        refresh_btn.clicked.connect(self._load_site_taxonomy)
        target_row.addWidget(refresh_btn)
        root.addLayout(target_row)

        root.addWidget(self._build_price_list_panel())

        rules_title = QLabel("📋 قاعده‌هایِ ثبت‌شده (کلیک رویِ ردیف = ویرایش)")
        rules_title.setStyleSheet("font-weight:700; margin-top:6px;")
        root.addWidget(rules_title)

        self.rules_table = QTableWidget(0, len(_RULES_COLUMNS))
        self.rules_table.setLayoutDirection(Qt.RightToLeft)
        self.rules_table.setHorizontalHeaderLabels(_RULES_COLUMNS)
        self.rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.rules_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rules_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rules_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rules_table.itemSelectionChanged.connect(self._on_rule_row_selected)
        root.addWidget(self.rules_table, 1)

        delete_row = QHBoxLayout()
        delete_row.addStretch(1)
        self.delete_rule_btn = QPushButton("🗑️ حذفِ ردیفِ انتخاب‌شده")
        self.delete_rule_btn.clicked.connect(self._delete_selected_rule)
        delete_row.addWidget(self.delete_rule_btn)
        root.addLayout(delete_row)

        self.status_label = QLabel("در حالِ دریافتِ دسته‌بندی/برندِ سایت...")
        self.status_label.setStyleSheet("color:#64748b; font-size:12px;")
        root.addWidget(self.status_label)

    def _build_price_list_panel(self) -> QWidget:
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        v = QVBoxLayout(box)

        title = QLabel("💰 لیستِ قیمتِ مخصوصِ دسته‌بندی/برندِ انتخاب‌شده")
        title.setStyleSheet("font-weight:700;")
        v.addWidget(title)

        reg_row = QHBoxLayout()
        reg_row.addWidget(QLabel("لیستِ قیمتِ عادی:"))
        self.price_list_combo = QComboBox()
        self.price_list_combo.addItem("— بدونِ override (ارثِ خودکار) —", -1)
        for i in range(1, 11):
            self.price_list_combo.addItem(f"لیست قیمت {i}", i - 1)
        reg_row.addWidget(self.price_list_combo, 1)

        reg_row.addWidget(QLabel("٪ عادی:"))
        self.regular_markup_percent_spin = QDoubleSpinBox()
        self.regular_markup_percent_spin.setRange(-90.0, 500.0)
        self.regular_markup_percent_spin.setDecimals(1)
        self.regular_markup_percent_spin.setSuffix(" %")
        reg_row.addWidget(self.regular_markup_percent_spin)

        reg_row.addWidget(QLabel("مبلغِ عادی:"))
        self.regular_markup_amount_spin = QDoubleSpinBox()
        self.regular_markup_amount_spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.regular_markup_amount_spin.setDecimals(0)
        reg_row.addWidget(self.regular_markup_amount_spin)
        v.addLayout(reg_row)

        sale_row = QHBoxLayout()
        self.sale_enabled_cb = QCheckBox("قیمتِ ویژه فعال:")
        sale_row.addWidget(self.sale_enabled_cb)
        self.sale_price_list_combo = QComboBox()
        self.sale_price_list_combo.addItem("— بدونِ override —", -1)
        for i in range(1, 11):
            self.sale_price_list_combo.addItem(f"لیست قیمت {i}", i - 1)
        sale_row.addWidget(self.sale_price_list_combo, 1)

        sale_row.addWidget(QLabel("٪ ویژه:"))
        self.sale_markup_percent_spin = QDoubleSpinBox()
        self.sale_markup_percent_spin.setRange(-90.0, 500.0)
        self.sale_markup_percent_spin.setDecimals(1)
        self.sale_markup_percent_spin.setSuffix(" %")
        sale_row.addWidget(self.sale_markup_percent_spin)

        sale_row.addWidget(QLabel("مبلغِ ویژه:"))
        self.sale_markup_amount_spin = QDoubleSpinBox()
        self.sale_markup_amount_spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.sale_markup_amount_spin.setDecimals(0)
        sale_row.addWidget(self.sale_markup_amount_spin)
        v.addLayout(sale_row)

        hint = QLabel(
            "درصد اول رویِ قیمتِ پایه اعمال می‌شه، بعد مبلغِ ثابت به نتیجه اضافه/کم می‌شه — عادی و ویژه "
            "کاملاً جدا از هم. اولویتِ نهایی: override رویِ خودِ محصول → برندِ سایتِ محصول → دسته‌بندیِ "
            "سایتِ محصول → لیستِ قیمتِ دژاوو/ERP → پیش‌فرضِ سراسریِ تبِ تنظیمات."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:11px;")
        v.addWidget(hint)

        btn_row = QHBoxLayout()
        save_cat_btn = QPushButton("💾 ثبت برایِ دسته‌بندیِ انتخاب‌شده")
        save_cat_btn.clicked.connect(self._save_price_settings_for_category)
        btn_row.addWidget(save_cat_btn)

        save_brand_btn = QPushButton("💾 ثبت برایِ برندِ انتخاب‌شده")
        save_brand_btn.clicked.connect(self._save_price_settings_for_brand)
        btn_row.addWidget(save_brand_btn)

        clear_btn = QPushButton("🆕 فرمِ خالیِ جدید")
        clear_btn.setToolTip("پاک‌کردنِ فیلدها برایِ ثبتِ یه قاعده‌ی جدید")
        clear_btn.clicked.connect(self._clear_price_fields)
        btn_row.addWidget(clear_btn)
        v.addLayout(btn_row)

        return box

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
        self._refresh_rules_table()

    # ------------------------------------------------------------------
    # جدولِ قاعده‌هایِ ثبت‌شده
    # ------------------------------------------------------------------
    def _refresh_rules_table(self):
        from sync_app.core.site_taxonomy_price_list import (
            list_brand_price_settings,
            list_category_price_settings,
        )

        cat_names = {int(c["id"]): str(c.get("name") or f"#{c['id']}") for c in self._categories if c.get("id")}
        brand_names = {int(b["id"]): str(b.get("name") or f"#{b['id']}") for b in self._brands if b.get("id")}

        rows: list[tuple[str, int, str, dict]] = []
        for cid_str, record in list_category_price_settings(self.config).items():
            cid = int(cid_str)
            rows.append(("category", cid, cat_names.get(cid, f"#{cid}"), record))
        for bid_str, record in list_brand_price_settings(self.config).items():
            bid = int(bid_str)
            rows.append(("brand", bid, brand_names.get(bid, f"#{bid}"), record))

        self.rules_table.setRowCount(0)
        for kind, entity_id, name, record in rows:
            row_idx = self.rules_table.rowCount()
            self.rules_table.insertRow(row_idx)
            type_item = QTableWidgetItem("🏷️ دسته‌بندی" if kind == "category" else "🏢 برند")
            type_item.setData(Qt.UserRole, (kind, entity_id))
            values = [
                type_item.text(),
                name,
                _index_label(record.get("regular_index")),
                _num_label(record.get("regular_markup_percent")),
                _num_label(record.get("regular_markup_amount")),
                "✅" if record.get("sale_enabled") else "—",
                _index_label(record.get("sale_index")) if record.get("sale_enabled") else "—",
                _num_label(record.get("sale_markup_percent")) if record.get("sale_enabled") else "—",
                _num_label(record.get("sale_markup_amount")) if record.get("sale_enabled") else "—",
            ]
            for col, text in enumerate(values):
                cell = QTableWidgetItem(text)
                if col == 0:
                    cell.setData(Qt.UserRole, (kind, entity_id))
                self.rules_table.setItem(row_idx, col, cell)

    def _selected_rule(self):
        items = self.rules_table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        first_cell = self.rules_table.item(row, 0)
        if first_cell is None:
            return None
        return first_cell.data(Qt.UserRole)

    def _on_rule_row_selected(self):
        rule = self._selected_rule()
        if not rule:
            return
        kind, entity_id = rule
        if kind == "category":
            idx = self.category_combo.findData(entity_id)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
        else:
            idx = self.brand_combo.findData(entity_id)
            if idx >= 0:
                self.brand_combo.setCurrentIndex(idx)

    def _delete_selected_rule(self):
        rule = self._selected_rule()
        if not rule:
            QMessageBox.warning(self, "توجه", "یک ردیف از جدول انتخاب کنید.")
            return
        kind, entity_id = rule
        answer = QMessageBox.question(
            self, "حذف", "این قاعده حذف بشه؟", QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        from sync_app.core.site_taxonomy_price_list import (
            delete_brand_price_settings,
            delete_category_price_settings,
        )

        if kind == "category":
            delete_category_price_settings(entity_id)
        else:
            delete_brand_price_settings(entity_id)
        self.config = load_secure_config(None) or {}
        self._refresh_rules_table()

    # ------------------------------------------------------------------
    def _clear_price_fields(self):
        self.price_list_combo.setCurrentIndex(0)
        self.regular_markup_percent_spin.setValue(0)
        self.regular_markup_amount_spin.setValue(0)
        self.sale_enabled_cb.setChecked(False)
        self.sale_price_list_combo.setCurrentIndex(0)
        self.sale_markup_percent_spin.setValue(0)
        self.sale_markup_amount_spin.setValue(0)

    def _load_price_fields_from_record(self, record: dict | None):
        self._clear_price_fields()
        if not record:
            return
        if record.get("regular_index") is not None:
            idx = self.price_list_combo.findData(int(record["regular_index"]))
            if idx >= 0:
                self.price_list_combo.setCurrentIndex(idx)
        self.regular_markup_percent_spin.setValue(float(record.get("regular_markup_percent") or 0))
        self.regular_markup_amount_spin.setValue(float(record.get("regular_markup_amount") or 0))
        self.sale_enabled_cb.setChecked(bool(record.get("sale_enabled")))
        if record.get("sale_index") is not None:
            idx = self.sale_price_list_combo.findData(int(record["sale_index"]))
            if idx >= 0:
                self.sale_price_list_combo.setCurrentIndex(idx)
        self.sale_markup_percent_spin.setValue(float(record.get("sale_markup_percent") or 0))
        self.sale_markup_amount_spin.setValue(float(record.get("sale_markup_amount") or 0))

    def _load_price_fields_for_current_category(self, *_args):
        from sync_app.core.site_taxonomy_price_list import get_category_price_settings

        cid = self.category_combo.currentData()
        if not cid:
            return
        self._load_price_fields_from_record(get_category_price_settings(self.config, cid))

    def _load_price_fields_for_current_brand(self, *_args):
        from sync_app.core.site_taxonomy_price_list import get_brand_price_settings

        bid = self.brand_combo.currentData()
        if not bid:
            return
        self._load_price_fields_from_record(get_brand_price_settings(self.config, bid))

    def _collect_price_record(self) -> dict:
        return {
            "regular_index": (
                int(self.price_list_combo.currentData())
                if int(self.price_list_combo.currentData() or -1) >= 0
                else None
            ),
            "regular_markup_percent": float(self.regular_markup_percent_spin.value()),
            "regular_markup_amount": float(self.regular_markup_amount_spin.value()),
            "sale_enabled": self.sale_enabled_cb.isChecked(),
            "sale_index": (
                int(self.sale_price_list_combo.currentData())
                if int(self.sale_price_list_combo.currentData() or -1) >= 0
                else None
            ),
            "sale_markup_percent": float(self.sale_markup_percent_spin.value()),
            "sale_markup_amount": float(self.sale_markup_amount_spin.value()),
        }

    def _save_price_settings_for_category(self):
        cid = self.category_combo.currentData()
        if not cid:
            QMessageBox.warning(self, "توجه", "یک دسته‌بندی از لیست انتخاب کنید.")
            return
        from sync_app.core.site_taxonomy_price_list import set_category_price_settings

        set_category_price_settings(cid, self._collect_price_record())
        self.config = load_secure_config(None) or {}
        title = self.category_combo.currentText()
        # فرم رو خالی می‌کنیم — وگرنه اگه بعدش بدونِ دستکاریِ فیلدها رویِ
        # «ثبت برایِ برند» هم کلیک بشه، همین مقادیر (که برایِ دسته‌بندی
        # بودن) اشتباهی رویِ برند هم ثبت می‌شدن.
        self._clear_price_fields()
        self._refresh_rules_table()
        QMessageBox.information(
            self, "ثبت شد",
            f"لیستِ قیمت/مارک‌آپ برایِ دسته‌بندیِ «{title}» ذخیره شد — "
            "این محصولات با سینکِ بعدی این قیمت رو می‌گیرن.",
        )

    def _save_price_settings_for_brand(self):
        bid = self.brand_combo.currentData()
        if not bid:
            QMessageBox.warning(self, "توجه", "یک برند از لیست انتخاب کنید.")
            return
        from sync_app.core.site_taxonomy_price_list import set_brand_price_settings

        set_brand_price_settings(bid, self._collect_price_record())
        self.config = load_secure_config(None) or {}
        title = self.brand_combo.currentText()
        self._clear_price_fields()
        self._refresh_rules_table()
        QMessageBox.information(
            self, "ثبت شد",
            f"لیستِ قیمت/مارک‌آپ برایِ برندِ «{title}» ذخیره شد — "
            "این محصولات با سینکِ بعدی این قیمت رو می‌گیرن.",
        )

    # ------------------------------------------------------------------
    def ensure_tab_data_loaded(self):
        if self.category_combo.count() == 0 and self.brand_combo.count() == 0:
            self._load_site_taxonomy()
