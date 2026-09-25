"""The New mission form: checkboxes and number inputs built from a workflow's described options.

The mission JSON stays the source of truth; the form edits it one field at a time. Choices
made before a draft exists are remembered and applied on top of the draft."""

from __future__ import annotations

from typing import Any

from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.validation import Number
from textual.widgets import Checkbox, Input, Label, Select

Key = tuple[str, ...]  # ("tools",) for a choice group, ("budget", "max_tasks") for a number


class MissionForm(VerticalScroll):
    class Changed(Message):
        def __init__(self, key: Key):
            super().__init__()
            self.key = key

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.touched: set[Key] = set()
        self._choices: dict[Key, list[tuple[str, Checkbox]]] = {}
        self._numbers: dict[Key, tuple[Input, dict[str, Any]]] = {}
        self._selects: dict[Key, Select] = {}
        self._syncing = False

    # ------------------------------------------------------------ build

    def build(self, options: dict[str, Any]) -> None:
        self.remove_children()
        self._choices, self._numbers, self._selects, self.touched = {}, {}, {}, set()
        for select in options.get("selects", []):
            choices = [(o["label"], o["value"]) for o in select["options"]]
            if not choices:
                continue
            default = select.get("default") if select.get("default") in {v for _, v in choices} else choices[0][1]
            self.mount(Label(select["label"], classes="nm-form-label"))
            widget = Select(choices, value=default, allow_blank=False, classes="nm-select")
            self._selects[(select["field"],)] = widget
            self.mount(widget)
        for choice in options.get("choices", []):
            key: Key = (choice["field"],)
            self.mount(Label(choice["label"], classes="nm-form-label"))
            boxes = []
            for option in choice["options"]:
                label = option["label"] + ("" if option["available"] else "  (unavailable)")
                box = Checkbox(label, value=False, disabled=not option["available"], classes="nm-check")
                if option.get("note"):
                    box.tooltip = option["note"]
                boxes.append((option["value"], box))
                self.mount(box)
            self._choices[key] = boxes
        if options.get("numbers"):
            self.mount(Label("Budget", classes="nm-form-label"))
        for number in options.get("numbers", []):
            key = tuple(number["path"])
            field = Input(type="integer" if number["integer"] else "number", classes="nm-number",
                          validators=[Number(minimum=number.get("min"), maximum=number.get("max"))],
                          placeholder=_limits(number))
            self._numbers[key] = (field, number)
            self.mount(Horizontal(Label(number["label"], classes="nm-number-label"), field, classes="nm-number-row"))

    # ------------------------------------------------------------ mission <-> form

    def load(self, mission: dict[str, Any]) -> None:
        """Show the mission's values in the form (without counting as user edits)."""
        self._syncing = True
        try:
            for key, boxes in self._choices.items():
                chosen = set(_get(mission, key) or [])
                for value, box in boxes:
                    box.value = value in chosen
            for key, (field, _) in self._numbers.items():
                value = _get(mission, key)
                field.value = "" if value is None else str(value)
            for key, widget in self._selects.items():
                value = _get(mission, key)
                if value is not None and value in {v for _, v in widget._options}:
                    widget.value = value
        finally:
            self.call_after_refresh(self._done_syncing)

    def _done_syncing(self) -> None:
        self._syncing = False

    def apply(self, mission: dict[str, Any], keys: set[Key] | None = None) -> dict[str, Any]:
        """Write the form's values for `keys` (default: all) into the mission; invalid numbers are skipped."""
        for key, boxes in self._choices.items():
            if keys is None or key in keys:
                _set(mission, key, [value for value, box in boxes if box.value])
        for key, (field, spec) in self._numbers.items():
            if (keys is None or key in keys) and field.is_valid and field.value.strip():
                _set(mission, key, int(field.value) if spec["integer"] else float(field.value))
        for key, widget in self._selects.items():
            if keys is None or key in keys:
                _set(mission, key, widget.value)
        return mission

    @property
    def select_keys(self) -> set[Key]:
        return set(self._selects)

    def value(self, key: Key) -> Any:
        widget = self._selects.get(key)
        return widget.value if widget is not None else None

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = next((k for k, boxes in self._choices.items() if any(b is event.checkbox for _, b in boxes)), None)
        self._changed(key)

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()  # the screen's own workflow picker listens for Select.Changed too
        self._changed(next((k for k, w in self._selects.items() if w is event.select), None))

    def on_input_changed(self, event: Input.Changed) -> None:
        key = next((k for k, (field, _) in self._numbers.items() if field is event.input), None)
        if event.validation_result is None or event.validation_result.is_valid:
            self._changed(key)

    def _changed(self, key: Key | None) -> None:
        if key is None or self._syncing:
            return
        self.touched.add(key)
        self.post_message(self.Changed(key))


def _limits(number: dict[str, Any]) -> str:
    low, high = number.get("min"), number.get("max")
    return f"{low}–{high}" if low is not None and high is not None else ""


def _get(mission: dict[str, Any], key: Key) -> Any:
    value: Any = mission
    for part in key:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _set(mission: dict[str, Any], key: Key, value: Any) -> None:
    target = mission
    for part in key[:-1]:
        target = target.setdefault(part, {})
    target[key[-1]] = value
