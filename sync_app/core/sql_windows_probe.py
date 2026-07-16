"""بررسی و راه‌اندازی SQL Express روی ویندوز"""
import os
import subprocess
import time

SERVICE_SQLEXPRESS = "MSSQL$SQLEXPRESS"
SERVICE_SQL_BROWSER = "SQLBrowser"

_UNREACHABLE_MARKERS = (
    "error locating server",
    "server is not found",
    "server is not found or not accessible",
    "login timeout expired",
    "does not exist or access denied",
    "08001",
    "sqlexpress",
    "سرویس sql server express خاموش",
    "بیش از",
    "ثانیه طول کشید",
)


def _run_hidden(cmd, timeout=2):
    flags = 0
    if os.name != "nt":
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=flags,
    )


def _service_query_text(service_name):
    try:
        cp = _run_hidden(["sc", "query", service_name], timeout=3)
        return (cp.stdout or "") + (cp.stderr or "")
    except Exception as exc:
        return str(exc)


def _service_exists(service_name):
    if os.name != "nt":
        return None
    text = _service_query_text(service_name).upper()
    if "FAILED" in text and "1060" in text:
        return False
    if "DOES NOT EXIST" in text:
        return False
    return "SERVICE_NAME" in text or service_name.upper() in text


def sqlexpress_service_status():
    """
    وضعیت سرویس SQL Express.
    True=روشن، False=خاموش، None=نامشخص
    """
    if os.name != "nt":
        return None, ""
    text = _service_query_text(SERVICE_SQLEXPRESS)
    upper = text.upper()
    if "RUNNING" in upper:
        return True, text
    if "STOPPED" in upper:
        return False, text
    return None, text


def sql_browser_service_status():
    return _sql_browser_status()


def _sql_browser_status():
    if os.name != "nt":
        return None
    text = _service_query_text(SERVICE_SQL_BROWSER).upper()
    if "RUNNING" in text:
        return True
    if "STOPPED" in text:
        return False
    return None


def is_sqlexpress_unreachable_error(error_text):
    """آیا متن خطا شبیه «SQL Express در دسترس نیست» است؟"""
    lowered = (error_text or "").lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in _UNREACHABLE_MARKERS)


def uses_sqlexpress_server(server):
    return _uses_sqlexpress_server(server)


def _uses_sqlexpress_server(server):
    raw = (server or "").strip().lower().replace(" ", "")
    if not raw:
        return True
    return "sqlexpress" in raw


def diagnose_sqlexpress_connection(error_text="", server=""):
    """تشخیص SQL Express — از رجیستری قوانین (قابل گسترش)."""
    from sync_app.core.diagnostics import diagnose_sql

    return diagnose_sql(error_text=error_text, server=server).to_dict()


def _uses_sqlexpress_server(server):
    try:
        cp = _run_hidden(["net", "start", service_name], timeout=timeout)
        text = ((cp.stdout or "") + (cp.stderr or "")).strip()
        lowered = text.lower()
        if cp.returncode == 0:
            return True, text or "started"
        if "already been started" in lowered or "already started" in lowered:
            return True, text
        return False, text or f"net start exit {cp.returncode}"
    except Exception as exc:
        return False, str(exc)


def _start_service_sc(service_name, timeout=25):
    try:
        cp = _run_hidden(["sc", "start", service_name], timeout=timeout)
        text = ((cp.stdout or "") + (cp.stderr or "")).strip()
        if cp.returncode == 0:
            return True, text or "started"
        return False, text or f"sc start exit {cp.returncode}"
    except Exception as exc:
        return False, str(exc)


def _start_service_powershell(service_name, timeout=25):
    ps = (
        f"$ErrorActionPreference='Stop'; "
        f"Start-Service -Name '{service_name}' -ErrorAction Stop; "
        f"'started'"
    )
    try:
        cp = _run_hidden(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            timeout=timeout,
        )
        text = ((cp.stdout or "") + (cp.stderr or "")).strip()
        if cp.returncode == 0:
            return True, text or "started"
        return False, text or f"powershell exit {cp.returncode}"
    except Exception as exc:
        return False, str(exc)


def _start_service_elevated(service_name):
    """درخواست UAC برای net start — پنجره مخفی"""
    try:
        import ctypes

        params = f'start "{service_name}"'
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "net.exe",
            params,
            None,
            0,
        )
        if rc <= 32:
            return False, f"UAC/ShellExecute ناموفق (کد {rc})"
        return True, "درخواست تایید مدیر سیستم نمایش داده شد"
    except Exception as exc:
        return False, str(exc)


def _wait_service_running(check_fn, timeout_sec=35, poll_sec=1.0):
    deadline = time.time() + max(int(timeout_sec), 5)
    while time.time() < deadline:
        running, _detail = check_fn()
        if running is True:
            return True
        time.sleep(poll_sec)
    return False


def _enable_sql_browser_startup():
    ps = (
        "$ErrorActionPreference='SilentlyContinue'; "
        f"Set-Service -Name '{SERVICE_SQL_BROWSER}' -StartupType Manual; "
        f"Start-Service -Name '{SERVICE_SQL_BROWSER}'"
    )
    try:
        cp = _run_hidden(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            timeout=20,
        )
        text = ((cp.stdout or "") + (cp.stderr or "")).strip()
        return cp.returncode == 0, text
    except Exception as exc:
        return False, str(exc)


def start_sqlexpress_service(*, allow_elevation=True, wait_sec=30):
    """
    تلاش واقعی برای روشن کردن SQL Express.
    خروجی: {ok, message, elevated, steps[]}
    """
    steps = []
    if os.name != "nt":
        return {"ok": False, "message": "فقط ویندوز", "elevated": False, "steps": steps}

    running, _detail = sqlexpress_service_status()
    if running is True:
        _try_start_sql_browser()
        return {
            "ok": True,
            "message": "سرویس SQL Express از قبل روشن است.",
            "elevated": False,
            "steps": ["already_running"],
        }

    if _service_exists(SERVICE_SQLEXPRESS) is False:
        return {
            "ok": False,
            "message": "SQL Server Express روی این سیستم نصب نیست.",
            "elevated": False,
            "steps": steps,
        }

    for name, fn in (
        ("net", lambda: _start_service_net(SERVICE_SQLEXPRESS)),
        ("sc", lambda: _start_service_sc(SERVICE_SQLEXPRESS)),
        ("powershell", lambda: _start_service_powershell(SERVICE_SQLEXPRESS)),
    ):
        ok, detail = fn()
        steps.append(f"{name}: {detail[:200]}")
        if ok and _wait_service_running(sqlexpress_service_status, timeout_sec=8, poll_sec=0.5):
            _try_start_sql_browser()
            return {
                "ok": True,
                "message": "سرویس SQL Express روشن شد.",
                "elevated": False,
                "steps": steps,
            }

    elevated = False
    if allow_elevation:
        uac_ok, uac_msg = _start_service_elevated(SERVICE_SQLEXPRESS)
        steps.append(f"uac: {uac_msg}")
        elevated = uac_ok
        if uac_ok and _wait_service_running(
            sqlexpress_service_status, timeout_sec=wait_sec, poll_sec=1.0
        ):
            _try_start_sql_browser()
            return {
                "ok": True,
                "message": "سرویس SQL Express با دسترسی مدیر روشن شد.",
                "elevated": True,
                "steps": steps,
            }

    running, _detail = sqlexpress_service_status()
    if running is True:
        _try_start_sql_browser()
        return {
            "ok": True,
            "message": "سرویس SQL Express روشن است.",
            "elevated": elevated,
            "steps": steps,
        }

    return {
        "ok": False,
        "message": (
            "روشن کردن SQL Express ناموفق بود. "
            "PeechaSync را Run as Administrator اجرا کنید یا در services.msc دستی Start بزنید."
        ),
        "elevated": elevated,
        "steps": steps,
    }


def start_sql_browser_service(*, allow_elevation=True):
    """روشن کردن SQL Browser برای instance نام‌دار"""
    steps = []
    if os.name != "nt":
        return {"ok": False, "message": "فقط ویندوز", "steps": steps}

    if _sql_browser_status() is True:
        return {"ok": True, "message": "SQL Browser از قبل روشن است.", "steps": ["already_running"]}

    ok, detail = _enable_sql_browser_startup()
    steps.append(f"powershell: {detail[:200]}")
    if ok and _sql_browser_status() is True:
        return {"ok": True, "message": "SQL Browser روشن شد.", "steps": steps}

    ok_net, detail_net = _start_service_net(SERVICE_SQL_BROWSER, timeout=15)
    steps.append(f"net: {detail_net[:200]}")
    if ok_net and _wait_service_running(
        lambda: (_sql_browser_status(), ""), timeout_sec=10, poll_sec=0.5
    ):
        return {"ok": True, "message": "SQL Browser روشن شد.", "steps": steps}

    if allow_elevation:
        uac_ok, uac_msg = _start_service_elevated(SERVICE_SQL_BROWSER)
        steps.append(f"uac: {uac_msg}")
        if uac_ok and _wait_service_running(
            lambda: (_sql_browser_status(), ""), timeout_sec=20, poll_sec=1.0
        ):
            return {"ok": True, "message": "SQL Browser با دسترسی مدیر روشن شد.", "steps": steps}

    return {
        "ok": False,
        "message": "روشن کردن SQL Browser ناموفق بود.",
        "steps": steps,
    }


def ensure_sqlexpress_running():
    """
    اگر SQL Express خاموش باشد خودکار Start می‌زند.
    True=روشن، False=روشن نشد، None=غیر ویندوز
    """
    if os.name != "nt":
        return None

    running, _detail = sqlexpress_service_status()
    if running is True:
        _try_start_sql_browser()
        return True

    result = start_sqlexpress_service(allow_elevation=True, wait_sec=20)
    if result.get("ok"):
        return True
    return False


def _try_start_sql_browser():
    """Browser برای TCP به named instance — اختیاری ولی کمک می‌کند."""
    if _sql_browser_status() is not False:
        return
    _enable_sql_browser_startup()


def sqlexpress_status_hint():
    running, _detail = sqlexpress_service_status()
    if running is True:
        return ""
    if running is False:
        return (
            "سرویس SQL Server Express خاموش است.\n"
            "از دکمه «روشن کردن سرویس SQL Express» در تنظیمات استفاده کنید."
        )
    if _service_exists(SERVICE_SQLEXPRESS) is False:
        return "SQL Server Express روی این سیستم نصب نیست."
    return ""
