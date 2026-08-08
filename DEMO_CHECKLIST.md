# Demo Readiness Checklist

Complete this checklist after the implementation phases and before presenting Bol Bachchan.

## Resolved Setup Findings

- The host currently has Python 3.10. Neonize requires Python 3.11 or newer.
- Docker is the selected Python 3.12 runtime and its daemon is running.
- A local `.env` is configured and ignored by Git.
- WhatsApp is linked and its Neonize session persists under `data/`.
- Phone-number and linked-identity (`@lid`) self-chat behavior is verified.
- Gemini structured output is verified with a live API request.
- A Gemini key was previously placed in `.env.example`; revoke it before testing and use a newly generated key only in `.env`.

## Runtime Setup

- [x] Install Python 3.11 or newer, preferably Python 3.12, or start the Docker daemon.
- [x] Create `.env` from `.env.example`.
- [x] Set `OWNER_JID` to the presentation account with its country code.
- [x] Set `OWNER_TIMEZONE` correctly.
- [x] Add a working `GEMINI_API_KEY`.
- [ ] Revoke the key previously exposed in `.env.example` and generate a replacement.
- [x] Confirm the laptop has stable internet access.
- [x] Link WhatsApp and confirm `data/neonize.db` persists after restart.

## Self-Chat Safety Test

Run this before enabling Gemini processing:

```bash
python -m app.main --self-chat-check
```

- [x] Send a plain text message to the account's own WhatsApp chat.
- [x] Confirm the event is accepted as an owner self-chat message.
- [x] Record the observed `from_me` value.
- [x] Confirm the WhatsApp message ID is logged.
- [ ] Repeat with an extended or quoted text message.
- [x] Restart the application and check reconnect/replay behavior.
- [x] Confirm the check mode never sends a reply.

## Phase 1 Demo Test

- [ ] Non-owner chats are ignored.
- [ ] Group messages are ignored.
- [x] The original owner message is stored once.
- [ ] Replayed message IDs are deduplicated.
- [x] Assistant outbound IDs are stored.
- [ ] Replayed outbound messages do not trigger responses.
- [ ] Messages are queued instead of processed in the Neonize callback.

## Phase 2 Demo Test

- [ ] English input receives an English response.
- [x] Hindi input receives a Hindi response.
- [x] Roman Hindi or Hinglish input receives a matching response style.
- [x] A personal fact creates a source-linked memory.
- [x] `Hindi mein jawab do` updates `preferred_language`.
- [x] An incomplete request asks one focused clarification question.
- [x] The follow-up message resolves the persisted pending action.
- [x] Restarting the application preserves messages, memories, preferences, and pending actions.
- [ ] Unsupported reminder requests are not falsely reported as completed.

## Presentation Safety

- [ ] Run the complete demo flow once immediately before presenting.
- [ ] Keep WhatsApp Web or the phone available to confirm account connectivity.
- [ ] Prevent the laptop from sleeping during the presentation.
- [ ] Keep terminal logs open in a separate window.
- [ ] Prepare an offline fallback recording or mock flow in case WhatsApp or Gemini is unavailable.
- [ ] Back up the working `.env` and `data/neonize.db` securely; never commit either file.

## Reviewer Readiness

Complete these after the live Phase 3-6 checks and before final submission.

- [ ] Add `ARCHITECTURE.md` describing boundaries, data flow, workers, and deterministic execution.
- [ ] Add `SECURITY.md` covering owner allowlisting, `@lid` validation, deduplication, loop prevention, media limits, and secret handling.
- [ ] Add architecture decision records for SQLite, structured Gemini decisions, database-backed workers, and optional integrations.
- [ ] Add a threat model covering spoofed messages, replay, prompt injection, malicious documents, leaked credentials, and provider outages.
- [ ] Document failure modes and recovery behavior for WhatsApp, Gemini, SQLite, reminder delivery, Maya, and Google Calendar.
- [ ] Add CI for tests, linting, type checks, compilation, and Alembic migration-drift detection.
- [ ] Pin production dependencies exactly and document the dependency-update process.
- [ ] Add structured logging with correlation identifiers for WhatsApp and database records.
- [ ] Add retry, timeout, and backoff policies for external providers.
- [ ] Add graceful shutdown tests for message and reminder workers.
- [ ] Add a health endpoint or health command covering the database and worker state.
- [ ] Add database backup, restore, export, and forget workflows.
- [ ] Add an integration-test matrix for text, reminders, voice notes, documents, restart recovery, and provider failures.
- [ ] Add a reproducible demo script with expected input, output, and verification steps.
- [ ] Document known limitations honestly, including single-instance SQLite operation and optional-provider credential requirements.
- [ ] State any required AI-tool disclosure according to the submission or review policy.

## Required Provider Acceptance

- [ ] Configure the real Maya API URL, key, and native-language voice.
- [ ] Verify Maya returns or is converted to WhatsApp-compatible OGG/Opus audio.
- [ ] Change `response_modality` conversationally to voice.
- [ ] Receive a real Maya-generated WhatsApp voice-note response.
- [ ] Verify Maya failure falls back to a text response.
- [ ] Configure Google OAuth client credentials and Calendar scope.
- [ ] Complete authorization and securely persist a refresh token.
- [ ] Create a confirmed reminder and verify its Google Calendar event.
- [ ] Create a timeline event and verify Calendar synchronization.
- [ ] Cancel or reschedule an item and verify Calendar stays consistent.
- [ ] Verify retries do not create duplicate Calendar events.

## Canonical Full Demo Runbook

Run this sequence from a clean, linked WhatsApp self-chat before the final presentation.
Do not skip confirmation messages; they demonstrate that Gemini interprets while Python
owns execution.

### 1. Remember

Send:

```text
Mera doctor Dr Sharma hai.
```

- [x] Personal fact is stored with the original WhatsApp message as provenance.
- [x] Memory survives an application restart.

Then send:

```text
Tumhe kaise pata ki Dr Sharma mere doctor hain?
```

- [x] Reply quotes the original statement and its date without calling Gemini for provenance.

### 2. Remind

Send:

```text
2 minute baad paani peene ka reminder lagao.
```

Reply `Haan` or `Yes` to confirmation.

- [x] Reminder is stored only after confirmation.
- [x] Reminder worker delivers it through WhatsApp.
- [x] Delivered status and outbound message ID are persisted.

### 3. Recurring And Rescheduling

Send:

```text
Har Sunday subah 10 baje medicines order karne ka reminder lagao.
```

Confirm, then send:

```text
Is reminder ko Sunday shaam 6 baje reschedule kar do.
```

- [x] Existing reminder is updated instead of duplicated.
- [x] Weekly recurrence remains intact.
- [x] SQLite reflects Sunday 6 PM before success is reported.

### 4. Configure

Send:

```text
Raat 10 baje ke baad reminders mat bhejna.
```

- [x] `quiet_hours_start=22:00` and default `quiet_hours_end=07:00` are stored.
- [ ] A reminder due during quiet hours moves to the next permitted time.

Then send:

```text
Mujhse Hindi mein baat karo.
```

- [x] `preferred_language` changes conversationally.
- [x] Later responses follow the preference.

### 5. Timeline Conflict

Create and confirm a doctor appointment, then request a reminder during it.

```text
Kal shaam 4:30 se 5:30 doctor appointment add karo.
Kal 5 baje Ramesh ko call karne ka reminder lagao.
```

- [ ] Timeline event is persisted after confirmation.
- [ ] Conflict is calculated by Python.
- [ ] Assistant suggests the event end time instead of blindly scheduling the overlap.

### 6. Understand A Document

Upload a bill or appointment PDF without a caption.

- [x] Download, MIME validation, storage, summary, and source linkage work.
- [ ] Final reply gives a neutral summary and asks what the user wants.
- [ ] No embedded document instruction creates a pending action.
- [ ] Document type, dates, amounts, and entities are persisted.

Follow up explicitly:

```text
Due date se do din pehle yaad dila dena.
```

- [ ] Relevant extracted date is used, then confirmation is requested.

### 7. Link And Retrieval

Send a public HTTP(S) article URL.

- [ ] Public HTML is bounded, summarized, and source-linked.
- [ ] Private and local destinations remain blocked.
- [ ] Asking about the saved page cites its source URL.

### 8. Voice Input

Send a Hindi or Hinglish voice note requesting a short reminder.

- [x] Real audio download, transcription, interpretation, confirmation, and delivery work.
- [ ] Every voice note, including short confirmations, stores a non-empty transcript.

### 9. Maya Voice Response

Complete the Required Provider Acceptance section, set response modality conversationally
to voice, and verify a real Maya-generated WhatsApp voice note plus text fallback.

### 10. Google Calendar

Complete the Required Provider Acceptance section and verify confirmed reminders and
timeline changes remain synchronized without duplicate Calendar events.

## Final Evidence

- [ ] Capture terminal logs for each runbook section.
- [ ] Capture SQLite rows showing provenance, confirmation state, due time, and delivery.
- [ ] Record one uninterrupted full-demo fallback video.
- [ ] Reset or redact personal and medical demo data before sharing evidence.
