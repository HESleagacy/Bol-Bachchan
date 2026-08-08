from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.domain.reminders import format_local
from app.persistence.models import PendingAction, User
from app.persistence.repositories import Repository


@dataclass(frozen=True, slots=True)
class AssistantContext:
    user_timezone: str
    current_time: str
    preferences: dict[str, str]
    memories: list[dict[str, object]]
    reminders: list[dict[str, object]]
    timeline_events: list[dict[str, object]]
    documents: list[dict[str, object]]
    pending_action: dict[str, object] | None

    def as_prompt(self) -> str:
        return json.dumps(
            {
                "timezone": self.user_timezone,
                "current_time": self.current_time,
                "preferences": self.preferences,
                "memories": self.memories,
                "upcoming_reminders": self.reminders,
                "upcoming_timeline_events": self.timeline_events,
                "recent_documents": self.documents,
                "pending_action": self.pending_action,
            },
            ensure_ascii=False,
        )


def build_context(repository: Repository, user: User, pending: PendingAction | None) -> AssistantContext:
    now_local = datetime.now(timezone.utc).astimezone(ZoneInfo(user.timezone))
    memories = [
        {"id": item.id, "kind": item.kind, "category": item.category, "content": item.content}
        for item in repository.list_memories(user.id)
    ]
    reminders = [
        {
            "id": item.id,
            "title": item.title,
            "due_at_local": format_local(item.due_at, user.timezone),
        }
        for item in repository.list_upcoming_reminders(user.id)
    ]
    events = [
        {
            "title": item.title,
            "starts_at_local": format_local(item.starts_at, user.timezone),
            "ends_at_local": format_local(item.ends_at, user.timezone),
        }
        for item in repository.list_upcoming_timeline_events(user.id)
    ]
    documents = [
        {"id": item.id, "filename": item.filename, "summary": item.summary}
        for item in repository.list_recent_documents(user.id)
    ]
    pending_payload: dict[str, object] | None = None
    if pending is not None:
        pending_payload = {"action_type": pending.action_type, **pending.payload}
    return AssistantContext(
        user_timezone=user.timezone,
        current_time=f"{now_local.isoformat()} ({now_local.strftime('%A')})",
        preferences=repository.get_preferences(user.id),
        memories=memories,
        reminders=reminders,
        timeline_events=events,
        documents=documents,
        pending_action=pending_payload,
    )
