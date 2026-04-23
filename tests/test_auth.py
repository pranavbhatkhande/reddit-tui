"""Tests for auth config loading and freshness checks."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from reddit_tui import auth


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CONFIG_DIR/CONFIG_PATH/TOKEN_PATH to a temp dir."""
    monkeypatch.setattr(auth, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(auth, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "auth.json")
    # Force keyring to return None so file path is exercised.
    monkeypatch.setattr(auth, "_try_keyring", lambda: None)
    auth.reset_cache()
    return tmp_path


class TestLoadConfig:
    def test_no_file(self, tmp_config: Path) -> None:
        assert auth.load_config() is None

    def test_valid(self, tmp_config: Path) -> None:
        (tmp_config / "config.json").write_text(json.dumps({
            "client_id": "cid",
            "client_secret": "csec",
            "username": "u",
            "password": "p",
        }))
        cfg = auth.load_config()
        assert cfg is not None
        assert cfg.username == "u"
        assert cfg.user_agent == auth.DEFAULT_USER_AGENT

    def test_missing_keys(self, tmp_config: Path) -> None:
        (tmp_config / "config.json").write_text(json.dumps({"client_id": "x"}))
        with pytest.raises(auth.AuthError, match="Missing keys"):
            auth.load_config()

    def test_custom_user_agent(self, tmp_config: Path) -> None:
        (tmp_config / "config.json").write_text(json.dumps({
            "client_id": "c", "client_secret": "s",
            "username": "u", "password": "p",
            "user_agent": "MyApp/1.0",
        }))
        cfg = auth.load_config()
        assert cfg is not None
        assert cfg.user_agent == "MyApp/1.0"


class TestIsFresh:
    def test_none(self) -> None:
        assert auth._is_fresh(None, "u") is False

    def test_expired(self) -> None:
        t = auth.TokenStore(
            access_token="a", expires_at=time.time() - 10, username="u"
        )
        assert auth._is_fresh(t, "u") is False

    def test_fresh(self) -> None:
        t = auth.TokenStore(
            access_token="a", expires_at=time.time() + 3600, username="u"
        )
        assert auth._is_fresh(t, "u") is True

    def test_wrong_user(self) -> None:
        t = auth.TokenStore(
            access_token="a", expires_at=time.time() + 3600, username="u"
        )
        assert auth._is_fresh(t, "other") is False

    def test_too_close_to_expiry(self) -> None:
        t = auth.TokenStore(
            access_token="a", expires_at=time.time() + 30, username="u"
        )
        # We require >60s remaining.
        assert auth._is_fresh(t, "u") is False


class TestSaveLoadToken:
    def test_round_trip(self, tmp_config: Path) -> None:
        t = auth.TokenStore(
            access_token="abc", expires_at=time.time() + 3600, username="u"
        )
        auth.save_token(t)
        loaded = auth.load_token()
        assert loaded is not None
        assert loaded.access_token == "abc"
        assert loaded.username == "u"
