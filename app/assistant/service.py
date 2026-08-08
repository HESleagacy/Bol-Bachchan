from __future__ import annotations

from dataclasses import dataclass

from app.assistant.context import build_context
from app.assistant.decision_engine import DecisionEngine, ExecutionResult
from app.assistant.schemas import AssistantDecision
from app.persistence.models import Message, User
from app.persistence.repositories import Repository
from app.providers.gemini import DecisionProvider


@dataclass(frozen=True, slots=True)
class MediaResult:
    execution: ExecutionResult
    transcript: str | None
    document_summary: str | None
    document_extracted_text: str | None


class AssistantService:
    def __init__(self, provider: DecisionProvider, decision_engine: DecisionEngine) -> None:
        self._provider = provider
        self._decision_engine = decision_engine

    def handle_text(
        self,
        text: str,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> ExecutionResult:
        pending = repository.get_pending_action(user.id)
        context = build_context(repository, user, pending)
        decision = self._provider.interpret(text, context.as_prompt())
        return self._decision_engine.execute(decision, repository, user, source_message, pending)

    def handle_audio(
        self,
        audio: bytes,
        mime_type: str,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> MediaResult:
        pending = repository.get_pending_action(user.id)
        context = build_context(repository, user, pending)
        decision = self._provider.interpret_audio(audio, mime_type, context.as_prompt())
        execution = self._decision_engine.execute(decision, repository, user, source_message, pending)
        return self._media_result(execution, decision)

    def handle_document(
        self,
        data: bytes,
        mime_type: str,
        filename: str,
        caption: str | None,
        repository: Repository,
        user: User,
        source_message: Message,
    ) -> MediaResult:
        pending = repository.get_pending_action(user.id)
        context = build_context(repository, user, pending)
        decision = self._provider.interpret_document(data, mime_type, filename, caption, context.as_prompt())
        execution = self._decision_engine.execute(decision, repository, user, source_message, pending)
        return self._media_result(execution, decision)

    @staticmethod
    def _media_result(execution: ExecutionResult, decision: AssistantDecision) -> MediaResult:
        return MediaResult(
            execution=execution,
            transcript=decision.transcript,
            document_summary=decision.document_summary,
            document_extracted_text=decision.document_extracted_text,
        )
