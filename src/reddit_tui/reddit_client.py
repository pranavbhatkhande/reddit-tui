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

USER_AGENT = "reddit-tui/0.2.0 (terminal browser; +https://github.com/local/reddit-tui)"
PUBLIC_BASE_URL = "https://www.reddit.com"
OAUTH_BASE_URL = "https://oauth.reddit.com"
TIMEOUT = 15


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
    replies: List["Comment"] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict, depth: int = 0) -> Optional["Comment"]:
        if data.get("kind") != "t1":
            return None
        d = data.get("data", {})
        replies_data = d.get("replies")
        replies: List[Comment] = []
        if isinstance(replies_data, dict):
            for child in replies_data.get("data", {}).get("children", []):
                c = cls.from_json(child, depth=depth + 1)
                if c is not None:
                    replies.append(c)
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
) -> dict:
    headers = {"User-Agent": USER_AGENT}
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
    ) -> None:
        self._token_provider = token_provider
        self.username = username

    @property
    def authenticated(self) -> bool:
        return self._token_provider is not None

    def _token(self) -> Optional[str]:
        if self._token_provider is None:
            return None
        return self._token_provider()

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
        sub = subreddit.strip().lstrip("/").removeprefix("r/")
        if not sub:
            sub = "all"
        sort = sort if sort in {"hot", "new", "top", "rising", "controversial"} else "hot"
        params = {"limit": str(limit), "raw_json": "1"}
        if after:
            params["after"] = after
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}/r/{urllib.parse.quote(sub)}/{sort}{suffix}?{urllib.parse.urlencode(params)}"
        data = _request(url, token=self._token())
        children = data.get("data", {}).get("children", [])
        return [Post.from_json(c) for c in children if c.get("kind") == "t3"]

    def get_frontpage(self, sort: str = "hot", limit: int = 25) -> List[Post]:
        return self.get_subreddit_posts("popular", sort=sort, limit=limit)

    def get_post_with_comments(self, permalink: str) -> tuple[Post, List[Comment]]:
        link = permalink if permalink.startswith("/") else f"/{permalink}"
        if link.endswith("/"):
            link = link[:-1]
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}{link}{suffix}?raw_json=1&limit=200"
        data = _request(url, token=self._token())
        if not isinstance(data, list) or len(data) < 2:
            raise RedditError("Unexpected response shape for post")
        post_listing = data[0].get("data", {}).get("children", [])
        if not post_listing:
            raise RedditError("Post not found")
        post = Post.from_json(post_listing[0])
        comments: List[Comment] = []
        for child in data[1].get("data", {}).get("children", []):
            c = Comment.from_json(child, depth=0)
            if c is not None:
                comments.append(c)
        return post, comments

    def search_subreddits(self, query: str, limit: int = 25) -> List[dict]:
        params = {"q": query, "limit": str(limit), "raw_json": "1"}
        suffix = ".json" if not self.authenticated else ""
        url = f"{self._base()}/subreddits/search{suffix}?{urllib.parse.urlencode(params)}"
        data = _request(url, token=self._token())
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
        token = self._require_auth()
        names: List[str] = []
        after: Optional[str] = None
        # Paginate up to ~500 subscriptions
        for _ in range(5):
            params = {"limit": "100", "raw_json": "1"}
            if after:
                params["after"] = after
            url = f"{OAUTH_BASE_URL}/subreddits/mine/subscriber?{urllib.parse.urlencode(params)}"
            data = _request(url, token=token)
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
        token = self._require_auth()
        if direction not in (-1, 0, 1):
            raise RedditError(f"Invalid vote direction: {direction}")
        body = urllib.parse.urlencode({"id": fullname, "dir": str(direction)}).encode("utf-8")
        _request(f"{OAUTH_BASE_URL}/api/vote", token=token, method="POST", data=body)

    def save(self, fullname: str) -> None:
        token = self._require_auth()
        body = urllib.parse.urlencode({"id": fullname}).encode("utf-8")
        _request(f"{OAUTH_BASE_URL}/api/save", token=token, method="POST", data=body)

    def unsave(self, fullname: str) -> None:
        token = self._require_auth()
        body = urllib.parse.urlencode({"id": fullname}).encode("utf-8")
        _request(f"{OAUTH_BASE_URL}/api/unsave", token=token, method="POST", data=body)

    def submit_comment(self, parent_fullname: str, text: str) -> None:
        token = self._require_auth()
        body = urllib.parse.urlencode(
            {"thing_id": parent_fullname, "text": text, "api_type": "json"}
        ).encode("utf-8")
        resp = _request(
            f"{OAUTH_BASE_URL}/api/comment", token=token, method="POST", data=body
        )
        # Reddit returns errors inside json.errors
        errs = resp.get("json", {}).get("errors", [])
        if errs:
            raise RedditError(f"Comment failed: {errs[0]}")

    def get_inbox(self, only_unread: bool = False) -> List[InboxItem]:
        token = self._require_auth()
        endpoint = "unread" if only_unread else "inbox"
        url = f"{OAUTH_BASE_URL}/message/{endpoint}?raw_json=1&limit=50"
        data = _request(url, token=token)
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
            return len(self.get_inbox(only_unread=True))
        except RedditError:
            return 0

    def mark_read(self, fullname: str) -> None:
        token = self._require_auth()
        body = urllib.parse.urlencode({"id": fullname}).encode("utf-8")
        _request(
            f"{OAUTH_BASE_URL}/api/read_message", token=token, method="POST", data=body
        )
