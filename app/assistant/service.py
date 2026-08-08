from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.assistant.context import build_context
from app.assistant.decision_engine import DecisionEngine, ExecutionResult
from app.assistant.schemas import AssistantDecision, ProposedAction
from app.domain.reminders import parse_natural_interval, parse_natural_schedule
from app.persistence.models import Message, User
from app.persistence.repositories import Repository
from app.providers.gemini import DecisionProvider


log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MediaResult:
    execution: ExecutionResult
    transcript: str | None
    document_summary: str | None
    document_extracted_text: str | None
    document_type: str | None
    document_dates: list[str]
    document_amounts: list[str]
    document_entities: list[str]
    detected_languages: list[str]


class AssistantService:
    def __init__(self, provider: DecisionProvider, decision_engine: DecisionEngine) -> None:
        self._provider = provider
        self._decision_engine = decision_engine

    def handle_text(
        self,
        text: str,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> ExecutionResult:
        provenance_response = self._memory_provenance_response(text, repository, user)
        if provenance_response is not None:
            return ExecutionResult(provenance_response, 0)
        pending = repository.get_pending_action(user.id)
        decision = self._canonical_text_decision(text, repository, user)
        if decision is None:
            context = build_context(repository, user, pending)
            decision = self._provider.interpret(text, context.as_prompt())
        decision = self._normalize_timeline(text, decision, user)
        decision = self._normalize_reschedule(text, decision, repository, user)
        return self._decision_engine.execute(decision, repository, user, source_message, pending)

    def handle_audio(
        self,
        audio: bytes,
        mime_type: str,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> MediaResult:
        pending = repository.get_pending_action(user.id)
        context = build_context(repository, user, pending)
        decision = self._provider.interpret_audio(audio, mime_type, context.as_prompt())
        execution = self._decision_engine.execute(decision, repository, user, source_message, pending)
        detected_languages = getattr(decision, "detected_languages", [])
        if detected_languages:
            try:
                response = self._provider.localize_response(
                    execution.response,
                    detected_languages[0],
                )
                execution = ExecutionResult(response, execution.executed_actions)
            except Exception:
                log.exception("Audio response localization failed; using the original response")
        return self._media_result(execution, decision)

    def handle_document(
        self,
        data: bytes,
        mime_type: str,
        filename: str,
        caption: str | None,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> MediaResult:
        pending = repository.get_pending_action(user.id)
        context = build_context(repository, user, pending)
        decision = self._provider.interpret_document(data, mime_type, filename, caption, context.as_prompt())
        if not caption:
            summary = decision.document_summary or "Document process ho gaya hai."
            decision = decision.model_copy(
                update={
                    "intent": "document_received",
                    "response": f"Maine document padha: {summary}\n\nAap iske saath kya karna chahte hain?",
                    "proposed_actions": [],
                    "missing_fields": [],
                }
            )
        execution = self._decision_engine.execute(decision, repository, user, source_message, pending)
        return self._media_result(execution, decision)

    @staticmethod
    def _media_result(execution: ExecutionResult, decision: AssistantDecision) -> MediaResult:
        return MediaResult(
            execution=execution,
            transcript=decision.transcript,
            document_summary=decision.document_summary,
            document_extracted_text=decision.document_extracted_text,
            document_type=decision.document_type,
            document_dates=decision.document_dates,
            document_amounts=decision.document_amounts,
            document_entities=decision.document_entities,
            detected_languages=getattr(decision, "detected_languages", []),
        )

    @staticmethod
    def _normalize_reschedule(
        text: str,
        decision: AssistantDecision,
        repository: Repository,
        user: User,
    ) -> AssistantDecision:
        if not re.search(r"reschedul|time\s+badal|samay\s+badal|shift|aage\s+kar", text, re.IGNORECASE):
            return decision
        reminders = repository.list_upcoming_reminders(user.id)
        parsed = parse_natural_schedule(text, user.timezone)
        actions = [
            action for action in decision.proposed_actions
            if action.action_type in {"create_reminder", "reschedule_reminder"}
        ]
        target_id = actions[0].reminder_id if actions else None
        if target_id is None and len(reminders) == 1:
            target_id = reminders[0].id
        if target_id is None:
            return decision.model_copy(
                update={
                    "intent": "clarify",
                    "response": "Kaunsa reminder reschedule karna hai?",
                    "proposed_actions": [],
                    "missing_fields": ["reminder_id"],
                }
            )
        if not actions:
            if parsed is None:
                return decision.model_copy(
                    update={
                        "intent": "clarify",
                        "response": "Reminder ka naya date aur time kya hona chahiye?",
                        "proposed_actions": [],
                        "missing_fields": ["scheduled_at"],
                    }
                )
            actions = [
                ProposedAction(
                    action_type="reschedule_reminder",
                    reminder_id=target_id,
                    scheduled_at=parsed.isoformat(),
                )
            ]
            decision = decision.model_copy(
                update={"response": "Reminder ko naye samay par reschedule kar doon?"}
            )
        normalized = actions[0].model_copy(
            update={
                "action_type": "reschedule_reminder",
                "reminder_id": target_id,
                "recurrence_frequency": None,
                "scheduled_at": actions[0].scheduled_at
                or (
                    parsed.isoformat()
                    if parsed
                    else None
                ),
            }
        )
        return decision.model_copy(
            update={
                "intent": "reschedule_reminder",
                "proposed_actions": [normalized],
                "missing_fields": [] if normalized.scheduled_at else ["scheduled_at"],
            }
        )

    @staticmethod
    def _canonical_text_decision(
        text: str,
        repository: Repository,
        user: User,
    ) -> AssistantDecision | None:
        lowered = text.lower()
        quiet = re.search(r"(?:raat|night).*?\b(\d{1,2})(?::(\d{2}))?\b", lowered)
        if quiet and re.search(r"reminder|yaad", lowered) and re.search(r"mat|nahi|dont|don't", lowered):
            hour = int(quiet.group(1))
            minute = int(quiet.group(2) or 0)
            if hour < 12:
                hour += 12
            return AssistantDecision(
                intent="update_preference",
                response=f"Theek hai, raat {hour % 12 or 12} baje ke baad reminders nahi bhejunga.",
                proposed_actions=[
                    ProposedAction(
                        action_type="update_preference",
                        key="quiet_hours_start",
                        value=f"{hour:02d}:{minute:02d}",
                    )
                ],
            )
        if re.search(r"doctor|medical", lowered) and re.search(
            r"ek\s+din\s+pehle|one\s+day\s+before|24\s*(?:hours?|ghante)", lowered
        ):
            return AssistantDecision(
                intent="update_preference",
                response="Theek hai, doctor appointments ke liye ek din pehle bhi yaad dilaunga.",
                proposed_actions=[
                    ProposedAction(
                        action_type="update_preference",
                        key="medical_appointment_reminder_minutes",
                        value="1440",
                    )
                ],
            )
        if re.search(r"usually|aksar|aam\s+taur|normally", lowered) and not re.search(
            r"remind|reminder|yaad\s+dila", lowered
        ):
            return AssistantDecision(
                intent="store_memory",
                response="Theek hai, maine ise aapki routine ke roop mein yaad rakh liya.",
                proposed_actions=[
                    ProposedAction(
                        action_type="store_memory",
                        kind="routine",
                        category="routine",
                        content=text.strip(),
                        confidence=1.0,
                    )
                ],
            )
        before = re.search(
            r"\b(\d+|ek|do|teen)\s*(?:din|days?)\s*(?:pehle|before)\b",
            lowered,
        )
        if before:
            documents = repository.list_recent_documents(user.id, limit=1)
            if documents and documents[0].extracted_dates:
                amount = {"ek": 1, "do": 2, "teen": 3}.get(before.group(1), None)
                days = amount if amount is not None else int(before.group(1))
                try:
                    due_date = datetime.fromisoformat(documents[0].extracted_dates[0]).date()
                except ValueError:
                    return AssistantDecision(
                        intent="clarify",
                        response="Document ki due date saaf nahi mili. Date dobara batayein.",
                        missing_fields=["scheduled_at"],
                    )
                local_due = datetime.combine(
                    due_date - timedelta(days=days),
                    time(9, 0),
                    tzinfo=ZoneInfo(user.timezone),
                ).astimezone(timezone.utc)
                return AssistantDecision(
                    intent="create_reminder",
                    response=f"Due date se {days} din pehle subah 9 baje reminder laga doon?",
                    proposed_actions=[
                        ProposedAction(
                            action_type="create_reminder",
                            title=f"{documents[0].document_type or documents[0].filename} due soon",
                            scheduled_at=local_due.isoformat(),
                            category="bill",
                        )
                    ],
                )
        return None

    @staticmethod
    def _normalize_timeline(
        text: str,
        decision: AssistantDecision,
        user: User,
    ) -> AssistantDecision:
        interval = parse_natural_interval(text, user.timezone)
        if interval is None or not re.search(r"appointment|event|meeting|commitment", text, re.IGNORECASE):
            return decision
        starts_at, ends_at = interval
        existing = next(
            (action for action in decision.proposed_actions if action.action_type == "create_timeline_event"),
            None,
        )
        title = existing.title if existing and existing.title else (
            "Doctor appointment" if re.search(r"doctor", text, re.IGNORECASE) else "Timeline event"
        )
        action = (existing or ProposedAction(action_type="create_timeline_event")).model_copy(
            update={
                "title": title,
                "starts_at": existing.starts_at if existing and existing.starts_at else starts_at.isoformat(),
                "ends_at": existing.ends_at if existing and existing.ends_at else ends_at.isoformat(),
                "event_category": existing.event_category if existing and existing.event_category else (
                    "medical_appointment" if re.search(r"doctor", text, re.IGNORECASE) else "personal"
                ),
            }
        )
        return decision.model_copy(
            update={
                "intent": "create_timeline_event",
                "response": decision.response or f"'{title}' timeline mein add kar doon?",
                "proposed_actions": [action],
                "missing_fields": [],
            }
        )

    @staticmethod
    def _memory_provenance_response(
        text: str,
        repository: Repository,
        user: User,
    ) -> str | None:
        if not re.search(
            r"kaise\s+pata|how\s+do\s+you\s+know|why\s+do\s+you\s+think|source|kab\s+bataya",
            text,
            re.IGNORECASE,
        ):
            return None
        memories = repository.list_memories(user.id)
        if not memories:
            return "Mere paas is baat ki koi stored source nahi hai."
        query_words = {
            word for word in re.findall(r"[a-z0-9]+", text.lower())
            if len(word) > 2
        }
        memory = max(
            memories,
            key=lambda item: len(query_words & set(re.findall(r"[a-z0-9]+", item.content.lower()))),
        )
        source = repository.session.get(Message, memory.source_message_id)
        if source is None:
            return "Yeh memory stored hai, lekin iska original source message nahi mila."
        original = source.text or source.transcript or "[media message]"
        date = source.created_at.strftime("%d %b %Y")
        return (
            f"Aapne {date} ko kaha tha: “{original}”\n\n"
            f"Isi source se maine yaad rakha: {memory.content}"
        )
