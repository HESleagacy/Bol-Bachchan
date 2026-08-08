from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.assistant.decision_engine import DecisionEngine
from app.assistant.schemas import AssistantDecision
from app.assistant.service import AssistantService
from app.domain.messages import InboundMessage, MessageType, OutboundMessage
from app.persistence.database import Database
from app.persistence.models import Base, Document, Message
from app.workers.message_worker import MessageWorker

OWNER = "919876543210@s.whatsapp.net"


class FakeMediaProvider:
    def __init__(self, decision: AssistantDecision) -> None:
        self.decision = decision
        self.audio_calls: list[tuple[bytes, str]] = []
        self.document_calls: list[tuple[str, str, str | None]] = []

    def interpret(self, _message: str, _context: str) -> AssistantDecision:
        raise AssertionError("text path should not be used")

    def interpret_audio(self, audio: bytes, mime_type: str, _context: str) -> AssistantDecision:
        self.audio_calls.append((audio, mime_type))
        return self.decision

    def interpret_document(
        self, _data: bytes, mime_type: str, filename: str, caption: str | None, _context: str
    ) -> AssistantDecision:
        self.document_calls.append((mime_type, filename, caption))
        return self.decision


class FakeTransport:
    def __init__(self, media: bytes | None = b"media-bytes") -> None:
        self.sent: list[OutboundMessage] = []
        self.media = media

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
        raise AssertionError("unused")

    def download_media(self, whatsapp_message_id: str) -> bytes | None:
        return self.media

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass


def media_inbound(
    message_type: MessageType,
    mime_type: str,
    filename: str | None = None,
    size: int | None = 1024,
    caption: str | None = None,
) -> InboundMessage:
    return InboundMessage(
        whatsapp_message_id="media-1",
        chat_jid=OWNER,
        sender_jid=OWNER,
        message_type=message_type,
        text=caption,
        occurred_at=datetime.now(timezone.utc),
        is_from_me=True,
        is_self_chat=True,
        media_mime_type=mime_type,
        media_filename=filename,
        media_size=size,
    )


def make_worker(
    tmp_path: Path, provider: FakeMediaProvider, transport: FakeTransport
) -> tuple[MessageWorker, Database]:
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(database.engine)
    assistant = AssistantService(provider, DecisionEngine(pending_action_ttl_minutes=30))
    worker = MessageWorker(
        database,
        assistant,
        transport,
        OWNER,
        "Asia/Kolkata",
        media_dir=tmp_path / "media",
        max_media_bytes=2048,
    )
    return worker, database


def test_voice_note_is_transcribed_and_stored_with_provenance(tmp_path: Path) -> None:
    decision = AssistantDecision(
        intent="answer_question",
        response="Samajh gaya.",
        transcript="Kal doctor ke paas jaana hai",
    )
    provider = FakeMediaProvider(decision)
    transport = FakeTransport()
    worker, database = make_worker(tmp_path, provider, transport)

    worker.process(media_inbound(MessageType.AUDIO, "audio/ogg; codecs=opus"))

    assert provider.audio_calls == [(b"media-bytes", "audio/ogg")]
    with database.session() as session:
        message = session.scalar(select(Message).where(Message.direction == "inbound"))
        assert message.transcript == "Kal doctor ke paas jaana hai"
        assert message.media_path is not None
        assert Path(message.media_path).read_bytes() == b"media-bytes"
    assert transport.sent[-1].text.endswith("Samajh gaya.")


def test_document_is_summarized_and_stored_with_source_reference(tmp_path: Path) -> None:
    decision = AssistantDecision(
        intent="document_received",
        response="Yeh ek bijli ka bill lag raha hai. Iske saath kya karna hai?",
        document_summary="Electricity bill for July 2026",
        document_extracted_text="Amount due: Rs 2,340. Due date: 15 Aug 2026.",
    )
    provider = FakeMediaProvider(decision)
    transport = FakeTransport()
    worker, database = make_worker(tmp_path, provider, transport)

    worker.process(
        media_inbound(MessageType.DOCUMENT, "application/pdf", filename="bill.pdf")
    )

    assert provider.document_calls == [("application/pdf", "bill.pdf", None)]
    with database.session() as session:
        document = session.scalar(select(Document))
        assert document is not None
        assert document.filename == "bill.pdf"
        assert document.summary == "Electricity bill for July 2026"
        assert "2,340" in document.extracted_text
        source = session.get(Message, document.source_message_id)
        assert source.whatsapp_message_id == "media-1"
    assert "bijli ka bill" in transport.sent[-1].text


def test_unsupported_mime_type_is_rejected_without_download(tmp_path: Path) -> None:
    provider = FakeMediaProvider(AssistantDecision(intent="answer_question", response="x"))
    transport = FakeTransport()
    worker, database = make_worker(tmp_path, provider, transport)

    worker.process(media_inbound(MessageType.DOCUMENT, "application/x-msdownload", filename="evil.exe"))

    assert provider.document_calls == []
    with database.session() as session:
        assert session.scalar(select(Document)) is None
    assert "supported nahi" in transport.sent[-1].text


def test_oversized_media_is_rejected(tmp_path: Path) -> None:
    provider = FakeMediaProvider(AssistantDecision(intent="answer_question", response="x"))
    transport = FakeTransport()
    worker, _database = make_worker(tmp_path, provider, transport)

    worker.process(
        media_inbound(MessageType.DOCUMENT, "application/pdf", filename="big.pdf", size=10_000_000)
    )

    assert provider.document_calls == []
    assert "badi hai" in transport.sent[-1].text


def test_failed_download_reports_error(tmp_path: Path) -> None:
    provider = FakeMediaProvider(AssistantDecision(intent="answer_question", response="x"))
    transport = FakeTransport(media=None)
    worker, _database = make_worker(tmp_path, provider, transport)

    worker.process(media_inbound(MessageType.AUDIO, "audio/ogg"))

    assert provider.audio_calls == []
    assert "download nahi" in transport.sent[-1].text
