"""Subreddit posts listing screen."""
from __future__ import annotations

from typing import List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, ListItem, ListView, Static

from reddit_tui.reddit_client import Post, RedditClient, RedditError, clean_sub
from reddit_tui.utils import escape_markup, format_age, format_score

DEFAULT_SUBS = [
    "popular",
    "all",
    "news",
    "worldnews",
    "technology",
    "programming",
    "python",
    "rust",
    "linux",
    "askreddit",
    "todayilearned",
    "science",
    "space",
    "movies",
    "games",
    "pics",
    "funny",
]


class SubredditScreen(Screen):
    """Display posts in a subreddit."""

    BINDINGS = [
        Binding("q", "app.quit", "Quit"),
        Binding("escape", "focus_table", "Focus list"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("g", "goto_subreddit", "Go"),
        Binding("/", "search", "Search"),
        Binding("tab", "toggle_sidebar_focus", "Sidebar"),
        Binding("enter", "open_post", "Open"),
        Binding("u", "upvote", "Upvote"),
        Binding("d", "downvote", "Downvote"),
        Binding("S", "toggle_save", "Save"),
        Binding("i", "open_inbox", "Inbox"),
    ]

    SORTS = ["hot", "new", "top", "rising"]
    SORT_ICONS = {"hot": "🔥", "new": "✨", "top": "⭐", "rising": "📈"}

    def __init__(self, client: RedditClient, subreddit: str = "popular") -> None:
        super().__init__()
        self.client = client
        self.subreddit = subreddit
        self.sort = "hot"
        self.posts: List[Post] = []
        self.subscribed: List[str] = []
        self.unread_count: int = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="sub-layout"):
            with Vertical(id="sidebar"):
                yield Static("● SUBREDDITS", id="sidebar-title")
                yield ListView(
                    *self._build_sidebar_items(DEFAULT_SUBS),
                    id="sidebar-list",
                )
                yield Static(self._sidebar_hint(), id="sidebar-hint")
            with Vertical(id="main-pane"):
                yield Static(self._title(), id="sub-title")
                table = DataTable(id="posts-table", cursor_type="row", zebra_stripes=True)
                table.add_columns("  #", "  ▲ ", "Title", "Author", "💬", "⏱")
                yield table
                yield Static("", id="status-bar")
        yield Footer()

    def _sidebar_hint(self) -> str:
        if self.client.authenticated:
            return "[dim]g: go to sub\n/: search\ntab: focus list\ni: inbox[/]"
        return "[dim]g: go to sub\n/: search\ntab: focus list[/]"

    def _build_sidebar_items(self, subs: List[str]) -> List[ListItem]:
        return [ListItem(Label(f"r/{s}"), name=s) for s in subs]

    def _title(self) -> str:
        icon = self.SORT_ICONS.get(self.sort, "•")
        user_part = ""
        if self.client.authenticated and self.client.username:
            inbox_part = ""
            if self.unread_count > 0:
                inbox_part = f"   [#6c7080]│[/]   [#ff5555 bold]✉ {self.unread_count}[/]"
            user_part = (
                f"   [#6c7080]│[/]   [#50fa7b]u/{escape_markup(self.client.username)}[/]"
                f"{inbox_part}"
            )
        return (
            f"  [#ff4500 bold]r/{escape_markup(self.subreddit)}[/]"
            f"   [#6c7080]│[/]   {icon} [yellow]{self.sort}[/]"
            f"   [#6c7080]│[/]   [#8a90a3]{len(self.posts)} posts[/]"
            f"{user_part}"
        )

    def on_mount(self) -> None:
        self._highlight_sidebar()
        self.query_one("#posts-table", DataTable).focus()
        self.load_posts()
        if self.client.authenticated:
            self.run_worker(self._load_subscriptions(), exclusive=True, group="subs")
            self.run_worker(self._load_unread(), exclusive=True, group="inbox")
        if getattr(self.app, "auth_status", ""):
            self._set_status(f"[#ff5555]✗ {escape_markup(self.app.auth_status)}[/]")

    def _highlight_sidebar(self) -> None:
        try:
            lv = self.query_one("#sidebar-list", ListView)
        except Exception:
            return
        for i, item in enumerate(lv.children):
            if getattr(item, "name", None) == self.subreddit:
                lv.index = i
                break

    async def _load_subscriptions(self) -> None:
        try:
            subs = await self.client.get_subscribed_subreddits()
        except RedditError:
            return
        if subs:
            self._populate_sidebar(subs)

    def _populate_sidebar(self, subs: List[str]) -> None:
        self.subscribed = subs
        seen = {s.lower() for s in subs}
        combined = subs + [s for s in DEFAULT_SUBS if s.lower() not in seen]
        try:
            lv = self.query_one("#sidebar-list", ListView)
        except Exception:
            return
        lv.clear()
        for item in self._build_sidebar_items(combined):
            lv.append(item)
        self.query_one("#sidebar-title", Static).update(
            f"● SUBREDDITS [#8a90a3]({len(subs)} subs)[/]"
        )
        self._highlight_sidebar()

    async def _load_unread(self) -> None:
        try:
            n = await self.client.get_unread_count()
        except RedditError:
            return
        self._set_unread(n)

    def _set_unread(self, n: int) -> None:
        self.unread_count = n
        self.query_one("#sub-title", Static).update(self._title())

    def action_focus_table(self) -> None:
        self.query_one("#posts-table", DataTable).focus()

    def action_toggle_sidebar_focus(self) -> None:
        if self.focused and self.focused.id == "sidebar-list":
            self.query_one("#posts-table", DataTable).focus()
        else:
            self.query_one("#sidebar-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = getattr(event.item, "name", None)
        if name:
            self._switch_subreddit(name)
            self.action_focus_table()

    def action_refresh(self) -> None:
        self.load_posts()
        if self.client.authenticated:
            self.run_worker(self._load_unread(), exclusive=True, group="inbox")

    def action_cycle_sort(self) -> None:
        idx = self.SORTS.index(self.sort) if self.sort in self.SORTS else 0
        self.sort = self.SORTS[(idx + 1) % len(self.SORTS)]
        self.query_one("#sub-title", Static).update(self._title())
        self.load_posts()

    def action_goto_subreddit(self) -> None:
        from reddit_tui.screens.input_dialog import InputDialog

        def _cb(value: str | None) -> None:
            if value:
                self._switch_subreddit(clean_sub(value))

        self.app.push_screen(InputDialog("Go to subreddit (without r/):"), _cb)

    def action_search(self) -> None:
        from reddit_tui.screens.input_dialog import InputDialog

        def _cb(value: str | None) -> None:
            if value:
                self.run_worker(self._do_search(value.strip()), exclusive=True)

        self.app.push_screen(InputDialog("Search subreddits:"), _cb)

    def action_open_inbox(self) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required for inbox[/]")
            return
        from reddit_tui.screens.inbox_screen import InboxScreen
        self.app.push_screen(InboxScreen(self.client))

    async def _do_search(self, query: str) -> None:
        try:
            results = await self.client.search_subreddits(query, limit=25)
        except RedditError as e:
            self._set_status(f"[#ff5555]✗ {escape_markup(str(e))}[/]")
            return
        if not results:
            self._set_status("[yellow]⚠ no subreddits found[/]")
            return
        first = results[0].get("display_name", query)
        self._set_status(
            f"[#50fa7b]✓ found {len(results)} subs · opening r/{escape_markup(first)}[/]"
        )
        self._switch_subreddit(first)

    def _switch_subreddit(self, name: str) -> None:
        self.subreddit = name
        self.query_one("#sub-title", Static).update(self._title())
        self._highlight_sidebar()
        self.load_posts()

    def action_open_post(self) -> None:
        table = self.query_one("#posts-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return
        row = table.cursor_row
        if 0 <= row < len(self.posts):
            from reddit_tui.screens.post_screen import PostScreen
            self.app.push_screen(PostScreen(self.client, self.posts[row]))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open_post()

    def _current_post(self) -> Optional[Post]:
        table = self.query_one("#posts-table", DataTable)
        row = table.cursor_row
        if row is None or not (0 <= row < len(self.posts)):
            return None
        return self.posts[row]

    def action_upvote(self) -> None:
        self._vote_current(1)

    def action_downvote(self) -> None:
        self._vote_current(-1)

    def _vote_current(self, direction: int) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required to vote[/]")
            return
        post = self._current_post()
        if post is None:
            return
        if (direction == 1 and post.likes is True) or (direction == -1 and post.likes is False):
            new_dir = 0
        else:
            new_dir = direction
        old_likes = post.likes
        old_score = post.score
        if new_dir == 1:
            post.score += 1 if old_likes is None else (2 if old_likes is False else 0)
            post.likes = True
        elif new_dir == -1:
            post.score += -1 if old_likes is None else (-2 if old_likes is True else 0)
            post.likes = False
        else:
            post.score += -1 if old_likes is True else (1 if old_likes is False else 0)
            post.likes = None
        self._refresh_row(post)
        self.run_worker(
            self._send_vote(post.name, new_dir, old_likes, old_score), group="vote"
        )

    async def _send_vote(
        self, fullname: str, direction: int, old_likes, old_score: int
    ) -> None:
        try:
            await self.client.vote(fullname, direction)
        except RedditError as e:
            self._revert_vote(fullname, old_likes, old_score, str(e))
            return
        label = {1: "upvoted", -1: "downvoted", 0: "vote cleared"}.get(direction, "voted")
        self._set_status(f"[#50fa7b]✓ {label}[/]")

    def _revert_vote(self, fullname: str, old_likes, old_score: int, err: str) -> None:
        for p in self.posts:
            if p.name == fullname:
                p.likes = old_likes
                p.score = old_score
                self._refresh_row(p)
                break
        self._set_status(f"[#ff5555]✗ vote failed: {escape_markup(err)}[/]")

    def action_toggle_save(self) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required to save[/]")
            return
        post = self._current_post()
        if post is None:
            return
        target = not post.saved
        post.saved = target
        self._refresh_row(post)
        self.run_worker(self._send_save(post.name, target), group="save")

    async def _send_save(self, fullname: str, save: bool) -> None:
        try:
            if save:
                await self.client.save(fullname)
            else:
                await self.client.unsave(fullname)
        except RedditError as e:
            self._revert_save(fullname, not save, str(e))
            return
        self._set_status(f"[#50fa7b]✓ {'saved' if save else 'unsaved'}[/]")

    def _revert_save(self, fullname: str, original: bool, err: str) -> None:
        for p in self.posts:
            if p.name == fullname:
                p.saved = original
                self._refresh_row(p)
                break
        self._set_status(f"[#ff5555]✗ save failed: {escape_markup(err)}[/]")

    def _set_status(self, msg: str) -> None:
        self.query_one("#status-bar", Static).update(msg)

    def load_posts(self) -> None:
        self._set_status("[#ff4500]◌ loading…[/]")
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        try:
            posts = await self.client.get_subreddit_posts(
                self.subreddit, sort=self.sort, limit=50
            )
        except RedditError as e:
            self._set_status(f"[#ff5555]✗ {escape_markup(str(e))}[/]")
            return
        self._populate(posts)

    def _score_color(self, score: int) -> str:
        if score >= 10000:
            return "#ff4500"
        if score >= 1000:
            return "#ffb86c"
        if score >= 100:
            return "#50fa7b"
        return "#8a90a3"

    def _format_row(self, i: int, p: Post) -> tuple:
        tags = ""
        if p.over_18:
            tags += " [#ff5555 bold]NSFW[/]"
        if p.is_self:
            tags += " [#bd93f9]TEXT[/]"
        elif p.domain and not p.domain.startswith("self."):
            tags += f" [#6272a4]{escape_markup(p.domain)}[/]"
        if p.saved:
            tags += " [#f1fa8c bold]★ SAVED[/]"

        title = p.title.replace("\n", " ")
        if len(title) > 90:
            title = title[:87] + "…"

        if p.likes is True:
            arrow = "[#ff4500 bold]▲[/]"
        elif p.likes is False:
            arrow = "[#8be9fd bold]▼[/]"
        else:
            arrow = " "
        score_color = self._score_color(p.score)
        comment_color = "#8be9fd" if p.num_comments > 100 else "#6c7080"
        return (
            f"[#6c7080]{i:>3}[/]",
            f"{arrow}[{score_color} bold]{format_score(p.score):>5}[/]",
            f"[#e8eaf0]{escape_markup(title)}[/]{tags}",
            f"[#f1fa8c]u/{escape_markup(p.author)}[/]",
            f"[{comment_color}]{format_score(p.num_comments):>4}[/]",
            f"[#8a90a3]{format_age(p.created_utc):>4}[/]",
        )

    def _refresh_row(self, post: Post) -> None:
        try:
            idx = self.posts.index(post)
        except ValueError:
            return
        table = self.query_one("#posts-table", DataTable)
        if idx >= table.row_count:
            return
        row_data = self._format_row(idx + 1, post)
        try:
            row_key = list(table.rows)[idx]
        except (IndexError, AttributeError):
            return
        try:
            for col_idx, (col_key, value) in enumerate(zip(table.columns, row_data)):
                table.update_cell(row_key, col_key, value)
        except Exception:
            self._populate(self.posts)

    def _populate(self, posts: List[Post]) -> None:
        self.posts = posts
        table = self.query_one("#posts-table", DataTable)
        table.clear()
        for i, p in enumerate(posts, start=1):
            table.add_row(*self._format_row(i, p))
        self.query_one("#sub-title", Static).update(self._title())
        auth_keys = ""
        if self.client.authenticated:
            auth_keys = "  [#c5c8d3]u[/] up  [#c5c8d3]d[/] down  [#c5c8d3]S[/] save  [#c5c8d3]i[/] inbox"
        self._set_status(
            f"[#50fa7b]✓ loaded {len(posts)} posts[/]   "
            "[#6c7080]│[/]   [#c5c8d3]enter[/] open  "
            "[#c5c8d3]s[/] sort  [#c5c8d3]g[/] go  "
            "[#c5c8d3]/[/] search  [#c5c8d3]r[/] refresh  "
            f"[#c5c8d3]tab[/] sidebar  [#c5c8d3]q[/] quit{auth_keys}"
        )
