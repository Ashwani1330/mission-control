"""Small modal dialogs: confirm an action, or type a note."""

from __future__ import annotations

from typing import ClassVar

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from mission_control import fmt


class Confirm(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,n", "dismiss(False)", "No"),
                                             Binding("y", "dismiss(True)", "Yes")]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Yes  y", id="yes", variant="error")
                yield Button("No  n", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class AskText(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, question: str, placeholder: str = ""):
        super().__init__()
        self.question, self.placeholder = question, placeholder

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question)
            yield Input(placeholder=self.placeholder, id="answer")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)


KEYS = [
    ("Missions", [("n", "new mission"), ("A", "approve a plan that waits for you (coding)"),
                  ("P", "pause / resume the selected run"), ("X", "stop it"),
                  ("M", "send a note to its next agent step")]),
    ("Screens", [("o", "overview"), ("l", "live agent tiles"), ("a", "agents (enter: session)"),
                 ("p", "plugins and tool calls"), ("m", "models per role"), ("f", "files the run produced")]),
    ("Runs", [("r", "jump to the run list"), ("b", "hide / show the run list"), ("esc", "back (overview → home)")]),
    ("Anywhere", [("v", "full view of the selected detail"), ("w", "follow newest (session)"), ("t", "theme"),
                  ("ctrl+p", "command palette"), ("q", "quit")]),
]


class KeysScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,question_mark,q", "dismiss(None)", "Close")]

    def compose(self) -> ComposeResult:
        grid = Table.grid(padding=(0, 3))
        grid.add_column(justify="right")
        grid.add_column()
        for section, keys in KEYS:
            grid.add_row(Text(section, style="bold"), "")
            for key, what in keys:
                grid.add_row(Text(key, style=f"bold {fmt.ACCENT}"), Text(what))
            grid.add_row("", "")
        with Vertical(classes="dialog keys"):
            yield Static(grid)
