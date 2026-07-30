import os
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal, QTimer, QPoint
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QMessageBox,
    QFrame,
    QWidget,
)
from PyQt5.QtGui import QPixmap, QPainter, QFont, QColor, QLinearGradient, QIcon, QPainterPath, QRegion
from sync_app.core.password_line_edit import PasswordLineEdit


def _login_resource_path(filename):
    """مسیر داینامیک برای EXE و سورس (همان مسیر لوگوی هدر برنامه)"""
    from sync_app.core.sync_utils import resource_path

    return resource_path(filename)


class ConnectivityWorker(QObject):
    finished = pyqtSignal(bool, str, bool, str)

    def __init__(self, config, mode="all", *, fast=False):
        super().__init__()
        self.config = config or {}
        self.mode = (mode or "all").strip().lower()
        self.fast = bool(fast)

    def run(self):
        from sync_app.core.connectivity_service import (
            load_connectivity_cache,
            probe_all,
            probe_sql,
            probe_wc,
            save_connectivity_cache,
        )

        if self.mode == "wc":
            cache = load_connectivity_cache(self.config)
            sql_ok = bool(cache.get("sql_ok", False))
            sql_msg = str(cache.get("sql_msg") or "")
            sql_ms = float(cache.get("sql_ms") or 0)
            wc_ok, wc_msg, wc_ms = probe_wc(self.config, attempts=1 if self.fast else 2, fast=self.fast)
            save_connectivity_cache(
                sql_ok, sql_msg, wc_ok, wc_msg, sql_ms=sql_ms, wc_ms=wc_ms
            )
            self.finished.emit(sql_ok, sql_msg, wc_ok, wc_msg)
            return

        if self.mode == "sql":
            cache = load_connectivity_cache(self.config)
            wc_ok = bool(cache.get("wc_ok", False))
            wc_msg = str(cache.get("wc_msg") or "")
            wc_ms = float(cache.get("wc_ms") or 0)
            sql_ok, sql_msg, sql_ms = probe_sql(self.config)
            save_connectivity_cache(
                sql_ok, sql_msg, wc_ok, wc_msg, sql_ms=sql_ms, wc_ms=wc_ms
            )
            self.finished.emit(sql_ok, sql_msg, wc_ok, wc_msg)
            return

        result = probe_all(self.config)
        self.finished.emit(
            result["sql_ok"],
            result["sql_msg"],
            result["wc_ok"],
            result["wc_msg"],
        )


class LoginWindow(QDialog):
    def __init__(self, config, on_login_success=None):
        super().__init__()
        self.config = config or {}
        self.on_login_success = on_login_success
        self._check_thread = None
        self._check_worker = None
        self._drag_position = None

        self.setWindowTitle("ورود به نرم افزار پیچا")
        from sync_app.core.brand_assets import apply_brand_window_icon

        apply_brand_window_icon(self)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setFixedSize(892, 600)
        # نوارِ عنوانِ نیتیوِ ویندوز همیشه چپ‌به‌راسته (کنترلِ برنامه روش
        # نیست) و با راست‌چینیِ داخلِ فرم هم‌خوانی نداشت — چون این کلاس از
        # قبل دکمه‌ی بستنِ اختصاصی (×) و درگ با ماوس (mousePressEvent/
        # mouseMoveEvent) رو داره، دیگه نیازی به نوارِ عنوانِ نیتیو نیست؛
        # حالا رو همه‌ی پلتفرم‌ها (شاملِ ویندوز) بدون‌فریمه، تا کل فرم
        # (شاملِ ناحیه‌ی بالا) واقعاً راست‌چین باشه.
        # WA_TranslucentBackground حذف شد: روی بعضی سیستم‌های ویندوز (بسته به
        # درایور/کامپوزیتور DWM) پنجره‌ی بی‌فریمِ نیمه‌شفاف گاهی فقط نیمه
        # رندر می‌شد و کامل باز نمی‌شد (گزارشِ تکراریِ کاربر). حالا به‌جای
        # شفافیتِ واقعیِ سیستم‌عامل، پس‌زمینه‌ی خودِ دیالوگ رنگِ تیرهٔ گوشه‌ی
        # کارت رو می‌گیره — گوشه‌های بیرونِ کارتِ گردشده به‌جای شفاف بودن
        # همون رنگ تیره می‌مونن، ولی رندر همیشه کامل و قابل‌اعتماده.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)

        self._init_ui()
        QTimer.singleShot(1500, self.refresh_connectivity_status)

    def _init_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: #0f0a1e;
            }
            QFrame#formPanel {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1e1b4b, stop:0.5 #1a1035, stop:1 #0f0a1e);
                border: 1.5px solid rgba(99, 102, 241, 0.6);
                border-left: none;
                border-top-right-radius: 26px;
                border-bottom-right-radius: 26px;
            }
            QLabel {
                background: transparent;
                color: #d1d5db;
            }
            QLabel#welcomeTitle {
                color: #ffffff;
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#welcomeSubtitle {
                color: #a5b4fc;
                font-size: 11.5px;
                font-weight: 500;
            }
            QLabel#fieldLabel {
                color: #a5b4fc;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#statusLabel {
                color: #6b7280;
                font-size: 10px;
            }
            QLineEdit {
                background-color: rgba(15, 20, 40, 0.85);
                border: 1px solid rgba(99, 102, 241, 0.35);
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 13px;
                color: #e5e7eb;
                selection-background-color: #4f46e5;
            }
            QLineEdit:focus {
                border: 1.5px solid #818cf8;
                background-color: rgba(10, 12, 30, 0.95);
            }
            QComboBox {
                background-color: rgba(15, 20, 40, 0.85);
                border: 1px solid rgba(99, 102, 241, 0.35);
                border-radius: 10px;
                padding: 8px 14px;
                font-size: 13px;
                color: #e5e7eb;
                selection-background-color: #4f46e5;
            }
            QComboBox:focus {
                border: 1.5px solid #818cf8;
                background-color: rgba(10, 12, 30, 0.95);
            }
            QComboBox::drop-down {
                border: none;
                width: 26px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1035;
                color: #e5e7eb;
                selection-background-color: #4f46e5;
                border: 1px solid rgba(99, 102, 241, 0.5);
                outline: none;
            }
            QPushButton#loginBtn {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4f46e5, stop:1 #7c3aed);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
                padding: 11px;
                letter-spacing: 1px;
            }
            QPushButton#loginBtn:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4338ca, stop:1 #6d28d9);
            }
            QPushButton#loginBtn:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3730a3, stop:1 #581c87);
            }
            QPushButton#refreshBtn {
                background-color: transparent;
                color: #6366f1;
                border: 1px solid rgba(99, 102, 241, 0.4);
                border-radius: 8px;
                font-size: 10px;
                font-weight: 600;
                padding: 7px;
            }
            QPushButton#refreshBtn:hover {
                background-color: rgba(79, 70, 229, 0.12);
                color: #a5b4fc;
                border-color: rgba(99, 102, 241, 0.7);
            }
            QPushButton#closeBtn {
                background-color: transparent;
                color: rgba(129, 140, 248, 0.6);
                border: none;
                font-size: 18px;
                min-width: 28px;
                min-height: 28px;
                border-radius: 14px;
            }
            QPushButton#closeBtn:hover {
                background-color: rgba(239, 68, 68, 0.2);
                color: #f87171;
            }
        """)

        PANEL_H = 568
        PHOTO_W = 336
        FORM_W = 524

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)

        # پنلِ فرم و پنلِ عکس با هم یک کارتِ یکپارچه می‌سازن؛ چون Qt.RightToLeft
        # هست، اولین آیتمِ افزوده‌شده به QHBoxLayout راست‌ترین می‌شه — پس فرم
        # (که باید سمتِ راست باشه) اول اضافه می‌شه و پنلِ عکس (سمتِ چپ) دوم.
        form_panel = QFrame()
        form_panel.setObjectName("formPanel")
        form_panel.setFixedSize(FORM_W, PANEL_H)
        card_layout = QVBoxLayout(form_panel)
        card_layout.setContentsMargins(30, 12, 30, 20)
        card_layout.setSpacing(0)

        # اولویت با ویدئوی واقعیِ پیچا (Peecha.mp4) — اگه نبود، به عکسِ ثابت
        # (Peecha.png) یا گرادیانِ رزرو برمی‌گرده.
        video_panel = self._build_video_panel(PHOTO_W, PANEL_H)
        if video_panel is not None:
            self.photo_panel = video_panel
        else:
            self.photo_panel = QLabel()
            self.photo_panel.setFixedSize(PHOTO_W, PANEL_H)
            self.photo_panel.setStyleSheet("background: transparent;")
            self.photo_panel.setPixmap(self._build_photo_panel_pixmap(PHOTO_W, PANEL_H))

        # ردیف بالا: دکمه بستن
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addStretch()
        self.close_btn = QPushButton("\u00d7")
        self.close_btn.setObjectName("closeBtn")
        self.close_btn.setAutoDefault(False)
        self.close_btn.setDefault(False)
        self.close_btn.clicked.connect(self.reject)
        top_row.addWidget(self.close_btn)
        card_layout.addLayout(top_row)
        card_layout.addSpacing(10)

        # سرتیترِ خوش‌آمدگویی — هویتِ برند («پیچا» + تگلاین) حالا رویِ پنلِ
        # عکس نقاشی می‌شه (_build_photo_panel_pixmap)، پس اینجا فقط یک
        # سلامِ ساده کافیه.
        welcome_title = QLabel("خوش آمدید")
        welcome_title.setObjectName("welcomeTitle")
        welcome_title.setAlignment(Qt.AlignRight | Qt.AlignAbsolute)
        card_layout.addWidget(welcome_title)
        card_layout.addSpacing(4)

        welcome_subtitle = QLabel(
            "برای ادامه، وارد حساب کاربری خود شوید"
        )
        welcome_subtitle.setObjectName("welcomeSubtitle")
        welcome_subtitle.setAlignment(Qt.AlignRight | Qt.AlignAbsolute)
        card_layout.addWidget(welcome_subtitle)
        card_layout.addSpacing(18)

        # خط جداکننده
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(99, 102, 241, 0.2); border: none; margin: 0 8px;")
        card_layout.addWidget(divider)
        card_layout.addSpacing(12)

        # نام کاربری / پروفایل — کشوی و قابل‌ویرایش:
        # اگه پروفایل ذخیره‌ای وجود داشته باشه، از فهرست انتخاب می‌شه (هر پروفایل تنظیماتی کاملاً جدا داره)، وگرنه می‌شه یه نامِ جدید همون‌جا تایپ کرد.
        lbl_user = QLabel("\u0646\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631\u06cc / \u067e\u0631\u0648\u0641\u0627\u06cc\u0644")
        lbl_user.setObjectName("fieldLabel")
        lbl_user.setAlignment(Qt.AlignRight | Qt.AlignAbsolute)
        lbl_user.setStyleSheet("background: transparent; margin: 0; padding: 0;")
        card_layout.addWidget(lbl_user)
        card_layout.addSpacing(5)

        from sync_app.core.user_profile import list_profile_ids, load_last_profile_id

        self.username_input = QComboBox()
        self.username_input.setEditable(True)
        self.username_input.setInsertPolicy(QComboBox.NoInsert)
        self.username_input.lineEdit().setPlaceholderText("\u0646\u0627\u0645 \u06a9\u0627\u0631\u0628\u0631\u06cc \u062e\u0648\u062f \u0631\u0627 \u0648\u0627\u0631\u062f \u06a9\u0646\u06cc\u062f")
        existing_profiles = list_profile_ids()
        self.username_input.addItems(existing_profiles)

        prefill = (
            load_last_profile_id()
            or (self.config.get("APP_LOGIN_USERNAME") or "").strip()
            or (existing_profiles[0] if existing_profiles else "")
            or "admin"
        )
        idx = self.username_input.findText(prefill)
        if idx >= 0:
            self.username_input.setCurrentIndex(idx)
        else:
            self.username_input.setCurrentText(prefill)
        self.username_input.setFixedHeight(42)
        self.username_input.lineEdit().returnPressed.connect(self.try_login)
        card_layout.addWidget(self.username_input)
        card_layout.addSpacing(10)

        # رمز عبور
        lbl_pass = QLabel("\u0631\u0645\u0632 \u0639\u0628\u0648\u0631")
        lbl_pass.setObjectName("fieldLabel")
        lbl_pass.setAlignment(Qt.AlignRight | Qt.AlignAbsolute)
        lbl_pass.setStyleSheet("background: transparent; margin: 0; padding: 0;")
        card_layout.addWidget(lbl_pass)
        card_layout.addSpacing(5)

        self.password_input = PasswordLineEdit()
        self.password_input.set_toggle_dark_theme(True)
        self.password_input.setPlaceholderText("\u0631\u0645\u0632 \u0639\u0628\u0648\u0631 \u062e\u0648\u062f \u0631\u0627 \u0648\u0627\u0631\u062f \u06a9\u0646\u06cc\u062f")
        self.password_input.setFixedHeight(42)
        self.password_input.returnPressed.connect(self.try_login)
        card_layout.addWidget(self.password_input)
        card_layout.addSpacing(14)

        # دکمه ورود
        self.login_btn = QPushButton("\u2192  \u0648\u0631\u0648\u062f")
        self.login_btn.setObjectName("loginBtn")
        self.login_btn.setDefault(True)
        self.login_btn.setAutoDefault(True)
        self.login_btn.setFixedHeight(44)
        self.login_btn.clicked.connect(self.try_login)
        card_layout.addWidget(self.login_btn)
        card_layout.addSpacing(10)

        # وضعیت اتصالات
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        self.sql_status = QLabel(f"\U0001f535 {self._erp_label()}")
        self.sql_status.setObjectName("statusLabel")
        self.sql_status.setAlignment(Qt.AlignCenter)
        self.sql_status.setStyleSheet("background: transparent; color: #6b7280; font-size: 10px;")
        self.wc_status = QLabel(f"\U0001f535 {self._platform_label()}")
        self.wc_status.setObjectName("statusLabel")
        self.wc_status.setAlignment(Qt.AlignCenter)
        self.wc_status.setStyleSheet("background: transparent; color: #6b7280; font-size: 10px;")
        status_row.addWidget(self.wc_status)
        status_row.addWidget(self.sql_status)
        card_layout.addLayout(status_row)
        card_layout.addSpacing(3)

        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        self.details_label.setObjectName("statusLabel")
        self.details_label.setAlignment(Qt.AlignCenter)
        self.details_label.setStyleSheet("background: transparent; margin: 0; padding: 0; font-size: 9px; color: #6b7280;")
        self.details_label.setMaximumHeight(32)
        card_layout.addWidget(self.details_label)
        card_layout.addSpacing(6)

        # دکمه بازبینی
        self.refresh_btn = QPushButton("\U0001f504 \u0628\u0627\u0632\u0628\u06cc\u0646\u06cc \u0627\u062a\u0635\u0627\u0644\u0627\u062a")
        self.refresh_btn.setObjectName("refreshBtn")
        self.refresh_btn.setFixedHeight(34)
        self.refresh_btn.clicked.connect(self.refresh_connectivity_status)
        card_layout.addWidget(self.refresh_btn)

        root.addWidget(form_panel, 0, Qt.AlignVCenter)
        root.addWidget(self.photo_panel, 0, Qt.AlignVCenter)

    def _build_video_panel(self, width: int, height: int, radius: int = 26):
        """اگه sync_app/core/Peecha.gif موجود باشه، یه پنلِ متحرکِ زنده
        (لوپ‌شده) به‌جایِ عکسِ ثابت می‌سازه — با همون گردیِ دو گوشه‌ی بیرونی و
        متنِ برندِ رویِ یه سایه‌ی تیره، بالایِ پنل.

        چرا GIF به‌جایِ فایلِ ویدئوییِ mp4: پخشِ mp4 از طریقِ
        QtMultimedia/QMediaPlayer به پلاگین‌های کدکِ سیستم‌عامل (GStreamer
        روی لینوکس، WMF روی ویندوز) وابسته‌ست که ممکنه رویِ سیستمِ کاربر
        نصب/کامل نباشه (دقیقاً همین اتفاق افتاد: هم تویِ محیطِ توسعه، هم رویِ
        ویندوزِ کاربر، فریمِ ویدئو هیچ‌وقت نرسید). QMovie/GIF برعکس، بخشی از
        خودِ Qt (بدونِ نیازِ به پلاگینِ جداگانه) هست و همیشه کار می‌کنه. اگه
        فایل نباشه، None برمی‌گرده تا فراخوان به‌جاش عکسِ ثابت رو نشون بده."""
        path = _login_resource_path("Peecha.gif")
        if not path or not os.path.isfile(path):
            return None

        from PyQt5.QtGui import QMovie

        movie = QMovie(path)
        if not movie.isValid():
            return None

        container = QWidget()
        container.setFixedSize(width, height)
        container.setStyleSheet("background: transparent;")

        # لایه‌ی زمینه (عکسِ ثابت/گرادیان): اگه به هر دلیلی GIF لود نشه، این
        # پشتِ صحنه دیده می‌شه، نه یه مستطیلِ خالی.
        background = QLabel(container)
        background.setFixedSize(width, height)
        background.setStyleSheet("background: transparent;")
        background.setPixmap(self._build_panel_base_pixmap(width, height, radius))
        background.move(0, 0)

        movie_label = QLabel(container)
        movie_label.setFixedSize(width, height)
        movie_label.setStyleSheet("background: transparent;")
        movie_label.move(0, 0)

        clip_path = QPainterPath()
        clip_path.moveTo(width, 0)
        clip_path.lineTo(radius, 0)
        clip_path.arcTo(0, 0, radius * 2, radius * 2, 90, 90)
        clip_path.lineTo(0, height - radius)
        clip_path.arcTo(0, height - radius * 2, radius * 2, radius * 2, 180, 90)
        clip_path.lineTo(width, height)
        clip_path.closeSubpath()
        movie_label.setMask(QRegion(clip_path.toFillPolygon().toPolygon()))

        movie.setCacheMode(QMovie.CacheAll)
        # GIF خودش loop=0 (بی‌نهایت) رو تویِ فایل داره، پس نیازی به مدیریتِ
        # دستیِ لوپ (برخلافِ QMediaPlayer) نیست.
        movie_label.setMovie(movie)
        movie.start()

        # ارجاع نگه داشته می‌شه تا garbage-collect نشه
        self._gif_movie = movie

        # سایه‌ی تیره از پایین برای خواناییِ متنِ سفید
        scrim_h = 130
        scrim = QWidget(container)
        scrim.setGeometry(0, height - scrim_h, width, scrim_h)
        scrim.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 rgba(8, 5, 18, 0), stop:1 rgba(8, 5, 18, 0.85));"
        )

        def _brand_label(text, bottom_margin, h, font_size, bold, color):
            lbl = QLabel(text, container)
            # AlignAbsolute لازمه: بدونش، Qt.AlignRight برایِ متنِ فارسی
            # (که خودش راست‌به‌چپه) به‌عنوانِ «trailing» تفسیر می‌شه و
            # چپ‌چین می‌شه — صرف‌نظر از جهتِ خودِ ویجت.
            lbl.setAlignment(Qt.AlignRight | Qt.AlignAbsolute | Qt.AlignBottom)
            weight = 800 if bold else 600
            lbl.setStyleSheet(
                f"background: transparent; color: {color}; font-size: {font_size}px; font-weight: {weight};"
            )
            lbl.setGeometry(24, height - bottom_margin - h, width - 48, h)
            return lbl

        _brand_label("پیچا", 96, 40, 26, True, "#ffffff")
        _brand_label("همگام‌سازی هوشمند فروشگاه", 60, 24, 11, False, "#c7d2fe")
        _brand_label("دژاوو / هلو / سپیدار ↔ ووکامرس / پرستاشاپ", 34, 18, 9, False, "#94a3fd")

        return container

    def _build_panel_base_pixmap(self, width: int, height: int, radius: int = 26) -> QPixmap:
        """پایه‌ی مشترکِ پنلِ سمتِ چپ (بدونِ متن): عکسِ واقعیِ «پیچا»
        (sync_app/core/Peecha.png) با برشِ کاور، یا در نبودِ فایل، یه
        گرادیانِ بنفش/نیلیِ هم‌رنگ با تمِ برنامه — با سایه‌ی تیره از پایین و
        گردیِ دو گوشه‌ی بیرونی (بالا/پایینِ چپ). هم به‌عنوانِ خروجیِ نهاییِ
        حالتِ بدونِ ویدئو استفاده می‌شه (با متنِ نقاشی‌شده روش)، هم به‌عنوانِ
        لایه‌ی زمینه‌ی پنلِ ویدئویی (اگه فریمِ ویدئو به هر دلیلی نرسه، این
        لایه به‌جاش دیده می‌شه، نه یه مستطیلِ خالی)."""
        path = _login_resource_path("Peecha.png")
        base = QPixmap()
        if path and os.path.isfile(path):
            src = QPixmap(path)
            if not src.isNull():
                src = src.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x = max(0, (src.width() - width) // 2)
                y = max(0, (src.height() - height) // 2)
                base = src.copy(x, y, width, height)

        if base.isNull():
            base = QPixmap(width, height)
            gradient = QLinearGradient(0, 0, width, height)
            gradient.setColorAt(0, QColor(67, 56, 202))
            gradient.setColorAt(1, QColor(124, 58, 237))
            grad_painter = QPainter(base)
            grad_painter.setRenderHint(QPainter.Antialiasing)
            grad_painter.fillRect(base.rect(), gradient)
            grad_painter.end()

        result = QPixmap(width, height)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)

        clip_path = QPainterPath()
        clip_path.moveTo(width, 0)
        clip_path.lineTo(radius, 0)
        clip_path.arcTo(0, 0, radius * 2, radius * 2, 90, 90)
        clip_path.lineTo(0, height - radius)
        clip_path.arcTo(0, height - radius * 2, radius * 2, radius * 2, 180, 90)
        clip_path.lineTo(width, height)
        clip_path.closeSubpath()

        painter.setClipPath(clip_path)
        painter.drawPixmap(0, 0, base)

        # سایه‌ی تیره از پایین برای خواناییِ متنِ سفیدِ رویِ عکس
        shade = QLinearGradient(0, 0, 0, height)
        shade.setColorAt(0.0, QColor(15, 10, 30, 30))
        shade.setColorAt(0.55, QColor(15, 10, 30, 70))
        shade.setColorAt(1.0, QColor(8, 5, 18, 215))
        painter.fillPath(clip_path, shade)
        painter.setClipping(False)

        painter.setClipPath(clip_path)
        pen = painter.pen()
        pen.setColor(QColor(129, 140, 248, 140))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.drawPath(clip_path)
        painter.end()
        return result

    def _build_photo_panel_pixmap(self, width: int, height: int, radius: int = 26) -> QPixmap:
        """همون پایه‌ی مشترکِ _build_panel_base_pixmap، به‌علاوه‌ی عنوانِ
        برندِ نقاشی‌شده رویِ خودِ عکس (برایِ حالتی که ویدئو موجود نیست)."""
        result = self._build_panel_base_pixmap(width, height, radius)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)

        # متنِ برند رویِ عکس (راست‌چین، چون فقط این‌طوری با متنِ فارسی
        # هم‌خوان می‌مونه — Qt خودش شکل‌دهی/ترتیبِ راست‌به‌چپِ حروف رو انجام
        # می‌ده، این پرچم فقط جایگیریِ کلِ خط رو تویِ مستطیل تعیین می‌کنه)
        painter.setFont(QFont("IranSans", 26, QFont.Bold))
        painter.setPen(QColor(255, 255, 255))
        title_rect = result.rect().adjusted(24, 0, -24, -96)
        painter.drawText(title_rect, Qt.AlignRight | Qt.AlignBottom, "\u067e\u06cc\u0686\u0627")

        painter.setFont(QFont("IranSans", 11, QFont.DemiBold))
        painter.setPen(QColor(199, 210, 254))
        tagline_rect = result.rect().adjusted(24, 0, -24, -60)
        painter.drawText(
            tagline_rect,
            Qt.AlignRight | Qt.AlignBottom,
            "\u0647\u0645\u06af\u0627\u0645\u200c\u0633\u0627\u0632\u06cc \u0647\u0648\u0634\u0645\u0646\u062f \u0641\u0631\u0648\u0634\u06af\u0627\u0647",
        )

        painter.setFont(QFont("IranSans", 9))
        painter.setPen(QColor(148, 163, 253, 210))
        small_rect = result.rect().adjusted(24, 0, -24, -34)
        painter.drawText(
            small_rect,
            Qt.AlignRight | Qt.AlignBottom,
            "\u062f\u0698\u0627\u0648\u0648 / \u0647\u0644\u0648 / \u0633\u067e\u06cc\u062f\u0627\u0631 \u2194 \u0648\u0648\u06a9\u0627\u0645\u0631\u0633 / \u067e\u0631\u0633\u062a\u0627\u0634\u0627\u067e",
        )

        painter.end()
        return result

    def _erp_label(self, config=None) -> str:
        try:
            from sync_app.core.integrations.erp_provider import erp_provider_label

            return erp_provider_label(config if config is not None else self.config)
        except Exception:
            return "دژاوو"

    def _platform_label(self, config=None) -> str:
        try:
            from sync_app.core.integrations.commerce_provider import store_platform_label

            return store_platform_label(config if config is not None else self.config)
        except Exception:
            return "ووکامرس"

    def refresh_connectivity_status(self):
        if self._check_thread is not None:
            return

        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("درحال بررسی...")
        self.details_label.setText("")

        from sync_app.core.user_profile import activate_profile, load_secure_config_after_profile

        username = (self.username_input.currentText() or "").strip() or "admin"
        activate_profile(username)
        probe_config = load_secure_config_after_profile() or self.config
        self._active_config = probe_config
        # چون فروشگاهِ فعال ممکنه بین پروفایل‌ها فرق کنه (یکی ووکامرس، یکی
        # پرستاشاپ)، لیبل قبل از رسیدنِ نتیجه هم به‌روز می‌شه — نه صرفاً
        # همیشه «ووکامرس» (رفعِ گزارشِ کاربر که پرستاشاپ هم اشتباهی
        # «WooCommerce» نشون می‌داد).
        self.wc_status.setText(f"🔵 {self._platform_label(probe_config)}")
        self.wc_status.setStyleSheet("background: transparent; color: #6b7280; font-size: 10px;")

        self._check_thread = QThread(self)
        self._check_worker = ConnectivityWorker(probe_config)
        self._check_worker.moveToThread(self._check_thread)
        self._check_thread.started.connect(self._check_worker.run)
        self._check_worker.finished.connect(self._on_connectivity_finished)
        self._check_worker.finished.connect(self._check_thread.quit)
        self._check_worker.finished.connect(self._check_worker.deleteLater)
        self._check_thread.finished.connect(self._check_thread.deleteLater)
        self._check_thread.finished.connect(self._on_connectivity_thread_finished)
        self._check_thread.start()

    def _on_connectivity_finished(self, sql_ok, sql_msg, wc_ok, wc_msg):
        erp_label = self._erp_label(getattr(self, "_active_config", None))
        if sql_ok:
            self.sql_status.setText(f"🟢 {erp_label}")
            self.sql_status.setStyleSheet("color: #4ade80; font-size: 10px; font-weight: 600;")
        else:
            self.sql_status.setText(f"🔴 {erp_label}")
            self.sql_status.setStyleSheet("color: #f87171; font-size: 10px; font-weight: 600;")

        platform_name = self._platform_label(getattr(self, "_active_config", None))
        if wc_ok:
            self.wc_status.setText(f"🟢 {platform_name}")
            self.wc_status.setStyleSheet("color: #4ade80; font-size: 10px; font-weight: 600;")
        else:
            self.wc_status.setText(f"🔴 {platform_name}")
            self.wc_status.setStyleSheet("color: #f87171; font-size: 10px; font-weight: 600;")

        if not sql_ok or not wc_ok:
            short_msg = []
            if not sql_ok:
                short_msg.append(sql_msg[:50])
            if not wc_ok:
                short_msg.append(wc_msg[:50])
            self.details_label.setText("\n".join(short_msg))

    def _on_connectivity_thread_finished(self):
        self._check_thread = None
        self._check_worker = None
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("بازبینی وضعیت")

    def try_login(self):
        from sync_app.core.user_profile import (
            activate_profile,
            initialize_new_profile_config,
            load_secure_config_after_profile,
            save_last_profile_id,
        )

        entered_user = (self.username_input.currentText() or "").strip()
        entered_pass = self.password_input.text() or ""

        if not entered_user:
            QMessageBox.warning(self, "خطا", "نام کاربری را وارد کنید.")
            return

        activate_profile(entered_user)
        cfg = load_secure_config_after_profile()

        if not cfg.get("APP_LOGIN_PASSWORD"):
            initialize_new_profile_config(entered_user, entered_pass or "123456")
        else:
            expected_user = (cfg.get("APP_LOGIN_USERNAME") or entered_user).strip()
            expected_pass = str(cfg.get("APP_LOGIN_PASSWORD") or "")
            if entered_user != expected_user or entered_pass != expected_pass:
                QMessageBox.warning(self, "خطا", "نام کاربری یا رمز عبور اشتباه است.")
                return

        save_last_profile_id(entered_user)
        if callable(self.on_login_success):
            self.on_login_success()
        self.accept()

    def closeEvent(self, event):
        if self._check_thread is not None and self._check_thread.isRunning():
            self._check_thread.quit()
            self._check_thread.wait()
        event.accept()

    def mousePressEvent(self, event):
        """شروع drag فرم"""
        if event.button() == Qt.LeftButton:
            self._drag_position = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        """جابجایی فرم هنگام drag"""
        if event.buttons() == Qt.LeftButton and self._drag_position is not None:
            self.move(event.globalPos() - self._drag_position)
