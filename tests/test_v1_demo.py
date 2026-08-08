from __future__ import annotations

from datetime import datetime, timezone

from app.assistant.decision_engine import DecisionEngine
from app.assistant.schemas import AssistantDecision
from app.assistant.service import AssistantService
from app.domain.messages import InboundMessage, MessageType
from app.persistence.database import Database
from app.persistence.models import Base
from app.persistence.repositories import Repository

OWNER = "919876543210@s.whatsapp.net"


class UnusedProvider:
    def interpret(self, message: str, context: str) -> AssistantDecision:
        raise AssertionError("Provenance answer should not call Gemini")


def test_canonical_memory_provenance_answer_is_deterministic(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(database.engine)
    assistant = AssistantService(UnusedProvider(), DecisionEngine(30))
    with database.session() as session:
        repository = Repository(session)
        user = repository.get_or_create_user(OWNER, "Asia/Kolkata")
        source = repository.add_inbound(
            user,
            InboundMessage(
                whatsapp_message_id="doctor-source",
                chat_jid=OWNER,
                sender_jid=OWNER,
                message_type=MessageType.TEXT,
                text="Mera doctor Dr Sharma hai",
                occurred_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
                is_from_me=True,
                is_self_chat=True,
            ),
        )
        repository.add_memory(user.id, source.id, "personal_fact", "doctor", "Dr Sharma", 1.0)
        question = repository.add_inbound(
            user,
            InboundMessage(
                whatsapp_message_id="why-source",
                chat_jid=OWNER,
                sender_jid=OWNER,
                message_type=MessageType.TEXT,
                text="Tumhe kaise pata ki Dr Sharma mere doctor hain?",
                occurred_at=datetime.now(timezone.utc),
                is_from_me=True,
                is_self_chat=True,
            ),
        )

        result = assistant.handle_text(question.text, repository, user, question)

    assert "08 Aug 2026" in result.response
    assert "Mera doctor Dr Sharma hai" in result.response
    assert "Dr Sharma" in result.response
