import re
import socket
import threading


_CONNECT_DEADLINE_SEC = 3


def _normalize_driver_name(driver_name):
    text = (driver_name or "").strip()
    if text.startswith("{") and text.endswith("}"):
        return text[1:-1].strip()
    return text


def build_conn_str(config, auth_mode="sql", server_override=None, database_override=None, timeout=None):
    driver_clean = _normalize_driver_name(config.get("SQL_DRIVER") or "ODBC Driver 18 for SQL Server")
    server = (server_override or config.get("SQL_SERVER") or "").strip()
    database = (database_override if database_override is not None else config.get("SQL_DATABASE") or "").strip()
    username = (config.get("SQL_USERNAME") or "").strip()
    password = config.get("SQL_PASSWORD") or ""

    parts = [f"DRIVER={{{driver_clean}}}", f"SERVER={server}"]
    if database:
        parts.append(f"DATABASE={database}")

    if auth_mode == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={username}")
        parts.append(f"PWD={password}")

    conn_timeout = timeout if timeout is not None else _CONNECT_DEADLINE_SEC
    conn_timeout = min(max(int(conn_timeout), 2), 5)
    parts.append(f"Connection Timeout={conn_timeout}")

    if "ODBC Driver 18" in driver_clean or "ODBC Driver 17" in driver_clean:
        parts.append("Encrypt=no")
        parts.append("TrustServerCertificate=yes")

    return ";".join(parts) + ";"


def local_server_variants(server):
    """نام‌های رایج SQLEXPRESS محلی — سریع‌ترین اول"""
    raw = (server or "").strip()
    if not raw:
        return [r".\SQLEXPRESS", r"(local)\SQLEXPRESS", r"localhost\SQLEXPRESS"]

    variants = [raw]
    lowered = raw.lower().replace(" ", "")
    if "sqlexpress" in lowered:
        for item in (
            raw,
            r".\SQLEXPRESS",
            r"(local)\SQLEXPRESS",
            r"localhost\SQLEXPRESS",
            r"127.0.0.1\SQLEXPRESS",
        ):
            if item not in variants:
                variants.append(item)
    return variants[:4]


def connect_with_deadline(connect_fn, deadline_sec=None):
    """pyodbc روی ویندوز گاهی timeout را نادیده می‌گیرد — سقف زمانی سخت"""
    limit = deadline_sec if deadline_sec is not None else _CONNECT_DEADLINE_SEC
    limit = min(max(int(limit), 2), 6)
    box = {"conn": None, "error": None}

    def _run():
        try:
            box["conn"] = connect_fn()
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(limit)
    if thread.is_alive():
        raise TimeoutError(
            f"اتصال SQL بیش از {limit} ثانیه طول کشید. "
            "سرویس SQL Express را در services.msc بررسی کنید."
        )
    if box["error"] is not None:
        raise box["error"]
    if box["conn"] is None:
        raise TimeoutError(f"اتصال SQL برقرار نشد (مهلت {limit} ثانیه).")
    return box["conn"]


def _extract_from_conn_str(conn_str, key):
    if not conn_str:
        return ""
    m = re.search(rf"(?:^|;)\s*{re.escape(key)}\s*=\s*([^;]+)", conn_str, re.IGNORECASE)
    return (m.group(1).strip() if m else "")


def _hostname_candidates():
    names = []
    try:
        host = socket.gethostname()
        if host:
            names.append(host)
    except Exception:
        pass
    return names


def _server_candidates(server):
    """نام سرور برای retry اتصال — برای SQLEXPRESS فقط instance نام‌دار، نه localhost خام"""
    raw = (server or "").strip()
    candidates = []

    def _add(item):
        item = (item or "").strip()
        if item and item not in candidates:
            candidates.append(item)

    lowered = raw.lower().replace(" ", "")

    if raw:
        _add(raw)

    if "sqlexpress" in lowered:
        for item in local_server_variants(raw):
            _add(item)
        for host in _hostname_candidates():
            _add(rf"{host}\SQLEXPRESS")
    elif raw:
        pass
    elif lowered in {"", "localhost", "127.0.0.1", ".", "(local)"}:
        for item in (
            r".\SQLEXPRESS",
            r"(local)\SQLEXPRESS",
            r"localhost\SQLEXPRESS",
            "localhost",
            ".",
        ):
            _add(item)

    if not candidates:
        for item in (r".\SQLEXPRESS", r"(local)\SQLEXPRESS", r"localhost\SQLEXPRESS"):
            _add(item)

    return candidates


def _extract_auth_mode(config):
    auth_mode = (config.get("SQL_AUTH_MODE") or "").strip().lower()
    if auth_mode in {"sql", "windows"}:
        return auth_mode

    conn_str = ((config.get("SQL_CONN_STRING") or "") + " ").lower()
    if "trusted_connection=yes" in conn_str or "integrated security=sspi" in conn_str:
        return "windows"
    if "uid=" in conn_str or "pwd=" in conn_str:
        return "sql"

    username = (config.get("SQL_USERNAME") or "").strip()
    password = config.get("SQL_PASSWORD") or ""
    if not username and not password:
        return "windows"
    return "sql"


def get_auth_order(config):
    primary = _extract_auth_mode(config)
    secondary = "windows" if primary == "sql" else "sql"
    return [primary, secondary]


def _is_database_missing_error(exc):
    text = str(exc).lower()
    markers = [
        "cannot open database",
        "login failed",
        "database",
        "4060",
    ]
    return any(m in text for m in markers)


def _list_dejavu_databases(config, server, auth_mode, timeout=4):
    import pyodbc

    probe_cfg = dict(config or {})
    probe_cfg["SQL_SERVER"] = server
    conn_str = build_conn_str(probe_cfg, auth_mode=auth_mode, database_override="master")
    conn = pyodbc.connect(conn_str, timeout=timeout)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sys.databases "
            "WHERE name LIKE 'Dejavu%' OR name LIKE 'dejavu%' "
            "ORDER BY name DESC"
        )
        return [str(row[0]).strip() for row in cur.fetchall() if row and row[0]]
    finally:
        conn.close()


def _database_candidates(config):
    configured = (config.get("SQL_DATABASE") or "").strip()
    candidates = []

    if configured:
        candidates.append(configured)

    mdf_path = (config.get("SQL_MDF_PATH") or "").strip()
    if mdf_path:
        from sync_app.core.sql_attach_helper import resolve_database_for_mdf_path
        resolved = resolve_database_for_mdf_path(mdf_path, config=config, timeout=3)
        if resolved and resolved not in candidates:
            candidates.append(resolved)
    for name in ["DejavuDB_14050302", "DejavuDB3", "DejavuDB1", "DejavuDB2"]:
        if name not in candidates:
            candidates.append(name)
    return candidates


def _try_connect(config, server, auth_mode, database, timeout):
    import pyodbc

    per_try_config = dict(config or {})
    per_try_config["SQL_SERVER"] = server
    probe_timeout = min(max(int(timeout or _CONNECT_DEADLINE_SEC), 2), 5)
    conn_str = build_conn_str(
        per_try_config,
        auth_mode=auth_mode,
        database_override=database,
        timeout=probe_timeout,
    )

    def _connect():
        return pyodbc.connect(conn_str, timeout=probe_timeout)

    conn = connect_with_deadline(_connect, deadline_sec=probe_timeout + 1)
    return conn, conn_str


def connect_with_fallback(config, timeout=8):
    conn, auth_mode, conn_str, _repaired = _connect_with_fallback(config, timeout=timeout)
    return conn, auth_mode, conn_str


def _connect_with_fallback(config, timeout=8):
    cfg = normalize_sql_config(config)
    server = (cfg.get("SQL_SERVER") or "").strip()
    username = (cfg.get("SQL_USERNAME") or "").strip()
    probe_timeout = min(max(int(timeout or 8), 2), 8)

    if not server:
        raise Exception("تنظیمات SQL ناقص است (Server خالی است).")

    last_error = None
    for server_candidate in _server_candidates(server):
        for auth_mode in get_auth_order(cfg):
            if auth_mode == "sql" and not username:
                last_error = Exception("نام کاربری SQL وارد نشده است.")
                continue

            discovered = []
            try:
                master_conn, _ = _try_connect(cfg, server_candidate, auth_mode, "master", probe_timeout)
                master_conn.close()
                discovered = _list_dejavu_databases(cfg, server_candidate, auth_mode, timeout=probe_timeout)
            except Exception as exc:
                last_error = exc
                continue

            db_names = []
            for name in _database_candidates(cfg) + discovered:
                if name and name not in db_names:
                    db_names.append(name)

            for db_name in db_names:
                try:
                    conn, conn_str = _try_connect(
                        cfg, server_candidate, auth_mode, db_name, probe_timeout
                    )
                    repaired = repair_sql_config_if_needed(cfg, auth_mode, conn_str)
                    repaired["SQL_SERVER"] = server_candidate
                    repaired["SQL_DATABASE"] = db_name
                    return conn, auth_mode, conn_str, repaired
                except Exception as exc:
                    last_error = exc

    raise last_error or Exception("اتصال SQL برقرار نشد.")


def repair_sql_config_if_needed(config, auth_mode, conn_str):
    repaired = dict(config or {})
    repaired["SQL_AUTH_MODE"] = auth_mode
    repaired["SQL_CONN_STRING"] = conn_str
    return repaired


def normalize_sql_config(config):
    """ Server/Database فرم با conn string """
    cfg = dict(config or {})
    server = (cfg.get("SQL_SERVER") or "").strip()
    database = (cfg.get("SQL_DATABASE") or "").strip()
    conn_str = cfg.get("SQL_CONN_STRING") or ""

    if not server:
        server = _extract_from_conn_str(conn_str, "SERVER").strip()
    if not database:
        database = _extract_from_conn_str(conn_str, "DATABASE").strip()

    if server:
        cfg["SQL_SERVER"] = server
    if database:
        cfg["SQL_DATABASE"] = database
    return cfg


def verify_sql_config_quick(config, timeout=3):
    """اگر تنظیمات فعلی جواب می‌دهد همان را برگردان — بدون fallback سنگین."""
    cfg = normalize_sql_config(config)
    server = (cfg.get("SQL_SERVER") or "").strip()
    database = (cfg.get("SQL_DATABASE") or "").strip()
    if not server or not database:
        return cfg, False

    probe_timeout = min(max(int(timeout or 3), 2), 3)
    try:
        conn, auth_mode, conn_str = open_master_connection(
            cfg,
            timeout=probe_timeout,
            server_fallback=False,
            auth_fallback=False,
        )
        conn.close()
        conn, _ = _try_connect(cfg, server, auth_mode, database, probe_timeout)
        conn.close()
        repaired = repair_sql_config_if_needed(cfg, auth_mode, conn_str)
        repaired["SQL_DATABASE"] = database
        return repaired, True
    except Exception:
        return cfg, False


def auto_repair_sql_config(config, timeout=5, *, allow_heavy_fallback=False):
    """تعمیر خودکار SQL — پیش‌فرض سبک، بدون fallback سنگین"""
    healed, ok, msg = auto_heal_sql_connection(config, timeout=min(int(timeout or 5), 4))
    if ok or not allow_heavy_fallback:
        return healed, msg

    cfg = normalize_sql_config(config)
    before = (cfg.get("SQL_SERVER"), cfg.get("SQL_DATABASE"), cfg.get("SQL_AUTH_MODE"))

    conn, auth_mode, conn_str, repaired = _connect_with_fallback(cfg, timeout=timeout)
    conn.close()

    after = (repaired.get("SQL_SERVER"), repaired.get("SQL_DATABASE"), repaired.get("SQL_AUTH_MODE"))
    if after != before:
        summary = (
            f"تنظیمات SQL خودکار اصلاح شد: "
            f"Server={repaired.get('SQL_SERVER')} | DB={repaired.get('SQL_DATABASE')} | Auth={auth_mode}"
        )
    else:
        summary = f"اتصال SQL برقرار است ({repaired.get('SQL_SERVER')} / {repaired.get('SQL_DATABASE')})"

    return repaired, summary


def auto_heal_sql_connection(config, timeout=4):
    """
    خودکار: روشن کردن SQL Express، امتحان نام‌های رایج Server، برگرداندن تنظیم اصلاح‌شده.
    خروجی: (config, ok, message)
    """
    from sync_app.core.sql_windows_probe import ensure_sqlexpress_running, sqlexpress_status_hint

    cfg = normalize_sql_config(config)
    server = (cfg.get("SQL_SERVER") or "").strip()
    notes = []

    if server and "sqlexpress" in server.lower().replace(" ", ""):
        started = ensure_sqlexpress_running()
        if started is True:
            notes.append("سرویس SQL Express روشن شد")
        elif started is False:
            hint = sqlexpress_status_hint()
            return cfg, False, hint or "سرویس SQL Express روشن نشد"

    quick_cfg, ok = verify_sql_config_quick(cfg, timeout=min(int(timeout or 4), 3))
    if ok:
        msg = "اتصال SQL با تنظیمات فعلی OK"
        if notes:
            msg = f"{notes[0]} — {msg}"
        return quick_cfg, True, msg

    if not server:
        return cfg, False, "Server خالی است"

    last_error = None
    for variant in local_server_variants(server):
        test_cfg = dict(cfg)
        test_cfg["SQL_SERVER"] = variant
        try:
            conn, auth_mode, conn_str = open_master_connection(
                test_cfg,
                timeout=timeout,
                server_fallback=False,
                auth_fallback=False,
            )
            conn.close()
            healed = repair_sql_config_if_needed(test_cfg, auth_mode, conn_str)
            healed["SQL_SERVER"] = variant
            msg = f"Server خودکار به «{variant}» اصلاح شد"
            if notes:
                msg = f"{notes[0]} — {msg}"
            return healed, True, msg
        except Exception as exc:
            last_error = exc

    hint = sqlexpress_status_hint()
    msg = str(last_error or "اتصال SQL برقرار نشد")
    if hint and hint not in msg:
        msg = f"{msg}\n\n{hint}"
    return cfg, False, msg


def format_db_error(exc):
    """خطای SQL برای UI/لاگ — از رجیستری تشخیص."""
    from sync_app.core.diagnostics import format_sql_error

    return format_sql_error(exc=exc)


def open_sql_connection(config, timeout=8):
    """ SQL با fallback """
    cfg = normalize_sql_config(config)
    conn, auth_mode, conn_str, _repaired = _connect_with_fallback(cfg, timeout=timeout)
    return conn, auth_mode, conn_str


def open_master_connection(
    config,
    timeout=5,
    *,
    server_fallback=False,
    auth_fallback=True,
):
    """اتصال سبک فقط به master — برای لیست دیتابیس‌ها و Attach"""
    from sync_app.core.sql_windows_probe import ensure_sqlexpress_running, sqlexpress_status_hint

    cfg = normalize_sql_config(config)
    server = (cfg.get("SQL_SERVER") or "").strip()
    if not server:
        raise Exception("Server خالی است.")

    if "sqlexpress" in server.lower().replace(" ", ""):
        ensure_sqlexpress_running()

    probe_timeout = min(max(int(timeout or 5), 2), 3)
    last_error = None

    if server_fallback:
        candidates = local_server_variants(server)
    else:
        candidates = [server]

    auth_modes = get_auth_order(cfg)
    if not auth_fallback:
        auth_modes = auth_modes[:1]

    for server_candidate in candidates:
        for auth_mode in auth_modes:
            if auth_mode == "sql" and not (cfg.get("SQL_USERNAME") or "").strip():
                last_error = Exception("نام کاربری SQL وارد نشده است.")
                continue
            try:
                conn, conn_str = _try_connect(
                    cfg, server_candidate, auth_mode, "master", probe_timeout
                )
                return conn, auth_mode, conn_str
            except Exception as exc:
                last_error = exc

    msg = str(last_error or "اتصال به SQL Server برقرار نشد.")
    extra = sqlexpress_status_hint()
    if extra and extra not in msg:
        msg = f"{msg}\n\n{extra}"
    raise Exception(msg)
