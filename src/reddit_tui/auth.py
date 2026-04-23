"""Reddit OAuth 2.0 (script app) authentication.

Uses Reddit's "script" app type, which lets a single user authenticate via
their own client_id/client_secret + username/password.

Credentials may be provided via either:

1. ``~/.config/reddit-tui/config.json`` (legacy plaintext file), or
2. The system keyring (recommended). Use ``reddit-tui login`` to store.

Tokens are cached at ``~/.config/reddit-tui/auth.json`` and refreshed when
they expire. Refresh is serialized via an asyncio lock so concurrent callers
don't trigger duplicate refreshes.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import httpx

DEFAULT_USER_AGENT = (
    "reddit-tui/0.3.0 (terminal browser; +https://github.com/anomalyco/reddit-tui)"
)
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
TIMEOUT = 15.0

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "reddit-tui"
CONFIG_PATH = CONFIG_DIR / "config.json"
TOKEN_PATH = CONFIG_DIR / "auth.json"

KEYRING_SERVICE = "reddit-tui"
KEYRING_FIELDS = ("client_id", "client_secret", "username", "password", "user_agent")

_REFRESH_LOCK = asyncio.Lock()
_CACHED_TOKEN: Optional["TokenStore"] = None


class AuthError(Exception):
    """Raised when authentication fails or config is missing/invalid."""


@dataclass
class AuthConfig:
    client_id: str
    client_secret: str
    username: str
    password: str
    user_agent: str = DEFAULT_USER_AGENT


@dataclass
class TokenStore:
    access_token: str
    expires_at: float  # epoch seconds
    username: str


def _try_keyring() -> Optional[AuthConfig]:
    """Return AuthConfig from system keyring if all required fields present."""
    try:
        import keyring  # type: ignore
    except Exception:
        return None
    try:
        values = {f: keyring.get_password(KEYRING_SERVICE, f) for f in KEYRING_FIELDS}
    except Exception:
        return None
    required = ("client_id", "client_secret", "username", "password")
    if not all(values.get(k) for k in required):
        return None
    return AuthConfig(
        client_id=values["client_id"],
        client_secret=values["client_secret"],
        username=values["username"],
        password=values["password"],
        user_agent=values.get("user_agent") or DEFAULT_USER_AGENT,
    )


def save_to_keyring(cfg: AuthConfig) -> None:
    """Persist AuthConfig fields to the system keyring. Raises if unavailable."""
    import keyring  # type: ignore

    keyring.set_password(KEYRING_SERVICE, "client_id", cfg.client_id)
    keyring.set_password(KEYRING_SERVICE, "client_secret", cfg.client_secret)
    keyring.set_password(KEYRING_SERVICE, "username", cfg.username)
    keyring.set_password(KEYRING_SERVICE, "password", cfg.password)
    keyring.set_password(KEYRING_SERVICE, "user_agent", cfg.user_agent)


def delete_from_keyring() -> None:
    """Best-effort wipe of all keyring entries."""
    try:
        import keyring  # type: ignore
    except Exception:
        return
    for f in KEYRING_FIELDS:
        try:
            keyring.delete_password(KEYRING_SERVICE, f)
        except Exception:
            pass


def load_config() -> Optional[AuthConfig]:
    """Return the user's auth config, or None if not configured.

    Resolution order: keyring → ``~/.config/reddit-tui/config.json``.
    """
    kr = _try_keyring()
    if kr is not None:
        return kr
    if not CONFIG_PATH.exists():
        return None
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise AuthError(f"Failed to read {CONFIG_PATH}: {e}") from e
    required = ("client_id", "client_secret", "username", "password")
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise AuthError(f"Missing keys in {CONFIG_PATH}: {', '.join(missing)}")
    ua = data.get("user_agent") or DEFAULT_USER_AGENT
    return AuthConfig(
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        username=data["username"],
        password=data["password"],
        user_agent=ua,
    )


def load_token() -> Optional[TokenStore]:
    if not TOKEN_PATH.exists():
        return None
    try:
        with TOKEN_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return TokenStore(
            access_token=data["access_token"],
            expires_at=float(data["expires_at"]),
            username=data["username"],
        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None


def save_token(token: TokenStore) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with TOKEN_PATH.open("w", encoding="utf-8") as f:
        json.dump(asdict(token), f, indent=2)
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass


async def fetch_token(config: AuthConfig) -> TokenStore:
    """Exchange username+password for a bearer token via the script app flow."""
    basic = base64.b64encode(
        f"{config.client_id}:{config.client_secret}".encode("utf-8")
    ).decode("ascii")
    headers = {
        "User-Agent": config.user_agent,
        "Authorization": f"Basic {basic}",
    }
    body = {
        "grant_type": "password",
        "username": config.username,
        "password": config.password,
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(TOKEN_URL, headers=headers, data=body)
    except httpx.TimeoutException as e:
        raise AuthError("Auth request timed out") from e
    except httpx.HTTPError as e:
        raise AuthError(f"Network error during auth: {e}") from e
    if resp.status_code >= 400:
        raise AuthError(f"Auth failed: HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as e:
        raise AuthError("Invalid JSON from token endpoint") from e
    if "error" in data or "access_token" not in data:
        raise AuthError(f"Token error: {data.get('error', 'unknown')}")
    expires_in = int(data.get("expires_in", 3600))
    return TokenStore(
        access_token=data["access_token"],
        expires_at=time.time() + expires_in,
        username=config.username,
    )


def _is_fresh(token: Optional[TokenStore], username: str) -> bool:
    return (
        token is not None
        and token.username == username
        and token.expires_at - time.time() > 60
    )


async def get_valid_token(config: AuthConfig, force_refresh: bool = False) -> TokenStore:
    """Return a non-expired token, refreshing if necessary.

    Coroutine-safe: serialized via an asyncio lock. Concurrent callers all
    receive the same freshly-fetched token.
    """
    global _CACHED_TOKEN

    if not force_refresh and _is_fresh(_CACHED_TOKEN, config.username):
        return _CACHED_TOKEN  # type: ignore[return-value]

    async with _REFRESH_LOCK:
        if not force_refresh and _is_fresh(_CACHED_TOKEN, config.username):
            return _CACHED_TOKEN  # type: ignore[return-value]
        if not force_refresh:
            disk = load_token()
            if _is_fresh(disk, config.username):
                _CACHED_TOKEN = disk
                return disk  # type: ignore[return-value]
        token = await fetch_token(config)
        save_token(token)
        _CACHED_TOKEN = token
        return token


def reset_cache() -> None:
    """Clear the in-memory token cache (mainly for tests)."""
    global _CACHED_TOKEN
    _CACHED_TOKEN = None
