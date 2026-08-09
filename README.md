# Bol Bachchan

> Bas bol do. Baaki yaad rahega.
> *(Just say it. The rest will be remembered.)*

A private, multilingual WhatsApp **self-chat assistant** that turns WhatsApp's
"Message Yourself" feature into an intelligent personal memory, reminder, and
timeline manager. Speak in English, Hindi, Hinglish, or mix them freely --
Bol Bachchan understands.

## What it does

| Capability | Example |
|---|---|
| **Remember facts** | *"Mera doctor Dr Sharma hai"* |
| **Set reminders** | *"Kal 5 baje Ramesh ko call karna"* |
| **Recurring reminders** | *"Har Sunday subah 10 baje medicines order karna"* |
| **Timeline events** | *"Kal shaam 4:30 se 5:30 doctor appointment"* |
| **Conflict detection** | Overlapping events are flagged with alternative-time suggestions |
| **Preferences** | *"Raat 10 ke baad reminders mat bhejna"* (quiet hours) |
| **Document summaries** | Send a PDF, image, or text file -- get a summary with dates, amounts, and entities |
| **Link summaries** | Paste a URL -- the page is fetched and summarized |
| **Voice notes** | Audio is transcribed and interpreted, replies come back as voice |
| **Google Calendar sync** | Confirmed reminders and events sync to your calendar |

## Architecture

```
WhatsApp (Neonize)
    |
    v
 Normalizer  -->  Message Worker  -->  Assistant Service  -->  Gemini AI
                      |                      |
                      v                      v
                  SQLite DB           Decision Engine
                      |                (deterministic)
                      v
               Reminder Worker  -->  WhatsApp reply
```

**Design principle:** The LLM understands the human. Deterministic code
executes the contract. Gemini does fuzzy interpretation (language, intent,
transcription). Python owns all authoritative operations (timestamps, database
writes, confirmation flow, overlap detection, delivery).

## Tech Stack

- **Python 3.11+** -- single monolith
- **Neonize** -- WhatsApp Linked Devices client
- **Google Gemini** (`gemini-2.5-flash`) -- structured AI decisions
- **SQLAlchemy 2 + Alembic** -- SQLite ORM and migrations
- **Pydantic v2** -- config, validation, AI response schemas
- **Maya TTS** -- optional voice replies (OGG/Opus via ffmpeg)
- **Google Calendar API** -- optional calendar sync
- **Docker** -- production container with dumb-init

## Requirements

- Docker (recommended), or Python 3.11+ with ffmpeg installed
- A WhatsApp account with Linked Devices support
- A [Gemini API key](https://aistudio.google.com/apikey)

## Quick Start

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
OWNER_JID=91XXXXXXXXXX@s.whatsapp.net
GEMINI_API_KEY=your-gemini-api-key
```

See `.env.example` for all available options.

### 2. Run with Docker Compose (recommended)

```bash
docker compose up --build
```

### 3. Run with Docker manually

```bash
# Build
docker build -t bol-bachchan .

# Self-chat check mode (no AI, no replies -- just logs events)
docker run --rm -it \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  bol-bachchan \
  python -m app.main --self-chat-check

# Full assistant
docker run --rm -it \
  --name bol-bachchan-app \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  bol-bachchan
```

### 4. Pair WhatsApp

On first run, a QR code appears in the terminal. Scan it with:

**WhatsApp > Settings > Linked Devices > Link a Device**

The session persists in `data/neonize.db` -- you only scan once.

## Local Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest
```

Alembic migrations run automatically at startup. To run manually:

```bash
alembic upgrade head
```

## Deployment (Railway)

The bot is configured for [Railway](https://railway.com) deployment:

1. Install the Railway CLI: `curl -fsSL https://railway.com/install.sh | sh`
2. `railway login && railway init && railway link`
3. Add a **persistent volume** at `/app/data` in the Railway dashboard
4. Set environment variables via `railway variables set` or the dashboard
5. `railway up`

See `railway.toml` for the deployment config.

## Google Calendar Setup

1. Enable **Google Calendar API** in a Google Cloud project
2. Configure the OAuth consent screen (add yourself as a test user)
3. Create a **Web application** OAuth client with redirect URI:
   ```
   http://127.0.0.1:8765/callback
   ```
4. Add the client ID and secret to `.env`, then run:
   ```bash
   .venv/bin/python -m app.providers.google_oauth
   ```

The refresh token is stored at `data/google_calendar_token.json` (mode `0600`).
The bot uses it to create, reschedule, and cancel calendar events.

## Maya TTS Setup

Set `MAYA_API_KEY` in `.env` to enable voice replies. The bot requests
automatic language selection and WhatsApp-compatible OGG/Opus audio, falling
back to text on any provider failure.

## Project Structure

```
app/
  main.py              # Entrypoint -- wires everything together
  config.py            # Pydantic Settings (env-based config)
  transport/           # WhatsApp I/O (Neonize adapter, normalizer)
  assistant/           # AI layer (Gemini prompts, schemas, decision engine)
  domain/              # Pure logic (messages, reminders, timeline, preferences)
  persistence/         # Database (SQLAlchemy models, repositories)
  providers/           # External services (Gemini, Maya TTS, Calendar, web)
  workers/             # Background threads (message processing, reminder delivery)
migrations/            # Alembic schema migrations
tests/                 # pytest test suite
```

## Safety

- Only the configured owner's self-chat is accepted
- Consequential actions (reminders, events, deletions) require confirmation
- Uncaptioned documents and fetched webpages cannot execute embedded instructions
- Private/local URLs and oversized media are rejected
- User-reported memories retain provenance (source message and date)
- Reminder state lives in SQLite, not in-memory timers

## License

GNU General License
