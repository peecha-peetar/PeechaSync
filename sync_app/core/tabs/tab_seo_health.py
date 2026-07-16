"""تب گزارش سئو و سلامت سایت — بررسی کلی محصولات از روی داده‌ی زنده‌ی فروشگاه
(ووکامرس یا پرستاشاپ)."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
    QDialog, QDialogButtonBox, QTextEdit,
)
from PyQt5.QtCore import Qt

from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.threading_helper import run_in_thread
from sync_app.core.integrations.commerce_provider import is_prestashop, store_platform_label
from sync_app.core.wc_sync_helper import build_wcapi, apply_network_overrides, wc_call
from sync_app.core.seo_helper import (
    analyze_product_seo_live, apply_seo_fixes, analyze_ps_product_seo, apply_ps_seo_fixes,
)

PRODUCT_FIELDS = "id,name,short_description,description,images,categories,meta_data"

FIELD_LABELS = {
    "description": "توضیحات کامل محصول",
    "short_description": "توضیح کوتاه",
    "alt_text": "Alt تصویر",
    "meta_description": "متا دیسکریپشن",
    "seo_title": "عنوان سئو",
    "meta_keywords": "کلمات کلیدی",
}


class SeoHealthTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._row_bundles = {}  # row index -> (wc_id, bundle)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("🩺 سئو و سلامت سایت")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel("بررسی زنده‌ی محصولات فروشگاه از نظر عنوان، توضیحات، Alt، متا دیسکریپشن، کلمات کلیدی")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        self.caveat = QLabel()
        self.caveat.setWordWrap(True)
        self.caveat.setStyleSheet("color:#b45309; font-size:11px;")
        self._set_platform_caveat()
        outer.addWidget(self.caveat)

        top_row = QHBoxLayout()
        self.run_btn = QPushButton("🔍 اجرای بررسی سئو")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.clicked.connect(self._run_check)
        top_row.addWidget(self.run_btn)
        self.bulk_fix_btn = QPushButton("🔧 رفع خودکار همه‌ی موارد ناقص")
        self.bulk_fix_btn.setMinimumHeight(40)
        self.bulk_fix_btn.setToolTip(
            "برای همه‌ی محصولاتی که مورد ناقص دارند، پیشنهادهای خودکار (همون چیزی که "
            "تو دیالوگ تک‌تک می‌بینید) رو یک‌جا ارسال می‌کنه — بدون باز شدن دیالوگ جدا."
        )
        self.bulk_fix_btn.clicked.connect(self._bulk_fix_all)
        top_row.addWidget(self.bulk_fix_btn)
        self.select_all_cb = QCheckBox("انتخاب همه")
        self.select_all_cb.stateChanged.connect(self._toggle_select_all_rows)
        top_row.addWidget(self.select_all_cb)
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-weight:700;")
        top_row.addWidget(self.summary_label)
        top_row.addStretch()
        outer.addLayout(top_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "محصول", "امتیاز سئو", "موارد ناقص", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 34)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 40)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        outer.addWidget(self.table)

    def _set_platform_caveat(self):
        cfg = load_secure_config(None) or {}
        if is_prestashop(cfg):
            self.caveat.setText(
                "ℹ️ روی پرستاشاپ، فیلدهای «متا دیسکریپشن/عنوان سئو/کلمات کلیدی» فیلد بومی محصول "
                "هستند (نه متادیتای یک افزونه) — پس همیشه قابل‌اعتمادند. چک/رفع «Alt تصویر» برای "
                "پرستاشاپ در این نسخه پشتیبانی نمی‌شود."
            )
        else:
            self.caveat.setText(
                "⚠️ چک‌های متا (دیسکریپشن/عنوان سئو/کلمات کلیدی) فقط وقتی درست کار می‌کنند که افزونه‌ی "
                "سئوی سایت (Yoast/Rank Math) آن فیلدها را در REST API عمومی expose کرده باشد. اگر همیشه "
                "«ندارد» نشان می‌دهد ولی مطمئنید مقدار دارید، یعنی افزونه‌ی سایت آن را در API عمومی "
                "نمی‌گذارد — این یک محدودیت شناخته‌شده است، نه باگ."
            )

    def _toggle_select_all_rows(self, state):
        checked = bool(state)
        for cb in getattr(self, "_row_checkboxes", {}).values():
            if cb.isEnabled():
                cb.setChecked(checked)

    def _bulk_fix_all(self):
        selected_rows = {
            row for row, cb in getattr(self, "_row_checkboxes", {}).items()
            if cb.isEnabled() and cb.isChecked()
        }
        targets = []
        for row, (wc_id, bundle) in self._row_bundles.items():
            if selected_rows and row not in selected_rows:
                continue
            suggestions = bundle.get("suggestions") or {}
            if not suggestions:
                continue
            to_send = {
                key: text.strip()
                for key, text in suggestions.items()
                if text and text.strip() and (key != "alt_text" or bundle.get("has_image"))
            }
            if to_send:
                targets.append((row, wc_id, to_send, bundle.get("image_id"), bundle.get("missing_alt_image_ids"), bundle["name"]))

        if not targets:
            QMessageBox.information(self, "چیزی برای رفع نیست", "همه‌ی محصولات از نظر سئو کامل هستند.")
            return

        confirm = QMessageBox.question(
            self, "تأیید رفع دسته‌جمعی",
            f"{len(targets)} محصول با پیشنهادهای خودکار سئو اصلاح می‌شوند "
            "(دقیقاً همون پیشنهادهایی که تو دیالوگ تک‌تک می‌بینید). ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.bulk_fix_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        config = load_secure_config(None) or {}
        ps_mode = is_prestashop(config)
        results = {"ok": 0, "failed": 0, "failed_names": []}

        def _worker():
            updated_bundles = {}
            if ps_mode:
                from sync_app.core.ps_sync_helper import ps_get_product, ps_list_categories

                categories = ps_list_categories(config)
                cat_by_id = {int(c["id"]): c for c in categories if isinstance(c, dict) and c.get("id")}
                for i, (row, wc_id, to_send, _image_id, _extra_ids, name) in enumerate(targets, start=1):
                    self.summary_label.setText(f"⏳ در حال رفع {i}/{len(targets)}: {name}")
                    try:
                        apply_ps_seo_fixes(config, wc_id, to_send)
                        product = ps_get_product(config, wc_id)
                        cats = (product or {}).get("categories") or []
                        cat_id = int(cats[0].get("id") or 0) if cats and isinstance(cats[0], dict) else 0
                        category_name = str((cat_by_id.get(cat_id) or {}).get("name") or "")
                        updated_bundles[row] = (
                            wc_id, analyze_ps_product_seo(product or {}, category_name=category_name)
                        )
                        results["ok"] += 1
                    except Exception:
                        results["failed"] += 1
                        results["failed_names"].append(name)
                return updated_bundles

            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            for i, (row, wc_id, to_send, image_id, extra_image_ids, name) in enumerate(targets, start=1):
                self.summary_label.setText(f"⏳ در حال رفع {i}/{len(targets)}: {name}")
                try:
                    apply_seo_fixes(wcapi, config, wc_id, to_send, image_id, extra_image_ids)
                    resp = wcapi.get(f"products/{int(wc_id)}", params={"_fields": PRODUCT_FIELDS})
                    live = resp.json()
                    updated_bundles[row] = (wc_id, analyze_product_seo_live(live))
                    results["ok"] += 1
                except Exception:
                    results["failed"] += 1
                    results["failed_names"].append(name)
            return updated_bundles

        def _done(updated_bundles):
            for row, (wc_id, new_bundle) in updated_bundles.items():
                self._row_bundles[row] = (wc_id, new_bundle)
                self._fill_row(row, new_bundle)
            self.bulk_fix_btn.setEnabled(True)
            self.run_btn.setEnabled(True)
            msg = f"✅ {results['ok']} محصول اصلاح شد."
            if results["failed"]:
                msg += f"\n❌ {results['failed']} محصول ناموفق: {'، '.join(results['failed_names'][:6])}"
            QMessageBox.information(self, "رفع دسته‌جمعی انجام شد", msg)

        def _fail(msg):
            self.bulk_fix_btn.setEnabled(True)
            self.run_btn.setEnabled(True)
            QMessageBox.critical(self, "خطا", f"رفع دسته‌جمعی متوقف شد:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _run_check(self):
        config = load_secure_config(None) or {}
        self._set_platform_caveat()
        ps_mode = is_prestashop(config)
        store_configured = bool(config.get("PS_URL")) if ps_mode else bool(config.get("WC_URL"))
        if not store_configured:
            QMessageBox.warning(
                self, "تنظیمات ناقص",
                f"ابتدا آدرس سایت {store_platform_label(config)} را در تنظیمات وارد کنید.",
            )
            return

        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ در حال بررسی...")
        self.summary_label.setText("")

        def _worker():
            if ps_mode:
                return self._fetch_and_score_ps(config)
            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            return self._fetch_and_score(wcapi)

        def _done(rows):
            self.run_btn.setEnabled(True)
            self.run_btn.setText("🔍 اجرای بررسی سئو")
            self._fill_table(rows)

        def _fail(msg):
            self.run_btn.setEnabled(True)
            self.run_btn.setText("🔍 اجرای بررسی سئو")
            QMessageBox.critical(self, "خطا", f"بررسی سئو ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _fetch_and_score_ps(self, config):
        from sync_app.core.ps_sync_helper import ps_list_products, ps_list_categories

        categories = ps_list_categories(config)
        cat_by_id = {int(c["id"]): c for c in categories if isinstance(c, dict) and c.get("id")}

        rows = []
        for item in ps_list_products(config):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            cats = item.get("categories") or []
            cat_id = int(cats[0].get("id") or 0) if cats and isinstance(cats[0], dict) else 0
            category_name = str((cat_by_id.get(cat_id) or {}).get("name") or "")
            bundle = analyze_ps_product_seo(item, category_name=category_name)
            rows.append((item["id"], bundle))

        rows.sort(key=lambda r: r[1]["current_score"])
        return rows

    def _fetch_and_score(self, wcapi):
        rows = []
        page = 1
        while True:
            def _fetch(p=page):
                resp = wcapi.get(
                    "products",
                    params={"per_page": 50, "page": p, "status": "publish", "_fields": PRODUCT_FIELDS},
                )
                data = resp.json()
                if not isinstance(data, list):
                    raise RuntimeError(f"پاسخ نامعتبر محصولات: {data}")
                return data

            batch = wc_call(wcapi, f"دریافت محصولات صفحه {page}", _fetch, retries=1)
            if not batch:
                break

            for item in batch:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                bundle = analyze_product_seo_live(item)
                rows.append((item["id"], bundle))

            if len(batch) < 50:
                break
            page += 1

        rows.sort(key=lambda r: r[1]["current_score"])
        return rows

    def _fill_table(self, rows):
        self.table.setRowCount(0)
        self._row_bundles = {}
        self._row_checkboxes = {}
        if not rows:
            self.summary_label.setText("هیچ محصولی یافت نشد.")
            return

        scores = [b["current_score"] for _wc_id, b in rows]
        avg = round(sum(scores) / len(scores))
        weak = sum(1 for s in scores if s < 60)
        self.summary_label.setText(
            f"📊 {len(rows)} محصول | میانگین امتیاز سئو: {avg} | محصولات ضعیف (زیر ۶۰): {weak}"
        )

        for wc_id, bundle in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._row_bundles[row] = (wc_id, bundle)
            self._fill_row(row, bundle)

    def _fill_row(self, row, bundle):
        select_cb = QCheckBox()
        select_wrap = QWidget()
        select_layout = QHBoxLayout(select_wrap)
        select_layout.setContentsMargins(0, 0, 0, 0)
        select_layout.setAlignment(Qt.AlignCenter)
        select_layout.addWidget(select_cb)
        self.table.setCellWidget(row, 0, select_wrap)
        self._row_checkboxes = getattr(self, "_row_checkboxes", {})
        self._row_checkboxes[row] = select_cb

        self.table.setItem(row, 1, QTableWidgetItem(bundle["name"]))
        score = bundle["current_score"]
        score_item = QTableWidgetItem(str(score))
        if score >= 90:
            score_item.setForeground(Qt.darkGreen)
        elif score >= 60:
            score_item.setForeground(Qt.darkYellow)
        else:
            score_item.setForeground(Qt.red)
        self.table.setItem(row, 2, score_item)

        missing = [c.missing_label for c in bundle["checks"] if not c.ok]
        self.table.setItem(row, 3, QTableWidgetItem("، ".join(missing) if missing else "✅ کامل"))

        if bundle["suggestions"]:
            fix_btn = QPushButton("🔧")
            fix_btn.setToolTip("رفع نواقص این محصول")
            fix_btn.setFixedSize(30, 26)
            fix_btn.setStyleSheet("font-size:13px; padding:0px;")
            fix_btn.clicked.connect(lambda _=False, r=row: self._open_fix_dialog(r))
            self.table.setCellWidget(row, 4, fix_btn)
        else:
            select_cb.setEnabled(False)  # چیزی برای رفع نیست، انتخابش هم بی‌فایده‌ست
            self.table.setCellWidget(row, 4, None)
            self.table.setItem(row, 4, QTableWidgetItem("✅"))

    def _open_fix_dialog(self, row):
        wc_id, bundle = self._row_bundles.get(row, (None, None))
        if not wc_id or not bundle:
            return
        suggestions = bundle["suggestions"]
        if not suggestions:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"رفع موارد ناقص — {bundle['name']}")
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.resize(560, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"امتیاز فعلی: {bundle['current_score']}/100"))

        checkbox_map = {}
        edit_map = {}
        for field_key, suggested_text in suggestions.items():
            label_text = FIELD_LABELS.get(field_key, field_key)
            if field_key == "alt_text" and not bundle["has_image"]:
                label_text += " (تصویر ندارد — غیرفعال)"
            if field_key == "description":
                label_text += " — می‌توانید همینجا بنویسید یا پیست کنید (Ctrl+V)"
            cb = QCheckBox(label_text)
            enabled = field_key != "alt_text" or bundle["has_image"]
            cb.setEnabled(enabled)
            cb.setChecked(enabled)
            layout.addWidget(cb)
            edit = QTextEdit(suggested_text)
            edit.setMaximumHeight(160 if field_key == "description" else 55)
            layout.addWidget(edit)
            checkbox_map[field_key] = cb
            edit_map[field_key] = edit

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("📤 ارسال موارد تیک‌خورده")
        buttons.button(QDialogButtonBox.Cancel).setText("بستن")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        to_send = {
            key: edit_map[key].toPlainText().strip()
            for key, cb in checkbox_map.items()
            if cb.isChecked() and edit_map[key].toPlainText().strip()
        }
        if not to_send:
            return

        self._send_fix(row, wc_id, to_send, bundle.get("image_id"), bundle.get("missing_alt_image_ids"))

    def _send_fix(self, row, wc_id, to_send, image_id, extra_image_ids=None):
        config = load_secure_config(None) or {}
        ps_mode = is_prestashop(config)

        def _worker():
            if ps_mode:
                return self._apply_and_rescan_ps(config, wc_id, to_send)
            apply_network_overrides(config)
            wcapi = build_wcapi(config)
            apply_seo_fixes(wcapi, config, wc_id, to_send, image_id, extra_image_ids)
            resp = wcapi.get(f"products/{int(wc_id)}", params={"_fields": PRODUCT_FIELDS})
            live = resp.json()
            return analyze_product_seo_live(live)

        def _done(new_bundle):
            self._row_bundles[row] = (wc_id, new_bundle)
            self._fill_row(row, new_bundle)
            QMessageBox.information(self, "ارسال شد", f"امتیاز جدید: {new_bundle['current_score']}/100")

        def _fail(msg):
            QMessageBox.critical(self, "خطا", f"ارسال ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _apply_and_rescan_ps(self, config, product_id, to_send):
        from sync_app.core.ps_sync_helper import ps_get_product, ps_list_categories

        apply_ps_seo_fixes(config, product_id, to_send)
        product = ps_get_product(config, product_id)
        categories = ps_list_categories(config)
        cat_by_id = {int(c["id"]): c for c in categories if isinstance(c, dict) and c.get("id")}
        cats = (product or {}).get("categories") or []
        cat_id = int(cats[0].get("id") or 0) if cats and isinstance(cats[0], dict) else 0
        category_name = str((cat_by_id.get(cat_id) or {}).get("name") or "")
        return analyze_ps_product_seo(product or {}, category_name=category_name)
