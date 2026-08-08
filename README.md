# Bol Bachchan

> Bas bol do. Baaki yaad rahega.

Bol Bachchan is a private, multilingual WhatsApp self-chat assistant. The first two phases
provide an owner-only Neonize transport, persistent message deduplication, Gemini structured
interpretation, source-linked memories, conversational preferences, and clarification state.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
python -m app.main --self-chat-check
```

Python 3.11 or newer is required by Neonize; the Docker image uses Python 3.12.

Set `OWNER_JID` to the linked account's full WhatsApp JID and add a Gemini API key. The
`--self-chat-check` mode performs the phase 1 transport feasibility check without calling
Gemini, writing application messages, or replying. Send text to your own WhatsApp chat and
confirm that the log contains its ID, `from_me` value, type, and text.

After that check, start the assistant:

```bash
python -m app.main
```

Alembic migrations run automatically at startup. Neonize and application SQLite state live
under `data/` by default.

## Tests

```bash
pytest
```

## Current Scope

- Text messages from the configured owner self-chat only
- Persistent inbound/outbound message IDs and duplicate suppression
- Gemini decisions validated with Pydantic
- User-reported memories linked to their source message
- Conversational preference updates
- Expiring pending actions for clarification follow-ups
- Hinglish, Hindi, and English response matching

Reminders, voice notes, documents, Maya, and Google Calendar belong to later phases.
