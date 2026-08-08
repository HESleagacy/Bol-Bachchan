"""Optional Maya text-to-speech provider.

Voice replies are used only when the owner's response_modality preference is
"voice" and Maya is configured. Any failure falls back to text, which is always
sent first per the project contract.
"""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class TTSProvider(Protocol):
    def synthesize(self, text: str) -> bytes | None: ...


class MayaProvider:
    """HTTP Maya client. Returns None on any failure so callers fall back to text."""

    def __init__(self, api_url: str, api_key: str, voice: str = "default", timeout_seconds: float = 30.0) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._voice = voice
        self._timeout_seconds = timeout_seconds

    def synthesize(self, text: str) -> bytes | None:
        import httpx

        try:
            response = httpx.post(
                self._api_url,
                json={"text": text, "voice": self._voice, "format": "ogg_opus"},
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except Exception:
            log.exception("Maya synthesis failed; falling back to text")
            return None
        if not response.content:
            log.warning("Maya returned empty audio; falling back to text")
            return None
        return response.content


def build_tts_provider(api_url: str, api_key: str, voice: str) -> TTSProvider | None:
    if not api_url or not api_key:
        return None
    return MayaProvider(api_url, api_key, voice)
