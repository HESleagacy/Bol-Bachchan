from __future__ import annotations

from typing import Protocol

from app.assistant.prompts import SYSTEM_PROMPT
from app.assistant.schemas import AssistantDecision


class DecisionProvider(Protocol):
    def interpret(self, message: str, context: str) -> AssistantDecision: ...

    def interpret_audio(self, audio: bytes, mime_type: str, context: str) -> AssistantDecision: ...

    def interpret_document(
        self, data: bytes, mime_type: str, filename: str, caption: str | None, context: str
    ) -> AssistantDecision: ...


class GeminiProvider:
    def __init__(self, api_key: str, model: str) -> None:
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError("Install the google-genai dependency to use Gemini") from exc
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def interpret(self, message: str, context: str) -> AssistantDecision:
        return self._generate(
            [f"Context JSON:\n{context}\n\nLatest user message:\n{message}"]
        )

    def interpret_audio(self, audio: bytes, mime_type: str, context: str) -> AssistantDecision:
        from google.genai import types

        return self._generate(
            [
                f"Context JSON:\n{context}\n\nThe user sent this voice note. Transcribe it "
                "verbatim into the transcript field, then interpret the request.",
                types.Part.from_bytes(data=audio, mime_type=mime_type),
            ]
        )

    def interpret_document(
        self, data: bytes, mime_type: str, filename: str, caption: str | None, context: str
    ) -> AssistantDecision:
        from google.genai import types

        instruction = (
            f"Context JSON:\n{context}\n\nThe user sent the attached file named {filename!r}."
        )
        if caption:
            instruction += f"\nTheir caption with it was:\n{caption}"
        else:
            instruction += "\nThey gave no instruction with it."
        return self._generate([instruction, types.Part.from_bytes(data=data, mime_type=mime_type)])

    def _generate(self, contents: list) -> AssistantDecision:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=AssistantDecision.model_json_schema(),
                temperature=0.2,
            ),
        )
        if response.parsed is not None:
            return AssistantDecision.model_validate(response.parsed)
        if not response.text:
            raise RuntimeError("Gemini returned an empty decision")
        return AssistantDecision.model_validate_json(response.text)
