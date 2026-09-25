"""The three panes: run list, timeline tree, detail view. They render; the app wires them."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static, Tree
from textual.widgets.tree import TreeNode

from mission_control.model import Call, Item, Run, Step, Update

STATUS = {"running": ("⟳", "yellow"), "done": ("✓", "green"), "failed": ("✗", "red"),
          "crashed": ("✗", "red"), "unknown": ("?", "dim")}
VERDICT_OK = {"PASS", "AWAITING_APPROVAL", None}
BRIEF = 70


# ------------------------------------------------------------------ run list

class RunTable(DataTable):
    COLUMNS = ("", "workflow", "mission", "started", "took", "cost")

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        for column in self.COLUMNS:
            self.add_column(column, key=column)
        self._shown: dict[str, tuple[Any, ...]] = {}
        self._filled = False  # the first fill starts on the newest run; later ones keep the selection

    def show(self, runs: list[Run]) -> None:
        """Add new runs and patch changed cells, keeping the newest run on top."""
        added = False
        for run in runs:
            key = str(run.path)
            cells = self._cells(run)
            if key not in self._shown:
                self.add_row(*cells, key=key)
                added = True
            elif cells != self._shown[key]:
                for column, old, value in zip(self.COLUMNS, self._shown[key], cells, strict=True):
                    if value != old:
                        self.update_cell(key, column, value)
            self._shown[key] = cells
        if added:
            first_fill = not self._filled
            selected = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
            self.sort("started", reverse=True)  # "MM-DD HH:MM" sorts correctly within a year
            self.move_cursor(row=0 if first_fill else self.get_row_index(selected))
            self._filled = True

    @property
    def current_key(self) -> str | None:
        if not self.row_count:
            return None
        return self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value

    @staticmethod
    def _cells(run: Run) -> tuple[Any, ...]:
        icon, style = STATUS[run.status]
        if run.status == "done" and run.verdict not in VERDICT_OK:
            icon, style = "!", "magenta"
        return (Text(icon, style=style), run.workflow, run.mission, _clock(run.started, "%m-%d %H:%M"),
                _duration(run.seconds), f"${run.cost_usd:.2f}" if run.cost_usd else "")


# ------------------------------------------------------------------ timeline

class Timeline(Tree[Item]):
    """A run's steps, tool calls and events, patched in place as updates arrive."""

    def __init__(self, **kwargs: Any):
        super().__init__("run", **kwargs)
        self.show_root = False
        self.follow = True
        self._by_item: dict[int, TreeNode[Item]] = {}

    def show(self, run: Run) -> None:
        self.clear()
        self._by_item = {}
        for entry in run.entries:
            node = self._add(entry, self.root)
            if isinstance(entry, Step):
                for child in entry.items:
                    self._add(child, node)

    def apply(self, updates: list[Update]) -> None:
        latest = None
        for update in updates:
            node = self._by_item.get(id(update.item))
            if node is not None:
                node.set_label(label(update.item))
                continue
            parent = self.root if update.parent is None else self._by_item.get(id(update.parent))
            if parent is None:  # a step first seen through one of its children
                parent = self._add(update.parent, self.root)
            latest = self._add(update.item, parent)
        if latest is not None and self.follow:
            self.call_after_refresh(self.scroll_to_node, latest)

    def _add(self, item: Item, parent: TreeNode[Item]) -> TreeNode[Item]:
        if isinstance(item, Step):
            node = parent.add(label(item), data=item, expand=not item.done)
        else:
            node = parent.add_leaf(label(item), data=item)
        self._by_item[id(item)] = node
        return node


def label(item: Item) -> Text:
    text = Text(_clock(item.time) + " ", style="dim")
    if isinstance(item, Step):
        text.append(_state_icon(item.done, item.error))
        text.append(item.name, style="bold")
        detail = " ".join(str(item.fields[k]) for k in ("vendor", "model") if item.fields.get(k))
        text.append(f"  {detail}", style="dim")
        calls = sum(isinstance(i, Call) for i in item.items)
        text.append(f"  {calls} tools" if calls else "", style="dim")
        text.append(f"  {_duration(item.seconds)}" if item.done else "")
    elif isinstance(item, Call):
        text.append(_state_icon(item.done, item.error))
        text.append(item.tool, style="cyan")
        text.append(f"  {_brief(item.input)}", style="dim")
        text.append(f"  {_duration(item.seconds)}" if item.done else "")
    elif item.name == "message":
        thinking = item.fields.get("kind") == "thinking"
        text.append("… " if thinking else "› ", style="dim")
        text.append(_brief(item.fields.get("text", "")), style="italic dim" if thinking else "")
    else:
        style = {"warning": "yellow", "error": "red", "run.failed": "red"}.get(item.name, "bold")
        text.append(item.name, style=style)
        scalars = {k: v for k, v in item.fields.items() if isinstance(v, (str, int, float, bool)) and v != ""}
        text.append(f"  {_brief(scalars.get('text') or scalars)}" if scalars else "", style="dim")
    return text


def _state_icon(done: bool, error: Any) -> Text:
    if error:
        return Text("✗ ", style="red")
    return Text("✓ ", style="green") if done else Text("⟳ ", style="yellow")


# ------------------------------------------------------------------ detail

class Detail(VerticalScroll):
    """Everything about the selected run or timeline item, in full."""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.item: Run | Item | None = None
        self._body = Static(Text("Select a run.", style="dim"))

    def compose(self):
        yield self._body

    def show(self, item: Run | Item, run: Run) -> None:
        self.item = item
        self._body.update(Group(*_describe(item, run)))

    def refresh_if_showing(self, items: list[Item], run: Run) -> None:
        if any(i is self.item for i in items):
            self._body.update(Group(*_describe(self.item, run)))


def _describe(item: Run | Item, run: Run) -> list[RenderableType]:
    if isinstance(item, Run):
        return [_title(f"{item.workflow} / {item.path.name}"),
                _facts(status=item.status, verdict=item.verdict, error=item.error, pid=item.pid,
                       started=_clock(item.started, "%Y-%m-%d %H:%M:%S"), took=_duration(item.seconds),
                       steps=len(item.steps), tool_calls=len(item.calls),
                       cost=f"${item.cost_usd:.2f}" if item.cost_usd else None, folder=str(item.path))]
    if isinstance(item, Step):
        parts = [_title(f"step {item.name}"), _facts(**{**item.fields, **item.usage})]
        prompt = _read(run.path / item.fields["prompt_file"]) if item.fields.get("prompt_file") else None
        parts += [_heading("prompt"), Text(prompt) if prompt else Text("(no prompt saved for this step)", "dim")]
        return parts
    if isinstance(item, Call):
        parts = [_title(item.tool), _facts(call_id=item.call_id, started=_clock(item.time),
                                           took=_duration(item.seconds), done=item.done)]
        if item.error:
            parts += [_heading("error", "red"), _data(item.error)]
        parts += [_heading("input"), _data(item.input), _heading("output"), _data(item.output)]
        return parts
    if item.name == "message":
        return [_title(f"message ({item.fields.get('kind', 'text')})"), Text(str(item.fields.get("text", "")))]
    return [_title(item.name), _facts(time=_clock(item.time, "%Y-%m-%d %H:%M:%S")), _data(item.fields)]


def _title(text: str) -> Text:
    return Text(text + "\n", style="bold underline")


def _heading(text: str, style: str = "bold") -> Text:
    return Text("\n" + text, style=style)


def _facts(**facts: Any) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    for key, value in facts.items():
        if value is None or value == "" or value == {} or value == []:
            continue
        table.add_row(key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return table


def _data(value: Any) -> RenderableType:
    """Pretty JSON when the value is (or contains) JSON, else plain text."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return Text(value)
    if value is None:
        return Text("—", style="dim")
    return Syntax(json.dumps(value, indent=2, ensure_ascii=False), "json", word_wrap=True,
                  background_color="default")


# ------------------------------------------------------------------ formatting

def _clock(time: datetime | None, fmt: str = "%H:%M:%S") -> str:
    return time.astimezone().strftime(fmt) if time else "--:--:--"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s" if minutes < 60 else f"{minutes // 60}h{minutes % 60:02d}m"


def _brief(value: Any) -> str:
    if isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= BRIEF else text[: BRIEF - 1] + "…"


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None
