from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Event, Thread
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.domain.preferences import next_allowed_time
from app.domain.reminders import as_utc
from app.persistence.database import Database
from app.persistence.models import Reminder, User
from app.persistence.repositories import Repository
from app.transport.base import MessageTransport
from app.workers.message_worker import format_assistant_response

log = logging.getLogger(__name__)


class ReminderWorker:
    """Database-backed polling worker. The database owns reminder state, which
    makes delivery recoverable after an application restart."""

    def __init__(
        self,
        database: Database,
        transport: MessageTransport,
        owner_jid: str,
        poll_seconds: int = 10,
    ) -> None:
        self._database = database
        self._transport = transport
        self._owner_jid = owner_jid
        self._poll_seconds = poll_seconds
        self._stopping = Event()
        self._thread = Thread(target=self._run, name="reminder-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=10)

    def deliver_due_reminders(self) -> int:
        now = datetime.now(timezone.utc)
        delivered = 0
        with self._database.session() as session:
            due_ids = [
                reminder.id
                for reminder in session.scalars(select(Reminder).where(Reminder.status == "pending"))
                if as_utc(reminder.due_at) <= now
            ]
        for reminder_id in due_ids:
            if self._deliver_one(reminder_id):
                delivered += 1
        return delivered

    def _deliver_one(self, reminder_id: int) -> bool:
        with self._database.session() as session:
            claimed = session.execute(
                update(Reminder)
                .where(Reminder.id == reminder_id, Reminder.status == "pending")
                .values(status="delivering")
            )
            if claimed.rowcount != 1:
                return False
            reminder = session.get(Reminder, reminder_id)
            user = session.get(User, reminder.user_id)
            repository = Repository(session)
            preferences = repository.get_preferences(user.id)

            deferred_to = self._quiet_hours_deferral(reminder, preferences)
            if deferred_to is not None:
                reminder.due_at = deferred_to
                reminder.status = "pending"
                log.info("Reminder %s deferred to %s by quiet hours", reminder.id, deferred_to)
                return False

            chat_jid = user.chat_jid or user.whatsapp_jid
            try:
                outbound = self._transport.send_text(
                    chat_jid,
                    format_assistant_response(f"Reminder: {reminder.title}"),
                )
            except Exception:
                log.exception("Reminder %s delivery failed; will retry", reminder.id)
                reminder.status = "pending"
                return False
            repository.add_outbound(user, outbound)
            reminder.status = "delivered"
            reminder.delivered_at = datetime.now(timezone.utc)
            log.info("Delivered reminder %s: %s", reminder.id, reminder.title)
            return True

    @staticmethod
    def _quiet_hours_deferral(reminder: Reminder, preferences: dict[str, str]) -> datetime | None:
        timezone_name = reminder.timezone or "UTC"
        now_local = datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name))
        allowed_local = next_allowed_time(
            now_local,
            preferences.get("quiet_hours_start"),
            preferences.get("quiet_hours_end"),
        )
        if allowed_local is None:
            return None
        return allowed_local.astimezone(timezone.utc)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.deliver_due_reminders()
            except Exception:
                log.exception("Reminder polling cycle failed")
            self._stopping.wait(self._poll_seconds)
