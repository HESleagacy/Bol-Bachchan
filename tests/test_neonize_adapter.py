from types import SimpleNamespace

from app.transport.neonize_adapter import NeonizeAdapter


class FakeClient:
    def __init__(self) -> None:
        self.message = SimpleNamespace(audioMessage=SimpleNamespace(mimetype="audio/ogg"))
        self.sent_to = None

    def build_audio_message(self, audio: bytes, ptt: bool) -> SimpleNamespace:
        assert audio == b"ogg-opus"
        assert ptt is True
        return self.message

    def send_message(self, chat_jid: object, message: object) -> SimpleNamespace:
        self.sent_to = chat_jid
        assert message is self.message
        return SimpleNamespace(ID="outbound-id")


def test_voice_notes_declare_the_opus_codec() -> None:
    adapter = object.__new__(NeonizeAdapter)
    adapter._client = FakeClient()
    adapter._build_jid = lambda _chat_jid: "owner-jid"

    outbound = adapter.send_voice_note("owner@s.whatsapp.net", b"ogg-opus")

    assert adapter._client.message.audioMessage.mimetype == "audio/ogg; codecs=opus"
    assert adapter._client.sent_to == "owner-jid"
    assert outbound.whatsapp_message_id == "outbound-id"
