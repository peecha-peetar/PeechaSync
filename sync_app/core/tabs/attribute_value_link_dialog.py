"""دیالوگِ لینکِ دستیِ مقدارهایِ ویژگی — برایِ وقتی مقدارِ یک ویژگی در
دیتابیس (ERP) با نامِ متفاوتی نسبت به همون مقدار در فروشگاه نوشته شده
(مثلاً ERP «سرخ»، فروشگاه «قرمز» یا «Red») و تطبیقِ خودکار (که فقط
متنِ دقیقاً یکسان را می‌شناسد) نمی‌تواند این دو را یکی تشخیص دهد.

مثلِ صفحه‌یِ اصلیِ «تطبیق»، مقدارهایِ نرم‌افزار و فروشگاه دو ستونِ کنارِ
هم هستن — کاربر یکی از هر طرف انتخاب می‌کنه و «🔗 لینک» می‌زنه؛ از
سینکِ بعدی، همیشه همون term استفاده می‌شه (نه ساختِ تکراری، نه تغییرِ
نامِ اشتباهِ یک termِ نامرتبط)."""

from __future__ import annotations

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from sync_app.core.rtl_item_delegate import RightAlignedItemDelegate


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
    """انتخابِ یک ویژگی، دیدنِ مقدارهایِ ERP در یک ستون و مقدارهایِ
    فروشگاه در ستونِ دیگر، و لینک/حذفِ‌لینکِ دستیِ نظیر‌به‌نظیر."""

    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.setWindowTitle("تطبیقِ دستیِ مقدارهایِ ویژگی")
        self.resize(780, 560)
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = config or {}
        self._erp_attrs: dict[str, list[str]] = {}
        self._site_attrs: dict[str, list[str]] = {}

        root = QVBoxLayout(self)

        hint = QLabel(
            "وقتی مقدارِ یک ویژگی در نرم‌افزار و فروشگاه هم‌معنی ولی هم‌نویسه "
            "نیستن (مثلاً «سرخ» در نرم‌افزار و «قرمز» در فروشگاه)، یکی از هر "
            "ستون رو انتخاب کنید و «🔗 لینک» بزنید — از سینکِ بعدی، این "
            "تطبیقِ دستی همیشه رعایت می‌شه."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#475569; font-size:12px;")
        root.addWidget(hint)

        top_row = QHBoxLayout()
        attr_label = QLabel("ویژگی:")
        self.attr_combo = QComboBox()
        self.attr_combo.setLayoutDirection(Qt.RightToLeft)
        self.attr_combo.setMinimumWidth(220)
        self.attr_combo.currentIndexChanged.connect(self._render_value_lists)
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

        # دقیقاً هم‌الگویِ صفحه‌یِ اصلیِ «تطبیق»: نرم‌افزار سمتِ چپ، فروشگاه
        # سمتِ راست (LeftToRight صریح، مستقل از راست‌چین‌بودنِ کلِ دیالوگ).
        lists_row = QHBoxLayout()
        lists_row.setDirection(QHBoxLayout.LeftToRight)

        erp_col = QVBoxLayout()
        erp_title = QLabel("🗄️ مقدارهایِ نرم‌افزار")
        erp_title.setAlignment(Qt.AlignRight)
        erp_col.addWidget(erp_title)
        self.erp_list = QListWidget()
        self.erp_list.setLayoutDirection(Qt.RightToLeft)
        self.erp_list.setMinimumHeight(280)
        self.erp_list.setSelectionMode(QListWidget.SingleSelection)
        self.erp_list.setItemDelegate(RightAlignedItemDelegate(self.erp_list))
        erp_col.addWidget(self.erp_list)
        lists_row.addLayout(erp_col, 1)

        mid_col = QVBoxLayout()
        mid_col.addStretch(1)
        self.link_btn = QPushButton("🔗 لینک")
        self.link_btn.setToolTip("مقدارِ انتخاب‌شده از هر دو ستون را به هم لینک می‌کند.")
        self.link_btn.clicked.connect(self._link_selected)
        mid_col.addWidget(self.link_btn)
        self.unlink_btn = QPushButton("❌ حذفِ لینک")
        self.unlink_btn.setToolTip("لینکِ دستیِ مقدارِ انتخاب‌شده از ستونِ نرم‌افزار را برمی‌دارد.")
        self.unlink_btn.clicked.connect(self._unlink_selected)
        mid_col.addWidget(self.unlink_btn)
        mid_col.addStretch(1)
        lists_row.addLayout(mid_col, 0)

        site_col = QVBoxLayout()
        site_title = QLabel("🛒 مقدارهایِ فروشگاه")
        site_title.setAlignment(Qt.AlignRight)
        site_col.addWidget(site_title)
        self.site_list = QListWidget()
        self.site_list.setLayoutDirection(Qt.RightToLeft)
        self.site_list.setMinimumHeight(280)
        self.site_list.setSelectionMode(QListWidget.SingleSelection)
        self.site_list.setItemDelegate(RightAlignedItemDelegate(self.site_list))
        site_col.addWidget(self.site_list)
        lists_row.addLayout(site_col, 1)

        root.addLayout(lists_row, 1)

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
        self.erp_list.clear()
        self.site_list.clear()
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

        self._render_value_lists()

    def _current_site_attr_name(self) -> str | None:
        attr_name = self.attr_combo.currentData()
        if not attr_name:
            return None
        return _find_site_attr_match(attr_name, self._site_attrs.keys())

    def _render_value_lists(self):
        self.erp_list.clear()
        self.site_list.clear()
        attr_name = self.attr_combo.currentData()
        if not attr_name:
            return

        from sync_app.core.attribute_value_links import list_value_links_for_attr

        erp_values = self._erp_attrs.get(attr_name) or []
        site_attr_name = self._current_site_attr_name()
        site_values = self._site_attrs.get(site_attr_name, []) if site_attr_name else []
        site_keys = {_match_key(v): v for v in site_values}
        links = list_value_links_for_attr(attr_name)

        if not site_attr_name:
            self.status_label.setText(
                f"⚠️ ویژگیِ «{attr_name}» هنوز در فروشگاه نیست — اول از تبِ «ویژگی‌ها» سینکش کنید."
            )
        else:
            self.status_label.setText(
                f"ویژگیِ فروشگاه: «{site_attr_name}» — {len(erp_values)} مقدارِ نرم‌افزار، "
                f"{len(site_values)} مقدارِ فروشگاه."
            )

        for erp_value in erp_values:
            link_entry = links.get(_match_key(erp_value))
            exact_hit = site_keys.get(_match_key(erp_value))
            if exact_hit:
                text = f"✅ {erp_value}"
                tooltip = "از قبل با همین نام روی فروشگاه هست — نیازی به لینکِ دستی نیست."
            elif link_entry:
                text = f"🔗 {erp_value}  ←  {link_entry.get('wc_label', '')}"
                tooltip = "لینکِ دستی — با «❌ حذفِ لینک» می‌تونید بردارید."
            else:
                text = f"⚠️ {erp_value}"
                tooltip = "نامنطبق — یک مقدار از ستونِ فروشگاه انتخاب کنید و «🔗 لینک» بزنید."
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, erp_value)
            item.setToolTip(tooltip)
            self.erp_list.addItem(item)

        for sv in site_values:
            item = QListWidgetItem(sv)
            item.setData(Qt.UserRole, sv)
            self.site_list.addItem(item)

    def _link_selected(self):
        attr_name = self.attr_combo.currentData()
        erp_item = self.erp_list.currentItem()
        site_item = self.site_list.currentItem()
        if not attr_name or not erp_item or not site_item:
            QMessageBox.information(
                self, "انتخاب نشده",
                "یک مقدار از ستونِ نرم‌افزار و یک مقدار از ستونِ فروشگاه انتخاب کنید.",
            )
            return

        from sync_app.core.attribute_value_links import set_value_link

        set_value_link(attr_name, erp_item.data(Qt.UserRole), site_item.data(Qt.UserRole))
        self._render_value_lists()

    def _unlink_selected(self):
        attr_name = self.attr_combo.currentData()
        erp_item = self.erp_list.currentItem()
        if not attr_name or not erp_item:
            QMessageBox.information(self, "انتخاب نشده", "یک مقدار از ستونِ نرم‌افزار انتخاب کنید.")
            return

        from sync_app.core.attribute_value_links import remove_value_link

        remove_value_link(attr_name, erp_item.data(Qt.UserRole))
        self._render_value_lists()
