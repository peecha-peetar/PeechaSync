"""هسته تشخیص خطا — هر مشکل یک قانون ثبت‌شده، بدون if/else بسته در UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class DiagnosticContext:
    """ورودی مشترک برای همه قوانین تشخیص."""

    domain: str = ""  # wc | sql
    error_text: str = ""
    config: dict | None = None
    http_status: int | None = None
    response_snippet: str = ""
    label: str = ""
    server: str = ""
    host: str = ""
    raw_exc: BaseException | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def lowered(self) -> str:
        return (self.error_text or "").lower()

    def with_host(self, host: str) -> DiagnosticContext:
        self.host = (host or "").strip()
        return self


@dataclass
class DiagnosticResult:
    """خروجی تشخیص — پیام، اقدام پیشنهادی، قابلیت رفع خودکار."""

    code: str
    message_fa: str
    hints: list[str] = field(default_factory=list)
    action_label: str = ""
    action_id: str = ""
    can_auto_fix: bool = False
    severity: str = "error"  # warning | info

    def full_message(self, *, include_hints: bool = True) -> str:
        parts = [self.message_fa.strip()] if self.message_fa else []
        if include_hints and self.hints:
            block = "\n".join(f"• {h}" for h in self.hints if h)
            if block:
                parts.append(block)
        return "\n\n".join(p for p in parts if p)

    def to_dict(self) -> dict[str, Any]:
        """سازگاری با UI قدیمی (settings_tab و ...)."""
        return {
            "code": self.code,
            "message_fa": self.message_fa,
            "action_label": self.action_label,
            "action_id": self.action_id or self.code,
            "can_auto_fix": self.can_auto_fix,
            "hints": list(self.hints),
            "severity": self.severity,
        }


Matcher = Callable[[DiagnosticContext], bool]
Builder = Callable[[DiagnosticContext], DiagnosticResult]


@dataclass
class DiagnosticRule:
    code: str
    priority: int
    match: Matcher
    build: Builder
    domains: tuple[str, ...] = ()


class DiagnosticRegistry:
    """ثبت قوانین — اولویت کمتر = زودتر بررسی می‌شود."""

    def __init__(self, name: str):
        self.name = name
        self._rules: list[DiagnosticRule] = []

    def register(
        self,
        code: str,
        *,
        priority: int,
        match: Matcher,
        build: Builder,
        domains: tuple[str, ...] = (),
    ) -> None:
        self._rules.append(
            DiagnosticRule(
                code=code,
                priority=int(priority),
                match=match,
                build=build,
                domains=domains,
            )
        )
        self._rules.sort(key=lambda r: r.priority)

    def diagnose(self, ctx: DiagnosticContext) -> DiagnosticResult | None:
        domain = (ctx.domain or "").strip().lower()
        for rule in self._rules:
            if rule.domains and domain not in rule.domains:
                continue
            try:
                if rule.match(ctx):
                    return rule.build(ctx)
            except Exception:
                continue
        return None

    def diagnose_or_unknown(self, ctx: DiagnosticContext, *, unknown_code: str, unknown_msg: str) -> DiagnosticResult:
        found = self.diagnose(ctx)
        if found is not None:
            return found
        return DiagnosticResult(code=unknown_code, message_fa=unknown_msg, severity="warning")
