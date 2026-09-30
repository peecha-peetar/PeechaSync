"""دیالوگِ لینکِ دستیِ مقدارهایِ ویژگی — برایِ وقتی مقدارِ یک ویژگی در
دیتابیس (ERP) با نامِ متفاوتی نسبت به همون مقدار در فروشگاه نوشته شده
(مثلاً ERP «سرخ»، فروشگاه «قرمز» یا «Red») و تطبیقِ خودکار (که فقط
متنِ دقیقاً یکسان را می‌شناسد) نمی‌تواند این دو را یکی تشخیص دهد.

کاربر این‌جا صریحاً می‌گوید «این مقدارِ ERP دقیقاً همین termِ فروشگاهه»
— از سینکِ بعدی، همیشه همون term استفاده می‌شه (نه ساختِ تکراری، نه
تغییرِ نامِ اشتباهِ یک termِ نامرتبط)."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _match_key(text) -> str:
    from sync_app.core.attribute_value_links import _key

    return _key(text)


def _find_site_attr_match(erp_name: str, site_attr_names) -> str | None:
    target = _match_key(erp_name)
    if not target:
        return None
    for name in site_attr_names:
        if _match_key(name) == target:
            return name
    for name in site_attr_names:
        k = _match_key(name)
        if k and (target in k or k in target):
            return name
    return None


class _LoadWorker(QThread):
    done = pyqtSignal(dict, dict, str)  # erp_attrs, site_attrs, error

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            erp_attrs, site_attrs = self._load()
            self.done.emit(erp_attrs, site_attrs, "")
        except Exception as exc:
            self.done.emit({}, {}, str(exc))

    def _load(self):
        from sync_app.core.scripts.Poshakproperties import (
            fetch_poshak_properties_rows,
            process_data_for_woocommerce,
        )

        raw_rows, cnxn = fetch_poshak_properties_rows(self.cfg)
        try:
            erp_attrs_raw = process_data_for_woocommerce(raw_rows)
        finally:
            try:
                cnxn.close()
            except Exception:
                pass
        erp_attrs = {name: sorted(values) for name, values in erp_attrs_raw.items() if values}

        from sync_app.core.integrations.commerce_provider import is_prestashop

        site_attrs: dict[str, list[str]] = {}
        if is_prestashop(self.cfg):
            from sync_app.core.ps_variation_helper import (
                ps_list_attribute_groups,
                ps_list_attribute_values,
            )

            for group in ps_list_attribute_groups(self.cfg):
                name = str(group.get("name") or "").strip()
                if not name:
                    continue
                values = ps_list_attribute_values(self.cfg, group["id"])
                site_attrs[name] = sorted({str(v.get("name") or "").strip() for v in values if v.get("name")})
        else:
            from sync_app.core.scripts.Poshakproperties import (
                _fetch_attribute_terms,
                _fetch_wc_attributes,
                create_wcapi,
            )

            verify_ssl = bool(self.cfg.get("WC_VERIFY_SSL", False))
            wcapi = create_wcapi(self.cfg, verify_ssl=verify_ssl)
            for attr in _fetch_wc_attributes(wcapi):
                name = str(attr.get("name") or "").strip()
                if not name or not attr.get("id"):
                    continue
                terms = _fetch_attribute_terms(wcapi, attr["id"])
                site_attrs[name] = sorted({
                    str(t.get("name") or "").strip() for t in terms if isinstance(t, dict) and t.get("name")
                })

        return erp_attrs, site_attrs


class AttributeValueLinkDialog(QDialog):
    """انتخابِ یک ویژگی، دیدنِ مقدارهایِ ERPِ آن، و لینکِ دستیِ هرکدام به
    یک termِ موجودِ فروشگاه (یا حذفِ لینکِ قبلی)."""

    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.setWindowTitle("تطبیقِ دستیِ مقدارهایِ ویژگی")
        self.resize(760, 560)
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = config or {}
        self._erp_attrs: dict[str, list[str]] = {}
        self._site_attrs: dict[str, list[str]] = {}

        root = QVBoxLayout(self)

        hint = QLabel(
            "وقتی مقدارِ یک ویژگی در نرم‌افزار و فروشگاه هم‌معنی ولی هم‌نویسه "
            "نیستن (مثلاً «سرخ» در نرم‌افزار و «قرمز» در فروشگاه)، این‌جا "
            "می‌تونید صریحاً بگید کدوم مقدارِ ERP دقیقاً معادلِ کدوم termِ "
            "فروشگاهه — از سینکِ بعدی، این تطبیقِ دستی همیشه رعایت می‌شه."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        root.addWidget(hint)

        top_row = QHBoxLayout()
        attr_label = QLabel("ویژگی:")
        self.attr_combo = QComboBox()
        self.attr_combo.setLayoutDirection(Qt.RightToLeft)
        self.attr_combo.setMinimumWidth(220)
        self.attr_combo.currentIndexChanged.connect(self._render_values_table)
        top_row.addWidget(attr_label)
        top_row.addWidget(self.attr_combo)
        top_row.addStretch(1)
        self.reload_btn = QPushButton("🔄 بازخوانی")
        self.reload_btn.clicked.connect(self._start_load)
        top_row.addWidget(self.reload_btn)
        root.addLayout(top_row)

        self.status_label = QLabel("در حالِ بارگذاریِ ویژگی‌ها از نرم‌افزار و فروشگاه…")
        self.status_label.setStyleSheet("color:#64748b; font-size:11px;")
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["مقدارِ ERP", "وضعیت", "termِ فروشگاه", "اقدام"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 120)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        root.addWidget(self.table, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("بستن")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

        self._worker = None
        self._start_load()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)

    def _start_load(self):
        self.status_label.setText("در حالِ بارگذاریِ ویژگی‌ها از نرم‌افزار و فروشگاه…")
        self.reload_btn.setEnabled(False)
        self.table.setRowCount(0)
        self._worker = _LoadWorker(self.config)
        self._worker.done.connect(self._on_loaded)
        self._worker.start()

    def _on_loaded(self, erp_attrs: dict, site_attrs: dict, error: str):
        self.reload_btn.setEnabled(True)
        if error:
            self.status_label.setText(f"❌ خطا در بارگذاری: {error}")
            QMessageBox.warning(self, "خطا", f"بارگذاریِ ویژگی‌ها ناموفق بود:\n{error}")
            return

        self._erp_attrs = erp_attrs
        self._site_attrs = site_attrs

        if not erp_attrs:
            self.status_label.setText("هیچ ویژگی‌ای در نرم‌افزار پیدا نشد.")
            return

        self.status_label.setText(
            f"{len(erp_attrs)} ویژگی در نرم‌افزار، {len(site_attrs)} ویژگی در فروشگاه."
        )

        current = self.attr_combo.currentData()
        self.attr_combo.blockSignals(True)
        self.attr_combo.clear()
        for name in sorted(erp_attrs.keys()):
            self.attr_combo.addItem(name, name)
        self.attr_combo.blockSignals(False)

        restored = False
        if current:
            idx = self.attr_combo.findData(current)
            if idx >= 0:
                self.attr_combo.setCurrentIndex(idx)
                restored = True
        if not restored and self.attr_combo.count():
            self.attr_combo.setCurrentIndex(0)

        self._render_values_table()

    def _render_values_table(self):
        self.table.setRowCount(0)
        attr_name = self.attr_combo.currentData()
        if not attr_name:
            return

        from sync_app.core.attribute_value_links import list_value_links_for_attr

        erp_values = self._erp_attrs.get(attr_name) or []
        site_attr_name = _find_site_attr_match(attr_name, self._site_attrs.keys())
        site_values = self._site_attrs.get(site_attr_name, []) if site_attr_name else []
        site_keys = {_match_key(v): v for v in site_values}
        links = list_value_links_for_attr(attr_name)

        if not site_attr_name:
            self.status_label.setText(
                f"⚠️ ویژگیِ «{attr_name}» هنوز در فروشگاه نیست — اول از تبِ «ویژگی‌ها» سینکش کنید."
            )

        self.table.setRowCount(len(erp_values))
        for row, erp_value in enumerate(erp_values):
            erp_item = QTableWidgetItem(erp_value)
            erp_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 0, erp_item)

            link_entry = links.get(_match_key(erp_value))
            exact_hit = site_keys.get(_match_key(erp_value))

            if exact_hit:
                status_text = "✅ از قبل یکسان"
            elif link_entry:
                status_text = f"🔗 لینک‌شده: {link_entry.get('wc_label', '')}"
            else:
                status_text = "⚠️ نامنطبق"
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 1, status_item)

            combo = QComboBox()
            combo.setLayoutDirection(Qt.RightToLeft)
            combo.addItem("— بدونِ لینک —", "")
            current_index = 0
            for i, sv in enumerate(site_values, start=1):
                combo.addItem(sv, sv)
                if link_entry and link_entry.get("wc_label") == sv:
                    current_index = i
            combo.setCurrentIndex(current_index)
            combo.setEnabled(bool(site_values))
            self.table.setCellWidget(row, 2, combo)

            action_btn = QPushButton("ذخیره")
            action_btn.clicked.connect(
                lambda _=False, r=row, a=attr_name, v=erp_value: self._save_row(r, a, v)
            )
            action_cell = QWidget()
            action_layout = QHBoxLayout(action_cell)
            action_layout.setContentsMargins(4, 0, 4, 0)
            action_layout.addWidget(action_btn)
            self.table.setCellWidget(row, 3, action_cell)

        self.table.resizeRowsToContents()

    def _save_row(self, row: int, attr_name: str, erp_value: str):
        from sync_app.core.attribute_value_links import remove_value_link, set_value_link

        combo = self.table.cellWidget(row, 2)
        chosen = combo.currentData() if isinstance(combo, QComboBox) else ""
        if chosen:
            set_value_link(attr_name, erp_value, chosen)
        else:
            remove_value_link(attr_name, erp_value)
        self._render_values_table()
