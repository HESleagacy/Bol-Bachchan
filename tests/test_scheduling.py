from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.assistant.decision_engine import DecisionEngine
from app.assistant.schemas import AssistantDecision, ProposedAction
from app.assistant.service import AssistantService
from app.domain.messages import InboundMessage, MessageType, OutboundMessage
from app.persistence.database import Database
from app.persistence.models import Base, PendingAction, Reminder, TimelineEvent
from app.persistence.repositories import Repository
from app.workers.message_worker import MessageWorker

OWNER = "919876543210@s.whatsapp.net"


class FakeProvider:
    def __init__(self, decisions: list[AssistantDecision]) -> None:
        self.decisions = decisions
        self.contexts: list[str] = []

    def interpret(self, _message: str, context: str) -> AssistantDecision:
        self.contexts.append(context)
        return self.decisions.pop(0)


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    def set_message_handler(self, _handler: object) -> None:
        pass

    def send_text(self, chat_jid: str, text: str) -> OutboundMessage:
        outbound = OutboundMessage(
            whatsapp_message_id=f"out-{len(self.sent) + 1}",
            chat_jid=chat_jid,
            text=text,
            occurred_at=datetime.now(timezone.utc),
        )
        self.sent.append(outbound)
        return outbound

    def send_voice_note(self, chat_jid: str, audio: bytes) -> OutboundMessage:
        raise AssertionError("voice should not be used in these tests")

    def download_media(self, whatsapp_message_id: str) -> bytes | None:
        return None

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass


def inbound(message_id: str, text: str) -> InboundMessage:
    return InboundMessage(
        whatsapp_message_id=message_id,
        chat_jid=OWNER,
        sender_jid=OWNER,
        message_type=MessageType.TEXT,
        text=text,
        occurred_at=datetime.now(timezone.utc),
        is_from_me=True,
        is_self_chat=True,
    )


def make_worker(tmp_path: Path, provider: FakeProvider) -> tuple[MessageWorker, Database, FakeTransport]:
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(database.engine)
    transport = FakeTransport()
    assistant = AssistantService(provider, DecisionEngine(pending_action_ttl_minutes=30))
    worker = MessageWorker(database, assistant, transport, OWNER, "Asia/Kolkata", media_dir=tmp_path / "media")
    return worker, database, transport


def reminder_decision(due_at: datetime, title: str = "Call Ramesh") -> AssistantDecision:
    return AssistantDecision(
        intent="create_reminder",
        response="Reminder laga doon?",
        proposed_actions=[
            ProposedAction(action_type="create_reminder", title=title, scheduled_at=due_at.isoformat())
        ],
    )


def confirmation_decision() -> AssistantDecision:
    return AssistantDecision(intent="confirm_action", response="Reminder laga diya.")


def test_reminder_requires_confirmation_then_executes(tmp_path: Path) -> None:
    due_at = datetime.now(timezone.utc) + timedelta(hours=4)
    provider = FakeProvider([reminder_decision(due_at), confirmation_decision()])
    worker, database, transport = make_worker(tmp_path, provider)

    worker.process(inbound("in-1", "Kal 5 baje Ramesh ko call karna"))
    with database.session() as session:
        assert session.scalar(select(Reminder)) is None
        pending = session.scalar(select(PendingAction).where(PendingAction.status == "pending"))
        assert pending is not None and pending.payload["stage"] == "confirm"

    worker.process(inbound("in-2", "Haan"))
    with database.session() as session:
        reminder = session.scalar(select(Reminder))
        assert reminder is not None
        assert reminder.title == "Call Ramesh"
        assert reminder.status == "pending"
        pending = session.scalar(select(PendingAction))
        assert pending.status == "resolved"
    assert transport.sent[-1].text.endswith("Reminder laga diya.")


def test_non_confirming_reply_dismisses_pending_confirmation(tmp_path: Path) -> None:
    due_at = datetime.now(timezone.utc) + timedelta(hours=4)
    provider = FakeProvider(
        [
            reminder_decision(due_at),
            AssistantDecision(intent="answer_question", response="Theek hai, cancel."),
        ]
    )
    worker, database, _transport = make_worker(tmp_path, provider)

    worker.process(inbound("in-1", "Kal 5 baje Ramesh ko call karna"))
    worker.process(inbound("in-2", "Nahin rehne do"))

    with database.session() as session:
        assert session.scalar(select(Reminder)) is None
        pending = session.scalar(select(PendingAction))
        assert pending.status == "resolved"


def test_past_reminder_time_is_rejected_deterministically(tmp_path: Path) -> None:
    due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    provider = FakeProvider([reminder_decision(due_at)])
    worker, database, transport = make_worker(tmp_path, provider)

    worker.process(inbound("in-1", "Reminder for earlier today"))

    with database.session() as session:
        assert session.scalar(select(Reminder)) is None
        assert session.scalar(select(PendingAction)) is None
    assert "guzar chuka" in transport.sent[-1].text


def test_conflict_note_is_appended_from_timeline(tmp_path: Path) -> None:
    event_start = datetime.now(timezone.utc) + timedelta(days=1)
    provider = FakeProvider(
        [reminder_decision(event_start + timedelta(minutes=30), title="Call Ramesh")]
    )
    worker, database, transport = make_worker(tmp_path, provider)

    with database.session() as session:
        repository = Repository(session)
        user = repository.get_or_create_user(OWNER, "Asia/Kolkata")
        message = repository.add_inbound(user, inbound("seed", "seed"))
        repository.add_timeline_event(
            user_id=user.id,
            source_message_id=message.id,
            title="Doctor appointment",
            starts_at=event_start,
            ends_at=event_start + timedelta(hours=1),
        )

    worker.process(inbound("in-1", "Us waqt Ramesh ko call karna"))

    assert "Doctor appointment" in transport.sent[-1].text


def test_cancel_reminder_confirmation_flow(tmp_path: Path) -> None:
    due_at = datetime.now(timezone.utc) + timedelta(hours=6)
    provider = FakeProvider(
        [
            reminder_decision(due_at),
            confirmation_decision(),
        ]
    )
    worker, database, _transport = make_worker(tmp_path, provider)
    worker.process(inbound("in-1", "Reminder set karo"))
    worker.process(inbound("in-2", "Haan"))

    with database.session() as session:
        reminder_id = session.scalar(select(Reminder)).id

    provider.decisions = [
        AssistantDecision(
            intent="answer_question",
            response="Cancel kar doon?",
            proposed_actions=[ProposedAction(action_type="cancel_reminder", reminder_id=reminder_id)],
        ),
        AssistantDecision(intent="confirm_action", response="Cancel kar diya."),
    ]
    worker.process(inbound("in-3", "Woh reminder cancel karo"))
    worker.process(inbound("in-4", "Haan"))

    with database.session() as session:
        assert session.scalar(select(Reminder)).status == "cancelled"


def test_timeline_event_created_after_confirmation(tmp_path: Path) -> None:
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    provider = FakeProvider(
        [
            AssistantDecision(
                intent="create_reminder",
                response="Event bana doon?",
                proposed_actions=[
                    ProposedAction(
                        action_type="create_timeline_event",
                        title="Team standup",
                        starts_at=starts_at.isoformat(),
                        ends_at=(starts_at + timedelta(hours=1)).isoformat(),
                    )
                ],
            ),
            confirmation_decision(),
        ]
    )
    worker, database, _transport = make_worker(tmp_path, provider)
    worker.process(inbound("in-1", "Parso standup schedule karo"))
    worker.process(inbound("in-2", "Haan"))

    with database.session() as session:
        event = session.scalar(select(TimelineEvent))
        assert event is not None and event.title == "Team standup"
