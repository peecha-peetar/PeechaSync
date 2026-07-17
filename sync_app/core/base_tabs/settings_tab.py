from PyQt5.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QLabel, QPushButton,
    QHBoxLayout, QMessageBox, QComboBox, QVBoxLayout, QGroupBox, QScrollArea, QPlainTextEdit, QGridLayout, QCheckBox,
    QApplication, QFileDialog, QSpinBox, QDoubleSpinBox, QListWidget, QListWidgetItem, QLayout, QDialog,
)
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal, QPropertyAnimation, QEasingCurve, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from datetime import datetime
import copy
import os
import time

# مسیر تنظیمات
from sync_app.core.secure_config_loader import load_secure_config, save_secure_config
from sync_app.core.password_line_edit import PasswordLineEdit
from sync_app.core.event_notifier import append_system_log
from sync_app.core.integrations.erp_provider import get_provider
from sync_app.core.field_sync_config import ALL_FIELD_GROUPS, FORCE_FULL_SYNC_FIELDS

HAS_WCAPI = None
_pyodbc = None


def _get_pyodbc():
    global _pyodbc
    if _pyodbc is not None:
        return _pyodbc
    try:
        import pyodbc as mod
        _pyodbc = mod
        return mod
    except ImportError:
        class MockDB:
            def connect(*args, **kwargs):
                raise Exception("ماژول pyodbc نصب نشده است.")
        _pyodbc = MockDB()
        return _pyodbc


def _has_wcapi():
    global HAS_WCAPI
    if HAS_WCAPI is not None:
        return HAS_WCAPI
    try:
        from woocommerce import API  # noqa: F401
        HAS_WCAPI = True
    except ImportError:
        HAS_WCAPI = False
    return HAS_WCAPI

BRAND_COLOR = "#1a2785"


class WooTestWorker(QObject):
    """Worker غیرهمزمان برای تست اتصال ووکامرس با endpoint سبک و retry."""
    log = pyqtSignal(str)
    success = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = dict(config or {})

    def run(self):
        try:
            from sync_app.core.connectivity_service import (
                classify_network_error,
                load_connectivity_cache,
                network_error_user_hint,
                probe_wc,
                save_connectivity_cache,
            )
            from sync_app.core.wc_sync_helper import apply_network_overrides

            cfg = dict(self.config)
            url = (cfg.get("WC_URL") or "").strip()
            ck = (cfg.get("WC_CONSUMER_KEY") or "").strip()
            cs = (cfg.get("WC_CONSUMER_SECRET") or "").strip()
            if not url:
                raise Exception("آدرس ووکامرس خالی است.")
            if not ck or not cs:
                raise Exception("Consumer Key / Consumer Secret وارد نشده است.")

            apply_network_overrides(cfg)
            from sync_app.core.connectivity_service import _wc_probe_urls
            from sync_app.core.wc_runtime_audit import audit_wc_runtime, format_wc_audit_report

            audit = audit_wc_runtime(cfg)
            self.log.emit(format_wc_audit_report(audit))
            for probe_url in _wc_probe_urls(cfg):
                if probe_url:
                    self.log.emit(f"→ درخواست HTTP: {probe_url}")
            self.log.emit(f"Timeout: {cfg.get('WC_READ_TIMEOUT', cfg.get('WC_TIMEOUT', 120))} ثانیه")
            self.log.emit("در حال تست WooCommerce (تنظیمات + API دسته‌بندی)...")

            ok, msg, ms = False, "", 0.0
            for attempt in range(1, 4):
                self.log.emit(f"تلاش {attempt}/3...")
                ok, msg, ms = probe_wc(cfg, attempts=2)
                if ok:
                    break
                self.log.emit(f"ناموفق: {msg}")
                cat = classify_network_error(msg)
                if attempt < 3 and cat in ("timeout", "ssl", "unknown"):
                    time.sleep(1.5 * attempt)
                    continue
                break

            if ok:
                self.log.emit(f"✅ {msg}")
                cache = load_connectivity_cache(cfg)
                sql_ok = bool(cache.get("sql_ok", True))
                sql_msg = str(cache.get("sql_msg") or "")
                save_connectivity_cache(sql_ok, sql_msg, True, msg, wc_ms=ms)
                self.success.emit(f"اتصال با موفقیت برقرار شد. ({ms:.0f}ms)")
                return

            category = classify_network_error(msg)
            from sync_app.core.wc_sync_helper import wc_store_label

            hint = network_error_user_hint(category, target=wc_store_label(cfg))
            if category == "unknown" and ("403" in msg or "forbidden" in msg.lower()):
                from sync_app.core.wc_sync_helper import format_wc_api_error

                hint = format_wc_api_error(msg, cfg)
            cache = load_connectivity_cache(cfg)
            sql_ok = bool(cache.get("sql_ok", True))
            sql_msg = str(cache.get("sql_msg") or "")
            save_connectivity_cache(sql_ok, sql_msg, False, msg, wc_ms=ms)
            self.error.emit(hint if category != "unknown" else msg)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class PrestaShopTestWorker(QObject):
    """Worker غیرهمزمان برای تست اتصال پرستاشاپ (Webservice API)."""
    log = pyqtSignal(str)
    success = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = dict(config or {})

    def run(self):
        try:
            from sync_app.core.ps_sync_helper import check_prestashop_connection

            cfg = dict(self.config)
            url = (cfg.get("PS_URL") or "").strip()
            key = (cfg.get("PS_API_KEY") or "").strip()
            if not url:
                raise Exception("آدرس پرستاشاپ خالی است.")
            if not key:
                raise Exception("کلید Webservice API وارد نشده است.")

            self.log.emit(f"در حال تست اتصال به {url} ...")
            ok, msg, currency = check_prestashop_connection(cfg)
            if ok:
                self.log.emit(f"✅ {msg}")
                if currency and currency != "N/A":
                    self.log.emit(f"واحد پول پیش‌فرض سایت: {currency}")
                self.success.emit(msg)
                return
            self.error.emit(msg)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class SqlDbListWorker(QObject):
    """بارگذاری لیست دیتابیس‌ها بدون قفل UI"""
    log = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    healed = pyqtSignal(object)

    def __init__(self, runtime_config):
        super().__init__()
        self.runtime_config = dict(runtime_config or {})

    def run(self):
        try:
            from sync_app.core.sql_connection_helper import (
                auto_heal_sql_connection,
                open_master_connection,
            )
            from sync_app.core.sql_windows_probe import (
                ensure_sqlexpress_running,
                sqlexpress_service_status,
            )

            runtime = dict(self.runtime_config)
            runtime["SQL_DATABASE"] = "master"
            self.log.emit("شروع بارگذاری لیست دیتابیس‌ها")
            self.log.emit(f"Server: {runtime.get('SQL_SERVER') or '—'}")
            self.log.emit(f"Driver: {runtime.get('SQL_DRIVER') or '—'}")

            running, _detail = sqlexpress_service_status()
            if running is True:
                self.log.emit("SQL Express: سرویس روشن است")
            elif running is False:
                self.log.emit("SQL Express: خاموش — تلاش برای Start...")
                if ensure_sqlexpress_running():
                    self.log.emit("SQL Express: سرویس روشن شد")
                else:
                    self.log.emit("SQL Express: روشن نشد (شاید نیاز به Run as Administrator)")
            else:
                self.log.emit("SQL Express: وضعیت سرویس نامشخص")

            self.log.emit("بررسی و اصلاح خودکار تنظیمات اتصال...")
            healed_cfg, ok, heal_msg = auto_heal_sql_connection(runtime, timeout=3)
            if heal_msg:
                self.log.emit(heal_msg)
            if ok:
                runtime = healed_cfg
                if healed_cfg != self.runtime_config:
                    self.healed.emit(healed_cfg)

            last_error = heal_msg if not ok else None
            for server_fallback in (False, True):
                step = (
                    "اتصال مستقیم به master"
                    if not server_fallback
                    else "امتحان نام‌های جایگزین Server"
                )
                self.log.emit(step)
                try:
                    conn, auth_mode, _conn_str = open_master_connection(
                        runtime,
                        timeout=3,
                        server_fallback=server_fallback,
                        auth_fallback=False,
                    )
                    self.log.emit(f"اتصال OK — Auth: {auth_mode}")
                    cur = conn.cursor()
                    self.log.emit("دریافت لیست از sys.databases ...")
                    cur.execute("SELECT name FROM sys.databases WHERE state = 0 ORDER BY name")
                    dbs = [row[0] for row in cur.fetchall()]
                    conn.close()
                    self.log.emit(f"✅ {len(dbs)} دیتابیس دریافت شد")
                    self.finished.emit(dbs)
                    return
                except Exception as exc:
                    last_error = str(exc)
                    self.log.emit(f"ناموفق: {last_error}")
            self.error.emit(str(last_error or "بارگذاری لیست دیتابیس ناموفق بود."))
        except Exception as e:
            self.error.emit(str(e))


class SqlAttachWorker(QObject):
    """Attach MDF با گزارش مرحله‌به‌مرحله"""
    log = pyqtSignal(str)
    success = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, runtime_config, mdf_path, *, fresh_import=True):
        super().__init__()
        self.runtime_config = dict(runtime_config or {})
        self.mdf_path = mdf_path
        self.fresh_import = bool(fresh_import)

    def run(self):
        try:
            from sync_app.core.sql_attach_helper import (
                attach_database_files,
                suggest_import_database_name,
            )
            from sync_app.core.sql_connection_helper import auto_heal_sql_connection
            from sync_app.core.sql_windows_probe import (
                ensure_sqlexpress_running,
                sqlexpress_service_status,
            )

            cfg = dict(self.runtime_config)
            from sync_app.core.app_version import APP_VERSION

            self.log.emit(f"نسخه برنامه: {APP_VERSION}")
            self.log.emit("شروع بررسی / Attach فایل MDF")
            self.log.emit(f"مسیر: {self.mdf_path}")
            if self.fresh_import:
                import_name = suggest_import_database_name(self.mdf_path)
                self.log.emit(f"نام دیتابیس جدید (فایل + تاریخ امروز): {import_name}")
            else:
                import_name = None

            running, _detail = sqlexpress_service_status()
            if running is True:
                self.log.emit("SQL Express: سرویس روشن است")
            elif running is False:
                self.log.emit("SQL Express: خاموش — تلاش برای Start...")
                if ensure_sqlexpress_running():
                    self.log.emit("SQL Express: سرویس روشن شد")
                else:
                    self.log.emit("SQL Express: روشن نشد")
            else:
                self.log.emit("SQL Express: وضعیت سرویس نامشخص")

            self.log.emit("اصلاح خودکار Server / اتصال...")
            healed, ok, heal_msg = auto_heal_sql_connection(cfg, timeout=3)
            if heal_msg:
                self.log.emit(heal_msg)
            if ok:
                cfg = healed

            self.log.emit("بررسی وضعیت Attach در SQL Server...")
            result = attach_database_files(
                cfg,
                self.mdf_path,
                fresh_import=self.fresh_import,
                timeout=4,
            )
            if result.get("attached"):
                self.log.emit(f"Attach جدید انجام شد: {result.get('database')}")
                if result.get("staged_dir"):
                    self.log.emit(f"فایل برای SQL کپی شد: {result['staged_dir']}")
            elif result.get("already_attached"):
                self.log.emit(
                    f"دیتابیس از قبل وصل است: {result.get('database')} — {result.get('mdf_path')}"
                )
            else:
                self.log.emit(f"نام دیتابیس: {result.get('database')}")
            self.success.emit(result)
        except Exception as exc:
            self.log.emit(f"❌ خطا: {exc}")
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class SqlTestWorker(QObject):
    """تست اتصال SQL بدون قفل UI"""
    log = pyqtSignal(str)
    success = pyqtSignal(dict)
    error = pyqtSignal(str)
    healed = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, payload):
        super().__init__()
        self.payload = dict(payload or {})

    def run(self):
        try:
            from sync_app.core.sql_connection_helper import (
                _normalize_driver_name,
                _server_candidates,
                _try_connect,
                auto_heal_sql_connection,
                local_server_variants,
            )

            cfg = dict(self.payload)
            healed, ok, heal_msg = auto_heal_sql_connection(cfg, timeout=3)
            if ok:
                cfg = healed
                if healed != self.payload:
                    self.healed.emit(healed)
                if heal_msg:
                    self.log.emit(heal_msg)

            selected_driver = _normalize_driver_name(cfg.get("SQL_DRIVER") or "")
            drivers_to_try = []
            if selected_driver:
                drivers_to_try.append(selected_driver)
            for drv in cfg.get("installed_drivers") or []:
                if drv and drv not in drivers_to_try:
                    drivers_to_try.append(drv)
            drivers_to_try = drivers_to_try[:3]

            if not drivers_to_try:
                raise Exception("هیچ درایور SQL Server روی سیستم شناسایی نشد.")

            raw_server = (cfg.get("SQL_SERVER") or "").strip()
            if "sqlexpress" in raw_server.lower().replace(" ", ""):
                server_candidates = local_server_variants(raw_server)[:5]
            else:
                server_candidates = _server_candidates(raw_server or "localhost")[:4]
            auth_modes = cfg.get("auth_modes") or ["sql", "windows"]
            database = (cfg.get("SQL_DATABASE") or "").strip() or None

            self.log.emit(f"Driver انتخابی: {selected_driver or 'نامشخص'}")
            self.log.emit(f"Server های تست: {', '.join(server_candidates)}")

            last_error = ""
            for drv in drivers_to_try:
                test_cfg = dict(cfg)
                test_cfg["SQL_DRIVER"] = f"{{{drv}}}"
                for server_name in server_candidates:
                    for auth_mode in auth_modes:
                        try:
                            self.log.emit(
                                f"در حال تست: {drv} | {server_name} | {auth_mode}"
                            )
                            conn, _conn_str = _try_connect(
                                test_cfg,
                                server_name,
                                auth_mode,
                                database,
                                4,
                            )
                            cur = conn.cursor()
                            cur.execute("SELECT DB_NAME(), SUSER_SNAME(), @@SERVERNAME")
                            row = cur.fetchone()
                            conn.close()

                            db_name = row[0] if row and row[0] else (database or "-")
                            db_user = row[1] if row and row[1] else "نامشخص"
                            db_server = row[2] if row and row[2] else server_name
                            self.success.emit(
                                {
                                    "driver": drv,
                                    "server": server_name,
                                    "auth_mode": auth_mode,
                                    "db_name": db_name,
                                    "db_user": db_user,
                                    "db_server": db_server,
                                }
                            )
                            return
                        except Exception as exc:
                            last_error = str(exc)
                            self.log.emit(f"ناموفق: {last_error}")

            self.error.emit(last_error or "اتصال SQL برقرار نشد.")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class SqlServiceStartWorker(QObject):
    """روشن کردن سرویس SQL Express / SQL Browser بدون قفل UI"""
    log = pyqtSignal(str)
    success = pyqtSignal(dict)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, action_id="start_sqlexpress"):
        super().__init__()
        self.action_id = (action_id or "start_sqlexpress").strip()

    def run(self):
        try:
            from sync_app.core.sql_windows_probe import (
                sqlexpress_service_status,
                start_sql_browser_service,
                start_sqlexpress_service,
            )

            if self.action_id == "start_browser":
                self.log.emit("در حال روشن کردن SQL Browser...")
                result = start_sql_browser_service(allow_elevation=True)
            else:
                self.log.emit("در حال روشن کردن SQL Server Express...")
                running, _detail = sqlexpress_service_status()
                if running is True:
                    self.log.emit("سرویس SQL Express از قبل روشن است.")
                result = start_sqlexpress_service(allow_elevation=True, wait_sec=35)

            for step in result.get("steps") or []:
                self.log.emit(f"  • {step}")

            if result.get("ok"):
                self.log.emit(f"✅ {result.get('message') or 'سرویس روشن شد'}")
                self.success.emit(result)
            else:
                self.error.emit(result.get("message") or "روشن کردن سرویس ناموفق بود.")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class WooStoreSetupWorker(QObject):
    """راه‌اندازی Cart/Checkout/My Account در وردپرس + اتصال WooCommerce."""
    log = pyqtSignal(str)
    success = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.config = dict(config or {})

    def run(self):
        try:
            from sync_app.core.scripts import woocommerce_store_setup

            class _EmitLog:
                def info(self, msg):
                    self._emit(msg)

                def warning(self, msg):
                    self._emit(f"⚠️ {msg}")

                def error(self, msg):
                    self._emit(f"❌ {msg}")

                def _emit(self, msg):
                    self.outer.log.emit(str(msg))

            import sync_app.core.scripts.woocommerce_store_setup as mod
            old_log = mod.log
            emitter = _EmitLog()
            emitter.outer = self
            mod.log = emitter
            try:
                report = woocommerce_store_setup.main(self.config)
            finally:
                mod.log = old_log

            created = 1 if report.get("installed") else 0
            page_ids = [
                (p or {}).get("page_id", 0)
                for p in (report.get("pages") or {}).values()
            ]
            linked = sum(1 for pid in page_ids if pid > 0)
            verified = len(report.get("verified") or [])
            warnings = report.get("warnings") or []
            warn_line = ""
            if warnings:
                warn_line = "\n" + "\n".join(f"⚠️ {w}" for w in warnings[:3])
            self.success.emit(
                f"صفحات فروشگاه آماده شد.\n"
                f"install_pages: {created} | صفحات متصل: {linked}/3 | URL تایید: {verified}"
                f"{warn_line}\n"
                "حالا /cart/ و /checkout/ باید کار کنند."
            )
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setLayoutDirection(Qt.RightToLeft)
        self.product_tab_ref = None
        self.variation_tab_ref = None
        self.category_tab_ref = None
        self.dashboard_tab_ref = None
        self.reconciliation_tab_ref = None
        self.properties_tab_ref = None
        self.customer_tab_ref = None
        self.order_tab_ref = None
        self.theme_changed_callback = None
        self._wc_thread = None
        self._wc_worker = None
        self._ps_thread = None
        self._ps_worker = None
        self._wc_setup_thread = None
        self._wc_setup_worker = None
        self._sql_test_thread = None
        self._sql_test_worker = None
        self._sql_db_thread = None
        self._sql_db_worker = None
        self._sql_attach_thread = None
        self._sql_attach_worker = None
        self._sql_service_thread = None
        self._sql_service_worker = None
        self._sql_service_retry_test = False
        self._sql_op_log = None
        self._db_list_cache = None
        self._pending_db_apply_name = None
        self._monitor_open = True
        self._monitor_anim = None
        self._settings_compact = None
        self._ui_built = False
        self._last_success_sql_auth_mode = "auto"
        try:
            from sync_app.core.user_profile import load_secure_config_after_profile

            self.config = load_secure_config_after_profile(None) or {}
        except Exception:
            self.config = {}
        self._wc_sites = []
        self._active_wc_site_id = ""
        self._wc_site_switching = False
        self._wc_active_site_baseline = {}
        self._wc_guard_busy = False
        self._ps_sites = []
        self._active_ps_site_id = ""
        self._ps_site_switching = False
        self._ps_active_site_baseline = {}
        self._ps_guard_busy = False
        self._last_success_sql_auth_mode = (self.config or {}).get("SQL_AUTH_MODE", "auto")
        self._dirty = False
        self._field_baselines = {}
        self._tracked_widgets = []

        boot = QVBoxLayout(self)
        boot.setContentsMargins(24, 24, 24, 24)
        self._boot_label = QLabel("⏳ در حال بارگذاری تنظیمات...")
        self._boot_label.setAlignment(Qt.AlignCenter)
        self._boot_label.setStyleSheet("color: #64748b; font-size: 14px; padding: 40px;")
        boot.addWidget(self._boot_label)
        QTimer.singleShot(0, self._deferred_build_ui)

    def _deferred_build_ui(self):
        if self._ui_built:
            return
        self._ui_built = True
        try:
            old = self.layout()
            if old is not None:
                while old.count():
                    item = old.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
                QWidget().setLayout(old)
            self.init_ui()
        except Exception:
            import logging
            import traceback

            logging.getLogger("SyncApp").error(
                "Settings tab UI build failed:\n%s", traceback.format_exc()
            )
            self._ui_built = False
            if getattr(self, "_boot_label", None) is not None:
                self._boot_label.setText(
                    "خطا در بارگذاری تنظیمات — برنامه را ببندید و دوباره run.bat را بزنید."
                )
                self._boot_label.setStyleSheet(
                    "color: #b91c1c; font-size: 14px; padding: 40px;"
                )

    def set_theme_callback(self, callback):
        self.theme_changed_callback = callback

    def set_font_size_callback(self, callback):
        # ثبت تابع callback برای تغییر سایز فونت
        self.font_size_changed_callback = callback

    def _detect_product_mode(self):
        from sync_app.core.threading_helper import run_in_thread
        from sync_app.core.product_mode import detect_product_mode_from_db, MODE_SIMPLE_ONLY

        self.product_mode_detect_btn.setEnabled(False)
        self.product_mode_detect_btn.setText("⏳ در حال بررسی دیتابیس...")
        cfg = self.config or {}

        def _worker():
            return detect_product_mode_from_db(cfg)

        def _done(result):
            mode, info = result
            self.product_mode_detect_btn.setEnabled(True)
            self.product_mode_detect_btn.setText("🔍 تشخیص خودکار از دیتابیس")
            idx = self.product_mode_combo.findData(mode)
            if idx >= 0:
                self.product_mode_combo.setCurrentIndex(idx)
            mode_fa = "فقط محصولات ساده" if mode == MODE_SIMPLE_ONLY else "دارای ویژگی و متغیر"
            QMessageBox.information(
                self, "نتیجه‌ی تشخیص",
                f"از {info['total_products']} کالای گروه‌های انتخابی، "
                f"{info['variable_products']} تا متغیر (چند سایز/رنگ) و "
                f"{info['simple_products']} تا ساده بودن.\n\n"
                f"پیشنهاد: «{mode_fa}»\n\n"
                "این فقط پیشنهاده — برای اعمال، دکمه‌ی «ذخیره تنظیمات» رو بزنید.",
            )

        def _fail(msg):
            self.product_mode_detect_btn.setEnabled(True)
            self.product_mode_detect_btn.setText("🔍 تشخیص خودکار از دیتابیس")
            QMessageBox.critical(self, "خطا در تشخیص", f"اتصال به دیتابیس ناموفق بود:\n{msg}")

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _refresh_site_currency(self):
        from sync_app.core.wc_sync_helper import apply_network_overrides, build_wcapi
        from sync_app.core.threading_helper import run_in_thread

        self.site_currency_refresh_btn.setEnabled(False)
        self.site_currency_label.setText("⏳ در حال دریافت...")
        cfg = self.config or {}

        def _worker():
            apply_network_overrides(cfg)
            wcapi = build_wcapi(cfg)
            resp = wcapi.get("system_status")
            status = resp.json()
            settings = status.get("settings", {}) if isinstance(status, dict) else {}
            return str(settings.get("currency") or "").strip().upper()

        # کد رایج ووکامرس (ISO) به نام فارسی قابل‌فهم — چون نمایش کد خام
        # («IRR ﷼» و مثل اون) برای کاربر فارسی‌زبان گیج‌کننده و «عجیب» بود.
        CURRENCY_FA = {
            "IRR": "ریال ایران",
            "IRT": "تومان ایران",
            "USD": "دلار آمریکا",
            "EUR": "یورو",
            "AED": "درهم امارات",
            "TRY": "لیر ترکیه",
            "GBP": "پوند انگلیس",
        }

        def _done(code):
            label = CURRENCY_FA.get(code, code or "نامشخص")
            self.site_currency_label.setText(label)
            self.site_currency_refresh_btn.setEnabled(True)

        def _fail(msg):
            self.site_currency_label.setText("خطا در دریافت")
            self.site_currency_refresh_btn.setEnabled(True)

        run_in_thread(_worker, on_complete=_done, on_error=_fail)

    def _apply_dev_lock_ui(self):
        from sync_app.core.dev_lock import apply_lock_state

        apply_lock_state(self, self._dev_locked, exclude_names={"devUnlockBtn"})
        if self._dev_locked:
            self._unlock_btn.setText("🔓 ویرایش (نیاز به رمز دوم)")
        else:
            self._unlock_btn.setText("🔒 قفل کردن دوباره")
        self._unlock_btn.setEnabled(True)

    def _toggle_dev_lock(self):
        from sync_app.core.dev_lock import prompt_unlock

        if not self._dev_locked:
            self._dev_locked = True
            self._apply_dev_lock_ui()
            return
        if prompt_unlock(self):
            self._dev_locked = False
            self._apply_dev_lock_ui()

    def _refresh_backup_list(self):
        from sync_app.core.secure_config_loader import list_config_backups, _candidate_pairs

        self.backup_list.clear()
        try:
            _, config_file = _candidate_pairs()[0]
            backups = list_config_backups(config_file)
        except Exception:
            backups = []

        if not backups:
            item = QListWidgetItem("هنوز پشتیبانی ساخته نشده (بعد از اولین ذخیره‌ی بعدی، اینجا نشون داده می‌شه)")
            item.setFlags(Qt.NoItemFlags)
            self.backup_list.addItem(item)
            return

        for b in backups:
            size_kb = max(1, b["size"] // 1024)
            label = f"{b['modified'].strftime('%Y-%m-%d %H:%M:%S')}  ({size_kb} کیلوبایت)"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, b["path"])
            self.backup_list.addItem(item)

    def _restore_selected_backup(self):
        from sync_app.core.secure_config_loader import restore_config_backup, _candidate_pairs

        item = self.backup_list.currentItem()
        backup_path = item.data(Qt.UserRole) if item else None
        if not backup_path:
            QMessageBox.information(self, "انتخاب نشده", "اول یک نسخه‌ی پشتیبان را از لیست انتخاب کنید.")
            return

        confirm = QMessageBox.question(
            self, "تأیید بازیابی",
            "تنظیمات فعلی با این نسخه‌ی پشتیبان جایگزین می‌شود "
            "(خودِ حالت فعلی هم قبلش پشتیبان گرفته می‌شود). ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            _, config_file = _candidate_pairs()[0]
            restore_config_backup(backup_path, config_file)
            QMessageBox.information(
                self, "انجام شد",
                "تنظیمات بازیابی شد. لطفاً برنامه را ببندید و دوباره باز کنید تا مقادیر جدید بارگذاری شوند.",
            )
            self._refresh_backup_list()
        except Exception as exc:
            QMessageBox.critical(self, "خطا در بازیابی", str(exc))

    def _resolve_sql_auth_mode_for_save(self, existing_config):
        auth_mode = self._last_success_sql_auth_mode
        if auth_mode in ["sql", "windows"]:
            return auth_mode

        saved_auth_mode = (existing_config or {}).get("SQL_AUTH_MODE")
        if saved_auth_mode in ["sql", "windows"]:
            return saved_auth_mode

        saved_conn_str = ((existing_config or {}).get("SQL_CONN_STRING") or "").lower()
        if "trusted_connection=yes" in saved_conn_str or "integrated security=sspi" in saved_conn_str:
            return "windows"
        if "uid=" in saved_conn_str or "pwd=" in saved_conn_str:
            return "sql"

        detected = self._detect_auth_modes()
        return detected[0] if detected else "sql"

    def set_button_status(self, button, success):
        if success:
            button.setStyleSheet(
                "background-color: #16a34a; color: white; border-radius: 8px; "
                "padding: 10px 16px; font-weight: 700; font-size: 12px; min-height: 38px;"
            )
            button.setText("✅ اتصال موفق")
        else:
            button.setStyleSheet(
                "background-color: #dc2626; color: white; border-radius: 8px; "
                "padding: 10px 16px; font-weight: 700; font-size: 12px; min-height: 38px;"
            )
            button.setText("❌ قطع اتصال")

    def init_ui(self):
        outer_layout = QVBoxLayout()
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(10)

        def english_caption(text):
            label = QLabel(text)
            label.setLayoutDirection(Qt.LeftToRight)
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return label

        from sync_app.core.app_version import APP_VERSION

        title = QLabel(f"تنظیمات اتصال و شخصی‌سازی — {APP_VERSION}")
        title.setProperty("role", "section-title")
        title.setAlignment(Qt.AlignCenter)
        outer_layout.addWidget(title)

        subtitle = QLabel("پیکربندی پایگاه داده، API فروشگاه و تنظیمات ظاهری برنامه")
        subtitle.setProperty("role", "caption")
        subtitle.setAlignment(Qt.AlignCenter)
        outer_layout.addWidget(subtitle)

        # ── پیش‌تنظیم‌های نام‌دارِ کلِ تنظیمات — چند مجموعه تنظیماتِ کامل (دیتابیس
        # + پلتفرم + فروشگاه + تم) زیرِ یک عنوان، قابلِ سوییچِ آنی بدونِ نیاز
        # به تعویضِ پروفایل/راه‌اندازیِ مجددِ برنامه ──────────────────────
        preset_bar = QWidget()
        preset_bar.setObjectName("presetBar")
        preset_bar.setStyleSheet(
            "QWidget#presetBar { background: #eef2ff; border: 1px solid #c7d2fe;"
            " border-radius: 10px; }"
        )
        preset_bar_layout = QHBoxLayout(preset_bar)
        preset_bar_layout.setContentsMargins(12, 8, 12, 8)
        preset_bar_layout.setSpacing(8)

        preset_label = QLabel("پیش‌تنظیم:")
        preset_label.setStyleSheet("font-weight:700; color:#3730a3;")
        preset_bar_layout.addWidget(preset_label)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumHeight(36)
        self.preset_combo.setMinimumWidth(220)
        preset_bar_layout.addWidget(self.preset_combo, 1)

        self.preset_save_btn = QPushButton("💾 ذخیره به‌عنوان...")
        self.preset_save_btn.setMinimumHeight(36)
        self.preset_save_btn.clicked.connect(self._on_save_config_preset)
        preset_bar_layout.addWidget(self.preset_save_btn)

        self.preset_delete_btn = QPushButton("🗑 حذف")
        self.preset_delete_btn.setMinimumHeight(36)
        self.preset_delete_btn.clicked.connect(self._on_delete_config_preset)
        preset_bar_layout.addWidget(self.preset_delete_btn)

        outer_layout.addWidget(preset_bar)

        preset_hint = QLabel(
            "هر پیش‌تنظیم کل تنظیمات این تب (دیتابیس، پلتفرم، فروشگاه، تم و بقیه) را زیر یک "
            "عنوان ذخیره می‌کند — با انتخاب یک پیش‌تنظیم، همه‌ی این تنظیمات جایگزین تنظیمات "
            "فعلی و بلافاصله اعمال می‌شود."
        )
        preset_hint.setWordWrap(True)
        preset_hint.setStyleSheet("color:#64748b; font-size:10px; padding: 0 4px;")
        outer_layout.addWidget(preset_hint)

        self._config_presets_switching = False
        self._refresh_preset_combo()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_combo_changed)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        # در حالت ریسپانسیو اسکرول افقی نباید ظاهر شود
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area = scroll_area

        container = QWidget()
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(12)

        sql_group = QGroupBox("تنظیمات SQL Server")
        sql_group.setLayoutDirection(Qt.LeftToRight)
        sql_layout = QFormLayout()

        app_group = QGroupBox("تنظیمات عمومی")
        app_layout = QFormLayout()

        wc_group = QGroupBox("تنظیمات فروشگاه")
        wc_group.setLayoutDirection(Qt.LeftToRight)
        wc_form_layout = QFormLayout()
        self.wc_form_layout = wc_form_layout

        # تنظیمات عمومی فارسی → لیبل راست-چین
        for layout in [app_layout]:
            layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.setFormAlignment(Qt.AlignTop)
            layout.setHorizontalSpacing(14)
            layout.setVerticalSpacing(10)

        # بخش‌های انگلیسی SQL و WooCommerce → لیبل چپ-چین و جهت LTR
        for layout in [sql_layout, wc_form_layout]:
            layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.setFormAlignment(Qt.AlignTop)
            layout.setHorizontalSpacing(14)
            layout.setVerticalSpacing(10)

        self.driver_input = QComboBox()
        self.driver_input.addItems([
            "{ODBC Driver 18 for SQL Server}",
            "{ODBC Driver 17 for SQL Server}",
            "{SQL Server Native Client 11.0}",
            "{SQL Server}",
        ])
        selected_driver = self.config.get("SQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
        driver_idx = self.driver_input.findText(selected_driver)
        if driver_idx >= 0:
            self.driver_input.setCurrentIndex(driver_idx)
        else:
            self.driver_input.addItem(selected_driver)
            self.driver_input.setCurrentIndex(self.driver_input.count() - 1)

        self.server_input = QLineEdit(self.config.get("SQL_SERVER", "localhost"))
        self.database_input = QLineEdit(self.config.get("SQL_DATABASE", "DejavuDB3"))
        self.username_input = QLineEdit(self.config.get("SQL_USERNAME", "sa"))

        # انتخاب دیتابیس از لیست
        self.db_picker_combo = QComboBox()
        self.db_picker_combo.setMinimumHeight(38)
        self.db_picker_combo.setLayoutDirection(Qt.LeftToRight)
        saved_db = str((self.config or {}).get("SQL_DATABASE") or "").strip()
        if saved_db:
            self.db_picker_combo.addItem(saved_db)
            self.db_picker_combo.setToolTip(
                "نام ذخیره‌شده — برای لیست کامل از SQL روی «بارگذاری» بزنید"
            )
        else:
            self.db_picker_combo.addItem("-- نام دیتابیس را بالا بنویسید یا بارگذاری کنید --")
        self.db_picker_combo.currentTextChanged.connect(self._on_db_picker_changed)
        self._db_picker_apply_enabled = False

        self.db_refresh_btn = QPushButton("↻ بارگذاری")
        self.db_refresh_btn.setMinimumHeight(38)
        self.db_refresh_btn.setToolTip(
            "لیست دیتابیس‌ها از SQL Server — اگر کند بود، همان نام بالا کافی است"
        )
        self.db_refresh_btn.clicked.connect(self._load_databases_to_picker)

        self.db_log_btn = QPushButton("لاگ SQL")
        self.db_log_btn.setMinimumHeight(38)
        self.db_log_btn.setToolTip("پنجره گزارش زنده — هنگام بارگذاری/Attach خودکار باز می‌شود")
        self.db_log_btn.clicked.connect(self._show_sql_operation_log)

        db_picker_widget = QWidget()
        db_picker_layout = QHBoxLayout(db_picker_widget)
        db_picker_layout.setContentsMargins(0, 0, 0, 0)
        db_picker_layout.setSpacing(6)
        db_picker_layout.addWidget(self.db_picker_combo)
        db_picker_layout.addWidget(self.db_refresh_btn)
        db_picker_layout.addWidget(self.db_log_btn)

        self.sql_mdf_path_input = QLineEdit((self.config or {}).get("SQL_MDF_PATH", ""))
        self.sql_mdf_path_input.setReadOnly(True)
        self.sql_mdf_path_input.setPlaceholderText("مسیر فایل .mdf — با دکمه انتخاب فایل")
        self.sql_mdf_path_input.setLayoutDirection(Qt.LeftToRight)
        self.sql_mdf_path_input.setAlignment(Qt.AlignLeft)
        self.sql_mdf_path_input.setMinimumHeight(38)

        self.db_browse_btn = QPushButton("📁 انتخاب فایل")
        self.db_browse_btn.setMinimumHeight(38)
        self.db_browse_btn.setToolTip("انتخاب فایل MDF/LDF و Attach به SQL Server")
        self.db_browse_btn.clicked.connect(self._browse_and_attach_database)

        db_file_widget = QWidget()
        db_file_layout = QHBoxLayout(db_file_widget)
        db_file_layout.setContentsMargins(0, 0, 0, 0)
        db_file_layout.setSpacing(6)
        db_file_layout.addWidget(self.sql_mdf_path_input, 1)
        db_file_layout.addWidget(self.db_browse_btn)

        self.password_input = QLineEdit(self.config.get("SQL_PASSWORD", "123"))
        self.password_input.setEchoMode(QLineEdit.Password)

        self.driver_input.currentIndexChanged.connect(self.apply_driver_preset)

        for field in [self.server_input, self.database_input, self.username_input, self.password_input]:
            field.setLayoutDirection(Qt.LeftToRight)
            field.setAlignment(Qt.AlignLeft)
            field.setMinimumHeight(38)

        self.driver_input.setLayoutDirection(Qt.LeftToRight)
        self.driver_input.setMinimumHeight(38)

        self.sql_test_button = QPushButton("تست اتصال SQL")
        self.sql_test_button.clicked.connect(self.test_sql_connection)
        self.sql_start_service_btn = QPushButton("▶ روشن کردن SQL Express")
        self.sql_start_service_btn.setMinimumHeight(38)
        self.sql_start_service_btn.setToolTip(
            "سرویس SQL Server Express را روشن می‌کند (در صورت نیاز UAC می‌پرسد)"
        )
        self.sql_start_service_btn.clicked.connect(self._on_sql_start_service_button_clicked)
        self.sql_start_service_btn.setVisible(os.name == "nt")
        sql_test_widget = QWidget()
        sql_test_layout = QHBoxLayout(sql_test_widget)
        sql_test_layout.setContentsMargins(0, 0, 0, 0)
        sql_test_layout.addWidget(self.sql_test_button)
        sql_test_layout.addWidget(self.sql_start_service_btn)
        sql_test_layout.addStretch()
        self.server_input.textChanged.connect(self._refresh_sql_service_button)
        QTimer.singleShot(0, self._refresh_sql_service_button)

        sql_layout.addRow(english_caption("Driver:"), self.driver_input)
        sql_layout.addRow(english_caption("Server:"), self.server_input)
        sql_layout.addRow(english_caption("Database:"), self.database_input)
        sql_layout.addRow(english_caption("فایل MDF:"), db_file_widget)
        sql_layout.addRow(english_caption("انتخاب DB:"), db_picker_widget)
        sql_layout.addRow(english_caption("Username:"), self.username_input)
        sql_layout.addRow(english_caption("Password:"), self.password_input)
        sql_layout.addRow(QLabel(""), sql_test_widget)

        self.price_combo = QComboBox()
        self.price_combo.addItems([f"لیست قیمت {i}" for i in range(1, 11)])
        self.price_combo.setCurrentIndex(self.config.get("PRICE_LIST_INDEX", 0))

        self.sale_price_enabled_cb = QCheckBox("ارسال قیمت ویژه (Sale Price) — فقط ووکامرس")
        self.sale_price_enabled_cb.setToolTip(
            "پرستاشاپ معادل مستقیم برای «قیمت ویژه» ندارد — این تنظیم فقط روی ووکامرس اثر دارد."
        )
        self.sale_price_enabled_cb.setLayoutDirection(Qt.RightToLeft)
        self.sale_price_enabled_cb.setChecked(bool(self.config.get("SALE_PRICE_LIST_ENABLED")))
        self.sale_price_combo = QComboBox()
        self.sale_price_combo.addItems([f"لیست قیمت {i}" for i in range(1, 11)])
        self.sale_price_combo.setCurrentIndex(int(self.config.get("SALE_PRICE_LIST_INDEX", 1)))

        self.price_markup_spin = QDoubleSpinBox()
        self.price_markup_spin.setRange(-90.0, 500.0)
        self.price_markup_spin.setDecimals(1)
        self.price_markup_spin.setSuffix(" %")
        self.price_markup_spin.setValue(float(self.config.get("PRICE_MARKUP_PERCENT", 0) or 0))
        self.price_markup_spin.setToolTip(
            "درصدی که موقع سینک، روی قیمت لیست قیمت عادی اضافه می‌شه.\n"
            "مثلاً ۱۰ یعنی قیمت نهایی رو سایت = قیمت لیست × ۱٫۱۰\n"
            "برای کم‌کردن قیمت، عدد منفی بذارید (مثلاً -5)."
        )

        self.sale_price_markup_spin = QDoubleSpinBox()
        self.sale_price_markup_spin.setRange(-90.0, 500.0)
        self.sale_price_markup_spin.setDecimals(1)
        self.sale_price_markup_spin.setSuffix(" %")
        self.sale_price_markup_spin.setValue(float(self.config.get("SALE_PRICE_MARKUP_PERCENT", 0) or 0))
        self.sale_price_markup_spin.setToolTip(
            "همون درصد ولی برای لیست قیمت ویژه — کاملاً مستقل از درصد قیمت عادی."
        )

        self.erp_picture_root_input = QLineEdit(str(self.config.get("ERP_PICTURE_ROOT") or ""))
        self.erp_picture_root_input.setPlaceholderText(
            r"مثلاً D:\Dejavu\Pictures — برای PicturePath در Article"
        )
        self.erp_picture_root_input.setLayoutDirection(Qt.LeftToRight)

        self.theme_combo = QComboBox()
        from sync_app.core.app_site_config import THEME_UI_LABELS

        for theme_key, theme_label in THEME_UI_LABELS.items():
            self.theme_combo.addItem(theme_label, theme_key)
        current_theme = self.config.get("APP_THEME", "navy")
        if current_theme not in {"navy", "red", "green"}:
            current_theme = "navy"
        idx = self.theme_combo.findData(current_theme)
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.theme_combo.currentIndexChanged.connect(self.preview_theme_change)

        # کمبوباکس انتخاب سایز فونت (درخواست کارفرما)
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItem("کوچک (12px)", 12)
        self.font_size_combo.addItem("متوسط (14px)", 14)
        self.font_size_combo.addItem("بزرگ (16px)", 16)
        self.font_size_combo.addItem("خیلی بزرگ (18px)", 18)
        self.font_size_combo.addItem("خیلی بزرگ Bold (18px ضخیم)", "18bold")
        current_font_size = self.config.get("APP_FONT_SIZE", 14)
        fs_idx = self.font_size_combo.findData(current_font_size)
        self.font_size_combo.setCurrentIndex(fs_idx if fs_idx >= 0 else 1)
        self.font_size_combo.currentIndexChanged.connect(self.preview_font_size_change)

        from sync_app.core.integrations.erp_provider import ERP_PROVIDER_CHOICES, normalize_erp_provider_key

        self.erp_provider_combo = QComboBox()
        for _key, _label in ERP_PROVIDER_CHOICES:
            suffix = " (فعلی)" if _key == "dejavu" else " (پیش‌نمایش آینده)"
            self.erp_provider_combo.addItem(f"{_label}{suffix}", _key)
        current_provider = normalize_erp_provider_key(self.config.get("ERP_PROVIDER"))
        provider_idx = self.erp_provider_combo.findData(current_provider)
        self.erp_provider_combo.setCurrentIndex(provider_idx if provider_idx >= 0 else 0)
        self.erp_provider_combo.currentIndexChanged.connect(self.update_provider_hint)

        self.provider_hint_label = QLabel("")
        self.provider_hint_label.setWordWrap(True)
        self.provider_hint_label.setStyleSheet("color: #4b5563; font-size: 11px;")

        self.app_login_username_input = QLineEdit(
            (self.config.get("APP_LOGIN_USERNAME") or "admin").strip() or "admin"
        )
        self.app_login_password_input = PasswordLineEdit(
            self.config.get("APP_LOGIN_PASSWORD", "123456")
        )
        self.login_screen_enabled_checkbox = QCheckBox("نمایش صفحه لاگین در شروع برنامه")
        self.login_screen_enabled_checkbox.setChecked(bool(self.config.get("APP_SHOW_LOGIN_SCREEN", True)))
        self.login_screen_enabled_checkbox.setLayoutDirection(Qt.RightToLeft)
        self.login_screen_enabled_checkbox.setMinimumHeight(36)

        self.auto_update_enabled_checkbox = QCheckBox("دریافت و نصب خودکار نسخه جدید")
        auto_update_default = self.config.get("AUTO_UPDATE_ENABLED")
        if auto_update_default is None:
            auto_update_default = False
        self.auto_update_enabled_checkbox.setChecked(bool(auto_update_default))
        self.auto_update_enabled_checkbox.setLayoutDirection(Qt.RightToLeft)
        self.auto_update_enabled_checkbox.setMinimumHeight(36)
        self.auto_update_enabled_checkbox.setToolTip(
            "وقتی فعال باشد، با شروع برنامه نسخه جدید از آدرس سرور لایسنس (تنظیمات) بررسی و نصب می‌شود.\n"
            "لایسنس، تنظیمات SQL/فروشگاه و نقشه‌ها حفظ می‌شوند."
        )

        # ── چک‌باکس‌های انتخاب فیلدهای همگام‌سازی (محصول/دسته/ویژگی/متغیر) ──
        self._field_sync_checkboxes = {}
        for _group_label, _fields in ALL_FIELD_GROUPS:
            for cfg_key, label, default in _fields:
                cb = QCheckBox(label)
                cb.setLayoutDirection(Qt.RightToLeft)
                cb.setChecked(bool(self.config.get(cfg_key, default)))
                cb.setMinimumHeight(30)
                self._field_sync_checkboxes[cfg_key] = cb

        # ── چک‌باکس‌های «همیشه دوباره ارسال کن، حتی بدون تغییر» — جدا برای
        # دسته‌بندی/ویژگی/محصول/متغیر (پیش‌فرض خاموش: تشخیصِ تغییر فعاله) ──
        self._force_full_sync_checkboxes = {}
        for cfg_key, label, default in FORCE_FULL_SYNC_FIELDS:
            cb = QCheckBox(label)
            cb.setLayoutDirection(Qt.RightToLeft)
            cb.setChecked(bool(self.config.get(cfg_key, default)))
            cb.setMinimumHeight(30)
            cb.setToolTip(
                "پیش‌فرض: فقط چیزهایی که واقعاً در دیتابیس عوض شده‌اند دوباره ارسال می‌شوند "
                "(سریع‌تر). اگر این گزینه را بزنید، هر بار همه‌چیز از اول دوباره بررسی/ارسال "
                "می‌شود — برای عیب‌یابی یا اطمینان از هم‌گام‌بودنِ کامل با فروشگاه مفید است."
            )
            self._force_full_sync_checkboxes[cfg_key] = cb

        self.license_server_url_input = QLineEdit(
            (self.config.get("LICENSE_SERVER_URL") or "").strip()
        )
        self.license_server_url_input.setPlaceholderText("https://your-license-server.com")
        self.license_api_key_input = PasswordLineEdit(self.config.get("LICENSE_API_KEY", ""))
        self.license_api_key_input.setPlaceholderText("کلید API از wp-admin")
        license_api_help = QLabel(
            "برای اعتبارسنجی آنلاین و بروزرسانی لازم است.\n"
            "مسیر: wp-admin -> لایسنس‌های پیچا -> تنظیمات -> کلید API\n"
            "اگر در افزونه خالی باشد، سرور چک نمی‌کند."
        )
        license_api_help.setStyleSheet("color:#64748b; font-size:10px;")
        license_api_help.setWordWrap(True)
        self.license_api_key_button = QPushButton("🔗 باز کردن تنظیمات لایسنس در wp-admin")
        self.license_api_key_button.setFlat(True)
        self.license_api_key_button.setCursor(Qt.PointingHandCursor)
        self.license_api_key_button.clicked.connect(self._open_license_api_settings_page)

        for field in [
            self.app_login_username_input,
            self.app_login_password_input,
        ]:
            field.setLayoutDirection(Qt.LeftToRight)
            field.setAlignment(Qt.AlignLeft)
            field.setMinimumHeight(38)

        for field in [self.license_server_url_input, self.license_api_key_input]:
            field.setLayoutDirection(Qt.LeftToRight)
            field.setAlignment(Qt.AlignLeft)
            field.setMinimumHeight(38)

        for field in [
            self.price_combo,
            self.sale_price_combo,
            self.price_markup_spin,
            self.sale_price_markup_spin,
            self.theme_combo,
            self.font_size_combo,
            self.erp_provider_combo,
        ]:
            field.setMinimumHeight(38)
        self.erp_picture_root_input.setMinimumHeight(38)

        app_layout.addRow(QLabel("لیست قیمت عادی:"), self.price_combo)
        app_layout.addRow(QLabel("درصد افزایش قیمت عادی:"), self.price_markup_spin)
        app_layout.addRow(QLabel("قیمت ویژه:"), self.sale_price_enabled_cb)
        app_layout.addRow(QLabel("لیست قیمت ویژه:"), self.sale_price_combo)
        app_layout.addRow(QLabel("درصد افزایش قیمت ویژه:"), self.sale_price_markup_spin)
        app_layout.addRow(QLabel("پوشه تصاویر ERP:"), self.erp_picture_root_input)
        app_layout.addRow(QLabel("تم نرم‌افزار:"), self.theme_combo)
        app_layout.addRow(QLabel("سایز فونت:"), self.font_size_combo)
        app_layout.addRow(QLabel("Provider ERP:"), self.erp_provider_combo)
        app_layout.addRow(QLabel("نام کاربری ورود:"), self.app_login_username_input)
        app_layout.addRow(QLabel("رمز عبور ورود:"), self.app_login_password_input)
        app_layout.addRow(QLabel("صفحه لاگین:"), self.login_screen_enabled_checkbox)

        from sync_app.core.user_profile import get_current_profile_id

        self.profile_switch_button = QPushButton("🔄 تعویض پروفایل...")
        self.profile_switch_button.setToolTip(
            "هر پروفایل دیتابیس، پلتفرم فروشگاه، آدرس/کلید فروشگاه، تم و بقیه‌ی تنظیمات "
            "را کاملاً جدا نگه می‌دارد — برای مثال یک پروفایل برای فروشگاه ووکامرس و یک "
            "پروفایل دیگر برای فروشگاه پرستاشاپ."
        )
        self.profile_switch_button.clicked.connect(self._open_profile_switcher)
        profile_row = QWidget()
        profile_row_layout = QHBoxLayout(profile_row)
        profile_row_layout.setContentsMargins(0, 0, 0, 0)
        profile_row_layout.addWidget(QLabel(get_current_profile_id() or "—"))
        profile_row_layout.addWidget(self.profile_switch_button)
        profile_row_layout.addStretch()
        app_layout.addRow(QLabel("پروفایل فعال:"), profile_row)
        app_layout.addRow(QLabel("بروزرسانی:"), self.auto_update_enabled_checkbox)
        app_layout.addRow(QLabel("راهنما:"), self.provider_hint_label)
        self.update_provider_hint()

        self.url_input = QLineEdit(self.config.get("WC_URL", ""))
        self.url_input.setPlaceholderText("https://your-store.com/wp-json/wc/v3/")
        self.ck_input = PasswordLineEdit(self.config.get("WC_CONSUMER_KEY", ""))
        self.ck_input.setPlaceholderText("ck_...")
        self.ck_input.set_toggle_tooltip_base("کلید API")
        self.cs_input = PasswordLineEdit(self.config.get("WC_CONSUMER_SECRET", ""))
        self.cs_input.setPlaceholderText("cs_...")
        self.cs_input.set_toggle_tooltip_base("رمز API")
        self.wp_username_input = QLineEdit(self.config.get("WP_USERNAME", ""))
        self.wp_username_input.setPlaceholderText("login وردپرس — مثلاً admin (از Users → All Users)")
        self.wp_app_password_input = PasswordLineEdit(self.config.get("WP_APP_PASSWORD", ""))
        self.wp_app_password_input.setPlaceholderText("Application Password وردپرس")
        self.wp_app_password_input.set_toggle_tooltip_base("Application Password")
        self.timeout_input = QLineEdit(str(self.config.get("WC_TIMEOUT", 60)))

        for field in [self.url_input, self.ck_input, self.cs_input,
                      self.wp_username_input, self.wp_app_password_input, self.timeout_input]:
            field.setLayoutDirection(Qt.LeftToRight)
            field.setAlignment(Qt.AlignLeft)
            field.setMinimumHeight(38)

        from sync_app.core.integrations.erp_provider import erp_provider_label

        self.currency_combo = QComboBox()
        self.currency_combo.addItem(f"تومان (فروشگاه → {erp_provider_label(self.config)} ×۱۰)", True)
        self.currency_combo.addItem("ریال (بدون تبدیل)", False)
        is_toman_saved = self.config.get("WC_CURRENCY_IS_TOMAN", True)
        self.currency_combo.setCurrentIndex(0 if is_toman_saved else 1)
        self.currency_combo.setMinimumHeight(38)

        # نمایش فقط‌خواندنیِ واحد پول واقعیِ سایت (خونده‌شده از خودِ ووکامرس) —
        # این با تنظیم بالا (نحوه‌ی تبدیل قیمت بین ERP و ووکامرس) فرق داره؛
        # این فقط برای اطلاعه، قابل ویرایش نیست.
        self.site_currency_label = QLabel("— (دکمه‌ی «دریافت» را بزنید)")
        self.site_currency_label.setStyleSheet("color:#334155; font-weight:700;")
        self.site_currency_refresh_btn = QPushButton("🔄 دریافت از سایت")
        self.site_currency_refresh_btn.setMaximumWidth(140)
        self.site_currency_refresh_btn.clicked.connect(self._refresh_site_currency)

        from sync_app.core.wc_site_profiles import (
            copy_sites,
            create_empty_site,
            find_wc_site,
            get_active_site_id,
            get_wc_sites,
            site_display_label,
        )

        self._wc_sites = copy_sites(get_wc_sites(self.config))
        self._active_wc_site_id = get_active_site_id(self.config)
        if not self._wc_sites:
            self._wc_sites = [create_empty_site(label="سایت ۱")]
            self._active_wc_site_id = str(self._wc_sites[0].get("id") or "")

        self.wc_site_combo = QComboBox()
        self.wc_site_combo.setMinimumHeight(38)
        self.wc_site_combo.setLayoutDirection(Qt.LeftToRight)
        self.wc_add_site_btn = QPushButton("➕ سایت جدید")
        self.wc_add_site_btn.setMinimumHeight(38)
        self.wc_delete_site_btn = QPushButton("🗑 حذف")
        self.wc_delete_site_btn.setMinimumHeight(38)
        self.wc_add_site_btn.clicked.connect(self._on_add_wc_site)
        self.wc_delete_site_btn.clicked.connect(self._on_delete_wc_site)
        self.wc_site_combo.currentIndexChanged.connect(self._on_wc_site_combo_changed)

        self.wc_site_name_input = QLineEdit()
        self.wc_site_name_input.setMinimumHeight(38)
        self.wc_site_name_input.setPlaceholderText("نام دلخواه فروشگاه (مثلاً فروشگاه اصلی)")
        self.wc_site_name_input.editingFinished.connect(self._on_wc_site_name_changed)

        wc_site_row = QWidget()
        wc_site_row_layout = QHBoxLayout(wc_site_row)
        wc_site_row_layout.setContentsMargins(0, 0, 0, 0)
        wc_site_row_layout.setSpacing(8)
        wc_site_row_layout.addWidget(self.wc_site_combo, 1)
        wc_site_row_layout.addWidget(self.wc_add_site_btn)
        wc_site_row_layout.addWidget(self.wc_delete_site_btn)

        self._refresh_wc_site_combo(select_id=self._active_wc_site_id)
        active_site = find_wc_site(self._wc_sites, self._active_wc_site_id)
        if active_site:
            self.url_input.setText(str(active_site.get("url") or self.url_input.text()))
            self.ck_input.setText(str(active_site.get("consumer_key") or self.ck_input.text()))
            self.cs_input.setText(str(active_site.get("consumer_secret") or self.cs_input.text()))
            self.wp_username_input.setText(str(active_site.get("wp_username") or self.wp_username_input.text()))
            self.wp_app_password_input.setText(
                str(active_site.get("wp_app_password") or self.wp_app_password_input.text())
            )
            is_toman = bool(active_site.get("currency_is_toman", is_toman_saved))
            self.currency_combo.setCurrentIndex(0 if is_toman else 1)
            self.wc_site_name_input.setText(str(active_site.get("label") or ""))
        self._snapshot_wc_site_baseline()

        wc_sites_help = QLabel(
            "هر فروشگاه با URL و کلید API جدا ذخیره می‌شود.\n"
            "اگر تنظیمات مربوط به فروشگاه دیگری است، «سایت جدید +» بزنید — "
            "ویرایش پروفایل موجود، اطلاعات همان سایت را بازنویسی می‌کند."
        )
        wc_sites_help.setStyleSheet("color:#64748b; font-size:10px;")
        wc_sites_help.setWordWrap(True)

        self.wc_test_button = QPushButton("تست اتصال ووکامرس")
        self.wc_test_button.clicked.connect(self.test_wc_connection)
        self.wc_setup_button = QPushButton("راه‌اندازی Cart/Checkout")
        self.wc_setup_button.clicked.connect(self.run_wc_store_setup)
        wc_test_widget = QWidget()
        wc_layout = QHBoxLayout(wc_test_widget)
        wc_layout.setContentsMargins(0, 0, 0, 0)
        wc_layout.addWidget(self.wc_setup_button)
        wc_layout.addWidget(self.wc_test_button)
        wc_layout.addStretch()

        wc_api_help = QLabel(
            "Consumer Key و Secret برای تست اتصال لازم است.\n"
            "مسیر: WooCommerce → Settings → Advanced → REST API → Add key (Read/Write)"
        )
        wc_api_help.setStyleSheet("color:#64748b; font-size:10px;")
        wc_api_help.setWordWrap(True)
        self.wc_api_keys_button = QPushButton("🔗 باز کردن صفحه ساخت کلید API")
        self.wc_api_keys_button.setFlat(True)
        self.wc_api_keys_button.setCursor(Qt.PointingHandCursor)
        self.wc_api_keys_button.clicked.connect(self._open_wc_api_keys_page)

        wc_setup_help = QLabel(
            "ساخت Cart/Checkout با API رسمی WooCommerce (install_pages) — "
            "نیازی به WP App Password نیست."
        )
        wc_setup_help.setStyleSheet("color:#888; font-size:10px;")
        wc_setup_help.setWordWrap(True)

        wp_help = QLabel(
            "Application Password برای آپلود تصویر (دسته‌بندی و محصول) لازم است.\n"
            "WP Username = ستون Username در Users → All Users (مثلاً admin).\n"
            "WP App Password = رشتهٔ کپی‌شده از Application Passwords (نه نام دلخواه رمز).\n"
            "اگر تست خطای LiteSpeed/WAF داد، ساخت رمز جدید کمکی نمی‌کند — باید هاست wp-json را باز کند."
        )
        wp_help.setStyleSheet("color:#64748b; font-size:10px;")
        wp_help.setWordWrap(True)
        self.wp_app_password_button = QPushButton("🔗 باز کردن Application Passwords")
        self.wp_app_password_button.setFlat(True)
        self.wp_app_password_button.setCursor(Qt.PointingHandCursor)
        self.wp_app_password_button.clicked.connect(self._open_wp_app_password_page)

        self.wp_users_page_button = QPushButton("👥 Users در وردپرس")
        self.wp_users_page_button.setMinimumHeight(38)
        self.wp_users_page_button.setToolTip("باز کردن Users → All Users برای دیدن Username واقعی")
        self.wp_users_page_button.clicked.connect(self._open_wp_users_page)

        self.wp_username_picker_button = QPushButton("📋 انتخاب از سایت")
        self.wp_username_picker_button.setMinimumHeight(38)
        self.wp_username_picker_button.setToolTip(
            "دریافت خودکار نام‌های کاربری از وردپرس — مدیران در بالای لیست"
        )
        self.wp_username_picker_button.clicked.connect(self._pick_wp_username_from_site)

        wp_username_row = QWidget()
        wp_username_row_layout = QHBoxLayout(wp_username_row)
        wp_username_row_layout.setContentsMargins(0, 0, 0, 0)
        wp_username_row_layout.setSpacing(8)
        wp_username_row_layout.addWidget(self.wp_username_input, 1)
        wp_username_row_layout.addWidget(self.wp_users_page_button)
        wp_username_row_layout.addWidget(self.wp_username_picker_button)

        self.wp_test_button = QPushButton("تست Application Password")
        self.wp_test_button.setMinimumHeight(38)
        self.wp_test_button.clicked.connect(self.test_wp_app_password)

        # --- پلتفرم فروشگاه: ووکامرس یا پرستاشاپ ---
        self.store_platform_combo = QComboBox()
        self.store_platform_combo.addItem("ووکامرس (WooCommerce)", "woocommerce")
        self.store_platform_combo.addItem("پرستاشاپ (PrestaShop)", "prestashop")
        self.store_platform_combo.setMinimumHeight(38)
        _current_platform = str(self.config.get("STORE_PLATFORM") or "woocommerce")
        _platform_idx = self.store_platform_combo.findData(_current_platform)
        self.store_platform_combo.setCurrentIndex(_platform_idx if _platform_idx >= 0 else 0)

        platform_help = QLabel(
            "با انتخاب پلتفرم، فقط فیلدهای همان پلتفرم نمایش داده می‌شوند."
        )
        platform_help.setStyleSheet("color:#64748b; font-size:10px;")
        platform_help.setWordWrap(True)

        wc_form_layout.addRow(QLabel("پلتفرم فروشگاه:"), self.store_platform_combo)
        wc_form_layout.addRow(QLabel(""), platform_help)

        wc_section_label = QLabel("ووکامرس (WooCommerce)")
        wc_section_label.setStyleSheet("font-weight:700; margin-top:10px;")
        wc_form_layout.addRow(QLabel(""), wc_section_label)

        wc_form_layout.addRow(QLabel("سایت فعال:"), wc_site_row)
        wc_form_layout.addRow(QLabel("نام پروفایل:"), self.wc_site_name_input)
        wc_form_layout.addRow(QLabel(""), wc_sites_help)
        wc_form_layout.addRow(english_caption("WC URL:"), self.url_input)
        wc_form_layout.addRow(english_caption("Consumer Key:"), self.ck_input)
        wc_form_layout.addRow(english_caption("Consumer Secret:"), self.cs_input)
        wc_form_layout.addRow(QLabel(""), wc_api_help)
        wc_form_layout.addRow(QLabel(""), self.wc_api_keys_button)
        wc_form_layout.addRow(english_caption("WP Username:"), wp_username_row)
        wc_form_layout.addRow(english_caption("WP App Password:"), self.wp_app_password_input)
        wc_form_layout.addRow(QLabel(""), wp_help)
        wc_form_layout.addRow(QLabel(""), self.wp_app_password_button)
        wc_form_layout.addRow(QLabel(""), self.wp_test_button)
        wc_form_layout.addRow(english_caption("Timeout:"), self.timeout_input)
        wc_form_layout.addRow(QLabel(f"تبدیل قیمت {erp_provider_label(self.config)}:"), self.currency_combo)

        self.product_mode_combo = QComboBox()
        from sync_app.core.product_mode import get_product_mode, MODE_SIMPLE_ONLY, MODE_WITH_VARIANTS
        self.product_mode_combo.addItem("دارای ویژگی و متغیر (پیش‌فرض)", MODE_WITH_VARIANTS)
        self.product_mode_combo.addItem("فقط محصولات ساده", MODE_SIMPLE_ONLY)
        current_mode = get_product_mode(self.config)
        idx = self.product_mode_combo.findData(current_mode)
        self.product_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.product_mode_combo.setToolTip(
            "اگه فروشگاهتون فقط محصول ساده داره (بدون رنگ/سایز/متغیر)، این رو "
            "روی «فقط ساده» بذارید تا تب‌ها و بخش‌های مربوط به ویژگی/متغیر "
            "از همه‌جای برنامه مخفی بشن. بعد از تغییر، برنامه رو ببندید و "
            "دوباره باز کنید تا اثر کنه."
        )
        self.product_mode_detect_btn = QPushButton("🔍 تشخیص خودکار از دیتابیس")
        self.product_mode_detect_btn.setToolTip(
            f"به دیتابیس {erp_provider_label(self.config)} وصل می‌شه و واقعاً چک می‌کنه تو گروه‌های انتخابی‌تون "
            "محصول متغیر (چند سایز/رنگ) هست یا نه — و بر همون اساس پیشنهاد می‌ده."
        )
        self.product_mode_detect_btn.clicked.connect(self._detect_product_mode)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.product_mode_combo)
        mode_row.addWidget(self.product_mode_detect_btn)
        wc_form_layout.addRow(QLabel("نوع محصولات فروشگاه:"), mode_row)
        site_currency_row = QHBoxLayout()
        site_currency_row.addWidget(self.site_currency_label)
        site_currency_row.addWidget(self.site_currency_refresh_btn)
        site_currency_row.addStretch()
        wc_form_layout.addRow(QLabel("واحد پول سایت (فقط نمایش):"), site_currency_row)
        wc_form_layout.addRow(QLabel(""), wc_test_widget)
        wc_form_layout.addRow(QLabel(""), wc_setup_help)

        # --- پرستاشاپ (Webservice API) ---
        ps_section_label = QLabel("پرستاشاپ (PrestaShop)")
        ps_section_label.setStyleSheet("font-weight:700; margin-top:10px;")
        wc_form_layout.addRow(QLabel(""), ps_section_label)

        from sync_app.core.ps_site_profiles import (
            copy_sites as ps_copy_sites,
            create_empty_site as ps_create_empty_site,
            find_ps_site,
            get_active_site_id as ps_get_active_site_id,
            get_ps_sites,
            site_display_label as ps_site_display_label,
        )

        self._ps_sites = ps_copy_sites(get_ps_sites(self.config))
        self._active_ps_site_id = ps_get_active_site_id(self.config)
        if not self._ps_sites:
            self._ps_sites = [ps_create_empty_site(label="سایت ۱")]
            self._active_ps_site_id = str(self._ps_sites[0].get("id") or "")

        self.ps_site_combo = QComboBox()
        self.ps_site_combo.setMinimumHeight(38)
        self.ps_site_combo.setLayoutDirection(Qt.LeftToRight)
        self.ps_add_site_btn = QPushButton("➕ سایت جدید")
        self.ps_add_site_btn.setMinimumHeight(38)
        self.ps_delete_site_btn = QPushButton("🗑 حذف")
        self.ps_delete_site_btn.setMinimumHeight(38)
        self.ps_add_site_btn.clicked.connect(self._on_add_ps_site)
        self.ps_delete_site_btn.clicked.connect(self._on_delete_ps_site)
        self.ps_site_combo.currentIndexChanged.connect(self._on_ps_site_combo_changed)

        self.ps_site_name_input = QLineEdit()
        self.ps_site_name_input.setMinimumHeight(38)
        self.ps_site_name_input.setPlaceholderText("نام دلخواه فروشگاه (مثلاً فروشگاه اصلی)")
        self.ps_site_name_input.editingFinished.connect(self._on_ps_site_name_changed)

        ps_site_row = QWidget()
        ps_site_row_layout = QHBoxLayout(ps_site_row)
        ps_site_row_layout.setContentsMargins(0, 0, 0, 0)
        ps_site_row_layout.setSpacing(8)
        ps_site_row_layout.addWidget(self.ps_site_combo, 1)
        ps_site_row_layout.addWidget(self.ps_add_site_btn)
        ps_site_row_layout.addWidget(self.ps_delete_site_btn)

        ps_sites_help = QLabel(
            "هر فروشگاه با URL و کلید Webservice جدا ذخیره می‌شود.\n"
            "اگر تنظیمات مربوط به فروشگاه دیگری است، «سایت جدید +» بزنید — "
            "ویرایش پروفایل موجود، اطلاعات همان سایت را بازنویسی می‌کند."
        )
        ps_sites_help.setStyleSheet("color:#64748b; font-size:10px;")
        ps_sites_help.setWordWrap(True)

        wc_form_layout.addRow(QLabel("فروشگاه پرستاشاپ:"), ps_site_row)
        wc_form_layout.addRow(QLabel("نام سایت:"), self.ps_site_name_input)
        wc_form_layout.addRow(QLabel(""), ps_sites_help)

        self.ps_url_input = QLineEdit(self.config.get("PS_URL", ""))
        self.ps_url_input.setPlaceholderText("https://your-prestashop-store.com")
        self.ps_api_key_input = PasswordLineEdit(self.config.get("PS_API_KEY", ""))
        self.ps_api_key_input.setPlaceholderText("کلید Webservice API")
        self.ps_api_key_input.set_toggle_tooltip_base("کلید Webservice")

        for field in [self.ps_url_input, self.ps_api_key_input]:
            field.setLayoutDirection(Qt.LeftToRight)
            field.setAlignment(Qt.AlignLeft)
            field.setMinimumHeight(38)

        ps_api_help = QLabel(
            "کلید Webservice: پیشخوان پرستاشاپ → Advanced Parameters → Webservice → Add new webservice key.\n"
            "دسترسی GET/PUT/POST را برای منابع products، categories و stock_availables فعال کنید.\n"
            "⚠️ پشتیبانی پرستاشاپ در حال حاضر شامل دسته‌بندی و محصول ساده (بدون واریانت) است."
        )
        ps_api_help.setStyleSheet("color:#64748b; font-size:10px;")
        ps_api_help.setWordWrap(True)

        self.ps_test_button = QPushButton("تست اتصال پرستاشاپ")
        self.ps_test_button.setMinimumHeight(38)
        self.ps_test_button.clicked.connect(self.test_ps_connection)

        wc_form_layout.addRow(english_caption("PrestaShop URL:"), self.ps_url_input)
        wc_form_layout.addRow(english_caption("Webservice API Key:"), self.ps_api_key_input)
        wc_form_layout.addRow(QLabel(""), ps_api_help)
        wc_form_layout.addRow(QLabel(""), self.ps_test_button)

        self._refresh_ps_site_combo(select_id=self._active_ps_site_id)
        active_ps_site = find_ps_site(self._ps_sites, self._active_ps_site_id)
        if active_ps_site:
            self.ps_url_input.setText(str(active_ps_site.get("url") or self.ps_url_input.text()))
            self.ps_api_key_input.setText(str(active_ps_site.get("api_key") or self.ps_api_key_input.text()))
            self.ps_site_name_input.setText(str(active_ps_site.get("label") or ""))
        self._snapshot_ps_site_baseline()

        # --- نمایش/مخفی‌کردن فیلدهای مخصوص هر پلتفرم بر اساس store_platform_combo ---
        # currency_combo/product_mode_combo عمداً اینجا نیستن — این دو مشترک بین هر
        # دو پلتفرمن (تبدیل قیمت ERP و نوع محصول)، نه مخصوص ووکامرس.
        self._wc_only_fields = [
            wc_section_label,
            wc_site_row, self.wc_site_name_input, wc_sites_help,
            self.url_input, self.ck_input, self.cs_input,
            wc_api_help, self.wc_api_keys_button,
            wp_username_row, self.wp_app_password_input, wp_help,
            self.wp_app_password_button, self.wp_test_button,
            self.timeout_input,
            site_currency_row, self.site_currency_label, self.site_currency_refresh_btn,
            wc_test_widget, wc_setup_help,
        ]
        self._ps_only_fields = [
            ps_section_label,
            ps_site_row, self.ps_site_name_input, ps_sites_help,
            self.ps_url_input, self.ps_api_key_input,
            ps_api_help, self.ps_test_button,
        ]
        self.store_platform_combo.currentIndexChanged.connect(
            lambda _idx: self._apply_platform_field_visibility()
        )
        self._apply_platform_field_visibility()

        # --- تلگرام (برای تقویم محتوا) — مستقل از پلتفرم فروشگاه، همیشه نمایان ---
        from sync_app.core.telegram_poster import (
            TELEGRAM_BOT_TOKEN_KEY,
            TELEGRAM_CHAT_ID_KEY,
            TELEGRAM_PROXY_URL_KEY,
        )

        self.telegram_group = QGroupBox("تلگرام (برای تقویم محتوا)")
        self.telegram_group.setLayoutDirection(Qt.LeftToRight)
        telegram_layout = QFormLayout()
        telegram_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        telegram_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        telegram_layout.setFormAlignment(Qt.AlignTop)
        telegram_layout.setHorizontalSpacing(14)
        telegram_layout.setVerticalSpacing(10)

        self.telegram_bot_token_input = PasswordLineEdit(str(self.config.get(TELEGRAM_BOT_TOKEN_KEY) or ""))
        self.telegram_bot_token_input.setPlaceholderText("123456:ABC-DEF...")
        self.telegram_chat_id_input = QLineEdit(str(self.config.get(TELEGRAM_CHAT_ID_KEY) or ""))
        self.telegram_chat_id_input.setPlaceholderText("@channel_username یا -1001234567890")
        self.telegram_proxy_url_input = QLineEdit(str(self.config.get(TELEGRAM_PROXY_URL_KEY) or ""))
        self.telegram_proxy_url_input.setPlaceholderText("مثلاً socks5://127.0.0.1:1080 (اختیاری)")
        for field in (self.telegram_bot_token_input, self.telegram_chat_id_input, self.telegram_proxy_url_input):
            field.setLayoutDirection(Qt.LeftToRight)
            field.setAlignment(Qt.AlignLeft)
            field.setMinimumHeight(38)

        telegram_help = QLabel(
            "توکنِ بات: با @BotFather بسازید. شناسه‌ی چت: نامِ کاربریِ کانال (با @) یا آیدیِ عددیِ آن — "
            "ربات باید ادمینِ کانال/گروه باشد.\n"
            "⚠️ api.telegram.org معمولاً در ایران فیلتر است — اگه اتصال با خطای "
            "«Connection refused» ناموفق شد، آدرسِ یک پراکسی (VPNِ محلی یا socks5) را در فیلدِ پراکسی وارد کنید."
        )
        telegram_help.setStyleSheet("color:#64748b; font-size:10px;")
        telegram_help.setWordWrap(True)

        self.telegram_test_button = QPushButton("تست اتصال تلگرام")
        self.telegram_test_button.setMinimumHeight(38)
        self.telegram_test_button.clicked.connect(self._test_telegram_connection)

        telegram_layout.addRow(english_caption("Bot Token:"), self.telegram_bot_token_input)
        telegram_layout.addRow(english_caption("Chat ID:"), self.telegram_chat_id_input)
        telegram_layout.addRow(english_caption("Proxy URL:"), self.telegram_proxy_url_input)
        telegram_layout.addRow(QLabel(""), telegram_help)
        telegram_layout.addRow(QLabel(""), self.telegram_test_button)
        self.telegram_group.setLayout(telegram_layout)

        # --- بله (Bale) — برای تقویمِ محتوا، فیلتر نیست، نیازی به پراکسی نداره ---
        from sync_app.core.bale_poster import BALE_BOT_TOKEN_KEY, BALE_CHAT_ID_KEY

        self.bale_group = QGroupBox("بله — Bale (برای تقویم محتوا)")
        self.bale_group.setLayoutDirection(Qt.LeftToRight)
        bale_layout = QFormLayout()
        bale_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        bale_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        bale_layout.setFormAlignment(Qt.AlignTop)
        bale_layout.setHorizontalSpacing(14)
        bale_layout.setVerticalSpacing(10)

        self.bale_bot_token_input = PasswordLineEdit(str(self.config.get(BALE_BOT_TOKEN_KEY) or ""))
        self.bale_bot_token_input.setPlaceholderText("123456:AAHdq...")
        self.bale_chat_id_input = QLineEdit(str(self.config.get(BALE_CHAT_ID_KEY) or ""))
        self.bale_chat_id_input.setPlaceholderText("@channel_username یا -1001234567890")
        for field in (self.bale_bot_token_input, self.bale_chat_id_input):
            field.setLayoutDirection(Qt.LeftToRight)
            field.setAlignment(Qt.AlignLeft)
            field.setMinimumHeight(38)

        bale_help = QLabel(
            "ساختِ بات: در برنامه‌ی بله سرچ کنید «BotFather» و مراحلِ مشابهِ تلگرام را طی کنید. "
            "بله در ایران فیلتر نیست — نیازی به پراکسی/VPN ندارد."
        )
        bale_help.setStyleSheet("color:#64748b; font-size:10px;")
        bale_help.setWordWrap(True)

        self.bale_test_button = QPushButton("تست اتصال بله")
        self.bale_test_button.setMinimumHeight(38)
        self.bale_test_button.clicked.connect(self._test_bale_connection)

        bale_layout.addRow(english_caption("Bot Token:"), self.bale_bot_token_input)
        bale_layout.addRow(english_caption("Chat ID:"), self.bale_chat_id_input)
        bale_layout.addRow(QLabel(""), bale_help)
        bale_layout.addRow(QLabel(""), self.bale_test_button)
        self.bale_group.setLayout(bale_layout)

        self.monitor_group = QGroupBox("مانیتورینگ عملیات اتصال")
        monitor_layout = QVBoxLayout()
        monitor_layout.setContentsMargins(10, 10, 10, 10)
        monitor_layout.setSpacing(8)

        monitor_toolbar = QHBoxLayout()
        monitor_toolbar.setContentsMargins(0, 0, 0, 0)
        monitor_toolbar.setSpacing(8)

        self.monitor_state_badge = QLabel("● فعال")
        self.monitor_state_badge.setStyleSheet(
            "color:#16a34a; background:#dcfce7; border-radius:10px; padding:4px 10px; font-weight:700; font-size:11px;"
        )
        monitor_toolbar.addWidget(self.monitor_state_badge)
        monitor_toolbar.addStretch()

        self.monitor_toggle_btn = QPushButton("بستن مانیتورینگ")
        self.monitor_toggle_btn.setFlat(True)
        self.monitor_toggle_btn.setMinimumHeight(30)
        self.monitor_toggle_btn.clicked.connect(self.toggle_monitoring_panel)
        monitor_toolbar.addWidget(self.monitor_toggle_btn)

        copy_monitor_btn = QPushButton("کپی لاگ")
        copy_monitor_btn.setFlat(True)
        copy_monitor_btn.setMinimumHeight(30)
        copy_monitor_btn.setToolTip("کپی کل گزارش تست SQL و فروشگاه در کلیپبورد")
        copy_monitor_btn.clicked.connect(self.copy_monitor_logs)
        monitor_toolbar.addWidget(copy_monitor_btn)

        clear_monitor_btn = QPushButton("پاکسازی گزارش")
        clear_monitor_btn.setFlat(True)
        clear_monitor_btn.setMinimumHeight(30)
        clear_monitor_btn.clicked.connect(self.clear_monitor)
        monitor_toolbar.addWidget(clear_monitor_btn)

        self.monitor_view = QPlainTextEdit()
        self.monitor_view.setReadOnly(True)
        self.monitor_view.setObjectName("log_view")
        self.monitor_view.setMinimumHeight(150)
        self.monitor_view.setLayoutDirection(Qt.LeftToRight)
        self.monitor_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.monitor_view.document().setMaximumBlockCount(400)
        self.monitor_view.setPlaceholderText("گزارش تست‌های اتصال اینجا نمایش داده می‌شود...")

        self.monitor_body = QWidget()
        monitor_body_layout = QVBoxLayout(self.monitor_body)
        monitor_body_layout.setContentsMargins(0, 0, 0, 0)
        monitor_body_layout.setSpacing(6)
        monitor_body_layout.addWidget(self.monitor_view)

        monitor_layout.addLayout(monitor_toolbar)
        monitor_layout.addWidget(self.monitor_body)
        self.monitor_group.setLayout(monitor_layout)

        sql_group.setLayout(sql_layout)
        app_group.setLayout(app_layout)
        wc_group.setLayout(wc_form_layout)
        self.sql_group = sql_group
        self.app_group = app_group
        self.wc_group = wc_group

        # ── گروه مشتری پیش‌فرض ──────────────────────────────────
        customer_group = QGroupBox("تنظیمات مشتری پیش‌فرض")
        customer_form = QFormLayout()
        customer_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        customer_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        customer_form.setHorizontalSpacing(14)
        customer_form.setVerticalSpacing(10)

        self.default_customer_mode_combo = QComboBox()
        self.default_customer_mode_combo.addItem("مشتریان سایت (خریداران ثبت‌نام‌شده)", "website")
        self.default_customer_mode_combo.addItem("مشتری ثابت (کد مشتری مشخص)", "fixed")
        self.default_customer_mode_combo.addItem("همه مشتریان فروشگاه", "all")
        saved_mode = self.config.get("DEFAULT_CUSTOMER_MODE", "website")
        mode_idx = self.default_customer_mode_combo.findData(saved_mode)
        if mode_idx >= 0:
            self.default_customer_mode_combo.setCurrentIndex(mode_idx)
        self.default_customer_mode_combo.currentIndexChanged.connect(self._on_default_customer_mode_changed)

        self.default_customer_code_input = QLineEdit(str(self.config.get("DEFAULT_CUSTOMER_CODE", "")))
        self.default_customer_code_input.setPlaceholderText("کد مشتری پیش‌فرض در نرم‌افزار")
        self.default_customer_code_label = QLabel("کد مشتری ثابت:")

        customer_form.addRow(QLabel("حالت مشتری پیش‌فرض:"), self.default_customer_mode_combo)
        customer_form.addRow(self.default_customer_code_label, self.default_customer_code_input)
        customer_group.setLayout(customer_form)
        self.customer_group = customer_group
        self._on_default_customer_mode_changed()  # نمایش/مخفی کردن بر اساس مقدار اولیه

        # ── گروه فیلدهای قابل‌انتخاب همگام‌سازی (محصول/دسته/ویژگی/متغیر) ──
        fields_group = QGroupBox("فیلدهای همگام‌سازی (SQL → فروشگاه)")
        fields_layout = QVBoxLayout()
        fields_layout.setSpacing(6)
        fields_hint = QLabel(
            "اگر تیک فیلدی برداشته شود، آن فیلد در همگام‌سازی ارسال نمی‌شود و "
            "مقدار فعلی آن روی سایت دست‌نخورده می‌ماند (حتی اگر در دیتابیس خالی باشد)."
        )
        fields_hint.setWordWrap(True)
        fields_hint.setStyleSheet("color:#64748b; font-size:10px;")
        fields_layout.addWidget(fields_hint)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("تعداد محصول هم‌زمان در ارسال (سرعت سینک):"))
        self.parallel_workers_spin = QSpinBox()
        self.parallel_workers_spin.setRange(1, 10)
        self.parallel_workers_spin.setValue(min(10, int(self.config.get("WC_PARALLEL_WORKERS", 10) or 10)))
        self.parallel_workers_spin.setToolTip(
            "چندتا محصول با هم (هم‌زمان) به فروشگاه ارسال بشه.\n"
            "عدد بیشتر = سریع‌تر، ولی فشار بیشتر رو هاست سایت.\n"
            "حداکثر ۱۰ (بیشتر از این، خیلی از هاست‌ها این رفتار رو حمله‌ی DDoS "
            "تشخیص می‌دن و IP سرور شما رو موقتاً بلاک می‌کنن)."
        )
        speed_row.addWidget(self.parallel_workers_spin)
        speed_row.addStretch()
        fields_layout.addLayout(speed_row)

        for group_label, fields in ALL_FIELD_GROUPS:
            sub_label = QLabel(group_label)
            sub_label.setStyleSheet("font-weight:700; margin-top:6px;")
            fields_layout.addWidget(sub_label)
            for cfg_key, _label, _default in fields:
                fields_layout.addWidget(self._field_sync_checkboxes[cfg_key])

        force_sync_label = QLabel("سینکِ کامل (نادیده گرفتنِ تشخیصِ تغییر)")
        force_sync_label.setStyleSheet("font-weight:700; margin-top:12px;")
        fields_layout.addWidget(force_sync_label)
        force_sync_hint = QLabel(
            "پیش‌فرض فقط چیزهایی که واقعاً در دیتابیس عوض شده‌اند دوباره ارسال می‌شوند. "
            "اگر لازم شد یک بخش را کامل و از اول دوباره بفرستید (مثلاً برای عیب‌یابی)، "
            "همان بخش را این‌جا فعال کنید."
        )
        force_sync_hint.setWordWrap(True)
        force_sync_hint.setStyleSheet("color:#64748b; font-size:10px;")
        fields_layout.addWidget(force_sync_hint)
        for cfg_key, _label, _default in FORCE_FULL_SYNC_FIELDS:
            fields_layout.addWidget(self._force_full_sync_checkboxes[cfg_key])

        fields_group.setLayout(fields_layout)
        self.fields_group = fields_group

        license_group = QGroupBox("تنظیمات لایسنس")
        license_form = QFormLayout()
        license_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        license_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        license_form.setHorizontalSpacing(14)
        license_form.setVerticalSpacing(10)

        license_form.addRow(QLabel("آدرس سرور لایسنس:"), self.license_server_url_input)
        license_form.addRow(QLabel("کلید API لایسنس:"), self.license_api_key_input)
        license_form.addRow(QLabel(""), license_api_help)
        license_form.addRow(QLabel(""), self.license_api_key_button)
        license_group.setLayout(license_form)
        self.license_group = license_group

        # ── پشتیبان‌های خودکار تنظیمات ──────────────────────────────
        backup_group = QGroupBox("💾 پشتیبان‌های خودکار تنظیمات")
        backup_layout = QVBoxLayout()
        backup_hint = QLabel(
            "قبل از هر ذخیره، یک نسخه از تنظیمات قبلی خودکار نگه داشته می‌شود "
            "(آخرین ۱۵ نسخه). اگر تنظیمات به‌اشتباه تغییر کرد، از اینجا برگردانید."
        )
        backup_hint.setWordWrap(True)
        backup_hint.setStyleSheet("color:#64748b; font-size:10px;")
        backup_layout.addWidget(backup_hint)

        self.backup_list = QListWidget()
        self.backup_list.setMaximumHeight(140)
        backup_layout.addWidget(self.backup_list)

        backup_btn_row = QHBoxLayout()
        self.backup_refresh_btn = QPushButton("🔄 بروزرسانی لیست")
        self.backup_refresh_btn.clicked.connect(self._refresh_backup_list)
        backup_btn_row.addWidget(self.backup_refresh_btn)
        self.backup_restore_btn = QPushButton("↩️ بازیابی نسخه‌ی انتخاب‌شده")
        self.backup_restore_btn.clicked.connect(self._restore_selected_backup)
        backup_btn_row.addWidget(self.backup_restore_btn)
        backup_btn_row.addStretch()
        backup_layout.addLayout(backup_btn_row)

        backup_group.setLayout(backup_layout)
        self.backup_group = backup_group
        self._refresh_backup_list()

        self.main_grid = QGridLayout()
        self.main_grid.setHorizontalSpacing(12)
        self.main_grid.setVerticalSpacing(12)
        root_layout.addLayout(self.main_grid)

        scroll_area.setWidget(container)
        outer_layout.addWidget(scroll_area)

        # ── نوار ذخیره چسبیده به پایین (خارج از اسکرول) ────────────────
        self._save_bar = QWidget()
        self._save_bar.setObjectName("saveBar")
        self._save_bar.setStyleSheet(
            "QWidget#saveBar { border-top: 2px solid #cbd5e1; background: #f1f5f9; }"
        )
        save_bar_layout = QHBoxLayout(self._save_bar)
        save_bar_layout.setContentsMargins(16, 8, 16, 8)
        save_bar_layout.setSpacing(12)

        self.status_label = QLabel("آماده")
        self.status_label.setStyleSheet(
            "color: #16a34a; font-weight: 700; font-size: 12px; "
            "padding: 6px 14px; background: #dcfce7; border-radius: 8px;"
        )
        save_bar_layout.addWidget(self.status_label)
        save_bar_layout.addStretch()

        self._unlock_btn = QPushButton("🔓 ویرایش (نیاز به رمز دوم)")
        self._unlock_btn.setObjectName("devUnlockBtn")
        self._unlock_btn.setMinimumHeight(44)
        self._unlock_btn.setStyleSheet("font-size:12px; font-weight:700; padding:10px 20px;")
        self._unlock_btn.clicked.connect(self._toggle_dev_lock)
        save_bar_layout.addWidget(self._unlock_btn)

        self._save_btn = QPushButton("💾  ذخیره تنظیمات")
        self._save_btn.setMinimumHeight(44)
        self._save_btn.setMinimumWidth(170)
        self._save_btn.setStyleSheet(
            "font-size: 13px; font-weight: 700; padding: 10px 28px;"
        )
        self._save_btn.clicked.connect(self.save_config)
        save_bar_layout.addWidget(self._save_btn)

        outer_layout.addWidget(self._save_bar)
        self.setLayout(outer_layout)

        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self._dev_unlock_shortcut = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self._dev_unlock_shortcut.activated.connect(self._toggle_dev_lock)

        # ── اتصال سیگنال‌های تغییر برای تشخیص تغییرات ذخیره‌نشده ──────
        self._tracked_widgets = [
            self.server_input, self.database_input, self.username_input,
            self.password_input, self.url_input, self.ck_input,
            self.cs_input, self.wp_username_input, self.wp_app_password_input,
            self.timeout_input, self.wc_site_combo, self.wc_site_name_input, self.app_login_username_input,
            self.app_login_password_input, self.license_server_url_input,
            self.license_api_key_input, self.default_customer_code_input,
            self.driver_input, self.price_combo, self.price_markup_spin, self.sale_price_enabled_cb,
            self.sale_price_combo, self.sale_price_markup_spin, self.erp_picture_root_input, self.theme_combo,
            self.font_size_combo, self.erp_provider_combo, self.currency_combo,
            self.default_customer_mode_combo, self.login_screen_enabled_checkbox,
            self.auto_update_enabled_checkbox,
            self.ps_url_input, self.ps_api_key_input, self.ps_site_combo, self.ps_site_name_input,
            self.telegram_bot_token_input, self.telegram_chat_id_input, self.telegram_proxy_url_input,
            self.bale_bot_token_input, self.bale_chat_id_input,
        ] + list(self._field_sync_checkboxes.values()) + list(self._force_full_sync_checkboxes.values())

        _text_inputs = [
            self.server_input, self.database_input, self.username_input,
            self.password_input, self.url_input, self.ck_input,
            self.cs_input, self.wp_username_input, self.wp_app_password_input,
            self.timeout_input, self.wc_site_name_input,
            self.app_login_username_input, self.app_login_password_input, self.license_server_url_input,
            self.license_api_key_input, self.default_customer_code_input,
            self.ps_url_input, self.ps_api_key_input, self.ps_site_name_input,
            self.telegram_bot_token_input, self.telegram_chat_id_input, self.telegram_proxy_url_input,
            self.bale_bot_token_input, self.bale_chat_id_input,
        ]
        for w in _text_inputs:
            w.textChanged.connect(self._on_settings_field_changed)

        _combo_inputs = [
            self.driver_input, self.price_combo, self.sale_price_combo,
            self.theme_combo, self.font_size_combo, self.erp_provider_combo,
            self.currency_combo, self.default_customer_mode_combo,
        ]
        for w in _combo_inputs:
            w.currentIndexChanged.connect(self._on_settings_field_changed)

        for w in (self.login_screen_enabled_checkbox, self.auto_update_enabled_checkbox, self.sale_price_enabled_cb):
            w.stateChanged.connect(self._on_settings_field_changed)
        for w in self._field_sync_checkboxes.values():
            w.stateChanged.connect(self._on_settings_field_changed)
        for w in self._force_full_sync_checkboxes.values():
            w.stateChanged.connect(self._on_settings_field_changed)

        self.erp_picture_root_input.textChanged.connect(self._on_settings_field_changed)

        if not (self.sql_mdf_path_input.text() or "").strip():
            QTimer.singleShot(200, lambda: self._sync_mdf_from_selected_database(silent=True, background=True))
        self._db_picker_apply_enabled = True
        self._snapshot_field_baselines()
        self._update_responsive_layout()

        self._dev_locked = True
        self._apply_dev_lock_ui()

    def _clear_grid(self, grid):
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _update_responsive_layout(self):
        # در عرض زیاد: 2x2 ، در عرض کم: تک ستونه
        grid = getattr(self, "main_grid", None)
        if grid is None or not getattr(self, "sql_group", None):
            return

        compact = self.width() <= 1200
        if self._settings_compact is not None and compact == self._settings_compact:
            return

        self._clear_grid(grid)

        if compact:
            grid.addWidget(self.sql_group, 0, 0)
            grid.addWidget(self.app_group, 1, 0)
            grid.addWidget(self.wc_group, 2, 0)
            grid.addWidget(self.telegram_group, 3, 0)
            grid.addWidget(self.bale_group, 4, 0)
            grid.addWidget(self.customer_group, 5, 0)
            grid.addWidget(self.fields_group, 6, 0)
            grid.addWidget(self.license_group, 7, 0)
            grid.addWidget(self.monitor_group, 8, 0)
            grid.addWidget(self.backup_group, 9, 0)
        else:
            grid.addWidget(self.sql_group, 0, 0)
            grid.addWidget(self.app_group, 0, 1)
            grid.addWidget(self.wc_group, 1, 0)
            grid.addWidget(self.monitor_group, 1, 1)
            grid.addWidget(self.telegram_group, 2, 0)
            grid.addWidget(self.bale_group, 2, 1)
            grid.addWidget(self.customer_group, 3, 0)
            grid.addWidget(self.license_group, 3, 1)
            grid.addWidget(self.fields_group, 4, 0, 1, 2)
            grid.addWidget(self.backup_group, 5, 0, 1, 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)

        self._settings_compact = compact

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "main_grid", None) is not None and self.main_grid.count() == 0:
            self._settings_compact = None
            self._update_responsive_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_layout()

    def _ensure_sql_op_log(self):
        from sync_app.core.sql_operation_log_dialog import SqlOperationLogDialog

        if self._sql_op_log is None:
            self._sql_op_log = SqlOperationLogDialog(self)
            self._sql_op_log.action_requested.connect(self._on_sql_log_action_requested)
        return self._sql_op_log

    def _current_sql_server_for_diag(self):
        if getattr(self, "server_input", None) is not None:
            return self.server_input.text().strip()
        return ((self.config or {}).get("SQL_SERVER") or "").strip()

    def _diagnose_sql_issue(self, error_text=""):
        from sync_app.core.diagnostics import diagnose_sql

        return diagnose_sql(
            error_text=error_text,
            server=self._current_sql_server_for_diag(),
            config=self.config,
        ).to_dict()

    def _refresh_sql_service_button(self):
        if not getattr(self, "sql_start_service_btn", None):
            return
        if os.name != "nt":
            self.sql_start_service_btn.setVisible(False)
            return

        from sync_app.core.sql_windows_probe import (
            sql_browser_service_status,
            sqlexpress_service_status,
            uses_sqlexpress_server,
        )

        server = self._current_sql_server_for_diag()
        if not uses_sqlexpress_server(server):
            self.sql_start_service_btn.setVisible(False)
            return

        running, _detail = sqlexpress_service_status()
        browser = sql_browser_service_status()
        if running is False:
            self.sql_start_service_btn.setVisible(True)
            self._highlight_sql_start_button(True)
            self.sql_start_service_btn.setText("▶ روشن کردن SQL Express (خاموش)")
            return

        if running is True and browser is False:
            self.sql_start_service_btn.setVisible(True)
            self._highlight_sql_start_button(True)
            self.sql_start_service_btn.setText("▶ روشن کردن SQL Browser")
            return

        self.sql_start_service_btn.setVisible(running is not True)
        self._highlight_sql_start_button(False)
        self.sql_start_service_btn.setText("▶ روشن کردن SQL Express")

    def _highlight_sql_start_button(self, highlight):
        if not getattr(self, "sql_start_service_btn", None):
            return
        if highlight:
            self.sql_start_service_btn.setStyleSheet(
                "background-color: #ea580c; color: white; border-radius: 8px; "
                "padding: 10px 14px; font-weight: 700; font-size: 12px; min-height: 38px;"
            )
        else:
            self.sql_start_service_btn.setStyleSheet(
                "background-color: #1d4ed8; color: white; border-radius: 8px; "
                "padding: 10px 14px; font-weight: 700; font-size: 12px; min-height: 38px;"
            )

    def _offer_sql_service_action(self, error_text=""):
        diagnosis = self._diagnose_sql_issue(error_text)
        if not diagnosis.get("can_auto_fix"):
            if self._sql_op_log is not None:
                self._sql_op_log.hide_action()
            return diagnosis

        dlg = self._ensure_sql_op_log()
        dlg.show_action(
            diagnosis.get("action_id") or diagnosis.get("code") or "start_sqlexpress",
            diagnosis.get("action_label") or "▶ روشن کردن SQL Express",
            diagnosis.get("message_fa") or "",
        )
        self._highlight_sql_start_button(True)
        return diagnosis

    def _on_sql_start_service_button_clicked(self):
        from sync_app.core.sql_windows_probe import (
            sql_browser_service_status,
            sqlexpress_service_status,
        )

        running, _detail = sqlexpress_service_status()
        if running is True and sql_browser_service_status() is False:
            self._start_sqlexpress_service_clicked("start_browser", retry_sql_test=True)
            return
        self._start_sqlexpress_service_clicked("start_sqlexpress", retry_sql_test=True)

    def _on_sql_log_action_requested(self, action_id):
        action = (action_id or "start_sqlexpress").strip()
        if action in {"service_stopped", "unreachable"}:
            action = "start_sqlexpress"
        self._start_sqlexpress_service_clicked(action, retry_sql_test=True)

    def _start_sqlexpress_service_clicked(
        self, action_id="start_sqlexpress", *, retry_sql_test=False
    ):
        if self._sql_service_thread is not None and self._sql_service_thread.isRunning():
            self._sql_op_log_line("عملیات روشن کردن سرویس هنوز در حال اجراست...")
            return

        action = (action_id or "start_sqlexpress").strip()
        if action in {"service_stopped", "unreachable"}:
            action = "start_sqlexpress"
        elif action == "browser_stopped":
            action = "start_browser"

        self._sql_service_retry_test = bool(retry_sql_test)
        if not self._monitor_open:
            self._animate_monitor_panel(True)
        self._begin_sql_op_log("روشن کردن سرویس SQL", clear=False)
        self._sql_op_log_line("شروع روشن کردن سرویس SQL...")

        self.sql_start_service_btn.setEnabled(False)
        self.sql_start_service_btn.setText("در حال روشن کردن...")

        self._sql_service_thread = QThread(self)
        self._sql_service_worker = SqlServiceStartWorker(action)
        self._sql_service_worker.moveToThread(self._sql_service_thread)

        self._sql_service_thread.started.connect(self._sql_service_worker.run)
        self._sql_service_worker.log.connect(self._sql_op_log_line)
        self._sql_service_worker.success.connect(self._on_sql_service_success)
        self._sql_service_worker.error.connect(self._on_sql_service_error)
        self._sql_service_worker.finished.connect(self._sql_service_thread.quit)
        self._sql_service_worker.finished.connect(self._sql_service_worker.deleteLater)
        self._sql_service_thread.finished.connect(self._sql_service_thread.deleteLater)
        self._sql_service_thread.finished.connect(self._on_sql_service_finished)
        self._sql_service_thread.start()

    def _on_sql_service_success(self, result):
        msg = (result or {}).get("message") or "سرویس SQL روشن شد."
        self._sql_op_log_line(msg)
        if self._sql_op_log is not None:
            self._sql_op_log.hide_action()
            self._sql_op_log.set_finished(True, msg)
        self.status_label.setText(f"✅ {msg}")
        self.status_label.setStyleSheet("color: #166534; font-weight: bold;")
        self._refresh_sql_service_button()
        if self._sql_service_retry_test:
            QTimer.singleShot(400, self.test_sql_connection)

    def _on_sql_service_error(self, message):
        self._sql_op_log_line(f"❌ {message}")
        diagnosis = self._offer_sql_service_action(message)
        if self._sql_op_log is not None:
            self._sql_op_log.set_finished(False, "روشن کردن سرویس ناموفق")
        self.status_label.setText("❌ روشن کردن SQL ناموفق")
        self.status_label.setStyleSheet("color: #b91c1c; font-weight: bold;")
        extra = ""
        if diagnosis.get("code") == "not_installed":
            extra = "\n\nSQL Server Express را نصب کنید."
        QMessageBox.warning(
            self,
            "روشن کردن سرویس",
            f"{message}{extra}\n\n"
            "اگر UAC پرسیده شد تایید کنید، یا PeechaSync را Run as Administrator اجرا کنید.",
        )

    def _on_sql_service_finished(self):
        self.sql_start_service_btn.setEnabled(True)
        self._refresh_sql_service_button()
        self._sql_service_thread = None
        self._sql_service_worker = None
        self._sql_service_retry_test = False

    def _show_sql_operation_log(self):
        dlg = self._ensure_sql_op_log()
        if not dlg._log_view.toPlainText().strip():
            dlg.begin_operation("گزارش عملیات SQL", clear=False)
            dlg.append_line("هنوز عملیاتی اجرا نشده — «بارگذاری» یا «انتخاب فایل MDF» را بزنید.")
        else:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()

    def _begin_sql_op_log(self, title: str, *, clear: bool = True):
        dlg = self._ensure_sql_op_log()
        dlg.begin_operation(title, clear=clear)
        if not self._monitor_open:
            self._animate_monitor_panel(True)
        return dlg

    def _sql_op_log_line(self, message: str):
        self._append_monitor(message)
        if self._sql_op_log is not None:
            self._sql_op_log.append_line(message)

    def _update_launcher_sql_header(self, db_name: str):
        from sync_app.core.connectivity_guard import find_peecha_launcher

        launcher = find_peecha_launcher(self)
        if launcher is not None and hasattr(launcher, "set_sql_header_database"):
            launcher.set_sql_header_database(db_name)

    def _append_monitor(self, message):
        ts = datetime.now().strftime("%H:%M:%S")
        self.monitor_view.appendPlainText(f"[{ts}] {message}")
        self.monitor_view.verticalScrollBar().setValue(self.monitor_view.verticalScrollBar().maximum())

    def clear_monitor(self):
        self.monitor_view.clear()
        self._append_monitor("گزارش پاکسازی شد.")

    def copy_monitor_logs(self):
        text = self.monitor_view.toPlainText()
        if not text.strip():
            QMessageBox.information(self, "کپی لاگ", "گزارشی برای کپی وجود ندارد.")
            return
        clipboard = QApplication.clipboard()
        if clipboard is None:
            QMessageBox.warning(self, "کپی لاگ", "دسترسی به کلیپبورد میسر نشد.")
            return
        clipboard.setText(text)
        QMessageBox.information(self, "کپی لاگ", "گزارش مانیتورینگ در کلیپبورد کپی شد.")

    def toggle_monitoring_panel(self):
        target_open = not self._monitor_open
        self._animate_monitor_panel(target_open)

    def _animate_monitor_panel(self, open_panel):
        start_h = self.monitor_body.maximumHeight() if self.monitor_body.maximumHeight() > 0 else self.monitor_body.sizeHint().height()
        end_h = self.monitor_body.sizeHint().height() if open_panel else 0

        if self._monitor_anim is not None:
            self._monitor_anim.stop()

        self._monitor_anim = QPropertyAnimation(self.monitor_body, b"maximumHeight", self)
        self._monitor_anim.setDuration(160)
        self._monitor_anim.setStartValue(start_h)
        self._monitor_anim.setEndValue(end_h)
        self._monitor_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._monitor_anim.start()

        self._monitor_open = open_panel
        if self._monitor_open:
            self.monitor_toggle_btn.setText("بستن مانیتورینگ")
            self.monitor_state_badge.setText("● فعال")
            self.monitor_state_badge.setStyleSheet(
                "color:#16a34a; background:#dcfce7; border-radius:10px; padding:4px 10px; font-weight:700; font-size:11px;"
            )
        else:
            self.monitor_toggle_btn.setText("نمایش مانیتورینگ")
            self.monitor_state_badge.setText("● بسته")
            self.monitor_state_badge.setStyleSheet(
                "color:#475569; background:#e2e8f0; border-radius:10px; padding:4px 10px; font-weight:700; font-size:11px;"
            )

    def _normalize_driver_name(self, raw_driver):
        name = (raw_driver or "").strip()
        if name.startswith("{") and name.endswith("}"):
            name = name[1:-1].strip()
        return name

    def _build_conn_str(self, driver_name, auth_mode="sql", server_override=None):
        driver_clean = self._normalize_driver_name(driver_name)
        server = (server_override if server_override is not None else self.server_input.text() or "").strip()
        database = (self.database_input.text() or "").strip()
        username = (self.username_input.text() or "").strip()
        password = self.password_input.text() or ""

        parts = [f"DRIVER={{{driver_clean}}}", f"SERVER={server}"]
        if database:
            parts.append(f"DATABASE={database}")

        if auth_mode == "windows":
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={username}")
            parts.append(f"PWD={password}")

        # فقط روی درایورهای جدید SQL پارامترهای Encrypt/Trust اضافه شود
        if "ODBC Driver 18" in driver_clean or "ODBC Driver 17" in driver_clean:
            parts.append("Encrypt=no")
            parts.append("TrustServerCertificate=yes")

        return ";".join(parts) + ";"

    def _detect_auth_modes(self):
        username = (self.username_input.text() or "").strip()
        password = self.password_input.text() or ""

        # اگر اطلاعات کاربر وارد نشده، اول احراز هویت ویندوز تست می‌شود
        if not username and not password:
            return ["windows", "sql"]

        # در حالت پیش‌فرض با اطلاعات SQL تست می‌شود و بعد fallback ویندوز
        return ["sql", "windows"]

    def _installed_sql_drivers(self):
        try:
            drivers = _get_pyodbc().drivers()
        except Exception:
            drivers = []

        priority = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "SQL Server Native Client 11.0",
            "SQL Server",
        ]

        ranked = []
        for p in priority:
            if p in drivers:
                ranked.append(p)
        for d in drivers:
            if d not in ranked and "SQL" in d.upper():
                ranked.append(d)
        return ranked

    def get_conn_str(self):
        auth_mode = self._last_success_sql_auth_mode
        if auth_mode not in ["sql", "windows"]:
            auth_mode = self._detect_auth_modes()[0]
        return self._build_conn_str(self.driver_input.currentText(), auth_mode=auth_mode)

    def get_optimized_timeout(self):
        try:
            raw_value = int((self.timeout_input.text() or "60").strip())
        except Exception:
            raw_value = 60

        # بازه امن و بهینه برای API
        value = max(10, min(raw_value, 300))
        if str(value) != self.timeout_input.text().strip():
            self.timeout_input.setText(str(value))
        return value

    def apply_driver_preset(self):
        # اگر سرور از قبل پر شده یا در تنظیمات ذخیره شده، دست نزن
        if self.server_input.text().strip():
            return
        saved_server = ((self.config or {}).get("SQL_SERVER") or "").strip()
        if saved_server:
            self.server_input.setText(saved_server)
            return
        current = self.driver_input.currentText()
        if "ODBC Driver 18" in current:
            self.server_input.setText("localhost")
        if not self.username_input.text().strip():
            self.username_input.setText("sa")

    def test_sql_connection(self):
        if self._sql_test_thread is not None and self._sql_test_thread.isRunning():
            self._append_monitor("تست SQL قبلی هنوز در حال اجراست...")
            return

        installed = self._installed_sql_drivers()
        if not installed:
            self._append_monitor("هیچ SQL Driver نصب‌شده‌ای در سیستم شناسایی نشد.")
            QMessageBox.critical(self, "خطا", "هیچ درایور SQL Server روی سیستم شناسایی نشد.")
            self.set_button_status(self.sql_test_button, False)
            return

        if not self._monitor_open:
            self._animate_monitor_panel(True)

        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label = erp_provider_label(self.config)
        self._begin_sql_op_log(f"تست اتصال {erp_label}", clear=False)
        self._sql_op_log_line(f"شروع تست اتصال {erp_label}...")
        self._sql_op_log_line("UI در این حالت قفل نمی‌شود.")

        self.sql_test_button.setEnabled(False)
        self.sql_test_button.setText(f"در حال تست {erp_label}...")
        self.status_label.setText(f"در حال تست اتصال {erp_label}...")
        self.status_label.setStyleSheet("color: #d97706; font-weight: bold;")

        payload = {
            "SQL_DRIVER": self.driver_input.currentText(),
            "SQL_SERVER": self.server_input.text().strip(),
            "SQL_DATABASE": self.database_input.text().strip(),
            "SQL_USERNAME": self.username_input.text().strip(),
            "SQL_PASSWORD": self.password_input.text()
            or (self.config or {}).get("SQL_PASSWORD")
            or "",
            "SQL_PASSWORD": self.password_input.text()
            or (self.config or {}).get("SQL_PASSWORD")
            or "",
            "SQL_AUTH_MODE": self._last_success_sql_auth_mode,
            "installed_drivers": installed,
            "auth_modes": self._detect_auth_modes(),
        }

        self._sql_test_thread = QThread(self)
        self._sql_test_worker = SqlTestWorker(payload)
        self._sql_test_worker.moveToThread(self._sql_test_thread)

        self._sql_test_thread.started.connect(self._sql_test_worker.run)
        self._sql_test_worker.healed.connect(self._apply_sql_heal_patch)
        self._sql_test_worker.log.connect(self._sql_op_log_line)
        self._sql_test_worker.success.connect(self._on_sql_test_success)
        self._sql_test_worker.error.connect(self._on_sql_test_error)
        self._sql_test_worker.finished.connect(self._sql_test_thread.quit)
        self._sql_test_worker.finished.connect(self._sql_test_worker.deleteLater)
        self._sql_test_thread.finished.connect(self._sql_test_thread.deleteLater)
        self._sql_test_thread.finished.connect(self._on_sql_test_finished)
        self._sql_test_thread.start()

    def _on_sql_test_success(self, result):
        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label = erp_provider_label(self.config)
        drv = result.get("driver") or ""
        server_name = result.get("server") or ""
        auth_mode = result.get("auth_mode") or "sql"
        db_name = result.get("db_name") or "-"
        db_user = result.get("db_user") or "نامشخص"
        db_server = result.get("db_server") or server_name

        self._append_monitor(
            f"اتصال {erp_label} موفق: {drv} | {server_name} | {auth_mode} | DB: {db_name} | User: {db_user}"
        )

        idx = self.driver_input.findText(f"{{{drv}}}")
        if idx < 0:
            self.driver_input.addItem(f"{{{drv}}}")
            idx = self.driver_input.findText(f"{{{drv}}}")
        if idx >= 0:
            self.driver_input.setCurrentIndex(idx)

        self.server_input.setText(server_name)
        self._last_success_sql_auth_mode = auth_mode
        self.set_button_status(self.sql_test_button, True)
        self.status_label.setText(f"✅ اتصال {erp_label} برقرار است")
        self.status_label.setStyleSheet("color: #166534; font-weight: bold;")
        if self._sql_op_log is not None:
            self._sql_op_log.set_finished(True, f"تست {erp_label} موفق")
        QTimer.singleShot(100, self._load_databases_to_picker)
        QMessageBox.information(
            self,
            "موفقیت",
            f"اتصال به SQL Server برقرار شد.\nDriver فعال: {drv}\nServer فعال: {server_name}\n"
            f"شیوه اتصال: {auth_mode}\nDB: {db_name}\nUser: {db_user}\nServer واقعی: {db_server}",
        )

    def _on_sql_test_error(self, last_error):
        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label = erp_provider_label(self.config)
        hint = ""
        lowered = (last_error or "").lower()
        if (
            "im002" in lowered
            or "data source name not found" in lowered
            or "default driver specified" in lowered
        ):
            hint = (
                "\n\nراهنما: درایور SQL روی ویندوز نصب نیست یا نسخه ناسازگار است. "
                "ODBC Driver 17/18 for SQL Server را نصب کن."
            )
        elif (
            "dbnetlib" in lowered
            or "does not exist" in lowered
            or "08001" in lowered
            or "server is not found" in lowered
        ):
            hint = (
                "\n\nراهنما: Server یا Database اشتباه است یا سرویس SQL Server در دسترس نیست. "
                "اگر SQL Express داری، Server را روی .\\SQLEXPRESS بگذار."
            )
        elif "login failed" in lowered or "28000" in lowered:
            hint = (
                "\n\nراهنما: نام کاربری/رمز SQL اشتباه است. "
                "اگر از Windows Auth استفاده می‌کنی، Username/Password را خالی بگذار."
            )

        diagnosis = self._offer_sql_service_action(last_error)

        self.set_button_status(self.sql_test_button, False)
        self.status_label.setText(f"❌ تست {erp_label} ناموفق")
        self.status_label.setStyleSheet("color: #b91c1c; font-weight: bold;")
        if self._sql_op_log is not None:
            self._sql_op_log.set_finished(False, f"تست {erp_label} ناموفق")

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("خطا")
        msg_box.setText(f"خطا در اتصال به SQL Server:\n{last_error}{hint}")
        start_btn = None
        if diagnosis.get("can_auto_fix"):
            start_btn = msg_box.addButton(
                diagnosis.get("action_label") or "▶ روشن کردن SQL Express",
                QMessageBox.ActionRole,
            )
        msg_box.addButton("بستن", QMessageBox.RejectRole)
        msg_box.exec_()
        if start_btn is not None and msg_box.clickedButton() == start_btn:
            action_id = diagnosis.get("action_id") or "start_sqlexpress"
            self._start_sqlexpress_service_clicked(action_id, retry_sql_test=True)

    def _on_sql_test_finished(self):
        from sync_app.core.integrations.erp_provider import erp_provider_label

        erp_label = erp_provider_label(self.config)
        self.sql_test_button.setEnabled(True)
        if self.sql_test_button.text() not in ("✅ اتصال موفق", "❌ قطع اتصال"):
            self.sql_test_button.setText(f"تست اتصال {erp_label}")
        self._sql_test_thread = None
        self._sql_test_worker = None
        self._append_monitor(f"پایان تست اتصال {erp_label}.")

    def _open_wp_users_page(self):
        self._open_external_url(self._wp_admin_url("wp-admin/users.php"))

    def _focus_wp_username_field(self):
        """اسکرول به فیلد WP Username و هایلایت کوتاه."""
        self.wp_username_input.setFocus(Qt.OtherFocusReason)
        try:
            self.scroll_area.ensureWidgetVisible(self.wp_username_input, 40, 40)
        except Exception:
            pass
        self._highlight_input_widget(self.wp_username_input)

    def _highlight_input_widget(self, widget, duration_ms: int = 2800):
        if widget is None:
            return
        original = widget.styleSheet() or ""
        widget.setStyleSheet(
            f"{original}"
            "QLineEdit { border: 2px solid #f59e0b; background: #fffbeb; }"
        )
        QTimer.singleShot(
            duration_ms,
            lambda w=widget, s=original: w.setStyleSheet(s) if w is not None else None,
        )

    def _pick_wp_username_from_site(self, *, probe_password: bool = True, offer_retest: bool = False):
        from PyQt5.QtWidgets import QApplication

        from sync_app.core.wc_site_profiles import ensure_wc_sites
        from sync_app.core.wc_sync_helper import fetch_wp_users_for_picker

        self._stash_wc_form_to_active_site()
        cfg = ensure_wc_sites({**(load_secure_config(None) or {}), **self._wc_config_from_form()})

        prev_text = self.wp_username_picker_button.text()
        self.wp_username_picker_button.setEnabled(False)
        self.wp_username_picker_button.setText("در حال دریافت...")
        QApplication.processEvents()
        try:
            users, note = fetch_wp_users_for_picker(
                cfg,
                probe_password=probe_password,
                entered_username=self.wp_username_input.text().strip(),
            )
        finally:
            self.wp_username_picker_button.setEnabled(True)
            self.wp_username_picker_button.setText(prev_text)

        if not users:
            QMessageBox.warning(
                self,
                "کاربری یافت نشد",
                f"{note}\n\n"
                "می‌توانید با دکمه «Users در وردپرس» صفحه Users → All Users را باز کنید "
                "و ستون Username را دستی کپی کنید.",
            )
            return None

        return self._apply_wp_username_pick(
            users,
            self.wp_username_input.text().strip(),
            note,
            offer_retest=offer_retest,
        )

    def focus_wp_username_field(self):
        self._focus_wp_username_field()

    def pick_wp_username_from_site(self, *, probe_password: bool = True, offer_retest: bool = False):
        return self._pick_wp_username_from_site(
            probe_password=probe_password,
            offer_retest=offer_retest,
        )

    def apply_wp_username_pick(
        self,
        users,
        current_username: str,
        note: str,
        *,
        offer_retest: bool = False,
    ):
        return self._apply_wp_username_pick(
            users,
            current_username,
            note,
            offer_retest=offer_retest,
        )

    def _show_wp_app_password_error(self, err: str, cfg: dict):
        from sync_app.core.wp_auth_error_ui import show_wp_media_auth_error_dialog

        show_wp_media_auth_error_dialog(self, err, cfg)

    def _apply_wp_username_pick(
        self,
        users,
        current_username: str,
        note: str,
        *,
        offer_retest: bool = False,
    ):
        from sync_app.core.wp_username_picker import pick_wp_username

        message = (
            "این نام‌های کاربری در سایت شما یافت شدند. "
            "کدام را به‌عنوان WP Username انتخاب می‌کنید؟\n\n"
            f"{note}\n\n"
            "مدیران (Administrator) در بالای لیست هستند."
        )
        selected = pick_wp_username(
            self,
            users,
            title="انتخاب WP Username",
            message=message,
            current_username=current_username,
        )
        if not selected:
            return None

        self.wp_username_input.setText(selected)
        self._focus_wp_username_field()
        self._stash_wc_form_to_active_site()
        self._quick_save_wc_sites(broadcast=True)

        if offer_retest:
            retry = QMessageBox.question(
                self,
                "تست مجدد",
                f"نام کاربری «{selected}» در فیلد WP Username قرار گرفت.\n"
                "آیا می‌خواهید دوباره Application Password را تست کنید؟",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if retry == QMessageBox.Yes:
                self.test_wp_app_password()
        else:
            QMessageBox.information(
                self,
                "انتخاب شد",
                f"WP Username روی «{selected}» تنظیم و ذخیره شد.\n"
                "اکنون «تست Application Password» را بزنید یا دوباره ارسال تصاویر را امتحان کنید.",
            )
        return selected

    def test_wp_app_password(self):
        """تست جداگانه Application Password — برای آپلود تصویر دسته‌بندی."""
        from PyQt5.QtWidgets import QApplication

        from sync_app.core.wc_sync_helper import (
            get_wp_media_credentials,
            response_is_waf_block_from_text,
            verify_wp_media_credentials,
            wp_media_waf_user_message,
        )
        from sync_app.core.wc_site_profiles import ensure_wc_sites

        self._stash_wc_form_to_active_site()
        cfg = ensure_wc_sites({**(load_secure_config(None) or {}), **self._wc_config_from_form()})
        user, pwd = get_wp_media_credentials(cfg)
        if not user or not pwd:
            from sync_app.core.wp_auth_error_ui import show_wp_media_auth_error_dialog

            show_wp_media_auth_error_dialog(
                self,
                "WP Username یا Application Password برای سایت فعال خالی است.\n"
                "این فیلدها جدا از Consumer Key/Secret ووکامرس هستند.",
                cfg,
            )
            return

        btn = self.wp_test_button
        btn.setEnabled(False)
        btn.setText("در حال تست...")
        QApplication.processEvents()
        try:
            ok, err = verify_wp_media_credentials(cfg)
        finally:
            btn.setEnabled(True)
            btn.setText("تست Application Password")

        if ok:
            self._quick_save_wc_sites(broadcast=True)
            QMessageBox.information(
                self,
                "موفق",
                "Application Password برای آپلود تصویر تأیید شد.\n"
                "اکنون می‌توانید «ارسال تصاویر» را در تب دسته‌بندی بزنید.",
            )
            return

        is_waf = (
            response_is_waf_block_from_text(err)
            or "ورود rest تأیید شد" in (err or "").lower()
            or "ساخت application password جدید کمکی نمی‌کند" in (err or "").lower()
        )
        if is_waf:
            QMessageBox.warning(
                self,
                "مسدودیت هاست (نه مشکل رمز)",
                err if "ورود REST" in (err or "") else wp_media_waf_user_message(err),
            )
            return

        self._show_wp_app_password_error(err, cfg)

    def test_wc_connection(self):
        if not _has_wcapi():
            QMessageBox.critical(self, "خطا", "ماژول woocommerce نصب نشده است.")
            return

        if self._wc_thread is not None and self._wc_thread.isRunning():
            self._append_monitor("تست قبلی هنوز در حال اجراست...")
            return

        timeout_sec = self.get_optimized_timeout()
        if not self._monitor_open:
            self._animate_monitor_panel(True)

        self._append_monitor("شروع تست اتصال WooCommerce...")
        self._append_monitor("UI در این حالت قفل نمی‌شود و گزارش زنده ثبت می‌شود.")

        self.wc_test_button.setEnabled(False)
        self.wc_test_button.setText("در حال تست اتصال...")
        self.status_label.setText("در حال تست ووکامرس...")
        self.status_label.setStyleSheet("color: #d97706; font-weight: bold;")
        from sync_app.core.connectivity_guard import find_peecha_launcher
        launcher = find_peecha_launcher(self)
        if launcher is not None:
            launcher._paint_wc_badge(None, pending=True, tooltip="در حال تست اتصال ووکامرس...")

        self._wc_thread = QThread(self)
        self._wc_worker = WooTestWorker(self._wc_config_from_form())
        self._wc_worker.moveToThread(self._wc_thread)

        self._wc_thread.started.connect(self._wc_worker.run)
        self._wc_worker.log.connect(self._append_monitor)
        self._wc_worker.success.connect(self._on_wc_test_success)
        self._wc_worker.error.connect(self._on_wc_test_error)
        self._wc_worker.finished.connect(self._wc_thread.quit)
        self._wc_worker.finished.connect(self._wc_worker.deleteLater)
        self._wc_thread.finished.connect(self._wc_thread.deleteLater)
        self._wc_thread.finished.connect(self._on_wc_test_finished)

        self._wc_thread.start()

    def _wc_store_base_from_form(self):
        from sync_app.core.wc_api_helper import normalize_wc_store_url

        return normalize_wc_store_url(self.url_input.text().strip())

    def _wp_admin_url(self, admin_path: str) -> str:
        base = self._wc_store_base_from_form()
        if not base:
            return ""
        path = (admin_path or "").lstrip("/")
        return f"{base}/{path}"

    def _open_external_url(self, url: str) -> bool:
        from sync_app.core.wc_sync_helper import open_external_url

        return open_external_url(self, url)

    def _open_wc_api_keys_page(self):
        self._open_external_url(
            self._wp_admin_url("wp-admin/admin.php?page=wc-settings&tab=advanced&section=keys")
        )

    def _open_wp_app_password_page(self):
        self._open_external_url(
            self._wp_admin_url("wp-admin/profile.php#application-passwords-section")
        )

    def _open_license_api_settings_page(self):
        self._open_external_url(self._wp_admin_url("wp-admin/admin.php?page=peecha-licenses"))

    def _open_profile_switcher(self):
        from sync_app.core.profile_switcher_dialog import ProfileSwitcherDialog

        dialog = ProfileSwitcherDialog(self)
        if dialog.exec_() == QDialog.Accepted and dialog.selected_profile_id:
            from sync_app.core.app_restart import restart_application

            restart_application()

    def _wc_error_category(self, error_message: str) -> str:
        from sync_app.core.connectivity_service import classify_network_error

        text = (error_message or "").lower()
        if classify_network_error(error_message) == "auth":
            return "auth"
        if "application password" in text or "wp app" in text:
            return "wp_app"
        return "generic"

    def _show_wc_connection_error(self, error_message: str):
        category = self._wc_error_category(error_message)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("خطا")
        box.setText("خطا در اتصال به WooCommerce")

        if category == "auth":
            box.setInformativeText(
                f"{error_message}\n\n"
                "راهنما:\n"
                "1. در وردپرس: WooCommerce → Settings → Advanced → REST API\n"
                "2. Add key با دسترسی Read/Write\n"
                "3. Consumer Key و Secret را اینجا paste کنید\n"
                "4. «ذخیره تنظیمات» → «تست اتصال ووکامرس»"
            )
            open_btn = box.addButton("باز کردن صفحه کلید API", QMessageBox.ActionRole)
        elif category == "wp_app":
            box.setInformativeText(
                f"{error_message}\n\n"
                "برای Application Password:\n"
                "Users → Profile → Application Passwords\n"
                "یک رمز یک‌بار مصرف بسازید و در فیلد WP App Password بگذارید."
            )
            open_btn = box.addButton("باز کردن Application Passwords", QMessageBox.ActionRole)
        else:
            box.setInformativeText(str(error_message or ""))
            open_btn = None

        box.addButton("باشه", QMessageBox.AcceptRole)
        box.exec_()

        clicked = box.clickedButton()
        if clicked is open_btn:
            if category == "wp_app":
                self._open_wp_app_password_page()
            else:
                self._open_wc_api_keys_page()

    def _wc_form_values(self):
        return {
            "url": self.url_input.text().strip(),
            "consumer_key": self.ck_input.text().strip(),
            "consumer_secret": self.cs_input.text().strip(),
            "wp_username": self.wp_username_input.text().strip(),
            "wp_app_password": self.wp_app_password_input.text().strip(),
            "currency_is_toman": bool(self.currency_combo.currentData()),
        }

    def _current_wc_form_site(self) -> dict:
        from sync_app.core.wc_site_profiles import find_wc_site, site_display_label, site_from_form

        active = find_wc_site(self._wc_sites, self._active_wc_site_id) or {}
        merged = {**active, **self._wc_form_values()}
        label = (self.wc_site_name_input.text() or "").strip() or site_display_label(merged)
        return site_from_form(
            site_id=self._active_wc_site_id,
            label=label,
            **self._wc_form_values(),
        )

    def _snapshot_wc_site_baseline(self):
        from sync_app.core.wc_site_profiles import find_wc_site

        site = find_wc_site(self._wc_sites, self._active_wc_site_id)
        self._wc_active_site_baseline = copy.deepcopy(site) if site else {}

    def _needs_wc_site_guard(self) -> bool:
        from sync_app.core.wc_site_edit_guard import wc_site_credentials_changed, wc_site_is_saved_profile

        if self._wc_guard_busy or self._wc_site_switching:
            return False
        baseline = self._wc_active_site_baseline or {}
        if not wc_site_is_saved_profile(baseline):
            return False
        return wc_site_credentials_changed(baseline, self._current_wc_form_site())

    def _guard_wc_site_save(self) -> str:
        from sync_app.core.wc_site_edit_guard import (
            ACTION_CANCEL,
            ACTION_NEW_SITE,
            ACTION_PROCEED,
            confirm_wc_site_edit,
        )

        if not self._needs_wc_site_guard():
            return ACTION_PROCEED

        self._wc_guard_busy = True
        try:
            action = confirm_wc_site_edit(
                self,
                baseline_site=self._wc_active_site_baseline,
                form_site=self._current_wc_form_site(),
            )
            if action == ACTION_CANCEL:
                self._revert_wc_form_to_baseline()
            elif action == ACTION_NEW_SITE:
                self._promote_wc_form_to_new_site()
            return action
        finally:
            self._wc_guard_busy = False

    def _revert_wc_form_to_baseline(self):
        if not self._wc_active_site_baseline:
            return
        self._load_wc_site_into_form(self._wc_active_site_baseline, refresh_baseline=False)

    def _promote_wc_form_to_new_site(self):
        from sync_app.core.wc_site_profiles import (
            find_wc_site,
            site_display_label,
            site_from_form,
        )
        from sync_app.core.wc_site_edit_guard import restore_site_in_list

        active_id = (self._active_wc_site_id or "").strip()
        form_site = self._current_wc_form_site()
        baseline = self._wc_active_site_baseline or find_wc_site(self._wc_sites, active_id) or {}

        self._wc_sites = restore_site_in_list(self._wc_sites, active_id, baseline)

        label = (form_site.get("label") or "").strip() or site_display_label(form_site)
        new_site = site_from_form(
            url=form_site.get("url") or "",
            consumer_key=form_site.get("consumer_key") or "",
            consumer_secret=form_site.get("consumer_secret") or "",
            wp_username=form_site.get("wp_username") or "",
            wp_app_password=form_site.get("wp_app_password") or "",
            currency_is_toman=bool(form_site.get("currency_is_toman", True)),
            label=label,
        )
        self._wc_sites.append(new_site)
        self._active_wc_site_id = str(new_site.get("id") or "")
        self._refresh_wc_site_combo(select_id=self._active_wc_site_id)
        self._load_wc_site_into_form(new_site)
        self._apply_active_wc_site_to_runtime_config()
        self._refresh_dirty_state()
        append_system_log(
            "settings",
            f"تنظیمات WooCommerce به‌عنوان سایت جدید «{label}» ذخیره شد — پروفایل قبلی بازگردانده شد.",
        )

    def _stash_wc_form_to_active_site(self):
        active_id = (self._active_wc_site_id or "").strip()
        if not active_id:
            return
        from sync_app.core.wc_site_profiles import find_wc_site, merge_form_into_site, site_display_label

        site = find_wc_site(self._wc_sites, active_id)
        if site is None:
            return
        merged = merge_form_into_site(site, preserve_secrets=True, **self._wc_form_values())
        custom = (self.wc_site_name_input.text() or "").strip()
        merged["label"] = custom or site_display_label(merged)
        for idx, item in enumerate(self._wc_sites):
            if str(item.get("id")) == active_id:
                self._wc_sites[idx] = merged
                break

    def _quick_save_wc_sites(self, *, broadcast: bool = True, skip_guard: bool = False) -> bool:
        """ذخیره فوری پروفایل‌های Woo — بدون انتظار «ذخیره تنظیمات» کامل."""
        from sync_app.core.wc_site_edit_guard import ACTION_CANCEL, ACTION_NEW_SITE, ACTION_PROCEED

        action = ACTION_PROCEED
        if not skip_guard:
            action = self._guard_wc_site_save()
            if action == ACTION_CANCEL:
                return False

        try:
            self._stash_wc_form_to_active_site()
            config = load_secure_config(None) or {}
            config = self._apply_wc_sites_to_config_dict(config)
            save_secure_config(config)
            self.config = dict(config)
            self._snapshot_wc_site_baseline()
            if broadcast:
                self._broadcast_wc_config_reload()
            if action == ACTION_NEW_SITE:
                self.status_label.setText("✅ به‌عنوان سایت جدید ذخیره شد")
                self.status_label.setStyleSheet(
                    "color: #166534; font-weight: 700; font-size: 12px; "
                    "padding: 6px 14px; background: #dcfce7; border-radius: 8px;"
                )
            return True
        except Exception as exc:
            append_system_log("settings", f"ذخیره سایت Woo: {exc}", level="ERROR")
            return False

    def _broadcast_wc_config_reload(self):
        from sync_app.core.connectivity_guard import find_peecha_launcher

        launcher = find_peecha_launcher(self)
        if launcher is not None and hasattr(launcher, "reload_wc_dependent_tabs"):
            launcher.reload_wc_dependent_tabs()
            return
        cfg = load_secure_config(None) or {}
        for ref in (
            self.product_tab_ref,
            self.variation_tab_ref,
            self.category_tab_ref,
            self.dashboard_tab_ref,
            self.properties_tab_ref,
            self.customer_tab_ref,
            self.order_tab_ref,
            self.reconciliation_tab_ref,
        ):
            if ref is not None and hasattr(ref, "config"):
                ref.config = dict(cfg)

    def _on_wc_site_name_changed(self):
        if self._wc_site_switching:
            return
        from sync_app.core.wc_site_profiles import find_wc_site, site_display_label

        site = find_wc_site(self._wc_sites, self._active_wc_site_id)
        if site is None:
            return
        custom = (self.wc_site_name_input.text() or "").strip()
        site["label"] = custom or site_display_label({**site, "url": self.url_input.text().strip()})
        self._refresh_wc_site_combo(select_id=self._active_wc_site_id)
        self._quick_save_wc_sites(broadcast=False)
        self._on_settings_field_changed()

    def _load_wc_site_into_form(self, site, *, refresh_baseline: bool = True):
        self._wc_site_switching = True
        try:
            site = site or {}
            self.url_input.setText(str(site.get("url") or ""))
            self.ck_input.setText(str(site.get("consumer_key") or ""))
            self.cs_input.setText(str(site.get("consumer_secret") or ""))
            self.wp_username_input.setText(str(site.get("wp_username") or ""))
            self.wp_app_password_input.setText(str(site.get("wp_app_password") or ""))
            is_toman = bool(site.get("currency_is_toman", True))
            self.currency_combo.setCurrentIndex(0 if is_toman else 1)
            self.wc_site_name_input.setText(str(site.get("label") or ""))
        finally:
            self._wc_site_switching = False
        if refresh_baseline:
            self._snapshot_wc_site_baseline()

    def _refresh_wc_site_combo(self, *, select_id=None):
        from sync_app.core.wc_site_profiles import site_display_label

        self._wc_site_switching = True
        try:
            self.wc_site_combo.blockSignals(True)
            self.wc_site_combo.clear()
            for site in self._wc_sites:
                sid = str(site.get("id") or "")
                self.wc_site_combo.addItem(site_display_label(site), sid)
            target = (select_id or self._active_wc_site_id or "").strip()
            idx = self.wc_site_combo.findData(target)
            if idx >= 0:
                self.wc_site_combo.setCurrentIndex(idx)
            elif self.wc_site_combo.count():
                self.wc_site_combo.setCurrentIndex(0)
                self._active_wc_site_id = str(self.wc_site_combo.currentData() or "")
            self.wc_delete_site_btn.setEnabled(len(self._wc_sites) > 1)
        finally:
            self.wc_site_combo.blockSignals(False)
            self._wc_site_switching = False

    def _apply_active_wc_site_to_runtime_config(self):
        from sync_app.core.wc_site_profiles import apply_site_to_flat_keys, find_wc_site

        site = find_wc_site(self._wc_sites, self._active_wc_site_id)
        if site:
            apply_site_to_flat_keys(self.config, site)

    def _on_wc_site_combo_changed(self, _index):
        if self._wc_site_switching:
            return
        from sync_app.core.wc_site_profiles import find_wc_site
        from sync_app.core.wc_site_edit_guard import ACTION_CANCEL, ACTION_NEW_SITE, ACTION_PROCEED

        new_id = str(self.wc_site_combo.currentData() or "").strip()
        if not new_id or new_id == self._active_wc_site_id:
            return

        prev_id = (self._active_wc_site_id or "").strip()
        action = ACTION_PROCEED
        if self._needs_wc_site_guard():
            action = self._guard_wc_site_save()
            if action == ACTION_CANCEL:
                self._wc_site_switching = True
                try:
                    self.wc_site_combo.blockSignals(True)
                    idx = self.wc_site_combo.findData(prev_id)
                    if idx >= 0:
                        self.wc_site_combo.setCurrentIndex(idx)
                finally:
                    self.wc_site_combo.blockSignals(False)
                    self._wc_site_switching = False
                return

        if action == ACTION_NEW_SITE:
            self._quick_save_wc_sites(broadcast=True, skip_guard=True)
            self._on_settings_field_changed()
            return

        self._stash_wc_form_to_active_site()
        self._active_wc_site_id = new_id
        site = find_wc_site(self._wc_sites, new_id)
        self._load_wc_site_into_form(site)
        self._apply_active_wc_site_to_runtime_config()
        self._quick_save_wc_sites(broadcast=True, skip_guard=True)
        self._on_settings_field_changed()

    def _on_add_wc_site(self):
        from sync_app.core.wc_site_profiles import create_empty_site, find_wc_site

        self._stash_wc_form_to_active_site()
        site = create_empty_site(label=f"سایت {len(self._wc_sites) + 1}")
        self._wc_sites.append(site)
        self._active_wc_site_id = str(site.get("id") or "")
        self._refresh_wc_site_combo(select_id=self._active_wc_site_id)
        self._load_wc_site_into_form(site)
        self._apply_active_wc_site_to_runtime_config()
        self._quick_save_wc_sites(broadcast=True)
        self.url_input.setFocus()
        self._on_settings_field_changed()

    def _on_delete_wc_site(self):
        from sync_app.core.wc_site_profiles import find_wc_site, site_display_label

        if len(self._wc_sites) <= 1:
            QMessageBox.information(
                self,
                "حذف سایت",
                "حداقل یک سایت باید باقی بماند.\nبرای قطع اتصال، فیلدهای آن را خالی کنید.",
            )
            return
        active_id = (self._active_wc_site_id or "").strip()
        label = site_display_label(find_wc_site(self._wc_sites, active_id))
        answer = QMessageBox.question(
            self,
            "حذف سایت",
            f"سایت «{label}» حذف شود؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._wc_sites = [s for s in self._wc_sites if str(s.get("id")) != active_id]
        self._active_wc_site_id = str(self._wc_sites[0].get("id") or "")
        self._refresh_wc_site_combo(select_id=self._active_wc_site_id)
        self._load_wc_site_into_form(find_wc_site(self._wc_sites, self._active_wc_site_id))
        self._apply_active_wc_site_to_runtime_config()
        self._quick_save_wc_sites(broadcast=True)
        self._on_settings_field_changed()

    def _apply_wc_sites_to_config_dict(self, config):
        from sync_app.core.wc_site_profiles import (
            find_wc_site,
            site_display_label,
            site_from_form,
            sync_sites_to_config,
        )

        self._stash_wc_form_to_active_site()
        active = find_wc_site(self._wc_sites, self._active_wc_site_id) or {}
        form_site = site_from_form(
            site_id=self._active_wc_site_id,
            label=(self.wc_site_name_input.text() or "").strip() or site_display_label(active),
            **self._wc_form_values(),
        )
        updated = sync_sites_to_config(
            config,
            self._wc_sites,
            self._active_wc_site_id,
            form_site=form_site,
        )
        self._wc_sites = list(updated.get("WC_SITES") or self._wc_sites)
        self._active_wc_site_id = str(updated.get("ACTIVE_WC_SITE_ID") or self._active_wc_site_id)
        return updated

    # ------------------------------------------------------------------
    # چند سایتِ پرستاشاپ — هم‌ساختار با متدهای چندسایتیِ ووکامرسِ بالا
    # ------------------------------------------------------------------

    def _ps_form_values(self):
        cfg = self.config or {}
        return {
            "url": self.ps_url_input.text().strip(),
            "api_key": self.ps_api_key_input.text().strip(),
            "verify_ssl": bool(cfg.get("PS_VERIFY_SSL", False)),
            "lang_id": int(cfg.get("PS_LANG_ID") or 1),
            "root_category_id": int(cfg.get("PS_ROOT_CATEGORY_ID") or 2),
            "currency_is_toman": bool(self.currency_combo.currentData()),
        }

    def _current_ps_form_site(self) -> dict:
        from sync_app.core.ps_site_profiles import find_ps_site, site_display_label, site_from_form

        active = find_ps_site(self._ps_sites, self._active_ps_site_id) or {}
        merged = {**active, **self._ps_form_values()}
        label = (self.ps_site_name_input.text() or "").strip() or site_display_label(merged)
        return site_from_form(
            site_id=self._active_ps_site_id,
            label=label,
            **self._ps_form_values(),
        )

    def _snapshot_ps_site_baseline(self):
        from sync_app.core.ps_site_profiles import find_ps_site

        site = find_ps_site(self._ps_sites, self._active_ps_site_id)
        self._ps_active_site_baseline = copy.deepcopy(site) if site else {}

    def _needs_ps_site_guard(self) -> bool:
        from sync_app.core.ps_site_edit_guard import ps_site_credentials_changed, ps_site_is_saved_profile

        if self._ps_guard_busy or self._ps_site_switching:
            return False
        baseline = self._ps_active_site_baseline or {}
        if not ps_site_is_saved_profile(baseline):
            return False
        return ps_site_credentials_changed(baseline, self._current_ps_form_site())

    def _guard_ps_site_save(self) -> str:
        from sync_app.core.ps_site_edit_guard import (
            ACTION_CANCEL,
            ACTION_NEW_SITE,
            ACTION_PROCEED,
            confirm_ps_site_edit,
        )

        if not self._needs_ps_site_guard():
            return ACTION_PROCEED

        self._ps_guard_busy = True
        try:
            action = confirm_ps_site_edit(
                self,
                baseline_site=self._ps_active_site_baseline,
                form_site=self._current_ps_form_site(),
            )
            if action == ACTION_CANCEL:
                self._revert_ps_form_to_baseline()
            elif action == ACTION_NEW_SITE:
                self._promote_ps_form_to_new_site()
            return action
        finally:
            self._ps_guard_busy = False

    def _revert_ps_form_to_baseline(self):
        if not self._ps_active_site_baseline:
            return
        self._load_ps_site_into_form(self._ps_active_site_baseline, refresh_baseline=False)

    def _promote_ps_form_to_new_site(self):
        from sync_app.core.ps_site_profiles import (
            find_ps_site,
            site_display_label,
            site_from_form,
        )
        from sync_app.core.ps_site_edit_guard import restore_site_in_list

        active_id = (self._active_ps_site_id or "").strip()
        form_site = self._current_ps_form_site()
        baseline = self._ps_active_site_baseline or find_ps_site(self._ps_sites, active_id) or {}

        self._ps_sites = restore_site_in_list(self._ps_sites, active_id, baseline)

        label = (form_site.get("label") or "").strip() or site_display_label(form_site)
        new_site = site_from_form(
            url=form_site.get("url") or "",
            api_key=form_site.get("api_key") or "",
            verify_ssl=bool(form_site.get("verify_ssl", False)),
            lang_id=int(form_site.get("lang_id") or 1),
            root_category_id=int(form_site.get("root_category_id") or 2),
            currency_is_toman=bool(form_site.get("currency_is_toman", True)),
            label=label,
        )
        self._ps_sites.append(new_site)
        self._active_ps_site_id = str(new_site.get("id") or "")
        self._refresh_ps_site_combo(select_id=self._active_ps_site_id)
        self._load_ps_site_into_form(new_site)
        self._apply_active_ps_site_to_runtime_config()
        self._refresh_dirty_state()
        append_system_log(
            "settings",
            f"تنظیمات PrestaShop به‌عنوان سایت جدید «{label}» ذخیره شد — پروفایل قبلی بازگردانده شد.",
        )

    def _stash_ps_form_to_active_site(self):
        active_id = (self._active_ps_site_id or "").strip()
        if not active_id:
            return
        from sync_app.core.ps_site_profiles import find_ps_site, merge_form_into_site, site_display_label

        site = find_ps_site(self._ps_sites, active_id)
        if site is None:
            return
        merged = merge_form_into_site(site, preserve_secrets=True, **self._ps_form_values())
        custom = (self.ps_site_name_input.text() or "").strip()
        merged["label"] = custom or site_display_label(merged)
        for idx, item in enumerate(self._ps_sites):
            if str(item.get("id")) == active_id:
                self._ps_sites[idx] = merged
                break

    def _quick_save_ps_sites(self, *, broadcast: bool = True, skip_guard: bool = False) -> bool:
        """ذخیره فوری پروفایل‌های PrestaShop — بدون انتظار «ذخیره تنظیمات» کامل."""
        from sync_app.core.ps_site_edit_guard import ACTION_CANCEL, ACTION_NEW_SITE, ACTION_PROCEED

        action = ACTION_PROCEED
        if not skip_guard:
            action = self._guard_ps_site_save()
            if action == ACTION_CANCEL:
                return False

        try:
            self._stash_ps_form_to_active_site()
            config = load_secure_config(None) or {}
            config = self._apply_ps_sites_to_config_dict(config)
            save_secure_config(config)
            self.config = dict(config)
            self._snapshot_ps_site_baseline()
            if broadcast:
                self._broadcast_wc_config_reload()
            if action == ACTION_NEW_SITE:
                self.status_label.setText("✅ به‌عنوان سایت جدید ذخیره شد")
                self.status_label.setStyleSheet(
                    "color: #166534; font-weight: 700; font-size: 12px; "
                    "padding: 6px 14px; background: #dcfce7; border-radius: 8px;"
                )
            return True
        except Exception as exc:
            append_system_log("settings", f"ذخیره سایت PrestaShop: {exc}", level="ERROR")
            return False

    def _on_ps_site_name_changed(self):
        if self._ps_site_switching:
            return
        from sync_app.core.ps_site_profiles import find_ps_site, site_display_label

        site = find_ps_site(self._ps_sites, self._active_ps_site_id)
        if site is None:
            return
        custom = (self.ps_site_name_input.text() or "").strip()
        site["label"] = custom or site_display_label({**site, "url": self.ps_url_input.text().strip()})
        self._refresh_ps_site_combo(select_id=self._active_ps_site_id)
        self._quick_save_ps_sites(broadcast=False)
        self._on_settings_field_changed()

    def _load_ps_site_into_form(self, site, *, refresh_baseline: bool = True):
        self._ps_site_switching = True
        try:
            site = site or {}
            self.ps_url_input.setText(str(site.get("url") or ""))
            self.ps_api_key_input.setText(str(site.get("api_key") or ""))
            self.ps_site_name_input.setText(str(site.get("label") or ""))
        finally:
            self._ps_site_switching = False
        if refresh_baseline:
            self._snapshot_ps_site_baseline()

    def _refresh_ps_site_combo(self, *, select_id=None):
        from sync_app.core.ps_site_profiles import site_display_label

        self._ps_site_switching = True
        try:
            self.ps_site_combo.blockSignals(True)
            self.ps_site_combo.clear()
            for site in self._ps_sites:
                sid = str(site.get("id") or "")
                self.ps_site_combo.addItem(site_display_label(site), sid)
            target = (select_id or self._active_ps_site_id or "").strip()
            idx = self.ps_site_combo.findData(target)
            if idx >= 0:
                self.ps_site_combo.setCurrentIndex(idx)
            elif self.ps_site_combo.count():
                self.ps_site_combo.setCurrentIndex(0)
                self._active_ps_site_id = str(self.ps_site_combo.currentData() or "")
            self.ps_delete_site_btn.setEnabled(len(self._ps_sites) > 1)
        finally:
            self.ps_site_combo.blockSignals(False)
            self._ps_site_switching = False

    def _apply_active_ps_site_to_runtime_config(self):
        from sync_app.core.ps_site_profiles import apply_site_to_flat_keys, find_ps_site

        site = find_ps_site(self._ps_sites, self._active_ps_site_id)
        if site:
            apply_site_to_flat_keys(self.config, site)

    def _on_ps_site_combo_changed(self, _index):
        if self._ps_site_switching:
            return
        from sync_app.core.ps_site_profiles import find_ps_site
        from sync_app.core.ps_site_edit_guard import ACTION_CANCEL, ACTION_NEW_SITE, ACTION_PROCEED

        new_id = str(self.ps_site_combo.currentData() or "").strip()
        if not new_id or new_id == self._active_ps_site_id:
            return

        prev_id = (self._active_ps_site_id or "").strip()
        action = ACTION_PROCEED
        if self._needs_ps_site_guard():
            action = self._guard_ps_site_save()
            if action == ACTION_CANCEL:
                self._ps_site_switching = True
                try:
                    self.ps_site_combo.blockSignals(True)
                    idx = self.ps_site_combo.findData(prev_id)
                    if idx >= 0:
                        self.ps_site_combo.setCurrentIndex(idx)
                finally:
                    self.ps_site_combo.blockSignals(False)
                    self._ps_site_switching = False
                return

        if action == ACTION_NEW_SITE:
            self._quick_save_ps_sites(broadcast=True, skip_guard=True)
            self._on_settings_field_changed()
            return

        self._stash_ps_form_to_active_site()
        self._active_ps_site_id = new_id
        site = find_ps_site(self._ps_sites, new_id)
        self._load_ps_site_into_form(site)
        self._apply_active_ps_site_to_runtime_config()
        self._quick_save_ps_sites(broadcast=True, skip_guard=True)
        self._on_settings_field_changed()

    def _on_add_ps_site(self):
        from sync_app.core.ps_site_profiles import create_empty_site, find_ps_site

        self._stash_ps_form_to_active_site()
        site = create_empty_site(label=f"سایت {len(self._ps_sites) + 1}")
        self._ps_sites.append(site)
        self._active_ps_site_id = str(site.get("id") or "")
        self._refresh_ps_site_combo(select_id=self._active_ps_site_id)
        self._load_ps_site_into_form(site)
        self._apply_active_ps_site_to_runtime_config()
        self._quick_save_ps_sites(broadcast=True)
        self.ps_url_input.setFocus()
        self._on_settings_field_changed()

    def _on_delete_ps_site(self):
        from sync_app.core.ps_site_profiles import find_ps_site, site_display_label

        if len(self._ps_sites) <= 1:
            QMessageBox.information(
                self,
                "حذف سایت",
                "حداقل یک سایت باید باقی بماند.\nبرای قطع اتصال، فیلدهای آن را خالی کنید.",
            )
            return
        active_id = (self._active_ps_site_id or "").strip()
        label = site_display_label(find_ps_site(self._ps_sites, active_id))
        answer = QMessageBox.question(
            self,
            "حذف سایت",
            f"سایت «{label}» حذف شود؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._ps_sites = [s for s in self._ps_sites if str(s.get("id")) != active_id]
        self._active_ps_site_id = str(self._ps_sites[0].get("id") or "")
        self._refresh_ps_site_combo(select_id=self._active_ps_site_id)
        self._load_ps_site_into_form(find_ps_site(self._ps_sites, self._active_ps_site_id))
        self._apply_active_ps_site_to_runtime_config()
        self._quick_save_ps_sites(broadcast=True)
        self._on_settings_field_changed()

    def _apply_ps_sites_to_config_dict(self, config):
        from sync_app.core.ps_site_profiles import (
            find_ps_site,
            site_display_label,
            site_from_form,
            sync_sites_to_config,
        )

        self._stash_ps_form_to_active_site()
        active = find_ps_site(self._ps_sites, self._active_ps_site_id) or {}
        form_site = site_from_form(
            site_id=self._active_ps_site_id,
            label=(self.ps_site_name_input.text() or "").strip() or site_display_label(active),
            **self._ps_form_values(),
        )
        updated = sync_sites_to_config(
            config,
            self._ps_sites,
            self._active_ps_site_id,
            form_site=form_site,
        )
        self._ps_sites = list(updated.get("PS_SITES") or self._ps_sites)
        self._active_ps_site_id = str(updated.get("ACTIVE_PS_SITE_ID") or self._active_ps_site_id)
        return updated

    # ------------------------------------------------------------------
    # پیش‌تنظیم‌های نام‌دارِ کلِ تنظیمات
    # ------------------------------------------------------------------

    def _refresh_preset_combo(self):
        from sync_app.core.config_presets import ACTIVE_CONFIG_PRESET_ID_KEY, list_presets

        presets = list_presets(self.config)
        self._config_presets_switching = True
        try:
            self.preset_combo.blockSignals(True)
            self.preset_combo.clear()
            self.preset_combo.addItem("— بدون پیش‌تنظیم (تنظیمات فعلی) —", "")
            for p in presets:
                self.preset_combo.addItem(str(p.get("title") or "بدون عنوان"), str(p.get("id") or ""))
            active_id = str((self.config or {}).get(ACTIVE_CONFIG_PRESET_ID_KEY) or "")
            idx = self.preset_combo.findData(active_id) if active_id else 0
            self.preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.preset_delete_btn.setEnabled(bool(presets) and self.preset_combo.currentIndex() > 0)
        finally:
            self.preset_combo.blockSignals(False)
            self._config_presets_switching = False

    def _on_preset_combo_changed(self, _index):
        if self._config_presets_switching:
            return
        from sync_app.core.config_presets import find_preset, list_presets

        new_id = str(self.preset_combo.currentData() or "")
        self.preset_delete_btn.setEnabled(bool(new_id))
        if not new_id:
            return

        presets = list_presets(self.config)
        preset = find_preset(presets, new_id)
        if preset is None:
            return

        answer = QMessageBox.question(
            self,
            "تعویض پیش‌تنظیم",
            f"همه‌ی فیلدهای این تب با تنظیماتِ پیش‌تنظیمِ «{preset.get('title')}» جایگزین می‌شود — "
            "تغییرات ذخیره‌نشده‌ی فعلی از دست می‌روند. ادامه می‌دهید؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self._refresh_preset_combo()
            return

        QTimer.singleShot(0, lambda: self._apply_config_preset(preset))

    def _apply_config_preset(self, preset):
        from sync_app.core.config_presets import ACTIVE_CONFIG_PRESET_ID_KEY, apply_preset

        new_cfg = apply_preset(self.config, preset)
        new_cfg[ACTIVE_CONFIG_PRESET_ID_KEY] = str(preset.get("id") or "")
        save_secure_config(new_cfg)
        self.config = dict(new_cfg)
        self._ui_built = False
        # _update_responsive_layout (که init_ui صداش می‌زنه) اگه compact/wide با
        # دفعه‌ی قبل فرق نکنه، زودتر برمی‌گرده و main_grid رو پر نمی‌کنه — چون
        # این تب همین الان هم دیده می‌شه (نه در حالِ نمایشِ اولیه)، showEvent هم
        # دوباره شلیک نمی‌شه تا این حالتِ خالی رو خودش تشخیص بده. با ریست‌کردنِ
        # این پرچم قبل از بازسازی، مطمئن می‌شیم گرید همیشه واقعاً پر بشه.
        self._settings_compact = None
        self._deferred_build_ui()

        from sync_app.core.connectivity_guard import find_peecha_launcher

        launcher = find_peecha_launcher(self)
        if launcher is not None:
            if hasattr(launcher, "reload_wc_dependent_tabs"):
                launcher.reload_wc_dependent_tabs()
            if hasattr(launcher, "refresh_sql_connectivity"):
                launcher.refresh_sql_connectivity(show_pending=False)

    def _on_save_config_preset(self):
        from PyQt5.QtWidgets import QInputDialog

        from sync_app.core.config_presets import (
            ACTIVE_CONFIG_PRESET_ID_KEY,
            find_preset,
            list_presets,
            save_preset,
        )

        presets = list_presets(self.config)
        current_id = str(self.preset_combo.currentData() or "")
        current_preset = find_preset(presets, current_id) if current_id else None

        title, ok = QInputDialog.getText(
            self,
            "ذخیره پیش‌تنظیم",
            "یک عنوان برای این مجموعه‌ی تنظیمات وارد کنید:",
            text=str((current_preset or {}).get("title") or ""),
        )
        if not ok:
            return
        title = (title or "").strip()
        if not title:
            QMessageBox.warning(self, "پیش‌تنظیم", "عنوان نمی‌تواند خالی باشد.")
            return

        # اگه عنوانِ واردشده همونِ عنوانِ پیش‌تنظیمِ فعلاً انتخاب‌شده باشه، یعنی
        # کاربر می‌خواد همونو آپدیت کنه. وگرنه (چه پیش‌تنظیمی انتخاب نشده باشه، چه
        # عنوان فرق کنه) پیش‌فرض ساختنِ پیش‌تنظیمِ جدیده — مگر اینکه عنوان دقیقاً
        # مالِ یه پیش‌تنظیمِ دیگه باشه که اون موقع با تاییدِ صریح بازنویسی می‌شه.
        by_title = next((p for p in presets if str(p.get("title") or "").strip() == title), None)
        if current_preset and str(current_preset.get("title") or "").strip() == title:
            target_id = current_id
        elif by_title:
            answer = QMessageBox.question(
                self,
                "بازنویسی پیش‌تنظیم",
                f"پیش‌تنظیمی با عنوان «{title}» از قبل وجود دارد. بازنویسی شود؟",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            target_id = str(by_title.get("id"))
        else:
            target_id = ""

        self.save_config()  # فیلدهای فعلیِ فرم را ذخیره و self.config را به‌روز می‌کند

        updated_cfg = save_preset(self.config, title, preset_id=target_id)
        saved = next((p for p in list_presets(updated_cfg) if str(p.get("title")) == title), None)
        updated_cfg[ACTIVE_CONFIG_PRESET_ID_KEY] = str(saved.get("id")) if saved else ""
        save_secure_config(updated_cfg)
        self.config = dict(updated_cfg)
        self._refresh_preset_combo()
        QMessageBox.information(self, "پیش‌تنظیم", f"تنظیمات با عنوان «{title}» ذخیره شد.")

    def _on_delete_config_preset(self):
        from sync_app.core.config_presets import ACTIVE_CONFIG_PRESET_ID_KEY, delete_preset, list_presets

        current_id = str(self.preset_combo.currentData() or "")
        if not current_id:
            return
        presets = list_presets(self.config)
        preset = next((p for p in presets if str(p.get("id")) == current_id), None)
        title = str((preset or {}).get("title") or "این پیش‌تنظیم")
        answer = QMessageBox.question(
            self,
            "حذف پیش‌تنظیم",
            f"پیش‌تنظیمِ «{title}» حذف شود؟ (تنظیمات فعلیِ برنامه تغییری نمی‌کند، فقط از لیست حذف می‌شود.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        updated_cfg = delete_preset(self.config, current_id)
        if str(updated_cfg.get(ACTIVE_CONFIG_PRESET_ID_KEY) or "") == current_id:
            updated_cfg[ACTIVE_CONFIG_PRESET_ID_KEY] = ""
        save_secure_config(updated_cfg)
        self.config = dict(updated_cfg)
        self._refresh_preset_combo()

    def _wc_config_from_form(self):
        timeout_sec = self.get_optimized_timeout()
        return {
            **(self.config or {}),
            "WC_URL": self.url_input.text().strip(),
            "WC_CONSUMER_KEY": self.ck_input.text().strip(),
            "WC_CONSUMER_SECRET": self.cs_input.text().strip(),
            "WP_USERNAME": self.wp_username_input.text().strip(),
            "WP_APP_PASSWORD": self.wp_app_password_input.text().strip(),
            "WC_TIMEOUT": timeout_sec,
            "WC_READ_TIMEOUT": timeout_sec,
            "WC_VERIFY_SSL": bool((self.config or {}).get("WC_VERIFY_SSL", False)),
        }

    def _set_form_field_visible(self, field, visible: bool):
        """یک ردیف QFormLayout (widget یا layout) رو همراه لیبلش نشون/مخفی می‌کنه."""
        layout = getattr(self, "wc_form_layout", None)
        label = layout.labelForField(field) if layout is not None else None
        if label is not None:
            label.setVisible(visible)
        if isinstance(field, QLayout):
            for i in range(field.count()):
                w = field.itemAt(i).widget()
                if w is not None:
                    w.setVisible(visible)
        elif field is not None:
            field.setVisible(visible)

    def _apply_platform_field_visibility(self):
        """با انتخاب پلتفرم، فیلدهای مخصوص ووکامرس/پرستاشاپ رو جدا نشون می‌ده."""
        platform = self.store_platform_combo.currentData() or "woocommerce"
        is_ps = platform == "prestashop"
        for field in getattr(self, "_wc_only_fields", []):
            self._set_form_field_visible(field, not is_ps)
        for field in getattr(self, "_ps_only_fields", []):
            self._set_form_field_visible(field, is_ps)

    def _ps_config_from_form(self):
        return {
            **(self.config or {}),
            "PS_URL": self.ps_url_input.text().strip(),
            "PS_API_KEY": self.ps_api_key_input.text().strip(),
            "PS_VERIFY_SSL": bool((self.config or {}).get("PS_VERIFY_SSL", False)),
            "PS_LANG_ID": (self.config or {}).get("PS_LANG_ID", 1),
            "PS_ROOT_CATEGORY_ID": (self.config or {}).get("PS_ROOT_CATEGORY_ID", 2),
        }

    def _test_bale_connection(self):
        from sync_app.core.threading_helper import run_in_thread
        from sync_app.core.bale_poster import test_connection as bale_test_connection

        token = self.bale_bot_token_input.text().strip()
        if not token:
            QMessageBox.warning(self, "بله", "ابتدا توکنِ بات را وارد کنید.")
            return

        self.bale_test_button.setEnabled(False)
        self.bale_test_button.setText("در حال تست اتصال...")

        def on_complete(result):
            ok, msg = result
            self.bale_test_button.setEnabled(True)
            self.bale_test_button.setText("تست اتصال بله")
            if ok:
                QMessageBox.information(self, "بله", msg)
            else:
                QMessageBox.critical(self, "بله", f"اتصال ناموفق بود:\n{msg}")

        def on_error(err):
            self.bale_test_button.setEnabled(True)
            self.bale_test_button.setText("تست اتصال بله")
            QMessageBox.critical(self, "بله", f"خطا: {err}")

        run_in_thread(bale_test_connection, token, on_complete=on_complete, on_error=on_error)

    def _test_telegram_connection(self):
        from sync_app.core.threading_helper import run_in_thread
        from sync_app.core.telegram_poster import test_connection as telegram_test_connection

        token = self.telegram_bot_token_input.text().strip()
        proxy_url = self.telegram_proxy_url_input.text().strip()
        if not token:
            QMessageBox.warning(self, "تلگرام", "ابتدا توکنِ بات را وارد کنید.")
            return

        self.telegram_test_button.setEnabled(False)
        self.telegram_test_button.setText("در حال تست اتصال...")

        def on_complete(result):
            ok, msg = result
            self.telegram_test_button.setEnabled(True)
            self.telegram_test_button.setText("تست اتصال تلگرام")
            if ok:
                QMessageBox.information(self, "تلگرام", msg)
            else:
                QMessageBox.critical(self, "تلگرام", f"اتصال ناموفق بود:\n{msg}")

        def on_error(err):
            self.telegram_test_button.setEnabled(True)
            self.telegram_test_button.setText("تست اتصال تلگرام")
            QMessageBox.critical(self, "تلگرام", f"خطا: {err}")

        run_in_thread(
            telegram_test_connection, token, proxy_url=proxy_url, on_complete=on_complete, on_error=on_error
        )

    def test_ps_connection(self):
        if self._ps_thread is not None and self._ps_thread.isRunning():
            self._append_monitor("تست قبلی هنوز در حال اجراست...")
            return

        if not self._monitor_open:
            self._animate_monitor_panel(True)
        self._append_monitor("شروع تست اتصال پرستاشاپ...")

        self.ps_test_button.setEnabled(False)
        self.ps_test_button.setText("در حال تست اتصال...")
        self.status_label.setText("در حال تست پرستاشاپ...")
        self.status_label.setStyleSheet("color: #d97706; font-weight: bold;")

        self._ps_thread = QThread(self)
        self._ps_worker = PrestaShopTestWorker(self._ps_config_from_form())
        self._ps_worker.moveToThread(self._ps_thread)

        self._ps_thread.started.connect(self._ps_worker.run)
        self._ps_worker.log.connect(self._append_monitor)
        self._ps_worker.success.connect(self._on_ps_test_success)
        self._ps_worker.error.connect(self._on_ps_test_error)
        self._ps_worker.finished.connect(self._ps_thread.quit)
        self._ps_worker.finished.connect(self._ps_worker.deleteLater)
        self._ps_thread.finished.connect(self._ps_thread.deleteLater)
        self._ps_thread.finished.connect(self._on_ps_test_finished)

        self._ps_thread.start()

    def _on_ps_test_success(self, message):
        self._append_monitor(f"✅ {message}")
        self.status_label.setText("پرستاشاپ متصل است ✅")
        self.status_label.setStyleSheet("color: #16a34a; font-weight: bold;")
        QMessageBox.information(self, "موفق", message)

    def _on_ps_test_error(self, error_message):
        self._append_monitor(f"❌ {error_message}")
        self.status_label.setText("خطا در اتصال پرستاشاپ ❌")
        self.status_label.setStyleSheet("color: #dc2626; font-weight: bold;")
        QMessageBox.critical(self, "خطا در اتصال به پرستاشاپ", str(error_message or ""))

    def _on_ps_test_finished(self):
        self.ps_test_button.setEnabled(True)
        self.ps_test_button.setText("تست اتصال پرستاشاپ")
        self._ps_thread = None
        self._ps_worker = None
        self._append_monitor("پایان تست اتصال پرستاشاپ.")

    def _sync_header_connectivity(self, wc_ok, wc_msg):
        from sync_app.core.connectivity_guard import find_peecha_launcher
        from sync_app.core.connectivity_service import load_connectivity_cache, save_connectivity_cache

        launcher = find_peecha_launcher(self)
        cache = load_connectivity_cache(self.config)
        sql_ok = bool(getattr(launcher, "_last_sql_ok", cache.get("sql_ok", True))) if launcher else bool(cache.get("sql_ok", True))
        sql_msg = str(getattr(launcher, "_sql_tooltip", "") or cache.get("sql_msg") or "") if launcher else str(cache.get("sql_msg") or "")
        save_connectivity_cache(
            sql_ok,
            sql_msg,
            bool(wc_ok),
            str(wc_msg or ""),
            sql_ms=float(cache.get("sql_ms") or 0),
            wc_ms=float(cache.get("wc_ms") or 0),
        )
        if launcher is not None:
            launcher.apply_connectivity_probe(sql_ok, sql_msg, bool(wc_ok), str(wc_msg or ""))
            QTimer.singleShot(350, lambda: launcher.refresh_wc_connectivity(show_pending=False))

    def run_wc_store_setup(self):
        if not _has_wcapi():
            QMessageBox.critical(self, "خطا", "ماژول woocommerce نصب نشده است.")
            return
        if self._wc_setup_thread is not None and self._wc_setup_thread.isRunning():
            self._append_monitor("راه‌اندازی قبلی هنوز در جریان است...")
            return

        if not self._monitor_open:
            self._animate_monitor_panel(True)

        cfg = self._wc_config_from_form()
        self._append_monitor("▶️ راه‌اندازی استاندارد Cart / Checkout / My Account...")
        self.wc_setup_button.setEnabled(False)
        self.wc_setup_button.setText("در حال راه‌اندازی...")

        self._wc_setup_thread = QThread(self)
        self._wc_setup_worker = WooStoreSetupWorker(cfg)
        self._wc_setup_worker.moveToThread(self._wc_setup_thread)
        self._wc_setup_thread.started.connect(self._wc_setup_worker.run)
        self._wc_setup_worker.log.connect(self._append_monitor)
        self._wc_setup_worker.success.connect(self._on_wc_setup_success)
        self._wc_setup_worker.error.connect(self._on_wc_setup_error)
        self._wc_setup_worker.finished.connect(self._wc_setup_thread.quit)
        self._wc_setup_worker.finished.connect(self._wc_setup_worker.deleteLater)
        self._wc_setup_thread.finished.connect(self._wc_setup_thread.deleteLater)
        self._wc_setup_thread.finished.connect(self._on_wc_setup_finished)
        self._wc_setup_thread.start()

    def _on_wc_setup_success(self, message):
        self._append_monitor(message)
        self.status_label.setText("✅ صفحات فروشگاه راه‌اندازی شد.")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        QMessageBox.information(self, "موفق", message)

    def _on_wc_setup_error(self, message):
        self._append_monitor(f"خطا: {message}")
        self.status_label.setText("❌ خطا در راه‌اندازی فروشگاه")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        QMessageBox.critical(self, "خطا", message)

    def _on_wc_setup_finished(self):
        self.wc_setup_button.setEnabled(True)
        self.wc_setup_button.setText("راه‌اندازی Cart/Checkout")
        self._wc_setup_thread = None
        self._wc_setup_worker = None
        self._append_monitor("پایان راه‌اندازی صفحات WooCommerce.")

    def _on_wc_test_success(self, message):
        self._append_monitor(message)
        self.set_button_status(self.wc_test_button, True)
        self.status_label.setText("✅ اتصال ووکامرس برقرار شد.")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")
        self._sync_header_connectivity(True, message)
        QMessageBox.information(self, "موفقیت", "اتصال به WooCommerce برقرار شد.")

    def _on_wc_test_error(self, error_message):
        self._append_monitor(f"خطا: {error_message}")
        self.set_button_status(self.wc_test_button, False)
        self.status_label.setText("❌ خطا در اتصال ووکامرس")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self._sync_header_connectivity(False, error_message)
        self._show_wc_connection_error(error_message)

    def _on_wc_test_finished(self):
        self.wc_test_button.setEnabled(True)
        if self.wc_test_button.text() != "❌ قطع اتصال" and self.wc_test_button.text() != "✅ اتصال موفق":
            self.wc_test_button.setText("تست اتصال ووکامرس")
        self._wc_thread = None
        self._wc_worker = None
        self._append_monitor("پایان تست اتصال WooCommerce.")

    def _on_default_customer_mode_changed(self):
        """نمایش/مخفی کردن فیلد کد مشتری بر اساس حالت انتخابی"""
        is_fixed = self.default_customer_mode_combo.currentData() == "fixed"
        self.default_customer_code_input.setVisible(is_fixed)
        self.default_customer_code_label.setVisible(is_fixed)

    def _project_root_dir(self):
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    def _default_mdf_browse_dir(self):
        saved = (self.sql_mdf_path_input.text() or (self.config or {}).get("SQL_MDF_PATH") or "").strip()
        if saved and os.path.isfile(saved):
            return os.path.dirname(saved)
        if saved and os.path.isdir(saved):
            return saved

        for candidate in [
            os.path.join(self._project_root_dir(), "DATA3", "DB_14050302"),
            os.path.join(self._project_root_dir(), "DATA3"),
            os.path.join(self._project_root_dir(), "..", "DB10"),
            self._project_root_dir(),
        ]:
            if os.path.isdir(candidate):
                return candidate
        return self._project_root_dir()

    def _master_runtime_sql_config(self):
        auth_mode = self._last_success_sql_auth_mode
        if auth_mode not in ["sql", "windows"]:
            auth_mode = self._detect_auth_modes()[0]
        return {
            "SQL_DRIVER": self.driver_input.currentText(),
            "SQL_SERVER": self.server_input.text().strip(),
            "SQL_DATABASE": "master",
            "SQL_USERNAME": self.username_input.text().strip(),
            "SQL_PASSWORD": self.password_input.text() or (self.config or {}).get("SQL_PASSWORD") or "",
            "SQL_AUTH_MODE": auth_mode,
        }

    def _apply_mdf_sync_result(self, mdf_path, ldf_path=None, *, silent=False, db_name=""):
        if not mdf_path:
            return False
        current_mdf = (self.sql_mdf_path_input.text() or "").strip()
        changed = (
            not current_mdf
            or os.path.normcase(os.path.abspath(current_mdf))
            != os.path.normcase(os.path.abspath(mdf_path))
        )
        if not changed:
            return False
        self.sql_mdf_path_input.setText(mdf_path)
        self.config = dict(self.config or {})
        self.config["SQL_MDF_PATH"] = mdf_path
        if ldf_path:
            self.config["SQL_LDF_PATH"] = ldf_path
        if not silent:
            label = db_name or self.database_input.text().strip() or "دیتابیس"
            self._append_monitor(f"مسیر MDF با {label} همگام شد.")
        return True

    def _apply_database_from_mdf_path(self, mdf_path, *, silent=False, background=False):
        """پس از انتخاب فایل MDF — نام دیتابیس از SQL/مسیر استخراج می‌شود."""
        if background:
            cfg = self._master_runtime_sql_config()

            def _worker():
                from sync_app.core.sql_attach_helper import resolve_database_for_mdf_path

                return resolve_database_for_mdf_path(mdf_path, config=cfg, timeout=4)

            def _done(resolved):
                if not resolved:
                    return
                self.database_input.setText(resolved)
                idx = self.db_picker_combo.findText(resolved)
                if idx >= 0:
                    self.db_picker_combo.blockSignals(True)
                    self.db_picker_combo.setCurrentIndex(idx)
                    self.db_picker_combo.blockSignals(False)
                if not silent:
                    self._append_monitor(f"نام دیتابیس از فایل MDF: {resolved}")

            from sync_app.core.threading_helper import run_in_thread

            run_in_thread(_worker, on_complete=_done)
            return True

        from sync_app.core.sql_attach_helper import resolve_database_for_mdf_path

        resolved = resolve_database_for_mdf_path(
            mdf_path,
            config=self._master_runtime_sql_config(),
            timeout=4,
        )
        if not resolved:
            return False
        self.database_input.setText(resolved)
        idx = self.db_picker_combo.findText(resolved)
        if idx >= 0:
            self.db_picker_combo.blockSignals(True)
            self.db_picker_combo.setCurrentIndex(idx)
            self.db_picker_combo.blockSignals(False)
        if not silent:
            self._append_monitor(f"نام دیتابیس از فایل MDF: {resolved}")
        return True

    def _sync_mdf_from_selected_database(self, *, silent=False, background=False):
        """انتخاب کاربر در فیلد Database مبناست — مسیر MDF از SQL به‌روز می‌شود."""
        db_name = self.database_input.text().strip()
        if not db_name:
            return False

        if background:
            if (self.sql_mdf_path_input.text() or "").strip():
                return False
            cfg = self._master_runtime_sql_config()

            def _worker():
                from sync_app.core.sql_attach_helper import resolve_mdf_path_for_database

                return resolve_mdf_path_for_database(cfg, db_name, timeout=4)

            def _done(result):
                mdf_path, ldf_path = result or (None, None)
                self._apply_mdf_sync_result(
                    mdf_path, ldf_path, silent=silent, db_name=db_name
                )

            from sync_app.core.threading_helper import run_in_thread

            run_in_thread(_worker, on_complete=_done)
            return True

        from sync_app.core.sql_attach_helper import resolve_mdf_path_for_database

        mdf_path, ldf_path = resolve_mdf_path_for_database(
            self._master_runtime_sql_config(),
            db_name,
            timeout=4,
        )
        return self._apply_mdf_sync_result(
            mdf_path, ldf_path, silent=silent, db_name=db_name
        )

    def _build_runtime_sql_config(self):
        auth_mode = self._last_success_sql_auth_mode
        if auth_mode not in ["sql", "windows"]:
            auth_mode = self._detect_auth_modes()[0]
        mdf_path = self.sql_mdf_path_input.text().strip()
        database = self.database_input.text().strip() or "master"
        return {
            "SQL_DRIVER": self.driver_input.currentText(),
            "SQL_SERVER": self.server_input.text().strip(),
            "SQL_DATABASE": database,
            "SQL_USERNAME": self.username_input.text().strip(),
            "SQL_PASSWORD": self.password_input.text() or (self.config or {}).get("SQL_PASSWORD") or "",
            "SQL_AUTH_MODE": auth_mode,
            "SQL_MDF_PATH": mdf_path,
            "SQL_LDF_PATH": (self.config or {}).get("SQL_LDF_PATH") or "",
        }

    def _build_runtime_sql_config_for_list(self):
        runtime = self._build_runtime_sql_config()
        runtime["SQL_DATABASE"] = "master"
        return runtime

    def _browse_and_attach_database(self):
        start_dir = self._default_mdf_browse_dir()
        mdf_path, _ = QFileDialog.getOpenFileName(
            self,
            "انتخاب فایل دیتابیس (MDF)",
            start_dir,
            "SQL Database (*.mdf);;All Files (*.*)",
        )
        if not mdf_path:
            return

        current = (self.sql_mdf_path_input.text() or "").strip()
        if current and os.path.normcase(os.path.abspath(current)) == os.path.normcase(os.path.abspath(mdf_path)):
            self._begin_sql_op_log("انتخاب فایل MDF")
            self._sql_op_log_line(
                f"همان فایل MDF انتخاب شده — دیتابیس: {self.database_input.text().strip()}"
            )
            if self._sql_op_log is not None:
                self._sql_op_log.set_finished(True, "فایل تکراری — نیازی به Attach نیست")
            return

        self._begin_sql_op_log("Attach فایل MDF")
        from sync_app.core.app_version import APP_VERSION
        from sync_app.core.sql_attach_helper import suggest_import_database_name

        planned_name = suggest_import_database_name(mdf_path)
        self._sql_op_log_line(f"نسخه برنامه: {APP_VERSION}")
        self._sql_op_log_line(f"فایل انتخاب شد: {mdf_path}")
        self._sql_op_log_line(f"نام دیتابیس جدید (فایل + تاریخ امروز): {planned_name}")
        self.database_input.setText(planned_name)
        self.db_browse_btn.setEnabled(False)
        self.db_browse_btn.setText("⏳ در حال بررسی...")
        runtime_cfg = self._build_runtime_sql_config()

        self._sql_attach_thread = QThread(self)
        self._sql_attach_worker = SqlAttachWorker(runtime_cfg, mdf_path, fresh_import=True)
        self._sql_attach_worker.moveToThread(self._sql_attach_thread)
        self._sql_attach_thread.started.connect(self._sql_attach_worker.run)
        self._sql_attach_worker.log.connect(self._sql_op_log_line)
        self._sql_attach_worker.success.connect(self._on_sql_attach_success)
        self._sql_attach_worker.error.connect(self._on_sql_attach_error)
        self._sql_attach_worker.finished.connect(self._sql_attach_thread.quit)
        self._sql_attach_worker.finished.connect(self._sql_attach_worker.deleteLater)
        self._sql_attach_thread.finished.connect(self._sql_attach_thread.deleteLater)
        self._sql_attach_thread.finished.connect(self._on_sql_attach_finished)
        self._sql_attach_thread.start()

    def _on_sql_attach_success(self, result):
        self.db_browse_btn.setEnabled(True)
        self.db_browse_btn.setText("📁 انتخاب فایل")
        db_name = result["database"]
        self.sql_mdf_path_input.setText(result["mdf_path"])
        self.database_input.setText(db_name)
        if result.get("server"):
            self.server_input.setText(result["server"])
        if result.get("auth_mode") in ["sql", "windows"]:
            self._last_success_sql_auth_mode = result["auth_mode"]

        self.config = dict(self.config or {})
        self.config["SQL_MDF_PATH"] = result["mdf_path"]
        if result.get("ldf_path"):
            self.config["SQL_LDF_PATH"] = result["ldf_path"]
        self.config["SQL_DATABASE"] = db_name

        if result.get("already_attached"):
            self._sql_op_log_line(f"دیتابیس {db_name} از قبل روی SQL فعال بود")
        else:
            self._sql_op_log_line(f"Attach انجام شد — {db_name}")

        self._seed_db_picker_from_saved_config()
        self._update_launcher_sql_header(db_name)
        self._apply_database_switch(db_name, skip_confirm=True)
        QTimer.singleShot(400, lambda: self._load_databases_to_picker(force=True, silent=True))

    def _on_sql_attach_error(self, exc):
        from sync_app.core.sql_connection_helper import format_db_error

        self.db_browse_btn.setEnabled(True)
        self.db_browse_btn.setText("📁 انتخاب فایل")
        err = format_db_error(Exception(str(exc)))
        self._sql_op_log_line(f"خطا در Attach: {err}")
        self._offer_sql_service_action(str(exc))
        if self._sql_op_log is not None:
            self._sql_op_log.set_finished(False, "Attach ناموفق")
        self.set_button_status(self.sql_test_button, False)
        self.status_label.setText("❌ Attach ناموفق")
        self.status_label.setStyleSheet("color: #b91c1c; font-weight: bold;")

    def _on_sql_attach_finished(self):
        self._sql_attach_thread = None
        self._sql_attach_worker = None

    def _apply_sql_heal_patch(self, cfg):
        if not isinstance(cfg, dict):
            return
        server = (cfg.get("SQL_SERVER") or "").strip()
        if server and server != (self.server_input.text() or "").strip():
            self.server_input.setText(server)
            self._sql_op_log_line(f"Server خودکار اصلاح شد: {server}")
        auth = cfg.get("SQL_AUTH_MODE")
        if auth in ("sql", "windows"):
            self._last_success_sql_auth_mode = auth
        self.config = dict(self.config or {})
        self.config.update(
            {
                k: cfg[k]
                for k in ("SQL_SERVER", "SQL_AUTH_MODE", "SQL_CONN_STRING")
                if cfg.get(k)
            }
        )

    def _seed_db_picker_from_saved_config(self):
        db = (self.database_input.text() or "").strip()
        if not db:
            return
        self.db_picker_combo.blockSignals(True)
        if self.db_picker_combo.findText(db) < 0:
            self.db_picker_combo.insertItem(0, db)
        idx = self.db_picker_combo.findText(db)
        if idx >= 0:
            self.db_picker_combo.setCurrentIndex(idx)
        self.db_picker_combo.blockSignals(False)

    def _on_db_picker_changed(self, db_name):
        """وقتی کاربر دیتابیس انتخاب کرد — ذخیره و بارگذاری همه تب‌ها"""
        if not db_name or db_name.startswith("--"):
            return
        if not getattr(self, "_db_picker_apply_enabled", False):
            return

        self.database_input.setText(db_name)
        self._sync_mdf_from_selected_database(silent=True, background=False)
        self._apply_database_switch(db_name)

    def _apply_database_switch(self, new_database, *, skip_confirm=False):
        """دیتابیس جدید را ذخیره و داده همه تب‌ها را از آن بارگذاری کن."""
        if getattr(self, "_db_switch_running", False):
            return
        saved_cfg = load_secure_config(None) or {}
        new_mdf = self.sql_mdf_path_input.text().strip()
        new_database = (new_database or "").strip()
        if not new_database:
            return

        self.database_input.setText(new_database)
        self._update_launcher_sql_header(new_database)

        if not skip_confirm and self._sql_database_changed(saved_cfg, new_mdf, new_database):
            loaded = self._collect_loaded_session_summary(saved_cfg)
            if loaded:
                old_label = self._format_db_label(saved_cfg)
                new_label = self._format_db_label({
                    "SQL_DATABASE": new_database,
                    "SQL_MDF_PATH": new_mdf,
                })
                if not self._confirm_database_switch(old_label, new_label, loaded):
                    old_db = str(saved_cfg.get("SQL_DATABASE") or "").strip()
                    self.database_input.setText(old_db)
                    self._seed_db_picker_from_saved_config()
                    return

        self._db_switch_running = True
        try:
            self._begin_sql_op_log("اعمال دیتابیس جدید", clear=False)
            self._sql_op_log_line(f"ذخیره و بارگذاری تب‌ها برای «{new_database}»")
            self._pending_db_apply_name = new_database
            self.save_config(database_switch_confirmed=True)
        finally:
            QTimer.singleShot(300, lambda: setattr(self, "_db_switch_running", False))

    def _db_list_cache_key(self):
        runtime = self._build_runtime_sql_config_for_list()
        return (
            runtime.get("SQL_SERVER"),
            runtime.get("SQL_USERNAME"),
            runtime.get("SQL_AUTH_MODE"),
            runtime.get("SQL_DRIVER"),
        )

    def _load_databases_to_picker(self, force=False, *, silent=False):
        """اتصال به SQL Server و بارگذاری لیست دیتابیس‌های موجود"""
        if getattr(self, "_sql_db_thread", None) is not None and self._sql_db_thread.isRunning():
            if not silent:
                self._append_monitor("بارگذاری لیست دیتابیس در حال اجراست...")
            return

        server = (self.server_input.text() or "").strip()
        if not server:
            if not silent:
                QMessageBox.warning(self, "تنظیمات SQL", "ابتدا Server را وارد کنید.")
            return

        cache_key = self._db_list_cache_key()
        cached = getattr(self, "_db_list_cache", None)
        if (
            not force
            and cached
            and cached.get("key") == cache_key
            and (time.time() - cached.get("ts", 0)) < 45
        ):
            if silent:
                self._db_list_load_silent = True
                self._on_sql_db_list_loaded(cached.get("dbs") or [], from_cache=True)
                return
            self._begin_sql_op_log("بارگذاری لیست دیتابیس‌ها", clear=False)
            self._sql_op_log_line("استفاده از کش — بدون اتصال جدید")
            self._on_sql_db_list_loaded(cached.get("dbs") or [], from_cache=True)
            if self._sql_op_log is not None:
                self._sql_op_log.set_finished(True, f"{len(cached.get('dbs') or [])} دیتابیس (کش)")
            return

        self._db_list_load_silent = bool(silent)
        if not silent:
            self._begin_sql_op_log("بارگذاری لیست دیتابیس‌ها")
            self._sql_op_log_line(f"Server: {server}")
            self.db_refresh_btn.setEnabled(False)
            self.db_refresh_btn.setText("⏳")
            self.status_label.setText("در حال بارگذاری لیست دیتابیس‌ها...")
            self.status_label.setStyleSheet("color: #d97706; font-weight: bold;")

        runtime = self._build_runtime_sql_config_for_list()
        self._sql_db_thread = QThread(self)
        self._sql_db_worker = SqlDbListWorker(runtime)
        self._sql_db_worker.moveToThread(self._sql_db_thread)
        self._sql_db_thread.started.connect(self._sql_db_worker.run)
        if not silent:
            self._sql_db_worker.log.connect(self._sql_op_log_line)
        self._sql_db_worker.healed.connect(self._apply_sql_heal_patch)
        self._sql_db_worker.finished.connect(self._on_sql_db_list_loaded)
        self._sql_db_worker.error.connect(self._on_sql_db_list_error)
        self._sql_db_worker.finished.connect(self._sql_db_thread.quit)
        self._sql_db_worker.error.connect(self._sql_db_thread.quit)
        self._sql_db_worker.finished.connect(self._sql_db_worker.deleteLater)
        self._sql_db_worker.error.connect(self._sql_db_worker.deleteLater)
        self._sql_db_thread.finished.connect(self._sql_db_thread.deleteLater)
        self._sql_db_thread.finished.connect(self._on_sql_db_list_finished)
        self._sql_db_thread.start()

    def _on_sql_db_list_loaded(self, dbs, from_cache=False):
        if not isinstance(dbs, list):
            dbs = list(dbs or [])
        silent = bool(getattr(self, "_db_list_load_silent", False))
        self._db_list_load_silent = False
        self._db_list_cache = {
            "key": self._db_list_cache_key(),
            "dbs": list(dbs),
            "ts": time.time(),
        }
        self.db_picker_combo.blockSignals(True)
        self.db_picker_combo.clear()
        for db in dbs:
            self.db_picker_combo.addItem(str(db))
        current = self.database_input.text().strip()
        idx = self.db_picker_combo.findText(current)
        if idx >= 0:
            self.db_picker_combo.setCurrentIndex(idx)
        self.db_picker_combo.blockSignals(False)
        if silent:
            return

        preview = ", ".join(str(db) for db in dbs[:12])
        if len(dbs) > 12:
            preview += f" ... (+{len(dbs) - 12})"
        self._sql_op_log_line(f"دیتابیس‌های موجود روی SQL ({len(dbs)}): {preview}")
        suffix = " (کش)" if from_cache else ""
        self.status_label.setText(f"✅ لیست SQL: {len(dbs)} دیتابیس{suffix}")
        self.status_label.setStyleSheet("color: #166534; font-weight: bold;")
        if self._sql_op_log is not None and not from_cache:
            self._sql_op_log.set_finished(True, f"لیست SQL: {len(dbs)} دیتابیس")

    def _on_sql_db_list_error(self, message):
        self._sql_op_log_line(f"خطا در بارگذاری دیتابیس‌ها: {message}")
        self._offer_sql_service_action(message)
        self._seed_db_picker_from_saved_config()
        self.status_label.setText("⚠️ لیست SQL نیامد — از نام ذخیره‌شده استفاده کنید")
        self.status_label.setStyleSheet("color: #b45309; font-weight: bold;")
        if self._sql_op_log is not None:
            self._sql_op_log.set_finished(False, "بارگذاری لیست ناموفق")

    def _on_sql_db_list_finished(self):
        self._sql_db_thread = None
        self.db_refresh_btn.setEnabled(True)
        self.db_refresh_btn.setText("↻ بارگذاری")

    def _widget_field_value(self, widget):
        """مقدار فعلی یک ویجت تنظیمات برای مقایسه با baseline"""
        if isinstance(widget, QLineEdit):
            return widget.text()
        if isinstance(widget, QComboBox):
            data = widget.currentData()
            return data if data is not None else widget.currentIndex()
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        return None

    def _apply_widget_modified_style(self, widget, modified):
        """هایلایت فیلد تغییرکرده تا قبل از ذخیره"""
        widget.setProperty("modified", bool(modified))
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _snapshot_field_baselines(self):
        """ثبت مقادیر ذخیره‌شده فعلی به‌عنوان مرجع"""
        self._field_baselines = {
            id(widget): self._widget_field_value(widget)
            for widget in self._tracked_widgets
        }

    def _on_settings_field_changed(self, *_args):
        """به‌روزرسانی هایلایت فیلدها و وضعیت کلی ذخیره‌نشده"""
        self._refresh_dirty_state()

    def _refresh_dirty_state(self):
        if not hasattr(self, "status_label"):
            # ممکنه در حینِ ساختِ init_ui، هایدشدن/دیده‌شدنِ یک فیلدِ ووکامرس/پرستاشاپ
            # (در _apply_platform_field_visibility) سیگنالِ editingFinished رو زودتر
            # از تکمیلِ کاملِ UI شلیک کنه — تا اون موقع چیزی برای رفرش نیست.
            return
        any_modified = False
        for widget in self._tracked_widgets:
            baseline = self._field_baselines.get(id(widget))
            modified = self._widget_field_value(widget) != baseline
            self._apply_widget_modified_style(widget, modified)
            if modified:
                any_modified = True

        self._dirty = any_modified
        if any_modified:
            self.status_label.setText("● تغییرات ذخیره نشده")
            self.status_label.setStyleSheet(
                "color: #92400e; font-weight: 700; font-size: 12px; "
                "padding: 6px 14px; background: #fef3c7; border-radius: 8px; "
                "border: 1px solid #f59e0b;"
            )
        elif self.status_label.text() == "● تغییرات ذخیره نشده":
            self.status_label.setText("آماده")
            self.status_label.setStyleSheet(
                "color: #16a34a; font-weight: 700; font-size: 12px; "
                "padding: 6px 14px; background: #dcfce7; border-radius: 8px;"
            )

    def _mark_dirty(self):
        """برای کد قدیمی."""
        self._refresh_dirty_state()

    def _clear_dirty(self):
        """پاکسازی وضعیت تغییرات ذخیره‌نشده و بازگشت رنگ فیلدها"""
        self._dirty = False
        self._snapshot_field_baselines()
        self._snapshot_wc_site_baseline()
        for widget in self._tracked_widgets:
            self._apply_widget_modified_style(widget, False)

    @staticmethod
    def _sql_database_identity(cfg):
        if not cfg:
            return "", ""
        mdf = (cfg.get("SQL_MDF_PATH") or "").strip()
        if mdf:
            mdf = os.path.normcase(os.path.normpath(mdf))
        db = (cfg.get("SQL_DATABASE") or "").strip().casefold()
        return mdf, db

    def _sql_database_changed(self, old_config, new_mdf_path, new_database):
        old_mdf, old_db = self._sql_database_identity(old_config)
        new_mdf = (new_mdf_path or "").strip()
        if new_mdf:
            new_mdf = os.path.normcase(os.path.normpath(new_mdf))
        new_db = (new_database or "").strip().casefold()
        if not (old_mdf or old_db):
            return False
        return (old_mdf, old_db) != (new_mdf, new_db)

    @staticmethod
    def _format_db_label(cfg):
        db = (cfg.get("SQL_DATABASE") or "").strip()
        mdf = (cfg.get("SQL_MDF_PATH") or "").strip()
        if db and mdf:
            return f"{db} — {os.path.basename(mdf)}"
        return db or (os.path.basename(mdf) if mdf else "—")

    @staticmethod
    def _list_widget_has_loaded_data(list_widget):
        if list_widget is None or list_widget.count() <= 0:
            return False
        if list_widget.count() == 1:
            text = (list_widget.item(0).text() or "").strip()
            if text.startswith("⚠️") or text.startswith("⏳"):
                return False
        return True

    def _collect_loaded_session_summary(self, config):
        items = []

        try:
            from sync_app.core.category_resolver import load_category_map
            category_map = load_category_map()
            if category_map:
                items.append(f"نگاشت دسته‌بندی: {len(category_map)} مورد")
        except Exception:
            pass

        try:
            from sync_app.core.product_woo_map_helper import load_product_woo_map
            product_map = load_product_woo_map()
            if product_map:
                items.append(f"نگاشت محصول: {len(product_map)} مورد")
        except Exception:
            pass

        selected_sub = [str(g).strip() for g in (config.get("SELECTED_SUB_GROUPS") or []) if str(g).strip()]
        if selected_sub:
            items.append(f"گروه‌های انتخاب‌شده: {len(selected_sub)} مورد")

        if self.category_tab_ref and getattr(self.category_tab_ref, "tree", None):
            if self.category_tab_ref.tree.topLevelItemCount() > 0:
                items.append("تب دسته‌بندی: داده بارگذاری شده")

        if self.product_tab_ref and self._list_widget_has_loaded_data(
            getattr(self.product_tab_ref, "product_list", None)
        ):
            items.append("تب محصولات: داده بارگذاری شده")

        if self.variation_tab_ref and self._list_widget_has_loaded_data(
            getattr(self.variation_tab_ref, "variation_list", None)
        ):
            items.append("تب متغیرها: داده بارگذاری شده")

        recon = self.reconciliation_tab_ref
        if recon is not None and getattr(recon, "_comparison", None) is not None:
            items.append("تب تطبیق: نتایج مقایسه بارگذاری شده")

        if self.properties_tab_ref and self._list_widget_has_loaded_data(
            getattr(self.properties_tab_ref, "properties_list", None)
        ):
            items.append("تب ویژگی‌ها: داده بارگذاری شده")

        return items

    def _confirm_database_switch(self, old_label, new_label, loaded_items):
        msg = QMessageBox(self)
        msg.setWindowTitle("تغییر دیتابیس SQL")
        msg.setIcon(QMessageBox.Warning)
        msg.setText(
            "مسیر یا نام دیتابیس SQL تغییر کرده است.\n\n"
            f"قبلی: {old_label}\n"
            f"جدید: {new_label}\n\n"
            "داده‌های زیر از دیتابیس قبلی بارگذاری شده یا نگاشت دارند:\n"
            + "\n".join(f"• {item}" for item in loaded_items)
            + "\n\n"
            "با ذخیره، همه تب‌های وابسته به SQL (محصولات، متغیرها، دسته‌بندی، "
            "داشبورد، ویژگی‌ها، مشتریان، سفارشات و تطبیق) "
            "از دیتابیس جدید بارگذاری می‌شوند.\n"
            "فایل‌های نگاشت (category_map / product_woo_map) ممکن است "
            "مربوط به دیتابیس قبلی باشند."
        )
        save_btn = msg.addButton("ذخیره و ادامه", QMessageBox.AcceptRole)
        msg.addButton("انصراف", QMessageBox.RejectRole)
        msg.setDefaultButton(save_btn)
        msg.exec_()
        return msg.clickedButton() == save_btn

    def hideEvent(self, event):
        """هشدار هنگام ترک تب تنظیمات با تغییرات ذخیره‌نشده"""
        if self._dirty:
            msg = QMessageBox(self)
            msg.setWindowTitle("تغییرات ذخیره نشده")
            msg.setText(
                "تغییراتی در تنظیمات اعمال شده و هنوز ذخیره نشده است.\n"
                "آیا می‌خواهید قبل از خروج ذخیره شود؟"
            )
            msg.setIcon(QMessageBox.Question)
            save_btn = msg.addButton("ذخیره", QMessageBox.AcceptRole)
            discard_btn = msg.addButton("بدون ذخیره خارج شو", QMessageBox.DestructiveRole)
            msg.setDefaultButton(save_btn)
            msg.exec_()
            if msg.clickedButton() == save_btn:
                self.save_config()
        super().hideEvent(event)

    def _reload_sql_tabs(self):
        db_name = (self.database_input.text() or "").strip() or "—"
        self._sql_op_log_line(f"بارگذاری مجدد تب‌ها از دیتابیس «{db_name}»...")

        from sync_app.core.connectivity_guard import find_peecha_launcher

        launcher = find_peecha_launcher(self)
        if launcher is not None and hasattr(launcher, "reload_sql_dependent_tabs"):
            launcher.reload_sql_dependent_tabs(log_callback=self._sql_op_log_line)
        else:
            if self.product_tab_ref:
                self.product_tab_ref.config = load_secure_config(None) or {}
                self.product_tab_ref.load_products()
            if self.variation_tab_ref:
                self.variation_tab_ref.config = load_secure_config(None) or {}
                self.variation_tab_ref.load_variations()
            if self.category_tab_ref:
                self.category_tab_ref.config = load_secure_config(None) or {}
                if hasattr(self.category_tab_ref, "_initial_load_started"):
                    self.category_tab_ref._initial_load_started = True
                self.category_tab_ref.load_groups()
            if self.dashboard_tab_ref:
                self.dashboard_tab_ref.load_data()
            if self.properties_tab_ref:
                self.properties_tab_ref.config = load_secure_config(None) or {}
                if hasattr(self.properties_tab_ref, "_initial_load_started"):
                    self.properties_tab_ref._initial_load_started = True
                self.properties_tab_ref.load_properties_preview()
            if self.customer_tab_ref and hasattr(self.customer_tab_ref, "load_site_customers"):
                self.customer_tab_ref.config = load_secure_config(None) or {}
                self.customer_tab_ref.load_site_customers(silent=True)
            if self.order_tab_ref and hasattr(self.order_tab_ref, "load_site_orders"):
                self.order_tab_ref.config = load_secure_config(None) or {}
                self.order_tab_ref.load_site_orders(silent=True)
            if self.reconciliation_tab_ref and hasattr(
                self.reconciliation_tab_ref, "invalidate_stale_sql_data"
            ):
                self.reconciliation_tab_ref.config = load_secure_config(None) or {}
                self.reconciliation_tab_ref.invalidate_stale_sql_data()

        pending = getattr(self, "_pending_db_apply_name", None)
        if pending:
            summary = f"✅ دیتابیس «{pending}» در برنامه اعمال شد"
            self._sql_op_log_line(
                "تب‌های باز‌شده از دیتابیس جدید بارگذاری شدند؛ "
                "بقیه تب‌ها با اولین باز کردن به‌روز می‌شوند."
            )
            self.status_label.setText(summary)
            self.status_label.setStyleSheet(
                "color: #166534; font-weight: 700; font-size: 12px; "
                "padding: 6px 14px; background: #dcfce7; border-radius: 8px;"
            )
            if self._sql_op_log is not None:
                self._sql_op_log.set_finished(True, summary)
            self._pending_db_apply_name = None
        else:
            self._sql_op_log_line("بارگذاری تب‌ها در پس‌زمینه شروع شد")

    def _needs_mdf_sync_on_save(self, saved_cfg: dict) -> bool:
        new_db = self.database_input.text().strip()
        old_db = str(saved_cfg.get("SQL_DATABASE") or "").strip()
        if new_db != old_db:
            return True
        return not (self.sql_mdf_path_input.text() or "").strip()

    @staticmethod
    def _config_slice_changed(old_cfg: dict, new_cfg: dict, keys: tuple[str, ...]) -> bool:
        for key in keys:
            if str(old_cfg.get(key) or "") != str(new_cfg.get(key) or ""):
                return True
        return False

    def _schedule_license_site_push(self, config: dict | None = None) -> None:
        import threading

        cfg = dict(config or self.config or {})

        def _run():
            try:
                from sync_app.core.license_remote import push_license_site_to_server

                push_license_site_to_server(cfg)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def _schedule_post_save_refresh(
        self,
        *,
        database_changed: bool,
        old_cfg: dict,
        new_cfg: dict,
        theme_value: str,
    ) -> None:
        sql_changed = database_changed or self._config_slice_changed(
            old_cfg,
            new_cfg,
            (
                "SQL_CONN_STRING",
                "SQL_DRIVER",
                "SQL_AUTH_MODE",
                "SQL_SERVER",
                "SQL_DATABASE",
                "SQL_MDF_PATH",
                "SQL_LDF_PATH",
                "SQL_USERNAME",
                "SQL_PASSWORD",
            ),
        )
        catalog_changed = self._config_slice_changed(
            old_cfg,
            new_cfg,
            (
                "PRICE_LIST_INDEX",
                "PRICE_LIST_COLUMN",
                "SALE_PRICE_LIST_ENABLED",
                "SALE_PRICE_LIST_INDEX",
                "SALE_PRICE_LIST_COLUMN",
                "ERP_PICTURE_ROOT",
                "WC_CURRENCY_IS_TOMAN",
                "ERP_PROVIDER",
            ),
        )
        theme_changed = str(old_cfg.get("APP_THEME") or "") != str(theme_value or "")

        from sync_app.core.connectivity_guard import find_peecha_launcher

        launcher = find_peecha_launcher(self)

        if sql_changed:
            db_name = str(new_cfg.get("SQL_DATABASE") or "").strip()
            if launcher is not None and db_name:
                if hasattr(launcher, "set_sql_header_database"):
                    launcher.set_sql_header_database(
                        db_name,
                        sql_ok=getattr(launcher, "_sql_display_ok", None),
                    )
            QTimer.singleShot(80, self._reload_sql_tabs)
        elif catalog_changed:
            if self.product_tab_ref:
                QTimer.singleShot(80, self.product_tab_ref.load_products)
            if self.variation_tab_ref:
                QTimer.singleShot(160, self.variation_tab_ref.load_variations)
            if self.category_tab_ref:
                QTimer.singleShot(240, self.category_tab_ref.load_groups)
            if self.dashboard_tab_ref:
                QTimer.singleShot(320, self.dashboard_tab_ref.load_data)

        if theme_changed and self.theme_changed_callback:
            QTimer.singleShot(0, lambda: self.theme_changed_callback(theme_value))

        if launcher is not None:
            wc_changed = self._config_slice_changed(
                old_cfg,
                new_cfg,
                (
                    "WC_URL",
                    "WC_CONSUMER_KEY",
                    "WC_CONSUMER_SECRET",
                    "WP_USERNAME",
                    "WP_APP_PASSWORD",
                    "WC_TIMEOUT",
                ),
            )
            if wc_changed:
                QTimer.singleShot(250, lambda: launcher.refresh_wc_connectivity())
            wc_sites_changed = self._config_slice_changed(
                old_cfg,
                new_cfg,
                ("ACTIVE_WC_SITE_ID",),
            )
            if wc_sites_changed and not wc_changed:
                QTimer.singleShot(250, lambda: launcher.refresh_wc_connectivity())
            if sql_changed:
                QTimer.singleShot(300, lambda: launcher.refresh_sql_connectivity(show_pending=False))

    def save_config(self, *, database_switch_confirmed=False):
        try:
            config_to_save = load_secure_config(None) or {}
            old_cfg = dict(config_to_save)
            if self._needs_mdf_sync_on_save(config_to_save):
                self._sync_mdf_from_selected_database(silent=True, background=False)
            new_mdf_path = self.sql_mdf_path_input.text().strip()
            new_database = self.database_input.text().strip()
            database_changed = self._sql_database_changed(
                config_to_save, new_mdf_path, new_database
            )
            if database_changed and not database_switch_confirmed:
                loaded_items = self._collect_loaded_session_summary(config_to_save)
                if loaded_items:
                    old_label = self._format_db_label(config_to_save)
                    new_label = self._format_db_label({
                        "SQL_DATABASE": new_database,
                        "SQL_MDF_PATH": new_mdf_path,
                    })
                    if not self._confirm_database_switch(old_label, new_label, loaded_items):
                        return

            auth_mode = self._resolve_sql_auth_mode_for_save(config_to_save)
            sql_password = self.password_input.text()
            if not sql_password and config_to_save.get("SQL_PASSWORD"):
                sql_password = config_to_save.get("SQL_PASSWORD") or ""

            conn_str = self._build_conn_str(self.driver_input.currentText(), auth_mode=auth_mode)

            app_login_username = (self.app_login_username_input.text() or "").strip() or "admin"
            app_login_password = self.app_login_password_input.text() or "123456"
            self.app_login_username_input.setText(app_login_username)

            license_server_url = (self.license_server_url_input.text() or "").strip().rstrip("/")
            self.license_server_url_input.setText(license_server_url)
            license_api_key = self.license_api_key_input.text()
            if not license_api_key and config_to_save.get("LICENSE_API_KEY"):
                license_api_key = config_to_save.get("LICENSE_API_KEY") or ""

            selected_index = self.price_combo.currentIndex()
            list_number = selected_index + 1
            column_suffix = "" if list_number == 1 else str(list_number)
            column_name = f"Sel_Price{column_suffix}"

            sale_index = self.sale_price_combo.currentIndex()
            sale_list_number = sale_index + 1
            sale_suffix = "" if sale_list_number == 1 else str(sale_list_number)
            sale_column_name = f"Sel_Price{sale_suffix}"

            config_to_save.update({
                "SQL_CONN_STRING": conn_str,
                "SQL_DRIVER": self.driver_input.currentText(),
                "SQL_AUTH_MODE": auth_mode,
                "SQL_SERVER": self.server_input.text(),
                "SQL_DATABASE": self.database_input.text(),
                "SQL_MDF_PATH": self.sql_mdf_path_input.text().strip(),
                "SQL_LDF_PATH": (self.config or {}).get("SQL_LDF_PATH") or "",
                "SQL_USERNAME": self.username_input.text(),
                "SQL_PASSWORD": sql_password,
                "WC_TIMEOUT": self.get_optimized_timeout(),
                "PRICE_LIST_INDEX": selected_index,
                "PRICE_LIST_COLUMN": column_name,
                "PRICE_MARKUP_PERCENT": self.price_markup_spin.value(),
                "SALE_PRICE_LIST_ENABLED": self.sale_price_enabled_cb.isChecked(),
                "SALE_PRICE_LIST_INDEX": sale_index,
                "SALE_PRICE_LIST_COLUMN": sale_column_name,
                "SALE_PRICE_MARKUP_PERCENT": self.sale_price_markup_spin.value(),
                "ERP_PICTURE_ROOT": self.erp_picture_root_input.text().strip(),
                "APP_THEME": self.theme_combo.currentData(),
                "ERP_PROVIDER": self.erp_provider_combo.currentData(),
                "APP_LOGIN_USERNAME": app_login_username,
                "APP_LOGIN_PASSWORD": app_login_password,
                "APP_SHOW_LOGIN_SCREEN": self.login_screen_enabled_checkbox.isChecked(),
                "AUTO_UPDATE_ENABLED": self.auto_update_enabled_checkbox.isChecked(),
                "LICENSE_SERVER_URL": license_server_url,
                "LICENSE_API_KEY": license_api_key,
                "DEFAULT_CUSTOMER_MODE": self.default_customer_mode_combo.currentData() or "website",
                "DEFAULT_CUSTOMER_CODE": (self.default_customer_code_input.text() or "").strip(),
                "STORE_PLATFORM": self.store_platform_combo.currentData() or "woocommerce",
                "PS_URL": self.ps_url_input.text().strip(),
                "PS_API_KEY": self.ps_api_key_input.text().strip(),
                "TELEGRAM_BOT_TOKEN": self.telegram_bot_token_input.text().strip(),
                "TELEGRAM_CHAT_ID": self.telegram_chat_id_input.text().strip(),
                "TELEGRAM_PROXY_URL": self.telegram_proxy_url_input.text().strip(),
                "BALE_BOT_TOKEN": self.bale_bot_token_input.text().strip(),
                "BALE_CHAT_ID": self.bale_chat_id_input.text().strip(),
            })
            for _cfg_key, _cb in self._field_sync_checkboxes.items():
                config_to_save[_cfg_key] = _cb.isChecked()
            for _cfg_key, _cb in self._force_full_sync_checkboxes.items():
                config_to_save[_cfg_key] = _cb.isChecked()

            from sync_app.core.wc_site_edit_guard import ACTION_CANCEL

            if self._needs_wc_site_guard():
                guard_action = self._guard_wc_site_save()
                if guard_action == ACTION_CANCEL:
                    self.status_label.setText("● ذخیره لغو شد — تغییرات WooCommerce برگردانده شد")
                    self.status_label.setStyleSheet(
                        "color: #92400e; font-weight: 700; font-size: 12px; "
                        "padding: 6px 14px; background: #fef3c7; border-radius: 8px;"
                    )
                    return

            from sync_app.core.ps_site_edit_guard import ACTION_CANCEL as PS_ACTION_CANCEL

            if self._needs_ps_site_guard():
                ps_guard_action = self._guard_ps_site_save()
                if ps_guard_action == PS_ACTION_CANCEL:
                    self.status_label.setText("● ذخیره لغو شد — تغییرات PrestaShop برگردانده شد")
                    self.status_label.setStyleSheet(
                        "color: #92400e; font-weight: 700; font-size: 12px; "
                        "padding: 6px 14px; background: #fef3c7; border-radius: 8px;"
                    )
                    return

            config_to_save = self._apply_wc_sites_to_config_dict(config_to_save)
            config_to_save = self._apply_ps_sites_to_config_dict(config_to_save)
            config_to_save["WC_PARALLEL_WORKERS"] = int(self.parallel_workers_spin.value())
            old_product_mode = str(self.config.get("PRODUCT_MODE", "with_variants"))
            new_product_mode = self.product_mode_combo.currentData()
            config_to_save["PRODUCT_MODE"] = new_product_mode

            save_secure_config(config_to_save)
            self.config = dict(config_to_save)
            if old_product_mode != new_product_mode:
                QMessageBox.information(
                    self, "نیاز به راه‌اندازی مجدد",
                    "نوع محصولات فروشگاه تغییر کرد. برای اینکه تب‌ها و بخش‌های "
                    "مربوط به ویژگی/متغیر در همه‌جای برنامه درست به‌روز بشن، "
                    "لطفاً برنامه را ببندید و دوباره باز کنید.",
                )
            self._broadcast_wc_config_reload()
            self._schedule_license_site_push(config_to_save)
            self._last_success_sql_auth_mode = auth_mode
            self._clear_dirty()
            append_system_log("settings", "تنظیمات با موفقیت ذخیره شد.")
            if not getattr(self, "_pending_db_apply_name", None):
                self.status_label.setText("✅ تنظیمات با موفقیت ذخیره شد.")
                self.status_label.setStyleSheet(
                    "color: #166534; font-weight: 700; font-size: 12px; "
                    "padding: 6px 14px; background: #dcfce7; border-radius: 8px;"
                )

            theme_value = self.theme_combo.currentData()
            self._schedule_post_save_refresh(
                database_changed=database_changed,
                old_cfg=old_cfg,
                new_cfg=config_to_save,
                theme_value=theme_value,
            )

        except Exception as e:
            append_system_log("settings", f"خطا در ذخیره تنظیمات: {e}", level="ERROR")
            self.status_label.setText(f"❌ خطا در ذخیره تنظیمات: {e}")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")

    def preview_font_size_change(self):
        # ذخیره و اعمال فوری سایز فونت انتخاب‌شده
        font_size = self.font_size_combo.currentData() or 14
        try:
            config_to_save = load_secure_config(None) or {}
            config_to_save["APP_FONT_SIZE"] = font_size
            save_secure_config(config_to_save)
            self.config["APP_FONT_SIZE"] = font_size
        except Exception:
            pass
        if hasattr(self, "font_size_changed_callback") and self.font_size_changed_callback:
            self.font_size_changed_callback(font_size)

    def preview_theme_change(self):
        selected_theme = self.theme_combo.currentData() or "navy"
        if selected_theme not in {"navy", "red", "green"}:
            selected_theme = "navy"

        # ذخیره فوری تم انتخاب‌شده تا در اجرای بعدی هم همان تم اعمال شود
        try:
            config_to_save = load_secure_config(None) or {}
            config_to_save["APP_THEME"] = selected_theme
            save_secure_config(config_to_save)
            self.config["APP_THEME"] = selected_theme
        except Exception:
            # خطای ذخیره تم نباید مانع پیش‌نمایش UI شود
            pass

        if self.theme_changed_callback:
            self.theme_changed_callback(selected_theme)

    def update_provider_hint(self):
        provider = get_provider(self.erp_provider_combo.currentData())
        self.provider_hint_label.setText(provider.get_provider_hint())
