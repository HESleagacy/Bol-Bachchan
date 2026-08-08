from __future__ import annotations

from datetime import datetime, time, timedelta


def parse_quiet_time(value: str) -> time | None:
    value = value.strip()
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


def is_quiet(now_local: datetime, start: time, end: time) -> bool:
    current = now_local.time()
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def next_allowed_time(now_local: datetime, start_str: str | None, end_str: str | None) -> datetime | None:
    """Return the next permitted local delivery time, or None when delivery is allowed now."""
    if not start_str or not end_str:
        return None
    start = parse_quiet_time(start_str)
    end = parse_quiet_time(end_str)
    if start is None or end is None or not is_quiet(now_local, start, end):
        return None
    allowed = now_local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if allowed <= now_local:
        allowed += timedelta(days=1)
    return allowed
