"""قوانین تشخیص خطای WooCommerce / REST API — قابل افزودن بدون تغییر هسته."""

from __future__ import annotations

import re

from sync_app.core.diagnostics.base import DiagnosticContext, DiagnosticRegistry, DiagnosticResult

_WC_REGISTRY = DiagnosticRegistry("woocommerce")


def wc_registry() -> DiagnosticRegistry:
    return _WC_REGISTRY


def _host(ctx: DiagnosticContext) -> str:
    if ctx.host:
        return ctx.host
    from sync_app.core.network_route_check import host_from_url

    return host_from_url(((ctx.config or {}).get("WC_URL") or "").strip(), default="فروشگاه")


def _has_http(ctx: DiagnosticContext, code: int) -> bool:
    if ctx.http_status == code:
        return True
    return re.search(rf"\b{code}\b", ctx.lowered) is not None


def _text_has_any(ctx: DiagnosticContext, *tokens: str) -> bool:
    low = ctx.lowered
    return any(t.lower() in low for t in tokens if t)


def _rule_forbidden(ctx: DiagnosticContext) -> DiagnosticResult:
    host = _host(ctx)
    return DiagnosticResult(
        code="wc_forbidden",
        message_fa=f"سرور {host} درخواست API را رد کرد (403 Forbidden).",
        hints=[
            "Consumer Key/Secret همین سایت با دسترسی Read/Write",
            "WooCommerce → Settings → Advanced → REST API",
            "پس از تغییر «ذخیره تنظیمات» را بزنید",
            "افزونه امنیتی/WAF (Wordfence و …) — IP را whitelist کنید",
            "Settings → Permalinks → Save",
            "VPN را یک‌بار قطع/وصل کنید",
        ],
    )


def _rule_auth(ctx: DiagnosticContext) -> DiagnosticResult:
    host = _host(ctx)
    return DiagnosticResult(
        code="wc_auth",
        message_fa=f"کلید API {host} نامعتبر، منقضی یا بدون مجوز کافی است.",
        hints=[
            "WooCommerce → Settings → Advanced → REST API → کلید جدید Read/Write",
            "کاربر وردپرس کلید باید مدیر یا Shop Manager باشد",
            "Consumer Key/Secret را کامل و بدون فاصله کپی کنید",
            "در PeechaSync «ذخیره تنظیمات» سپس «تست اتصال»",
        ],
    )


def _rule_cannot_view(ctx: DiagnosticContext) -> DiagnosticResult:
    host = _host(ctx)
    return DiagnosticResult(
        code="wc_cannot_view",
        message_fa=f"احراز هویت API {host} انجام نشد یا مجوز لیست‌کردن منابع نیست.",
        hints=[
            "در مرورگر بدون کلید API همیشه 401 می‌گیرید — طبیعی است",
            "با Consumer Key/Secret درست تست کنید",
            "کلید Read/Write برای کاربر با نقش مناسب بسازید",
        ],
    )


def _rule_invalid_json(ctx: DiagnosticContext) -> DiagnosticResult:
    host = _host(ctx)
    msg = f"سرور {host} به جای JSON پاسخ خالی یا HTML داد."
    if ctx.response_snippet:
        msg += f"\n\nنمونه پاسخ: {ctx.response_snippet}"
    return DiagnosticResult(
        code="wc_invalid_json",
        message_fa=msg,
        hints=[
            "معمولاً API مسدود است یا کلید REST اشتباه است",
            "WooCommerce → REST API — کلید Read/Write جدید",
            "WAF/امنیت سایت را بررسی کنید",
            "Permalinks → Save",
        ],
    )


def _rule_timeout(ctx: DiagnosticContext) -> DiagnosticResult:
    host = _host(ctx)
    return DiagnosticResult(
        code="wc_timeout",
        message_fa=f"شبکه به {host} وصل شد اما پاسخ دیر رسید (timeout).",
        hints=[
            "چند ثانیه صبر کنید و دوباره تلاش کنید",
            "سیم‌کارت/Wi‑Fi یا VPN را عوض کنید",
            "Timeout را در تنظیمات افزایش دهید",
        ],
        severity="warning",
    )


def _rule_ssl(ctx: DiagnosticContext) -> DiagnosticResult:
    host = _host(ctx)
    return DiagnosticResult(
        code="wc_ssl",
        message_fa=f"خطای SSL در اتصال به {host}.",
        hints=[
            "VPN/فیلترشکن را قطع/وصل کنید",
            "در تنظیمات «تأیید SSL» را در صورت نیاز فعال کنید",
            "دوباره تست اتصال بزنید",
        ],
    )


def _rule_dns(ctx: DiagnosticContext) -> DiagnosticResult:
    host = _host(ctx)
    return DiagnosticResult(
        code="wc_dns",
        message_fa=f"اینترنت یا DNS در دسترس نیست — {host} پیدا نشد.",
        hints=[
            "اتصال اینترنت را بررسی کنید",
            "VPN را قطع/وصل کنید",
            "آدرس WC_URL در تنظیمات را بررسی کنید",
        ],
    )


def _rule_vpn_tunnel(ctx: DiagnosticContext) -> DiagnosticResult:
    host = _host(ctx)
    return DiagnosticResult(
        code="wc_vpn_tunnel",
        message_fa=f"اتصال به {host} از تونل/VPN ناقص رد می‌شود.",
        hints=[
            "VPN را کاملاً ببندید (Exit، نه فقط Disconnect)",
            "Docker/WSL را در صورت نیاز خاموش کنید",
            "حالت پرواز ON/OFF",
        ],
    )


def _rule_http_status(ctx: DiagnosticContext, status: int, message: str, hints: list[str]) -> DiagnosticResult:
    return DiagnosticResult(
        code=f"wc_http_{status}",
        message_fa=message,
        hints=hints,
    )


def _register_wc_rules() -> None:
    r = _WC_REGISTRY

    r.register(
        "wc_forbidden",
        priority=10,
        domains=("wc",),
        match=lambda c: _has_http(c, 403) or _text_has_any(c, "forbidden"),
        build=_rule_forbidden,
    )
    r.register(
        "wc_cannot_view",
        priority=15,
        domains=("wc",),
        match=lambda c: _text_has_any(c, "woocommerce_rest_cannot_view", "cannot list", "نمی توانید منابع"),
        build=_rule_cannot_view,
    )
    r.register(
        "wc_auth",
        priority=20,
        domains=("wc",),
        match=lambda c: (
            _has_http(c, 401)
            or _text_has_any(c, "consumer key", "invalid signature", "unauthorized", "authentication")
        ),
        build=_rule_auth,
    )
    r.register(
        "wc_invalid_json",
        priority=30,
        domains=("wc",),
        match=lambda c: _text_has_any(
            c,
            "expecting value",
            "jsondecodeerror",
            "پاسخ json نامعتبر",
            "به جای json",
            "invalid json",
        ),
        build=_rule_invalid_json,
    )
    r.register(
        "wc_vpn_tunnel",
        priority=40,
        domains=("wc",),
        match=lambda c: _text_has_any(
            c, "vpn/تونل", "tunnel", "docker/wsl", "آداپتور مجازی", "172.18.", "172.17."
        ),
        build=_rule_vpn_tunnel,
    )
    r.register(
        "wc_dns",
        priority=50,
        domains=("wc",),
        match=lambda c: _text_has_any(c, "getaddrinfo", "11001", "name or service not known", "nodename"),
        build=_rule_dns,
    )
    r.register(
        "wc_timeout",
        priority=60,
        domains=("wc",),
        match=lambda c: _text_has_any(c, "timed out", "timeout", "connecttimeout", "readtimeout"),
        build=_rule_timeout,
    )
    r.register(
        "wc_ssl",
        priority=70,
        domains=("wc",),
        match=lambda c: _text_has_any(c, "ssl", "certificate", "unexpected_eof", "ssleoferror"),
        build=_rule_ssl,
    )
    r.register(
        "wc_http_404",
        priority=80,
        domains=("wc",),
        match=lambda c: _has_http(c, 404),
        build=lambda c: _rule_http_status(
            c,
            404,
            f"آدرس API {_host(c)} پیدا نشد (404) — WC_URL یا Permalinks را بررسی کنید.",
            ["Settings → Permalinks → Save", "WC_URL باید ریشه سایت باشد (بدون /wp-json)"],
        ),
    )
    r.register(
        "wc_http_5xx",
        priority=90,
        domains=("wc",),
        match=lambda c: ctx_http_5xx(c),
        build=lambda c: _rule_http_status(
            c,
            c.http_status or 500,
            f"خطای سرور {_host(c)} (HTTP {c.http_status or '5xx'}).",
            ["چند دقیقه بعد دوباره تلاش کنید", "با پشتیبانی هاست تماس بگیرید"],
        ),
    )


def ctx_http_5xx(ctx: DiagnosticContext) -> bool:
    if ctx.http_status and 500 <= ctx.http_status <= 599:
        return True
    m = re.search(r"\b(5\d{2})\b", ctx.lowered)
    return m is not None


_register_wc_rules()
