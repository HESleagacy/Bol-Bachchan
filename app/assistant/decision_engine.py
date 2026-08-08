from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.assistant.schemas import AssistantDecision, ProposedAction
from app.domain.reminders import as_utc, ensure_future, format_local, parse_user_datetime
from app.domain.timeline import Interval, find_conflicts
from app.persistence.models import Message, PendingAction, User
from app.persistence.repositories import Repository

log = logging.getLogger(__name__)

PREFERENCE_KEY = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
DIRECT_ACTIONS = {"store_memory", "update_preference"}
CONFIRM_ACTIONS = {"create_reminder", "create_timeline_event", "cancel_reminder", "forget_memory"}
DEFAULT_EVENT_MINUTES = 60


class CalendarSync(Protocol):
    def create_event(self, title: str, starts_at: datetime, ends_at: datetime, timezone_name: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    response: str
    executed_actions: int


class ValidationFailure(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class DecisionEngine:
    def __init__(self, pending_action_ttl_minutes: int, calendar: CalendarSync | None = None) -> None:
        self._pending_action_ttl_minutes = pending_action_ttl_minutes
        self._calendar = calendar

    def execute(
        self,
        decision: AssistantDecision,
        repository: Repository,
        user: User,
        source_message: Message,
        pending: PendingAction | None,
    ) -> ExecutionResult:
        if decision.intent == "confirm_action":
            return self._execute_confirmed(decision, repository, user, source_message, pending)

        if decision.intent == "clarify" or decision.missing_fields:
            partial = [action.model_dump(mode="json") for action in decision.proposed_actions]
            action_type = decision.proposed_actions[0].action_type if decision.proposed_actions else decision.intent
            repository.replace_pending_action(
                user_id=user.id,
                source_message_id=source_message.id,
                action_type=action_type,
                payload={
                    "stage": "clarify",
                    "proposed_actions": partial,
                    "missing_fields": decision.missing_fields,
                },
                ttl_minutes=self._pending_action_ttl_minutes,
            )
            return ExecutionResult(decision.response, 0)

        direct = [a for a in decision.proposed_actions if a.action_type in DIRECT_ACTIONS]
        deferred = [a for a in decision.proposed_actions if a.action_type in CONFIRM_ACTIONS]

        try:
            conflict_note = self._validate_deferred(deferred, repository, user)
        except ValidationFailure as failure:
            repository.resolve_pending_action(pending)
            return ExecutionResult(failure.user_message, 0)

        executed = self._execute_direct(direct, repository, user, source_message)
        repository.resolve_pending_action(pending)

        if deferred:
            repository.replace_pending_action(
                user_id=user.id,
                source_message_id=source_message.id,
                action_type="confirm",
                payload={
                    "stage": "confirm",
                    "proposed_actions": [a.model_dump(mode="json") for a in deferred],
                },
                ttl_minutes=self._pending_action_ttl_minutes,
            )
            return ExecutionResult(decision.response + conflict_note, executed)

        return ExecutionResult(decision.response, executed)

    def _execute_confirmed(
        self,
        decision: AssistantDecision,
        repository: Repository,
        user: User,
        source_message: Message,
        pending: PendingAction | None,
    ) -> ExecutionResult:
        if pending is None or pending.payload.get("stage") != "confirm":
            return ExecutionResult(decision.response, 0)
        actions = [
            ProposedAction.model_validate(raw)
            for raw in pending.payload.get("proposed_actions", [])
        ]
        try:
            self._validate_deferred(actions, repository, user)
        except ValidationFailure as failure:
            repository.resolve_pending_action(pending)
            return ExecutionResult(failure.user_message, 0)

        executed = 0
        for action in actions:
            executed += self._execute_confirmed_action(action, repository, user, source_message)
        repository.resolve_pending_action(pending)
        return ExecutionResult(decision.response, executed)

    def _execute_direct(
        self,
        actions: list[ProposedAction],
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> int:
        executed = 0
        for action in actions:
            if action.action_type == "store_memory":
                if not action.content:
                    raise ValueError("store_memory requires content")
                repository.add_memory(
                    user_id=user.id,
                    source_message_id=source_message.id,
                    kind=action.kind or "personal_fact",
                    category=action.category or "general",
                    content=action.content,
                    confidence=action.confidence,
                )
                executed += 1
            elif action.action_type == "update_preference":
                key = action.key or ""
                if not PREFERENCE_KEY.fullmatch(key) or action.value is None:
                    raise ValueError(f"Invalid preference key: {key!r}")
                repository.set_preference(user.id, source_message.id, key, action.value)
                executed += 1
        return executed

    def _execute_confirmed_action(
        self,
        action: ProposedAction,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> int:
        if action.action_type == "create_reminder":
            due_at = parse_user_datetime(action.scheduled_at or "", user.timezone)
            repository.add_reminder(
                user_id=user.id,
                source_message_id=source_message.id,
                title=action.title or "",
                due_at=due_at,
                timezone_name=user.timezone,
            )
            self._sync_calendar(action.title or "", due_at, due_at + timedelta(minutes=DEFAULT_EVENT_MINUTES), user.timezone)
            return 1
        if action.action_type == "create_timeline_event":
            starts_at = parse_user_datetime(action.starts_at or "", user.timezone)
            ends_at = parse_user_datetime(action.ends_at or "", user.timezone)
            repository.add_timeline_event(
                user_id=user.id,
                source_message_id=source_message.id,
                title=action.title or "",
                starts_at=starts_at,
                ends_at=ends_at,
            )
            self._sync_calendar(action.title or "", starts_at, ends_at, user.timezone)
            return 1
        if action.action_type == "cancel_reminder":
            if action.reminder_id is None or not repository.cancel_reminder(user.id, action.reminder_id):
                raise ValidationFailure("Yeh reminder ab pending nahi hai, isliye cancel nahi ho paya.")
            return 1
        if action.action_type == "forget_memory":
            if action.memory_id is None or not repository.forget_memory(user.id, action.memory_id):
                raise ValidationFailure("Yeh yaad nahi mili, isliye kuch delete nahi hua.")
            return 1
        return 0

    def _validate_deferred(
        self,
        actions: list[ProposedAction],
        repository: Repository,
        user: User,
    ) -> str:
        conflict_note = ""
        intervals = [
            Interval(title=event.title, starts_at=as_utc(event.starts_at), ends_at=as_utc(event.ends_at))
            for event in repository.list_upcoming_timeline_events(user.id, limit=50)
        ]
        for action in actions:
            if action.action_type == "create_reminder":
                if not action.title:
                    raise ValidationFailure("Reminder ka title samajh nahi aaya, dobara batayein.")
                due_at = self._parse_or_fail(action.scheduled_at, user.timezone)
                if not ensure_future(due_at):
                    raise ValidationFailure("Yeh samay pehle hi guzar chuka hai. Naya samay batayein.")
                conflict_note += self._conflict_note(find_conflicts(intervals, due_at), user.timezone)
            elif action.action_type == "create_timeline_event":
                if not action.title:
                    raise ValidationFailure("Event ka title samajh nahi aaya, dobara batayein.")
                starts_at = self._parse_or_fail(action.starts_at, user.timezone)
                ends_at = self._parse_or_fail(action.ends_at, user.timezone)
                if ends_at <= starts_at:
                    raise ValidationFailure("Event ka end time start ke baad hona chahiye.")
                conflict_note += self._conflict_note(find_conflicts(intervals, starts_at, ends_at), user.timezone)
            elif action.action_type == "cancel_reminder":
                if action.reminder_id is None or repository.get_reminder(user.id, action.reminder_id) is None:
                    raise ValidationFailure("Yeh reminder nahi mila. Pehle apne reminders ki list dekh lein.")
            elif action.action_type == "forget_memory":
                if action.memory_id is None or repository.get_memory(user.id, action.memory_id) is None:
                    raise ValidationFailure("Yeh yaad nahi mili. Pehle apni memories ki list dekh lein.")
        return conflict_note

    @staticmethod
    def _parse_or_fail(value: str | None, timezone_name: str) -> datetime:
        try:
            return parse_user_datetime(value or "", timezone_name)
        except ValueError as exc:
            raise ValidationFailure("Samay samajh nahi aaya. Date aur time dobara batayein.") from exc

    @staticmethod
    def _conflict_note(conflicts: list[Interval], timezone_name: str) -> str:
        if not conflicts:
            return ""
        first = conflicts[0]
        window = f"{format_local(first.starts_at, timezone_name)} - {format_local(first.ends_at, timezone_name)}"
        return f"\n\nDhyan dein: is samay '{first.title}' ({window}) bhi hai."

    def _sync_calendar(self, title: str, starts_at: datetime, ends_at: datetime, timezone_name: str) -> None:
        if self._calendar is None:
            return
        try:
            self._calendar.create_event(title, starts_at, ends_at, timezone_name)
        except Exception:
            log.exception("Calendar sync failed for %r; continuing without it", title)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
