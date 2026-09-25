"""Overview: the selected run from a bird's-eye view. Every panel opens a detail screen."""

from __future__ import annotations

from typing import ClassVar

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Grid
from textual.widgets import DataTable, Static

from mission_control import fmt
from mission_control.model import Call, Event, Run, Step, Update
from mission_control.plugins import summarize
from mission_control.screens.agents import COMPACT_COLUMNS, agent_rows
from mission_control.screens.base import View
from mission_control.screens.plugins import plugin_rows
from mission_control.widgets import Row, label, make_table, sync_table

RECENT = 8  # items shown for the active step


def log_rows(run: Run) -> list[Row]:
    """Milestones, oldest first: steps starting and ending, workflow events, runner tool calls (grouped)."""
    lines: list[tuple[str, str]] = []  # (time, text)
    for entry in run.entries:
        if isinstance(entry, Step):
            lines.append((fmt.clock(entry.time), f"started {entry.name}  {entry.vendor} {entry.role}".rstrip()))
            if entry.done:
                icon = "✗" if entry.error else "✓"
                lines.append((fmt.clock(entry.ended), f"{icon} {entry.name} done in {fmt.duration(entry.seconds)}"))
        elif isinstance(entry, Call):
            previous = lines[-1][1] if lines else ""
            prefix = f"runner · {entry.tool}"
            if previous.startswith(prefix):
                n = int(previous.rsplit("×", 1)[1]) + 1 if "×" in previous else 2
                lines[-1] = (lines[-1][0], f"{prefix} ×{n}")
            else:
                lines.append((fmt.clock(entry.time), prefix))
        elif isinstance(entry, Event):
            lines.append((fmt.clock(entry.time), fmt.brief(label(entry).plain.split(" ", 1)[1], 90)))
    return [(str(i), [time, text]) for i, (time, text) in enumerate(lines)]


def active_panel(run: Run) -> Group:
    step = run.active_step
    if step is None:
        return Group(Text("No agent step yet.", style="dim"))
    head = Text()
    head.append_text(fmt.status_icon(step.status))
    head.append(f" {step.name}", style="bold")
    head.append(f"  {step.vendor} {step.model} · {step.role}", style="dim")
    head.append(f"  {fmt.duration(step.seconds)}" if step.done else "  running")
    recent = [label(item) for item in step.items[-RECENT:]]
    more = len(step.items) - len(recent)
    return Group(head, Text(f"  ↑ {more} earlier" if more > 0 else "", style="dim"), *recent)


class OverviewScreen(View):
    TITLES: ClassVar[dict[str, str]] = {"#active": "Active step", "#overview-agents": "Agents · a",
                                        "#overview-plugins": "Plugins · p", "#log": "Progress log"}

    def body(self) -> ComposeResult:
        with Grid(id="overview"):
            yield Static(id="active")
            yield make_table(*COMPACT_COLUMNS, id="overview-agents")
            yield make_table("plugin", "calls", "errors", "running", "avg", id="overview-plugins")
            yield make_table("time", "event", id="log")

    def redraw(self, run: Run, updates: list[Update]) -> None:
        self.query_one("#active", Static).update(active_panel(run))
        sync_table(self.query_one("#overview-agents", DataTable), agent_rows(run, compact=True))
        sync_table(self.query_one("#overview-plugins", DataTable),
                   plugin_rows(summarize(list(run.calls.values()))))
        log = self.query_one("#log", DataTable)
        rows = log_rows(run)
        grew = len(rows) > log.row_count
        sync_table(log, rows)
        if grew:
            log.scroll_end(animate=False)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "overview-agents":
            self.app.open_session(event.row_key.value)
        elif event.data_table.id == "overview-plugins":
            self.app.open_plugin(event.row_key.value)
