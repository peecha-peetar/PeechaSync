"""تب شبکه‌های اجتماعی — تعریف الگوی پست برای ارسال به تلگرام (فاز اول)."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPlainTextEdit,
    QPushButton, QScrollArea, QMessageBox,
)
from PyQt5.QtCore import Qt

from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.social_post_helper import (
    TELEGRAM_TEMPLATE_CONFIG_KEY,
    DEFAULT_TELEGRAM_TEMPLATE,
    get_telegram_template,
    placeholder_help_text,
)


class SocialTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("📢 شبکه‌های اجتماعی")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel(
            "الگوی متن پستی که هنگام ارسال محصول به تلگرام استفاده می‌شود را اینجا تعریف کنید.\n"
            "فقط متن ساخته می‌شود — خودتان با انتخاب گروه/کانال از داخل اکانت تلگرام‌تان ارسال می‌کنید."
        )
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setSpacing(12)

        tg_group = QGroupBox("✈️ الگوی پست تلگرام")
        tg_layout = QVBoxLayout()
        tg_layout.setSpacing(8)

        help_label = QLabel(placeholder_help_text())
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color:#64748b; font-size:11px;")
        tg_layout.addWidget(help_label)

        note_label = QLabel(
            "نکته: نیازی نیست لینک محصول را خودتان در متن بگذارید — "
            "لینک واقعی صفحه‌ی محصول به‌صورت خودکار انتهای پیام اضافه می‌شود."
        )
        note_label.setWordWrap(True)
        note_label.setStyleSheet("color:#0369a1; font-size:11px;")
        tg_layout.addWidget(note_label)

        self.template_edit = QPlainTextEdit()
        self.template_edit.setPlainText(get_telegram_template(self.config))
        self.template_edit.setLayoutDirection(Qt.RightToLeft)
        self.template_edit.setMinimumHeight(160)
        tg_layout.addWidget(self.template_edit)

        preview_label_title = QLabel("پیش‌نمایش با داده‌ی نمونه:")
        preview_label_title.setStyleSheet("font-weight:700; margin-top:6px;")
        tg_layout.addWidget(preview_label_title)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet(
            "background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; "
            "padding:10px; color:#0f172a;"
        )
        tg_layout.addWidget(self.preview_label)
        self.template_edit.textChanged.connect(self._update_preview)

        btn_row = QHBoxLayout()
        self.reset_btn = QPushButton("↺ بازگشت به الگوی پیش‌فرض")
        self.reset_btn.clicked.connect(self._reset_template)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch()
        self.save_btn = QPushButton("💾 ذخیره الگو")
        self.save_btn.setMinimumWidth(140)
        self.save_btn.setMinimumHeight(38)
        self.save_btn.clicked.connect(self._save_template)
        btn_row.addWidget(self.save_btn)
        tg_layout.addLayout(btn_row)

        tg_group.setLayout(tg_layout)
        c_layout.addWidget(tg_group)

        future_hint = QLabel(
            "🔜 پلتفرم‌های بعدی (اینستاگرام، بله، ایتا، روبیکا) پس از تکمیل تلگرام اضافه می‌شوند."
        )
        future_hint.setStyleSheet("color:#94a3b8; font-size:11px;")
        future_hint.setAlignment(Qt.AlignCenter)
        c_layout.addWidget(future_hint)
        c_layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

        self._update_preview()

    def _sample_product(self):
        return {
            "name": "تیشرت مردانه نمونه",
            "price": 250000,
            "sale_price": 199000,
            "stock": 12,
            "sku": "1234567",
            "description": "جنس نخ پنبه، سایزبندی کامل",
        }

    def _update_preview(self):
        from sync_app.core.social_post_helper import render_template

        template = self.template_edit.toPlainText()
        text = render_template(template, self._sample_product())
        preview = text.replace("\n", "<br>") + "<br><span style='color:#94a3b8'>(لینک محصول اینجا)</span>"
        self.preview_label.setText(preview)

    def _reset_template(self):
        self.template_edit.setPlainText(DEFAULT_TELEGRAM_TEMPLATE)

    def _save_template(self):
        cfg = load_secure_config(None) or {}
        cfg[TELEGRAM_TEMPLATE_CONFIG_KEY] = self.template_edit.toPlainText()
        try:
            save_secure_config(cfg)
            self.config = cfg
            QMessageBox.information(self, "ذخیره شد", "الگوی پست تلگرام ذخیره شد.")
        except Exception as exc:
            QMessageBox.critical(self, "خطا", f"ذخیره الگو ناموفق بود:\n{exc}")
