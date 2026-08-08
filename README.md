# Bol Bachchan

> Bas bol do. Baaki yaad rahega.

A private, multilingual WhatsApp **Message Yourself** assistant for memories, reminders,
timeline context, documents, links, preferences, and voice notes. See `PRODUCT.md` for the
product contract and `PROJECT.md` for the implementation plan.

## Implemented

- Owner-only Neonize self-chat, including WhatsApp linked-identity (`@lid`) events
- Persistent message IDs, duplicate suppression, and outbound-loop protection
- Gemini decisions validated through Pydantic JSON Schema
- Source-linked personal facts and routines
- Conversational language, response-modality, quiet-hour, and category preferences
- One-time and recurring reminders with confirmation
- Reminder listing, cancellation, rescheduling, restart-safe delivery, and quiet hours
- Timeline events with deterministic overlap detection and alternative-time suggestions
- PDF, common image, and plain-text summaries with structured dates, amounts, and entities
- Safe public-link fetching and summarization
- Voice-note transcription with original-message provenance
- Maya TTS voice responses with text fallback
- Google Calendar synchronization for confirmed reminders and timeline events

## Requirements

- Docker, or Python 3.11+
- A WhatsApp account that can use Linked Devices
- A Gemini API key

## Configuration

Create `.env` from `.env.example`, then set at least:

```env
OWNER_JID=91XXXXXXXXXX@s.whatsapp.net
OWNER_TIMEZONE=Asia/Kolkata
GEMINI_API_KEY=your-private-key
```

Never put a real secret in `.env.example` or commit `.env`.

## Docker

```bash
docker build -t bol-bachchan .

docker run --rm -it \
  -v "$PWD/.env:/app/.env:ro" \
  -v "$PWD/data:/app/data" \
  bol-bachchan \
  python -m app.main --self-chat-check
```

Scan the terminal QR through **WhatsApp > Linked devices**, send a self-chat message, and
confirm its normalized event appears. Check mode never invokes Gemini or replies.

Start the full assistant:

```bash
docker run --rm -it \
  --name bol-bachchan-app \
  -v "$PWD/.env:/app/.env:ro" \
  -v "$PWD/data:/app/data" \
  bol-bachchan
```

The WhatsApp session, SQLite database, and downloaded media persist under `data/`.

## Local Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest
```

Alembic migrations run automatically at application startup.

## Google Calendar Authorization

1. Enable Google Calendar API in a Google Cloud project.
2. Configure the OAuth consent screen and add the owner as a test user when the app is in testing mode.
3. Create a **Web application** OAuth client with this redirect URI:

```text
http://127.0.0.1:8765/callback
```

4. Put the client ID and secret in `.env`, then authorize locally:

```bash
.venv/bin/python -m app.providers.google_oauth
```

The browser consent result is stored with mode `0600` at
`data/google_calendar_token.json`. The application uses that refresh token to create,
reschedule, and cancel the same persisted Calendar event without duplication.

## Maya TTS

Set `MAYA_API_URL`, `MAYA_API_KEY`, and `MAYA_VOICE` only after confirming Maya's real API
request and audio-response contract. Bol Bachchan requests automatic language selection and
WhatsApp-compatible OGG/Opus, and falls back to text on provider failure.

## Safety Boundaries

- Only the configured owner's self-chat is accepted.
- Consequential actions require confirmation.
- Uncaptioned documents and fetched webpages cannot execute embedded instructions.
- Private/local URLs and oversized media are rejected.
- User-reported memories retain provenance and are not presented as independently verified.
- Reminder state lives in SQLite rather than in-memory timers.

## Current Limits

- Designed for one owner and one running SQLite instance
- Google Calendar and Maya require external credentials; both must be configured for full V1 acceptance
- Links support public HTTP(S) text and HTML pages only
- Production hardening items remain tracked in `DEMO_CHECKLIST.md`
