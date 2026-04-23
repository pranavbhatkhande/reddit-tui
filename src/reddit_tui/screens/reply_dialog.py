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
    DEFAULT_CSS = """
    ReplyDialog {
        align: center middle;
    }
    #reply-box {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        background: #161922;
        border: round #ff4500;
        padding: 1 2;
    }
    #reply-prompt {
        color: #f1fa8c;
        padding-bottom: 1;
    }
    #reply-area {
        height: 12;
        min-height: 6;
        background: #0f1117;
        border: round #2a2f3d;
    }
    #reply-hint {
        color: #6c7080;
        padding-top: 1;
    }
    """

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
