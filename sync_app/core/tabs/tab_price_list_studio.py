"""تبِ «لیستِ قیمت» — تنظیمِ لیستِ قیمتِ عادی/ویژه و مارک‌آپِ مخصوصِ هر
دسته‌بندی یا برندِ سایت (جدا از تبِ «دسته‌بندی و برند» تا اونجا شلوغ نشه).

هر محصولی که به یه دسته‌بندی/برند وصل باشه (چه با تبِ «دسته‌بندی و برند»
چه به‌صورتِ خودکار)، اگه اون دسته‌بندی/برند این‌جا لیستِ قیمت/مارک‌آپِ
مخصوصِ خودش رو داشته باشه، با سینکِ بعدی (دستی یا خودکار) همون رو می‌گیره —
اولویت روی لیستِ قیمتِ دژاوو/ERP و مارک‌آپِ سراسریِ تبِ تنظیمات داره، مگر
خودِ محصول override‌ِ شخصیِ خودش رو داشته باشه."""

from __future__ import annotations

import logging

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt

from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.tabs.tab_category_brand_studio import SiteTaxonomyLoader

log = logging.getLogger("SyncApp")


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
            "و برند»)، با سینکِ بعدی خودکار همینو می‌گیرن."
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
        root.addStretch(1)

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

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("لیستِ قیمتِ عادی:"))
        self.price_list_combo = QComboBox()
        self.price_list_combo.addItem("— بدونِ override (ارثِ خودکار) —", -1)
        for i in range(1, 11):
            self.price_list_combo.addItem(f"لیست قیمت {i}", i - 1)
        row1.addWidget(self.price_list_combo, 1)

        self.sale_enabled_cb = QCheckBox("قیمتِ ویژه:")
        row1.addWidget(self.sale_enabled_cb)
        self.sale_price_list_combo = QComboBox()
        self.sale_price_list_combo.addItem("— بدونِ override —", -1)
        for i in range(1, 11):
            self.sale_price_list_combo.addItem(f"لیست قیمت {i}", i - 1)
        row1.addWidget(self.sale_price_list_combo, 1)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("درصدِ افزایش/کاهشِ قیمت:"))
        self.markup_percent_spin = QDoubleSpinBox()
        self.markup_percent_spin.setRange(-90.0, 500.0)
        self.markup_percent_spin.setDecimals(1)
        self.markup_percent_spin.setSuffix(" %")
        row2.addWidget(self.markup_percent_spin)

        row2.addWidget(QLabel("مبلغِ ثابتِ افزایش/کاهش:"))
        self.markup_amount_spin = QDoubleSpinBox()
        self.markup_amount_spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        self.markup_amount_spin.setDecimals(0)
        row2.addWidget(self.markup_amount_spin)
        v.addLayout(row2)

        hint = QLabel(
            "درصد اول رویِ قیمتِ پایه اعمال می‌شه، بعد مبلغِ ثابت به نتیجه اضافه/کم می‌شه. "
            "اولویتِ نهایی: override رویِ خودِ محصول (اگه باشه) → همین تنظیماتِ دسته‌بندی/برند → "
            "لیستِ قیمتِ دژاوو/ERP → پیش‌فرضِ سراسریِ تبِ تنظیمات."
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

        clear_btn = QPushButton("🗑️ پاک‌کردنِ فیلدها")
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

    # ------------------------------------------------------------------
    def _clear_price_fields(self):
        self.price_list_combo.setCurrentIndex(0)
        self.sale_enabled_cb.setChecked(False)
        self.sale_price_list_combo.setCurrentIndex(0)
        self.markup_percent_spin.setValue(0)
        self.markup_amount_spin.setValue(0)

    def _load_price_fields_from_record(self, record: dict | None):
        self._clear_price_fields()
        if not record:
            return
        if record.get("regular_index") is not None:
            idx = self.price_list_combo.findData(int(record["regular_index"]))
            if idx >= 0:
                self.price_list_combo.setCurrentIndex(idx)
        self.sale_enabled_cb.setChecked(bool(record.get("sale_enabled")))
        if record.get("sale_index") is not None:
            idx = self.sale_price_list_combo.findData(int(record["sale_index"]))
            if idx >= 0:
                self.sale_price_list_combo.setCurrentIndex(idx)
        self.markup_percent_spin.setValue(float(record.get("markup_percent") or 0))
        self.markup_amount_spin.setValue(float(record.get("markup_amount") or 0))

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
            "sale_enabled": self.sale_enabled_cb.isChecked(),
            "sale_index": (
                int(self.sale_price_list_combo.currentData())
                if int(self.sale_price_list_combo.currentData() or -1) >= 0
                else None
            ),
            "markup_percent": float(self.markup_percent_spin.value()),
            "markup_amount": float(self.markup_amount_spin.value()),
        }

    def _save_price_settings_for_category(self):
        cid = self.category_combo.currentData()
        if not cid:
            QMessageBox.warning(self, "توجه", "یک دسته‌بندی از لیست انتخاب کنید.")
            return
        from sync_app.core.site_taxonomy_price_list import set_category_price_settings

        set_category_price_settings(cid, self._collect_price_record())
        self.config = load_secure_config(None) or {}
        QMessageBox.information(
            self, "ثبت شد",
            f"لیستِ قیمت/مارک‌آپ برایِ دسته‌بندیِ «{self.category_combo.currentText()}» ذخیره شد — "
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
        QMessageBox.information(
            self, "ثبت شد",
            f"لیستِ قیمت/مارک‌آپ برایِ برندِ «{self.brand_combo.currentText()}» ذخیره شد — "
            "این محصولات با سینکِ بعدی این قیمت رو می‌گیرن.",
        )

    # ------------------------------------------------------------------
    def ensure_tab_data_loaded(self):
        if self.category_combo.count() == 0 and self.brand_combo.count() == 0:
            self._load_site_taxonomy()
