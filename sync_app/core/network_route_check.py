"""تشخیص مسیریابی از تونل/VPN ناقص (Docker، WSL، VPN) — TCP وصل، HTTPS قطع."""

from __future__ import annotations

import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlparse

# Docker Desktop / WSL / Hyper-V — در تست واقعی با 172.18.0.1 دیده شد
_TUNNEL_LOCAL_PREFIXES = (
    "127.",
    "169.254.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
)

# هاستینگ خارجی — اگر IP عمومی این باشد ولی سایت ایرانی است، احتمال VPN
_FOREIGN_HOSTING_KEYWORDS = (
    "hetzner",
    "digitalocean",
    "amazon",
    "google cloud",
    "microsoft azure",
    "ovh",
    "contabo",
    "linode",
)


def host_from_url(url: str, default: str = "") -> str:
    raw = (url or "").strip()
    if not raw:
        return (default or "").strip().lower()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or default or "").strip().lower()


def is_tunnel_local_ip(ip: str) -> bool:
    ip = (ip or "").strip()
    if not ip:
        return False
    if any(ip.startswith(prefix) for prefix in _TUNNEL_LOCAL_PREFIXES):
        return True
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_loopback or addr.is_link_local:
            return True
    except ValueError:
        pass
    return False


def get_outbound_local_ip(host: str, port: int = 443, *, timeout: float = 8.0) -> tuple[str | None, float | None, str]:
    """
    IP محلی سوکت خروجی به host:port.
    برمی‌گرداند: (local_ip, connect_ms, error)
    """
    host = (host or "").strip()
    if not host:
        return None, None, "host خالی"
    sock = None
    t0 = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        return sock.getsockname()[0], ms, ""
    except Exception as exc:
        return None, None, str(exc)[:120]
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _quick_tls_ok(host: str, *, timeout: float = 6.0) -> bool:
    import ssl

    ctx = ssl.create_default_context()
    raw = None
    try:
        raw = socket.create_connection((host, 443), timeout=timeout)
        with ctx.wrap_socket(raw, server_hostname=host) as secure:
            secure.do_handshake()
        return True
    except Exception:
        return False
    finally:
        if raw is not None:
            try:
                raw.close()
            except Exception:
                pass


def _quick_public_ip_hint() -> dict[str, str]:
    """اختیاری — بدون وابستگی سنگین؛ فقط برای تقویت هشدار."""
    try:
        import requests

        resp = requests.get(
            "http://ip-api.com/json/?fields=status,query,isp,org,hosting",
            timeout=4,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json() if resp.content else {}
        if not isinstance(data, dict) or data.get("status") != "success":
            return {}
        isp = f"{data.get('isp', '')} {data.get('org', '')}".lower()
        foreign = any(k in isp for k in _FOREIGN_HOSTING_KEYWORDS) or bool(data.get("hosting"))
        return {
            "public_ip": str(data.get("query") or ""),
            "isp": str(data.get("isp") or ""),
            "foreign_hosting": "1" if foreign else "0",
        }
    except Exception:
        return {}


def detect_broken_tunnel(host: str, *, wc_failed_timeout_or_ssl: bool = False) -> dict[str, Any]:
    """
    الگوی VPN/تونل ناقص:
    - IP محلی 172.18.x / Docker / loopback
    - TCP سریع ولی TLS شکست (وقتی WC هم timeout داده)
    - IP عمومی هاستینگ خارجی (مثلاً Hetzner) در حالی که به سیم‌کارت وصلید
    """
    host = host_from_url(host)
    local_ip, connect_ms, bind_err = get_outbound_local_ip(host, 443, timeout=8.0)

    reasons: list[str] = []
    suspected = False

    if local_ip and is_tunnel_local_ip(local_ip):
        suspected = True
        reasons.append(f"ترافیک از آداپتور مجازی {local_ip} رد می‌شود (Docker/WSL/VPN)")

    tls_ok = None
    if local_ip and wc_failed_timeout_or_ssl:
        tls_ok = _quick_tls_ok(host, timeout=6.0)
        if not tls_ok and connect_ms is not None and connect_ms < 80:
            suspected = True
            reasons.append("TCP وصل است اما HTTPS/TLS کامل نمی‌شود (الگوی VPN ناقص)")

    ip_hint = _quick_public_ip_hint() if suspected or wc_failed_timeout_or_ssl else {}
    if ip_hint.get("foreign_hosting") == "1":
        suspected = True
        isp = ip_hint.get("isp") or "خارجی"
        pub = ip_hint.get("public_ip") or "?"
        reasons.append(f"IP عمومی {pub} ({isp}) — احتمال VPN فعال")

    if not suspected:
        return {
            "suspected": False,
            "host": host,
            "local_ip": local_ip or "",
            "connect_ms": connect_ms,
            "tls_ok": tls_ok,
            "bind_error": bind_err,
            "reasons": [],
            "user_message_fa": "",
        }

    user_message_fa = (
        "احتمال VPN/تونل ناقص — ووکامرس وصل نمی‌شود.\n"
        "VPN را کاملاً ببندید (Exit)، Docker Desktop را خاموش کنید، "
        "یا پس از تعویض سیم‌کارت حالت پرواز را ON/OFF کنید."
    )
    if reasons:
        user_message_fa = f"{reasons[0]}.\n{user_message_fa}"

    return {
        "suspected": True,
        "host": host,
        "local_ip": local_ip or "",
        "connect_ms": connect_ms,
        "tls_ok": tls_ok,
        "bind_error": bind_err,
        "public_ip": ip_hint.get("public_ip", ""),
        "isp": ip_hint.get("isp", ""),
        "reasons": reasons,
        "user_message_fa": user_message_fa,
    }
