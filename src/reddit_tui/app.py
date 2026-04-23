"""Main Textual application."""
from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from reddit_tui import auth as auth_mod
from reddit_tui.reddit_client import RedditClient
from reddit_tui.screens.subreddit_screen import SubredditScreen


class RedditTUI(App):
    """Terminal-based Reddit browser."""

    TITLE = "reddit-tui"
    SUB_TITLE = "browse reddit from your terminal"

    CSS_PATH = ["styles/app.tcss", "styles/inbox.tcss", "styles/reply.tcss"]

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.auth_status: str = ""
        self.auth_config = None
        try:
            self.auth_config = auth_mod.load_config()
        except auth_mod.AuthError as e:
            self.auth_status = f"auth config error: {e}"

        if self.auth_config is not None:
            cfg = self.auth_config

            async def _provider() -> str:
                return (await auth_mod.get_valid_token(cfg)).access_token

            self.client = RedditClient(
                token_provider=_provider,
                username=cfg.username,
                user_agent=cfg.user_agent,
            )
            self.SUB_TITLE = f"u/{cfg.username} (signing in…)"
        else:
            self.client = RedditClient()

    async def on_mount(self) -> None:
        await self.push_screen(SubredditScreen(self.client, subreddit="popular"))
        if self.auth_config is not None:
            self.run_worker(self._verify_login(), exclusive=True, group="auth")

    async def _verify_login(self) -> None:
        cfg = self.auth_config
        if cfg is None:
            return
        try:
            await auth_mod.get_valid_token(cfg)
        except auth_mod.AuthError as e:
            self.SUB_TITLE = "logged out (auth failed)"
            self.auth_status = f"login failed: {e}"
            # Replace with anonymous client; close old one.
            old = self.client
            self.client = RedditClient(user_agent=old.user_agent)
            await old.aclose()
            return
        self.SUB_TITLE = f"logged in as u/{cfg.username}"
        self.auth_status = ""

    async def on_unmount(self) -> None:
        await self.client.aclose()
