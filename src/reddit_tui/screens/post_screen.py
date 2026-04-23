"""Post detail screen with comments.

Comments are rendered into a single ``Static`` widget using a Rich ``Group``
of styled text blocks. This keeps Textual's layout work O(1) instead of
mounting one widget per comment, which proved expensive on threads with
hundreds of comments. j/k navigation tracks the focused index in screen
state; on each move we rebuild the Group (cheap) and update the Static.
"""
from __future__ import annotations

from collections.abc import Sequence

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from reddit_tui.reddit_client import (
    Comment,
    MoreComments,
    Post,
    RedditClient,
    RedditError,
)
from reddit_tui.utils import escape_markup, format_age, format_score

# Rotating colors for comment depth guides (Reddit-ish palette)
DEPTH_COLORS = [
    "#ff4500",  # orange (OP-level)
    "#50fa7b",  # green
    "#8be9fd",  # cyan
    "#bd93f9",  # purple
    "#f1fa8c",  # yellow
    "#ff79c6",  # pink
]


def _wrap_text(text: str, width: int = 100) -> list[str]:
    out: list[str] = []
    for raw_line in text.splitlines() or [""]:
        line = raw_line
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


def _indent_with_guides(lines: list[str], depth: int) -> list[str]:
    if depth == 0:
        return lines
    bars = ""
    for d in range(depth):
        color = DEPTH_COLORS[d % len(DEPTH_COLORS)]
        bars += f"[{color}]│[/] "
    return [bars + ln for ln in lines]


def _score_color(score: int) -> str:
    if score >= 1000:
        return "#ff4500"
    if score >= 100:
        return "#ffb86c"
    if score >= 10:
        return "#50fa7b"
    if score < 0:
        return "#ff5555"
    return "#8a90a3"


def _flatten(items: Sequence[object]) -> list[object]:
    """Flatten the comment tree in display order (Comment | MoreComments)."""
    out: list[object] = []

    def walk(seq: Sequence[object]) -> None:
        for it in seq:
            out.append(it)
            if isinstance(it, Comment):
                walk(it.replies)

    walk(items)
    return out


class PostScreen(Screen):
    BINDINGS = [
        Binding("q", "app.pop_screen", "Back"),
        Binding("escape", "app.pop_screen", "Back"),
        Binding("o", "open_url", "Open URL"),
        Binding("r", "refresh", "Reload"),
        Binding("j", "next_comment", "Next"),
        Binding("k", "prev_comment", "Prev"),
        Binding("u", "upvote", "Upvote"),
        Binding("d", "downvote", "Downvote"),
        Binding("S", "toggle_save", "Save"),
        Binding("c", "reply_post", "Reply post"),
        Binding("R", "reply_comment", "Reply cmt"),
        Binding("M", "load_more", "Load more"),
    ]

    def __init__(self, client: RedditClient, post: Post) -> None:
        super().__init__()
        self.client = client
        self.post = post
        self.top_items: list[object] = []  # tree (Comment | MoreComments)
        self._flat: list[object] = []  # flattened display order
        self._focused_idx: int = -1  # -1 means post focused

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="post-scroll"):
            yield Static(self._post_card(), id="post-card")
            yield Static("", id="post-body")
            yield Static(self._comments_header_loading(), id="comments-title")
            yield Static("[#6c7080]◌ loading comments…[/]", id="comments-body")
        yield Static("", id="status-bar")
        yield Footer()

    def _post_card(self) -> str:
        p = self.post
        score_c = _score_color(p.score)
        nsfw = "  [#ff5555 bold]NSFW[/]" if p.over_18 else ""
        kind = "[#bd93f9]TEXT[/]" if p.is_self else f"[#6272a4]{escape_markup(p.domain)}[/]"
        if p.likes is True:
            arrow = "[#ff4500 bold]▲[/] "
        elif p.likes is False:
            arrow = "[#8be9fd bold]▼[/] "
        else:
            arrow = ""
        saved = "  [#f1fa8c bold]★ SAVED[/]" if p.saved else ""
        focus_marker = "  [#50fa7b bold][POST FOCUSED][/]" if self._focused_idx == -1 else ""
        return (
            f"[bold #ffffff]{escape_markup(p.title)}[/]{nsfw}{saved}{focus_marker}\n"
            f"[#6c7080]──────────────────────────────────────────────[/]\n"
            f"[#ff4500]r/{escape_markup(p.subreddit)}[/]  "
            f"[#6c7080]·[/]  [#f1fa8c]u/{escape_markup(p.author)}[/]  "
            f"[#6c7080]·[/]  {arrow}[{score_c} bold]▲ {format_score(p.score)}[/]  "
            f"[#6c7080]·[/]  [#8be9fd]💬 {format_score(p.num_comments)}[/]  "
            f"[#6c7080]·[/]  [#8a90a3]⏱ {format_age(p.created_utc)} ago[/]  "
            f"[#6c7080]·[/]  {kind}"
        )

    def _comments_header_loading(self) -> str:
        return "[#ff4500 bold]── COMMENTS ─────────────────────────────────────[/]"

    def _refresh_post_card(self) -> None:
        try:
            self.query_one("#post-card", Static).update(self._post_card())
        except Exception:
            pass

    def _comments_header_loaded(self, total: int) -> str:
        return (
            f"[#ff4500 bold]── COMMENTS[/] [#8a90a3]({total} threads)[/] "
            f"[#ff4500 bold]─────────────────────[/]"
        )

    def on_mount(self) -> None:
        body_widget = self.query_one("#post-body", Static)
        if self.post.is_self and self.post.selftext:
            wrapped = "\n".join(_wrap_text(escape_markup(self.post.selftext)))
            body_widget.update(wrapped)
        elif not self.post.is_self:
            safe_url = escape_markup(self.post.url)
            body_widget.update(
                f"[#8be9fd]🔗 {safe_url}[/]\n\n"
                f"[#6c7080]press [#c5c8d3]o[/#c5c8d3] to open in browser[/]"
            )
        else:
            body_widget.update("[#6c7080 italic](no text body)[/]")
        self._update_status_hint()
        self.run_worker(self._fetch_comments(), exclusive=True)

    def _update_status_hint(self) -> None:
        try:
            sb = self.query_one("#status-bar", Static)
        except Exception:
            return
        if self.client.authenticated:
            hint = (
                "  [#c5c8d3]j/k[/] navigate  [#c5c8d3]u/d[/] vote  "
                "[#c5c8d3]S[/] save  [#c5c8d3]c[/] reply post  "
                "[#c5c8d3]R[/] reply cmt  [#c5c8d3]M[/] load more  "
                "[#c5c8d3]o[/] open  [#c5c8d3]q[/] back"
            )
        else:
            hint = (
                "  [#c5c8d3]j/k[/] navigate  [#c5c8d3]o[/] open  "
                "[#c5c8d3]M[/] load more  [#c5c8d3]r[/] reload  [#c5c8d3]q[/] back"
            )
        sb.update(hint)

    def action_refresh(self) -> None:
        self.query_one("#comments-body", Static).update("[#6c7080]◌ reloading…[/]")
        self.run_worker(self._fetch_comments(), exclusive=True)

    def action_open_url(self) -> None:
        import webbrowser
        target = self.post.url or f"https://www.reddit.com{self.post.permalink}"
        try:
            webbrowser.open(target)
        except Exception:
            pass

    async def _fetch_comments(self) -> None:
        try:
            fresh_post, items = await self.client.get_post_with_comments(self.post.permalink)
        except RedditError as e:
            self.query_one("#comments-body", Static).update(
                f"[#ff5555]✗ failed to load comments: {escape_markup(str(e))}[/]"
            )
            return
        self._update_post_meta(fresh_post)
        self._render_tree(items)

    def _update_post_meta(self, fresh: Post) -> None:
        self.post.likes = fresh.likes
        self.post.saved = fresh.saved
        self.post.score = fresh.score
        self.post.num_comments = fresh.num_comments
        if not self.post.name:
            self.post.name = fresh.name
        self._refresh_post_card()

    def _render_tree(self, items: list[object]) -> None:
        self.top_items = items
        self._flat = _flatten(items)
        self.query_one("#comments-title", Static).update(
            self._comments_header_loaded(len(self._flat))
        )
        body = self.query_one("#comments-body", Static)
        if not self._flat:
            body.update("[#6c7080 italic](no comments yet)[/]")
            self._focused_idx = -1
            self._refresh_post_card()
            return
        self._focused_idx = -1
        body.update(self._build_renderable())
        self._refresh_post_card()

    # ---------- rendering ----------

    def _build_renderable(self) -> RenderableType:
        """Build a Rich Group containing one Text per item in display order."""
        parts: list[RenderableType] = []
        for i, item in enumerate(self._flat):
            focused = i == self._focused_idx
            if isinstance(item, Comment):
                parts.append(self._render_comment(item, focused))
            elif isinstance(item, MoreComments):
                parts.append(self._render_more(item, focused))
            # blank spacer between blocks
            parts.append(Text(""))
        return Group(*parts)

    def _render_comment(self, c: Comment, focused: bool) -> Text:
        score_c = _score_color(c.score)
        depth_color = DEPTH_COLORS[c.depth % len(DEPTH_COLORS)]
        op_marker = (
            " [#ff4500 bold]OP[/]"
            if c.author == self.post.author and c.author != "[deleted]"
            else ""
        )
        if c.likes is True:
            arrow = "[#ff4500 bold]▲[/] "
        elif c.likes is False:
            arrow = "[#8be9fd bold]▼[/] "
        else:
            arrow = ""
        saved = " [#f1fa8c]★[/]" if c.saved else ""
        focus_pill = " [#50fa7b bold reverse] FOCUS [/]" if focused else ""
        header = (
            f"[{depth_color} bold]●[/] "
            f"[#f1fa8c]u/{escape_markup(c.author)}[/]{op_marker}  "
            f"{arrow}[{score_c}]▲ {format_score(c.score)}[/]  "
            f"[#6c7080]· {format_age(c.created_utc)} ago[/]{saved}{focus_pill}"
        )
        body_lines = _wrap_text(
            escape_markup(c.body or "[deleted]"), width=max(60, 100 - c.depth * 2)
        )
        block = [header] + body_lines
        all_lines = _indent_with_guides(block, c.depth)
        markup = "\n".join(all_lines)
        text = Text.from_markup(markup)
        if focused:
            text.stylize("on #1a1d27")
        return text

    def _render_more(self, m: MoreComments, focused: bool) -> Text:
        depth_color = DEPTH_COLORS[m.depth % len(DEPTH_COLORS)]
        if m.count > 0:
            label = f"load {m.count} more {'reply' if m.count == 1 else 'replies'}"
        else:
            label = "continue this thread"
        focus_pill = " [#50fa7b bold reverse] FOCUS [/]" if focused else ""
        line = (
            f"[{depth_color}]├─[/] "
            f"[#8be9fd underline]{label}[/]  "
            f"[#6c7080](press M)[/]{focus_pill}"
        )
        lines = _indent_with_guides([line], m.depth)
        text = Text.from_markup("\n".join(lines))
        if focused:
            text.stylize("on #1a1d27")
        return text

    def _redraw_comments(self) -> None:
        if not self._flat:
            return
        self.query_one("#comments-body", Static).update(self._build_renderable())

    # ---------- navigation ----------

    def action_next_comment(self) -> None:
        if not self._flat:
            self.query_one("#post-scroll", VerticalScroll).scroll_down()
            return
        self._set_focus(self._focused_idx + 1)

    def action_prev_comment(self) -> None:
        if not self._flat:
            self.query_one("#post-scroll", VerticalScroll).scroll_up()
            return
        self._set_focus(self._focused_idx - 1)

    def _set_focus(self, new_idx: int) -> None:
        new_idx = max(-1, min(len(self._flat) - 1, new_idx))
        if new_idx == self._focused_idx:
            return
        self._focused_idx = new_idx
        self._refresh_post_card()
        self._redraw_comments()
        scroll = self.query_one("#post-scroll", VerticalScroll)
        if new_idx == -1:
            scroll.scroll_home()
        else:
            # Approximate scroll: each item ~3 lines. Good enough until we
            # measure line-accurate positions in a future pass.
            target = self.query_one("#comments-body", Static).region.y + new_idx * 3
            scroll.scroll_to(y=max(0, target - 4), animate=False)

    # ---------- focused item ----------

    def _focused_thing(self) -> tuple[str, object] | None:
        if self._focused_idx == -1:
            if not self.post.name:
                return None
            return ("post", self.post)
        if 0 <= self._focused_idx < len(self._flat):
            it = self._flat[self._focused_idx]
            if isinstance(it, Comment):
                return ("comment", it)
            if isinstance(it, MoreComments):
                return ("more", it)
        return None

    # ---------- voting ----------

    def action_upvote(self) -> None:
        self._do_vote(1)

    def action_downvote(self) -> None:
        self._do_vote(-1)

    def _do_vote(self, direction: int) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required to vote[/]")
            return
        target = self._focused_thing()
        if target is None or target[0] == "more":
            return
        kind, obj = target
        if (direction == 1 and obj.likes is True) or (direction == -1 and obj.likes is False):
            new_dir = 0
        else:
            new_dir = direction
        old_likes = obj.likes
        old_score = obj.score
        if new_dir == 1:
            obj.score += 1 if old_likes is None else (2 if old_likes is False else 0)
            obj.likes = True
        elif new_dir == -1:
            obj.score += -1 if old_likes is None else (-2 if old_likes is True else 0)
            obj.likes = False
        else:
            obj.score += -1 if old_likes is True else (1 if old_likes is False else 0)
            obj.likes = None
        if kind == "post":
            self._refresh_post_card()
        else:
            self._redraw_comments()
        self.run_worker(
            self._send_vote(obj.name, new_dir, kind, old_likes, old_score),
            group="vote",
        )

    async def _send_vote(
        self, fullname: str, direction: int, kind: str, old_likes, old_score: int
    ) -> None:
        try:
            await self.client.vote(fullname, direction)
        except RedditError as e:
            self._revert_vote(fullname, kind, old_likes, old_score, str(e))
            return
        label = {1: "upvoted", -1: "downvoted", 0: "vote cleared"}.get(direction, "voted")
        self._set_status(f"[#50fa7b]✓ {label}[/]")

    def _revert_vote(
        self, fullname: str, kind: str, old_likes, old_score: int, err: str
    ) -> None:
        if kind == "post" and self.post.name == fullname:
            self.post.likes = old_likes
            self.post.score = old_score
            self._refresh_post_card()
        else:
            for it in self._flat:
                if isinstance(it, Comment) and it.name == fullname:
                    it.likes = old_likes
                    it.score = old_score
                    self._redraw_comments()
                    break
        self._set_status(f"[#ff5555]✗ vote failed: {escape_markup(err)}[/]")

    # ---------- save ----------

    def action_toggle_save(self) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required to save[/]")
            return
        target = self._focused_thing()
        if target is None or target[0] == "more":
            return
        kind, obj = target
        target_state = not obj.saved
        obj.saved = target_state
        if kind == "post":
            self._refresh_post_card()
        else:
            self._redraw_comments()
        self.run_worker(self._send_save(obj.name, target_state, kind), group="save")

    async def _send_save(self, fullname: str, save: bool, kind: str) -> None:
        try:
            if save:
                await self.client.save(fullname)
            else:
                await self.client.unsave(fullname)
        except RedditError as e:
            self._revert_save(fullname, kind, not save, str(e))
            return
        self._set_status(f"[#50fa7b]✓ {'saved' if save else 'unsaved'}[/]")

    def _revert_save(self, fullname: str, kind: str, original: bool, err: str) -> None:
        if kind == "post" and self.post.name == fullname:
            self.post.saved = original
            self._refresh_post_card()
        else:
            for it in self._flat:
                if isinstance(it, Comment) and it.name == fullname:
                    it.saved = original
                    self._redraw_comments()
                    break
        self._set_status(f"[#ff5555]✗ save failed: {escape_markup(err)}[/]")

    # ---------- reply ----------

    def action_reply_post(self) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required to comment[/]")
            return
        if not self.post.name:
            self._set_status("[yellow]⚠ post id missing[/]")
            return
        self._open_reply_dialog(self.post.name, f"reply to post: {self.post.title[:40]}")

    def action_reply_comment(self) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required to comment[/]")
            return
        target = self._focused_thing()
        if target is None or target[0] != "comment":
            self._set_status("[yellow]⚠ select a comment first (j/k)[/]")
            return
        c = target[1]
        self._open_reply_dialog(c.name, f"reply to u/{c.author}")

    def _open_reply_dialog(self, parent_fullname: str, prompt: str) -> None:
        from reddit_tui.screens.reply_dialog import ReplyDialog

        def _cb(value: str | None) -> None:
            if value and value.strip():
                self.run_worker(
                    self._send_reply(parent_fullname, value.strip()), group="reply"
                )

        self.app.push_screen(ReplyDialog(prompt), _cb)

    async def _send_reply(self, parent_fullname: str, text: str) -> None:
        try:
            await self.client.submit_comment(parent_fullname, text)
        except RedditError as e:
            self._set_status(f"[#ff5555]✗ comment failed: {escape_markup(str(e))}[/]")
            return
        self._set_status("[#50fa7b]✓ comment posted, reloading…[/]")
        self.action_refresh()

    # ---------- load more ----------

    def action_load_more(self) -> None:
        target = self._focused_thing()
        if target is None or target[0] != "more":
            self._set_status("[yellow]⚠ focus a 'load more' line first[/]")
            return
        m: MoreComments = target[1]
        if not self.post.name:
            self._set_status("[yellow]⚠ post id missing[/]")
            return
        if not m.children:
            # "continue this thread" -- we'd need to refetch a sub-permalink.
            self._set_status("[yellow]⚠ deep thread continuation not yet supported[/]")
            return
        self._set_status("[#6c7080]◌ loading more…[/]")
        self.run_worker(self._fetch_more(self.post.name, m), group="more")

    async def _fetch_more(self, link_fullname: str, placeholder: MoreComments) -> None:
        try:
            new_items = await self.client.get_more_children(link_fullname, placeholder.children)
        except RedditError as e:
            self._set_status(f"[#ff5555]✗ load more failed: {escape_markup(str(e))}[/]")
            return
        self._splice_more(placeholder, new_items)

    def _splice_more(self, placeholder: MoreComments, new_items: list[object]) -> None:
        """Replace ``placeholder`` in the tree with ``new_items``, re-threading
        any items whose parent_id matches an existing comment."""
        # Build index of all comments by fullname
        index: dict[str, Comment] = {}

        def index_walk(seq: Sequence[object]) -> None:
            for it in seq:
                if isinstance(it, Comment):
                    if it.name:
                        index[it.name] = it
                    index_walk(it.replies)

        index_walk(self.top_items)

        # Re-thread fetched items: those whose parent is in index get appended
        # to that parent's replies; the rest go in a flat list to splice in
        # place of the placeholder.
        flat_replacement: list[object] = []
        for it in new_items:
            parent = None
            if isinstance(it, Comment):
                parent = index.get(getattr(it, "name", ""))  # avoid dup
                if parent is not None:
                    continue  # already present
                # parent_id is on raw json, not on our Comment dataclass; rely
                # on depth heuristic and placeholder's depth instead.
                # Adjust depth based on placeholder depth.
                it.depth = placeholder.depth
                index[it.name] = it
            elif isinstance(it, MoreComments):
                it.depth = placeholder.depth
            flat_replacement.append(it)

        # Splice into the tree: find placeholder and replace.
        def replace_in(seq: list[object]) -> bool:
            for i, x in enumerate(seq):
                if x is placeholder:
                    seq[i : i + 1] = flat_replacement
                    return True
                if isinstance(x, Comment):
                    if replace_in(x.replies):  # type: ignore[arg-type]
                        return True
            return False

        replace_in(self.top_items)  # type: ignore[arg-type]
        self._flat = _flatten(self.top_items)
        # Clamp focus
        self._focused_idx = min(self._focused_idx, len(self._flat) - 1)
        self.query_one("#comments-title", Static).update(
            self._comments_header_loaded(len(self._flat))
        )
        self._redraw_comments()
        self._set_status(f"[#50fa7b]✓ loaded {len(new_items)} more[/]")

    # ---------- status ----------

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status-bar", Static).update(msg)
        except Exception:
            pass
