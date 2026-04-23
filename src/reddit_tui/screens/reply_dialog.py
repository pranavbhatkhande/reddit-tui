"""Multi-line reply dialog using a TextArea.

Submit with ctrl+enter (or ctrl+s); cancel with escape. Returns the
typed text as a ``str`` on submit, or ``None`` on cancel.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea


class ReplyDialog(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Submit", show=True),
    ]

    def __init__(self, prompt: str, initial: str = "") -> None:
        super().__init__()
        self.prompt = prompt
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="reply-box"):
            yield Static(f"  {self.prompt}", id="reply-prompt")
            yield TextArea(text=self.initial, id="reply-area")
            yield Static(
                "  [#c5c8d3]ctrl+s[/] submit   [#c5c8d3]esc[/] cancel   "
                "[#6c7080](markdown supported)[/]",
                id="reply-hint",
            )

    def on_mount(self) -> None:
        area = self.query_one("#reply-area", TextArea)
        area.focus()

    def action_submit(self) -> None:
        text = self.query_one("#reply-area", TextArea).text
        if text.strip():
            self.dismiss(text)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
