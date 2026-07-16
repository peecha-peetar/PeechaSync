import re
from datetime import datetime


_LOG_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(,\d{3})?(.*)$")


def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621

    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)

    return jy, jm, jd


def format_datetime_jalali(dt=None) -> str:
    """تاریخ/ساعت شمسی برای نمایش در UI."""
    dt = dt or datetime.now()
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    text = f"{jy:04d}/{jm:02d}/{jd:02d} {dt.hour:02d}:{dt.minute:02d}"
    return f"\u2066{text}\u2069"


def format_log_line_jalali(line):
    """ تاریخ لاگ میلادی به شمسی برای نمایش """
    if not line:
        return line

    match = _LOG_PREFIX_RE.match(line)
    if not match:
        return line

    ts, millis, rest = match.groups()
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return line

    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    ms_part = millis or ""

    # تاریخ LTR تا توی فارسی جابه‌جا نشه
    stable_prefix = f"[{jy:04d}/{jm:02d}/{jd:02d} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}{ms_part}]"
    return f"\u2066{stable_prefix}\u2069 {rest.lstrip()}"


def format_log_lines_jalali(lines):
    formatted = []
    for line in lines:
        if line.endswith("\n"):
            formatted.append(format_log_line_jalali(line.rstrip("\n")) + "\n")
        else:
            formatted.append(format_log_line_jalali(line) + "\n")
    return "".join(formatted)
