"""Optional Google Calendar synchronization.

Configured with an OAuth client and refresh token. Confirmed reminders and
timeline events are mirrored as Calendar events; failures never block the
deterministic reminder pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"


class GoogleCalendarProvider:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        calendar_id: str = "primary",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._calendar_id = calendar_id
        self._timeout_seconds = timeout_seconds

    def create_event(self, title: str, starts_at: datetime, ends_at: datetime, timezone_name: str) -> None:
        import httpx

        token = self._access_token()
        response = httpx.post(
            EVENTS_URL.format(calendar_id=self._calendar_id),
            headers={"Authorization": f"Bearer {token}"},
            json={
                "summary": title,
                "start": {"dateTime": starts_at.isoformat(), "timeZone": timezone_name},
                "end": {"dateTime": ends_at.isoformat(), "timeZone": timezone_name},
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        log.info("Created Google Calendar event for %r", title)

    def _access_token(self) -> str:
        import httpx

        response = httpx.post(
            TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()["access_token"]


def build_calendar_provider(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    calendar_id: str,
) -> GoogleCalendarProvider | None:
    if not client_id or not client_secret or not refresh_token:
        return None
    return GoogleCalendarProvider(client_id, client_secret, refresh_token, calendar_id)
