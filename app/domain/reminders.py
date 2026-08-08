from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def parse_user_datetime(value: str, user_timezone: str) -> datetime:
    """Parse an ISO 8601 datetime from a Gemini decision into an aware UTC datetime.

    Naive values are interpreted in the user's timezone. Gemini interprets the
    human request; this function makes the timestamp authoritative.
    """
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(user_timezone))
    return parsed.astimezone(timezone.utc)


def ensure_future(due_at: datetime, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return due_at > now


def as_utc(value: datetime) -> datetime:
    """Attach UTC to naive datetimes loaded from SQLite."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_local(value: datetime, user_timezone: str) -> str:
    return as_utc(value).astimezone(ZoneInfo(user_timezone)).strftime("%d %b %Y, %I:%M %p")
