"""Building blocks the screens share: run header, table syncing, timeline tree, detail view."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import DataTable, Static, Tree
from textual.widgets.tree import TreeNode

from mission_control import fmt
from mission_control.model import Call, Item, Run, Step, Update

Row = tuple[str, Sequence[Any]]  # (row key, cells)


# ------------------------------------------------------------------ header

class RunHeader(Static):
    """One line: which run, its state, and its running totals."""

    def show(self, run: Run | None) -> None:
        if run is None:
            self.update(Text("No runs yet.", style="dim"))
            return
        tokens = run.tokens
        text = Text()
        text.append("Mission Control", style="bold magenta")
        text.append(f"  {run.workflow} / {run.mission}   ", style="dim")
        state = run.verdict if run.status == "done" and run.verdict else run.status
        text.append_text(fmt.status_text(run.status, state.upper()))
        text.append("   TIME ", style="dim")
        text.append(fmt.duration(run.seconds))
        for name, key in (("in", "input_tokens"), ("cached", "cached_input_tokens"), ("out", "output_tokens")):
            text.append(f" · {name} ", style="dim")
            text.append(fmt.count(tokens[key]))
        text.append(" · ", style="dim")
        text.append(fmt.money(tokens["cost_usd"]))
        self.update(text)


# ------------------------------------------------------------------ tables

def make_table(*columns: str, id: str | None = None) -> DataTable:
    table = DataTable(id=id, cursor_type="row", zebra_stripes=True)
    for column in columns:
        table.add_column(column, key=column)
    return table


def sync_table(table: DataTable, rows: list[Row]) -> None:
    """Make `table` show `rows` in order, touching only what changed and keeping the cursor's row."""
    keys = [key for key, _ in rows]
    if keys != [row.value for row in table.rows]:
        selected = cursor_key(table)
        table.clear()
        for key, cells in rows:
            table.add_row(*cells, key=key)
        if selected in keys:
            table.move_cursor(row=keys.index(selected), animate=False)
        return
    columns = list(table.columns)
    for key, cells in rows:
        for column, value in zip(columns, cells, strict=True):
            if table.get_cell(key, column) != value:
                table.update_cell(key, column, value)


def cursor_key(table: DataTable) -> str | None:
    if not table.row_count:
        return None
    return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value


# ------------------------------------------------------------------ timeline

class Timeline(Tree[Item]):
    """Steps, tool calls and events as a tree, patched in place as updates arrive.

    `scope` is the step whose items sit at the top level (None: the whole run)."""

    def __init__(self, **kwargs: Any):
        super().__init__("run", **kwargs)
        self.show_root = False
        self.follow = True
        self.scope: Step | None = None
        self._by_item: dict[int, TreeNode[Item]] = {}

    def show(self, entries: list[Item], scope: Step | None = None) -> None:
        self.clear()
        self.scope = scope
        self._by_item = {}
        for entry in entries:
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
            if update.parent is self.scope:
                parent = self.root
            else:
                parent = self._by_item.get(id(update.parent))
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
    text = Text(fmt.clock(item.time) + " ", style="dim")
    if isinstance(item, Step):
        text.append_text(fmt.status_icon(item.status))
        text.append(f" {item.name}", style="bold")
        text.append(f"  {item.vendor} {item.model}", style="dim")
        calls = len(item.calls)
        text.append(f"  {calls} tools" if calls else "", style="dim")
        text.append(f"  {fmt.duration(item.seconds)}" if item.done else "")
    elif isinstance(item, Call):
        text.append_text(fmt.status_icon(item.status))
        text.append(f" {item.tool}", style="cyan")
        text.append(f"  {fmt.brief(item.input)}", style="dim")
        text.append(f"  {fmt.duration(item.seconds)}" if item.done else "")
    elif item.name == "message":
        thinking = item.fields.get("kind") == "thinking"
        text.append("… " if thinking else "› ", style="dim")
        text.append(fmt.brief(item.fields.get("text", ""), 110), style="italic dim" if thinking else "")
    else:
        style = {"warning": "yellow", "error": "red", "run.failed": "red"}.get(item.name, "bold")
        text.append(item.name, style=style)
        scalars = {k: v for k, v in item.fields.items() if isinstance(v, (str, int, float, bool)) and v != ""}
        text.append(f"  {fmt.brief(scalars.get('text') or scalars)}" if scalars else "", style="dim")
    return text


# ------------------------------------------------------------------ detail

class Detail(VerticalScroll):
    """Everything about one run or timeline item, in full."""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.item: Run | Item | None = None
        self._run: Run | None = None
        self._body = Static(Text("Select something.", style="dim"))

    def compose(self):
        yield self._body

    def show(self, item: Run | Item | None, run: Run) -> None:
        self.item, self._run = item, run
        self._body.update(Group(*describe(item, run)) if item is not None else Text("—", style="dim"))

    def refresh_if_showing(self, items: list[Item]) -> None:
        if self._run is not None and any(i is self.item for i in items):
            self.show(self.item, self._run)


def describe(item: Run | Item, run: Run) -> list[RenderableType]:
    if isinstance(item, Run):
        return [_title(f"{item.workflow} / {item.path.name}"),
                facts(status=item.status, verdict=item.verdict, error=item.error, pid=item.pid,
                      started=fmt.clock(item.started, "%Y-%m-%d %H:%M:%S"), took=fmt.duration(item.seconds),
                      steps=len(item.steps), tool_calls=len(item.calls), cost=fmt.money(item.cost_usd),
                      folder=str(item.path))]
    if isinstance(item, Step):
        parts = [_title(f"step {item.name}"), facts(**{**item.fields, **item.session, **item.usage})]
        prompt = _read(run.path / item.fields["prompt_file"]) if item.fields.get("prompt_file") else None
        parts += [_heading("prompt"), Text(prompt) if prompt else Text("(no prompt saved for this step)", "dim")]
        return parts
    if isinstance(item, Call):
        parts = [_title(item.tool), facts(step=item.step or "runner", call_id=item.call_id,
                                          started=fmt.clock(item.time), took=fmt.duration(item.seconds),
                                          status=item.status)]
        if item.error:
            parts += [_heading("error", "red"), data(item.error)]
        parts += [_heading("input"), data(item.input), _heading("output"), data(item.output)]
        return parts
    if item.name == "message":
        return [_title(f"message ({item.fields.get('kind', 'text')})"), Text(str(item.fields.get("text", "")))]
    return [_title(item.name), facts(time=fmt.clock(item.time, "%Y-%m-%d %H:%M:%S")), data(item.fields)]


def _title(text: str) -> Text:
    return Text(text + "\n", style="bold underline")


def _heading(text: str, style: str = "bold") -> Text:
    return Text("\n" + text, style=style)


def facts(**values: Any) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    for key, value in values.items():
        if value is None or value in ("", "-", {}, []):
            continue
        table.add_row(key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
    return table


def data(value: Any) -> RenderableType:
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


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None
