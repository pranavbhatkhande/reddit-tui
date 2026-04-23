"""Modal text input dialog."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class InputDialog(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, prompt: str, initial: str = "") -> None:
        super().__init__()
        self.prompt = prompt
        self.initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            yield Static(f"  {self.prompt}", id="dialog-prompt")
            yield Input(value=self.initial, id="input-field", placeholder="type here…")
            yield Static("  [#c5c8d3]enter[/] submit   [#c5c8d3]esc[/] cancel", id="dialog-hint")

    def on_mount(self) -> None:
        self.query_one("#input-field", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
