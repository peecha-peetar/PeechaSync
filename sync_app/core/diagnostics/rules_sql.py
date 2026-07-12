"""قوانین تشخیص خطای SQL — قابل افزودن بدون تغییر UI."""

from __future__ import annotations

import os

from sync_app.core.diagnostics.base import DiagnosticContext, DiagnosticRegistry, DiagnosticResult

_SQL_REGISTRY = DiagnosticRegistry("sql")


def sql_registry() -> DiagnosticRegistry:
    return _SQL_REGISTRY


def _text_has_any(ctx: DiagnosticContext, *tokens: str) -> bool:
    low = ctx.lowered
    return any(t.lower() in low for t in tokens if t)


def _register_sql_rules() -> None:
    r = _SQL_REGISTRY

    r.register(
        "sql_not_windows",
        priority=10,
        domains=("sql",),
        match=lambda c: os.name != "nt" and _text_has_any(c, "sqlexpress", "sql server", "mssql"),
        build=lambda c: DiagnosticResult(
            code="sql_not_windows",
            message_fa="مدیریت سرویس SQL فقط روی ویندوز پشتیبانی می‌شود.",
        ),
    )

    r.register(
        "sql_driver_missing",
        priority=15,
        domains=("sql",),
        match=lambda c: _text_has_any(
            c, "im002", "data source name not found", "default driver specified", "driver"
        ),
        build=lambda c: DiagnosticResult(
            code="sql_driver_missing",
            message_fa="درایور ODBC SQL Server روی سیستم نصب نیست یا نسخه ناسازگار است.",
            hints=["ODBC Driver 17 یا 18 for SQL Server را نصب کنید", "در تنظیمات Driver را انتخاب کنید"],
        ),
    )

    r.register(
        "sql_login_failed",
        priority=20,
        domains=("sql",),
        match=lambda c: _text_has_any(c, "login failed", "28000", "18456"),
        build=lambda c: DiagnosticResult(
            code="sql_login_failed",
            message_fa="نام کاربری یا رمز SQL اشتباه است.",
            hints=[
                "Username/Password را در تنظیمات بررسی کنید",
                "Windows Authentication را امتحان کنید (فیلدها خالی)",
                "Mixed Mode و کاربر sa روی SQL فعال باشد",
            ],
        ),
    )

    r.register(
        "sql_database_missing",
        priority=25,
        domains=("sql",),
        match=lambda c: _text_has_any(c, "cannot open database", "4060"),
        build=lambda c: DiagnosticResult(
            code="sql_database_missing",
            message_fa="دیتابیس پیدا نشد یا هنوز Attach نشده است.",
            hints=[
                "نام Database را بررسی کنید",
                "فایل MDF را با «انتخاب فایل» Attach کنید",
                "«بارگذاری» لیست دیتابیس‌ها را بزنید",
            ],
        ),
    )

    r.register(
        "sql_service_stopped",
        priority=30,
        domains=("sql",),
        match=_match_service_stopped,
        build=lambda c: DiagnosticResult(
            code="sql_service_stopped",
            action_id="start_sqlexpress",
            message_fa="سرویس SQL Server Express خاموش است.",
            action_label="▶ روشن کردن سرویس SQL Express",
            can_auto_fix=True,
        ),
    )

    r.register(
        "sql_not_installed",
        priority=35,
        domains=("sql",),
        match=_match_not_installed,
        build=lambda c: DiagnosticResult(
            code="sql_not_installed",
            message_fa=(
                "SQL Server Express روی این سیستم نصب نیست.\n"
                "از نصاب PeechaSync یا Microsoft SQL Server Express استفاده کنید."
            ),
        ),
    )

    r.register(
        "sql_browser_stopped",
        priority=40,
        domains=("sql",),
        match=_match_browser_stopped,
        build=lambda c: DiagnosticResult(
            code="sql_browser_stopped",
            action_id="start_browser",
            message_fa="سرویس SQL Express روشن است ولی SQL Browser خاموش است.",
            action_label="▶ روشن کردن SQL Browser",
            can_auto_fix=True,
        ),
    )

    r.register(
        "sql_remote_server",
        priority=45,
        domains=("sql",),
        match=_match_remote_only,
        build=lambda c: DiagnosticResult(
            code="sql_remote_server",
            message_fa=(
                "Server انتخاب‌شده SQL Express محلی نیست — "
                "روشن کردن سرویس از برنامه فقط برای .\\SQLEXPRESS است."
            ),
        ),
    )

    r.register(
        "sql_unreachable",
        priority=50,
        domains=("sql",),
        match=lambda c: _text_has_any(
            c,
            "error locating server",
            "server is not found",
            "login timeout",
            "08001",
            "بیش از",
            "ثانیه طول کشید",
            "sqlexpress",
        ),
        build=lambda c: DiagnosticResult(
            code="sql_unreachable",
            action_id="start_sqlexpress",
            message_fa="اتصال به SQL Server برقرار نشد.",
            action_label="▶ تلاش برای روشن کردن SQL Express",
            can_auto_fix=_can_fix_local_express(c),
            hints=[
                "سرویس SQL Server (SQLEXPRESS) را بررسی کنید",
                "SQL Browser را روشن کنید",
                "Server را .\\SQLEXPRESS بگذارید",
            ],
        ),
    )

    r.register(
        "sql_timeout",
        priority=60,
        domains=("sql",),
        match=lambda c: _text_has_any(c, "timeout", "timed out"),
        build=lambda c: DiagnosticResult(
            code="sql_timeout",
            message_fa="اتصال SQL بیش از حد طول کشید.",
            hints=["سرویس SQL را بررسی کنید", "برنامه‌های سنگین را ببندید و دوباره تلاش کنید"],
            severity="warning",
        ),
    )


def _uses_sqlexpress(server: str) -> bool:
    raw = (server or "").strip().lower().replace(" ", "")
    if not raw:
        return True
    return "sqlexpress" in raw


def _can_fix_local_express(ctx: DiagnosticContext) -> bool:
    return os.name == "nt" and _uses_sqlexpress(ctx.server or (ctx.config or {}).get("SQL_SERVER", ""))


def _match_remote_only(ctx: DiagnosticContext) -> bool:
    if os.name != "nt":
        return False
    server = ctx.server or (ctx.config or {}).get("SQL_SERVER", "")
    if _uses_sqlexpress(server):
        return False
    return _text_has_any(ctx, "sqlexpress", "08001", "server is not found")


def _match_service_stopped(ctx: DiagnosticContext) -> bool:
    if os.name != "nt":
        return False
    server = ctx.server or (ctx.config or {}).get("SQL_SERVER", "")
    if not _uses_sqlexpress(server):
        return False
    from sync_app.core.sql_windows_probe import sqlexpress_service_status

    running, _ = sqlexpress_service_status()
    return running is False


def _match_not_installed(ctx: DiagnosticContext) -> bool:
    if os.name != "nt":
        return False
    server = ctx.server or (ctx.config or {}).get("SQL_SERVER", "")
    if not _uses_sqlexpress(server):
        return False
    from sync_app.core.sql_windows_probe import _service_exists

    return _service_exists("MSSQL$SQLEXPRESS") is False and _text_has_any(
        ctx, "sqlexpress", "08001", "server is not found", "error locating"
    )


def _match_browser_stopped(ctx: DiagnosticContext) -> bool:
    if os.name != "nt":
        return False
    server = ctx.server or (ctx.config or {}).get("SQL_SERVER", "")
    if not _uses_sqlexpress(server):
        return False
    from sync_app.core.sql_windows_probe import sqlexpress_service_status, sql_browser_service_status

    if sqlexpress_service_status()[0] is not True:
        return False
    if sql_browser_service_status() is not False:
        return False
    return _text_has_any(ctx, "error locating", "08001", "server is not found", "login timeout")


_register_sql_rules()
