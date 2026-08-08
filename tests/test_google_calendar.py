from __future__ import annotations

import json

from app.providers.google_calendar import load_refresh_token


def test_configured_google_refresh_token_takes_precedence(tmp_path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({"refresh_token": "file-token"}))

    assert load_refresh_token("env-token", token_path) == "env-token"


def test_google_refresh_token_loads_from_private_file(tmp_path) -> None:
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({"refresh_token": "file-token"}))

    assert load_refresh_token("", token_path) == "file-token"
