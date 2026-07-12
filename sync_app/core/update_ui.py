"""دیالوگ بروزرسانی با نوار پیشرفت و مراحل اتصال."""

from __future__ import annotations

from PyQt5.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.app_version import APP_VERSION
from sync_app.core.message_boxes_fa import set_rtl_label_text


class HeaderUpdateSpinner(QLabel):
    """نشانگر کوچک چرخان در هدر هنگام بررسی بروزرسانی."""

    _FRAMES = ("◐", "◓", "◑", "◒")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("headerUpdateSpinner")
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(16, 16)
        self.setVisible(False)
        self.setToolTip("در حال بررسی بروزرسانی")
        self._idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(130)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._idx = (self._idx + 1) % len(self._FRAMES)
        self.setText(self._FRAMES[self._idx])

    def start(self) -> None:
        self._idx = 0
        self.setText(self._FRAMES[0])
        self.setVisible(True)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.setVisible(False)

    def apply_style(self, size: int = 12) -> None:
        self.setStyleSheet(
            f"color: rgba(255,255,255,0.92); font-size: {size}px; font-weight: 700; "
            "background: transparent;"
        )


class AppUpdateBanner(QFrame):
    """بنر بالای برنامه برای بررسی و اعلام بروزرسانی نرم‌افزار."""

    install_clicked = pyqtSignal()
    later_clicked = pyqtSignal()
    details_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("appUpdateBanner")
        self.setVisible(False)
        self._info: dict = {}
        self._palette: dict = {}
        self._fade_anim: QPropertyAnimation | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_checking_page())
        self._stack.addWidget(self._build_ready_page())
        root.addWidget(self._stack)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

    def _build_checking_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(14)

        self._checking_icon = QLabel("⟳")
        self._checking_icon.setObjectName("appUpdateBannerCheckingIcon")
        self._checking_icon.setAlignment(Qt.AlignCenter)
        self._checking_icon.setFixedSize(40, 40)
        layout.addWidget(self._checking_icon, 0)

        col = QVBoxLayout()
        col.setSpacing(6)
        self._checking_title = QLabel()
        self._checking_title.setObjectName("appUpdateBannerCheckingTitle")
        set_rtl_label_text(self._checking_title, "در حال بررسی بروزرسانی...")
        col.addWidget(self._checking_title)

        self._checking_progress = QProgressBar()
        self._checking_progress.setObjectName("appUpdateBannerCheckingBar")
        self._checking_progress.setRange(0, 0)
        self._checking_progress.setFixedHeight(6)
        self._checking_progress.setTextVisible(False)
        col.addWidget(self._checking_progress)

        self._checking_detail = QLabel()
        self._checking_detail.setObjectName("appUpdateBannerCheckingDetail")
        from sync_app.core.license_remote import license_server_host
        set_rtl_label_text(self._checking_detail, f"اتصال به {license_server_host()}")
        col.addWidget(self._checking_detail)
        layout.addLayout(col, 1)
        return page

    def _build_ready_page(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        self._ready_icon = QLabel("⬆")
        self._ready_icon.setObjectName("appUpdateBannerReadyIcon")
        self._ready_icon.setAlignment(Qt.AlignCenter)
        self._ready_icon.setFixedSize(44, 44)
        layout.addWidget(self._ready_icon, 0)

        col = QVBoxLayout()
        col.setSpacing(4)

        self._ready_title = QLabel()
        self._ready_title.setObjectName("appUpdateBannerReadyTitle")
        set_rtl_label_text(self._ready_title, "بروزرسانی جدید PeechaSync")
        col.addWidget(self._ready_title)

        self._ready_versions = QLabel()
        self._ready_versions.setObjectName("appUpdateBannerReadyVersions")
        col.addWidget(self._ready_versions)

        self._ready_changelog = QLabel()
        self._ready_changelog.setObjectName("appUpdateBannerReadyChangelog")
        self._ready_changelog.setWordWrap(True)
        self._ready_changelog.setVisible(False)
        col.addWidget(self._ready_changelog)
        layout.addLayout(col, 1)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        btn_col.addStretch(1)

        self._install_btn = QPushButton("دانلود و نصب")
        self._install_btn.setObjectName("appUpdateBannerInstallBtn")
        self._install_btn.setCursor(Qt.PointingHandCursor)
        self._install_btn.clicked.connect(self.install_clicked.emit)
        btn_col.addWidget(self._install_btn)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._details_btn = QPushButton("جزئیات")
        self._details_btn.setObjectName("appUpdateBannerDetailsBtn")
        self._details_btn.setCursor(Qt.PointingHandCursor)
        self._details_btn.clicked.connect(self.details_clicked.emit)
        self._later_btn = QPushButton("بعداً")
        self._later_btn.setObjectName("appUpdateBannerLaterBtn")
        self._later_btn.setCursor(Qt.PointingHandCursor)
        self._later_btn.clicked.connect(self.later_clicked.emit)
        btn_row.addWidget(self._details_btn)
        btn_row.addWidget(self._later_btn)
        btn_col.addLayout(btn_row)
        btn_col.addStretch(1)
        layout.addLayout(btn_col, 0)
        return page

    def _animate_in(self) -> None:
        self.setVisible(True)
        if self._fade_anim is not None:
            self._fade_anim.stop()
        self._fade_anim = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade_anim.setDuration(320)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.start()

    def hide_banner(self) -> None:
        self.setVisible(False)
        self._opacity.setOpacity(0.0)
        self._info = {}

    def set_checking(self, active: bool) -> None:
        if not active:
            if not self._info.get("update_available"):
                self.hide_banner()
            return
        self._stack.setCurrentIndex(0)
        self._animate_in()

    def show_update(self, info: dict) -> None:
        from sync_app.core.app_update import update_banner_text

        self._info = dict(info or {})
        if not self._info.get("update_available"):
            self.hide_banner()
            return

        latest = str(self._info.get("latest_version") or APP_VERSION)
        current = str(self._info.get("current_version") or APP_VERSION)
        changelog = str(self._info.get("changelog") or "").strip()

        set_rtl_label_text(self._ready_title, f"نسخه {latest} آماده نصب است")
        version_html = (
            f'<span style="background:rgba(255,255,255,0.22);padding:2px 8px;border-radius:6px;">'
            f'فعلی {current}</span>'
            f' <span style="color:#86efac;font-weight:700;">-&gt;</span> '
            f'<span style="background:rgba(255,255,255,0.35);padding:2px 10px;border-radius:6px;font-weight:700;">'
            f'{latest}</span>'
        )
        self._ready_versions.setTextFormat(Qt.RichText)
        self._ready_versions.setText(
            f'<div align="right" dir="rtl">{version_html}</div>'
        )

        if changelog:
            preview = changelog.split("\n", 1)[0].strip()
            if len(preview) > 120:
                preview = preview[:117] + "..."
            set_rtl_label_text(self._ready_changelog, preview)
            self._ready_changelog.setVisible(True)
        else:
            set_rtl_label_text(self._ready_changelog, update_banner_text(self._info))
            self._ready_changelog.setVisible(True)

        self._install_btn.setText(f"نصب {latest}")
        self._install_btn.setEnabled(True)
        self._stack.setCurrentIndex(1)
        self._animate_in()

    def set_install_busy(self, busy: bool, *, latest: str = "") -> None:
        self._install_btn.setEnabled(not busy)
        if busy:
            self._install_btn.setText("در حال بروزرسانی...")
        elif latest:
            self._install_btn.setText(f"نصب {latest}")

    def apply_theme(self, palette: dict, theme_name: str = "navy") -> None:
        self._palette = dict(palette or {})
        primary = self._palette.get("primary", "#1a2785")
        hover = self._palette.get("hover", "#243399")
        accent = "#22c55e" if theme_name == "green" else "#3b82f6"
        if theme_name == "red":
            accent = "#f87171"

        self.setStyleSheet(
            f"QFrame#appUpdateBanner {{"
            f"  background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {primary}, stop:0.55 #1e3a8a, stop:1 {hover});"
            f"  border-bottom: 2px solid rgba(255,255,255,0.12);"
            f"}}"
            f"QLabel#appUpdateBannerCheckingIcon, QLabel#appUpdateBannerReadyIcon {{"
            f"  background: rgba(255,255,255,0.14); color: #fff; font-size: 20px;"
            f"  border-radius: 22px; font-weight: 700;"
            f"}}"
            f"QLabel#appUpdateBannerCheckingTitle, QLabel#appUpdateBannerReadyTitle {{"
            f"  color: #fff; font-size: 15px; font-weight: 700; background: transparent;"
            f"}}"
            f"QLabel#appUpdateBannerCheckingDetail, QLabel#appUpdateBannerReadyVersions,"
            f"QLabel#appUpdateBannerReadyChangelog {{"
            f"  color: rgba(255,255,255,0.88); font-size: 12px; background: transparent;"
            f"}}"
            f"QProgressBar#appUpdateBannerCheckingBar {{"
            f"  background: rgba(255,255,255,0.2); border: none; border-radius: 3px;"
            f"}}"
            f"QProgressBar#appUpdateBannerCheckingBar::chunk {{"
            f"  background: {accent}; border-radius: 3px;"
            f"}}"
            f"QPushButton#appUpdateBannerInstallBtn {{"
            f"  background: {accent}; color: #fff; border: none; border-radius: 10px;"
            f"  padding: 9px 18px; font-weight: 700; min-width: 110px;"
            f"}}"
            f"QPushButton#appUpdateBannerInstallBtn:hover {{ background: #4ade80; }}"
            f"QPushButton#appUpdateBannerInstallBtn:disabled {{ background: rgba(255,255,255,0.25); }}"
            f"QPushButton#appUpdateBannerDetailsBtn, QPushButton#appUpdateBannerLaterBtn {{"
            f"  background: transparent; color: rgba(255,255,255,0.92);"
            f"  border: 1px solid rgba(255,255,255,0.35); border-radius: 8px; padding: 6px 12px;"
            f"}}"
            f"QPushButton#appUpdateBannerDetailsBtn:hover, QPushButton#appUpdateBannerLaterBtn:hover {{"
            f"  background: rgba(255,255,255,0.12);"
            f"}}"
        )


def humanize_update_error(err: str) -> str:
    from sync_app.core.license_remote import license_server_host

    host = license_server_host()
    code = (err or "").strip().lower()
    if not code:
        return "خطای ناشناخته در بروزرسانی."
    if code == "timeout":
        return (
            f"اتصال به {host} کند شد یا قطع شد.\n\n"
            "اینترنت، VPN یا فایروال را چک کنید و دوباره بزنید."
        )
    if code == "connection_error":
        return (
            f"به {host} وصل نشد.\n\n"
            "DNS، VPN یا مسدودیت شبکه را بررسی کنید."
        )
    if code == "no_license_key":
        return "کلید لایسنس ثبت نشده — ابتدا فعال‌سازی کنید."
    if code == "no_download_url":
        return (
            "آدرس دانلود بروزرسانی از سرور دریافت نشد.\n\n"
            f"احتمالاً فایل بروزرسانی روی {host} کامل آپلود نشده است.\n"
            "از Setup ZIP نسخه جدید استفاده کنید:\n"
            "Extract → Install PeechaSync.bat → دکمه ۳ (حذف کامل) → دکمه ۱ (نصب)"
        )
    if code.startswith("invalid_zip"):
        return (
            "فایل دانلود‌شده معتبر نیست (ZIP خراب یا ناقص).\n\n"
            + err
            + "\n\n"
            "فایل کش را پاک کنید و دوباره امتحان کنید، یا از Setup ZIP نصب کنید."
        )
    if "no_update_source" in code or code == "http 404":
        return (
            f"بسته بروزرسانی روی {host} موجود نیست.\n\n"
            "از Setup ZIP (PeechaSync-Setup-1.1.x-Portable.zip) نصب دستی انجام دهید."
        )
    if "invalid api key" in code or code == "forbidden":
        return (
            f"کلید API لایسنس با {host} یکی نیست.\n\n"
            "wp-admin -> لایسنس‌های پیچا -> تنظیمات -> کلید API را کپی کنید\n"
            "و در تنظیمات PeechaSync (کلید API لایسنس) بگذارید.\n"
            "یا فیلد کلید API را در افزونه خالی کنید و ذخیره کنید."
        )
    if "license key not found" in code or code == "not_found":
        return (
            f"{host} به لایسنس دسترسی نداشت.\n\n"
            "لایسنس روی این دستگاه فعال است ولی بررسی بروزرسانی به سرور نیاز دارد.\n"
            "VPN را روشن کنید و دوباره بزنید.\n"
            "اگر باز همین بود، با VPN روشن یک‌بار لایسنس را دوباره فعال کنید."
        )
    if code.startswith("http "):
        return f"سرور پاسخ خطا داد ({err}).\n\nبعداً دوباره امتحان کنید."
    return err


class UpdateProgressDialog(QDialog):
    def __init__(self, parent=None, *, title: str = "بروزرسانی"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setLayoutDirection(Qt.RightToLeft)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("updateProgressTitle")
        set_rtl_label_text(self.title_label, title)
        root.addWidget(self.title_label)

        self.status_label = QLabel()
        self.status_label.setObjectName("updateProgressStatus")
        set_rtl_label_text(self.status_label, "در حال آماده‌سازی...")
        root.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setObjectName("updateProgressBar")
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        root.addWidget(self.progress)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("updateProgressDetail")
        self.detail_label.setWordWrap(True)
        set_rtl_label_text(self.detail_label, "")
        self.detail_label.setVisible(False)
        root.addWidget(self.detail_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("انصراف")
        self.cancel_btn.setVisible(False)
        btn_row.addWidget(self.cancel_btn)
        root.addLayout(btn_row)

        self.setStyleSheet(
            "QDialog { background: #f8fafc; }"
            "QLabel#updateProgressTitle { font-size: 16px; font-weight: 700; color: #0f172a; }"
            "QLabel#updateProgressStatus { font-size: 13px; color: #334155; }"
            "QLabel#updateProgressDetail { font-size: 12px; color: #64748b; }"
            "QProgressBar#updateProgressBar {"
            "  border: 1px solid #cbd5e1; border-radius: 8px; height: 22px;"
            "  background: #e2e8f0; text-align: center; color: #0f172a;"
            "}"
            "QProgressBar#updateProgressBar::chunk {"
            "  background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2563eb, stop:1 #1d4ed8);"
            "  border-radius: 7px;"
            "}"
        )

    def set_status(self, text: str, *, detail: str = "") -> None:
        set_rtl_label_text(self.status_label, text)
        if detail:
            set_rtl_label_text(self.detail_label, detail)
            self.detail_label.setVisible(True)
        else:
            self.detail_label.setVisible(False)

    def set_indeterminate(self, active: bool = True) -> None:
        if active:
            self.progress.setRange(0, 0)
            self.progress.setFormat("")
        else:
            self.progress.setRange(0, 100)

    def set_percent(self, value: int, *, text: str | None = None) -> None:
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(max(0, min(100, int(value))))
        if text is not None:
            self.progress.setFormat(text)
        else:
            self.progress.setFormat("%p%")


class UpdateAvailableDialog(QDialog):
    def __init__(self, parent, info: dict):
        super().__init__(parent)
        self.setWindowTitle("بروزرسانی جدید")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setLayoutDirection(Qt.RightToLeft)
        self._info = info

        latest = str(info.get("latest_version") or APP_VERSION)
        current = str(info.get("current_version") or APP_VERSION)
        changelog = str(info.get("changelog") or "").strip()

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        badge = QFrame()
        badge.setObjectName("updateAvailableBadge")
        badge_layout = QVBoxLayout(badge)
        badge_layout.setContentsMargins(16, 14, 16, 14)
        badge_layout.setSpacing(6)

        headline = QLabel()
        headline.setObjectName("updateAvailableHeadline")
        set_rtl_label_text(headline, f"نسخه {latest} آماده نصب است")
        badge_layout.addWidget(headline)

        versions = QLabel()
        versions.setObjectName("updateAvailableVersions")
        set_rtl_label_text(
            versions,
            f"نسخه فعلی شما: {current}\nنسخه جدید: {latest}",
            multiline=True,
        )
        badge_layout.addWidget(versions)
        root.addWidget(badge)

        if changelog:
            cap = QLabel("تغییرات این نسخه")
            cap.setObjectName("updateAvailableChangelogCap")
            set_rtl_label_text(cap, "تغییرات این نسخه")
            root.addWidget(cap)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setMaximumHeight(180)
            body = QLabel()
            body.setWordWrap(True)
            set_rtl_label_text(body, changelog, multiline=True)
            scroll.setWidget(body)
            root.addWidget(scroll)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.later_btn = QPushButton("بعداً")
        self.install_btn = QPushButton("دانلود و نصب")
        self.install_btn.setDefault(True)
        self.install_btn.setObjectName("updateAvailableInstallBtn")
        btn_row.addWidget(self.later_btn)
        btn_row.addWidget(self.install_btn)
        root.addLayout(btn_row)

        self.later_btn.clicked.connect(self.reject)
        self.install_btn.clicked.connect(self.accept)

        self.setStyleSheet(
            "QDialog { background: #f8fafc; }"
            "QFrame#updateAvailableBadge {"
            "  background: #ecfdf5; border: 1px solid #6ee7b7; border-radius: 12px;"
            "}"
            "QLabel#updateAvailableHeadline { font-size: 17px; font-weight: 700; color: #065f46; }"
            "QLabel#updateAvailableVersions { font-size: 13px; color: #047857; }"
            "QLabel#updateAvailableChangelogCap { font-size: 13px; font-weight: 600; color: #334155; }"
            "QPushButton#updateAvailableInstallBtn {"
            "  background: #2563eb; color: white; border: none; border-radius: 8px;"
            "  padding: 10px 18px; font-weight: 700; min-width: 120px;"
            "}"
            "QPushButton#updateAvailableInstallBtn:hover { background: #1d4ed8; }"
            "QPushButton { border-radius: 8px; padding: 8px 14px; }"
        )


class UpdateCheckWorker(QObject):
    status = pyqtSignal(str, str)
    finished = pyqtSignal(bool, object, str)

    def __init__(self, hwid: str):
        super().__init__()
        self.hwid = hwid

    def run(self) -> None:
        from sync_app.core.app_update import lookup_update_info
        from sync_app.core.license_remote import license_server_host

        host = license_server_host()
        self.status.emit("اتصال به سرور لایسنس", f"{host} / WordPress API")
        ok, info, err = lookup_update_info(hwid=self.hwid)
        if ok:
            self.status.emit("بررسی نسخه انجام شد", "مقایسه با GitHub / آینه سرور")
        self.finished.emit(ok, info, err)


class UpdateDownloadWorker(QObject):
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(bool, str, bool)

    def __init__(self, info: dict, hwid: str, *, force_download: bool = False, ignore_apply_block: bool = False):
        super().__init__()
        self.info = info
        self.hwid = hwid
        self.force_download = force_download
        self.ignore_apply_block = ignore_apply_block

    def run(self) -> None:
        from sync_app.core.app_update import download_and_apply_update

        def on_progress(done: int, total: int, label: str) -> None:
            self.progress.emit(done, total, label)

        ok, msg, restart = download_and_apply_update(
            self.info,
            hwid=self.hwid,
            progress=on_progress,
            force_download=self.force_download,
            ignore_apply_block=self.ignore_apply_block,
        )
        self.finished.emit(ok, msg, restart)


def _pump_events() -> None:
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def run_update_check(parent, hwid: str) -> tuple[bool, dict, str]:
    from sync_app.core.license_remote import license_server_host

    dialog = UpdateProgressDialog(parent, title="بررسی بروزرسانی")
    dialog.set_status("شروع بررسی...", detail=f"اتصال به {license_server_host()}")
    dialog.show()
    _pump_events()

    thread = QThread(parent)
    worker = UpdateCheckWorker(hwid)
    worker.moveToThread(thread)

    result: dict = {"ok": False, "info": {}, "err": ""}

    def on_status(title: str, detail: str) -> None:
        dialog.set_status(title, detail=detail)
        _pump_events()

    def on_done(ok: bool, info: object, err: str) -> None:
        result["ok"] = ok
        result["info"] = info if isinstance(info, dict) else {}
        result["err"] = err or ""

    worker.status.connect(on_status)
    worker.finished.connect(on_done)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    thread.start()
    while thread.isRunning():
        _pump_events()
        thread.wait(50)

    dialog.close()
    return result["ok"], result["info"], result["err"]


def prompt_cached_update_choice(parent, version: str) -> str:
    """install | redownload | cancel"""
    from sync_app.core.message_boxes_fa import rtl_html

    box = QMessageBox(parent)
    box.setWindowTitle("بروزرسانی")
    box.setIcon(QMessageBox.Question)
    box.setTextFormat(Qt.RichText)
    box.setText(
        rtl_html(
            f"بسته نسخه {version} قبلاً روی این سیستم دانلود شده است.\n\n"
            "نصب از فایل موجود انجام شود یا دوباره از سرور دانلود شود؟"
        )
    )
    install_btn = box.addButton("نصب فایل موجود", QMessageBox.AcceptRole)
    redownload_btn = box.addButton("دانلود دوباره", QMessageBox.ActionRole)
    box.addButton("انصراف", QMessageBox.RejectRole)
    box.exec_()
    clicked = box.clickedButton()
    if clicked == install_btn:
        return "install"
    if clicked == redownload_btn:
        return "redownload"
    return "cancel"


def run_update_download(
    parent,
    info: dict,
    hwid: str,
    *,
    force_download: bool = False,
    ask_cached: bool = False,
    ignore_apply_block: bool = False,
) -> tuple[bool, str, bool]:
    from sync_app.core.app_update import find_cached_update_zip, should_block_update_apply

    latest = str(info.get("latest_version") or APP_VERSION)
    if not ignore_apply_block:
        blocked, block_msg = should_block_update_apply()
        if blocked:
            return False, block_msg, False
    if ask_cached and not force_download and find_cached_update_zip(latest):
        choice = prompt_cached_update_choice(parent, latest)
        if choice == "cancel":
            return False, "", False
        if choice == "redownload":
            force_download = True

    from sync_app.core.license_remote import license_server_host

    dialog = UpdateProgressDialog(parent, title="دریافت بروزرسانی")
    dialog.set_status("آماده‌سازی دانلود...", detail=f"سرور {license_server_host()}")
    dialog.set_indeterminate(True)
    dialog.show()
    _pump_events()

    thread = QThread(parent)
    worker = UpdateDownloadWorker(
        info,
        hwid,
        force_download=force_download,
        ignore_apply_block=ignore_apply_block,
    )
    worker.moveToThread(thread)

    outcome = {"ok": False, "msg": "", "restart": False}

    def on_status(text: str) -> None:
        dialog.set_status(text)
        _pump_events()

    def on_progress(done: int, total: int, label: str) -> None:
        dialog.set_indeterminate(False)
        if total > 0:
            pct = int(done * 100 / total)
            mb_done = done / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            dialog.set_percent(
                pct,
                text=f"{mb_done:.1f} / {mb_total:.1f} MB",
            )
            dialog.set_status("در حال دانلود بسته بروزرسانی", detail=label)
        elif "بسته دانلود" in label or "استفاده از بسته" in label:
            dialog.set_percent(100, text="آماده")
            dialog.set_status("نصب بروزرسانی...", detail=label)
        else:
            dialog.set_indeterminate(True)
            dialog.set_status(label)
        _pump_events()

    def on_done(ok: bool, msg: str, restart: bool) -> None:
        outcome["ok"] = ok
        outcome["msg"] = msg or ""
        outcome["restart"] = bool(restart)

    worker.status.connect(on_status)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_done)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    thread.start()
    while thread.isRunning():
        _pump_events()
        thread.wait(50)

    if outcome["ok"]:
        dialog.set_percent(100, text="100%")
        dialog.set_status("در حال اعمال بروزرسانی...")
    else:
        dialog.set_status("بروزرسانی ناموفق بود", detail=outcome["msg"])
        dialog.set_indeterminate(False)
        dialog.set_percent(0)
    _pump_events()
    dialog.close()
    return outcome["ok"], outcome["msg"], outcome["restart"]


def prompt_and_run_update(parent, info: dict, hwid: str) -> bool:
    from sync_app.core.app_update import summarize_update
    from PyQt5.QtWidgets import QApplication

    if not info.get("update_available"):
        QMessageBox.information(parent, "بروزرسانی", summarize_update(info))
        return False

    ok, msg, restart = run_update_download(parent, info, hwid, ask_cached=True)
    if not ok:
        if not msg:
            return False
        QMessageBox.warning(parent, "بروزرسانی", humanize_update_error(msg) if msg in (
            "timeout", "connection_error"
        ) else (msg or "بروزرسانی ناموفق بود."))
        return False

    if restart:
        import os

        from sync_app.core.app_update import _kill_peecha_processes

        _kill_peecha_processes()
        os._exit(0)
    return True
