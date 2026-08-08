from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal[
    "create_reminder",
    "store_memory",
    "update_preference",
    "answer_question",
    "document_received",
    "clarify",
    "confirm_action",
]
ActionType = Literal[
    "create_reminder",
    "store_memory",
    "update_preference",
    "create_timeline_event",
    "cancel_reminder",
    "forget_memory",
]


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: ActionType
    content: str | None = None
    kind: str | None = None
    category: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    key: str | None = None
    value: str | None = None
    title: str | None = None
    scheduled_at: str | None = Field(
        default=None,
        description="ISO 8601 datetime with offset for create_reminder",
    )
    starts_at: str | None = Field(
        default=None,
        description="ISO 8601 start datetime for create_timeline_event",
    )
    ends_at: str | None = Field(
        default=None,
        description="ISO 8601 end datetime for create_timeline_event",
    )
    reminder_id: int | None = Field(
        default=None,
        description="Existing reminder id for cancel_reminder",
    )
    memory_id: int | None = Field(
        default=None,
        description="Existing memory id for forget_memory",
    )


class AssistantDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    response: str = Field(min_length=1)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    transcript: str | None = Field(
        default=None,
        description="Verbatim transcript when the input is audio",
    )
    document_summary: str | None = Field(
        default=None,
        description="Short summary when the input is a document or image",
    )
    document_extracted_text: str | None = Field(
        default=None,
        description="Extracted text or OCR content when the input is a document or image",
    )
