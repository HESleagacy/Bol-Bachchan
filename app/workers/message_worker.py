from __future__ import annotations

import logging
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread

import httpx

from app.assistant.service import AssistantService, MediaResult
from app.domain.messages import InboundMessage, MessageType
from app.persistence.database import Database
from app.persistence.models import Message, User
from app.persistence.repositories import Repository
from app.providers.maya import TTSProvider
from app.providers.web import SafeWebFetcher, first_url
from app.transport.base import MessageTransport

log = logging.getLogger(__name__)

DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "text/plain",
}
MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "text/plain": ".txt",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
}
FALLBACK_ERROR_TEXT = "Kuch gadbad ho gayi, thodi der baad dobara koshish karein."
TOO_LARGE_TEXT = "Yeh file bahut badi hai, isliye main ise process nahi kar paya."
UNSUPPORTED_TYPE_TEXT = "Is tarah ki file abhi supported nahi hai. PDF, image, ya text file bhejein."
DOWNLOAD_FAILED_TEXT = "File download nahi ho payi, dobara bhejne ki koshish karein."


def format_assistant_response(text: str) -> str:
    return f"*Bol Bachchan*\n{text.strip()}"


class MessageWorker:
    def __init__(
        self,
        database: Database,
        assistant: AssistantService,
        transport: MessageTransport,
        owner_jid: str,
        owner_timezone: str,
        media_dir: Path = Path("data/media"),
        max_media_bytes: int = 20 * 1024 * 1024,
        tts: TTSProvider | None = None,
        web_fetcher: SafeWebFetcher | None = None,
        queue_size: int = 100,
    ) -> None:
        self._database = database
        self._assistant = assistant
        self._transport = transport
        self._owner_jid = owner_jid
        self._owner_timezone = owner_timezone
        self._media_dir = media_dir
        self._max_media_bytes = max_media_bytes
        self._tts = tts
        self._web_fetcher = web_fetcher
        self._queue: Queue[InboundMessage] = Queue(maxsize=queue_size)
        self._stopping = Event()
        self._thread = Thread(target=self._run, name="message-worker", daemon=True)

    def enqueue(self, message: InboundMessage) -> None:
        try:
            self._queue.put_nowait(message)
        except Full:
            log.error("Message queue is full; dropping WhatsApp message %s", message.whatsapp_message_id)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=10)

    def process(self, inbound: InboundMessage) -> bool:
        if not inbound.is_self_chat or inbound.sender_jid != self._owner_jid:
            log.warning("Ignoring message outside the configured owner self-chat")
            return False
        with self._database.session() as session:
            repository = Repository(session)
            if repository.has_message(inbound.whatsapp_message_id):
                log.info("Ignoring duplicate or known outbound message %s", inbound.whatsapp_message_id)
                return False
            user = repository.get_or_create_user(inbound.sender_jid, self._owner_timezone)
            repository.update_chat_jid(user, inbound.chat_jid)
            source_message = repository.add_inbound(user, inbound)
            if source_message is None:
                return False
            try:
                response_text = self._handle(inbound, repository, user, source_message)
            except Exception:
                log.exception("Failed to interpret WhatsApp message %s", inbound.whatsapp_message_id)
                response_text = FALLBACK_ERROR_TEXT
            if response_text is None:
                return True
            self._reply(
                repository,
                user,
                inbound.chat_jid,
                response_text,
                prefer_voice=inbound.message_type == MessageType.AUDIO,
                detected_languages=(
                    source_message.detected_languages
                    if inbound.message_type == MessageType.AUDIO
                    else None
                ),
            )
            return True

    def _handle(
        self,
        inbound: InboundMessage,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> str | None:
        if inbound.message_type == MessageType.TEXT and inbound.text:
            url = first_url(inbound.text)
            if url and self._web_fetcher is not None:
                return self._handle_link(url, inbound, repository, user, source_message)
            return self._assistant.handle_text(inbound.text, repository, user, source_message).response
        if inbound.message_type == MessageType.AUDIO:
            return self._handle_audio(inbound, repository, user, source_message)
        if inbound.message_type in (MessageType.DOCUMENT, MessageType.IMAGE):
            return self._handle_document(inbound, repository, user, source_message)
        return None

    def _handle_audio(
        self,
        inbound: InboundMessage,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> str:
        if inbound.media_size and inbound.media_size > self._max_media_bytes:
            return TOO_LARGE_TEXT
        audio = self._transport.download_media(inbound.whatsapp_message_id)
        if audio is None:
            return DOWNLOAD_FAILED_TEXT
        if len(audio) > self._max_media_bytes:
            return TOO_LARGE_TEXT
        mime_type = _base_mime(inbound.media_mime_type) or "audio/ogg"
        source_message.media_path = self._store_media(inbound.whatsapp_message_id, mime_type, audio)
        result = self._assistant.handle_audio(audio, mime_type, repository, user, source_message)
        if result.transcript:
            source_message.transcript = result.transcript
        source_message.detected_languages = result.detected_languages
        return result.execution.response

    def _handle_link(
        self,
        url: str,
        inbound: InboundMessage,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> str:
        try:
            page = self._web_fetcher.fetch(url)
        except (ValueError, httpx.HTTPError, OSError) as exc:
            log.warning("Link fetch rejected for %s: %s", url, exc)
            return "Yeh link safely open nahi ho paya. Public text ya HTML link dobara bhejein."
        result = self._assistant.handle_document(
            page.content,
            "text/plain",
            page.filename,
            None,
            repository,
            user,
            source_message,
        )
        repository.add_document(
            user_id=user.id,
            source_message_id=source_message.id,
            filename=page.filename,
            mime_type="text/html",
            storage_path=page.url,
            summary=result.document_summary,
            extracted_text=result.document_extracted_text,
            document_type=result.document_type or "web_page",
            extracted_dates=result.document_dates,
            extracted_amounts=result.document_amounts,
            extracted_entities=result.document_entities,
        )
        return result.execution.response

    def _handle_document(
        self,
        inbound: InboundMessage,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> str:
        mime_type = _base_mime(inbound.media_mime_type)
        if mime_type not in DOCUMENT_MIME_TYPES:
            return UNSUPPORTED_TYPE_TEXT
        if inbound.media_size and inbound.media_size > self._max_media_bytes:
            return TOO_LARGE_TEXT
        data = self._transport.download_media(inbound.whatsapp_message_id)
        if data is None:
            return DOWNLOAD_FAILED_TEXT
        if len(data) > self._max_media_bytes:
            return TOO_LARGE_TEXT
        filename = inbound.media_filename or f"{inbound.whatsapp_message_id}{MIME_EXTENSIONS.get(mime_type, '')}"
        storage_path = self._store_media(inbound.whatsapp_message_id, mime_type, data)
        source_message.media_path = storage_path
        result = self._assistant.handle_document(
            data, mime_type, filename, inbound.text, repository, user, source_message
        )
        repository.add_document(
            user_id=user.id,
            source_message_id=source_message.id,
            filename=filename,
            mime_type=mime_type,
            storage_path=storage_path,
            summary=result.document_summary,
            extracted_text=result.document_extracted_text,
            document_type=result.document_type,
            extracted_dates=result.document_dates,
            extracted_amounts=result.document_amounts,
            extracted_entities=result.document_entities,
        )
        return result.execution.response

    def _reply(
        self,
        repository: Repository,
        user: User,
        chat_jid: str,
        text: str,
        prefer_voice: bool = False,
        detected_languages: list[str] | None = None,
    ) -> None:
        formatted = format_assistant_response(text)
        preferences = repository.get_preferences(user.id)
        if (prefer_voice or preferences.get("response_modality") == "voice") and self._tts is not None:
            language = preferences.get("preferred_language")
            if detected_languages:
                language = detected_languages[0]
            audio = self._tts.synthesize(text, language)
            if audio is not None:
                try:
                    outbound = self._transport.send_voice_note(chat_jid, audio)
                    repository.add_outbound(user, outbound)
                    return
                except Exception:
                    log.exception("Voice note send failed; falling back to text")
        outbound = self._transport.send_text(chat_jid, formatted)
        repository.add_outbound(user, outbound)

    def _store_media(self, message_id: str, mime_type: str, data: bytes) -> str:
        self._media_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(char for char in message_id if char.isalnum())
        path = self._media_dir / f"{safe_id}{MIME_EXTENSIONS.get(mime_type, '.bin')}"
        path.write_bytes(data)
        return str(path)

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                inbound = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self.process(inbound)
            except Exception:
                log.exception("Failed to process WhatsApp message %s", inbound.whatsapp_message_id)
            finally:
                self._queue.task_done()


def _base_mime(mime_type: str | None) -> str | None:
    if not mime_type:
        return None
    return mime_type.split(";", 1)[0].strip().lower()
