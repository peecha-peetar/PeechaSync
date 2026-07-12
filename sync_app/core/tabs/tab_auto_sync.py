"""تب همگام‌سازی خودکار — اجرای زمان‌بندی‌شده یا دستی اسکریپت‌های همگام‌سازی."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.connectivity_guard import ensure_connectivity
from sync_app.core.event_notifier import append_system_log
from sync_app.core.jalali_log_formatter import format_log_lines_jalali
from sync_app.core.live_site_backup_guard import confirm_live_site_backup
from sync_app.core.log_panel_ui import LogActionRail, LogPanelController
from sync_app.core.message_boxes_fa import ask_yes_no
from sync_app.core.product_woo_map_helper import load_product_woo_map
from sync_app.core.scripts import (
    ProductCategoriesSync,
    Poshakproperties,
    customersync,
    ordersync,
    sync_fullproduct,
    update_variations,
)
from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.store_setup_guard import ensure_store_pages_ready
from sync_app.core.log_catalog import LOG_TOPIC_TOKEN_MAP, read_sync_log_lines
from sync_app.core.sync_utils import clear_filtered_logs

AUTO_SYNC_LOG_TOKENS = LOG_TOPIC_TOKEN_MAP["auto_sync"]

AUTO_INTERVAL_OPTIONS = (
    "15 دقیقه", "30 دقیقه",
    "1 ساعت", "2 ساعت", "4 ساعت", "6 ساعت", "8 ساعت", "12 ساعت", "24 ساعت",
)
AUTO_INTERVAL_MS = {
    "15 دقیقه": 15 * 60 * 1000,
    "30 دقیقه": 30 * 60 * 1000,
    "1 ساعت": 60 * 60 * 1000,
    "2 ساعت": 2 * 60 * 60 * 1000,
    "4 ساعت": 4 * 60 * 60 * 1000,
    "6 ساعت": 6 * 60 * 60 * 1000,
    "8 ساعت": 8 * 60 * 60 * 1000,
    "12 ساعت": 12 * 60 * 60 * 1000,
    "24 ساعت": 24 * 60 * 60 * 1000,
}
# نگاشت فاصله‌های قدیمی‌تر (که دیگه تو گزینه‌های اصلی نیستن) به نزدیک‌ترین گزینه‌ی موجود
_LEGACY_AUTO_INTERVAL = {
    "5 دقیقه": "15 دقیقه",
    "10 دقیقه": "15 دقیقه",
}


def _normalize_auto_interval(saved: str) -> str:
    text = str(saved or "").strip()
    if text in AUTO_INTERVAL_OPTIONS:
        return text
    return _LEGACY_AUTO_INTERVAL.get(text, "4 ساعت")


def _interval_index(interval_text: str) -> int:
    normalized = _normalize_auto_interval(interval_text)
    try:
        return AUTO_INTERVAL_OPTIONS.index(normalized)
    except ValueError:
        return AUTO_INTERVAL_OPTIONS.index("4 ساعت")

RECON_AWARE_KEYS = frozenset({"sync_fullproduct", "update_variations"})


@dataclass(frozen=True)
class AutoSyncJob:
    key: str
    title: str
    icon: str
    hint: str
    runner: Callable[[], object]
    touches_live_store: bool = True

    @property
    def label(self) -> str:
        return f"{self.title} {self.icon}"


AUTO_SYNC_JOBS: tuple[AutoSyncJob, ...] = (
    AutoSyncJob(
        "ProductCategoriesSync",
        "دسته‌بندی‌ها",
        "📂",
        "همگام‌سازی گروه‌ها و نامک‌های ERP",
        ProductCategoriesSync.main,
    ),
    AutoSyncJob(
        "Poshakproperties",
        "ویژگی‌ها",
        "🎯",
        "سایز، رنگ و attributeهای محصول",
        Poshakproperties.main,
    ),
    AutoSyncJob(
        "sync_fullproduct",
        "محصولات",
        "📦",
        "ارسال کالاهای گروه انتخاب‌شده",
        sync_fullproduct.main,
    ),
    AutoSyncJob(
        "update_variations",
        "متغیرها",
        "🎨",
        "قیمت و موجودی variationها",
        update_variations.main,
    ),
    AutoSyncJob(
        "customersync",
        "مشتریان",
        "👥",
        "خریداران دارای سفارش یا مشتری ثابت",
        customersync.main,
    ),
    AutoSyncJob(
        "ordersync",
        "سفارشات",
        "🧾",
        "انتقال سفارش‌های processing به ERP",
        ordersync.main,
    ),
)
AUTO_SYNC_JOB_ROW_HEIGHT = 64
AUTO_SYNC_JOB_BY_KEY = {job.key: job for job in AUTO_SYNC_JOBS}


class SyncWorker(QThread):
    progress_updated = pyqtSignal(int, str, str)
    batch_finished = pyqtSignal(int, int)

    def __init__(self, script_keys: list[str]):
        super().__init__()
        self.script_keys = list(script_keys)
        self.total_count = len(self.script_keys)

    def run(self):
        ok_count = 0
        fail_count = 0
        for index, script_key in enumerate(self.script_keys, start=1):
            if self.isInterruptionRequested():
                break
            job = AUTO_SYNC_JOB_BY_KEY.get(script_key)
            label = job.label if job else script_key
            progress = int((index / max(self.total_count, 1)) * 100)
            self.progress_updated.emit(
                progress,
                script_key,
                f"📌 در حال اجرا ({index}/{self.total_count}): {label}",
            )
            try:
                if job is None:
                    raise RuntimeError(f"اسکریپت ناشناخته: {script_key}")
                from sync_app.core.auto_sync_scope import run_job_with_scope
                run_job_with_scope(script_key, job.runner)
                ok_count += 1
                self.progress_updated.emit(progress, script_key, f"✅ انجام شد: {label}")
            except Exception as exc:
                fail_count += 1
                self.progress_updated.emit(
                    progress,
                    script_key,
                    f"❌ خطا در {label}: {exc}",
                )
        self.batch_finished.emit(ok_count, fail_count)


class AutoSyncTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("autoSyncRoot")
        self.setLayoutDirection(Qt.RightToLeft)
        self.config = load_secure_config(None) or {}

        self.checkboxes: list[QCheckBox] = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.run_auto)
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._toggle_running_blink)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._refresh_logs_if_visible)

        self.is_batch_running = False
        self.blink_visible = True
        self.sync_worker: SyncWorker | None = None
        self._job_rows: list[QFrame] = []
        self._jobs_fullscreen = False
        self._jobs_fullscreen_restore = {}

        self._build_ui()
        self._restore_auto_timer_from_config()
        self.log_timer.start(2000)
        self.refresh_logs()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setDirection(QHBoxLayout.LeftToRight)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.splitter = splitter = QSplitter(Qt.Horizontal)
        splitter.setLayoutDirection(Qt.LeftToRight)
        splitter.setHandleWidth(6)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("log_view")
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LeftToRight)
        self.log_view.setMinimumWidth(260)
        splitter.addWidget(self.log_view)

        panel = QWidget()
        panel.setObjectName("autoSyncPanel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        self.log_actions = LogActionRail(clear_text="حذف لاگ‌های همگام‌سازی خودکار", parent=self)

        self.status_bar = QFrame()
        self.status_bar.setObjectName("reconStatusBar")
        self.status_bar.setProperty("state", "ready")
        status_row = QHBoxLayout(self.status_bar)
        status_row.setContentsMargins(10, 6, 10, 6)
        self.status_message = QLabel("✓ آماده — آیتم‌ها را انتخاب و «اجرای دستی» یا حالت اتوماتیک را فعال کنید")
        self.status_message.setObjectName("reconStatusMessage")
        self.status_message.setWordWrap(True)
        status_row.addWidget(self.status_message, 1)
        layout.addWidget(self.status_bar)

        self.info_card = info_card = QFrame()
        info_card.setObjectName("autoSyncInfoCard")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(16, 12, 16, 12)
        info_layout.setSpacing(6)
        info_title = QLabel("⚡ همگام‌سازی خودکار")
        info_title.setObjectName("autoSyncInfoTitle")
        info_title.setWordWrap(True)
        info_layout.addWidget(info_title)
        info_body = QLabel(
            "برای فروشگاه از قبل فعال، ابتدا تب «تطبیق» را کامل کنید تا قیمت و موجودی "
            "روی کالای درست اعمال شود. نگاشت‌های دستی و ثبت‌شده در تطبیق در همگام‌سازی خودکار "
            "رعایت می‌شوند. قبل از اجرای دستی روی سایت زنده، بکاپ الزامی است."
        )
        info_body.setObjectName("autoSyncInfoBody")
        info_body.setWordWrap(True)
        info_layout.addWidget(info_body)
        layout.addWidget(info_card)

        jobs_card = QFrame()
        jobs_card.setObjectName("autoSyncJobsCard")
        jobs_layout = QVBoxLayout(jobs_card)
        jobs_layout.setContentsMargins(16, 12, 16, 12)
        jobs_layout.setSpacing(10)

        jobs_header = QHBoxLayout()
        jobs_header.setSpacing(8)
        select_all_btn = QPushButton("همه")
        select_all_btn.setObjectName("autoSyncJobsSelectAll")
        select_all_btn.setCursor(Qt.PointingHandCursor)
        select_all_btn.setFixedHeight(30)
        select_all_btn.clicked.connect(self._select_all_jobs)
        jobs_header.addWidget(select_all_btn)

        clear_all_btn = QPushButton("هیچ")
        clear_all_btn.setObjectName("autoSyncJobsClearAll")
        clear_all_btn.setCursor(Qt.PointingHandCursor)
        clear_all_btn.setFixedHeight(30)
        clear_all_btn.clicked.connect(self._clear_all_jobs)
        jobs_header.addWidget(clear_all_btn)

        self.jobs_fullscreen_btn = QPushButton("⛶ تمام‌صفحه")
        self.jobs_fullscreen_btn.setObjectName("autoSyncJobsFullscreen")
        self.jobs_fullscreen_btn.setCursor(Qt.PointingHandCursor)
        self.jobs_fullscreen_btn.setFixedHeight(30)
        self.jobs_fullscreen_btn.setToolTip("مخفی‌کردن بقیه‌ی بخش‌ها تا لیست ماژول‌ها فضای بیشتری داشته باشد")
        self.jobs_fullscreen_btn.clicked.connect(self._toggle_jobs_fullscreen)
        jobs_header.addWidget(self.jobs_fullscreen_btn)

        jobs_header.addStretch(1)

        jobs_title = QLabel(f"انتخاب ماژول‌های همگام‌سازی ({len(AUTO_SYNC_JOBS)} مورد)")
        jobs_title.setObjectName("autoSyncJobsTitle")
        jobs_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        jobs_header.addWidget(jobs_title)
        jobs_layout.addLayout(jobs_header)

        jobs_hint = QLabel("روی هر ردیف کلیک کنید یا تیک بزنید — ترتیب اجرا از بالا به پایین است.")
        jobs_hint.setObjectName("autoSyncJobsHint")
        jobs_hint.setWordWrap(True)
        jobs_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        jobs_layout.addWidget(jobs_hint)

        jobs_list = QFrame()
        jobs_list.setObjectName("autoSyncJobsList")
        jobs_list_layout = QVBoxLayout(jobs_list)
        jobs_list_layout.setContentsMargins(0, 0, 0, 0)
        jobs_list_layout.setSpacing(8)

        from sync_app.core.product_mode import is_simple_only
        simple_only = is_simple_only()
        visible_jobs = [
            job for job in AUTO_SYNC_JOBS
            if not (simple_only and job.key in ("update_variations", "Poshakproperties"))
        ]
        for job in visible_jobs:
            row, cb = self._build_job_row(job)
            self._job_rows.append(row)
            jobs_list_layout.addWidget(row)

        jobs_content_height = len(visible_jobs) * AUTO_SYNC_JOB_ROW_HEIGHT + max(0, len(visible_jobs) - 1) * 8
        jobs_list.setMinimumHeight(jobs_content_height)
        jobs_list.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        self.jobs_scroll = jobs_scroll = QScrollArea()
        jobs_scroll.setObjectName("autoSyncJobsScroll")
        jobs_scroll.setWidgetResizable(True)
        jobs_scroll.setFrameShape(QFrame.NoFrame)
        jobs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        jobs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        jobs_scroll.setMinimumHeight(min(jobs_content_height, 260))
        jobs_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        jobs_scroll.setWidget(jobs_list)
        jobs_layout.addWidget(jobs_scroll, 1)
        layout.addWidget(jobs_card, 1)

        interval_row = QHBoxLayout()
        interval_row.addStretch(1)
        self.interval_box = QComboBox()
        self.interval_box.setObjectName("autoSyncIntervalCombo")
        self.interval_box.setLayoutDirection(Qt.RightToLeft)
        self.interval_box.addItems(list(AUTO_INTERVAL_OPTIONS))
        saved_raw = str(self.config.get("AUTO_INTERVAL", "4 ساعت")).strip()
        saved_interval = _normalize_auto_interval(saved_raw)
        self.interval_box.blockSignals(True)
        self.interval_box.setCurrentIndex(_interval_index(saved_interval))
        self.interval_box.blockSignals(False)
        if saved_raw != saved_interval:
            self._persist_auto_interval(saved_interval)
        self.interval_box.currentIndexChanged.connect(self._on_interval_changed)
        interval_row.addWidget(self.interval_box)

        self.interval_label = interval_label = QLabel("⏱ فاصله زمانی:")
        interval_label.setObjectName("autoSyncIntervalLabel")
        interval_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        interval_row.addWidget(interval_label)
        layout.addLayout(interval_row)

        self.auto_enabled = QCheckBox("فعال‌سازی حالت اتوماتیک")
        self.auto_enabled.setObjectName("autoSyncEnabledCheck")
        self.auto_enabled.setLayoutDirection(Qt.RightToLeft)
        self.auto_enabled.setChecked(bool(self.config.get("AUTO_ENABLED", False)))
        self.auto_enabled.stateChanged.connect(self._on_auto_enabled_changed)
        layout.addWidget(self.auto_enabled)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("siteFetchProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        self.progress_info_label = QLabel("آماده برای اجرا")
        self.progress_info_label.setObjectName("autoSyncProgressInfo")
        self.progress_info_label.setAlignment(Qt.AlignCenter)
        self.progress_info_label.setWordWrap(True)
        layout.addWidget(self.progress_info_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.manual_btn = QPushButton("اجرای دستی همگام‌سازی")
        self.manual_btn.setObjectName("autoSyncManualBtn")
        self.manual_btn.setMinimumHeight(42)
        self.manual_btn.clicked.connect(self.run_manual)
        btn_row.addWidget(self.manual_btn, 2)

        self._unlock_btn = QPushButton("🔓 ویرایش")
        self._unlock_btn.setObjectName("devUnlockBtn")
        self._unlock_btn.setMinimumHeight(42)
        self._unlock_btn.clicked.connect(self._toggle_dev_lock)
        btn_row.addWidget(self._unlock_btn, 1)

        self.save_btn = QPushButton("💾 ذخیره تنظیمات")
        self.save_btn.setObjectName("autoSyncSaveBtn")
        self.save_btn.setMinimumHeight(42)
        self.save_btn.clicked.connect(self.save_config)
        btn_row.addWidget(self.save_btn, 1)
        layout.addLayout(btn_row)

        self.auto_state_label = QLabel("")
        self.auto_state_label.setObjectName("autoSyncStateLabel")
        self.auto_state_label.setWordWrap(True)
        layout.addWidget(self.auto_state_label)

        splitter.addWidget(panel)

        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self._dev_unlock_shortcut = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self._dev_unlock_shortcut.activated.connect(self._toggle_dev_lock)
        self._dev_locked = True

        self.log_panel_controller = LogPanelController(
            splitter=splitter,
            button=self.log_actions.toggle_button,
            open_size=360,
            duration_ms=160,
            log_widget=self.log_view,
            storage_key="auto_sync_tab",
            parent=self,
        )
        self.log_actions.bind_toggle(self.log_panel_controller.toggle)
        self.log_actions.bind_clear(self.clear_tab_logs)
        self.log_panel_controller.collapse_initial()  # پیش‌فرض: لاگ مخفی — با دکمه‌ی کناری نمایش داده می‌شود

        root.addWidget(splitter, 1)
        root.addWidget(self.log_actions)

        self._update_manual_button_text()
        self._update_auto_state_ui()
        self._apply_dev_lock_ui()

    def _apply_dev_lock_ui(self):
        from sync_app.core.dev_lock import apply_lock_state

        apply_lock_state(self, self._dev_locked, exclude_names={"devUnlockBtn", "autoSyncManualBtn"})
        self._unlock_btn.setText("🔓 ویرایش" if self._dev_locked else "🔒 قفل کردن دوباره")
        self._unlock_btn.setEnabled(True)
        self.manual_btn.setEnabled(True)

    def _toggle_dev_lock(self):
        from sync_app.core.dev_lock import prompt_unlock

        if not self._dev_locked:
            self._dev_locked = True
            self._apply_dev_lock_ui()
            return
        if prompt_unlock(self):
            self._dev_locked = False
            self._apply_dev_lock_ui()

    def _build_scope_control(self, job: AutoSyncJob, parent):
        """
        کنترل محدوده‌ی همگام‌سازی خودکار برای این job — بر اساس نوعش:
        محصولات/دسته‌بندی‌ها/متغیرها → ۳ گزینه (تطبیق‌شده/زیرگروه انتخابی/همه)
        مشتریان → ۳ گزینه (پرداخت‌کرده/همه/هیچ‌کدام — از تنظیمات موجود)
        ویژگی‌ها و سفارشات → فقط توضیح (این دو اصلاً مفهوم محدوده ندارن)
        """
        from sync_app.core.auto_sync_scope import (
            SCOPE_CAPABLE_JOBS, SCOPE_LABELS, SCOPE_ORDER, SCOPE_ALL_CHECKED_JOBS,
            get_job_scope, set_job_scope,
        )

        if job.key == "update_variations":
            current = get_job_scope("update_variations", self.config)
            note = QLabel(f"ℹ️ از تنظیم «محصولات» ارث می‌برد — الان: {SCOPE_LABELS.get(current, current)}")
            note.setStyleSheet("color:#94a3b8; font-size:11px;")
            note.setWordWrap(True)
            return note

        if job.key in SCOPE_CAPABLE_JOBS:
            combo = QComboBox()
            combo.setObjectName("autoSyncScopeCombo")
            modes = [
                m for m in SCOPE_ORDER
                if m != "all_checked" or job.key in SCOPE_ALL_CHECKED_JOBS
            ]
            for mode in modes:
                combo.addItem(SCOPE_LABELS[mode], mode)
            current = get_job_scope(job.key, self.config)
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _=0, jk=job.key, c=combo: set_job_scope(jk, c.currentData())
            )
            return combo

        if job.key == "customersync":
            current = str(self.config.get("DEFAULT_CUSTOMER_MODE", "website"))
            labels = {
                "website": "فقط مشتریانی که خرید و پرداخت کرده‌اند",
                "all": "همه‌ی مشتریان",
                "fixed": "هیچ‌کدام (مشتری ثابت — غیرفعال)",
            }
            note = QLabel(
                f"ℹ️ حالت فعلی: «{labels.get(current, current)}» — این یک تنظیم مشترک بین "
                "حالت خودکار و دستیه، از تب «⚙️ تنظیمات» تغییرش بدید."
            )
            note.setStyleSheet("color:#94a3b8; font-size:11px;")
            note.setWordWrap(True)
            return note

        if job.key == "Poshakproperties":
            note = QLabel("ℹ️ همیشه همه‌ی ویژگی‌ها — این بخش هنوز محدوده‌ی جزئی ندارد")
            note.setStyleSheet("color:#94a3b8; font-size:11px;")
            note.setWordWrap(True)
            return note

        if job.key == "ordersync":
            note = QLabel("ℹ️ فقط سفارش‌های «در حال انجام» — گزینه‌ی دیگری ندارد")
            note.setStyleSheet("color:#94a3b8; font-size:11px;")
            note.setWordWrap(True)
            return note

        return None

    def _toggle_jobs_fullscreen(self) -> None:
        if self._jobs_fullscreen:
            self._exit_jobs_fullscreen()
        else:
            self._enter_jobs_fullscreen()

    def _enter_jobs_fullscreen(self) -> None:
        if self._jobs_fullscreen:
            return
        self._jobs_fullscreen_restore = {
            "splitter_sizes": list(self.splitter.sizes()),
            "jobs_scroll_min_height": self.jobs_scroll.minimumHeight(),
        }
        self._jobs_fullscreen = True
        self.jobs_fullscreen_btn.setText("↙ خروج از تمام‌صفحه")
        self.jobs_fullscreen_btn.setToolTip("بازگشت به حالت عادی")
        self.jobs_fullscreen_btn.setProperty("active", True)
        self.jobs_fullscreen_btn.style().unpolish(self.jobs_fullscreen_btn)
        self.jobs_fullscreen_btn.style().polish(self.jobs_fullscreen_btn)

        # مخفی کردن همه‌چیز به‌جز کارت انتخاب ماژول‌ها
        self.log_actions.setVisible(False)
        self.status_bar.setVisible(False)
        self.info_card.setVisible(False)
        self.interval_box.setVisible(False)
        self.interval_label.setVisible(False)
        self.auto_enabled.setVisible(False)
        self.progress_bar.setVisible(False)
        self.progress_info_label.setVisible(False)
        self.manual_btn.setVisible(False)
        self.save_btn.setVisible(False)
        self.auto_state_label.setVisible(False)

        total = max(sum(self.splitter.sizes()), 1)
        self.splitter.setSizes([0, total])
        self.jobs_scroll.setMinimumHeight(max(480, self.height() - 160))

    def _exit_jobs_fullscreen(self) -> None:
        if not self._jobs_fullscreen:
            return
        self._jobs_fullscreen = False
        saved = self._jobs_fullscreen_restore or {}

        self.jobs_fullscreen_btn.setText("⛶ تمام‌صفحه")
        self.jobs_fullscreen_btn.setToolTip("مخفی‌کردن بقیه‌ی بخش‌ها تا لیست ماژول‌ها فضای بیشتری داشته باشد")
        self.jobs_fullscreen_btn.setProperty("active", False)
        self.jobs_fullscreen_btn.style().unpolish(self.jobs_fullscreen_btn)
        self.jobs_fullscreen_btn.style().polish(self.jobs_fullscreen_btn)

        self.log_actions.setVisible(True)
        self.status_bar.setVisible(True)
        self.info_card.setVisible(True)
        self.interval_box.setVisible(True)
        self.interval_label.setVisible(True)
        self.auto_enabled.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_info_label.setVisible(True)
        self.manual_btn.setVisible(True)
        self.save_btn.setVisible(True)
        self.auto_state_label.setVisible(True)

        sizes = saved.get("splitter_sizes")
        if isinstance(sizes, list) and len(sizes) >= 2:
            self.splitter.setSizes(sizes)
        self.jobs_scroll.setMinimumHeight(int(saved.get("jobs_scroll_min_height", 260)))

    def _build_job_row(self, job: AutoSyncJob) -> tuple[QFrame, QCheckBox]:
        row = QFrame()
        row.setObjectName("autoSyncJobRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setProperty("jobSelected", False)

        row.setMinimumHeight(AUTO_SYNC_JOB_ROW_HEIGHT)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 18, 10)
        row_layout.setSpacing(10)

        cb = QCheckBox()
        cb.setObjectName("autoSyncJobCheck")
        cb.setLayoutDirection(Qt.RightToLeft)
        cb.setMinimumWidth(28)
        cb.setChecked(bool(self.config.get(f"AUTO_{job.key}", False)))
        cb.setProperty("jobKey", job.key)
        cb.stateChanged.connect(self._on_job_check_changed)

        text_wrap = QWidget()
        text_wrap.setObjectName("autoSyncJobText")
        text_col = QVBoxLayout(text_wrap)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        title = QLabel(f"{job.icon}  {job.title}")
        title.setObjectName("autoSyncJobTitle")
        title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title.setWordWrap(True)
        title.setMinimumHeight(22)
        text_col.addWidget(title)
        hint = QLabel(job.hint)
        hint.setObjectName("autoSyncJobHint")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hint.setMinimumHeight(18)
        text_col.addWidget(hint)

        scope_row = self._build_scope_control(job, text_wrap)
        if scope_row is not None:
            text_col.addWidget(scope_row)

        row_layout.addWidget(text_wrap, 1)
        row_layout.addWidget(cb, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.checkboxes.append(cb)
        self._sync_job_row_state(row, cb.isChecked())

        def toggle_from_row(event, checkbox=cb, frame=row):
            if event.button() != Qt.LeftButton:
                return
            target = frame.childAt(event.pos())
            while target is not None:
                if isinstance(target, QCheckBox):
                    return
                target = target.parent()  # type: ignore[assignment]
            checkbox.setChecked(not checkbox.isChecked())

        row.mousePressEvent = toggle_from_row  # type: ignore[method-assign]
        return row, cb

    def _sync_job_row_state(self, row: QFrame, selected: bool):
        row.setProperty("jobSelected", selected)
        row.style().unpolish(row)
        row.style().polish(row)
        row.update()

    def _on_job_check_changed(self, *_args):
        sender = self.sender()
        if isinstance(sender, QCheckBox):
            for row in self._job_rows:
                cb = row.findChild(QCheckBox, "autoSyncJobCheck")
                if cb is sender:
                    self._sync_job_row_state(row, cb.isChecked())
                    break
        self._update_manual_button_text()

    def _select_all_jobs(self):
        for cb in self.checkboxes:
            cb.setChecked(True)

    def _clear_all_jobs(self):
        for cb in self.checkboxes:
            cb.setChecked(False)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_logs()
        if self.auto_enabled.isChecked() and not self.timer.isActive() and not self.is_batch_running:
            self._start_auto_timer(save=False)

    def _selected_script_keys(self) -> list[str]:
        keys: list[str] = []
        for cb in self.checkboxes:
            if cb.isChecked():
                keys.append(str(cb.property("jobKey")))
        return keys

    def _update_manual_button_text(self, *_args):
        labels = [
            AUTO_SYNC_JOB_BY_KEY[key].label
            for key in self._selected_script_keys()
            if key in AUTO_SYNC_JOB_BY_KEY
        ]
        if labels:
            full_text = "اجرای دستی: " + "، ".join(labels)
            self.manual_btn.setToolTip(full_text)
            if len(labels) == 1:
                text = full_text
            else:
                text = f"اجرای دستی ({len(labels)} ماژول)"
        else:
            text = "اجرای دستی همگام‌سازی"
            self.manual_btn.setToolTip("")
        self.manual_btn.setText(text)

    def _set_status(self, state: str, text: str):
        self.status_message.setText(text)
        self.status_bar.setProperty("state", state)
        self.status_bar.style().unpolish(self.status_bar)
        self.status_bar.style().polish(self.status_bar)

    def _resolve_runnable_scripts(self, selected: list[str], *, interactive: bool) -> list[str]:
        if not RECON_AWARE_KEYS.intersection(selected):
            return selected
        if load_product_woo_map():
            return selected
        message = (
            "فایل نگاشت محصول (product_woo_map) خالی است.\n"
            "اگر فروشگاه از قبل کالا دارد، ابتدا تب «تطبیق» را انجام دهید.\n\n"
            "ادامه می‌دهید؟"
        )
        if interactive:
            if ask_yes_no(self, "تطبیق پیشنهاد می‌شود", message, tone="warning", default_yes=False):
                return selected
            return [key for key in selected if key not in RECON_AWARE_KEYS]

        filtered = [key for key in selected if key not in RECON_AWARE_KEYS]
        if len(filtered) < len(selected):
            self._set_status(
                "warning",
                "⚠️ بدون نگاشت محصول، ماژول محصول/متغیر در اجرای خودکار رد شد",
            )
        return filtered

    def _ensure_ordersync_ready(self, selected: list[str], *, silent: bool = False) -> bool:
        if "ordersync" not in selected:
            return True
        ok = ensure_store_pages_ready(self, silent=silent)
        if not ok and silent:
            self._set_status(
                "warning",
                "⚠️ همگام‌سازی سفارشات رد شد — Cart/Checkout را در تنظیمات راه‌اندازی کنید",
            )
        return ok

    def _preflight_batch(self, selected: list[str], *, interactive: bool) -> list[str]:
        if not selected:
            if interactive:
                QMessageBox.warning(self, "هشدار", "هیچ ماژولی انتخاب نشده.")
            return []
        if not ensure_connectivity(self, need_sql=True, need_wc=True, live=True):
            return []
        runnable = self._resolve_runnable_scripts(selected, interactive=interactive)
        if not runnable:
            return []
        if not self._ensure_ordersync_ready(runnable, silent=not interactive):
            if interactive:
                return []
            runnable = [key for key in runnable if key != "ordersync"]
        if not runnable:
            return []
        if interactive and any(
            AUTO_SYNC_JOB_BY_KEY.get(key) and AUTO_SYNC_JOB_BY_KEY[key].touches_live_store
            for key in runnable
        ):
            if not confirm_live_site_backup(self, "همگام‌سازی خودکار (اجرای دستی)"):
                return []
        return runnable

    def run_manual(self):
        if self.is_batch_running:
            QMessageBox.information(self, "در حال اجرا", "یک دور همگام‌سازی هنوز تمام نشده است.")
            return
        selected = self._selected_script_keys()
        runnable = self._preflight_batch(selected, interactive=True)
        if not runnable:
            return
        self._start_batch(runnable)

    def run_auto(self):
        if not self.auto_enabled.isChecked() or self.is_batch_running:
            return
        interval_text = self._current_interval_text()
        interval_ms = AUTO_INTERVAL_MS.get(interval_text, AUTO_INTERVAL_MS["4 ساعت"])
        self._save_next_auto_run_at(interval_ms)
        selected = self._selected_script_keys()
        runnable = self._preflight_batch(selected, interactive=False)
        if not runnable:
            return
        self._start_batch(runnable)

    def _start_batch(self, selected: list[str]):
        self._begin_batch_run(len(selected))
        self.sync_worker = SyncWorker(selected)
        self.sync_worker.progress_updated.connect(self._on_progress_updated)
        self.sync_worker.batch_finished.connect(self._on_batch_finished)
        self.sync_worker.start()

    def _on_progress_updated(self, progress: int, _script_key: str, status_msg: str):
        self.progress_bar.setValue(progress)
        self.progress_info_label.setText(status_msg)
        self._set_status("loading", status_msg)

    def _on_batch_finished(self, ok_count: int, fail_count: int):
        self._finish_batch_run(ok_count, fail_count)

    def _begin_batch_run(self, total_count: int):
        self.is_batch_running = True
        self._set_auto_sync_running_flag(True)
        self.progress_bar.setValue(0)
        self.progress_info_label.setText(
            f"⚡ همگام‌سازی آغاز شد ({total_count} ماژول) — برنامه را نبندید"
        )
        self._set_status("loading", self.progress_info_label.text())
        self.manual_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        append_system_log("auto_sync", f"شروع دور همگام‌سازی ({total_count} ماژول)")
        self.blink_visible = True
        self.blink_timer.start(500)

    def _set_auto_sync_running_flag(self, running: bool) -> None:
        # این پرچم رو تو تنظیمات ذخیره می‌کنیم (نه فقط self.is_batch_running)
        # چون هدر برنامه یه آبجکت جداست و باید بدون نیاز به این‌که این تب
        # الان باز باشه، بفهمه همگام‌سازی الان واقعاً در حال اجراست یا نه —
        # تا به‌جای شمارش‌معکوس، «در حال انجام» رو نشون بده.
        # زمان شروع رو هم ذخیره می‌کنیم — اگه برنامه وسط همگام‌سازی به‌طور
        # ناگهانی بسته بشه (کرش/قطع برق/...)، این پرچم دیگه هیچ‌وقت False
        # نمی‌شه؛ هدر با چک‌کردن این زمان، بعد از یه مهلت منطقی، خودش
        # تشخیص می‌ده این پرچم قدیمی/گیرکرده‌ست و نادیده‌اش می‌گیره.
        try:
            cfg = load_secure_config(None) or {}
            cfg["AUTO_SYNC_RUNNING"] = bool(running)
            if running:
                from datetime import datetime
                cfg["AUTO_SYNC_RUNNING_SINCE"] = datetime.now().isoformat()
            else:
                cfg.pop("AUTO_SYNC_RUNNING_SINCE", None)
            save_secure_config(cfg)
        except Exception:
            pass

    def _finish_batch_run(self, ok_count: int, fail_count: int):
        self.is_batch_running = False
        self._set_auto_sync_running_flag(False)
        self.blink_timer.stop()
        self.progress_info_label.setStyleSheet("")
        self.manual_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.progress_bar.setValue(100 if fail_count == 0 else max(0, 100 - fail_count * 10))
        if fail_count == 0:
            msg = f"✅ {ok_count} ماژول با موفقیت اجرا شد"
            self._set_status("success", msg)
            append_system_log("auto_sync", f"پایان دور: {ok_count} موفق")
        else:
            msg = f"⚠️ {ok_count} موفق، {fail_count} ناموفق — جزئیات را در لاگ ببینید"
            self._set_status("warning", msg)
            append_system_log(
                "auto_sync",
                f"پایان دور: {ok_count} موفق، {fail_count} ناموفق",
                level="WARNING",
            )
        self.progress_info_label.setText(msg)
        self.refresh_logs()
        self._update_auto_state_ui()

    def _toggle_running_blink(self):
        if not self.is_batch_running:
            return
        self.blink_visible = not self.blink_visible
        opacity = "100%" if self.blink_visible else "35%"
        self.progress_info_label.setStyleSheet(f"opacity: {opacity};")

    def _current_interval_text(self) -> str:
        return _normalize_auto_interval(self.interval_box.currentText())

    def _persist_auto_interval(self, interval_text: str | None = None) -> str:
        normalized = _normalize_auto_interval(interval_text or self.interval_box.currentText())
        cfg = load_secure_config(None) or {}
        cfg["AUTO_INTERVAL"] = normalized
        save_secure_config(cfg)
        self.config = cfg
        return normalized

    def _restart_auto_timer(self):
        interval_text = self._current_interval_text()
        interval_ms = AUTO_INTERVAL_MS.get(interval_text, AUTO_INTERVAL_MS["4 ساعت"])
        self.timer.stop()
        self.timer.start(interval_ms)
        self._save_next_auto_run_at(interval_ms)
        self._update_auto_state_ui()

    def _save_next_auto_run_at(self, interval_ms: int) -> None:
        # فقط برای نمایش شمارش معکوس در هدر برنامه — مستقل از اینکه این
        # تب باز باشه یا نه (چون تایمر واقعی داخل خودِ این تبه، ولی هدر
        # باید حتی وقتی این تب هیچ‌وقت باز نشده هم بدونه چقدر مونده).
        from datetime import datetime, timedelta
        next_at = datetime.now() + timedelta(milliseconds=interval_ms)
        cfg = load_secure_config(None) or {}
        cfg["AUTO_NEXT_RUN_AT"] = next_at.isoformat()
        save_secure_config(cfg)
        self.config = cfg

    def _restore_auto_timer_from_config(self):
        if not self.auto_enabled.isChecked():
            return
        # به‌جای شروع دوباره‌ی کامل تایمر (که باعث می‌شد با هر بار باز کردن
        # برنامه، شمارش معکوس از نو کامل شروع بشه)، اول ببینیم از قبل یه
        # AUTO_NEXT_RUN_AT معتبر ذخیره شده یا نه — اگه بله و هنوز نگذشته،
        # دقیقاً همون زمان باقی‌مونده رو استفاده می‌کنیم.
        interval_text = self._current_interval_text()
        interval_ms = AUTO_INTERVAL_MS.get(interval_text, AUTO_INTERVAL_MS["4 ساعت"])

        remaining_ms = None
        next_at_raw = str(self.config.get("AUTO_NEXT_RUN_AT") or "").strip()
        if next_at_raw:
            try:
                from datetime import datetime
                next_at = datetime.fromisoformat(next_at_raw)
                remaining = (next_at - datetime.now()).total_seconds() * 1000
                if 0 < remaining <= interval_ms:
                    remaining_ms = int(remaining)
            except Exception:
                remaining_ms = None

        self.timer.stop()
        if remaining_ms is not None:
            self.timer.start(remaining_ms)
            self._update_auto_state_ui()
        else:
            # چیزی برای بازیابی نبود (اولین‌بار) یا زمان ذخیره‌شده گذشته/نامعتبر
            # بود — طبق قبل، یه دور کامل تازه شروع می‌کنیم.
            self._restart_auto_timer()

    def _start_auto_timer(self, *, save: bool = True):
        self._restart_auto_timer()
        if save:
            self.save_config()

    def _stop_auto_timer(self):
        self.timer.stop()
        self._update_auto_state_ui()

    def _on_auto_enabled_changed(self, *_args):
        if self.auto_enabled.isChecked():
            self._restart_auto_timer()
        else:
            self._stop_auto_timer()
        self.save_config()

    def _on_interval_changed(self, *_args):
        interval_text = self._current_interval_text()
        if self.interval_box.currentText().strip() != interval_text:
            self.interval_box.blockSignals(True)
            self.interval_box.setCurrentIndex(_interval_index(interval_text))
            self.interval_box.blockSignals(False)
        self._persist_auto_interval(interval_text)
        self._update_auto_state_ui()
        if self.auto_enabled.isChecked():
            self._restart_auto_timer()

    def _update_auto_state_ui(self):
        if self.auto_enabled.isChecked():
            interval = self._current_interval_text()
            self.auto_state_label.setText(f"▶️ اجرای اتوماتیک فعال — هر {interval}")
        else:
            self.auto_state_label.setText("⏹ اجرای اتوماتیک غیرفعال است")

    def save_config(self):
        try:
            config_to_save = load_secure_config(None) or {}
            for cb in self.checkboxes:
                key = str(cb.property("jobKey"))
                config_to_save[f"AUTO_{key}"] = cb.isChecked()
            config_to_save["AUTO_INTERVAL"] = self._current_interval_text()
            config_to_save["AUTO_ENABLED"] = self.auto_enabled.isChecked()
            save_secure_config(config_to_save)
            self.config = config_to_save
            self._update_auto_state_ui()
            if self.auto_enabled.isChecked():
                self._restart_auto_timer()
            self._set_status("success", "✅ تنظیمات همگام‌سازی خودکار ذخیره شد")
        except Exception as exc:
            self._set_status("error", f"❌ خطا در ذخیره تنظیمات: {exc}")

    def _filter_log_lines(self, lines: list[str]) -> list[str]:
        tokens = [token.lower() for token in AUTO_SYNC_LOG_TOKENS]
        return [line for line in lines if any(token in line.lower() for token in tokens)]

    def refresh_logs(self):
        try:
            lines = read_sync_log_lines()
        except OSError as exc:
            self.log_view.setPlainText(f"خطا در خواندن لاگ: {exc}")
            return
        if not lines:
            self.log_view.setPlainText("فایل لاگ یافت نشد.")
            return
        filtered = self._filter_log_lines(lines)
        tail = filtered[-200:] if filtered else lines[-80:]
        self.log_view.setPlainText(format_log_lines_jalali(tail))
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _refresh_logs_if_visible(self):
        if self.isVisible():
            self.refresh_logs()

    def clear_tab_logs(self):
        removed = clear_filtered_logs(list(AUTO_SYNC_LOG_TOKENS))
        self.refresh_logs()
        self._set_status("info", f"🧹 {removed} خط لاگ مرتبط با همگام‌سازی خودکار حذف شد")
