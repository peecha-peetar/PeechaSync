"""تبِ «مقالاتِ سایت» — لیستِ مقالاتِ موجود + ایجاد/ویرایشِ مقاله‌یِ
جدید (عنوان، محتوایِ کامل با ویرایشگرِ ساده، دسته‌بندی، تصویر) + بررسیِ
سئو با پیشنهادِ اصلاح. بسته به پلتفرمِ فروشگاه (تشخیصِ خودکار از تنظیمات)
از طریقِ article_provider.py یا به وردپرس (ووکامرس) یا به صفحاتِ CMS
پرستاشاپ وصل می‌شه.

⚠️ برایِ پرستاشاپ: چون Webserviceِ core هیچ منبعِ استانداردی برایِ
«مقاله»/بلاگ نداره، نزدیک‌ترین معادلِ پایدار یعنی «صفحاتِ CMS» استفاده
می‌شه (نه ماژولِ اختصاصیِ Blog که API عمومیِ مستندی نداره). به همین
دلیل تصویرِ شاخص و چند-دسته‌بندی فقط برایِ ووکامرس در دسترسه."""

import re

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextListFormat
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from sync_app.core import article_provider as ap
from sync_app.core.article_seo_helper import score_article_seo, suggest_article_fixes
from sync_app.core.integrations.commerce_provider import is_prestashop, store_platform_label
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.threading_helper import run_in_thread


class ArticlesTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._articles_by_id: dict[int, dict] = {}
        self._categories: list[dict] = []
        self._current_article_id: int | None = None
        self._build_ui()
        self._on_new_article()
        self._load_articles()

    # ── UI ───────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        title = QLabel("📰 مقالاتِ سایت")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        self.caveat_label = QLabel()
        self.caveat_label.setWordWrap(True)
        self.caveat_label.setStyleSheet("color:#b45309; font-size:11px;")
        outer.addWidget(self.caveat_label)

        top_row = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 بارگذاریِ مقالات")
        self.refresh_btn.clicked.connect(self._load_articles)
        top_row.addWidget(self.refresh_btn)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("جستجو در عنوانِ مقالات...")
        self.search_input.returnPressed.connect(self._load_articles)
        top_row.addWidget(self.search_input, 1)

        self.new_btn = QPushButton("➕ مقاله‌یِ جدید")
        self.new_btn.clicked.connect(self._on_new_article)
        top_row.addWidget(self.new_btn)
        outer.addLayout(top_row)

        self.status_label = QLabel("برایِ شروع، «بارگذاریِ مقالات» رو بزنید.")
        self.status_label.setStyleSheet("color:#4b5563; font-size:11px;")
        outer.addWidget(self.status_label)

        splitter = QSplitter(Qt.Horizontal)

        self.article_list = QListWidget()
        self.article_list.setMaximumWidth(320)
        self.article_list.currentItemChanged.connect(self._on_select_article)
        splitter.addWidget(self.article_list)

        splitter.addWidget(self._build_editor_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        self.setLayout(outer)
        self._refresh_platform_caveat()

    def _refresh_platform_caveat(self):
        config = load_secure_config(None) or {}
        if is_prestashop(config):
            self.caveat_label.setText(
                "⚠️ فروشگاهِ شما پرستاشاپه — چون Webserviceِ اصلیِ پرستاشاپ هیچ منبعِ استانداردی برایِ «بلاگ» "
                "نداره، این بخش با «صفحاتِ CMS» (نزدیک‌ترین معادلِ پایدار) کار می‌کنه. به همین دلیل تصویرِ شاخص "
                "در دسترس نیست (عکس رو مستقیم با لینک داخلِ محتوا اضافه کنید) و هر مقاله فقط یک دسته‌بندی داره."
            )
            self.featured_image_row.setVisible(False)
        else:
            self.caveat_label.setText(
                f"فروشگاهِ شما {store_platform_label(config)}ه — مقالات مستقیم رویِ وردپرسِ سایتتون (wp-json/wp/v2/posts) "
                "مدیریت می‌شن. متا-دیسکریپشن از فیلدِ «خلاصه»یِ وردپرس نوشته می‌شه؛ اگه از افزونه‌ی سئویِ خاصی "
                "(یاست/رنک‌مث) استفاده می‌کنید، ممکنه لازم باشه فیلدهایِ اختصاصیِ اون افزونه رو جدا تنظیم کنید."
            )
            self.featured_image_row.setVisible(True)

    def _build_editor_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        form = QVBoxLayout(panel)
        form.setSpacing(8)

        form.addWidget(QLabel("عنوانِ مقاله:"))
        self.title_input = QLineEdit()
        self.title_input.textChanged.connect(self._refresh_seo_panel)
        form.addWidget(self.title_input)

        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("دسته‌بندی:"))
        self.category_combo = QComboBox()
        cat_row.addWidget(self.category_combo, 1)
        self.new_category_btn = QPushButton("+ دسته‌یِ جدید")
        self.new_category_btn.clicked.connect(self._on_new_category)
        cat_row.addWidget(self.new_category_btn)
        form.addLayout(cat_row)

        self.featured_image_row = QWidget()
        fi_layout = QHBoxLayout(self.featured_image_row)
        fi_layout.setContentsMargins(0, 0, 0, 0)
        fi_layout.addWidget(QLabel("تصویرِ شاخص:"))
        self.featured_image_label = QLabel("—")
        self.featured_image_label.setWordWrap(True)
        fi_layout.addWidget(self.featured_image_label, 1)
        self.pick_featured_image_btn = QPushButton("📷 انتخابِ تصویر")
        self.pick_featured_image_btn.clicked.connect(self._on_pick_featured_image)
        fi_layout.addWidget(self.pick_featured_image_btn)
        form.addWidget(self.featured_image_row)

        form.addWidget(QLabel("خلاصه / متا-دیسکریپشن:"))
        self.excerpt_input = QLineEdit()
        self.excerpt_input.textChanged.connect(self._refresh_seo_panel)
        form.addWidget(self.excerpt_input)

        form.addWidget(QLabel("متا-کلمات‌کلیدی (اختیاری):"))
        self.keywords_input = QLineEdit()
        form.addWidget(self.keywords_input)

        form.addWidget(QLabel("محتوایِ مقاله:"))
        toolbar = QHBoxLayout()
        bold_btn = QPushButton("B")
        bold_btn.setToolTip("توپر")
        bold_btn.clicked.connect(self._toggle_bold)
        toolbar.addWidget(bold_btn)

        italic_btn = QPushButton("I")
        italic_btn.setToolTip("مورب")
        italic_btn.clicked.connect(self._toggle_italic)
        toolbar.addWidget(italic_btn)

        underline_btn = QPushButton("U")
        underline_btn.setToolTip("زیرخط")
        underline_btn.clicked.connect(self._toggle_underline)
        toolbar.addWidget(underline_btn)

        h2_btn = QPushButton("H2")
        h2_btn.setToolTip("زیرعنوان بزرگ")
        h2_btn.clicked.connect(lambda: self._insert_heading("h2"))
        toolbar.addWidget(h2_btn)

        h3_btn = QPushButton("H3")
        h3_btn.setToolTip("زیرعنوان کوچک")
        h3_btn.clicked.connect(lambda: self._insert_heading("h3"))
        toolbar.addWidget(h3_btn)

        list_btn = QPushButton("• لیست")
        list_btn.clicked.connect(self._insert_bullet_list)
        toolbar.addWidget(list_btn)

        img_btn = QPushButton("🖼 افزودنِ عکس")
        img_btn.clicked.connect(self._on_insert_image)
        toolbar.addWidget(img_btn)
        toolbar.addStretch()
        form.addLayout(toolbar)

        self.content_edit = QTextEdit()
        self.content_edit.setMinimumHeight(260)
        self.content_edit.textChanged.connect(self._refresh_seo_panel)
        form.addWidget(self.content_edit)

        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("وضعیت:"))
        self.status_combo = QComboBox()
        self.status_combo.addItem("پیش‌نویس", "draft")
        self.status_combo.addItem("منتشرشده", "publish")
        status_row.addWidget(self.status_combo)
        status_row.addStretch()
        form.addLayout(status_row)

        form.addWidget(QLabel("🩺 بررسیِ سئو:"))
        self.seo_score_label = QLabel("امتیاز: —")
        form.addWidget(self.seo_score_label)
        self.seo_list = QListWidget()
        self.seo_list.setMaximumHeight(140)
        form.addWidget(self.seo_list)

        self.apply_seo_btn = QPushButton("💡 اعمالِ پیشنهادهایِ خودکار")
        self.apply_seo_btn.clicked.connect(self._apply_seo_suggestions)
        form.addWidget(self.apply_seo_btn)

        save_row = QHBoxLayout()
        self.save_btn = QPushButton("💾 ذخیره")
        self.save_btn.setMinimumHeight(38)
        self.save_btn.clicked.connect(self._on_save_article)
        save_row.addWidget(self.save_btn)

        self.delete_btn = QPushButton("🗑 حذفِ این مقاله")
        self.delete_btn.setMinimumHeight(38)
        self.delete_btn.clicked.connect(self._on_delete_article)
        save_row.addWidget(self.delete_btn)
        form.addLayout(save_row)

        form.addStretch()
        scroll.setWidget(panel)
        return scroll

    # ── ویرایشگرِ متن ────────────────────────────────────────────
    def _toggle_bold(self):
        cursor = self.content_edit.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontWeight(400 if fmt.fontWeight() > 400 else 700)
        cursor.mergeCharFormat(fmt)
        self.content_edit.mergeCurrentCharFormat(fmt)

    def _toggle_italic(self):
        cursor = self.content_edit.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontItalic(not fmt.fontItalic())
        cursor.mergeCharFormat(fmt)
        self.content_edit.mergeCurrentCharFormat(fmt)

    def _toggle_underline(self):
        cursor = self.content_edit.textCursor()
        fmt = cursor.charFormat()
        fmt.setFontUnderline(not fmt.fontUnderline())
        cursor.mergeCharFormat(fmt)
        self.content_edit.mergeCurrentCharFormat(fmt)

    def _insert_heading(self, tag: str):
        cursor = self.content_edit.textCursor()
        selected = cursor.selectedText() or "زیرعنوان"
        cursor.insertHtml(f"<{tag}>{selected}</{tag}><p></p>")

    def _insert_bullet_list(self):
        cursor = self.content_edit.textCursor()
        cursor.insertList(QTextListFormat.ListDisc)

    def _on_insert_image(self):
        config = load_secure_config(None) or {}
        if is_prestashop(config):
            url, ok = QInputDialog.getText(self, "لینکِ عکس", "لینکِ عکس (URL) را وارد کنید:")
            if ok and url.strip():
                self.content_edit.textCursor().insertHtml(f'<img src="{url.strip()}" alt="" /><p></p>')
            return

        path, _ = QFileDialog.getOpenFileName(self, "انتخابِ عکس", "", "تصاویر (*.jpg *.jpeg *.png *.webp)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            QMessageBox.warning(self, "خطا", f"خوندنِ فایل ناموفق بود:\n{e}")
            return

        import os
        filename = os.path.basename(path)
        ok, _media_id, url, err = ap.upload_image(config, data, filename)
        if not ok:
            QMessageBox.warning(self, "آپلود ناموفق بود", err)
            return
        self.content_edit.textCursor().insertHtml(f'<img src="{url}" alt="" /><p></p>')

    def _on_pick_featured_image(self):
        config = load_secure_config(None) or {}
        path, _ = QFileDialog.getOpenFileName(self, "انتخابِ تصویرِ شاخص", "", "تصاویر (*.jpg *.jpeg *.png *.webp)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            QMessageBox.warning(self, "خطا", f"خوندنِ فایل ناموفق بود:\n{e}")
            return

        import os
        filename = os.path.basename(path)
        ok, media_id, url, err = ap.upload_image(config, data, filename)
        if not ok:
            QMessageBox.warning(self, "آپلود ناموفق بود", err)
            return
        self._featured_media_id = media_id
        self._featured_image_url = url
        self.featured_image_label.setText(url)
        self._refresh_seo_panel()

    # ── دسته‌بندی ────────────────────────────────────────────────
    def _on_new_category(self):
        name, ok = QInputDialog.getText(self, "دسته‌یِ جدید", "نامِ دسته‌بندی:")
        if not ok or not name.strip():
            return
        config = load_secure_config(None) or {}
        try:
            new_cat = ap.create_category(config, name.strip())
        except Exception as e:
            QMessageBox.warning(self, "خطا", f"ایجادِ دسته‌بندی ناموفق بود:\n{e}")
            return
        self._categories.append(new_cat)
        self.category_combo.addItem(new_cat["name"], new_cat["id"])
        self.category_combo.setCurrentIndex(self.category_combo.count() - 1)

    # ── بارگذاریِ لیستِ مقالات ─────────────────────────────────────
    def _load_articles(self):
        self._refresh_platform_caveat()
        config = load_secure_config(None) or {}
        search = self.search_input.text().strip()
        self.status_label.setText("⏳ در حالِ بارگذاری...")
        self.refresh_btn.setEnabled(False)

        def _worker():
            articles, _total = ap.list_articles(config, per_page=50, search=search)
            categories = ap.list_categories(config)
            return articles, categories

        def _done(result):
            articles, categories = result
            self.refresh_btn.setEnabled(True)
            self._categories = categories
            self._populate_category_combo()
            self.article_list.clear()
            self._articles_by_id.clear()
            for art in articles:
                self._articles_by_id[art["id"]] = art
                item = QListWidgetItem(f"{'✅' if art['status'] == 'publish' else '📝'} {art['title']}")
                item.setData(Qt.UserRole, art["id"])
                self.article_list.addItem(item)
            self.status_label.setText(f"✅ {len(articles)} مقاله بارگذاری شد.")

        def _fail(msg):
            self.refresh_btn.setEnabled(True)
            self.status_label.setText(f"❌ خطا: {msg[:200]}")
            QMessageBox.critical(self, "خطا", f"بارگذاریِ مقالات ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _populate_category_combo(self):
        current_id = self.category_combo.currentData()
        self.category_combo.clear()
        self.category_combo.addItem("— بدونِ دسته —", None)
        for cat in self._categories:
            self.category_combo.addItem(cat["name"], cat["id"])
        if current_id is not None:
            idx = self.category_combo.findData(current_id)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)

    def _on_select_article(self, current, _previous):
        if current is None:
            return
        article_id = current.data(Qt.UserRole)
        article = self._articles_by_id.get(article_id)
        if not article:
            return
        self._load_article_into_editor(article)

    def _load_article_into_editor(self, article: dict):
        self._current_article_id = article.get("id")
        self.title_input.setText(article.get("title") or "")
        self.excerpt_input.setText(article.get("excerpt") or "")
        self.keywords_input.setText(article.get("meta_keywords") or "")
        self.content_edit.setHtml(article.get("content_html") or "")
        idx = self.status_combo.findData(article.get("status") or "draft")
        self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
        cat_ids = article.get("category_ids") or []
        idx = self.category_combo.findData(cat_ids[0]) if cat_ids else 0
        self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._featured_media_id = article.get("featured_media_id")
        self._featured_image_url = article.get("featured_image_url") or ""
        self.featured_image_label.setText(self._featured_image_url or "—")
        self._refresh_seo_panel()

    def _on_new_article(self):
        self._current_article_id = None
        self.title_input.clear()
        self.excerpt_input.clear()
        self.keywords_input.clear()
        self.content_edit.clear()
        self.status_combo.setCurrentIndex(0)
        self.category_combo.setCurrentIndex(0)
        self._featured_media_id = None
        self._featured_image_url = ""
        self.featured_image_label.setText("—")
        self.article_list.setCurrentItem(None)
        self._refresh_seo_panel()

    @staticmethod
    def _body_html(full_html: str) -> str:
        """QTextEdit.toHtml() یه سندِ کاملِ HTML (با head/style) برمی‌گردونه —
        فقط محتوایِ داخلِ body رو نگه می‌داریم تا چیزی که به سایت فرستاده
        می‌شه تمیز باشه."""
        m = re.search(r"<body[^>]*>(.*)</body>", full_html, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else full_html

    # ── جمع‌آوریِ مقاله از فرم ─────────────────────────────────────
    def _collect_article_from_form(self) -> dict:
        cat_id = self.category_combo.currentData()
        return {
            "title": self.title_input.text().strip(),
            "content_html": self._body_html(self.content_edit.toHtml()),
            "excerpt": self.excerpt_input.text().strip(),
            "meta_keywords": self.keywords_input.text().strip(),
            "status": self.status_combo.currentData(),
            "category_ids": [cat_id] if cat_id else [],
            "featured_media_id": getattr(self, "_featured_media_id", None),
            "featured_image_url": getattr(self, "_featured_image_url", ""),
        }

    # ── سئو ──────────────────────────────────────────────────────
    def _refresh_seo_panel(self):
        config = load_secure_config(None) or {}
        article = self._collect_article_from_form()
        result = score_article_seo(article, supports_featured_image=ap.supports_featured_image(config))
        self.seo_score_label.setText(f"امتیاز: {result.score}٪")
        self.seo_list.clear()
        for check in result.checks:
            icon = "✅" if check.ok else "❌"
            label = check.label if check.ok else check.missing_label
            item = QListWidgetItem(f"{icon} {label}")
            self.seo_list.addItem(item)

    def _apply_seo_suggestions(self):
        article = self._collect_article_from_form()
        suggestions = suggest_article_fixes(article)
        if not suggestions:
            QMessageBox.information(self, "همه چی خوبه", "پیشنهادِ اصلاحی برایِ این مقاله وجود نداره.")
            return
        lines = [f"• {msg}" for msg in suggestions.values()]
        if "excerpt" in suggestions and not article.get("excerpt"):
            self.excerpt_input.setText(suggestions["excerpt"])
        QMessageBox.information(self, "پیشنهادهایِ اصلاحِ سئو", "\n".join(lines))

    # ── ذخیره/حذف ───────────────────────────────────────────────
    def _on_save_article(self):
        article = self._collect_article_from_form()
        if not article["title"]:
            QMessageBox.warning(self, "عنوان خالیه", "لطفاً عنوانِ مقاله رو وارد کنید.")
            return

        config = load_secure_config(None) or {}
        self.save_btn.setEnabled(False)
        self.status_label.setText("⏳ در حالِ ذخیره...")

        article_id = self._current_article_id

        def _worker():
            if article_id:
                return ap.update_article(config, article_id, article)
            return ap.create_article(config, article)

        def _done(saved):
            self.save_btn.setEnabled(True)
            self._current_article_id = saved.get("id")
            self.status_label.setText("✅ مقاله ذخیره شد.")
            self._load_articles()

        def _fail(msg):
            self.save_btn.setEnabled(True)
            self.status_label.setText(f"❌ خطا: {msg[:200]}")
            QMessageBox.critical(self, "خطا", f"ذخیره‌یِ مقاله ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _on_delete_article(self):
        if not self._current_article_id:
            QMessageBox.information(self, "چیزی انتخاب نشده", "اول یه مقاله رو از لیست انتخاب کنید.")
            return
        confirm = QMessageBox.question(
            self, "حذفِ مقاله", "این مقاله برایِ همیشه از سایت حذف بشه؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        config = load_secure_config(None) or {}
        article_id = self._current_article_id
        self.status_label.setText("⏳ در حالِ حذف...")

        def _worker():
            return ap.delete_article(config, article_id)

        def _done(_result):
            self.status_label.setText("✅ مقاله حذف شد.")
            self._on_new_article()
            self._load_articles()

        def _fail(msg):
            self.status_label.setText(f"❌ خطا: {msg[:200]}")
            QMessageBox.critical(self, "خطا", f"حذفِ مقاله ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)
