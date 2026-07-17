"""تب «تقویم محتوا» — لیستِ پست‌های زمان‌بندی‌شده‌ی شبکه‌های اجتماعی
(تلگرام/بله) که از زیرتبِ «📅 زمان‌بندی شبکه اجتماعی» در Content Studio
(تبِ محصولات) اضافه شده‌اند. ارسالِ واقعی به‌صورتِ خودکار توسطِ تایمرِ
پس‌زمینه در peecha_launcher.py انجام می‌شود؛ این تب فقط برای مدیریت
(مشاهده/لغو/حذف/ارسالِ فوری) است."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
)
from PyQt5.QtCore import Qt

from sync_app.core.content_calendar_store import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    delete_scheduled_post,
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
        self._build_ui()
        self.refresh()

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

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["زمانِ ارسال", "محصول", "پلتفرم", "وضعیت", "خطا", "عملیات"]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table)

    def refresh(self):
        from datetime import datetime

        posts = load_scheduled_posts()
        posts.sort(key=lambda p: str(p.get("scheduled_at") or ""))

        self.table.setRowCount(0)
        pending_count = 0
        for post in posts:
            row = self.table.rowCount()
            self.table.insertRow(row)

            try:
                dt = datetime.fromisoformat(str(post.get("scheduled_at") or ""))
                when = to_jalali_datetime_str(dt)
            except ValueError:
                when = str(post.get("scheduled_at") or "")
            self.table.setItem(row, 0, QTableWidgetItem(when))

            product_label = f"{post.get('product_name') or ''} ({post.get('sku') or ''})"
            self.table.setItem(row, 1, QTableWidgetItem(product_label))

            platform = str(post.get("platform") or "")
            self.table.setItem(row, 2, QTableWidgetItem(PLATFORM_LABELS.get(platform, platform)))

            status = str(post.get("status") or "")
            if status == STATUS_PENDING:
                pending_count += 1
            self.table.setItem(row, 3, QTableWidgetItem(_STATUS_LABELS.get(status, status)))

            self.table.setItem(row, 4, QTableWidgetItem(str(post.get("error") or "")))

            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(4, 0, 4, 0)
            actions_layout.setSpacing(6)
            post_id = str(post.get("id") or "")

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

            self.table.setCellWidget(row, 5, actions)

        self.summary_label.setText(f"مجموع: {len(posts)} — در انتظار: {pending_count}")

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
        from sync_app.core.secure_config_loader import load_secure_config
        from sync_app.core.social_poster import is_platform_configured, send_post_for_platform

        cfg = load_secure_config(None) or {}
        platform = str(post.get("platform") or "telegram")
        if not is_platform_configured(platform, cfg):
            QMessageBox.warning(
                self, f"{PLATFORM_LABELS.get(platform, platform)} تنظیم نشده",
                f"ابتدا توکنِ بات و شناسه‌ی چت را در «تنظیمات → {PLATFORM_LABELS.get(platform, platform)}» وارد کنید.",
            )
            return

        self.refresh_btn.setEnabled(False)

        def _worker():
            return send_post_for_platform(
                platform, cfg, post.get("text") or "", photo_path=post.get("image_path") or ""
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
