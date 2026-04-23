"""Tests for the CLI dispatcher (status & help paths only)."""
from __future__ import annotations

from pathlib import Path

import pytest

from reddit_tui import cli


def test_status_no_creds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from reddit_tui import auth

    monkeypatch.setattr(auth, "_try_keyring", lambda: None)
    monkeypatch.setattr(auth, "CONFIG_PATH", tmp_path / "missing-config.json")
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "missing-token.json")
    rc = cli.main(["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "credentials: none" in out
    assert "absent" in out


def test_help_runs(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "reddit-tui" in out
    assert "login" in out
    assert "logout" in out


def test_unknown_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        cli.main(["bogus"])
