"""HTTP-level tests for RedditClient: User-Agent, 403 fallback, error messages."""
from __future__ import annotations

import getpass
import hashlib
import platform
from typing import Any

import httpx
import pytest

from reddit_tui.reddit_client import (
    OLD_REDDIT_BASE_URL,
    RedditClient,
    RedditError,
    _build_default_user_agent,
)

# ---------------------------------------------------------------------------
# Minimal valid comments response payload (two-element list expected by
# get_post_with_comments).
# ---------------------------------------------------------------------------
VALID_COMMENTS_PAYLOAD: list[Any] = [
    {
        "data": {
            "children": [
                {
                    "kind": "t3",
                    "data": {
                        "id": "abc",
                        "name": "t3_abc",
                        "title": "Test Post",
                        "author": "u_test",
                        "subreddit": "test",
                        "score": 10,
                        "num_comments": 1,
                        "permalink": "/r/test/comments/abc/test_post/",
                        "url": "https://www.reddit.com/r/test/comments/abc/test_post/",
                        "selftext": "",
                        "created_utc": 1700000000.0,
                        "is_self": True,
                        "domain": "self.test",
                        "over_18": False,
                    },
                }
            ]
        }
    },
    {
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "id": "xyz",
                        "name": "t1_xyz",
                        "author": "commenter",
                        "body": "A comment",
                        "score": 5,
                        "created_utc": 1700001000.0,
                        "replies": "",
                    },
                }
            ]
        }
    },
]


def _make_client_with_transport(transport: httpx.MockTransport) -> RedditClient:
    """Return a RedditClient whose underlying httpx client uses *transport*."""
    client = RedditClient()
    # Replace the internal AsyncClient with one backed by the mock transport.
    client._client = httpx.AsyncClient(
        transport=transport,
        headers={"User-Agent": client.user_agent},
        timeout=15.0,
        follow_redirects=True,
    )
    return client


# ---------------------------------------------------------------------------
# User-Agent tests
# ---------------------------------------------------------------------------


class TestDefaultUserAgent:
    def test_unique_per_host(self) -> None:
        """Two instances on the same machine must produce the same UA."""
        ua1 = _build_default_user_agent()
        ua2 = _build_default_user_agent()
        assert ua1 == ua2

    def test_contains_correct_repo_url(self) -> None:
        ua = _build_default_user_agent()
        assert "pranavbhatkhande/reddit-tui" in ua
        assert "anomalyco" not in ua

    def test_contains_per_install_suffix(self) -> None:
        machine_key = platform.node() + getpass.getuser()
        expected_suffix = hashlib.sha256(machine_key.encode()).hexdigest()[:8]
        ua = _build_default_user_agent()
        assert expected_suffix in ua

    def test_env_var_overrides_user_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REDDIT_TUI_USER_AGENT", "my-custom-ua/1.0")
        ua = _build_default_user_agent()
        assert ua == "my-custom-ua/1.0"

    def test_env_var_empty_does_not_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REDDIT_TUI_USER_AGENT", "  ")
        ua = _build_default_user_agent()
        # Empty / whitespace-only env var must not override the computed default.
        assert "pranavbhatkhande" in ua


# ---------------------------------------------------------------------------
# 403 fallback and error message tests
# ---------------------------------------------------------------------------


class TestAnonymous403Fallback:
    async def test_falls_back_to_old_reddit(self) -> None:
        """www.reddit.com → 403, old.reddit.com → 200 must succeed."""
        requests_seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(str(request.url))
            if request.url.host == "www.reddit.com":
                return httpx.Response(403)
            # old.reddit.com responds with valid payload.
            return httpx.Response(200, json=VALID_COMMENTS_PAYLOAD)

        client = _make_client_with_transport(httpx.MockTransport(handler))
        async with client:
            post, comments = await client.get_post_with_comments(
                "/r/test/comments/abc/test_post/"
            )

        assert post.id == "abc"
        assert len(comments) == 1
        assert any(OLD_REDDIT_BASE_URL in url for url in requests_seen), (
            f"Expected a request to {OLD_REDDIT_BASE_URL}; saw: {requests_seen}"
        )

    async def test_double_failure_raises_friendly_error(self) -> None:
        """Both www and old.reddit.com return 403 → friendly RedditError."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        client = _make_client_with_transport(httpx.MockTransport(handler))
        with pytest.raises(RedditError) as exc_info:
            async with client:
                await client.get_post_with_comments(
                    "/r/test/comments/abc/test_post/"
                )

        msg = str(exc_info.value)
        assert "log in" in msg.lower() or "REDDIT_TUI_USER_AGENT" in msg

    async def test_authenticated_403_does_not_fall_back(self) -> None:
        """Authenticated (oauth.reddit.com) 403 must NOT trigger old.reddit.com."""
        requests_seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(str(request.url))
            return httpx.Response(403)

        async def token_provider() -> str:
            return "fake-token"

        client = RedditClient(token_provider=token_provider)
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"User-Agent": client.user_agent},
            timeout=15.0,
            follow_redirects=True,
        )

        with pytest.raises(RedditError) as exc_info:
            async with client:
                await client.get_post_with_comments(
                    "/r/test/comments/abc/test_post/"
                )

        # Only one request should have been made (no old.reddit.com retry).
        assert len(requests_seen) == 1, (
            f"Expected exactly 1 request, got: {requests_seen}"
        )
        assert "old.reddit.com" not in requests_seen[0]
        # The error should mention permissions, not "log in".
        msg = str(exc_info.value)
        assert "insufficient permissions" in msg or "private" in msg
