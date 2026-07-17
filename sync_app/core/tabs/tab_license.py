import base64
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sync_app.core.app_theme import (
    build_license_tab_stylesheet,
    get_active_theme_palette,
    resolve_user_font_pref,
)
from sync_app.core.message_boxes_fa import set_rtl_label_text
from sync_app.core.secure_config_loader import load_secure_config
from sync_app.core.user_profile import load_secure_config_after_profile


def _legacy_license_path() -> str:
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, "license.json")


def license_file_path() -> str:
    """مسیر ذخیره لایسنس — در AppData تا در EXE قابل نوشتن باشد."""
    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    base = os.path.join(local, "PeechaSync")
    os.makedirs(base, exist_ok=True)
    target = os.path.join(base, "license.json")
    if os.path.exists(target):
        return target

    legacy = _legacy_license_path()
    if os.path.exists(legacy):
        try:
            shutil.copy2(legacy, target)
        except Exception:
            pass
    return target


LICENSE_BYPASS = False

# کلیدِ عمومیِ Ed25519 — امن است که همین‌جا و در سورسِ عمومی باشد؛ فقط
# برای تأییدِ امضا کاربرد داره، نه ساختِ امضای جدید (کلیدِ خصوصیِ متناظر
# فقط سمتِ سرور/وردپرس نگه داشته می‌شه). این جایگزینِ کلیدِ مشترکِ HMAC
# قدیمی (V2) شد، چون اون کلید چون داخلِ سورسِ عمومی هاردکد بود لو رفت —
# با این طرح، حتی اگه کل سورس همیشه Public بمونه، کسی نمی‌تونه لایسنسِ
# جعلی بسازه.
_ED25519_PUBLIC_KEY_B64 = "nQcflkw7e6P1oaV2CJLT0L20nVJtNt181hs6ZhdtEAg="


class LicenseTab(QWidget):
    def __init__(self, on_activated=None):
        super().__init__()
        self._on_activated = on_activated
        self.hwid = self.get_hwid()
        self.setObjectName("licenseRoot")
        self.setLayoutDirection(Qt.RightToLeft)
        self._info_value_labels: dict[str, QLabel] = {}
        self._was_locked_once = False
        self._apply_tab_theme()
        self.init_ui()
        self.refresh_license_display()

    def _apply_tab_theme(self) -> None:
        cfg = load_secure_config(None) or {}
        _, palette = get_active_theme_palette()
        font_size, is_bold = resolve_user_font_pref(cfg.get("APP_FONT_SIZE", 14))
        self.setStyleSheet(build_license_tab_stylesheet(palette, font_size, is_bold))

    @staticmethod
    def _read_hwid_serial(text: str) -> str:
        for line in (text or "").splitlines():
            serial = line.strip()
            if not serial or serial.lower() == "serialnumber":
                continue
            if serial == "To be filled by O.E.M.":
                return "DEV_MODE_ID"
            return serial
        return ""

    @staticmethod
    def get_hwid():
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            commands = (
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_BaseBoard).SerialNumber",
                ],
                ["wmic", "baseboard", "get", "serialnumber"],
            )
            for cmd in commands:
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=4,
                        creationflags=creationflags,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    continue
                serial = LicenseTab._read_hwid_serial(result.stdout)
                if serial:
                    return serial

        return "GENERIC_HWID"

    @staticmethod
    def is_license_server_denied() -> bool:
        try:
            license_file = license_file_path()
            if not os.path.exists(license_file):
                return False
            with open(license_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cache = data.get("remote_cache") if isinstance(data.get("remote_cache"), dict) else {}
            from sync_app.core.license_remote import is_server_denied_status

            return is_server_denied_status(str(cache.get("status") or ""))
        except Exception:
            return False

    @staticmethod
    def find_launcher(widget):
        w = widget
        while w is not None:
            if w.__class__.__name__ == "PeechaLauncher":
                return w
            w = w.parent()
        return None

    @staticmethod
    def guard_usable(parent=None) -> bool:
        if LICENSE_BYPASS:
            return True
        if not LicenseTab.is_license_server_denied():
            return True
        launcher = LicenseTab.find_launcher(parent)
        if launcher is not None and hasattr(launcher, "_enter_license_renewal_mode"):
            cache_status = "expired"
            try:
                with open(license_file_path(), "r", encoding="utf-8") as f:
                    raw = json.load(f)
                cache = raw.get("remote_cache") if isinstance(raw.get("remote_cache"), dict) else {}
                cache_status = str(cache.get("status") or "expired")
            except Exception:
                pass
            launcher._enter_license_renewal_mode(cache_status)
        elif parent is not None:
            QMessageBox.warning(
                parent,
                "لایسنس",
                "لایسنس منقضی یا باطل شده است.\n\nبا peecha.ir تماس بگیرید.",
            )
        return False

    @staticmethod
    def is_license_cache_revoked() -> bool:
        return LicenseTab.is_license_server_denied()

    @staticmethod
    def is_license_valid(*, online: bool = True):
        if LICENSE_BYPASS:
            return True
        if LicenseTab.is_license_server_denied():
            return False
        license_file = license_file_path()
        if not os.path.exists(license_file):
            return False
        try:
            with open(license_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = data.get("license_key", "")
            hwid = LicenseTab.get_hwid()

            from sync_app.core.license_remote import (
                apply_server_license_denial,
                is_revoked_error,
                is_server_denied_status,
                merge_remote_cache,
                remote_cache_license_valid,
                try_online_validate,
            )

            cache = data.get("remote_cache") if isinstance(data.get("remote_cache"), dict) else {}
            if is_server_denied_status(str(cache.get("status") or "")):
                return False

            if LicenseTab.validate_key(key, hwid):
                if not online:
                    return True
                if remote_cache_license_valid(cache, hwid):
                    return True

            if not online:
                return False

            ok, lic, err = try_online_validate(key, hwid, activate=False)
            if ok:
                merge_remote_cache(key, lic, hwid)
                return True

            denied = apply_server_license_denial(hwid, err, lic if isinstance(lic, dict) else {})
            if denied:
                return False

            if remote_cache_license_valid(cache, hwid):
                return True

            if err and err not in ("timeout", "connection_error"):
                return False

            return LicenseTab.validate_key(key, hwid)
        except Exception:
            return False

    @staticmethod
    def is_license_valid_for_launch():
        """بدون شبکه — فقط برای باز کردن سریع پنجره."""
        if LicenseTab.is_license_server_denied():
            return False
        return LicenseTab.is_license_valid(online=False)

    @staticmethod
    def _urlsafe_b64decode_padded(value):
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _validate_v3_signed_key(key, hwid):
        """امضای نامتقارنِ Ed25519 — کلیدِ خصوصیِ متناظر فقط سمتِ سرور/
        وردپرسه، هیچ‌وقت داخلِ این سورس نبوده و نیست. جایگزینِ روشِ قدیمیِ
        HMACِ مشترک (V2) شد چون اون کلید داخلِ همین سورس هاردکد بود و با
        Publicشدنِ مخزن لو رفت."""
        if "." not in key:
            return False

        payload_b64, given_sig_b64 = key.split(".", 1)

        sig_padded = given_sig_b64 + "=" * (-len(given_sig_b64) % 4)
        signature = base64.urlsafe_b64decode(sig_padded.encode("utf-8"))

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(_ED25519_PUBLIC_KEY_B64)
        )
        try:
            public_key.verify(signature, payload_b64.encode("utf-8"))
        except InvalidSignature:
            return False

        payload_json = LicenseTab._urlsafe_b64decode_padded(payload_b64)
        payload = json.loads(payload_json)

        if payload.get("v") != 3:
            return False

        if payload.get("h") != hwid:
            return False

        expiry_text = payload.get("e")
        if not expiry_text:
            return False

        if datetime.strptime(expiry_text, "%Y-%m-%d") < datetime.now():
            return False

        return True

    @staticmethod
    def validate_key(key, hwid):
        if not key:
            return False

        try:
            return LicenseTab._validate_v3_signed_key(key, hwid)
        except Exception:
            return False

    @staticmethod
    def _load_license_key() -> str:
        if LICENSE_BYPASS:
            return ""
        try:
            license_file = license_file_path()
            if not os.path.exists(license_file):
                return ""
            with open(license_file, "r", encoding="utf-8") as f:
                return str(json.load(f).get("license_key") or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _normalize_site_url(url: str) -> str:
        return (url or "").strip().rstrip("/").lower()

    @staticmethod
    def _site_fingerprint(url: str) -> str:
        import hashlib

        normalized = LicenseTab._normalize_site_url(url)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _current_site_url(config: dict) -> str:
        from sync_app.core.integrations.commerce_provider import is_prestashop

        if is_prestashop(config):
            return str(config.get("PS_URL") or "").strip()
        return str(config.get("WC_URL") or "").strip()

    @staticmethod
    def _load_sites_seen() -> list:
        try:
            with open(license_file_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            seen = data.get("sites_seen")
            return list(seen) if isinstance(seen, list) else []
        except Exception:
            return []

    @staticmethod
    def _save_sites_seen(sites_seen: list) -> None:
        try:
            path = license_file_path()
            data = {}
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["sites_seen"] = sites_seen
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def check_license_scope(config: dict | None = None) -> tuple:
        """چکِ محدودیتِ «تعدادِ سایت» و «پلتفرمِ مجاز» — جدا از اعتبارِ خودِ
        امضا/انقضای لایسنس (که validate_key چک می‌کنه). این مقادیر داخلِ
        payloadِ امضاشده هستن، پس قابلِ دستکاری از بیرون نیستن. خروجی:
        (ok, پیامِ فارسیِ توضیح در صورتِ رد شدن)."""
        if LICENSE_BYPASS:
            return True, ""

        key = LicenseTab._load_license_key()
        if not key:
            return True, ""

        payload = LicenseTab.parse_license_payload(key)
        if not payload:
            return True, ""

        config = config if config is not None else (load_secure_config(None) or {})

        allowed_platform = str(payload.get("p") or "both").strip().lower()
        if allowed_platform in ("wc", "ps"):
            from sync_app.core.integrations.commerce_provider import (
                is_prestashop,
                store_platform_label,
            )

            current_is_ps = is_prestashop(config)
            if allowed_platform == "wc" and current_is_ps:
                return False, (
                    "لایسنسِ شما فقط برای ووکامرس صادر شده — برای استفاده با "
                    f"{store_platform_label(config)} باید لایسنسِ «هر دو پلتفرم» تهیه کنید."
                )
            if allowed_platform == "ps" and not current_is_ps:
                return False, (
                    "لایسنسِ شما فقط برای پرستاشاپ صادر شده — برای استفاده با "
                    f"{store_platform_label(config)} باید لایسنسِ «هر دو پلتفرم» تهیه کنید."
                )

        max_sites = int(payload.get("s") or 0)
        if max_sites > 0:
            site_url = LicenseTab._current_site_url(config)
            if site_url:
                fingerprint = LicenseTab._site_fingerprint(site_url)
                sites_seen = LicenseTab._load_sites_seen()
                if fingerprint not in sites_seen:
                    if len(sites_seen) >= max_sites:
                        return False, (
                            f"لایسنسِ شما فقط برای {max_sites} سایت معتبر است و سهمیه‌اش قبلاً "
                            "برای سایت‌های دیگری استفاده شده — برای این سایتِ جدید به لایسنسِ "
                            "چندسایتی نیاز دارید."
                        )
                    sites_seen.append(fingerprint)
                    LicenseTab._save_sites_seen(sites_seen)

        return True, ""

    @staticmethod
    def parse_license_payload(key: str) -> dict:
        if not key:
            return {}
        if "." in key:
            try:
                payload_b64, _sig = key.split(".", 1)
                return json.loads(LicenseTab._urlsafe_b64decode_padded(payload_b64))
            except Exception:
                return {}
        try:
            decoded = base64.b64decode(key).decode("utf-8")
            lic_hwid, lic_expiry = decoded.split("|", 1)
            return {"v": 1, "h": lic_hwid, "e": lic_expiry.strip()}
        except Exception:
            return {}

    @staticmethod
    def parse_expiry_date(key: str):
        payload = LicenseTab.parse_license_payload(key)
        expiry_text = payload.get("e")
        if not expiry_text:
            return None
        try:
            return datetime.strptime(str(expiry_text), "%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def parse_issued_date(key: str):
        payload = LicenseTab.parse_license_payload(key)
        issued_text = payload.get("i")
        if not issued_text:
            return None
        try:
            return datetime.strptime(str(issued_text), "%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def format_date_jalali(dt: datetime) -> str:
        from sync_app.core.jalali_log_formatter import gregorian_to_jalali

        jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
        raw = f"{jy:04d}/{jm:02d}/{jd:02d}"
        return raw.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    @staticmethod
    def _mask_license_key(key: str) -> str:
        key = (key or "").strip()
        if not key:
            return "—"
        if len(key) <= 20:
            return key[:6] + "…" + key[-4:]
        return key[:10] + "…" + key[-8:]

    @staticmethod
    def _display_expiry(key: str, remote_cache: dict) -> datetime | None:
        server_expires = remote_cache.get("license_expires")
        if remote_cache.get("server_registered") and server_expires:
            try:
                return datetime.strptime(str(server_expires), "%Y-%m-%d")
            except ValueError:
                pass
        expiry = LicenseTab.parse_expiry_date(key)
        if expiry is not None:
            return expiry
        if server_expires:
            try:
                return datetime.strptime(str(server_expires), "%Y-%m-%d")
            except ValueError:
                pass
        return None

    @staticmethod
    def get_license_details(hwid: str | None = None) -> dict:
        hwid = hwid or LicenseTab.get_hwid()
        key = LicenseTab._load_license_key()
        payload = LicenseTab.parse_license_payload(key)
        today = datetime.now().date()

        if LICENSE_BYPASS:
            return {
                "status": "active",
                "status_label": "فعال (حالت توسعه)",
                "hero_title": "لایسنس فعال",
                "hero_subtitle": "حالت bypass برای توسعه فعال است.",
                "hwid": hwid,
                "key_masked": "—",
                "version_label": "—",
                "issued_jalali": "—",
                "issued_gregorian": "—",
                "expiry_jalali": "—",
                "expiry_gregorian": "—",
                "days_left": None,
                "days_total": None,
                "progress_pct": 100,
                "show_progress": False,
            }

        if not key:
            return {
                "status": "missing",
                "status_label": "ثبت نشده",
                "hero_title": "لایسنس ثبت نشده",
                "hero_subtitle": "برای استفاده از برنامه، کلید فعال‌سازی را وارد کنید.",
                "hwid": hwid,
                "key_masked": "—",
                "version_label": "—",
                "issued_jalali": "—",
                "issued_gregorian": "—",
                "expiry_jalali": "—",
                "expiry_gregorian": "—",
                "days_left": None,
                "days_total": None,
                "progress_pct": 0,
                "show_progress": False,
                "server_plugin": "—",
                "server_sync": "—",
            }

        remote_cache = {}
        try:
            license_file = license_file_path()
            if os.path.exists(license_file):
                with open(license_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw.get("remote_cache"), dict):
                    remote_cache = raw["remote_cache"]
        except Exception:
            remote_cache = {}

        bound_hwid = str(payload.get("h") or remote_cache.get("hwid") or "").strip()
        expiry = LicenseTab._display_expiry(key, remote_cache)
        issued = LicenseTab.parse_issued_date(key)
        version = payload.get("v", 1)
        version_label = f"v{version}" if version else "v1"
        key_masked = LicenseTab._mask_license_key(key)

        expiry_jalali = LicenseTab.format_date_jalali(expiry) if expiry else "—"
        expiry_gregorian = expiry.strftime("%Y-%m-%d") if expiry else "—"
        issued_jalali = LicenseTab.format_date_jalali(issued) if issued else "—"
        issued_gregorian = issued.strftime("%Y-%m-%d") if issued else "—"

        days_left = None
        days_total = None
        progress_pct = 0
        if expiry is not None:
            days_left = (expiry.date() - today).days
            if issued is not None:
                days_total = max(1, (expiry.date() - issued.date()).days)
                progress_pct = int(min(100, max(0, (max(days_left, 0) / days_total) * 100)))
            elif days_left is not None and days_left >= 0:
                progress_pct = min(100, max(8, days_left))

        if str(remote_cache.get("status") or "").lower() == "revoked":
            return {
                "status": "revoked",
                "status_label": "باطل شده",
                "hero_title": "لایسنس باطل شده",
                "hero_subtitle": "لایسنس شما باطل شده است. با سایت peecha.ir تماس بگیرید.",
                "hwid": hwid,
                "key_masked": key_masked,
                "version_label": version_label,
                "issued_jalali": issued_jalali,
                "issued_gregorian": issued_gregorian,
                "expiry_jalali": expiry_jalali,
                "expiry_gregorian": expiry_gregorian,
                "days_left": days_left,
                "days_total": days_total,
                "progress_pct": 0,
                "show_progress": False,
                "server_plugin": str(remote_cache.get("server_plugin_version") or "—"),
                "server_sync": str(remote_cache.get("validated_at") or "—").replace("T", " ")[:16],
            }

        if str(remote_cache.get("status") or "").lower() == "expired":
            return {
                "status": "expired",
                "status_label": "منقضی / باطل در سرور",
                "hero_title": "لایسنس در سرور معتبر نیست",
                "hero_subtitle": "لایسنس در peecha.ir منقضی یا باطل شده است. با سایت peecha.ir تماس بگیرید.",
                "hwid": hwid,
                "key_masked": key_masked,
                "version_label": version_label,
                "issued_jalali": issued_jalali,
                "issued_gregorian": issued_gregorian,
                "expiry_jalali": expiry_jalali,
                "expiry_gregorian": expiry_gregorian,
                "days_left": days_left,
                "days_total": days_total,
                "progress_pct": 0,
                "show_progress": False,
                "server_plugin": str(remote_cache.get("server_plugin_version") or "—"),
                "server_sync": str(remote_cache.get("validated_at") or "—").replace("T", " ")[:16],
            }

        days_left = None
        days_total = None
        progress_pct = 0
        if expiry is not None:
            days_left = (expiry.date() - today).days
            if issued is not None:
                days_total = max(1, (expiry.date() - issued.date()).days)
                progress_pct = int(min(100, max(0, (max(days_left, 0) / days_total) * 100)))
            elif days_left is not None and days_left >= 0:
                progress_pct = min(100, max(8, days_left))

        valid_now = LicenseTab.validate_key(key, hwid)
        if not valid_now and remote_cache:
            from sync_app.core.license_remote import remote_cache_license_valid

            valid_now = remote_cache_license_valid(remote_cache, hwid)
        if bound_hwid and bound_hwid != hwid:
            status = "invalid"
            status_label = "نامعتبر — دستگاه دیگر"
            hero_title = "لایسنس برای این دستگاه نیست"
            hero_subtitle = "کلید فعال‌سازی به شناسه سخت‌افزاری دیگری صادر شده است."
        elif not valid_now and key and expiry is not None and days_left is not None and days_left < 0:
            status = "expired"
            status_label = "منقضی شده"
            hero_title = "لایسنس منقضی شده"
            hero_subtitle = f"اعتبار در تاریخ {expiry_jalali} به پایان رسیده است."
            progress_pct = 0
        elif not valid_now:
            status = "invalid"
            status_label = "نامعتبر"
            hero_title = "لایسنس نامعتبر"
            hero_subtitle = "امضای کلید تأیید نشد یا فرمت آن اشتباه است."
        elif expiry is None:
            status = "invalid"
            status_label = "نامعتبر"
            hero_title = "لایسنس نامعتبر"
            hero_subtitle = "تاریخ انقضا در کلید یافت نشد."
        elif days_left is not None and days_left <= 30:
            status = "warning"
            status_label = "فعال — نزدیک انقضا"
            hero_title = "لایسنس فعال"
            hero_subtitle = f"{days_left} روز تا پایان اعتبار باقی مانده — تمدید را در نظر بگیرید."
        else:
            status = "active"
            status_label = "فعال"
            hero_title = "لایسنس فعال و معتبر"
            hero_subtitle = "همه سرویس‌های پیچا برای این دستگاه در دسترس هستند."

        server_plugin = str(remote_cache.get("server_plugin_version") or "—")
        validated = str(remote_cache.get("validated_at") or "").strip()
        if remote_cache.get("server_registered") and validated:
            server_sync = validated.replace("T", " ")[:16]
        else:
            server_sync = "—"

        return {
            "status": status,
            "status_label": status_label,
            "hero_title": hero_title,
            "hero_subtitle": hero_subtitle,
            "hwid": hwid,
            "key_masked": key_masked,
            "version_label": version_label,
            "issued_jalali": issued_jalali,
            "issued_gregorian": issued_gregorian,
            "expiry_jalali": expiry_jalali,
            "expiry_gregorian": expiry_gregorian,
            "days_left": days_left,
            "days_total": days_total,
            "progress_pct": progress_pct,
            "show_progress": status in ("active", "warning", "expired") and expiry is not None,
            "server_plugin": server_plugin,
            "server_sync": server_sync,
        }

    @staticmethod
    def get_license_expiry_header() -> tuple[str, bool, int | None]:
        details = LicenseTab.get_license_details()
        if details["status"] == "revoked":
            return "لایسنس باطل شده", True, None
        if details["status"] == "expired":
            return "لایسنس منقضی شده", True, details.get("days_left")
        if details["status"] == "missing" or details["expiry_jalali"] == "—":
            return "", False, None
        jalali = details["expiry_jalali"]
        days_left = details["days_left"]
        if details["status"] == "expired":
            return f"اعتبار: {jalali} (منقضی)", True, days_left
        return f"اعتبار تا {jalali}", False, days_left

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("licenseScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 16)
        content_layout.setSpacing(16)

        self.status_hero = QFrame()
        self.status_hero.setObjectName("licenseStatusHero")
        hero_layout = QVBoxLayout(self.status_hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(10)

        pill_row = QHBoxLayout()
        pill_row.addStretch(1)
        self.status_pill = QLabel()
        self.status_pill.setObjectName("licenseStatusPill")
        pill_row.addWidget(self.status_pill, 0, Qt.AlignRight)
        hero_layout.addLayout(pill_row)

        self.hero_title = QLabel()
        self.hero_title.setObjectName("licenseHeroTitle")
        set_rtl_label_text(self.hero_title, "")
        hero_layout.addWidget(self.hero_title)

        self.hero_subtitle = QLabel()
        self.hero_subtitle.setObjectName("licenseHeroSubtitle")
        self.hero_subtitle.setWordWrap(True)
        set_rtl_label_text(self.hero_subtitle, "")
        hero_layout.addWidget(self.hero_subtitle)

        self.validity_bar = QProgressBar()
        self.validity_bar.setObjectName("licenseValidityBar")
        self.validity_bar.setTextVisible(False)
        self.validity_bar.setRange(0, 100)
        hero_layout.addWidget(self.validity_bar)

        content_layout.addWidget(self.status_hero)

        info_title = QLabel("جزئیات لایسنس")
        info_title.setObjectName("licenseSectionTitle")
        content_layout.addWidget(info_title)

        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(12)
        info_grid.setVerticalSpacing(12)
        tiles = [
            ("status", "وضعیت"),
            ("days_left", "روزهای باقی‌مانده"),
            ("expiry_jalali", "تاریخ پایان (شمسی)"),
            ("expiry_gregorian", "تاریخ پایان (میلادی)"),
            ("issued_jalali", "تاریخ فعال‌سازی (شمسی)"),
            ("issued_gregorian", "تاریخ فعال‌سازی (میلادی)"),
            ("version_label", "نسخه لایسنس"),
            ("hwid", "شناسه دستگاه"),
            ("key_masked", "اثرانگشت کلید"),
            ("server_plugin", "نسخه افزونه سرور"),
            ("server_sync", "آخرین ثبت در سرور"),
        ]
        for idx, (key, caption) in enumerate(tiles):
            tile = self._make_info_tile(caption)
            row, col = divmod(idx, 3)
            info_grid.addWidget(tile, row, col)
            self._info_value_labels[key] = tile.findChild(QLabel, "licenseInfoValue")
        content_layout.addLayout(info_grid)

        activation_card = QFrame()
        activation_card.setObjectName("licenseActivationCard")
        activation_layout = QVBoxLayout(activation_card)
        activation_layout.setContentsMargins(20, 18, 20, 18)
        activation_layout.setSpacing(12)

        act_title = QLabel("فعال‌سازی / تمدید")
        act_title.setObjectName("licenseSectionTitle")
        activation_layout.addWidget(act_title)

        hwid_caption = QLabel("شناسه سخت‌افزاری این دستگاه")
        hwid_caption.setObjectName("licenseInfoCaption")
        activation_layout.addWidget(hwid_caption)

        hwid_row = QHBoxLayout()
        self.hwid_display = QLineEdit(self.hwid)
        self.hwid_display.setObjectName("licenseHwidDisplay")
        self.hwid_display.setReadOnly(True)
        hwid_row.addWidget(self.hwid_display, 1)
        copy_btn = QPushButton("کپی")
        copy_btn.setObjectName("licenseCopyHwidBtn")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_hwid)
        hwid_row.addWidget(copy_btn)
        activation_layout.addLayout(hwid_row)

        key_caption = QLabel("کلید فعال‌سازی")
        key_caption.setObjectName("licenseInfoCaption")
        activation_layout.addWidget(key_caption)

        self.license_input = QLineEdit()
        self.license_input.setObjectName("licenseKeyInput")
        self.license_input.setPlaceholderText("کلید لایسنس را اینجا وارد کنید…")
        activation_layout.addWidget(self.license_input)

        self.btn_activate = QPushButton("فعال‌سازی و ورود به برنامه")
        self.btn_activate.setObjectName("licenseActivateBtn")
        self.btn_activate.setMinimumHeight(46)
        self.btn_activate.setCursor(Qt.PointingHandCursor)
        self.btn_activate.clicked.connect(self.activate_now)
        activation_layout.addWidget(self.btn_activate)

        self.btn_register_server = QPushButton("ثبت در لیست peecha.ir")
        self.btn_register_server.setObjectName("licenseUpdateBtn")
        self.btn_register_server.setMinimumHeight(40)
        self.btn_register_server.setCursor(Qt.PointingHandCursor)
        self.btn_register_server.clicked.connect(self.register_on_server)
        activation_layout.addWidget(self.btn_register_server)

        self.btn_check_update = QPushButton("بررسی بروزرسانی")
        self.btn_check_update.setObjectName("licenseUpdateBtn")
        self.btn_check_update.setMinimumHeight(40)
        self.btn_check_update.setCursor(Qt.PointingHandCursor)
        self.btn_check_update.clicked.connect(self.check_for_updates)
        activation_layout.addWidget(self.btn_check_update)

        self._unlock_btn = QPushButton("🔓 ویرایش لایسنس فعال")
        self._unlock_btn.setObjectName("devUnlockBtn")
        self._unlock_btn.setMinimumHeight(40)
        self._unlock_btn.setCursor(Qt.PointingHandCursor)
        self._unlock_btn.clicked.connect(self._toggle_dev_lock)
        self._unlock_btn.setVisible(False)  # فقط وقتی لایسنس از قبل فعاله نشون داده می‌شه
        activation_layout.addWidget(self._unlock_btn)

        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self._dev_unlock_shortcut = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self._dev_unlock_shortcut.activated.connect(self._toggle_dev_lock)
        self._dev_locked = None  # هنوز تعیین نشده — بعد از اولین refresh_license_display مشخص می‌شه

        content_layout.addWidget(activation_card)
        content_layout.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll)

    def _make_info_tile(self, caption: str) -> QFrame:
        tile = QFrame()
        tile.setObjectName("licenseInfoTile")
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        cap = QLabel(caption)
        cap.setObjectName("licenseInfoCaption")
        val = QLabel("—")
        val.setObjectName("licenseInfoValue")
        val.setWordWrap(True)
        layout.addWidget(cap)
        layout.addWidget(val)
        return tile

    def _set_widget_status(self, widget, status: str) -> None:
        widget.setProperty("licenseStatus", status)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _apply_dev_lock_ui(self):
        from sync_app.core.dev_lock import apply_lock_state

        apply_lock_state(
            self, self._dev_locked,
            exclude_names={"devUnlockBtn", "licenseUpdateBtn"},
        )
        self._unlock_btn.setVisible(bool(self._dev_locked) or self._was_locked_once)
        self._unlock_btn.setText("🔓 ویرایش لایسنس فعال" if self._dev_locked else "🔒 قفل کردن دوباره")
        self._unlock_btn.setEnabled(True)
        self.btn_check_update.setEnabled(True)

    def _toggle_dev_lock(self):
        from sync_app.core.dev_lock import prompt_unlock

        self._was_locked_once = True
        if not self._dev_locked:
            self._dev_locked = True
            self._apply_dev_lock_ui()
            return
        if prompt_unlock(self):
            self._dev_locked = False
            self._apply_dev_lock_ui()

    def refresh_license_display(self) -> None:
        details = self.get_license_details(self.hwid)
        status = details["status"]

        if self._dev_locked is None:
            # اولین بار: فقط اگه لایسنس از قبل فعال و معتبره قفل کن — تا
            # مشتری تازه بتونه بدون هیچ مانعی اولین‌بار فعال‌سازی کنه.
            self._dev_locked = (status == "active")
            self._apply_dev_lock_ui()

        self._set_widget_status(self.status_hero, status)
        self._set_widget_status(self.status_pill, status)
        self.status_pill.setText(details["status_label"])
        set_rtl_label_text(self.hero_title, details["hero_title"])
        set_rtl_label_text(self.hero_subtitle, details["hero_subtitle"], multiline=True)

        self.validity_bar.setVisible(bool(details["show_progress"]))
        self.validity_bar.setValue(int(details["progress_pct"] or 0))

        days_text = "—"
        if details["days_left"] is not None:
            if details["days_left"] < 0:
                days_text = f"{abs(details['days_left'])} روز گذشته"
            else:
                days_text = f"{details['days_left']} روز"
        display = {**details, "days_left": days_text}

        for key, label in self._info_value_labels.items():
            if label is None:
                continue
            value = str(display.get(key, "—"))
            set_rtl_label_text(label, value)

        self._notify_header_refresh()

    def _copy_hwid(self) -> None:
        QApplication.clipboard().setText(self.hwid)
        QMessageBox.information(self, "کپی شد", "شناسه دستگاه در کلیپ‌بورد کپی شد.")

    def _notify_header_refresh(self) -> None:
        widget = self.parent()
        while widget is not None:
            refresh = getattr(widget, "_refresh_header_license_expiry", None)
            if callable(refresh):
                refresh()
                return
            widget = widget.parent()

    def activate_now(self):
        key = self.license_input.text().strip()
        if not key:
            QMessageBox.warning(self, "خطا", "کلید لایسنس را وارد کنید.")
            return

        from sync_app.core.license_remote import (
            apply_server_license_denial,
            humanize_license_error,
            is_revoked_error,
            merge_remote_cache,
            try_online_validate,
        )

        ok_remote, lic, err_remote = try_online_validate(key, self.hwid, activate=True)
        if ok_remote:
            merge_remote_cache(key, lic, self.hwid)
            self.refresh_license_display()
            launcher = LicenseTab.find_launcher(self)
            if launcher is not None and hasattr(launcher, "_clear_license_renewal_lock"):
                launcher._clear_license_renewal_lock()
            QMessageBox.information(self, "موفق", "لایسنس با سرور فعال شد و برنامه آماده است.")
            if callable(self._on_activated):
                self._on_activated()
                self.close()
            return

        denied = apply_server_license_denial(
            self.hwid,
            err_remote,
            lic if isinstance(lic, dict) else {},
        )
        if denied or is_revoked_error(err_remote, lic if isinstance(lic, dict) else {}):
            self.refresh_license_display()
            QMessageBox.critical(
                self,
                "لایسنس باطل شده" if denied == "revoked" else "لایسنس نامعتبر",
                humanize_license_error(denied or err_remote),
            )
            return

        try:
            if self.validate_key(key, self.hwid):
                with open(license_file_path(), "w", encoding="utf-8") as f:
                    json.dump({"license_key": key}, f)

                self.refresh_license_display()
                hint = ""
                if err_remote:
                    hint = f"\n\nاتصال به سرور لایسنس برقرار نشد ({err_remote})؛ اعتبارسنجی آفلاین انجام شد."
                QMessageBox.information(self, "موفق", f"برنامه با موفقیت فعال شد.{hint}")

                if callable(self._on_activated):
                    self._on_activated()
                    self.close()
            else:
                self.refresh_license_display()
                detail = f"\n\nسرور: {err_remote}" if err_remote else ""
                QMessageBox.critical(self, "خطا", f"این لایسنس برای این دستگاه معتبر نیست.{detail}")
        except Exception:
            QMessageBox.critical(self, "خطا", "فرمت لایسنس اشتباه است.")

    def register_on_server(self):
        from sync_app.core.license_remote import (
            humanize_license_error,
            load_license_file,
            register_license_with_server,
        )

        key = self._load_license_key() or self.license_input.text().strip()
        if not key:
            QMessageBox.warning(self, "لایسنس", "کلید لایسنس یافت نشد.")
            return

        ok, _lic, err = register_license_with_server(key, self.hwid, config=load_secure_config_after_profile())
        self.refresh_license_display()
        if ok:
            launcher = LicenseTab.find_launcher(self)
            if launcher is not None and hasattr(launcher, "_clear_license_renewal_lock"):
                launcher._clear_license_renewal_lock()
            cache = load_license_file().get("remote_cache") or {}
            ver = str(cache.get("server_plugin_version") or "—")
            QMessageBox.information(
                self,
                "ثبت شد",
                f"این دستگاه در peecha.ir ثبت شد.\n"
                f"نسخه افزونه سرور: {ver}\n"
                f"در wp-admin جستجو کنید: {self.hwid}",
            )
            return

        if err and err.startswith("server_plugin_old:"):
            ver = err.split(":", 1)[-1]
            QMessageBox.warning(
                self,
                "افزونه سرور قدیمی",
                f"افزونه peecha.ir هنوز {ver} است (باید 1.0.31 باشد).\n"
                "tools\\Run_Deploy_WP_LicensePlugin.bat را بزنید و صفحه wp-admin را رفرش کنید.",
            )
            return

        human = humanize_license_error(err)
        if err == "revoked":
            QMessageBox.critical(
                self,
                "لایسنس باطل شده",
                "لایسنس شما باطل شده است.\n\nبا سایت peecha.ir تماس بگیرید.",
            )
            return
        if err == "api_key_missing" or "api key" in (err or "").lower() or "forbidden" in (err or "").lower():
            human = (
                "کلید API در تنظیمات برنامه با wp-admin یکی نیست.\n"
                "تنظیمات -> کلید API لایسنس را از wp-admin کپی کنید و ذخیره کنید."
            )
        QMessageBox.warning(self, "ثبت ناموفق", human)

    def check_for_updates(self):
        from sync_app.core.update_ui import (
            humanize_update_error,
            prompt_and_run_update,
            run_update_check,
        )

        if not self.is_license_valid():
            QMessageBox.warning(self, "بروزرسانی", "ابتدا لایسنس را فعال کنید.")
            return

        ok, info, err = run_update_check(self, self.hwid)
        if not ok:
            QMessageBox.warning(self, "بروزرسانی", humanize_update_error(err))
            return

        self.refresh_license_display()
        launcher = LicenseTab.find_launcher(self)
        if launcher is not None:
            if hasattr(launcher, "_refresh_header_license_expiry"):
                launcher._refresh_header_license_expiry()
            if not LicenseTab.is_license_server_denied() and hasattr(launcher, "_clear_license_renewal_lock"):
                launcher._clear_license_renewal_lock()

        prompt_and_run_update(self, info, self.hwid)

    def check_license_status(self):
        from sync_app.core.license_remote import (
            refresh_denied_license_if_needed,
            register_license_with_server,
        )

        key = self._load_license_key()
        if not key:
            self.refresh_license_display()
            return

        if LicenseTab.is_license_server_denied():
            refresh_denied_license_if_needed()
        register_license_with_server(key, self.hwid, config=load_secure_config_after_profile())

        self.refresh_license_display()
        launcher = LicenseTab.find_launcher(self)
        if launcher is not None and hasattr(launcher, "_clear_license_renewal_lock"):
            if not LicenseTab.is_license_server_denied():
                launcher._clear_license_renewal_lock()

    def showEvent(self, event):
        super().showEvent(event)
        if LicenseTab.is_license_server_denied():
            from sync_app.core.license_remote import refresh_denied_license_if_needed

            if refresh_denied_license_if_needed():
                self.refresh_license_display()
                launcher = LicenseTab.find_launcher(self)
                if launcher is not None and hasattr(launcher, "_clear_license_renewal_lock"):
                    launcher._clear_license_renewal_lock()

    def check_license(self):
        self.check_license_status()
