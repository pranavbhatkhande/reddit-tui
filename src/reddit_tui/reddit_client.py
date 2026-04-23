"""Reddit JSON API client (async, httpx-based).

Supports two modes:
- **Anonymous**: hits ``https://www.reddit.com/*.json`` (read-only, no auth).
- **Authenticated**: hits ``https://oauth.reddit.com`` with a Bearer token,
  enabling voting, commenting, saving, subscribed feed, inbox, etc.

All public methods are coroutines. Use ``async with RedditClient(...) as c``
to ensure the underlying httpx client is closed; or call ``await c.aclose()``
manually.
"""
from __future__ import annotations

import asyncio
import getpass
import hashlib
import os
import platform
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx


def _build_default_user_agent() -> str:
    """Build a unique, descriptive User-Agent string per Reddit API guidelines.

    The UA includes the package version (from ``reddit_tui.__version__`` when
    available), a stable per-machine suffix derived from the hostname and
    username, and the correct repo URL.  The ``REDDIT_TUI_USER_AGENT``
    environment variable overrides everything.
    """
    env_ua = os.environ.get("REDDIT_TUI_USER_AGENT", "").strip()
    if env_ua:
        return env_ua

    try:
        from reddit_tui import __version__ as _ver  # type: ignore[attr-defined]
    except (ImportError, AttributeError):
        _ver = "0.3.0"

    # Stable per-install suffix: first 8 hex chars of SHA-256(hostname+username).
    machine_key = platform.node() + getpass.getuser()
    suffix = hashlib.sha256(machine_key.encode()).hexdigest()[:8]
    return (
        f"reddit-tui/{_ver} (terminal browser; "
        f"+https://github.com/pranavbhatkhande/reddit-tui; {suffix})"
    )


DEFAULT_USER_AGENT = _build_default_user_agent()
PUBLIC_BASE_URL = "https://www.reddit.com"
OLD_REDDIT_BASE_URL = "https://old.reddit.com"
OAUTH_BASE_URL = "https://oauth.reddit.com"
TIMEOUT = 15.0


def clean_sub(name: str) -> str:
    """Normalize a user-supplied subreddit name.

    Strips leading/trailing slashes, an optional ``r/`` prefix, and whitespace.
    Returns ``"all"`` for empty input.
    """
    s = (name or "").strip().strip("/").strip()
    if s.lower().startswith("r/"):
        s = s[2:]
    s = s.strip("/").strip()
    return s or "all"


class RedditError(Exception):
    """Raised when the Reddit API call fails."""


@dataclass
class Post:
    id: str
    name: str  # fullname, e.g. "t3_abc123"
    title: str
    author: str
    subreddit: str
    score: int
    num_comments: int
    permalink: str
    url: str
    selftext: str
    created_utc: float
    is_self: bool
    domain: str
    over_18: bool
    likes: bool | None = None  # True=upvoted, False=downvoted, None=no vote
    saved: bool = False

    @classmethod
    def from_json(cls, data: dict) -> Post:
        d = data.get("data", data)
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            title=d.get("title", "").strip(),
            author=d.get("author", "[deleted]"),
            subreddit=d.get("subreddit", ""),
            score=int(d.get("score", 0)),
            num_comments=int(d.get("num_comments", 0)),
            permalink=d.get("permalink", ""),
            url=d.get("url", ""),
            selftext=d.get("selftext", "") or "",
            created_utc=float(d.get("created_utc", 0)),
            is_self=bool(d.get("is_self", False)),
            domain=d.get("domain", ""),
            over_18=bool(d.get("over_18", False)),
            likes=d.get("likes"),
            saved=bool(d.get("saved", False)),
        )


@dataclass
class Comment:
    id: str
    name: str  # fullname, e.g. "t1_xyz"
    author: str
    body: str
    score: int
    created_utc: float
    depth: int = 0
    likes: bool | None = None
    saved: bool = False
    replies: list[object] = field(default_factory=list)  # List[Comment | MoreComments]

    @classmethod
    def from_json(cls, data: dict, depth: int = 0) -> Comment | None:
        if data.get("kind") != "t1":
            return None
        d = data.get("data", {})
        replies_data = d.get("replies")
        replies: list[object] = []
        if isinstance(replies_data, dict):
            for child in replies_data.get("data", {}).get("children", []):
                kind = child.get("kind")
                if kind == "t1":
                    c = cls.from_json(child, depth=depth + 1)
                    if c is not None:
                        replies.append(c)
                elif kind == "more":
                    m = MoreComments.from_json(child, depth=depth + 1)
                    if m is not None:
                        replies.append(m)
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            author=d.get("author", "[deleted]"),
            body=d.get("body", "") or "",
            score=int(d.get("score", 0)),
            created_utc=float(d.get("created_utc", 0)),
            depth=depth,
            likes=d.get("likes"),
            saved=bool(d.get("saved", False)),
            replies=replies,
        )


@dataclass
class MoreComments:
    """Represents a 'kind=more' placeholder pointing at unloaded children."""

    id: str
    name: str
    parent_id: str
    count: int
    depth: int
    children: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict, depth: int = 0) -> MoreComments | None:
        if data.get("kind") != "more":
            return None
        d = data.get("data", {})
        return cls(
            id=d.get("id", ""),
            name=d.get("name", "") or "",
            parent_id=d.get("parent_id", "") or "",
            count=int(d.get("count", 0) or 0),
            depth=depth,
            children=list(d.get("children", []) or []),
        )


@dataclass
class InboxItem:
    id: str
    name: str  # fullname, t1_xxx for comment reply, t4_xxx for PM
    kind: str  # "t1" or "t4"
    author: str
    subject: str
    body: str
    context: str  # permalink for comment replies
    created_utc: float
    new: bool  # unread
    subreddit: str

    @classmethod
    def from_json(cls, data: dict) -> InboxItem | None:
        kind = data.get("kind")
        if kind not in {"t1", "t4"}:
            return None
        d = data.get("data", {})
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            kind=kind,
            author=d.get("author", "[deleted]") or "[deleted]",
            subject=d.get("subject", "") or d.get("link_title", "") or "",
            body=d.get("body", "") or "",
            context=d.get("context", "") or "",
            created_utc=float(d.get("created_utc", 0)),
            new=bool(d.get("new", False)),
            subreddit=d.get("subreddit", "") or "",
        )


# Async token provider returns the bearer access token string.
TokenProvider = Callable[[], Awaitable[str]]


class RedditClient:
    """Async Reddit client. If a token provider is supplied, OAuth endpoints are used."""

    def __init__(
        self,
        token_provider: TokenProvider | None = None,
        username: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._token_provider = token_provider
        self.username = username
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.user_agent},
            timeout=TIMEOUT,
            follow_redirects=True,
            http2=False,
        )
        # Last seen rate-limit headers (for diagnostics / future backoff).
        self.rl_remaining: float | None = None
        self.rl_reset_at: float | None = None
        self._rl_lock = asyncio.Lock()

    async def __aenter__(self) -> RedditClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def authenticated(self) -> bool:
        return self._token_provider is not None

    async def _token(self) -> str | None:
        if self._token_provider is None:
            return None
        return await self._token_provider()

    def _base(self) -> str:
        return OAUTH_BASE_URL if self.authenticated else PUBLIC_BASE_URL

    async def _maybe_throttle(self) -> None:
        """Best-effort backoff if Reddit's rate-limit headers say we're near zero."""
        async with self._rl_lock:
            if (
                self.rl_remaining is not None
                and self.rl_remaining < 1.0
                and self.rl_reset_at is not None
            ):
                wait = max(0.0, self.rl_reset_at - time.monotonic())
                if wait > 0:
                    await asyncio.sleep(min(wait, 5.0))

    def _record_rate_limit(self, resp: httpx.Response) -> None:
        try:
            rem = resp.headers.get("x-ratelimit-remaining")
            reset = resp.headers.get("x-ratelimit-reset")
            if rem is not None:
                self.rl_remaining = float(rem)
            if reset is not None:
                self.rl_reset_at = time.monotonic() + float(reset)
        except (TypeError, ValueError):
            pass

    async def _req(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict | None = None,
        require_auth: bool = False,
    ) -> dict | list:
        await self._maybe_throttle()
        headers: dict[str, str] = {}
        if require_auth:
            token = await self._token()
            if not token:
                raise RedditError("This action requires logging in")
            headers["Authorization"] = f"Bearer {token}"
        else:
            token = await self._token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        try:
            resp = await self._client.request(
                method, url, headers=headers, data=data
            )
        except httpx.TimeoutException as e:
            raise RedditError("Request timed out") from e
        except httpx.HTTPError as e:
            raise RedditError(f"Network error: {e}") from e
        self._record_rate_limit(resp)
        if resp.status_code == 401 and require_auth:
            raise RedditError("Authentication expired or invalid")
        if resp.status_code == 429:
            raise RedditError("Rate limited by Reddit (HTTP 429)")
        if resp.status_code == 403:
            # For anonymous GETs targeting www.reddit.com, retry once against
            # old.reddit.com which is more permissive for unauthenticated reads.
            is_anonymous_get = (
                not headers.get("Authorization")
                and method.upper() == "GET"
                and url.startswith(PUBLIC_BASE_URL)
            )
            if is_anonymous_get:
                fallback_url = url.replace(PUBLIC_BASE_URL, OLD_REDDIT_BASE_URL, 1)
                try:
                    fb_resp = await self._client.request(
                        method, fallback_url, headers=headers, data=data
                    )
                except httpx.TimeoutException as e:
                    raise RedditError("Request timed out") from e
                except httpx.HTTPError as e:
                    raise RedditError(f"Network error: {e}") from e
                self._record_rate_limit(fb_resp)
                if fb_resp.status_code < 400:
                    if not fb_resp.content:
                        return {}
                    try:
                        return fb_resp.json()
                    except ValueError as e:
                        raise RedditError("Invalid JSON from Reddit") from e
            # Both hosts failed (or non-anonymous/non-GET) — surface a helpful message.
            if not headers.get("Authorization"):
                raise RedditError(
                    "HTTP 403 from Reddit (anonymous). Try logging in (see README)"
                    " or set REDDIT_TUI_USER_AGENT to a unique value."
                )
            raise RedditError(
                "HTTP 403 from Reddit — insufficient permissions or private subreddit."
            )
        if resp.status_code >= 400:
            raise RedditError(f"HTTP {resp.status_code} fetching {url}")
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as e:
            raise RedditError("Invalid JSON from Reddit") from e

    # ---------- read endpoints ----------

    async def get_subreddit_posts(
        self,
        subreddit: str,
        sort: str = "hot",
        limit: int = 25,
        after: str | None = None,
    ) -> list[Post]:
        sub = clean_sub(subreddit)
        sort = sort if sort in {"hot", "new", "top", "rising", "controversial"} else "hot"
        params = {"limit": str(limit), "raw_json": "1"}
        if after:
            params["after"] = after
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}/r/{urllib.parse.quote(sub)}/{sort}{suffix}?{urllib.parse.urlencode(params)}"
        data = await self._req(url)
        if not isinstance(data, dict):
            return []
        children = data.get("data", {}).get("children", [])
        return [Post.from_json(c) for c in children if c.get("kind") == "t3"]

    async def get_frontpage(self, sort: str = "hot", limit: int = 25) -> list[Post]:
        return await self.get_subreddit_posts("popular", sort=sort, limit=limit)

    async def get_post_with_comments(
        self, permalink: str
    ) -> tuple[Post, list[object]]:
        """Return (post, top-level items). Items are Comment or MoreComments."""
        link = permalink if permalink.startswith("/") else f"/{permalink}"
        if link.endswith("/"):
            link = link[:-1]
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}{link}{suffix}?raw_json=1&limit=200"
        data = await self._req(url)
        if not isinstance(data, list) or len(data) < 2:
            raise RedditError("Unexpected response shape for post")
        post_listing = data[0].get("data", {}).get("children", [])
        if not post_listing:
            raise RedditError("Post not found")
        post = Post.from_json(post_listing[0])
        items: list[object] = []
        for child in data[1].get("data", {}).get("children", []):
            kind = child.get("kind")
            if kind == "t1":
                c = Comment.from_json(child, depth=0)
                if c is not None:
                    items.append(c)
            elif kind == "more":
                m = MoreComments.from_json(child, depth=0)
                if m is not None:
                    items.append(m)
        return post, items

    async def get_more_children(
        self, link_fullname: str, child_ids: list[str], sort: str = "confidence"
    ) -> list[object]:
        if not child_ids:
            return []
        params = {
            "api_type": "json",
            "link_id": link_fullname,
            "children": ",".join(child_ids[:100]),
            "sort": sort,
            "raw_json": "1",
        }
        url = f"{self._base()}/api/morechildren?{urllib.parse.urlencode(params)}"
        data = await self._req(url)
        if not isinstance(data, dict):
            return []
        things = data.get("json", {}).get("data", {}).get("things", [])
        out: list[object] = []
        for child in things:
            kind = child.get("kind")
            if kind == "t1":
                c = Comment.from_json(child, depth=0)
                if c is not None:
                    out.append(c)
            elif kind == "more":
                m = MoreComments.from_json(child, depth=0)
                if m is not None:
                    out.append(m)
        return out

    async def search_subreddits(self, query: str, limit: int = 25) -> list[dict]:
        params = {"q": query, "limit": str(limit), "raw_json": "1"}
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}/subreddits/search{suffix}?{urllib.parse.urlencode(params)}"
        data = await self._req(url)
        if not isinstance(data, dict):
            return []
        children = data.get("data", {}).get("children", [])
        return [c.get("data", {}) for c in children]

    # ---------- authenticated-only endpoints ----------

    async def get_subscribed_subreddits(self) -> list[str]:
        """Return list of subreddit display names the user is subscribed to."""
        if not self.authenticated:
            raise RedditError("This action requires logging in")
        names: list[str] = []
        after: str | None = None
        for _ in range(5):
            params = {"limit": "100", "raw_json": "1"}
            if after:
                params["after"] = after
            url = f"{OAUTH_BASE_URL}/subreddits/mine/subscriber?{urllib.parse.urlencode(params)}"
            data = await self._req(url, require_auth=True)
            if not isinstance(data, dict):
                break
            children = data.get("data", {}).get("children", [])
            for c in children:
                d = c.get("data", {})
                name = d.get("display_name")
                if name:
                    names.append(name)
            after = data.get("data", {}).get("after")
            if not after:
                break
        return sorted(names, key=str.lower)

    async def vote(self, fullname: str, direction: int) -> None:
        """direction: 1=upvote, 0=clear, -1=downvote."""
        if direction not in (-1, 0, 1):
            raise RedditError(f"Invalid vote direction: {direction}")
        await self._req(
            f"{OAUTH_BASE_URL}/api/vote",
            method="POST",
            data={"id": fullname, "dir": str(direction)},
            require_auth=True,
        )

    async def save(self, fullname: str) -> None:
        await self._req(
            f"{OAUTH_BASE_URL}/api/save",
            method="POST",
            data={"id": fullname},
            require_auth=True,
        )

    async def unsave(self, fullname: str) -> None:
        await self._req(
            f"{OAUTH_BASE_URL}/api/unsave",
            method="POST",
            data={"id": fullname},
            require_auth=True,
        )

    async def submit_comment(self, parent_fullname: str, text: str) -> None:
        resp = await self._req(
            f"{OAUTH_BASE_URL}/api/comment",
            method="POST",
            data={"thing_id": parent_fullname, "text": text, "api_type": "json"},
            require_auth=True,
        )
        errs = (
            resp.get("json", {}).get("errors", [])
            if isinstance(resp, dict)
            else []
        )
        if errs:
            raise RedditError(f"Comment failed: {errs[0]}")

    async def get_inbox(self, only_unread: bool = False) -> list[InboxItem]:
        endpoint = "unread" if only_unread else "inbox"
        url = f"{OAUTH_BASE_URL}/message/{endpoint}?raw_json=1&limit=50"
        data = await self._req(url, require_auth=True)
        if not isinstance(data, dict):
            return []
        children = data.get("data", {}).get("children", [])
        items: list[InboxItem] = []
        for c in children:
            it = InboxItem.from_json(c)
            if it is not None:
                items.append(it)
        return items

    async def get_unread_count(self) -> int:
        if not self.authenticated:
            return 0
        try:
            data = await self._req(f"{OAUTH_BASE_URL}/api/v1/me", require_auth=True)
        except RedditError:
            return 0
        if not isinstance(data, dict):
            return 0
        try:
            return int(data.get("inbox_count", 0) or 0)
        except (TypeError, ValueError):
            return 0

    async def mark_read(self, fullname: str) -> None:
        await self._req(
            f"{OAUTH_BASE_URL}/api/read_message",
            method="POST",
            data={"id": fullname},
            require_auth=True,
        )
