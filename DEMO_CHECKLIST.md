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
