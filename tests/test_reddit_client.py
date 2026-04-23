"""Tests for reddit_client parsing and clean_sub helper."""
from __future__ import annotations

from reddit_tui.reddit_client import (
    Comment,
    InboxItem,
    MoreComments,
    Post,
    clean_sub,
)


class TestCleanSub:
    def test_plain(self) -> None:
        assert clean_sub("python") == "python"

    def test_with_prefix(self) -> None:
        assert clean_sub("r/python") == "python"

    def test_with_slash_prefix(self) -> None:
        assert clean_sub("/r/python") == "python"

    def test_trailing_slash(self) -> None:
        assert clean_sub("r/python/") == "python"

    def test_whitespace(self) -> None:
        assert clean_sub("  python  ") == "python"

    def test_empty_returns_all(self) -> None:
        assert clean_sub("") == "all"
        assert clean_sub("   ") == "all"
        assert clean_sub(None) == "all"  # type: ignore[arg-type]

    def test_uppercase_prefix(self) -> None:
        assert clean_sub("R/Python") == "Python"


class TestPostFromJson:
    def test_minimal(self) -> None:
        p = Post.from_json({"data": {"id": "abc", "title": " hi "}})
        assert p.id == "abc"
        assert p.title == "hi"
        assert p.author == "[deleted]"
        assert p.score == 0

    def test_full(self) -> None:
        p = Post.from_json({
            "data": {
                "id": "x", "name": "t3_x", "title": "T", "author": "u",
                "subreddit": "s", "score": 42, "num_comments": 7,
                "permalink": "/r/s/x", "url": "https://e", "selftext": "body",
                "created_utc": 100, "is_self": True, "domain": "self.s",
                "over_18": False, "likes": True, "saved": True,
            }
        })
        assert p.score == 42
        assert p.likes is True
        assert p.saved is True
        assert p.is_self is True


class TestCommentFromJson:
    def test_wrong_kind(self) -> None:
        assert Comment.from_json({"kind": "more", "data": {}}) is None

    def test_basic(self) -> None:
        c = Comment.from_json({
            "kind": "t1",
            "data": {
                "id": "a", "name": "t1_a", "author": "u",
                "body": "hello", "score": 5, "created_utc": 1,
            },
        })
        assert c is not None
        assert c.body == "hello"
        assert c.depth == 0

    def test_nested_replies(self) -> None:
        c = Comment.from_json({
            "kind": "t1",
            "data": {
                "id": "a", "body": "p", "score": 1,
                "replies": {
                    "data": {
                        "children": [
                            {"kind": "t1", "data": {"id": "b", "body": "child"}},
                            {"kind": "more", "data": {"count": 3, "children": ["c1"]}},
                        ]
                    }
                },
            },
        })
        assert c is not None
        assert len(c.replies) == 2
        assert isinstance(c.replies[0], Comment)
        assert c.replies[0].depth == 1
        assert isinstance(c.replies[1], MoreComments)
        assert c.replies[1].count == 3


class TestMoreCommentsFromJson:
    def test_wrong_kind(self) -> None:
        assert MoreComments.from_json({"kind": "t1", "data": {}}) is None

    def test_basic(self) -> None:
        m = MoreComments.from_json({
            "kind": "more",
            "data": {"id": "x", "name": "t1_x", "parent_id": "t1_p",
                     "count": 12, "children": ["a", "b", "c"]},
        }, depth=2)
        assert m is not None
        assert m.count == 12
        assert m.depth == 2
        assert m.children == ["a", "b", "c"]


class TestInboxItemFromJson:
    def test_wrong_kind(self) -> None:
        assert InboxItem.from_json({"kind": "t3", "data": {}}) is None

    def test_comment_reply(self) -> None:
        it = InboxItem.from_json({
            "kind": "t1",
            "data": {"id": "a", "name": "t1_a", "author": "u",
                     "subject": "", "link_title": "Re: post",
                     "body": "hi", "context": "/r/s/x",
                     "created_utc": 5, "new": True, "subreddit": "s"},
        })
        assert it is not None
        assert it.kind == "t1"
        assert it.subject == "Re: post"  # falls back to link_title
        assert it.new is True

    def test_pm(self) -> None:
        it = InboxItem.from_json({
            "kind": "t4",
            "data": {"id": "p", "name": "t4_p", "author": "x",
                     "subject": "hello", "body": "msg", "new": False},
        })
        assert it is not None
        assert it.kind == "t4"
        assert it.subject == "hello"
        assert it.new is False
