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

    CSS = """
    /* ---------- global ---------- */
    Screen {
        background: #0f1117;
    }

    Header {
        background: #ff4500;
        color: #ffffff;
        text-style: bold;
    }

    Footer {
        background: #1a1d27;
        color: #c5c8d3;
    }
    Footer > .footer--key {
        background: #ff4500;
        color: #ffffff;
        text-style: bold;
    }
    Footer > .footer--description {
        color: #c5c8d3;
    }

    /* ---------- subreddit screen ---------- */
    #sub-layout {
        height: 1fr;
    }

    #sidebar {
        width: 24;
        background: #161922;
        border-right: vkey #2a2f3d;
        padding: 1 1;
    }
    #sidebar-title {
        color: #ff4500;
        text-style: bold;
        padding: 0 1 1 1;
    }
    #sidebar ListView {
        background: #161922;
        height: auto;
    }
    #sidebar ListItem {
        padding: 0 1;
        color: #c5c8d3;
    }
    #sidebar ListItem.--highlight {
        background: #ff4500 30%;
        color: #ffffff;
        text-style: bold;
    }
    #sidebar-hint {
        color: #6c7080;
        padding: 1 1 0 1;
    }

    #main-pane {
        width: 1fr;
        height: 1fr;
    }

    #sub-title {
        background: #1a1d27;
        color: #e8eaf0;
        padding: 1 2;
        border-bottom: hkey #2a2f3d;
    }

    DataTable {
        height: 1fr;
        background: #0f1117;
        color: #e8eaf0;
    }
    DataTable > .datatable--header {
        background: #1a1d27;
        color: #ff4500;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #ff4500 40%;
        color: #ffffff;
        text-style: bold;
    }
    DataTable > .datatable--hover {
        background: #2a2f3d;
    }
    DataTable > .datatable--odd-row {
        background: #131620;
    }
    DataTable > .datatable--even-row {
        background: #0f1117;
    }

    #status-bar {
        background: #1a1d27;
        color: #8a90a3;
        padding: 0 2;
        border-top: hkey #2a2f3d;
        height: 1;
    }

    /* ---------- post screen ---------- */
    #post-scroll {
        padding: 1 3;
        background: #0f1117;
    }
    #post-card {
        background: #161922;
        border: round #ff4500;
        padding: 1 2;
        margin-bottom: 1;
    }
    #post-title {
        color: #ffffff;
        text-style: bold;
    }
    #post-meta {
        color: #8a90a3;
        padding-top: 1;
    }
    #post-body {
        background: #131620;
        border-left: thick #ff4500;
        padding: 1 2;
        margin-bottom: 1;
        color: #d8dbe5;
    }
    #comments-title {
        color: #ff4500;
        text-style: bold;
        padding: 1 0 1 0;
    }
    #comments-body {
        color: #d8dbe5;
    }

    /* ---------- modal input ---------- */
    InputDialog {
        align: center middle;
    }
    InputDialog > #dialog-box {
        width: 70;
        height: auto;
        background: #161922;
        border: round #ff4500;
        padding: 1 2;
    }
    InputDialog #dialog-prompt {
        color: #ff4500;
        text-style: bold;
        padding-bottom: 1;
    }
    InputDialog Input {
        background: #0f1117;
        color: #e8eaf0;
        border: tall #2a2f3d;
    }
    InputDialog Input:focus {
        border: tall #ff4500;
    }
    InputDialog #dialog-hint {
        color: #6c7080;
        padding-top: 1;
    }

    ReplyDialog {
        align: center middle;
    }
    ReplyDialog > #reply-box {
        width: 90;
        height: 24;
        background: #161922;
        border: round #ff4500;
        padding: 1 2;
    }
    ReplyDialog #reply-prompt {
        color: #ff4500;
        text-style: bold;
        padding-bottom: 1;
    }
    ReplyDialog TextArea {
        background: #0f1117;
        color: #e8eaf0;
        border: tall #2a2f3d;
        height: 1fr;
    }
    ReplyDialog TextArea:focus {
        border: tall #ff4500;
    }
    ReplyDialog #reply-hint {
        color: #6c7080;
        padding-top: 1;
    }
    """

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
