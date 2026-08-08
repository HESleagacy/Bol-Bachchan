from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.assistant.decision_engine import DecisionEngine
from app.assistant.schemas import AssistantDecision, ProposedAction
from app.assistant.service import AssistantService
from app.domain.messages import InboundMessage, MessageType, OutboundMessage
from app.persistence.database import Database
from app.persistence.models import Base, Memory, Message, PendingAction, Preference
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
    worker = MessageWorker(database, assistant, transport, OWNER, "Asia/Kolkata")
    return worker, database, transport


def test_routes_once_and_suppresses_duplicate_and_outbound_replay(tmp_path: Path) -> None:
    provider = FakeProvider(
        [AssistantDecision(intent="answer_question", response="Theek hai", proposed_actions=[])]
    )
    worker, database, transport = make_worker(tmp_path, provider)

    assert worker.process(inbound("in-1", "Hello")) is True
    assert worker.process(inbound("in-1", "Hello")) is False
    assert worker.process(inbound("out-1", "Theek hai")) is False

    assert len(transport.sent) == 1
    assert transport.sent[0].text == "*Bol Bachchan*\nTheek hai"
    assert provider.decisions == []
    with database.session() as session:
        assert session.scalar(select(func.count(Message.id))) == 2


def test_stores_source_linked_memory_and_updates_preference(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            AssistantDecision(
                intent="store_memory",
                response="Yaad rakhunga.",
                proposed_actions=[
                    ProposedAction(
                        action_type="store_memory",
                        kind="personal_fact",
                        category="health",
                        content="User reports a penicillin allergy",
                        confidence=0.98,
                    )
                ],
            ),
            AssistantDecision(
                intent="update_preference",
                response="Ab Hindi mein jawab dunga.",
                proposed_actions=[
                    ProposedAction(
                        action_type="update_preference",
                        key="preferred_language",
                        value="hi",
                    )
                ],
            ),
        ]
    )
    worker, database, _transport = make_worker(tmp_path, provider)

    worker.process(inbound("in-memory", "Mujhe penicillin se allergy hai"))
    worker.process(inbound("in-preference", "Hindi mein jawab do"))

    with database.session() as session:
        memory = session.scalar(select(Memory))
        source = session.get(Message, memory.source_message_id) if memory else None
        preference = session.scalar(select(Preference))
        assert memory is not None
        assert source is not None and source.whatsapp_message_id == "in-memory"
        assert preference is not None and (preference.key, preference.value) == ("preferred_language", "hi")


def test_clarification_context_is_persisted_then_resolved(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            AssistantDecision(
                intent="clarify",
                response="Kaunsi language?",
                missing_fields=["value"],
                proposed_actions=[ProposedAction(action_type="update_preference", key="preferred_language")],
            ),
            AssistantDecision(
                intent="update_preference",
                response="Hindi set kar di.",
                proposed_actions=[
                    ProposedAction(action_type="update_preference", key="preferred_language", value="hi")
                ],
            ),
        ]
    )
    worker, database, _transport = make_worker(tmp_path, provider)

    worker.process(inbound("in-clarify", "Meri language badal do"))
    worker.process(inbound("in-answer", "Hindi"))

    assert '"pending_action"' in provider.contexts[1]
    assert '"preferred_language"' in provider.contexts[1]
    with database.session() as session:
        pending = session.scalar(select(PendingAction))
        assert pending is not None and pending.status == "resolved"
