"""Reddit JSON API client.

Supports two modes:
- **Anonymous**: hits https://www.reddit.com/*.json (read-only, no auth).
- **Authenticated**: hits https://oauth.reddit.com with a Bearer token,
  enabling voting, commenting, saving, subscribed feed, inbox, etc.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional

DEFAULT_USER_AGENT = (
    "reddit-tui/0.3.0 (terminal browser; +https://github.com/anomalyco/reddit-tui)"
)
PUBLIC_BASE_URL = "https://www.reddit.com"
OAUTH_BASE_URL = "https://oauth.reddit.com"
TIMEOUT = 15


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
    likes: Optional[bool] = None  # True=upvoted, False=downvoted, None=no vote
    saved: bool = False

    @classmethod
    def from_json(cls, data: dict) -> "Post":
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
    likes: Optional[bool] = None
    saved: bool = False
    replies: List[object] = field(default_factory=list)  # List[Comment | MoreComments]

    @classmethod
    def from_json(cls, data: dict, depth: int = 0) -> Optional["Comment"]:
        if data.get("kind") != "t1":
            return None
        d = data.get("data", {})
        replies_data = d.get("replies")
        replies: List[object] = []
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
    """Represents a 't1 kind=more' placeholder pointing at unloaded children."""

    id: str
    name: str  # fullname (often "t1_..." or empty for "continue this thread")
    parent_id: str
    count: int
    depth: int
    children: List[str] = field(default_factory=list)  # child comment ids

    @classmethod
    def from_json(cls, data: dict, depth: int = 0) -> Optional["MoreComments"]:
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
    def from_json(cls, data: dict) -> Optional["InboxItem"]:
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


def _request(
    url: str,
    *,
    token: Optional[str] = None,
    method: str = "GET",
    data: Optional[bytes] = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict:
    headers = {"User-Agent": user_agent}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise RedditError(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise RedditError(f"Network error: {e.reason}") from e
    except TimeoutError as e:
        raise RedditError("Request timed out") from e
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RedditError("Invalid JSON from Reddit") from e


class RedditClient:
    """Reddit client. If a token provider is supplied, OAuth endpoints are used."""

    def __init__(
        self,
        token_provider: Optional[Callable[[], str]] = None,
        username: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self._token_provider = token_provider
        self.username = username
        self.user_agent = user_agent or DEFAULT_USER_AGENT

    @property
    def authenticated(self) -> bool:
        return self._token_provider is not None

    def _token(self) -> Optional[str]:
        if self._token_provider is None:
            return None
        return self._token_provider()

    def _req(
        self,
        url: str,
        *,
        method: str = "GET",
        data: Optional[bytes] = None,
        require_auth: bool = False,
    ) -> dict:
        token = self._require_auth() if require_auth else self._token()
        return _request(
            url,
            token=token,
            method=method,
            data=data,
            user_agent=self.user_agent,
        )

    def _base(self) -> str:
        return OAUTH_BASE_URL if self.authenticated else PUBLIC_BASE_URL

    # ---------- read endpoints ----------

    def get_subreddit_posts(
        self,
        subreddit: str,
        sort: str = "hot",
        limit: int = 25,
        after: Optional[str] = None,
    ) -> List[Post]:
        sub = clean_sub(subreddit)
        sort = sort if sort in {"hot", "new", "top", "rising", "controversial"} else "hot"
        params = {"limit": str(limit), "raw_json": "1"}
        if after:
            params["after"] = after
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}/r/{urllib.parse.quote(sub)}/{sort}{suffix}?{urllib.parse.urlencode(params)}"
        data = self._req(url)
        children = data.get("data", {}).get("children", [])
        return [Post.from_json(c) for c in children if c.get("kind") == "t3"]

    def get_frontpage(self, sort: str = "hot", limit: int = 25) -> List[Post]:
        return self.get_subreddit_posts("popular", sort=sort, limit=limit)

    def get_post_with_comments(
        self, permalink: str
    ) -> tuple[Post, List[object]]:
        """Return (post, top-level items). Items are Comment or MoreComments."""
        link = permalink if permalink.startswith("/") else f"/{permalink}"
        if link.endswith("/"):
            link = link[:-1]
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}{link}{suffix}?raw_json=1&limit=200"
        data = self._req(url)
        if not isinstance(data, list) or len(data) < 2:
            raise RedditError("Unexpected response shape for post")
        post_listing = data[0].get("data", {}).get("children", [])
        if not post_listing:
            raise RedditError("Post not found")
        post = Post.from_json(post_listing[0])
        items: List[object] = []
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

    def get_more_children(
        self, link_fullname: str, child_ids: List[str], sort: str = "confidence"
    ) -> List[object]:
        """Expand a 'more' placeholder. Returns flat list of Comment/MoreComments
        in pre-order; parent linkage is preserved by the comments' parent_id but
        the caller is responsible for re-threading them under their parents.
        """
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
        data = self._req(url)
        things = (
            data.get("json", {}).get("data", {}).get("things", [])
            if isinstance(data, dict)
            else []
        )
        out: List[object] = []
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

    def search_subreddits(self, query: str, limit: int = 25) -> List[dict]:
        params = {"q": query, "limit": str(limit), "raw_json": "1"}
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}/subreddits/search{suffix}?{urllib.parse.urlencode(params)}"
        data = self._req(url)
        children = data.get("data", {}).get("children", [])
        return [c.get("data", {}) for c in children]

    # ---------- authenticated-only endpoints ----------

    def _require_auth(self) -> str:
        token = self._token()
        if not token:
            raise RedditError("This action requires logging in")
        return token

    def get_subscribed_subreddits(self) -> List[str]:
        """Return list of subreddit display names the user is subscribed to."""
        self._require_auth()
        names: List[str] = []
        after: Optional[str] = None
        # Paginate up to ~500 subscriptions
        for _ in range(5):
            params = {"limit": "100", "raw_json": "1"}
            if after:
                params["after"] = after
            url = f"{OAUTH_BASE_URL}/subreddits/mine/subscriber?{urllib.parse.urlencode(params)}"
            data = self._req(url, require_auth=True)
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

    def vote(self, fullname: str, direction: int) -> None:
        """direction: 1=upvote, 0=clear, -1=downvote."""
        if direction not in (-1, 0, 1):
            raise RedditError(f"Invalid vote direction: {direction}")
        body = urllib.parse.urlencode({"id": fullname, "dir": str(direction)}).encode("utf-8")
        self._req(f"{OAUTH_BASE_URL}/api/vote", method="POST", data=body, require_auth=True)

    def save(self, fullname: str) -> None:
        body = urllib.parse.urlencode({"id": fullname}).encode("utf-8")
        self._req(f"{OAUTH_BASE_URL}/api/save", method="POST", data=body, require_auth=True)

    def unsave(self, fullname: str) -> None:
        body = urllib.parse.urlencode({"id": fullname}).encode("utf-8")
        self._req(f"{OAUTH_BASE_URL}/api/unsave", method="POST", data=body, require_auth=True)

    def submit_comment(self, parent_fullname: str, text: str) -> None:
        body = urllib.parse.urlencode(
            {"thing_id": parent_fullname, "text": text, "api_type": "json"}
        ).encode("utf-8")
        resp = self._req(
            f"{OAUTH_BASE_URL}/api/comment", method="POST", data=body, require_auth=True
        )
        # Reddit returns errors inside json.errors
        errs = resp.get("json", {}).get("errors", [])
        if errs:
            raise RedditError(f"Comment failed: {errs[0]}")

    def get_inbox(self, only_unread: bool = False) -> List[InboxItem]:
        endpoint = "unread" if only_unread else "inbox"
        url = f"{OAUTH_BASE_URL}/message/{endpoint}?raw_json=1&limit=50"
        data = self._req(url, require_auth=True)
        children = data.get("data", {}).get("children", [])
        items: List[InboxItem] = []
        for c in children:
            it = InboxItem.from_json(c)
            if it is not None:
                items.append(it)
        return items

    def get_unread_count(self) -> int:
        if not self.authenticated:
            return 0
        try:
            data = self._req(f"{OAUTH_BASE_URL}/api/v1/me", require_auth=True)
        except RedditError:
            return 0
        try:
            return int(data.get("inbox_count", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def mark_read(self, fullname: str) -> None:
        body = urllib.parse.urlencode({"id": fullname}).encode("utf-8")
        self._req(
            f"{OAUTH_BASE_URL}/api/read_message", method="POST", data=body, require_auth=True
        )
