"""سرورِ محلیِ دریافتِ عکس از برنامه‌ی همراهِ موبایل (PWA) — رویِ شبکه‌ی
محلی/وای‌فایِ مشترک با کامپیوترِ پیچا کار می‌کنه، بدونِ نیاز به اینترنت.

عکس‌ها به‌صورتِ multipart/form-data به /upload ارسال می‌شن (با یه توکنِ
اشتراکی برایِ احرازِ هویتِ ساده)، تویِ پوشه‌ی «صندوقِ ورودی» ذخیره می‌شن،
و از اون‌جا با نامِ فایل (که کدِ کالا توش هست) به تب محصولات وصل می‌شن."""

from __future__ import annotations

import http.server
import json
import os
import re
import secrets
import socket
import socketserver
import threading
import time

MOBILE_PHOTO_SERVER_ENABLED_KEY = "MOBILE_PHOTO_SERVER_ENABLED"
MOBILE_PHOTO_SERVER_PORT_KEY = "MOBILE_PHOTO_SERVER_PORT"
MOBILE_PHOTO_SERVER_TOKEN_KEY = "MOBILE_PHOTO_SERVER_TOKEN"
DEFAULT_PORT = 8765
INBOX_SUBDIR = "incoming_mobile_photos"
MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # ۳۰ مگابایت — کافی برایِ یه عکسِ موبایلِ ادیت‌شده


def get_or_create_token(config: dict | None = None) -> str:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = config if config is not None else (load_secure_config(None) or {})
    token = str(cfg.get(MOBILE_PHOTO_SERVER_TOKEN_KEY) or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(18)
    cfg[MOBILE_PHOTO_SERVER_TOKEN_KEY] = token
    save_secure_config(cfg)
    return token


def regenerate_token() -> str:
    from sync_app.core.secure_config_loader import load_secure_config, save_secure_config

    cfg = load_secure_config(None) or {}
    token = secrets.token_urlsafe(18)
    cfg[MOBILE_PHOTO_SERVER_TOKEN_KEY] = token
    save_secure_config(cfg)
    return token


def local_lan_ip() -> str:
    """آی‌پیِ کامپیوتر رویِ شبکه‌ی محلی — برایِ نمایش به کاربر تا تویِ PWA
    وارد کنه. اتصالِ UDP واقعاً برقرار نمی‌شه (فقط مسیریابیِ سیستم‌عامل
    استفاده می‌شه)، پس نیازی به اینترنتِ واقعی نیست."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def inbox_dir() -> str:
    from sync_app.core.sync_utils import app_path

    path = app_path(INBOX_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
}


def _guess_content_type(path: str) -> str:
    _, ext = os.path.splitext(path)
    return _CONTENT_TYPES.get(ext.lower(), "application/octet-stream")


def _pwa_dir() -> str:
    """پوشه‌ی فایل‌هایِ استاتیکِ اپِ همراهِ موبایل (mobile_pwa) — کنارِ همین
    فایل، هم تویِ حالتِ توسعه هم تویِ بستهٔ نهایی (resource_path)."""
    try:
        from sync_app.core.sync_utils import resource_path

        path = resource_path("mobile_pwa")
        return path if os.path.isdir(path) else ""
    except Exception:
        return ""


def _safe_filename(name: str) -> str:
    name = os.path.basename((name or "").strip().replace("\\", "/"))
    name = re.sub(r"[^A-Za-z0-9_.\-؀-ۿ ]", "_", name).strip()
    return name or f"photo_{int(time.time())}.jpg"


def _unique_path(directory: str, filename: str) -> str:
    base, ext = os.path.splitext(filename)
    candidate = filename
    n = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}_{n}{ext}"
        n += 1
    return os.path.join(directory, candidate)


def _parse_multipart(body: bytes, boundary: bytes) -> list[dict]:
    """پارسِ سبکِ multipart/form-data — فقط بخش‌هایی که filename دارن
    (یعنی فایل‌ها، نه فیلدهایِ متنیِ ساده) برگردونده می‌شن."""
    parts = body.split(b"--" + boundary)
    files = []
    for part in parts:
        part = part.strip(b"\r\n")
        if not part or part in (b"", b"--"):
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        if content.endswith(b"\r\n"):
            content = content[:-2]
        headers = header_blob.decode("utf-8", errors="replace")
        if "filename=" not in headers:
            continue
        m = re.search(r'filename="([^"]*)"', headers)
        filename = m.group(1) if m else ""
        files.append({"filename": filename, "content": content})
    return files


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # لاگِ پیش‌فرضِ http.server رو خاموش می‌کنیم؛ لاگِ خودمون رو جدا می‌نویسیم

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _current_token(self) -> str:
        return get_or_create_token()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/ping" or path.startswith("/ping"):
            self._json(200, {"status": "ok", "app": "PeechaSync"})
            return
        if path == "/config" or path.startswith("/config"):
            self._json(200, {"token": self._current_token()})
            return
        if self._serve_static(path):
            return
        self._json(404, {"error": "not found"})

    def _serve_static(self, path: str) -> bool:
        """پوسته‌ی PWA (index.html/app.js/style.css/manifest/آیکون‌ها) رو
        از پوشه‌ی همراه سرو می‌کنه — تا کاربر فقط با بازکردنِ آدرسِ سرور تویِ
        مرورگرِ موبایل، بدونِ نصب/آپلودِ جداگانه، اپ رو بگیره."""
        pwa_dir = _pwa_dir()
        if not pwa_dir:
            return False

        rel = path.lstrip("/") or "index.html"
        target = os.path.normpath(os.path.join(pwa_dir, rel))
        # جلوگیری از path traversal (../..) به بیرونِ پوشه‌ی PWA
        if not (target == pwa_dir or target.startswith(pwa_dir + os.sep)):
            return False
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        if not os.path.isfile(target):
            return False

        content_type = _guess_content_type(target)
        try:
            with open(target, "rb") as f:
                data = f.read()
        except OSError:
            return False

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return True

    def do_POST(self):
        if not self.path.startswith("/upload"):
            self._json(404, {"error": "not found"})
            return

        auth = self.headers.get("Authorization", "")
        given = auth[7:].strip() if auth.startswith("Bearer ") else ""
        if not given:
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            given = (qs.get("token") or [""])[0]
        if not given or given != self._current_token():
            self._json(401, {"error": "unauthorized"})
            return

        content_type = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=(.+)", content_type)
        if "multipart/form-data" not in content_type or not m:
            self._json(400, {"error": "expected multipart/form-data"})
            return
        boundary = m.group(1).strip().strip('"').encode("utf-8")

        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self._json(413, {"error": "payload too large or empty"})
            return

        body = self.rfile.read(length)
        files = _parse_multipart(body, boundary)
        if not files:
            self._json(400, {"error": "no file in request"})
            return

        saved = []
        directory = inbox_dir()
        for f in files:
            filename = _safe_filename(f["filename"])
            dest = _unique_path(directory, filename)
            with open(dest, "wb") as out:
                out.write(f["content"])
            saved.append(os.path.basename(dest))

        try:
            from sync_app.core.sync_utils import log

            log.info(f"📸 عکسِ موبایل دریافت شد: {', '.join(saved)}")
        except Exception:
            pass

        self._json(200, {"status": "ok", "saved": saved})


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


_server_instance: _ThreadingServer | None = None
_server_thread: threading.Thread | None = None
_server_lock = threading.Lock()


def is_running() -> bool:
    return _server_instance is not None


def start_server(port: int | None = None) -> tuple[bool, str]:
    global _server_instance, _server_thread
    with _server_lock:
        if _server_instance is not None:
            return True, "از قبل در حال اجراست"
        from sync_app.core.secure_config_loader import load_secure_config

        cfg = load_secure_config(None) or {}
        p = int(port or cfg.get(MOBILE_PHOTO_SERVER_PORT_KEY) or DEFAULT_PORT)
        try:
            server = _ThreadingServer(("0.0.0.0", p), _Handler)
        except OSError as exc:
            return False, f"پورتِ {p} در دسترس نیست: {exc}"
        _server_instance = server
        thread = threading.Thread(target=server.serve_forever, daemon=True, name="PeechaMobilePhotoServer")
        _server_thread = thread
        thread.start()
        return True, f"سرور رویِ پورتِ {p} شروع شد"


def stop_server() -> None:
    global _server_instance, _server_thread
    with _server_lock:
        if _server_instance is not None:
            try:
                _server_instance.shutdown()
                _server_instance.server_close()
            except Exception:
                pass
            _server_instance = None
        _server_thread = None
