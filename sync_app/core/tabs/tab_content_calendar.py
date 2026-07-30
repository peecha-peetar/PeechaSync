"""تب «تقویم محتوا» — لیستِ پست‌های زمان‌بندی‌شده‌ی شبکه‌های اجتماعی
(تلگرام/بله) که از زیرتبِ «📅 زمان‌بندی شبکه اجتماعی» در Content Studio
(تبِ محصولات) اضافه شده‌اند. ارسالِ واقعی به‌صورتِ خودکار توسطِ تایمرِ
پس‌زمینه در peecha_launcher.py انجام می‌شود؛ این تب فقط برای مدیریت
(مشاهده/فیلتر/لغو/حذفِ تکی یا گروهی/ارسالِ فوری) است."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
)
from PyQt5.QtCore import Qt, QTimer

from sync_app.core.content_calendar_store import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    delete_scheduled_post,
    delete_scheduled_posts,
    load_scheduled_posts,
    update_post_status,
)
from sync_app.core.jalali_date_utils import to_jalali_datetime_str
from sync_app.core.social_poster import PLATFORM_LABELS
from sync_app.core.threading_helper import run_in_thread

_STATUS_LABELS = {
    STATUS_PENDING: "⏳ در انتظار",
    STATUS_SENT: "✅ ارسال‌شده",
    STATUS_FAILED: "❌ ناموفق",
    STATUS_CANCELLED: "🚫 لغوشده",
}


class ContentCalendarTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self._row_checkboxes = {}  # post_id -> QCheckBox
        self._build_ui()
        # با تأخیرِ صفر (نه مستقیم تویِ __init__) تا خودِ تب اول رندر بشه،
        # بعد لیست پر بشه — این تب معمولاً همراهِ چندتا زیرتبِ دیگه یک‌جا
        # داخلِ «دستیارِ هوشمند» ساخته می‌شه، پس تأخیرِ صفر باعثِ نمی‌شه
        # کلیکِ اول رویِ اون هاب حس بشه که قفل کرده.
        QTimer.singleShot(0, self.refresh)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("📅 تقویم محتوا")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        subtitle = QLabel(
            "پست‌های زمان‌بندی‌شده برای شبکه‌های اجتماعی — برای افزودنِ پستِ جدید، از تبِ «محصولات»، "
            "روی دکمه‌ی محتوای هر محصول، زیرتبِ «📅 زمان‌بندی شبکه اجتماعی» را باز کنید."
        )
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        toolbar = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 بروزرسانی")
        self.refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addStretch()
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color:#64748b; font-size:11px;")
        toolbar.addWidget(self.summary_label)
        outer.addLayout(toolbar)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("پلتفرم:"))
        self.platform_filter = QComboBox()
        self.platform_filter.addItem("همه", "")
        for key, label in PLATFORM_LABELS.items():
            self.platform_filter.addItem(label, key)
        self.platform_filter.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.platform_filter)

        filter_row.addWidget(QLabel("وضعیت:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("همه", "")
        for key, label in _STATUS_LABELS.items():
            self.status_filter.addItem(label, key)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.status_filter)

        filter_row.addWidget(QLabel("جستجو:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("نامِ محصول یا SKU")
        self.search_input.textChanged.connect(self.refresh)
        filter_row.addWidget(self.search_input, 1)
        outer.addLayout(filter_row)

        bulk_row = QHBoxLayout()
        select_all_btn = QPushButton("☑️ انتخابِ همه‌ی نمایش‌داده‌شده‌ها")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        bulk_row.addWidget(select_all_btn)
        clear_selection_btn = QPushButton("☐ لغوِ انتخاب")
        clear_selection_btn.clicked.connect(lambda: self._set_all_checked(False))
        bulk_row.addWidget(clear_selection_btn)
        bulk_row.addStretch()
        self.delete_selected_btn = QPushButton("🗑 حذفِ انتخاب‌شده‌ها")
        self.delete_selected_btn.clicked.connect(self._delete_selected)
        bulk_row.addWidget(self.delete_selected_btn)
        self.delete_all_filtered_btn = QPushButton("🗑 حذفِ همه‌ی نمایش‌داده‌شده‌ها")
        self.delete_all_filtered_btn.clicked.connect(self._delete_all_filtered)
        bulk_row.addWidget(self.delete_all_filtered_btn)
        outer.addLayout(bulk_row)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["", "زمانِ ارسال", "محصول", "پلتفرم", "وضعیت", "خطا", "مقصد", "عملیات"]
        )
        self.table.setColumnWidth(0, 30)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table)

    def _filtered_posts(self, posts: list[dict] | None = None) -> list[dict]:
        posts = load_scheduled_posts() if posts is None else list(posts)
        posts.sort(key=lambda p: str(p.get("scheduled_at") or ""))

        platform_f = self.platform_filter.currentData()
        status_f = self.status_filter.currentData()
        search_f = (self.search_input.text() or "").strip().lower()

        out = []
        for post in posts:
            if platform_f and str(post.get("platform") or "") != platform_f:
                continue
            if status_f and str(post.get("status") or "") != status_f:
                continue
            if search_f:
                haystack = f"{post.get('product_name') or ''} {post.get('sku') or ''}".lower()
                if search_f not in haystack:
                    continue
            out.append(post)
        return out

    def refresh(self):
        from datetime import datetime

        # قبلاً اینجا load_scheduled_posts() جدا صدا زده می‌شد و بعد دوباره
        # داخلِ _filtered_posts() — یعنی فایلِ تقویم دوبار از دیسک خونده و
        # JSON‌پارس می‌شد. حالا فقط یک‌بار می‌خونیم.
        all_posts = load_scheduled_posts()
        all_count = len(all_posts)
        posts = self._filtered_posts(all_posts)
        self._row_checkboxes = {}

        self.table.setRowCount(0)
        pending_count = 0
        for post in posts:
            row = self.table.rowCount()
            self.table.insertRow(row)
            post_id = str(post.get("id") or "")

            checkbox_container = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_container)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignCenter)
            checkbox = QCheckBox()
            checkbox_layout.addWidget(checkbox)
            self.table.setCellWidget(row, 0, checkbox_container)
            self._row_checkboxes[post_id] = checkbox

            try:
                dt = datetime.fromisoformat(str(post.get("scheduled_at") or ""))
                when = to_jalali_datetime_str(dt)
            except ValueError:
                when = str(post.get("scheduled_at") or "")
            self.table.setItem(row, 1, QTableWidgetItem(when))

            product_label = f"{post.get('product_name') or ''} ({post.get('sku') or ''})"
            self.table.setItem(row, 2, QTableWidgetItem(product_label))

            platform = str(post.get("platform") or "")
            self.table.setItem(row, 3, QTableWidgetItem(PLATFORM_LABELS.get(platform, platform)))

            status = str(post.get("status") or "")
            if status == STATUS_PENDING:
                pending_count += 1
            self.table.setItem(row, 4, QTableWidgetItem(_STATUS_LABELS.get(status, status)))

            self.table.setItem(row, 5, QTableWidgetItem(str(post.get("error") or "")))

            chat_override = str(post.get("chat_id_override") or "").strip()
            self.table.setItem(row, 6, QTableWidgetItem(chat_override or "پیش‌فرض (تنظیمات)"))

            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(4, 0, 4, 0)
            actions_layout.setSpacing(6)

            if status == STATUS_PENDING:
                send_now_btn = QPushButton("🚀 ارسالِ الان")
                send_now_btn.clicked.connect(lambda _=False, pid=post_id, p=post: self._send_now(pid, p))
                actions_layout.addWidget(send_now_btn)

                cancel_btn = QPushButton("🚫 لغو")
                cancel_btn.clicked.connect(lambda _=False, pid=post_id: self._cancel(pid))
                actions_layout.addWidget(cancel_btn)
            else:
                delete_btn = QPushButton("🗑 حذف")
                delete_btn.clicked.connect(lambda _=False, pid=post_id: self._delete(pid))
                actions_layout.addWidget(delete_btn)

            self.table.setCellWidget(row, 7, actions)

        self.summary_label.setText(f"نمایش: {len(posts)} از {all_count} — در انتظار: {pending_count}")

    def _set_all_checked(self, checked: bool):
        for checkbox in self._row_checkboxes.values():
            checkbox.setChecked(checked)

    def _selected_post_ids(self) -> list[str]:
        return [pid for pid, checkbox in self._row_checkboxes.items() if checkbox.isChecked()]

    def _delete_selected(self):
        ids = self._selected_post_ids()
        if not ids:
            QMessageBox.information(self, "حذفِ انتخاب‌شده‌ها", "هیچ ردیفی انتخاب نشده.")
            return
        answer = QMessageBox.question(
            self, "حذفِ انتخاب‌شده‌ها", f"{len(ids)} پستِ انتخاب‌شده حذف شود؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        delete_scheduled_posts(ids)
        self.refresh()

    def _delete_all_filtered(self):
        ids = [str(p.get("id") or "") for p in self._filtered_posts()]
        if not ids:
            QMessageBox.information(self, "حذفِ همه", "با فیلترِ فعلی هیچ پستی برای حذف نیست.")
            return
        answer = QMessageBox.question(
            self, "حذفِ همه‌ی نمایش‌داده‌شده‌ها",
            f"همه‌ی {len(ids)} پستِ نمایش‌داده‌شده (بر اساسِ فیلترِ فعلی) حذف شوند؟ این کار قابلِ بازگشت نیست.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        delete_scheduled_posts(ids)
        self.refresh()

    def _cancel(self, post_id: str):
        update_post_status(post_id, STATUS_CANCELLED)
        self.refresh()

    def _delete(self, post_id: str):
        answer = QMessageBox.question(
            self, "حذف پست", "این پست از تقویمِ محتوا حذف شود؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        delete_scheduled_post(post_id)
        self.refresh()

    def _send_now(self, post_id: str, post: dict):
        from sync_app.core.content_calendar_store import post_image_paths
        from sync_app.core.secure_config_loader import load_secure_config
        from sync_app.core.social_poster import is_platform_configured, send_post_for_platform

        cfg = load_secure_config(None) or {}
        platform = str(post.get("platform") or "telegram")
        chat_id_override = str(post.get("chat_id_override") or "").strip()
        if not is_platform_configured(platform, cfg, chat_id_override=chat_id_override):
            QMessageBox.warning(
                self, f"{PLATFORM_LABELS.get(platform, platform)} تنظیم نشده",
                f"ابتدا توکنِ بات را در «تنظیمات → {PLATFORM_LABELS.get(platform, platform)}» وارد کنید "
                "(اگه مقصدِ سفارشی نداره، شناسه‌ی چت هم لازمه).",
            )
            return

        self.refresh_btn.setEnabled(False)

        def _worker():
            return send_post_for_platform(
                platform, cfg, post.get("text") or "",
                photo_paths=post_image_paths(post), chat_id_override=chat_id_override,
            )

        def on_complete(result):
            ok, msg = result
            self.refresh_btn.setEnabled(True)
            if ok:
                update_post_status(post_id, STATUS_SENT)
                QMessageBox.information(self, "ارسال شد", "پست با موفقیت ارسال شد.")
            else:
                update_post_status(post_id, STATUS_FAILED, error=msg)
                QMessageBox.critical(self, "ارسال ناموفق", msg)
            self.refresh()

        def on_error(err):
            self.refresh_btn.setEnabled(True)
            update_post_status(post_id, STATUS_FAILED, error=str(err))
            QMessageBox.critical(self, "خطا", str(err))
            self.refresh()

        run_in_thread(_worker, on_complete=on_complete, on_error=on_error)
