"""Live smoke test that mirrors what the TUI does on startup + opening a post.

Runs with no auth, like a fresh-clone user. Exits non-zero on first failure
so it's usable from CI / Docker to reproduce the "works on my machine but
403s on a fresh box" class of bug.
"""
from __future__ import annotations

import asyncio
import sys

from reddit_tui.reddit_client import DEFAULT_USER_AGENT, RedditClient


async def main() -> int:
    print(f"User-Agent: {DEFAULT_USER_AGENT}")
    async with RedditClient() as client:
        print("[1/2] Fetching r/python hot listing ...")
        posts = await client.get_subreddit_posts("python", sort="hot", limit=5)
        if not posts:
            print("FAIL: empty listing", file=sys.stderr)
            return 1
        print(f"  ok, {len(posts)} posts; first: {posts[0].title!r}")

        print("[2/2] Fetching post + comments (this is what 403s on fresh boxes) ...")
        post, items = await client.get_post_with_comments(posts[0].permalink)
        print(f"  ok, post={post.title!r}, top-level items={len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
