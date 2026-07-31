"""تبِ «لیستِ قیمت» — یه جدولِ خام: هر ردیف یک قاعده‌ست، همه‌چیز مستقیم
تویِ خودِ ردیف تنظیم و ذخیره می‌شه (بدونِ فرم/هدرِ جدا). ستونِ اول یه
دسته‌بندی یا برندِ سایت رو انتخاب می‌کنه (فقط یکی، هر ردیف مستقلِ خودشه)،
بقیه‌ی ستون‌ها لیستِ قیمتِ عادی/ویژه و درصد/مبلغِ مارک‌آپِ همون هدف رو
می‌گیرن. دکمه‌ی 💾 همون ردیف رو ذخیره می‌کنه، 🗑 همون ردیف رو حذف می‌کنه.

اولویتِ نهایی موقعِ سینک: override رویِ خودِ محصول (اگه از قبل جایی ست
شده باشه) → برندِ دستیِ سایتِ محصول → دسته‌بندیِ دستیِ سایتِ محصول → لیستِ
قیمتِ دژاوو/ERP → پیش‌فرضِ سراسریِ تبِ تنظیمات."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.tabs.tab_category_brand_studio import SiteTaxonomyLoader

log = logging.getLogger("SyncApp")

COL_TARGET = 0
COL_REG_LIST = 1
COL_REG_PCT = 2
COL_REG_AMT = 3
COL_SALE_ON = 4
COL_SALE_LIST = 5
COL_SALE_PCT = 6
COL_SALE_AMT = 7
COL_ACTIONS = 8

_HEADERS = [
    "دسته‌بندی/برند", "لیستِ عادی", "٪ عادی", "مبلغِ عادی",
    "ویژه", "لیستِ ویژه", "٪ ویژه", "مبلغِ ویژه", "",
]


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
            "هر ردیف یک قاعده‌ی مستقله: یا برایِ یه دسته‌بندیِ سایت، یا برایِ یه برندِ سایت. لیستِ "
            "قیمتِ عادی/ویژه و درصد/مبلغِ مارک‌آپ رو مستقیم تویِ همون ردیف بدید و 💾 بزنید. همه‌ی "
            "محصولاتی که به همون دسته‌بندی/برند وصل باشن، خودکار همینو می‌گیرن — اگه یه محصول هم "
            "برندِ قیمت‌دار داشته باشه هم دسته‌بندیِ قیمت‌دار، برند اولویت داره."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        root.addWidget(hint)

        top_row = QHBoxLayout()
        add_btn = QPushButton("➕ افزودنِ ردیفِ جدید")
        add_btn.clicked.connect(lambda: self._add_row())
        top_row.addWidget(add_btn)
        top_row.addStretch(1)
        refresh_btn = QPushButton("🔄 بروزرسانیِ دسته‌بندی/برندِ سایت")
        refresh_btn.clicked.connect(self._load_site_taxonomy)
        top_row.addWidget(refresh_btn)
        root.addLayout(top_row)

        self.rules_table = QTableWidget(0, len(_HEADERS))
        self.rules_table.setLayoutDirection(Qt.RightToLeft)
        self.rules_table.setHorizontalHeaderLabels(_HEADERS)
        self.rules_table.horizontalHeader().setSectionResizeMode(COL_TARGET, QHeaderView.Stretch)
        self.rules_table.verticalHeader().setVisible(False)
        # ویجت‌هایی که تویِ هر ردیف می‌ذاریم (کمبو/اسپین‌باکس) با ارتفاعِ
        # پیش‌فرضِ خیلی کمِ QTableWidget جمع‌وجور و روی‌هم می‌افتادن — یه
        # ارتفاعِ ثابتِ بزرگ‌تر برایِ همه‌ی ردیف‌ها تنظیم می‌کنیم.
        self.rules_table.verticalHeader().setDefaultSectionSize(44)
        root.addWidget(self.rules_table, 1)

        self.status_label = QLabel("در حالِ دریافتِ دسته‌بندی/برندِ سایت...")
        self.status_label.setStyleSheet("color:#64748b; font-size:12px;")
        root.addWidget(self.status_label)

    # ------------------------------------------------------------------
    # ویجت‌سازهایِ کمکی
    # ------------------------------------------------------------------
    def _make_target_combo(self) -> QComboBox:
        combo = QComboBox()
        self._fill_target_combo(combo)
        return combo

    def _fill_target_combo(self, combo: QComboBox, keep_selection=None):
        # نکته: dataِ آیتمِ کمبو رو tuple نمی‌ذاریم — findData()ِ پی‌کیوت۵
        # QVariantِ اشیایِ پایتونیِ پیچیده (مثلِ tuple) رو گاهی با مقایسه‌ی
        # identity (نه ==) چک می‌کنه، پس یه tupleِ جداگانه‌ساخته‌شده با همون
        # مقدار پیدا نمی‌شه. یه رشته‌ی ساده («category:5») همیشه درست کار می‌کنه.
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— انتخاب کنید —", "")
        for cat in sorted(self._categories, key=lambda c: str(c.get("name") or "")):
            cid = int(cat.get("id") or 0)
            if cid:
                combo.addItem(f"🏷️ {cat.get('name')}", f"category:{cid}")
        for b in sorted(self._brands, key=lambda c: str(c.get("name") or "")):
            bid = int(b.get("id") or 0)
            if bid:
                combo.addItem(f"🏢 {b.get('name')}", f"brand:{bid}")
        if keep_selection:
            idx = combo.findData(keep_selection)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _make_price_list_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.addItem("—", -1)
        for i in range(1, 11):
            combo.addItem(str(i), i - 1)
        return combo

    def _make_percent_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-90.0, 500.0)
        spin.setDecimals(1)
        spin.setSuffix(" %")
        return spin

    def _make_amount_spin(self) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        spin.setDecimals(0)
        return spin

    def _centered(self, widget: QWidget) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(widget)
        return container

    # ------------------------------------------------------------------
    # ردیف‌سازی
    # ------------------------------------------------------------------
    def _add_row(self, kind: str | None = None, entity_id: int | None = None, record: dict | None = None):
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        self.rules_table.setRowHeight(row, 44)

        target_combo = self._make_target_combo()
        if kind and entity_id:
            idx = target_combo.findData(f"{kind}:{entity_id}")
            if idx >= 0:
                target_combo.setCurrentIndex(idx)
        self.rules_table.setCellWidget(row, COL_TARGET, target_combo)

        reg_list = self._make_price_list_combo()
        reg_pct = self._make_percent_spin()
        reg_amt = self._make_amount_spin()
        sale_cb = QCheckBox()
        sale_list = self._make_price_list_combo()
        sale_pct = self._make_percent_spin()
        sale_amt = self._make_amount_spin()

        if record:
            if record.get("regular_index") is not None:
                i = reg_list.findData(int(record["regular_index"]))
                if i >= 0:
                    reg_list.setCurrentIndex(i)
            reg_pct.setValue(float(record.get("regular_markup_percent") or 0))
            reg_amt.setValue(float(record.get("regular_markup_amount") or 0))
            sale_cb.setChecked(bool(record.get("sale_enabled")))
            if record.get("sale_index") is not None:
                i = sale_list.findData(int(record["sale_index"]))
                if i >= 0:
                    sale_list.setCurrentIndex(i)
            sale_pct.setValue(float(record.get("sale_markup_percent") or 0))
            sale_amt.setValue(float(record.get("sale_markup_amount") or 0))

        self.rules_table.setCellWidget(row, COL_REG_LIST, reg_list)
        self.rules_table.setCellWidget(row, COL_REG_PCT, reg_pct)
        self.rules_table.setCellWidget(row, COL_REG_AMT, reg_amt)
        self.rules_table.setCellWidget(row, COL_SALE_ON, self._centered(sale_cb))
        self.rules_table.setCellWidget(row, COL_SALE_LIST, sale_list)
        self.rules_table.setCellWidget(row, COL_SALE_PCT, sale_pct)
        self.rules_table.setCellWidget(row, COL_SALE_AMT, sale_amt)

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(2, 2, 2, 2)
        save_btn = QPushButton("💾")
        save_btn.setToolTip("ذخیره‌یِ همین ردیف")
        del_btn = QPushButton("🗑")
        del_btn.setToolTip("حذفِ همین ردیف")
        actions_layout.addWidget(save_btn)
        actions_layout.addWidget(del_btn)
        self.rules_table.setCellWidget(row, COL_ACTIONS, actions)

        save_btn.clicked.connect(lambda _checked=False, w=actions: self._save_row(w))
        del_btn.clicked.connect(lambda _checked=False, w=actions: self._delete_row(w))
        return row

    def _parse_target(self, raw: str | None) -> tuple[str, int] | None:
        if not raw:
            return None
        kind, _sep, id_str = str(raw).partition(":")
        if not id_str.isdigit():
            return None
        return kind, int(id_str)

    def _row_for_actions_widget(self, actions_widget: QWidget) -> int:
        for r in range(self.rules_table.rowCount()):
            if self.rules_table.cellWidget(r, COL_ACTIONS) is actions_widget:
                return r
        return -1

    def _collect_row_record(self, row: int) -> dict:
        reg_list = self.rules_table.cellWidget(row, COL_REG_LIST)
        reg_pct = self.rules_table.cellWidget(row, COL_REG_PCT)
        reg_amt = self.rules_table.cellWidget(row, COL_REG_AMT)
        sale_cb = self.rules_table.cellWidget(row, COL_SALE_ON).findChild(QCheckBox)
        sale_list = self.rules_table.cellWidget(row, COL_SALE_LIST)
        sale_pct = self.rules_table.cellWidget(row, COL_SALE_PCT)
        sale_amt = self.rules_table.cellWidget(row, COL_SALE_AMT)
        return {
            "regular_index": int(reg_list.currentData()) if int(reg_list.currentData() or -1) >= 0 else None,
            "regular_markup_percent": float(reg_pct.value()),
            "regular_markup_amount": float(reg_amt.value()),
            "sale_enabled": sale_cb.isChecked(),
            "sale_index": int(sale_list.currentData()) if int(sale_list.currentData() or -1) >= 0 else None,
            "sale_markup_percent": float(sale_pct.value()),
            "sale_markup_amount": float(sale_amt.value()),
        }

    def _save_row(self, actions_widget: QWidget):
        row = self._row_for_actions_widget(actions_widget)
        if row < 0:
            return
        target_combo = self.rules_table.cellWidget(row, COL_TARGET)
        target = self._parse_target(target_combo.currentData())
        if not target:
            QMessageBox.warning(self, "توجه", "یک دسته‌بندی یا برند از ستونِ اول انتخاب کنید.")
            return
        kind, entity_id = target
        record = self._collect_row_record(row)
        from sync_app.core.site_taxonomy_price_list import set_brand_price_settings, set_category_price_settings

        if kind == "category":
            set_category_price_settings(entity_id, record)
        else:
            set_brand_price_settings(entity_id, record)
        self.config = load_secure_config(None) or {}
        self.status_label.setText(f"✅ ذخیره شد: {target_combo.currentText()}")

    def _delete_row(self, actions_widget: QWidget):
        row = self._row_for_actions_widget(actions_widget)
        if row < 0:
            return
        target_combo = self.rules_table.cellWidget(row, COL_TARGET)
        target = self._parse_target(target_combo.currentData())
        if target:
            answer = QMessageBox.question(
                self, "حذف", "این قاعده حذف بشه؟", QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            kind, entity_id = target
            from sync_app.core.site_taxonomy_price_list import (
                delete_brand_price_settings,
                delete_category_price_settings,
            )

            if kind == "category":
                delete_category_price_settings(entity_id)
            else:
                delete_brand_price_settings(entity_id)
            self.config = load_secure_config(None) or {}
        self.rules_table.removeRow(row)

    # ------------------------------------------------------------------
    def _refresh_rules_table(self):
        from sync_app.core.site_taxonomy_price_list import list_brand_price_settings, list_category_price_settings

        self.rules_table.setRowCount(0)
        for cid_str, record in list_category_price_settings(self.config).items():
            self._add_row(kind="category", entity_id=int(cid_str), record=record)
        for bid_str, record in list_brand_price_settings(self.config).items():
            self._add_row(kind="brand", entity_id=int(bid_str), record=record)

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
        self.status_label.setText(
            f"✅ {len(self._categories)} دسته‌بندی و {len(self._brands)} برند از سایت دریافت شد."
        )
        self._refresh_rules_table()

    # ------------------------------------------------------------------
    def ensure_tab_data_loaded(self):
        if not self._categories and not self._brands:
            self._load_site_taxonomy()
