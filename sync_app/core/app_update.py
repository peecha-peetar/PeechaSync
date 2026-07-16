"""App update check and download for PeechaSync."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from typing import Any

import requests

from sync_app.core.app_version import APP_VERSION
from sync_app.core.license_remote import (
    _api_headers,
    check_updates,
    license_api_key,
    license_server_url,
    license_site_url,
    load_license_file,
    merge_remote_cache,
)

_session: requests.Session | None = None

UPDATE_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "DATA3",
    "node_modules",
    ".idea",
    ".vscode",
    ".cursor",
}

UPDATE_SKIP_FILES = {
    "license.json",
    "secure_config.bin",
    "secure_config.json",
    "sync_key.key",
    "product_woo_map.json",
    "category_map.json",
    "category_images_map.json",
    "product_images_map.json",
}


def _http() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": f"PeechaSync/{APP_VERSION}"})
    return _session


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for piece in (version or "").strip().split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0])


def is_newer_version(latest: str, current: str | None = None) -> bool:
    return _version_tuple(latest) > _version_tuple(current or APP_VERSION)


def client_updates_allowed(config: dict | None = None) -> bool:
    data = load_license_file()
    cache = data.get("remote_cache") if isinstance(data.get("remote_cache"), dict) else {}
    if "updates_allowed" in cache:
        return bool(cache.get("updates_allowed"))

    until = cache.get("updates_until") or cache.get("license_expires")
    if not until:
        return True
    try:
        return datetime.strptime(str(until), "%Y-%m-%d").date() >= datetime.now().date()
    except ValueError:
        return False


def lookup_update_info(
    *,
    license_key: str | None = None,
    hwid: str | None = None,
    current_version: str | None = None,
    config: dict | None = None,
) -> tuple[bool, dict[str, Any], str]:
    from sync_app.core.tabs.tab_license import LicenseTab

    key = (license_key or "").strip()
    device = (hwid or LicenseTab.get_hwid()).strip()
    if not key:
        data = load_license_file()
        key = str(data.get("license_key") or "").strip()
    if not key:
        return False, {}, "no_license_key"

    ok, data, err = check_updates(key, device, current_version=current_version, config=config)
    if not ok:
        return False, {}, err

    lic = data.get("license") if isinstance(data.get("license"), dict) else {}
    if lic:
        merge_remote_cache(key, lic, device)

    if data.get("reason") == "updates_not_allowed" or data.get("update_available") is False:
        lic = data.get("license") if isinstance(data.get("license"), dict) else {}
        if lic or data.get("reason") == "updates_not_allowed":
            data["update_available"] = False
    return True, data, ""


def _download_url(
    url: str,
    dest_path: str,
    *,
    params: dict | None = None,
    config: dict | None = None,
    timeout: float = 900,
    progress=None,
) -> tuple[bool, str]:
    from sync_app.core.network_route_check import host_from_url

    label = "دریافت از سرور"
    host = host_from_url(url, default="")
    if host:
        label = f"دانلود از {host}"
    try:
        if progress:
            progress(0, 0, label)
        with _http().get(
            url,
            params=params,
            headers=_api_headers(config),
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        ) as resp:
            if resp.status_code >= 400:
                return False, f"HTTP {resp.status_code}"
            total = int(resp.headers.get("content-length") or 0)
            done = 0
            with open(dest_path, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        out.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total, label)
    except requests.exceptions.Timeout:
        return False, "timeout"
    except requests.exceptions.ConnectionError:
        return False, "connection_error"
    except requests.exceptions.RequestException as exc:
        return False, str(exc)
    return True, ""


def _server_download_urls(info: dict[str, Any], config: dict | None = None) -> list[str]:
    urls: list[str] = []
    for key in ("download_url", "mirror_url"):
        url = str(info.get(key) or "").strip()
        if url and "github.com" not in url.lower() and url not in urls:
            urls.append(url)

    base = license_server_url(config).rstrip("/")
    api_url = f"{base}/wp-json/peecha/v1/updates/download"
    if api_url not in urls:
        urls.append(api_url)
    return urls


def _download_server_package(
    download_url: str,
    dest_path: str,
    *,
    license_key: str,
    hwid: str,
    config: dict | None = None,
    progress=None,
) -> tuple[bool, str]:
    params = {
        "license_key": license_key,
        "hwid": hwid,
    }
    site = license_site_url(config)
    if site:
        params["site_url"] = site
    api_key = license_api_key(config)
    if api_key:
        params["api_key"] = api_key

    if download_url.rstrip("/").endswith("/updates/download"):
        return _download_url(download_url, dest_path, params=params, config=config, progress=progress)
    return _download_url(download_url, dest_path, config=config, progress=progress)


def update_cache_dir() -> str:
    return os.path.join(tempfile.gettempdir(), "PeechaSync-updates")


def find_cached_update_zip(latest_version: str) -> str | None:
    latest = str(latest_version or "").strip()
    if not latest:
        return None
    path = os.path.join(update_cache_dir(), f"PeechaSync-{latest}.zip")
    if not os.path.isfile(path):
        return None
    try:
        if os.path.getsize(path) < 1024:
            return None
        if not zipfile.is_zipfile(path):
            return None
    except OSError:
        return None
    return path


def download_update_package(
    info: dict[str, Any],
    *,
    license_key: str | None = None,
    hwid: str | None = None,
    config: dict | None = None,
    dest_dir: str | None = None,
    progress=None,
    force_download: bool = False,
) -> tuple[bool, str, str]:
    from sync_app.core.tabs.tab_license import LicenseTab

    key = (license_key or "").strip()
    device = (hwid or LicenseTab.get_hwid()).strip()
    if not key:
        data = load_license_file()
        key = str(data.get("license_key") or "").strip()
    if not key:
        return False, "", "no_license_key"

    dest_dir = dest_dir or update_cache_dir()
    os.makedirs(dest_dir, exist_ok=True)
    latest = str(info.get("latest_version") or APP_VERSION)
    dest_path = os.path.join(dest_dir, f"PeechaSync-{latest}.zip")

    def _clear_bad_cache() -> None:
        try:
            if os.path.isfile(dest_path):
                os.remove(dest_path)
        except OSError:
            pass

    if force_download:
        _clear_bad_cache()

    if not force_download:
        cached = find_cached_update_zip(latest)
        if cached:
            if progress:
                progress(0, 0, "استفاده از بسته دانلود‌شده")
            return True, cached, "cached"

    last_err = "no_download_url"
    urls = _server_download_urls(info, config)
    if not urls:
        return False, "", "no_download_url"

    min_bytes = 100 * 1024 * 1024
    for attempt in range(2):
        if attempt > 0:
            _clear_bad_cache()
        for download_url in urls:
            if progress and attempt > 0:
                progress(0, 0, "تلاش دوباره دانلود")
            elif progress:
                progress(0, 0, "شروع دانلود از سرور")
            ok, err = _download_server_package(
                download_url,
                dest_path,
                license_key=key,
                hwid=device,
                config=config,
                progress=progress,
            )
            if not ok:
                if err:
                    last_err = err
                continue
            if not os.path.exists(dest_path):
                last_err = "download_missing"
                continue
            size = os.path.getsize(dest_path)
            if size < min_bytes:
                last_err = f"invalid_zip_size ({size // (1024 * 1024)} MB, expected ~200 MB)"
                _clear_bad_cache()
                continue
            if zipfile.is_zipfile(dest_path):
                return True, dest_path, "remote"
            last_err = f"invalid_zip ({size // (1024 * 1024)} MB — file is not a valid ZIP)"
            _clear_bad_cache()

    return False, "", last_err


def summarize_update(info: dict[str, Any]) -> str:
    latest = str(info.get("latest_version") or APP_VERSION)
    current = str(info.get("current_version") or APP_VERSION)
    if not info.get("update_available"):
        return f"نسخه فعلی ({current}) به‌روز است."
    changelog = str(info.get("changelog") or "").strip()
    if changelog:
        return f"نسخه جدید {latest} موجود است.\n\n{changelog}"
    return f"نسخه جدید {latest} موجود است. نسخه فعلی: {current}."


def update_banner_text(info: dict[str, Any]) -> str:
    latest = str(info.get("latest_version") or APP_VERSION)
    current = str(info.get("current_version") or APP_VERSION)
    return f"نسخه جدید {latest} آماده است — نسخه فعلی: {current}"


def app_install_root() -> str:
    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    loc = os.path.join(local, "PeechaSync", "install.loc")
    if os.path.isfile(loc):
        try:
            with open(loc, encoding="utf-8") as f:
                path = f.read().strip()
            if path and os.path.isdir(path):
                return os.path.normpath(path)
        except OSError:
            pass

    from sync_app.core.sync_utils import get_base_path

    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    base = get_base_path()
    project = os.path.dirname(os.path.dirname(base))
    if os.path.isfile(os.path.join(project, "main.py")):
        return project
    parent = os.path.dirname(base)
    if os.path.isdir(os.path.join(parent, "sync_app")):
        return parent
    return base


UPDATE_BOOTSTRAP_FILES = (
    "Run-PeechaSync.bat",
    "Apply-ClientUpdate.ps1",
    "Apply-CachedUpdate.bat",
    "peecha-version-refresh.ps1",
    "peecha-apply-cached-update.ps1",
    "launch-gui.ps1",
    "set-python-env.bat",
    "test-import.ps1",
    "show-startup-error.bat",
    "show-user-message.ps1",
)


def _peecha_state_dir() -> str:
    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(local, "PeechaSync")
    os.makedirs(path, exist_ok=True)
    return path


def _apply_fail_path() -> str:
    return os.path.join(_peecha_state_dir(), "update-apply-failed.json")


def _update_attempt_path() -> str:
    return os.path.join(_peecha_state_dir(), "update-apply-attempts.json")


def read_pending_update_job() -> dict | None:
    path = os.path.join(_peecha_state_dir(), "pending-update.json")
    if not os.path.isfile(path):
        return None
    try:
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def clear_pending_update_job() -> None:
    try:
        path = os.path.join(_peecha_state_dir(), "pending-update.json")
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _read_version_from_zip(zip_path: str) -> str:
    if not zip_path or not os.path.isfile(zip_path) or not zipfile.is_zipfile(zip_path):
        return ""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in ("VERSION.txt", "sync_app/core/app_version.py"):
                try:
                    text = zf.read(name).decode("utf-8", errors="replace")
                except KeyError:
                    continue
                if name == "VERSION.txt":
                    ver = text.strip()
                    if ver:
                        return ver
                for line in text.splitlines():
                    if "_BUILTIN_VERSION" in line and '"' in line:
                        part = line.split('"')
                        if len(part) >= 2:
                            return part[1].strip()
    except (OSError, zipfile.BadZipFile):
        pass
    return ""


def _bump_update_apply_attempt() -> int:
    import json

    path = _update_attempt_path()
    count = 0
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                count = int(data.get("count") or 0)
    except (OSError, ValueError, TypeError):
        count = 0
    count += 1
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"count": count, "at": datetime.now().isoformat(timespec="seconds")}, f)
    except OSError:
        pass
    return count


def reconcile_update_state_on_startup() -> None:
    """Stop OTA retry loop when apply never changes installed version."""
    job = read_pending_update_job()
    if not job:
        return
    zip_path = str(job.get("zip") or "").strip()
    if not zip_path or not os.path.isfile(zip_path):
        clear_pending_update_job()
        return
    zip_ver = _read_version_from_zip(zip_path)
    if not zip_ver or not is_newer_version(zip_ver, APP_VERSION):
        clear_pending_update_job()
        return
    attempts = _bump_update_apply_attempt()
    if attempts >= 2:
        mark_update_apply_failed(
            f"OTA apply did not update version (still {APP_VERSION}, zip {zip_ver})",
            install=app_install_root(),
        )
        clear_pending_update_job()
        _update_log(f"update loop blocked after {attempts} attempts still on {APP_VERSION}")


def read_update_apply_failure() -> dict | None:
    path = _apply_fail_path()
    if not os.path.isfile(path):
        return None
    try:
        import json

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def mark_update_apply_failed(reason: str, *, install: str = "") -> None:
    try:
        import json

        payload = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "reason": str(reason or "").strip()[:500],
            "install": os.path.normpath(install) if install else "",
        }
        with open(_apply_fail_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError:
        pass


def clear_update_apply_failed() -> None:
    try:
        path = _apply_fail_path()
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def should_block_update_apply(*, cooldown_hours: int = 24) -> tuple[bool, str]:
    data = read_update_apply_failure()
    if not data:
        return False, ""
    at_raw = str(data.get("at") or "").strip()
    if not at_raw:
        return False, ""
    try:
        failed_at = datetime.fromisoformat(at_raw)
    except ValueError:
        return False, ""
    age_hours = (datetime.now() - failed_at).total_seconds() / 3600.0
    if age_hours >= cooldown_hours:
        return False, ""
    reason = str(data.get("reason") or "").strip()
    msg = (
        "نصب خودکار بروزرسانی اخیراً ناموفق بود.\n\n"
        "برای جلوگیری از تکرار، چند ساعت آپدیت خودکار متوقف شده است.\n"
        "از Setup ZIP یا Apply-CachedUpdate.bat استفاده کنید."
    )
    if reason:
        msg += f"\n\nجزئیات: {reason}"
    return True, msg


def _update_log(msg: str) -> None:
    try:
        from datetime import datetime

        path = os.path.join(_peecha_state_dir(), "update-last.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def _write_pending_update_job(zip_path: str, install_root: str) -> None:
    try:
        import json

        job_path = os.path.join(_peecha_state_dir(), "pending-update.json")
        with open(job_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "zip": os.path.normpath(zip_path),
                    "install": os.path.normpath(install_root),
                },
                f,
                ensure_ascii=False,
            )
    except OSError:
        pass


def _bootstrap_launcher_from_zip(zip_path: str, install_root: str) -> None:
    """فایل‌های لانچر را زود از ZIP می‌کشد بیرون — حتی اگر نصب کامل بعداً گیر کند."""
    install_root = os.path.normpath(install_root)
    if not zip_path or not os.path.isfile(zip_path) or not os.path.isdir(install_root):
        return
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            for name in UPDATE_BOOTSTRAP_FILES:
                if name not in names:
                    continue
                dest = os.path.join(install_root, name)
                os.makedirs(os.path.dirname(dest) or install_root, exist_ok=True)
                with zf.open(name) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
    except Exception:
        pass


def _install_python_exe(install_root: str) -> str:
    for rel in (r".venv\Scripts\python.exe", r"python\python.exe"):
        path = os.path.join(install_root, rel)
        if os.path.isfile(path):
            return path
    return ""


def _stage_update_zip(zip_path: str, pending_dir: str) -> str:
    """کپی ZIP به پوشه pending — با retry؛ اگر قفل بود همان مسیر اصلی."""
    zip_path = os.path.normpath(zip_path)
    pending_zip = os.path.join(pending_dir, "package.zip")
    try:
        if os.path.isfile(pending_zip):
            os.remove(pending_zip)
    except OSError:
        pass
    last_err: OSError | None = None
    for attempt in range(6):
        try:
            shutil.copy2(zip_path, pending_zip)
            _update_log(f"stage zip ok -> {pending_zip}")
            return pending_zip
        except OSError as exc:
            last_err = exc
            _update_log(f"stage zip attempt {attempt + 1} failed: {exc}")
            winerr = getattr(exc, "winerror", None)
            if winerr != 32 and "being used by another process" not in str(exc).lower():
                raise
            time.sleep(1.0 + attempt * 0.5)
    if last_err:
        try:
            with open(zip_path, "rb") as src, open(pending_zip, "wb") as dst:
                shutil.copyfileobj(src, dst)
            _update_log(f"stage zip ok (stream copy) -> {pending_zip}")
            return pending_zip
        except OSError as exc:
            _update_log(f"stage zip stream copy failed: {exc}")
    _update_log(f"stage zip use source path -> {zip_path}")
    return zip_path


def _write_restart_script_from_zip(zip_path: str, install_root: str) -> str:
    install_root = os.path.normpath(install_root)
    pending = _pending_update_dir()
    pending_zip = _stage_update_zip(zip_path, pending)
    staging = os.path.join(pending, "extracted")
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)

    with zipfile.ZipFile(pending_zip, "r") as zf:
        zf.extractall(staging)
    source_root = _detect_zip_root(staging)
    bundled_apply = ""
    if source_root:
        candidate = os.path.join(source_root, "Apply-ClientUpdate.ps1")
        if os.path.isfile(candidate):
            bundled_apply = os.path.join(pending, "Apply-ClientUpdate.ps1")
            shutil.copy2(candidate, bundled_apply)

    log_dir = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "PeechaSync")
    log_path = os.path.join(log_dir, "update-last.log")
    py_exe = _install_python_exe(install_root)

    launch_bat = os.path.join(install_root, "Run-PeechaSync.bat")
    relaunch_path = os.path.join(log_dir, "relaunch.cmd")
    if os.path.isfile(launch_bat):
        with open(relaunch_path, "w", encoding="utf-8") as f:
            f.write(
                "\r\n".join(
                    [
                        "@echo off",
                        "setlocal EnableExtensions",
                        "chcp 65001 >nul",
                        "timeout /t 20 /nobreak >nul",
                        f'cd /d "{install_root}"',
                        f'call "{launch_bat}"',
                    ]
                )
                + "\r\n"
            )
        launch_cmd = f'start "" "{relaunch_path}"'
    else:
        exe_path = os.path.abspath(sys.executable)
        main_py = os.path.join(install_root, "main.py")
        with open(relaunch_path, "w", encoding="utf-8") as f:
            f.write(
                "\r\n".join(
                    [
                        "@echo off",
                        "timeout /t 20 /nobreak >nul",
                        f'cd /d "{install_root}"',
                        f'"{exe_path}" -u "{main_py}"',
                    ]
                )
                + "\r\n"
            )
        launch_cmd = f'start "" "{relaunch_path}"'

    script_path = os.path.join(tempfile.gettempdir(), "PeechaSync-apply-update.bat")
    lines = [
        "@echo off",
        "setlocal EnableExtensions",
        "chcp 65001 >nul",
        f'if not exist "{log_dir}" mkdir "{log_dir}"',
        f'echo [%date% %time%] update start > "{log_path}"',
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process pythonw,python -EA 0 | Where-Object { $_.Path -and ($_.Path -like ''*PeechaSync*'') } | Stop-Process -Force -EA 0"',
        "timeout /t 5 /nobreak >nul",
    ]

    if bundled_apply and source_root:
        lines.append(
            f'powershell -NoProfile -ExecutionPolicy Bypass -File "{bundled_apply}" '
            f'-InstallRoot "{install_root}" -SourceRoot "{source_root}" -LogPath "{log_path}" '
            f'>>"{log_path}" 2>&1'
        )
        lines.append("if errorlevel 1 (")
        lines.append(f'  echo bundled apply failed>>"{log_path}"')
        lines.append("  exit /b 1")
        lines.append(")")
    else:
        clear_ps = (
            f"$root = '{install_root}'; "
            "if (Test-Path (Join-Path $root 'main.pyc')) { Remove-Item -LiteralPath (Join-Path $root 'main.pyc') -Force }; "
            "Get-ChildItem -LiteralPath $root -Recurse -Directory -Filter '__pycache__' -EA 0 | Remove-Item -Recurse -Force -EA 0; "
            "Get-ChildItem -LiteralPath $root -Recurse -Filter '*.pyc' -File -EA 0 | Remove-Item -Force -EA 0"
        )
        compile_ps = ""
        if py_exe:
            compile_ps = f"& '{py_exe}' -m compileall -b -q '{install_root}'"
        lines.extend(
            [
                f'powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process pythonw,python -EA 0 | Where-Object {{ $_.Path -and ($_.Path -like ''*PeechaSync*'') }} | Stop-Process -Force -EA 0"',
                "timeout /t 5 /nobreak >nul",
                f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{clear_ps}"',
                f'if exist "{staging}" rmdir /S /Q "{staging}"',
                f'powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath \'{pending_zip}\' -DestinationPath \'{staging}\' -Force"',
                f'if exist "{staging}\\sync_app" (set "SRC={staging}") else (',
                f'  for /d %%D in ("{staging}\\*") do set "SRC=%%D"',
                f')',
                "if not defined SRC (",
                f'  echo no source in zip>>"{log_path}"',
                "  exit /b 1",
                ")",
                f'robocopy "%SRC%" "{install_root}" /E /IS /IT /R:3 /W:2 /NFL /NDL /NJH /NJS /NC /NS /NP>>"{log_path}"',
                "if errorlevel 8 (",
                f'  echo robocopy failed>>"{log_path}"',
                "  exit /b 1",
                ")",
            ]
        )
        if compile_ps:
            lines.append(
                f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{compile_ps}" >> "{log_path}" 2>&1'
            )

    lines.extend(
        [
            f'echo [%date% %time%] launch>>"{log_path}"',
            launch_cmd,
            f'if exist "{pending}" rmdir /S /Q "{pending}"',
            "del /F /Q \"%~f0\"",
        ]
    )
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return script_path


def _detect_zip_root(extracted_dir: str) -> str | None:
    if not os.path.isdir(extracted_dir):
        return None
    if os.path.isdir(os.path.join(extracted_dir, "sync_app")) or os.path.isfile(
        os.path.join(extracted_dir, "main.py")
    ):
        return extracted_dir

    entries = [
        name
        for name in os.listdir(extracted_dir)
        if name not in (".", "..") and not name.startswith("__MACOSX")
    ]
    if len(entries) == 1:
        only = os.path.join(extracted_dir, entries[0])
        if os.path.isdir(only) and (
            os.path.isdir(os.path.join(only, "sync_app"))
            or os.path.isfile(os.path.join(only, "main.py"))
        ):
            return only
    return None


def _should_skip_update_dir(name: str) -> bool:
    return name in UPDATE_SKIP_DIRS or name.startswith(".")


def _should_skip_update_file(name: str) -> bool:
    if name in UPDATE_SKIP_FILES:
        return True
    if name.endswith((".pyc", ".pyo", ".log", ".bak")):
        return True
    return False


def _copy_update_tree(source_root: str, dest_root: str) -> None:
    for root, dirs, files in os.walk(source_root):
        dirs[:] = [d for d in dirs if not _should_skip_update_dir(d)]
        rel = os.path.relpath(root, source_root)
        target_dir = dest_root if rel in (".", "") else os.path.join(dest_root, rel)
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            if _should_skip_update_file(name):
                continue
            src = os.path.join(root, name)
            dst = os.path.join(target_dir, name)
            shutil.copy2(src, dst)


def _kill_peecha_processes() -> None:
    if sys.platform != "win32":
        return
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    "Get-Process pythonw,python -EA 0 | "
                    "Where-Object { $_.Path -and ($_.Path -like '*PeechaSync*') } | "
                    "Stop-Process -Force -EA 0"
                ),
            ],
            check=False,
            creationflags=flags,
        )
    except Exception:
        pass


def _write_apply_recovery_bat(install_root: str) -> None:
    """اگر آپدیت از داخل برنامه گیر کرد، کاربر یا لانچر بعدی از این فایل استفاده کند."""
    if sys.platform != "win32":
        return
    install_root = os.path.normpath(install_root)
    src = os.path.join(install_root, "Apply-CachedUpdate.bat")
    if not os.path.isfile(src):
        return
    state_dir = _peecha_state_dir()
    for dest_name in ("Apply-CachedUpdate.bat", "Apply-Update-Now.bat"):
        try:
            shutil.copy2(src, os.path.join(state_dir, dest_name))
        except OSError:
            pass


def _pending_update_dir() -> str:
    local = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(local, "PeechaSync", "update-pending")
    os.makedirs(path, exist_ok=True)
    return path


def _spawn_apply_script(script_path: str) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    si = None
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
    subprocess.Popen(
        ["cmd.exe", "/c", script_path],
        close_fds=True,
        creationflags=flags,
        startupinfo=si,
    )


def _apply_update_deferred_zip(zip_path: str, install_root: str, *, progress=None) -> tuple[bool, str, bool]:
    if progress:
        progress(0, 0, "آماده‌سازی نصب")
    _update_log(f"apply deferred start zip={zip_path} install={install_root}")
    try:
        restart_script = _write_restart_script_from_zip(zip_path, install_root)
    except Exception as exc:
        _update_log(f"apply prepare failed: {exc}")
        mark_update_apply_failed(str(exc), install=install_root)
        raise
    _update_log(f"apply script spawned: {restart_script}")
    _kill_peecha_processes()
    _spawn_apply_script(restart_script)
    return True, "", True


def apply_update_package(zip_path: str, *, progress=None) -> tuple[bool, str, bool]:
    """
    Extract update ZIP and copy into install folder.
    Returns (ok, message, needs_restart).
    """
    if not zip_path or not os.path.isfile(zip_path):
        return False, "فایل بروزرسانی پیدا نشد.", False
    if not zipfile.is_zipfile(zip_path):
        return False, "فایل ZIP معتبر نیست.", False

    install_root = app_install_root()

    if sys.platform == "win32":
        try:
            return _apply_update_deferred_zip(zip_path, install_root, progress=progress)
        except Exception as exc:
            _update_log(f"apply package failed: {exc}")
            return False, str(exc), False

    temp_dir = tempfile.mkdtemp(prefix="peecha-update-")
    try:
        if progress:
            progress(0, 0, "استخراج فایل ZIP")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
        source_root = _detect_zip_root(temp_dir)
        if not source_root:
            return False, "ساختار ZIP نامعتبر است (sync_app یا main.py نیست).", False

        if progress:
            progress(0, 0, "کپی فایل‌های جدید")
        _copy_update_tree(source_root, install_root)
        return True, f"بروزرسانی در پوشه برنامه اعمال شد.\n{install_root}", True
    except Exception as exc:
        return False, str(exc), False
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def download_and_apply_update(
    info: dict[str, Any],
    *,
    license_key: str | None = None,
    hwid: str | None = None,
    config: dict | None = None,
    progress=None,
    force_download: bool = False,
    ignore_apply_block: bool = False,
) -> tuple[bool, str, bool]:
    if not client_updates_allowed(config):
        return False, "مهلت بروزرسانی تمام شده — لایسنس را تمدید کنید.", False

    blocked, block_msg = should_block_update_apply()
    if blocked and not ignore_apply_block:
        _update_log(f"apply blocked: {block_msg[:120]}")
        return False, block_msg, False

    latest = str(info.get("latest_version") or APP_VERSION)
    _update_log(f"download start target={latest} force={force_download}")

    ok_info, fresh_info, info_err = lookup_update_info(
        license_key=license_key,
        hwid=hwid,
        config=config,
    )
    if ok_info and isinstance(fresh_info, dict) and fresh_info.get("update_available"):
        info = fresh_info

    ok, path, err = download_update_package(
        info,
        license_key=license_key,
        hwid=hwid,
        config=config,
        progress=progress,
        force_download=force_download,
    )
    if not ok:
        _update_log(f"download failed: {err or 'download_failed'}")
        return False, err or "download_failed", False

    _update_log(f"download ok path={path} source={err}")
    install_root = app_install_root()
    _write_pending_update_job(path, install_root)
    _bootstrap_launcher_from_zip(path, install_root)
    _write_apply_recovery_bat(install_root)

    ok_apply, msg, restart = apply_update_package(path, progress=progress)
    if ok_apply:
        _update_log("apply queued, app should exit")
        return True, msg, restart
    _update_log(f"apply failed: {msg}")
    return False, msg, False
