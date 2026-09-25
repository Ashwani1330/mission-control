"""Small modal dialogs: confirm an action, or type a note."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


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
