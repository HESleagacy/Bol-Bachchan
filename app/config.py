from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    owner_jid: str = Field(description="Allowed WhatsApp owner JID")
    owner_timezone: str = "Asia/Kolkata"
    database_url: str = "sqlite:///data/bol_bachchan.db"
    neonize_session_path: Path = Path("data/neonize.db")
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"
    message_queue_size: int = Field(default=100, ge=1)
    pending_action_ttl_minutes: int = Field(default=30, ge=1)
    log_level: str = "INFO"
    reminder_poll_seconds: int = Field(default=10, ge=1)
    media_dir: Path = Path("data/media")
    max_media_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    maya_api_url: str = ""
    maya_api_key: SecretStr = SecretStr("")
    maya_voice: str = "default"
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_refresh_token: SecretStr = SecretStr("")
    google_calendar_id: str = "primary"

    @field_validator("owner_jid")
    @classmethod
    def normalize_owner_jid(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            value = f"{value}@s.whatsapp.net"
        if value.endswith("@c.us"):
            value = value.removesuffix("@c.us") + "@s.whatsapp.net"
        if not value.split("@", 1)[0]:
            raise ValueError("OWNER_JID must contain a phone number")
        return value

    @field_validator("owner_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {value}") from exc
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
