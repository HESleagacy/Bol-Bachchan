from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.assistant.decision_engine import DecisionEngine
from app.assistant.service import AssistantService
from app.config import get_settings
from app.persistence.database import Database
from app.providers.gemini import GeminiProvider
from app.providers.google_calendar import build_calendar_provider
from app.providers.maya import build_tts_provider
from app.providers.web import SafeWebFetcher
from app.transport.neonize_adapter import NeonizeAdapter
from app.workers.message_worker import MessageWorker
from app.workers.reminder_worker import ReminderWorker

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Minimal health-check HTTP server (for Fly.io / any container orchestrator)
# ---------------------------------------------------------------------------

class _HealthHandler(BaseHTTPRequestHandler):
    """Return 200 OK on any GET request. Suppresses access logs."""

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args: object) -> None:  # silence logs
        pass


def _start_health_server() -> None:
    """Start a background HTTP health-check server if PORT env var is set.

    Fly.io sets PORT automatically. Locally this is a no-op unless you
    explicitly export PORT.
    """
    port_str = os.environ.get("PORT")
    if not port_str:
        return
    port = int(port_str)
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="health")
    thread.start()
    log.info("Health-check server listening on :%s", port)


def run_migrations(database_url: str) -> None:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def connect_with_retry(
    transport: NeonizeAdapter,
    initial_seconds: int,
    max_seconds: int,
) -> None:
    delay = initial_seconds
    while True:
        try:
            transport.connect()
            log.warning("WhatsApp connection ended; reconnecting in %s seconds", delay)
        except Exception:
            log.exception("WhatsApp connection failed; retrying in %s seconds", delay)
        time.sleep(delay)
        delay = min(delay * 2, max_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bol Bachchan WhatsApp assistant")
    parser.add_argument(
        "--self-chat-check",
        action="store_true",
        help="Log normalized owner self-chat events without invoking Gemini or replying",
    )
    args = parser.parse_args()
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    _start_health_server()

    transport = NeonizeAdapter(
        settings.neonize_session_path,
        settings.owner_jid,
        diagnostics=args.self_chat_check,
    )
    if args.self_chat_check:
        transport.set_message_handler(
            lambda message: log.info(
                "Self-chat check: id=%s from_me=%s type=%s text=%r",
                message.whatsapp_message_id,
                message.is_from_me,
                message.message_type,
                message.text,
            )
        )
        log.info("Self-chat check enabled; Gemini and database processing are disabled")
        connect_with_retry(
            transport,
            settings.whatsapp_reconnect_initial_seconds,
            settings.whatsapp_reconnect_max_seconds,
        )
        return

    run_migrations(settings.database_url)
    database = Database(settings.database_url)
    gemini_api_key = settings.gemini_api_key.get_secret_value()
    if not gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required outside --self-chat-check mode")
    provider = GeminiProvider(gemini_api_key, settings.gemini_model)
    calendar = build_calendar_provider(
        settings.google_client_id,
        settings.google_client_secret.get_secret_value(),
        settings.google_refresh_token.get_secret_value(),
        settings.google_calendar_id,
        settings.google_token_path,
    )
    if calendar is not None:
        log.info("Google Calendar synchronization enabled")
    tts = build_tts_provider(
        settings.maya_api_url,
        settings.maya_api_key.get_secret_value(),
        settings.maya_voice,
        settings.maya_model,
    )
    if tts is not None:
        log.info("Maya text-to-speech enabled with text fallback")
    assistant = AssistantService(provider, DecisionEngine(settings.pending_action_ttl_minutes, calendar))
    message_worker = MessageWorker(
        database=database,
        assistant=assistant,
        transport=transport,
        owner_jid=settings.owner_jid,
        owner_timezone=settings.owner_timezone,
        media_dir=settings.media_dir,
        max_media_bytes=settings.max_media_bytes,
        tts=tts,
        web_fetcher=SafeWebFetcher(settings.max_media_bytes),
        queue_size=settings.message_queue_size,
    )
    reminder_worker = ReminderWorker(
        database=database,
        transport=transport,
        owner_jid=settings.owner_jid,
        poll_seconds=settings.reminder_poll_seconds,
    )
    transport.set_message_handler(message_worker.enqueue)
    message_worker.start()
    reminder_worker.start()
    try:
        connect_with_retry(
            transport,
            settings.whatsapp_reconnect_initial_seconds,
            settings.whatsapp_reconnect_max_seconds,
        )
    finally:
        reminder_worker.stop()
        message_worker.stop()
        database.dispose()


if __name__ == "__main__":
    main()
