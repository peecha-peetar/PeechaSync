"""تبِ «تطبیقِ ساختاری» — برایِ وقتی ساختارِ یک محصول رویِ سایت با ساختارش
در {ERP} یکی نیست:

۱) سایت محصولِ متغیر داره (چند واریانت)، ولی در {ERP} هر واریانت یک کالایِ
   سادهٔ مستقل تعریف شده — این‌جا مشخص می‌کنید کدوم SKUِ سادهٔ {ERP} در
   واقع کدوم واریانتِ کدوم محصولِ سایته؛ از این به بعد قیمت/موجودیِ اون
   SKU مستقیم رویِ همون واریانتِ سایت اعمال می‌شه، نه محصولِ جدا.

۲) {ERP} محصول رو متغیر (با چند زیرواریانت) می‌بینه، ولی رویِ سایت این
   یک محصولِ ساده‌ست — این‌جا مشخص می‌کنید کدوم زیرواریانتِ {ERP} به‌عنوانِ
   منبعِ قیمت/موجودیِ همون محصولِ سادهٔ سایت استفاده بشه؛ بقیهٔ زیرواریانت‌ها
   نادیده گرفته می‌شن و محصول به‌عنوانِ محصولِ متغیر سینک نمی‌شه."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.secure_config_loader import load_secure_config

log = logging.getLogger("SyncApp")


class _SiteVariationsLoader(QThread):
    """دریافتِ لیستِ واریانت‌هایِ یک محصولِ خاص از سایت (WC یا PS)."""

    done = pyqtSignal(list, str)  # [(id, label), ...], error

    def __init__(self, cfg, parent_product_id: int):
        super().__init__()
        self.cfg = cfg
        self.parent_product_id = parent_product_id

    def run(self):
        try:
            from sync_app.core.integrations.commerce_provider import is_prestashop

            pid = int(self.parent_product_id)
            if is_prestashop(self.cfg):
                from sync_app.core.ps_variation_helper import ps_list_combinations

                combos = ps_list_combinations(self.cfg, pid)
                out = [
                    (int(c["id"]), f"#{c['id']} — {c.get('reference') or 'بدونِ SKU'}")
                    for c in combos
                    if c.get("id")
                ]
            else:
                from sync_app.core.wc_sync_helper import apply_network_overrides, build_wcapi

                apply_network_overrides(self.cfg)
                wcapi = build_wcapi(self.cfg)
                resp = wcapi.get(f"products/{pid}/variations", params={"per_page": 100})
                data = resp.json()
                if not isinstance(data, list):
                    self.done.emit([], "پاسخِ نامعتبر از فروشگاه")
                    return
                out = []
                for v in data:
                    if not isinstance(v, dict) or not v.get("id"):
                        continue
                    attrs = "، ".join(
                        str(a.get("option") or "") for a in (v.get("attributes") or []) if a.get("option")
                    )
                    label = f"#{v['id']} — {v.get('sku') or attrs or 'بدونِ برچسب'}"
                    out.append((int(v["id"]), label))
            self.done.emit(out, "")
        except Exception as exc:
            self.done.emit([], str(exc))


class _ErpVariationsLoader(QThread):
    """دریافتِ زیرواریانت‌هایِ یک کدِ کالایِ متغیر مستقیم از دیتابیسِ ERP."""

    done = pyqtSignal(list, str)  # [(sku, label), ...], error

    def __init__(self, cfg, parent_sku: str):
        super().__init__()
        self.cfg = cfg
        self.parent_sku = parent_sku

    def run(self):
        try:
            from sync_app.core.sql_connection_helper import open_sql_connection
            from sync_app.core.scripts.update_variations import fetch_variations_from_db, _fetch_attribute_labels
            from sync_app.core.category_price_list import resolve_article_price_column

            conn, _, _ = open_sql_connection(self.cfg, timeout=10)
            try:
                cursor = conn.cursor()
                price_col = resolve_article_price_column(self.parent_sku, "", self.cfg)
                cursor.execute(
                    f"SELECT TOP 1 A_Code, A_Name, {price_col} FROM Article WHERE A_Code = ?",
                    (self.parent_sku,),
                )
                row = cursor.fetchone()
                cursor.close()
                if not row:
                    from sync_app.core.integrations.erp_provider import erp_provider_label

                    self.done.emit(
                        [], f"کدِ کالایِ «{self.parent_sku}» در {erp_provider_label(self.cfg)} پیدا نشد."
                    )
                    return
                raw_price = float(row[2] or 0)
                size_label, color_label, dim3_label = _fetch_attribute_labels(conn)
                variations, _attr_map = fetch_variations_from_db(
                    conn, self.parent_sku, raw_price, size_label, color_label, dim3_label, config=self.cfg,
                )
            finally:
                conn.close()
            out = []
            for v in variations or []:
                sku = str(v.get("sku") or "").strip()
                if not sku:
                    continue
                attrs = "، ".join(
                    str(a.get("option") or "") for a in (v.get("attributes") or []) if a.get("option")
                )
                out.append((sku, f"{sku} — {attrs}" if attrs else sku))
            if not out:
                self.done.emit([], f"زیرواریانتی برایِ «{self.parent_sku}» پیدا نشد.")
                return
            self.done.emit(out, "")
        except Exception as exc:
            self.done.emit([], str(exc))


class StructureReconciliationTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self._sv_loader = None
        self._fs_loader = None
        self.init_ui()
        self._refresh_sv_table()
        self._refresh_fs_table()

    # ------------------------------------------------------------------
    def _erp_label(self) -> str:
        from sync_app.core.integrations.erp_provider import erp_provider_label

        return erp_provider_label(self.config)

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        sub_tabs = QTabWidget()
        sub_tabs.setLayoutDirection(Qt.RightToLeft)
        sub_tabs.addTab(self._build_site_variation_section(), "🧩 سایت متغیر / ERP ساده")
        sub_tabs.addTab(self._build_force_simple_section(), "📦 ERP متغیر / سایت ساده")
        root.addWidget(sub_tabs)

    # ------------------------------------------------------------------
    # حالتِ ۱: سایت متغیر داره، ERP ساده می‌بینه
    # ------------------------------------------------------------------
    def _build_site_variation_section(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)

        erp_label = self._erp_label()
        hint = QLabel(
            f"سایت این محصول رو متغیر (با چند واریانت) نشون می‌ده، ولی در {erp_label} هر واریانت یک کالایِ "
            "سادهٔ جداست. یه SKUِ سادهٔ {erp} رو انتخاب کنید، شناسهٔ محصولِ والدِ سایت رو بدید، بعد از لیستِ "
            "واریانت‌هایِ همون محصول، واریانتِ درست رو انتخاب و ذخیره کنید — از این به بعد قیمت/موجودیِ این "
            "SKU مستقیم رویِ همون واریانت اعمال می‌شه، نه یک محصولِ جدا.".replace("{erp}", erp_label)
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        v.addWidget(hint)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(f"SKUِ سادهٔ {erp_label}:"))
        self.sv_sku_input = QLineEdit()
        self.sv_sku_input.setPlaceholderText("مثلاً 010203")
        row1.addWidget(self.sv_sku_input, 1)
        row1.addWidget(QLabel("شناسهٔ محصولِ والدِ سایت:"))
        self.sv_parent_id_spin = QSpinBox()
        self.sv_parent_id_spin.setRange(0, 999_999_999)
        row1.addWidget(self.sv_parent_id_spin)
        self.sv_fetch_btn = QPushButton("🔍 دریافتِ واریانت‌ها")
        self.sv_fetch_btn.clicked.connect(self._sv_fetch_variations)
        row1.addWidget(self.sv_fetch_btn)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("واریانتِ سایت:"))
        self.sv_variation_combo = QComboBox()
        self.sv_variation_combo.addItem("— اول «دریافتِ واریانت‌ها» را بزنید —", None)
        row2.addWidget(self.sv_variation_combo, 1)
        self.sv_save_btn = QPushButton("💾 ذخیرهٔ تطبیق")
        self.sv_save_btn.clicked.connect(self._sv_save)
        row2.addWidget(self.sv_save_btn)
        v.addLayout(row2)

        self.sv_status_label = QLabel("")
        self.sv_status_label.setStyleSheet("color:#64748b; font-size:12px;")
        v.addWidget(self.sv_status_label)

        self.sv_table = QTableWidget(0, 4)
        self.sv_table.setLayoutDirection(Qt.RightToLeft)
        self.sv_table.setHorizontalHeaderLabels(
            [f"SKUِ {erp_label}", "محصولِ والدِ سایت", "واریانتِ سایت", ""]
        )
        self.sv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.sv_table.verticalHeader().setVisible(False)
        v.addWidget(self.sv_table, 1)

        return panel

    def _sv_fetch_variations(self):
        pid = self.sv_parent_id_spin.value()
        if not pid:
            QMessageBox.warning(self, "توجه", "شناسهٔ محصولِ والدِ سایت را وارد کنید.")
            return
        self.sv_status_label.setText("⏳ در حالِ دریافتِ واریانت‌ها از سایت...")
        self._sv_loader = _SiteVariationsLoader(self.config, pid)
        self._sv_loader.done.connect(self._on_sv_variations_loaded)
        self._sv_loader.start()

    def _on_sv_variations_loaded(self, options, error):
        if error:
            self.sv_status_label.setText(f"⚠️ دریافتِ واریانت‌ها ناموفق بود: {error}")
            return
        self.sv_variation_combo.clear()
        self.sv_variation_combo.addItem("— انتخاب کنید —", None)
        for vid, label in options:
            self.sv_variation_combo.addItem(label, vid)
        self.sv_status_label.setText(f"✅ {len(options)} واریانت دریافت شد.")

    def _sv_save(self):
        sku = (self.sv_sku_input.text() or "").strip()
        pid = self.sv_parent_id_spin.value()
        vid = self.sv_variation_combo.currentData()
        if not sku:
            QMessageBox.warning(self, "توجه", f"SKUِ {self._erp_label()} را وارد کنید.")
            return
        if not pid or not vid:
            QMessageBox.warning(self, "توجه", "شناسهٔ محصولِ والد و واریانتِ سایت را مشخص کنید.")
            return
        from sync_app.core.structure_mismatch_override import set_site_variation_target

        set_site_variation_target(sku, pid, int(vid), label=self.sv_variation_combo.currentText())
        self.sv_sku_input.clear()
        self._refresh_sv_table()
        QMessageBox.information(self, "انجام شد", f"SKUِ «{sku}» به واریانتِ سایت وصل شد.")

    def _refresh_sv_table(self):
        from sync_app.core.structure_mismatch_override import list_site_variation_targets

        table = list_site_variation_targets()
        self.sv_table.setRowCount(0)
        for sku, entry in table.items():
            row = self.sv_table.rowCount()
            self.sv_table.insertRow(row)
            self.sv_table.setItem(row, 0, QTableWidgetItem(sku))
            self.sv_table.setItem(row, 1, QTableWidgetItem(str(entry.get("parent_product_id") or "")))
            variation_label = entry.get("label") or f"#{entry.get('variation_id')}"
            self.sv_table.setItem(row, 2, QTableWidgetItem(str(variation_label)))
            del_btn = QPushButton("🗑 حذف")
            del_btn.clicked.connect(lambda _checked=False, s=sku: self._sv_delete(s))
            self.sv_table.setCellWidget(row, 3, del_btn)

    def _sv_delete(self, sku: str):
        from sync_app.core.structure_mismatch_override import clear_site_variation_target

        clear_site_variation_target(sku)
        self._refresh_sv_table()

    # ------------------------------------------------------------------
    # حالتِ ۲: ERP متغیر می‌بینه، سایت ساده داره
    # ------------------------------------------------------------------
    def _build_force_simple_section(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)

        erp_label = self._erp_label()
        hint = QLabel(
            f"{erp_label} این کد کالا رو متغیر (با چند زیرواریانت) می‌بینه، ولی رویِ سایت این یک محصولِ "
            "ساده‌ست. کدِ کالایِ والد رو بدید، از لیستِ زیرواریانت‌هایِ همون کد، یکی رو به‌عنوانِ منبعِ قیمت/"
            "موجودیِ محصولِ سادهٔ سایت انتخاب کنید — بقیهٔ زیرواریانت‌ها نادیده گرفته می‌شن و محصول دیگه "
            "به‌عنوانِ محصولِ متغیر سینک نمی‌شه."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        v.addWidget(hint)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(f"کدِ کالایِ والدِ {erp_label}:"))
        self.fs_sku_input = QLineEdit()
        self.fs_sku_input.setPlaceholderText("مثلاً 0102")
        row1.addWidget(self.fs_sku_input, 1)
        self.fs_fetch_btn = QPushButton("🔍 دریافتِ زیرواریانت‌ها")
        self.fs_fetch_btn.clicked.connect(self._fs_fetch_variations)
        row1.addWidget(self.fs_fetch_btn)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("زیرواریانتِ منبع:"))
        self.fs_variation_combo = QComboBox()
        self.fs_variation_combo.addItem("— اول «دریافتِ زیرواریانت‌ها» را بزنید —", None)
        row2.addWidget(self.fs_variation_combo, 1)
        self.fs_save_btn = QPushButton("💾 ذخیرهٔ تطبیق")
        self.fs_save_btn.clicked.connect(self._fs_save)
        row2.addWidget(self.fs_save_btn)
        v.addLayout(row2)

        self.fs_status_label = QLabel("")
        self.fs_status_label.setStyleSheet("color:#64748b; font-size:12px;")
        v.addWidget(self.fs_status_label)

        self.fs_table = QTableWidget(0, 3)
        self.fs_table.setLayoutDirection(Qt.RightToLeft)
        self.fs_table.setHorizontalHeaderLabels([f"کدِ والدِ {erp_label}", "زیرواریانتِ منبع", ""])
        self.fs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.fs_table.verticalHeader().setVisible(False)
        v.addWidget(self.fs_table, 1)

        return panel

    def _fs_fetch_variations(self):
        sku = (self.fs_sku_input.text() or "").strip()
        if not sku:
            QMessageBox.warning(self, "توجه", f"کدِ کالایِ والدِ {self._erp_label()} را وارد کنید.")
            return
        self.fs_status_label.setText(f"⏳ در حالِ دریافتِ زیرواریانت‌ها از {self._erp_label()}...")
        self._fs_loader = _ErpVariationsLoader(self.config, sku)
        self._fs_loader.done.connect(self._on_fs_variations_loaded)
        self._fs_loader.start()

    def _on_fs_variations_loaded(self, options, error):
        if error:
            self.fs_status_label.setText(f"⚠️ {error}")
            return
        self.fs_variation_combo.clear()
        self.fs_variation_combo.addItem("— انتخاب کنید —", None)
        for sku, label in options:
            self.fs_variation_combo.addItem(label, sku)
        self.fs_status_label.setText(f"✅ {len(options)} زیرواریانت دریافت شد.")

    def _fs_save(self):
        sku = (self.fs_sku_input.text() or "").strip()
        source_sku = self.fs_variation_combo.currentData()
        if not sku:
            QMessageBox.warning(self, "توجه", f"کدِ کالایِ والدِ {self._erp_label()} را وارد کنید.")
            return
        if not source_sku:
            QMessageBox.warning(self, "توجه", "زیرواریانتِ منبع را انتخاب کنید.")
            return
        from sync_app.core.structure_mismatch_override import set_force_simple_source

        set_force_simple_source(sku, source_sku)
        self.fs_sku_input.clear()
        self._refresh_fs_table()
        QMessageBox.information(self, "انجام شد", f"محصولِ «{sku}» از این به بعد به‌عنوانِ محصولِ سادهٔ سایت سینک می‌شه.")

    def _refresh_fs_table(self):
        from sync_app.core.structure_mismatch_override import list_force_simple_sources

        table = list_force_simple_sources()
        self.fs_table.setRowCount(0)
        for sku, entry in table.items():
            row = self.fs_table.rowCount()
            self.fs_table.insertRow(row)
            self.fs_table.setItem(row, 0, QTableWidgetItem(sku))
            self.fs_table.setItem(row, 1, QTableWidgetItem(str(entry.get("source_variation_sku") or "")))
            del_btn = QPushButton("🗑 حذف")
            del_btn.clicked.connect(lambda _checked=False, s=sku: self._fs_delete(s))
            self.fs_table.setCellWidget(row, 2, del_btn)

    def _fs_delete(self, sku: str):
        from sync_app.core.structure_mismatch_override import clear_force_simple_source

        clear_force_simple_source(sku)
        self._refresh_fs_table()

    # ------------------------------------------------------------------
    def ensure_tab_data_loaded(self):
        pass
