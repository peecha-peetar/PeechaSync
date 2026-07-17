"""دیالوگِ «طراحِ قالبِ پست» — ویرایشگرِ فیلد به فیلدِ کارتِ متنی: هر فیلد
(نامِ محصول/قیمت/توضیح/لینک/آدرسِ سایت/تلفن/شبکه‌های اجتماعی/متنِ دلخواه)
اندازه‌فونت، رنگ، ضخامت، چیدمان و فاصله‌ی خودش رو داره؛ می‌شه فیلد
اضافه/حذف/جابه‌جا کرد. پیش‌نمایش با یک contextِ نمونه زنده به‌روز می‌شه.
خروجی یک دیکشنریِ «قالب» است که با post_template_store.py ذخیره می‌شه."""

from __future__ import annotations

import os
import tempfile

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
)

from sync_app.core.post_template_renderer import (
    FIELD_TYPE_LABELS,
    TEXT_ALIGN_LABELS,
    normalize_field,
    normalize_template,
    render_post_template,
)

_SAMPLE_CONTEXT = {
    "name": "نمونه محصول شما",
    "price": 1250000,
    "description": "این یک توضیحِ نمونه برای پیش‌نمایش است — می‌تونه چند خط بشه.",
    "permalink": "https://yourshop.com/product/sample",
    "site_address": "yourshop.com",
    "phone": "021-00000000",
    "social_instagram": "@yourshop",
    "social_telegram": "@yourshop_channel",
    "social_whatsapp": "0912-000-0000",
}


def _color_button(initial_rgb: list) -> QPushButton:
    btn = QPushButton()
    btn.setFixedWidth(60)
    btn.setMinimumHeight(28)
    _apply_button_color(btn, initial_rgb)
    return btn


def _apply_button_color(btn: QPushButton, rgb: list) -> None:
    r, g, b = (int(c) for c in rgb)
    btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #94a3b8;")
    btn.setProperty("rgb", [r, g, b])


def _field_summary(field: dict) -> str:
    label = FIELD_TYPE_LABELS.get(field.get("type"), field.get("type"))
    if field.get("type") == "custom_text" and field.get("text"):
        label = f'{label}: {field["text"][:20]}'
    extras = []
    if field.get("bold"):
        extras.append("Bold")
    extras.append(TEXT_ALIGN_LABELS.get(field.get("align"), ""))
    extras_text = "، ".join(e for e in extras if e)
    return f"{label} ({extras_text})" if extras_text else label


class PostTemplateDesignerDialog(QDialog):
    def __init__(self, parent=None, *, template: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("🎨 طراحِ قالبِ پست")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(940, 640)

        self._template = normalize_template(template)
        self._fields = [dict(f) for f in self._template["fields"]]
        self._current_index = 0 if self._fields else -1
        self._preview_tmp_dir = tempfile.mkdtemp(prefix="peecha_template_preview_")
        self.saved_template: dict | None = None
        self._updating_panel = False

        root = QHBoxLayout(self)

        # --- پیش‌نمایش (اسکرول‌شونده چون ارتفاعِ کارت داینامیکه) ---
        preview_col = QVBoxLayout()
        preview_col.addWidget(QLabel("پیش‌نمایشِ زنده:"))
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFixedWidth(340)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.preview_label.setStyleSheet("background:#f1f5f9;")
        self.preview_scroll.setWidget(self.preview_label)
        preview_col.addWidget(self.preview_scroll, 1)
        root.addLayout(preview_col)

        # --- ستونِ میانی: عنوان + رنگِ زمینه + لیستِ فیلدها ---
        mid_col = QVBoxLayout()
        form_top = QFormLayout()
        self.title_input = QLineEdit(str(self._template.get("title") or ""))
        form_top.addRow("عنوانِ قالب:", self.title_input)
        self.bg_color_btn = _color_button(self._template.get("bg_color") or [255, 255, 255])
        self.bg_color_btn.clicked.connect(lambda: self._pick_color(self.bg_color_btn, refresh_only=True))
        form_top.addRow("رنگِ زمینه‌ی کارت:", self.bg_color_btn)
        mid_col.addLayout(form_top)

        mid_col.addWidget(QLabel("فیلدهای کارت (به‌ترتیبِ نمایش):"))
        self.field_list = QListWidget()
        self.field_list.currentRowChanged.connect(self._on_field_selected)
        mid_col.addWidget(self.field_list, 1)

        field_btns_row = QHBoxLayout()
        add_field_btn = QPushButton("➕ فیلدِ جدید")
        add_field_btn.clicked.connect(self._add_field)
        field_btns_row.addWidget(add_field_btn)
        remove_field_btn = QPushButton("🗑 حذف")
        remove_field_btn.clicked.connect(self._remove_field)
        field_btns_row.addWidget(remove_field_btn)
        up_btn = QPushButton("⬆")
        up_btn.setFixedWidth(36)
        up_btn.clicked.connect(lambda: self._move_field(-1))
        field_btns_row.addWidget(up_btn)
        down_btn = QPushButton("⬇")
        down_btn.setFixedWidth(36)
        down_btn.clicked.connect(lambda: self._move_field(1))
        field_btns_row.addWidget(down_btn)
        mid_col.addLayout(field_btns_row)

        root.addLayout(mid_col, 1)

        # --- ستونِ راست: ویرایشِ فیلدِ انتخاب‌شده ---
        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("تنظیماتِ فیلدِ انتخاب‌شده:"))
        panel_form = QFormLayout()

        self.field_type_combo = QComboBox()
        for key, label in FIELD_TYPE_LABELS.items():
            self.field_type_combo.addItem(label, key)
        self.field_type_combo.currentIndexChanged.connect(self._on_panel_changed)
        panel_form.addRow("نوعِ فیلد:", self.field_type_combo)

        self.field_text_input = QLineEdit()
        self.field_text_input.setPlaceholderText("فقط برای «متنِ دلخواه» استفاده می‌شه")
        self.field_text_input.textChanged.connect(self._on_panel_changed)
        panel_form.addRow("متن (برای متنِ دلخواه):", self.field_text_input)

        self.field_color_btn = _color_button([30, 30, 30])
        self.field_color_btn.clicked.connect(lambda: self._pick_color(self.field_color_btn))
        panel_form.addRow("رنگِ متن:", self.field_color_btn)

        self.field_size_slider = QSlider(Qt.Horizontal)
        self.field_size_slider.setRange(2, 10)
        self.field_size_slider.valueChanged.connect(self._on_panel_changed)
        panel_form.addRow("اندازه‌ی فونت (٪):", self.field_size_slider)

        self.field_bold_check = QCheckBox("ضخیم (Bold)")
        self.field_bold_check.stateChanged.connect(self._on_panel_changed)
        panel_form.addRow("", self.field_bold_check)

        self.field_align_combo = QComboBox()
        for key, label in TEXT_ALIGN_LABELS.items():
            self.field_align_combo.addItem(label, key)
        self.field_align_combo.currentIndexChanged.connect(self._on_panel_changed)
        panel_form.addRow("چیدمان:", self.field_align_combo)

        self.field_spacing_slider = QSlider(Qt.Horizontal)
        self.field_spacing_slider.setRange(0, 10)
        self.field_spacing_slider.valueChanged.connect(self._on_panel_changed)
        panel_form.addRow("فاصله از فیلدِ قبلی (٪):", self.field_spacing_slider)

        right_col.addLayout(panel_form)
        right_col.addStretch()

        actions_row = QHBoxLayout()
        actions_row.addStretch()
        cancel_btn = QPushButton("انصراف")
        cancel_btn.clicked.connect(self.reject)
        actions_row.addWidget(cancel_btn)
        save_btn = QPushButton("💾 ذخیره قالب")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        actions_row.addWidget(save_btn)
        right_col.addLayout(actions_row)

        root.addLayout(right_col, 1)

        self._reload_field_list(select_index=self._current_index)
        self._refresh_preview()

    # ------------------------------------------------------------------
    def _reload_field_list(self, *, select_index=-1):
        self.field_list.blockSignals(True)
        self.field_list.clear()
        for f in self._fields:
            self.field_list.addItem(_field_summary(f))
        self.field_list.blockSignals(False)
        if self._fields:
            idx = select_index if 0 <= select_index < len(self._fields) else 0
            self.field_list.setCurrentRow(idx)
        else:
            self._current_index = -1
            self._load_field_into_panel(None)

    def _on_field_selected(self, row: int):
        self._current_index = row
        field = self._fields[row] if 0 <= row < len(self._fields) else None
        self._load_field_into_panel(field)

    def _load_field_into_panel(self, field: dict | None):
        self._updating_panel = True
        try:
            enabled = field is not None
            for w in (
                self.field_type_combo, self.field_text_input, self.field_color_btn,
                self.field_size_slider, self.field_bold_check, self.field_align_combo,
                self.field_spacing_slider,
            ):
                w.setEnabled(enabled)
            if not field:
                return
            idx = self.field_type_combo.findData(field.get("type"))
            self.field_type_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.field_text_input.setText(str(field.get("text") or ""))
            _apply_button_color(self.field_color_btn, field.get("color") or [30, 30, 30])
            self.field_size_slider.setValue(int(float(field.get("font_size_pct", 0.04)) * 100))
            self.field_bold_check.setChecked(bool(field.get("bold")))
            align_idx = self.field_align_combo.findData(field.get("align"))
            self.field_align_combo.setCurrentIndex(align_idx if align_idx >= 0 else 0)
            self.field_spacing_slider.setValue(int(float(field.get("spacing_before_pct", 0.02)) * 100))
        finally:
            self._updating_panel = False

    def _on_panel_changed(self, *_args):
        if self._updating_panel or self._current_index < 0 or self._current_index >= len(self._fields):
            return
        field = self._fields[self._current_index]
        field["type"] = self.field_type_combo.currentData()
        field["text"] = self.field_text_input.text()
        field["color"] = self.field_color_btn.property("rgb")
        field["font_size_pct"] = self.field_size_slider.value() / 100.0
        field["bold"] = self.field_bold_check.isChecked()
        field["align"] = self.field_align_combo.currentData()
        field["spacing_before_pct"] = self.field_spacing_slider.value() / 100.0
        self.field_list.item(self._current_index).setText(_field_summary(field))
        self._refresh_preview()

    def _add_field(self):
        new_field = normalize_field({"type": "custom_text", "text": "متنِ جدید"})
        self._fields.append(new_field)
        self._reload_field_list(select_index=len(self._fields) - 1)
        self._refresh_preview()

    def _remove_field(self):
        if self._current_index < 0 or self._current_index >= len(self._fields):
            return
        del self._fields[self._current_index]
        self._reload_field_list(select_index=min(self._current_index, len(self._fields) - 1))
        self._refresh_preview()

    def _move_field(self, delta: int):
        i = self._current_index
        j = i + delta
        if i < 0 or j < 0 or j >= len(self._fields):
            return
        self._fields[i], self._fields[j] = self._fields[j], self._fields[i]
        self._reload_field_list(select_index=j)
        self._refresh_preview()

    def _pick_color(self, btn: QPushButton, *, refresh_only: bool = False):
        current = btn.property("rgb") or [0, 0, 0]
        color = QColorDialog.getColor(QColor(*current), self, "انتخابِ رنگ")
        if color.isValid():
            _apply_button_color(btn, [color.red(), color.green(), color.blue()])
            if refresh_only:
                self._refresh_preview()
            else:
                self._on_panel_changed()

    def _current_template_fields(self) -> dict:
        return {
            "title": self.title_input.text().strip(),
            "bg_color": self.bg_color_btn.property("rgb"),
            "fields": [dict(f) for f in self._fields],
        }

    def _refresh_preview(self):
        template = normalize_template(self._current_template_fields())
        dst = os.path.join(self._preview_tmp_dir, "preview.jpg")
        result = render_post_template(dst, _SAMPLE_CONTEXT, template)
        if not result.ok:
            self.preview_label.setText(f"خطا در پیش‌نمایش:\n{result.error}")
            self.preview_label.setPixmap(QPixmap())
            return
        pix = QPixmap(dst)
        if pix.isNull():
            return
        scaled = pix.scaledToWidth(320, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)
        self.preview_label.resize(scaled.size())

    def _save(self):
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "طراحِ قالب", "یک عنوان برای قالب وارد کنید.")
            return
        if not self._fields:
            QMessageBox.warning(self, "طراحِ قالب", "حداقل یک فیلد اضافه کنید.")
            return
        fields = self._current_template_fields()
        fields["title"] = title
        fields["id"] = self._template.get("id") or ""
        self.saved_template = normalize_template(fields)
        self.accept()
