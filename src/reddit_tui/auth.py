"""Reddit OAuth 2.0 (script app) authentication.

Uses Reddit's "script" app type, which lets a single user authenticate via
their own client_id/client_secret + username/password. The user must create a
"script" app at https://www.reddit.com/prefs/apps and store the credentials in
``~/.config/reddit-tui/config.json``::

    {
      "client_id": "xxxxxxxxxxxxxx",
      "client_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxx",
      "username": "your_reddit_username",
      "password": "your_reddit_password",
      "user_agent": "optional custom UA string"
    }

Tokens are cached at ``~/.config/reddit-tui/auth.json`` and refreshed when
they expire. Token refresh is serialized via a process-wide lock so concurrent
requests from worker threads can't trigger duplicate refreshes.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

DEFAULT_USER_AGENT = (
    "reddit-tui/0.3.0 (terminal browser; +https://github.com/anomalyco/reddit-tui)"
)
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
TIMEOUT = 15

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "reddit-tui"
CONFIG_PATH = CONFIG_DIR / "config.json"
TOKEN_PATH = CONFIG_DIR / "auth.json"

# Process-wide refresh lock + in-memory cache. Worker threads that need a
# token call ``get_valid_token`` concurrently; the lock guarantees only one
# network refresh happens at a time and the cache avoids re-reading the file.
_REFRESH_LOCK = threading.Lock()
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


def load_config() -> Optional[AuthConfig]:
    """Return the user's auth config, or None if not configured."""
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


def fetch_token(config: AuthConfig) -> TokenStore:
    """Exchange username+password for a bearer token via the script app flow."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "username": config.username,
            "password": config.password,
        }
    ).encode("utf-8")
    basic = base64.b64encode(
        f"{config.client_id}:{config.client_secret}".encode("utf-8")
    ).decode("ascii")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "User-Agent": config.user_agent,
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise AuthError(f"Auth failed: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise AuthError(f"Network error during auth: {e.reason}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
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
    # 60-second buffer
    return (
        token is not None
        and token.username == username
        and token.expires_at - time.time() > 60
    )


def get_valid_token(config: AuthConfig, force_refresh: bool = False) -> TokenStore:
    """Return a non-expired token, refreshing if necessary.

    Thread-safe: serialized via a module-level lock. The first thread to enter
    after expiry will hit the network; subsequent threads get the cached token.
    """
    global _CACHED_TOKEN

    if not force_refresh and _is_fresh(_CACHED_TOKEN, config.username):
        return _CACHED_TOKEN  # type: ignore[return-value]

    with _REFRESH_LOCK:
        # Re-check inside the lock in case another thread refreshed.
        if not force_refresh and _is_fresh(_CACHED_TOKEN, config.username):
            return _CACHED_TOKEN  # type: ignore[return-value]
        if not force_refresh:
            disk = load_token()
            if _is_fresh(disk, config.username):
                _CACHED_TOKEN = disk
                return disk  # type: ignore[return-value]
        token = fetch_token(config)
        save_token(token)
        _CACHED_TOKEN = token
        return token


def reset_cache() -> None:
    """Clear the in-memory token cache (mainly for tests)."""
    global _CACHED_TOKEN
    with _REFRESH_LOCK:
        _CACHED_TOKEN = None
