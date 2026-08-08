from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InboundMessage:
    whatsapp_message_id: str
    chat_jid: str
    sender_jid: str
    message_type: MessageType
    text: str | None
    occurred_at: datetime
    is_from_me: bool
    is_self_chat: bool
    media_mime_type: str | None = None
    media_filename: str | None = None
    media_size: int | None = None


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    whatsapp_message_id: str
    chat_jid: str
    text: str
    occurred_at: datetime
