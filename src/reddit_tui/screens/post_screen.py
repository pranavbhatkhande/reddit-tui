"""Post detail screen with comments."""
from __future__ import annotations

from typing import List, Optional

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from reddit_tui.reddit_client import Comment, Post, RedditClient, RedditError
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


def _wrap_text(text: str, width: int = 100) -> List[str]:
    out: List[str] = []
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


def _indent_with_guides(lines: List[str], depth: int) -> List[str]:
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


class CommentWidget(Static):
    """A single comment, rendered with header + body and depth-indented guides."""

    DEFAULT_CSS = """
    CommentWidget {
        padding: 0 0;
        height: auto;
        background: #0f1117;
    }
    CommentWidget.-focused {
        background: #1a1d27;
    }
    """

    def __init__(self, comment: Comment, op_author: str) -> None:
        self.comment = comment
        self.op_author = op_author
        super().__init__(self._build())

    def _build(self) -> str:
        c = self.comment
        score_c = _score_color(c.score)
        depth_color = DEPTH_COLORS[c.depth % len(DEPTH_COLORS)]
        op_marker = (
            " [#ff4500 bold]OP[/]"
            if c.author == self.op_author and c.author != "[deleted]"
            else ""
        )
        if c.likes is True:
            arrow = "[#ff4500 bold]▲[/] "
        elif c.likes is False:
            arrow = "[#8be9fd bold]▼[/] "
        else:
            arrow = ""
        saved = " [#f1fa8c]★[/]" if c.saved else ""
        header = (
            f"[{depth_color} bold]●[/] "
            f"[#f1fa8c]u/{escape_markup(c.author)}[/]{op_marker}  "
            f"{arrow}[{score_c}]▲ {format_score(c.score)}[/]  "
            f"[#6c7080]· {format_age(c.created_utc)} ago[/]{saved}"
        )
        body_lines = _wrap_text(
            escape_markup(c.body or "[deleted]"), width=max(60, 100 - c.depth * 2)
        )
        block = [header] + body_lines
        all_lines = _indent_with_guides(block, c.depth)
        return "\n".join(all_lines)

    def refresh_render(self) -> None:
        self.update(self._build())


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
    ]

    def __init__(self, client: RedditClient, post: Post) -> None:
        super().__init__()
        self.client = client
        self.post = post
        self.comments: List[Comment] = []
        self._flat_comments: List[Comment] = []
        self._comment_widgets: List[CommentWidget] = []
        self._focused_idx: int = -1  # index into _flat_comments; -1 means post

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
        self._fetch_comments()

    def _update_status_hint(self) -> None:
        try:
            sb = self.query_one("#status-bar", Static)
        except Exception:
            return
        if self.client.authenticated:
            hint = (
                "  [#c5c8d3]j/k[/] navigate  [#c5c8d3]u/d[/] vote  "
                "[#c5c8d3]S[/] save  [#c5c8d3]c[/] reply post  "
                "[#c5c8d3]R[/] reply cmt  [#c5c8d3]o[/] open  [#c5c8d3]q[/] back"
            )
        else:
            hint = "  [#c5c8d3]j/k[/] scroll  [#c5c8d3]o[/] open  [#c5c8d3]r[/] reload  [#c5c8d3]q[/] back"
        sb.update(hint)

    def action_refresh(self) -> None:
        self.query_one("#comments-body", Static).update("[#6c7080]◌ reloading…[/]")
        self._fetch_comments()

    def action_open_url(self) -> None:
        import webbrowser
        target = self.post.url or f"https://www.reddit.com{self.post.permalink}"
        try:
            webbrowser.open(target)
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def _fetch_comments(self) -> None:
        try:
            fresh_post, comments = self.client.get_post_with_comments(self.post.permalink)
        except RedditError as e:
            self.app.call_from_thread(
                self.query_one("#comments-body", Static).update,
                f"[#ff5555]✗ failed to load comments: {escape_markup(str(e))}[/]",
            )
            return
        self.app.call_from_thread(self._update_post_meta, fresh_post)
        self.app.call_from_thread(self._render_comments, comments)

    def _update_post_meta(self, fresh: Post) -> None:
        # Update vote / save state from fresh fetch (anonymous won't have these)
        self.post.likes = fresh.likes
        self.post.saved = fresh.saved
        self.post.score = fresh.score
        self.post.num_comments = fresh.num_comments
        if not self.post.name:
            self.post.name = fresh.name
        self._refresh_post_card()

    def _refresh_post_card(self) -> None:
        self.query_one("#post-card", Static).update(self._post_card())

    def _flatten(self, comments: List[Comment]) -> List[Comment]:
        out: List[Comment] = []

        def walk(cs: List[Comment]) -> None:
            for c in cs:
                out.append(c)
                walk(c.replies)

        walk(comments)
        return out

    def _render_comments(self, comments: List[Comment]) -> None:
        self.comments = comments
        self._flat_comments = self._flatten(comments)

        scroll = self.query_one("#post-scroll", VerticalScroll)
        # Remove the placeholder body widget if present
        try:
            self.query_one("#comments-body", Static).remove()
        except Exception:
            pass
        # Remove any existing CommentWidgets (in case of refresh)
        for w in list(scroll.query(CommentWidget)):
            w.remove()

        self.query_one("#comments-title", Static).update(
            self._comments_header_loaded(len(self._flat_comments))
        )

        if not self._flat_comments:
            scroll.mount(Static("[#6c7080 italic](no comments yet)[/]", id="comments-body"))
            return

        self._comment_widgets = []
        for c in self._flat_comments:
            w = CommentWidget(c, op_author=self.post.author)
            self._comment_widgets.append(w)
            scroll.mount(w)
        # Keep focus on post initially
        self._focused_idx = -1
        self._refresh_post_card()

    # ---------- navigation ----------

    def action_next_comment(self) -> None:
        if not self._comment_widgets:
            self.query_one("#post-scroll", VerticalScroll).scroll_down()
            return
        self._set_focus(self._focused_idx + 1)

    def action_prev_comment(self) -> None:
        if not self._comment_widgets:
            self.query_one("#post-scroll", VerticalScroll).scroll_up()
            return
        self._set_focus(self._focused_idx - 1)

    def _set_focus(self, new_idx: int) -> None:
        new_idx = max(-1, min(len(self._comment_widgets) - 1, new_idx))
        if new_idx == self._focused_idx:
            return
        # Unstyle old
        if 0 <= self._focused_idx < len(self._comment_widgets):
            self._comment_widgets[self._focused_idx].remove_class("-focused")
        self._focused_idx = new_idx
        if new_idx == -1:
            self.query_one("#post-scroll", VerticalScroll).scroll_home()
        else:
            w = self._comment_widgets[new_idx]
            w.add_class("-focused")
            w.scroll_visible()
        self._refresh_post_card()

    # ---------- voting ----------

    def _focused_thing(self) -> tuple[str, object] | None:
        """Return (kind, target) where kind is 'post' or 'comment'."""
        if self._focused_idx == -1:
            if not self.post.name:
                return None
            return ("post", self.post)
        if 0 <= self._focused_idx < len(self._flat_comments):
            return ("comment", self._flat_comments[self._focused_idx])
        return None

    def action_upvote(self) -> None:
        self._do_vote(1)

    def action_downvote(self) -> None:
        self._do_vote(-1)

    def _do_vote(self, direction: int) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required to vote[/]")
            return
        target = self._focused_thing()
        if target is None:
            return
        kind, obj = target
        # toggle
        if (direction == 1 and obj.likes is True) or (direction == -1 and obj.likes is False):
            new_dir = 0
        else:
            new_dir = direction
        old_likes = obj.likes
        old_score = obj.score
        if new_dir == 1:
            obj.score += (1 if old_likes is None else (2 if old_likes is False else 0))
            obj.likes = True
        elif new_dir == -1:
            obj.score += (-1 if old_likes is None else (-2 if old_likes is True else 0))
            obj.likes = False
        else:
            obj.score += (-1 if old_likes is True else (1 if old_likes is False else 0))
            obj.likes = None
        self._refresh_target(kind, obj)
        self._send_vote(obj.name, new_dir, kind, old_likes, old_score)

    @work(exclusive=False, thread=True, group="vote")
    def _send_vote(self, fullname: str, direction: int, kind: str, old_likes, old_score: int) -> None:
        try:
            self.client.vote(fullname, direction)
        except RedditError as e:
            self.app.call_from_thread(self._revert_vote, fullname, kind, old_likes, old_score, str(e))
            return
        label = {1: "upvoted", -1: "downvoted", 0: "vote cleared"}.get(direction, "voted")
        self.app.call_from_thread(self._set_status, f"[#50fa7b]✓ {label}[/]")

    def _revert_vote(self, fullname: str, kind: str, old_likes, old_score: int, err: str) -> None:
        if kind == "post" and self.post.name == fullname:
            self.post.likes = old_likes
            self.post.score = old_score
            self._refresh_post_card()
        else:
            for i, c in enumerate(self._flat_comments):
                if c.name == fullname:
                    c.likes = old_likes
                    c.score = old_score
                    if i < len(self._comment_widgets):
                        self._comment_widgets[i].refresh_render()
                    break
        self._set_status(f"[#ff5555]✗ vote failed: {escape_markup(err)}[/]")

    def _refresh_target(self, kind: str, obj) -> None:
        if kind == "post":
            self._refresh_post_card()
        else:
            try:
                idx = self._flat_comments.index(obj)
            except ValueError:
                return
            if idx < len(self._comment_widgets):
                self._comment_widgets[idx].refresh_render()

    # ---------- save ----------

    def action_toggle_save(self) -> None:
        if not self.client.authenticated:
            self._set_status("[yellow]⚠ login required to save[/]")
            return
        target = self._focused_thing()
        if target is None:
            return
        kind, obj = target
        target_state = not obj.saved
        obj.saved = target_state
        self._refresh_target(kind, obj)
        self._send_save(obj.name, target_state, kind)

    @work(exclusive=False, thread=True, group="save")
    def _send_save(self, fullname: str, save: bool, kind: str) -> None:
        try:
            if save:
                self.client.save(fullname)
            else:
                self.client.unsave(fullname)
        except RedditError as e:
            self.app.call_from_thread(self._revert_save, fullname, kind, not save, str(e))
            return
        self.app.call_from_thread(
            self._set_status, f"[#50fa7b]✓ {'saved' if save else 'unsaved'}[/]"
        )

    def _revert_save(self, fullname: str, kind: str, original: bool, err: str) -> None:
        if kind == "post" and self.post.name == fullname:
            self.post.saved = original
            self._refresh_post_card()
        else:
            for i, c in enumerate(self._flat_comments):
                if c.name == fullname:
                    c.saved = original
                    if i < len(self._comment_widgets):
                        self._comment_widgets[i].refresh_render()
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
        if self._focused_idx < 0 or self._focused_idx >= len(self._flat_comments):
            self._set_status("[yellow]⚠ select a comment first (j/k)[/]")
            return
        c = self._flat_comments[self._focused_idx]
        self._open_reply_dialog(c.name, f"reply to u/{c.author}")

    def _open_reply_dialog(self, parent_fullname: str, prompt: str) -> None:
        from reddit_tui.screens.input_dialog import InputDialog

        def _cb(value: str | None) -> None:
            if value and value.strip():
                self._send_reply(parent_fullname, value.strip())

        self.app.push_screen(InputDialog(prompt), _cb)

    @work(exclusive=False, thread=True, group="reply")
    def _send_reply(self, parent_fullname: str, text: str) -> None:
        try:
            self.client.submit_comment(parent_fullname, text)
        except RedditError as e:
            self.app.call_from_thread(
                self._set_status, f"[#ff5555]✗ comment failed: {escape_markup(str(e))}[/]"
            )
            return
        self.app.call_from_thread(self._set_status, "[#50fa7b]✓ comment posted, reloading…[/]")
        self.app.call_from_thread(self.action_refresh)

    # ---------- status ----------

    def _set_status(self, msg: str) -> None:
        try:
            self.query_one("#status-bar", Static).update(msg)
        except Exception:
            pass
