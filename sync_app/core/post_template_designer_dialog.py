"""دیالوگِ «طراحِ قالبِ پست» — ویرایشگرِ فیلد-به-فیلدِ متنِ پست (نه عکس):
فیلدهای ثابت (نامِ محصول/قیمت/توضیح/لینک/آدرسِ سایت/تلفن/شبکه‌های
اجتماعی) یا متنِ دلخواه، هرکدوم با امکانِ Bold/Italic و افزودنِ خطِ
خالیِ قبلش؛ می‌شه فیلد اضافه/حذف/جابه‌جا کرد. پیش‌نمایشِ زنده روی یک
contextِ نمونه — دقیقاً همون HTML‌ی که به تلگرام/بله ارسال می‌شه.
خروجی یک دیکشنریِ «قالب» است که با post_template_store.py ذخیره می‌شه."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from sync_app.core.post_template_renderer import (
    FIELD_TYPE_LABELS,
    TEXT_ALIGN_LABELS,
    normalize_field,
    normalize_template,
    render_post_text,
)

_EMOJI_CHOICES = [
    ("🔥", "آتش/داغ"), ("✅", "تیک"), ("❌", "ضربدر"), ("⭐", "ستاره"), ("🎉", "جشن"),
    ("🎁", "هدیه"), ("📦", "بسته"), ("🚚", "ارسال"), ("💯", "صددرصد"), ("💰", "پول"),
    ("🏷️", "برچسبِ تخفیف"), ("🛍️", "خرید"), ("📱", "موبایل"), ("📸", "دوربین"), ("✨", "درخشش"),
    ("👍", "لایک"), ("❤️", "قلب"), ("😍", "عاشق"), ("🆕", "جدید"), ("⚡", "فوری"),
    ("🔔", "زنگ/اعلان"), ("📢", "اطلاعیه"), ("💬", "پیام"), ("🔗", "لینک"), ("🕒", "زمان"),
    ("📍", "مکان"), ("🎯", "هدف"), ("✔️", "چک"), ("➡️", "فلشِ راست"), ("⬅️", "فلشِ چپ"),
    ("👇", "پایین"), ("👉", "اشاره‌ی راست"), ("🌟", "ستاره‌ی درخشان"), ("💎", "الماس"), ("🥇", "طلا"),
    ("🔵", "دایره‌ی آبی"), ("🟢", "دایره‌ی سبز"), ("🟡", "دایره‌ی زرد"), ("🔴", "دایره‌ی قرمز"), ("⚠️", "هشدار"),
]

_SAMPLE_CONTEXT = {
    "name": "نمونه محصول شما",
    "price": 1250000,
    "description": "این یک توضیحِ نمونه برای پیش‌نمایش است.",
    "permalink": "https://yourshop.com/product/sample",
    "site_address": "yourshop.com",
    "phone": "021-00000000",
    "social_instagram": "@yourshop",
    "social_telegram": "@yourshop_channel",
    "social_whatsapp": "0912-000-0000",
}


def _field_summary(field: dict) -> str:
    label = FIELD_TYPE_LABELS.get(field.get("type"), field.get("type"))
    if field.get("type") == "custom_text" and field.get("text"):
        label = f'{label}: {field["text"][:20]}'
    extras = []
    if field.get("bold"):
        extras.append("Bold")
    if field.get("italic"):
        extras.append("Italic")
    if field.get("align") and field.get("align") != "right":
        extras.append(TEXT_ALIGN_LABELS.get(field["align"], field["align"]))
    if field.get("blank_line_before"):
        extras.append("فاصله")
    extras_text = "، ".join(extras)
    return f"{label} ({extras_text})" if extras_text else label


class PostTemplateDesignerDialog(QDialog):
    def __init__(self, parent=None, *, template: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("🧩 طراحِ قالبِ متنِ پست")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(880, 560)

        self._template = normalize_template(template)
        self._fields = [dict(f) for f in self._template["fields"]]
        self._current_index = 0 if self._fields else -1
        self.saved_template: dict | None = None
        self._updating_panel = False

        root = QHBoxLayout(self)

        # --- پیش‌نمایش ---
        preview_col = QVBoxLayout()
        preview_col.addWidget(QLabel("پیش‌نمایشِ متنِ نهایی:"))
        self.preview_edit = QTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setLayoutDirection(Qt.RightToLeft)
        self.preview_edit.setStyleSheet("background:#f1f5f9;")
        preview_col.addWidget(self.preview_edit, 1)
        preview_hint = QLabel(
            "این پیش‌نمایش برای تلگرام است (Bold/Italic واقعاً اعمال می‌شه). "
            "بله فرمت‌بندی (Bold/Italic) رو رندر نمی‌کنه — همون قالب برای بله به‌صورتِ متنِ کاملاً ساده ارسال می‌شه."
        )
        preview_hint.setWordWrap(True)
        preview_hint.setStyleSheet("color:#64748b; font-size:10px;")
        preview_col.addWidget(preview_hint)
        root.addLayout(preview_col, 1)

        # --- ستونِ میانی: عنوان + لیستِ فیلدها ---
        mid_col = QVBoxLayout()
        form_top = QFormLayout()
        self.title_input = QLineEdit(str(self._template.get("title") or ""))
        form_top.addRow("عنوانِ قالب:", self.title_input)
        mid_col.addLayout(form_top)

        mid_col.addWidget(QLabel("فیلدهای متن (به‌ترتیبِ نمایش):"))
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

        text_row = QHBoxLayout()
        self.field_text_input = QLineEdit()
        self.field_text_input.setPlaceholderText("برای «متنِ دلخواه» الزامیه؛ برای بقیه اختیاریه")
        self.field_text_input.textChanged.connect(self._on_panel_changed)
        text_row.addWidget(self.field_text_input, 1)
        self.field_emoji_btn = QPushButton("😀 ایموجی")
        self.field_emoji_btn.setToolTip("درجِ ایموجی در متنِ این فیلد")
        self.field_emoji_btn.setFixedWidth(90)
        self.field_emoji_btn.clicked.connect(self._open_emoji_menu)
        text_row.addWidget(self.field_emoji_btn)
        panel_form.addRow("متن / مقدارِ دستی:", text_row)

        text_hint = QLabel(
            "برای «متنِ دلخواه» این جعبه همون متنه. برای «لینکِ محصول»، این متن به‌جای نمایشِ خودِ آدرسِ طولانی، "
            "به‌عنوانِ برچسبِ لینک نشون داده می‌شه (مثلاً «لینکِ سفارش از سایت») — در تلگرام واقعاً همون برچسب "
            "قابلِ‌کلیک می‌شه؛ در بله چون HTML نداره، برچسب قبل از خودِ لینک میاد. برای بقیه‌ی فیلدها (تلفن/"
            "اینستاگرام/توضیح/...) اگه اینجا چیزی بنویسید همون استفاده می‌شه؛ اگه خالی بمونه، خودکار از «تنظیمات "
            "→ اطلاعاتِ تماس و برندینگ» یا اطلاعاتِ واقعیِ محصول پر می‌شه."
        )
        text_hint.setWordWrap(True)
        text_hint.setStyleSheet("color:#94a3b8; font-size:9px;")
        panel_form.addRow("", text_hint)

        self.field_bold_check = QCheckBox("ضخیم (Bold)")
        self.field_bold_check.stateChanged.connect(self._on_panel_changed)
        panel_form.addRow("", self.field_bold_check)

        self.field_italic_check = QCheckBox("کج (Italic)")
        self.field_italic_check.stateChanged.connect(self._on_panel_changed)
        panel_form.addRow("", self.field_italic_check)

        self.field_align_combo = QComboBox()
        for key, label in TEXT_ALIGN_LABELS.items():
            self.field_align_combo.addItem(label, key)
        self.field_align_combo.currentIndexChanged.connect(self._on_panel_changed)
        panel_form.addRow("چیدمان:", self.field_align_combo)

        align_hint = QLabel(
            "«راست»/«چپ» جهتِ واقعیِ متن رو کنترل می‌کنن (مفید برای لینک/تلفنِ لاتین وسطِ متنِ فارسی)؛ "
            "«وسط» چون هیچ اپِ پیام‌رسانی (نه تلگرام، نه بله) وسط‌چینیِ واقعی نداره، فقط یک تلاشِ تقریبیه."
        )
        align_hint.setWordWrap(True)
        align_hint.setStyleSheet("color:#94a3b8; font-size:9px;")
        panel_form.addRow("", align_hint)

        self.field_blank_line_check = QCheckBox("یک خطِ خالی قبل از این فیلد")
        self.field_blank_line_check.stateChanged.connect(self._on_panel_changed)
        panel_form.addRow("", self.field_blank_line_check)

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
                self.field_type_combo, self.field_text_input, self.field_emoji_btn,
                self.field_bold_check, self.field_italic_check,
                self.field_align_combo, self.field_blank_line_check,
            ):
                w.setEnabled(enabled)
            if not field:
                return
            idx = self.field_type_combo.findData(field.get("type"))
            self.field_type_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.field_text_input.setText(str(field.get("text") or ""))
            self.field_bold_check.setChecked(bool(field.get("bold")))
            self.field_italic_check.setChecked(bool(field.get("italic")))
            align_idx = self.field_align_combo.findData(field.get("align", "right"))
            self.field_align_combo.setCurrentIndex(align_idx if align_idx >= 0 else 0)
            self.field_blank_line_check.setChecked(bool(field.get("blank_line_before")))
        finally:
            self._updating_panel = False

    def _on_panel_changed(self, *_args):
        if self._updating_panel or self._current_index < 0 or self._current_index >= len(self._fields):
            return
        field = self._fields[self._current_index]
        field["type"] = self.field_type_combo.currentData()
        field["text"] = self.field_text_input.text()
        field["bold"] = self.field_bold_check.isChecked()
        field["italic"] = self.field_italic_check.isChecked()
        field["align"] = self.field_align_combo.currentData()
        field["blank_line_before"] = self.field_blank_line_check.isChecked()
        self.field_list.item(self._current_index).setText(_field_summary(field))
        self._refresh_preview()

    def _open_emoji_menu(self):
        menu = QMenu(self)
        menu.setLayoutDirection(Qt.RightToLeft)
        for emoji, label in _EMOJI_CHOICES:
            action = menu.addAction(f"{emoji}  {label}")
            action.triggered.connect(lambda _=False, e=emoji: self._insert_emoji(e))
        menu.exec_(QCursor.pos())

    def _insert_emoji(self, emoji: str):
        self.field_text_input.insert(emoji)

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

    def _current_template_fields(self) -> dict:
        return {
            "title": self.title_input.text().strip(),
            "fields": [dict(f) for f in self._fields],
        }

    def _refresh_preview(self):
        template = normalize_template(self._current_template_fields())
        rendered = render_post_text(_SAMPLE_CONTEXT, template)
        html_preview = rendered.replace("\n", "<br>") or "<i style='color:#94a3b8'>(هیچ فیلدی مقدار نداره)</i>"
        self.preview_edit.setHtml(html_preview)

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
