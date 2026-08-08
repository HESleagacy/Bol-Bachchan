from __future__ import annotations

import logging
import subprocess
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

DEFAULT_MAYA_URL = "https://tts.mayaresearch.ai/v1/tts"
DEFAULT_MODEL = "Maya 2 Native"
MAX_PCM_BYTES = 25 * 1024 * 1024
LANGUAGE_CODES = {
    "hindi": "hi",
    "hi": "hi",
    "english": "en",
    "en": "en",
    "bengali": "bn",
    "bn": "bn",
    "tamil": "ta",
    "ta": "ta",
    "telugu": "te",
    "te": "te",
    "marathi": "mr",
    "mr": "mr",
    "gujarati": "gu",
    "gu": "gu",
    "kannada": "kn",
    "kn": "kn",
    "malayalam": "ml",
    "ml": "ml",
    "punjabi": "pa",
    "pa": "pa",
    "odia": "or",
    "or": "or",
}


class TTSProvider(Protocol):
    def synthesize(self, text: str, language: str | None = None) -> bytes | None: ...


class MayaProvider:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        voice: str = "Ananya",
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_url = api_url or DEFAULT_MAYA_URL
        self._api_key = api_key
        self._voice = voice
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
        )

    def synthesize(self, text: str, language: str | None = None) -> bytes | None:
        payload: dict[str, str] = {
            "text": text,
            "voice": self._voice,
            "model": self._model,
        }
        normalized_language = LANGUAGE_CODES.get((language or "").strip().lower())
        if normalized_language:
            payload["language"] = normalized_language
        try:
            pcm = bytearray()
            with self._client.stream("POST", self._api_url, json=payload) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not content_type.startswith("audio/l16"):
                    raise ValueError(f"Unexpected Maya content type: {content_type or 'missing'}")
                for chunk in response.iter_bytes():
                    pcm.extend(chunk)
                    if len(pcm) > MAX_PCM_BYTES:
                        raise ValueError("Maya audio response exceeded the size limit")
            if not pcm:
                raise ValueError("Maya returned empty audio")
            return pcm_to_ogg_opus(bytes(pcm), timeout_seconds=self._timeout_seconds)
        except Exception:
            log.exception("Maya synthesis failed; falling back to text")
            return None


def pcm_to_ogg_opus(pcm: bytes, timeout_seconds: float = 30.0) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            "24000",
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-f",
            "ogg",
            "pipe:1",
        ],
        input=pcm,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if result.returncode != 0 or not result.stdout:
        error = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg failed to encode Maya audio: {error}")
    return result.stdout


def build_tts_provider(
    api_url: str,
    api_key: str,
    voice: str,
    model: str = DEFAULT_MODEL,
) -> TTSProvider | None:
    if not api_key:
        return None
    return MayaProvider(api_url or DEFAULT_MAYA_URL, api_key, voice, model)
