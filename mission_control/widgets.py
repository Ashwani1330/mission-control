"""Building blocks the screens share: run header, table syncing, timeline tree, detail view."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Static, TextArea, Tree
from textual.widgets.tree import TreeNode

from mission_control import fmt
from mission_control.model import Call, Item, Run, Step, Update

Row = tuple[str, Sequence[Any]]  # (row key, cells)


# ------------------------------------------------------------------ header

class RunHeader(Vertical):
    """Two lines: brand, runs folder and totals; then the run's state and step progress."""

    BAR = 24

    def compose(self):
        with Horizontal(id="header-top"):
            yield Static(id="brand")
            yield Static(id="totals")
        yield Static(id="status")

    def show(self, run: Run | None, root: Path) -> None:
        brand = Text()
        brand.append("▲ Mission Control", style=f"bold {fmt.ACCENT}")
        brand.append(f"  {_home(root)}", style="dim")
        self.query_one("#brand", Static).update(brand)
        if run is None:
            self.query_one("#totals", Static).update("")
            self.query_one("#status", Static).update(
                Text("No run selected: pick one from the list (r), or start one (n).", style="dim"))
            return

        tokens = run.tokens
        totals = Text(justify="right")
        for name, value in (("TIME", fmt.duration(run.seconds)), ("Input", fmt.count(tokens["input_tokens"])),
                            ("Cached", fmt.count(tokens["cached_input_tokens"])),
                            ("Output", fmt.count(tokens["output_tokens"])), ("Cost", fmt.money(tokens["cost_usd"]))):
            totals.append(f"  {name} ", style="dim")
            totals.append(value)
        self.query_one("#totals", Static).update(totals)

        steps = list(run.steps.values())
        done = sum(s.done for s in steps)
        state = run.verdict if run.status == "done" and run.verdict else run.status
        status = Text()
        status.append_text(fmt.status_text(run.status, state.upper()))
        status.append(f"   {run.workflow} / {run.mission}   ", style="bold")
        filled = round(self.BAR * done / len(steps)) if steps else 0
        status.append("━" * filled, style=fmt.ACCENT)
        status.append("━" * (self.BAR - filled), style=fmt.MUTED)
        status.append(f"  {done}/{len(steps)} steps · {len(run.calls)} tool calls", style="dim")
        self.query_one("#status", Static).update(status)


def _home(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


# ------------------------------------------------------------------ tables

def make_table(*columns: str, id: str | None = None) -> DataTable:
    table = DataTable(id=id, cursor_type="row", zebra_stripes=False, cursor_foreground_priority="renderable")
    for column in columns:
        table.add_column(column, key=column)
    return table


def sync_table(table: DataTable, rows: list[Row]) -> None:
    """Make `table` show `rows` in order, touching only what changed and keeping the cursor's row."""
    keys = [key for key, _ in rows]
    current = [row.value for row in table.rows]
    if keys[:len(current)] == current and len(keys) > len(current):  # only grew: append, keep scroll
        for key, cells in rows[len(current):]:
            table.add_row(*cells, key=key)
        rows = rows[:len(current)]
    elif keys != current:
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
        text.append(f" {item.tool}", style="bold")
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

PREVIEW_LINES = 80  # longer sections are clipped; `v` opens the full text
TABLE_ROWS = 12
DEBOUNCE = 0.06  # seconds; holding an arrow key renders only where it stops


@dataclass
class Section:
    heading: str | None
    kind: str  # "facts" (a dict) · "text" (a str) · "json" (any value)
    body: Any
    style: str = "bold"


def describe(item: Run | Item, run: Run) -> tuple[str, list[Section]]:
    """What there is to say about one item, independent of how it is drawn."""
    if isinstance(item, Run):
        return f"{item.workflow} / {item.path.name}", [Section(None, "facts", {
            "status": item.status, "verdict": item.verdict, "error": item.error, "pid": item.pid,
            "started": fmt.clock(item.started, "%Y-%m-%d %H:%M:%S"), "took": fmt.duration(item.seconds),
            "steps": len(item.steps), "tool calls": len(item.calls), "cost": fmt.money(item.cost_usd),
            "folder": str(item.path)})]
    if isinstance(item, Step):
        prompt = _read(run.path / item.fields["prompt_file"]) if item.fields.get("prompt_file") else None
        return f"step {item.name}", [
            Section(None, "facts", {**item.fields, **item.session, **item.usage}),
            Section("prompt", "text", prompt or "(no prompt saved for this step)")]
    if isinstance(item, Call):
        sections = [Section(None, "facts", {"step": item.step or "runner", "call id": item.call_id,
                                            "started": fmt.clock(item.time), "took": fmt.duration(item.seconds),
                                            "status": item.status})]
        if item.error:
            sections.append(Section("error", "json", item.error, "bold red"))
        return item.tool, [*sections, Section("input", "json", item.input), Section("output", "json", item.output)]
    if item.name == "message":
        # "json" also renders plain text; agents often answer in JSON, which then gets pretty-printed.
        return f"message ({item.fields.get('kind', 'text')})", [Section(None, "json", str(item.fields.get("text", "")))]
    return item.name, [Section(None, "facts", {"time": fmt.clock(item.time, "%Y-%m-%d %H:%M:%S")}),
                       Section(None, "json", item.fields)]


def full_text(item: Run | Item, run: Run) -> str:
    title, sections = describe(item, run)
    parts = [title, ""]
    for section in sections:
        if section.heading:
            parts += [f"── {section.heading} ──"]
        if section.kind == "facts":
            parts += [f"{k}: {_fact(v)}" for k, v in section.body.items() if not _empty(v)]
        elif section.kind == "text":
            parts.append(section.body)
        else:
            parts.append(_pretty(section.body))
        parts.append("")
    return "\n".join(parts)


def preview(item: Run | Item, run: Run) -> Group:
    title, sections = describe(item, run)
    parts: list[RenderableType] = [Text(title + "\n", style="bold underline")]
    for section in sections:
        if section.heading:
            parts.append(Text("\n" + section.heading, style=section.style))
        if section.kind == "facts":
            parts.append(facts(**section.body))
        elif section.kind == "text":
            parts.append(Text(_clip(section.body)))
        else:
            parts.extend(data(section.body))
    return Group(*parts)


class Detail(VerticalScroll):
    """One run or timeline item: a preview here, the full text with `v`."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("v", "view_full", "View full")]

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.item: Run | Item | None = None
        self._run: Run | None = None
        self._timer: Timer | None = None
        self._body = Static(Text("Select something.", style="dim"))

    def compose(self):
        yield self._body

    def show(self, item: Run | Item | None, run: Run) -> None:
        self.item, self._run = item, run
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(DEBOUNCE, self._render_now)

    def _render_now(self) -> None:
        self._timer = None
        if self.item is None or self._run is None:
            self._body.update(Text("—", style="dim"))
            return
        self._body.update(preview(self.item, self._run))
        self.scroll_home(animate=False)

    def refresh_if_showing(self, items: list[Item]) -> None:
        if self._run is not None and any(i is self.item for i in items):
            self.show(self.item, self._run)

    def action_view_full(self) -> None:
        if self.item is not None and self._run is not None:
            self.app.push_screen(FullText(full_text(self.item, self._run)))


class FullText(ModalScreen):
    """The full text of one item. TextArea draws only the visible lines, so size does not matter."""

    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape,v,q", "dismiss", "Close")]

    def __init__(self, text: str):
        super().__init__()
        self._text = text

    def compose(self):
        yield TextArea(self._text, read_only=True, soft_wrap=True, show_line_numbers=True, id="full-text")
        yield Footer()


def facts(**values: Any) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    for key, value in values.items():
        if not _empty(value):
            table.add_row(key, _fact(value))
    return table


def data(value: Any) -> list[RenderableType]:
    """A value as clipped, highlighted JSON (or text); tabular yc results also as a table."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [Text(_clip(value))]
    if value is None:
        return [Text("—", style="dim")]
    value, rows = _split_csv(value)
    parts: list[RenderableType] = []
    if rows is not None:
        parts.append(_rows_table(rows))
    parts.append(Syntax(_clip(_pretty(value)), "json", word_wrap=True, background_color="default"))
    return parts


def _split_csv(value: Any) -> tuple[Any, list[dict[str, str]] | None]:
    """yc tools return rows as CSV inside JSON; pull them out so they can be drawn as a table."""
    if not isinstance(value, dict):
        return value, None
    inner = value.get("result") if isinstance(value.get("result"), dict) else value
    text = inner.get("csv_results")
    if not isinstance(text, str) or not text:
        return value, None
    rows = list(csv.DictReader(io.StringIO(text)))
    inner = {**inner, "csv_results": f"({len(rows)} rows, shown as a table above; v for the raw text)"}
    return ({**value, "result": inner} if inner is not value and "result" in value else inner), rows


def _rows_table(rows: list[dict[str, str]]) -> Table:
    columns = [c for c in (rows[0] if rows else {}) if c and "link" not in c][:6]
    table = Table(*columns, box=None, header_style="bold", show_edge=False, pad_edge=False,
                  caption=f"+{len(rows) - TABLE_ROWS} more rows (v)" if len(rows) > TABLE_ROWS else None,
                  caption_justify="left")
    for row in rows[:TABLE_ROWS]:
        table.add_row(*(fmt.brief(row.get(c) or "", 60) for c in columns))
    return table


def _clip(text: str, lines: int = PREVIEW_LINES) -> str:
    split = text.splitlines()
    if len(split) <= lines:
        return text
    return "\n".join(split[:lines]) + f"\n… {len(split) - lines} more lines (v to view all)"


def _pretty(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _fact(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _empty(value: Any) -> bool:
    return value is None or value in ("", "-", {}, [])


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None
