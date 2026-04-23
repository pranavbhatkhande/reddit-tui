"""Inbox screen — read replies and PMs."""
from __future__ import annotations

from typing import List

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from reddit_tui.reddit_client import InboxItem, RedditClient, RedditError
from reddit_tui.utils import escape_markup, format_age


def _wrap(text: str, width: int = 100) -> List[str]:
    out: List[str] = []
    for raw in text.splitlines() or [""]:
        line = raw
        if not line:
            out.append("")
            continue
        while len(line) > width:
            cut = line.rfind(" ", 0, width)
            if cut <= 0:
                cut = width
            out.append(line[:cut])
            line = line[cut:].lstrip()
        out.append(line)
    return out


class InboxItemWidget(Static):
    def __init__(self, item: InboxItem) -> None:
        self.item = item
        super().__init__(self._build())
        if item.new:
            self.add_class("-unread")

    def _build(self) -> str:
        it = self.item
        kind_label = (
            "[#bd93f9]COMMENT REPLY[/]" if it.kind == "t1" else "[#8be9fd]MESSAGE[/]"
        )
        unread = " [#ff4500 bold]●UNREAD[/]" if it.new else ""
        sub = f"  [#6c7080]·[/]  [#ff4500]r/{escape_markup(it.subreddit)}[/]" if it.subreddit else ""
        header = (
            f"{kind_label}{unread}  "
            f"[#f1fa8c]u/{escape_markup(it.author)}[/]{sub}  "
            f"[#6c7080]· {format_age(it.created_utc)} ago[/]"
        )
        subj = f"[bold #e8eaf0]{escape_markup(it.subject)}[/]" if it.subject else ""
        body = "\n".join(_wrap(escape_markup(it.body), width=100))
        parts = [header]
        if subj:
            parts.append(subj)
        parts.append(body)
        return "\n".join(parts)

    def refresh_render(self) -> None:
        self.update(self._build())


class InboxScreen(Screen):
    BINDINGS = [
        Binding("q", "app.pop_screen", "Back"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("j", "next_item", "Next"),
        Binding("k", "prev_item", "Prev"),
        Binding("enter", "open_item", "Open"),
        Binding("m", "mark_read", "Mark read"),
    ]

    DEFAULT_CSS = ""

    def __init__(self, client: RedditClient) -> None:
        super().__init__()
        self.client = client
        self.items: List[InboxItem] = []
        self._widgets: List[InboxItemWidget] = []
        self._focused_idx: int = -1

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("  [#ff4500 bold]✉ INBOX[/]", id="inbox-title")
        yield VerticalScroll(id="inbox-scroll")
        yield Static(
            "  [#c5c8d3]j/k[/] navigate  [#c5c8d3]enter[/] open  "
            "[#c5c8d3]m[/] mark read  [#c5c8d3]r[/] refresh  [#c5c8d3]q[/] back",
            id="inbox-status",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._fetch()

    def action_refresh(self) -> None:
        self._fetch()

    def _fetch(self) -> None:
        self.run_worker(self._do_fetch(), exclusive=True)

    async def _do_fetch(self) -> None:
        try:
            items = await self.client.get_inbox(only_unread=False)
        except RedditError as e:
            self._set_status(f"[#ff5555]✗ {escape_markup(str(e))}[/]")
            return
        self._populate(items)

    def _set_status(self, msg: str) -> None:
        self.query_one("#inbox-status", Static).update(msg)

    def _populate(self, items: List[InboxItem]) -> None:
        self.items = items
        scroll = self.query_one("#inbox-scroll", VerticalScroll)
        for w in list(scroll.query(InboxItemWidget)):
            w.remove()
        self._widgets = []
        if not items:
            scroll.mount(Static("[#6c7080 italic](inbox empty)[/]"))
            return
        for it in items:
            w = InboxItemWidget(it)
            self._widgets.append(w)
            scroll.mount(w)
        unread = sum(1 for it in items if it.new)
        self.query_one("#inbox-title", Static).update(
            f"  [#ff4500 bold]✉ INBOX[/]  [#8a90a3]({len(items)} items, {unread} unread)[/]"
        )
        self._focused_idx = 0 if items else -1
        if self._focused_idx >= 0:
            self._widgets[0].add_class("-focused")

    def _set_focus(self, new_idx: int) -> None:
        if not self._widgets:
            return
        new_idx = max(0, min(len(self._widgets) - 1, new_idx))
        if new_idx == self._focused_idx:
            return
        if 0 <= self._focused_idx < len(self._widgets):
            self._widgets[self._focused_idx].remove_class("-focused")
        self._focused_idx = new_idx
        self._widgets[new_idx].add_class("-focused")
        self._widgets[new_idx].scroll_visible()

    def action_next_item(self) -> None:
        self._set_focus(self._focused_idx + 1)

    def action_prev_item(self) -> None:
        self._set_focus(self._focused_idx - 1)

    def action_open_item(self) -> None:
        if not (0 <= self._focused_idx < len(self.items)):
            return
        it = self.items[self._focused_idx]
        if it.kind == "t1" and it.context:
            # Open the thread in PostScreen
            from reddit_tui.screens.post_screen import PostScreen
            from reddit_tui.reddit_client import Post
            # Build a stub Post; PostScreen's _fetch_comments will fill in details
            stub = Post(
                id="",
                name="",
                title=it.subject or "(reply)",
                author=it.author,
                subreddit=it.subreddit,
                score=0,
                num_comments=0,
                permalink=it.context,
                url="",
                selftext="",
                created_utc=it.created_utc,
                is_self=True,
                domain="",
                over_18=False,
            )
            self.app.push_screen(PostScreen(self.client, stub))
        else:
            self._set_status("[yellow]⚠ direct messages: view-only here[/]")

    def action_mark_read(self) -> None:
        if not (0 <= self._focused_idx < len(self.items)):
            return
        it = self.items[self._focused_idx]
        if not it.new:
            return
        self._send_mark_read(it.name, self._focused_idx)

    def _send_mark_read(self, fullname: str, idx: int) -> None:
        self.run_worker(self._do_mark_read(fullname, idx), group="markread")

    async def _do_mark_read(self, fullname: str, idx: int) -> None:
        try:
            await self.client.mark_read(fullname)
        except RedditError as e:
            self._set_status(f"[#ff5555]✗ {escape_markup(str(e))}[/]")
            return
        self._on_marked(idx)

    def _on_marked(self, idx: int) -> None:
        if 0 <= idx < len(self.items):
            self.items[idx].new = False
            self._widgets[idx].remove_class("-unread")
            self._widgets[idx].item = self.items[idx]
            self._widgets[idx].refresh_render()
        self._set_status("[#50fa7b]✓ marked as read[/]")
