"""تشخیص خطا و راهکار — هر مشکل یک قانون در rules_wc / rules_sql ثبت می‌شود."""

from __future__ import annotations

import re

from sync_app.core.diagnostics.base import (
    DiagnosticContext,
    DiagnosticRegistry,
    DiagnosticResult,
    DiagnosticRule,
)
from sync_app.core.diagnostics.rules_sql import sql_registry
from sync_app.core.diagnostics.rules_wc import wc_registry

__all__ = [
    "DiagnosticContext",
    "DiagnosticResult",
    "DiagnosticRegistry",
    "DiagnosticRule",
    "diagnose_wc",
    "diagnose_sql",
    "format_wc_error",
    "format_sql_error",
    "register_wc_rule",
    "register_sql_rule",
    "wc_context_from_response",
]


def register_wc_rule(*args, **kwargs) -> None:
    """ثبت قانون جدید WooCommerce — برای افزونه‌ها یا نسخه‌های بعد."""
    wc_registry().register(*args, **kwargs)


def register_sql_rule(*args, **kwargs) -> None:
    """ثبت قانون جدید SQL."""
    sql_registry().register(*args, **kwargs)


def _host_from_config(config) -> str:
    from sync_app.core.network_route_check import host_from_url

    return host_from_url(((config or {}).get("WC_URL") or "").strip(), default="فروشگاه")


def _exc_text(exc) -> str:
    if exc is None:
        return ""
    text = str(exc).strip()
    if not text and getattr(exc, "args", None):
        parts = [str(p).strip() for p in exc.args if p]
        text = "\n".join(parts)
    return text


def diagnose_wc(
    *,
    exc=None,
    error_text: str = "",
    config=None,
    http_status: int | None = None,
    response_snippet: str = "",
    label: str = "",
) -> DiagnosticResult:
    text = (error_text or _exc_text(exc)).strip()
    ctx = DiagnosticContext(
        domain="wc",
        error_text=text,
        config=config,
        http_status=http_status,
        response_snippet=(response_snippet or "").strip(),
        label=label or "",
        host=_host_from_config(config),
        raw_exc=exc if isinstance(exc, BaseException) else None,
    )
    if not ctx.error_text and not ctx.http_status and not ctx.response_snippet:
        return DiagnosticResult(code="wc_unknown", message_fa="خطای نامشخص ووکامرس.", severity="warning")

    result = wc_registry().diagnose(ctx)
    if result is not None:
        return result

    from sync_app.core.connectivity_service import classify_network_error, network_error_user_hint
    from sync_app.core.wc_sync_helper import wc_store_label

    cat = classify_network_error(ctx.error_text)
    if cat != "unknown":
        target = wc_store_label(config or {})
        return DiagnosticResult(
            code=f"wc_{cat}",
            message_fa=network_error_user_hint(cat, target=target),
        )

    host = ctx.host or "فروشگاه"
    return DiagnosticResult(
        code="wc_unknown",
        message_fa=f"اتصال به {host} برقرار نشد.\n{ctx.error_text[:400]}".strip(),
        hints=["اینترنت و VPN را بررسی کنید", "تنظیمات API را ذخیره و دوباره تست کنید"],
        severity="warning",
    )


def diagnose_sql(
    *,
    exc=None,
    error_text: str = "",
    server: str = "",
    config=None,
) -> DiagnosticResult:
    text = (error_text or _exc_text(exc)).strip()
    ctx = DiagnosticContext(
        domain="sql",
        error_text=text,
        config=config,
        server=(server or (config or {}).get("SQL_SERVER") or "").strip(),
        raw_exc=exc if isinstance(exc, BaseException) else None,
    )
    result = sql_registry().diagnose(ctx)
    if result is not None:
        return result
    if text:
        return DiagnosticResult(code="sql_unknown", message_fa=text[:1500], severity="warning")
    return DiagnosticResult(code="sql_unknown", message_fa="", severity="info")


def format_wc_error(exc=None, config=None, **kwargs) -> str:
    return diagnose_wc(exc=exc, config=config, **kwargs).full_message()


def format_sql_error(exc=None, **kwargs) -> str:
    result = diagnose_sql(exc=exc, **kwargs)
    if not result.message_fa and not result.hints:
        return _exc_text(exc) or "خطای نامشخص دیتابیس"
    if result.message_fa and _exc_text(exc) and result.message_fa not in _exc_text(exc):
        return f"{_exc_text(exc)[:800]}\n\n{result.full_message()}"[:1500]
    return result.full_message()[:1500]


def wc_context_from_response(response, *, config=None, label: str = "") -> DiagnosticContext:
    status = getattr(response, "status_code", None)
    status_num = int(status) if status is not None and str(status).isdigit() else None
    snippet = ""
    try:
        from sync_app.core.wc_sync_helper import _wc_response_text_snippet

        snippet = _wc_response_text_snippet(response)
    except Exception:
        text = getattr(response, "text", "") or ""
        snippet = re.sub(r"\s+", " ", text.strip())[:180]

    body_code = ""
    try:
        data = response.json()
        if isinstance(data, dict):
            body_code = str(data.get("code") or "")
    except Exception:
        pass

    err_parts = []
    if status_num:
        err_parts.append(f"HTTP {status_num}")
    if body_code:
        err_parts.append(body_code)
    if snippet:
        err_parts.append(snippet)

    return DiagnosticContext(
        domain="wc",
        error_text=" ".join(err_parts),
        config=config,
        http_status=status_num,
        response_snippet=snippet,
        label=label,
        host=_host_from_config(config),
    )


def wc_raise_from_response(response, *, config=None, label: str = "Woo") -> None:
    """پاسخ HTTP را تشخیص بده و RuntimeError با پیام راهنما بده."""
    ctx = wc_context_from_response(response, config=config, label=label)
    if ctx.http_status and ctx.http_status < 400:
        try:
            data = response.json()
        except Exception as exc:
            ctx.error_text = _exc_text(exc)
            result = diagnose_wc(
                exc=exc,
                config=config,
                http_status=ctx.http_status,
                response_snippet=ctx.response_snippet,
                label=label,
            )
            raise RuntimeError(result.full_message()) from exc
        if isinstance(data, dict) and data.get("code") and not data.get("id"):
            msg = data.get("message") or data.get("code")
            raise RuntimeError(f"{label}: {msg}")
        return
    result = diagnose_wc(
        config=config,
        http_status=ctx.http_status,
        response_snippet=ctx.response_snippet,
        label=label,
        exc=Exception(ctx.error_text or f"HTTP {ctx.http_status}"),
    )
    prefix = f"{label}: " if label and label not in result.message_fa else ""
    raise RuntimeError(f"{prefix}{result.full_message()}".strip())
