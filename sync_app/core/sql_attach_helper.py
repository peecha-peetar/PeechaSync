""" attach MDF/LDF به SQL """
import os
import re
import shutil
import time


def _escape_sql_path(path):
    return os.path.abspath(path).replace("'", "''")


def _norm_path(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _is_access_denied_error(exc):
    if isinstance(exc, PermissionError):
        return True
    text = str(exc).lower()
    return (
        "access is denied" in text
        or "permission denied" in text
        or "errno 13" in text
        or "[errno 13]" in text
        or "5120" in text
        or "operating system error 5" in text
    )


def _staged_dir_for_mdf(mdf_path):
    db_key = suggest_database_name(mdf_path).replace("\\", "_").replace("/", "_")
    return _staged_dir_for_db_name(db_key)


def _staged_dir_for_db_name(db_name):
    safe = re.sub(r"[^A-Za-z0-9_]", "_", (db_name or "import").strip()) or "import"
    return os.path.join(
        os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
        "PeechaSync",
        "databases",
        safe,
    )


def _safe_copy_database_file(src_path, target_dir):
    """کپی MDF/LDF — اگر مقصد قفل باشد نام جدید می‌سازد."""
    src_path = os.path.abspath(src_path)
    os.makedirs(target_dir, exist_ok=True)
    dst_path = os.path.join(target_dir, os.path.basename(src_path))
    if _norm_path(src_path) == _norm_path(dst_path):
        return dst_path

    if os.path.isfile(dst_path):
        try:
            with open(dst_path, "r+b"):
                pass
        except OSError:
            stem, ext = os.path.splitext(dst_path)
            dst_path = os.path.join(target_dir, f"{stem}_{int(time.time())}{ext}")

    shutil.copy2(src_path, dst_path)
    return dst_path


def _stage_files_for_sql_service(mdf_path, ldf_path=None, *, target_dir=None):
    """کپی به ProgramData تا SQL service دسترسی داشته باشد."""
    target_dir = target_dir or _staged_dir_for_mdf(mdf_path)
    target_mdf = _safe_copy_database_file(mdf_path, target_dir)

    target_ldf = None
    if ldf_path and os.path.isfile(ldf_path):
        target_ldf = _safe_copy_database_file(ldf_path, target_dir)

    return target_mdf, target_ldf, target_dir


def suggest_database_name(mdf_path):
    """نام DB از مسیر یا فایل."""
    folder = os.path.basename(os.path.dirname(os.path.abspath(mdf_path)))
    if re.match(r"^DejavuDB_\d+$", folder, re.I):
        return folder
    m = re.match(r"^DejavuDB(\d+)$", folder, re.I)
    if m:
        return f"DejavuDB_{m.group(1)}"
    if re.match(r"^DB_\d+$", folder, re.I):
        return f"DejavuDB_{folder[3:]}"
    if re.match(r"^DB\d+$", folder, re.I):
        return f"DejavuDB_{folder[2:]}"

    stem = os.path.splitext(os.path.basename(mdf_path))[0]
    if stem.lower().endswith("_data"):
        stem = stem[: -len("_data")]
    stem = re.sub(r"[^A-Za-z0-9_]", "_", stem).strip("_")
    return f"DejavuDB_{stem}" if stem else "DejavuDB_import"


def suggest_import_database_name(mdf_path):
    """نام دیتابیس جدید برای import فایل MDF: پایه از فایل + _ + تاریخ شمسی امروز."""
    from datetime import datetime

    from sync_app.core.jalali_log_formatter import gregorian_to_jalali

    stem = os.path.splitext(os.path.basename(mdf_path))[0]
    if stem.lower().endswith("_data"):
        stem = stem[: -len("_data")]
    stem = re.sub(r"[^A-Za-z0-9_]", "_", stem).strip("_")

    if re.match(r"^DejavuDB\d+$", stem or "", re.I):
        base = stem
    elif stem and re.match(r"^Dejavu", stem, re.I):
        base = "DejavuDB"
    elif stem:
        base = f"DejavuDB_{stem}"
    else:
        base = "DejavuDB"

    base = re.sub(r"_\d{8}$", "", base, flags=re.I)

    now = datetime.now()
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{base}_{jy:04d}{jm:02d}{jd:02d}"


def resolve_mdf_path_for_database(config, database_name, timeout=5):
    """مسیر فیزیکی MDF/LDF دیتابیس attach‌شده در SQL Server."""
    database_name = (database_name or "").strip()
    if not database_name:
        return None, None
    try:
        conn, _auth_mode, _repaired = _connect_master(config, timeout=timeout)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT mf.physical_name, mf.type_desc
                FROM sys.master_files mf
                INNER JOIN sys.databases d ON d.database_id = mf.database_id
                WHERE d.name = ?
                """,
                database_name,
            )
            mdf_path = None
            ldf_path = None
            for physical_name, type_desc in cur.fetchall():
                if not physical_name:
                    continue
                abs_path = os.path.abspath(physical_name)
                kind = str(type_desc or "").upper()
                if kind == "ROWS" and not mdf_path:
                    mdf_path = abs_path
                elif kind == "LOG" and not ldf_path:
                    ldf_path = abs_path
            return mdf_path, ldf_path
        finally:
            conn.close()
    except Exception:
        return None, None


def resolve_database_for_mdf_path(mdf_path, config=None, timeout=5):
    """نام واقعی دیتابیس از SQL (اگر attach شده) یا از مسیر MDF."""
    mdf_path = os.path.abspath(mdf_path)
    if config:
        try:
            conn, _auth_mode, _repaired = _connect_master(config, timeout=timeout)
            try:
                existing_name, _existing_path = _find_attached_for_paths(
                    conn, _candidate_attach_paths(mdf_path)
                )
                if existing_name:
                    return existing_name
            finally:
                conn.close()
        except Exception:
            pass
    return suggest_database_name(mdf_path)


def find_ldf_file(mdf_path):
    """LDF هم‌پوشه MDF."""
    folder = os.path.dirname(os.path.abspath(mdf_path))
    if not os.path.isdir(folder):
        return None

    mdf_stem = os.path.splitext(os.path.basename(mdf_path))[0].lower()
    candidates = []
    for name in os.listdir(folder):
        if name.lower().endswith(".ldf"):
            candidates.append(os.path.join(folder, name))

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    for path in candidates:
        base = os.path.splitext(os.path.basename(path))[0].lower()
        if "log" in base or mdf_stem.replace("_data", "") in base:
            return path
    return candidates[0]


def _connect_master(config, timeout=8, *, server_fallback=False, auth_fallback=None):
    from sync_app.core.sql_connection_helper import (
        open_master_connection,
        repair_sql_config_if_needed,
    )

    probe = dict(config or {})
    probe["SQL_DATABASE"] = "master"
    if auth_fallback is None:
        auth_fallback = (probe.get("SQL_AUTH_MODE") or "").strip().lower() not in {
            "sql",
            "windows",
        }
    conn, auth_mode, conn_str = open_master_connection(
        probe,
        timeout=min(max(int(timeout or 8), 2), 3),
        server_fallback=server_fallback,
        auth_fallback=auth_fallback,
    )
    repaired = repair_sql_config_if_needed(probe, auth_mode, conn_str)
    return conn, auth_mode, repaired


def _mdf_paths_for_database(conn, database_name):
    cur = conn.cursor()
    cur.execute(
        """
        SELECT mf.physical_name, mf.type_desc
        FROM sys.master_files mf
        INNER JOIN sys.databases d ON d.database_id = mf.database_id
        WHERE d.name = ?
        """,
        database_name,
    )
    mdf_path = None
    ldf_path = None
    for physical_name, type_desc in cur.fetchall():
        if not physical_name:
            continue
        abs_path = os.path.abspath(physical_name)
        kind = str(type_desc or "").upper()
        if kind == "ROWS" and not mdf_path:
            mdf_path = abs_path
        elif kind == "LOG" and not ldf_path:
            ldf_path = abs_path
    return mdf_path, ldf_path


def _database_is_online(conn, database_name):
    database_name = (database_name or "").strip()
    if not database_name:
        return False
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sys.databases WHERE name = ? AND state = 0",
        database_name,
    )
    return bool(cur.fetchone())


def _lookup_attached_by_mdf_path(conn, mdf_path):
    abs_path = os.path.abspath(mdf_path)
    cur = conn.cursor()
    for path in (abs_path, abs_path.replace("\\", "/")):
        cur.execute(
            """
            SELECT TOP 1 d.name, mf.physical_name
            FROM sys.master_files mf
            INNER JOIN sys.databases d ON d.database_id = mf.database_id
            WHERE mf.type_desc = 'ROWS' AND d.state = 0 AND mf.physical_name = ?
            """,
            path,
        )
        row = cur.fetchone()
        if row:
            return str(row[0]), row[1]

    norm_target = _norm_path(abs_path)
    cur.execute(
        """
        SELECT d.name, mf.physical_name
        FROM sys.master_files mf
        INNER JOIN sys.databases d ON d.database_id = mf.database_id
        WHERE mf.type_desc = 'ROWS' AND d.state = 0
        """
    )
    for name, physical_name in cur.fetchall():
        if physical_name and _norm_path(physical_name) == norm_target:
            return str(name), physical_name
    return None, None


def _find_attached_db_name(conn, mdf_path):
    name, path = _lookup_attached_by_mdf_path(conn, mdf_path)
    return name


def _find_attached_for_paths(conn, paths):
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        existing = _find_attached_db_name(conn, path)
        if existing:
            return existing, path
    return None, None


def _candidate_attach_paths(mdf_path, ldf_path=None):
    paths = [os.path.abspath(mdf_path)]
    staged_dir = _staged_dir_for_mdf(mdf_path)
    staged_mdf = os.path.join(staged_dir, os.path.basename(mdf_path))
    if os.path.isfile(staged_mdf):
        paths.append(staged_mdf)
    if ldf_path and os.path.isfile(ldf_path):
        paths.append(os.path.abspath(ldf_path))
    return paths


def _unique_db_name(conn, preferred):
    name = preferred
    cur = conn.cursor()
    suffix = 1
    while True:
        cur.execute("SELECT name FROM sys.databases WHERE name = ?", name)
        if not cur.fetchone():
            return name
        suffix += 1
        name = f"{preferred}_{suffix}"


def _execute_attach(conn, db_name, mdf_path, ldf_path):
    mdf_sql = _escape_sql_path(mdf_path)
    conn.autocommit = True
    cur = conn.cursor()

    if ldf_path and os.path.isfile(ldf_path):
        ldf_sql = _escape_sql_path(ldf_path)
        sql = (
            f"CREATE DATABASE [{db_name}] ON "
            f"(FILENAME = N'{mdf_sql}'), "
            f"(FILENAME = N'{ldf_sql}') FOR ATTACH"
        )
    else:
        sql = (
            f"CREATE DATABASE [{db_name}] ON "
            f"(FILENAME = N'{mdf_sql}') FOR ATTACH_REBUILD_LOG"
        )
    cur.execute(sql)


def _attach_result(
    *,
    database,
    mdf_path,
    ldf_path,
    server,
    auth_mode,
    attached,
    already_attached,
    source_mdf_path=None,
    staged_dir=None,
):
    return {
        "database": database,
        "mdf_path": mdf_path,
        "ldf_path": ldf_path,
        "source_mdf_path": source_mdf_path or mdf_path,
        "staged_dir": staged_dir,
        "server": server,
        "auth_mode": auth_mode,
        "attached": attached,
        "already_attached": already_attached,
    }


def attach_database_files(config, mdf_path, ldf_path=None, db_name=None, timeout=10, *, fresh_import=False):
    """MDF را attach می‌کند."""
    mdf_path = os.path.abspath(mdf_path)
    if not os.path.isfile(mdf_path):
        raise FileNotFoundError(f"فایل MDF یافت نشد:\n{mdf_path}")

    ldf_path = ldf_path or find_ldf_file(mdf_path)
    if fresh_import:
        preferred_name = suggest_import_database_name(mdf_path)
    else:
        preferred_name = (db_name or suggest_database_name(mdf_path)).strip()
    connect_timeout = min(max(int(timeout or 10), 2), 4)

    conn, auth_mode, repaired = _connect_master(
        config,
        timeout=connect_timeout,
        auth_fallback=False,
    )
    try:
        if not fresh_import and preferred_name and _database_is_online(conn, preferred_name):
            active_mdf, active_ldf = _mdf_paths_for_database(conn, preferred_name)
            return _attach_result(
                database=preferred_name,
                mdf_path=active_mdf or mdf_path,
                ldf_path=active_ldf or ldf_path,
                server=repaired.get("SQL_SERVER"),
                auth_mode=auth_mode,
                attached=False,
                already_attached=True,
                source_mdf_path=mdf_path,
            )

        if not fresh_import:
            existing_name, existing_path = _find_attached_for_paths(
                conn, _candidate_attach_paths(mdf_path, ldf_path)
            )
            if existing_name:
                return _attach_result(
                    database=existing_name,
                    mdf_path=existing_path or mdf_path,
                    ldf_path=ldf_path,
                    server=repaired.get("SQL_SERVER"),
                    auth_mode=auth_mode,
                    attached=False,
                    already_attached=True,
                    source_mdf_path=mdf_path,
                )

        db_name = _unique_db_name(conn, preferred_name)
        source_mdf, source_ldf = mdf_path, ldf_path
        staged_dir = None

        if fresh_import:
            stage_dir = _staged_dir_for_db_name(db_name)
            staged_mdf, staged_ldf, staged_dir = _stage_files_for_sql_service(
                source_mdf, source_ldf, target_dir=stage_dir
            )
            _execute_attach(conn, db_name, staged_mdf, staged_ldf)
            use_mdf, use_ldf = staged_mdf, staged_ldf
        else:
            try:
                _execute_attach(conn, db_name, source_mdf, source_ldf)
                use_mdf, use_ldf = source_mdf, source_ldf
            except Exception as exc:
                if not _is_access_denied_error(exc):
                    raise
                try:
                    staged_mdf, staged_ldf, staged_dir = _stage_files_for_sql_service(
                        source_mdf, source_ldf
                    )
                except Exception as copy_exc:
                    if _is_access_denied_error(copy_exc):
                        existing_name, existing_path = _find_attached_for_paths(
                            conn, _candidate_attach_paths(mdf_path, ldf_path)
                        )
                        if existing_name:
                            return _attach_result(
                                database=existing_name,
                                mdf_path=existing_path or mdf_path,
                                ldf_path=ldf_path,
                                server=repaired.get("SQL_SERVER"),
                                auth_mode=auth_mode,
                                attached=False,
                                already_attached=True,
                                source_mdf_path=mdf_path,
                                staged_dir=_staged_dir_for_mdf(mdf_path),
                            )
                        raise PermissionError(
                            "فایل دیتابیس در حال استفاده است یا SQL Server به مسیر دسترسی ندارد.\n"
                            f"مسیر: {mdf_path}\n\n"
                            "۱) اگر همین دیتابیس قبلاً وصل شده، از لیست «انتخاب DB» همان را انتخاب کنید.\n"
                            "۲) فایل MDF را در Explorer باز نکنید.\n"
                            "۳) در صورت نیاز SQL Server را یک‌بار Restart کنید."
                        ) from copy_exc
                    raise

                existing_name, existing_path = _find_attached_for_paths(conn, [staged_mdf])
                if existing_name:
                    return _attach_result(
                        database=existing_name,
                        mdf_path=existing_path or staged_mdf,
                        ldf_path=staged_ldf or ldf_path,
                        server=repaired.get("SQL_SERVER"),
                        auth_mode=auth_mode,
                        attached=False,
                        already_attached=True,
                        source_mdf_path=mdf_path,
                        staged_dir=staged_dir,
                    )

                _execute_attach(conn, db_name, staged_mdf, staged_ldf)
                use_mdf, use_ldf = staged_mdf, staged_ldf

        return _attach_result(
            database=db_name,
            mdf_path=use_mdf,
            ldf_path=use_ldf,
            server=repaired.get("SQL_SERVER"),
            auth_mode=auth_mode,
            attached=True,
            already_attached=False,
            source_mdf_path=source_mdf,
            staged_dir=staged_dir,
        )
    finally:
        conn.close()


def ensure_config_database_attached(config, timeout=8):
    """MDF در config بود attach کن."""
    cfg = dict(config or {})
    db_name = (cfg.get("SQL_DATABASE") or "").strip()
    mdf_path = (cfg.get("SQL_MDF_PATH") or "").strip()

    if db_name and not mdf_path:
        try:
            conn, auth_mode, repaired = _connect_master(
                cfg, timeout=min(int(timeout or 8), 3), auth_fallback=False
            )
            try:
                if _database_is_online(conn, db_name):
                    active_mdf, active_ldf = _mdf_paths_for_database(conn, db_name)
                    if active_mdf:
                        cfg["SQL_MDF_PATH"] = active_mdf
                    if active_ldf:
                        cfg["SQL_LDF_PATH"] = active_ldf
                    if repaired.get("SQL_SERVER"):
                        cfg["SQL_SERVER"] = repaired["SQL_SERVER"]
                    cfg["SQL_AUTH_MODE"] = auth_mode
                    return cfg, bool(active_mdf)
            finally:
                conn.close()
        except Exception:
            pass

    if not mdf_path or not os.path.isfile(mdf_path):
        return cfg, False

    if db_name:
        try:
            conn, _auth_mode, _repaired = _connect_master(
                cfg, timeout=min(int(timeout or 8), 3), auth_fallback=False
            )
            try:
                if _database_is_online(conn, db_name):
                    return cfg, False
            finally:
                conn.close()
        except Exception:
            pass

    ldf_path = cfg.get("SQL_LDF_PATH") or None
    result = attach_database_files(
        cfg, mdf_path, ldf_path=ldf_path, db_name=db_name or None, timeout=timeout
    )

    updated = dict(cfg)
    updated["SQL_SERVER"] = result.get("server") or updated.get("SQL_SERVER")
    updated["SQL_DATABASE"] = result["database"]
    updated["SQL_MDF_PATH"] = result["mdf_path"]
    if result.get("ldf_path"):
        updated["SQL_LDF_PATH"] = result["ldf_path"]
    updated["SQL_AUTH_MODE"] = result.get("auth_mode") or updated.get("SQL_AUTH_MODE")
    return updated, True
