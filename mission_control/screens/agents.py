"""Agents: every agent step as a row (plus the runner's own work), and one step's session."""

from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import DataTable, Static, Tree

from mission_control import fmt
from mission_control.model import Call, Run, Step, Update
from mission_control.screens.base import View
from mission_control.widgets import Detail, Row, Timeline, facts, make_table, sync_table

RUNNER = "__runner__"  # row key for work the runner did outside any agent step
FILTERS = ("vendor", "role", "status")


def agent_rows(run: Run, compact: bool = False, only: dict[str, str] | None = None) -> list[Row]:
    """A "runner" row first when plain runner code made tool calls, then one row per step."""
    rows: list[Row] = []
    runner_calls = [i for i in run.runner_items if isinstance(i, Call)]
    if runner_calls and _keep(RUNNER_VALUES, only):
        cells: list[Any] = [Text("⚙", style="dim"), "runner", "code", "runner"]
        cells += ["", fmt.clock(runner_calls[0].time)] if not compact else []
        cells += ["", str(len(runner_calls))] + (["", "", ""] if not compact else []) + [""]
        rows.append((RUNNER, cells))
    for step in run.steps.values():
        if _keep(filter_values(step), only):
            rows.append((step.name, _step_cells(step, compact)))
    return rows


RUNNER_VALUES = {"vendor": "code", "role": "runner", "status": "done"}


def filter_values(step: Step) -> dict[str, str]:
    return {"vendor": step.vendor, "role": step.role, "status": step.status}


def _keep(values: dict[str, str], only: dict[str, str] | None) -> bool:
    return not only or all(values[k] == v for k, v in only.items())


def _step_cells(step: Step, compact: bool) -> list[Any]:
    tokens = step.tokens
    cells: list[Any] = [fmt.status_icon(step.status), step.name, step.vendor, step.role]
    cells += [step.model, fmt.clock(step.time)] if not compact else []
    cells += [fmt.duration(step.seconds) if step.done else "…", str(len(step.calls))]
    if not compact:
        cells += [fmt.count(tokens["input_tokens"]), fmt.count(tokens["cached_input_tokens"]),
                  fmt.count(tokens["output_tokens"])]
    return [*cells, fmt.money(tokens["cost_usd"])]


COMPACT_COLUMNS = ("", "step", "vendor", "role", "took", "tools", "cost")
FULL_COLUMNS = ("", "step", "vendor", "role", "model", "started", "took", "tools", "in", "cached", "out", "cost")


class AgentsScreen(View):
    TITLES: ClassVar[dict[str, str]] = {"#agents": "Agents"}
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("v", "cycle('vendor')", "Vendor"),
        Binding("l", "cycle('role')", "Role"),
        Binding("s", "cycle('status')", "Status"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.only: dict[str, str] = {}

    def body(self) -> ComposeResult:
        yield Static(id="filters")
        yield make_table(*FULL_COLUMNS, id="agents")

    def redraw(self, run: Run, updates: list[Update]) -> None:
        text = Text()
        for key in FILTERS:
            text.append(f"{key}: ", style="dim")
            text.append(self.only.get(key, "all"), style="bold" if key in self.only else "")
            text.append("   ")
        self.query_one("#filters", Static).update(text)
        sync_table(self.query_one("#agents", DataTable), agent_rows(run, only=self.only))

    def action_cycle(self, key: str) -> None:
        run = self.app.selected
        if run is None:
            return
        values = {filter_values(s)[key] for s in run.steps.values()} | {RUNNER_VALUES[key]}
        options = ["all", *sorted(v for v in values if v)]
        current = self.only.get(key, "all")
        chosen = options[(options.index(current) + 1) % len(options)] if current in options else "all"
        if chosen == "all":
            self.only.pop(key, None)
        else:
            self.only[key] = chosen
        self.refresh_view([])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.app.open_session(event.row_key.value)


class SessionScreen(View):
    """One agent step from prompt to result (or the runner's own work): its timeline and details."""

    TITLES: ClassVar[dict[str, str]] = {"#session-timeline": "Timeline", "#session-detail": "Detail · v full view"}
    BINDINGS: ClassVar[list[BindingType]] = [Binding("f", "toggle_follow", "Follow")]

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self._shown_run: Run | None = None

    def body(self) -> ComposeResult:
        yield Static(id="session-facts")
        with Horizontal():
            yield Timeline(id="session-timeline")
            yield Detail(id="session-detail")

    def _scope(self, run: Run) -> tuple[Step | None, list]:
        if self.key == RUNNER:
            return None, run.runner_items
        step = run.steps.get(self.key)
        return step, step.items if step else []

    def redraw(self, run: Run, updates: list[Update]) -> None:
        step, entries = self._scope(run)
        timeline = self.query_one(Timeline)
        if run is not self._shown_run:
            self._shown_run = run
            timeline.show(entries, scope=step)
            timeline.focus()
        else:
            mine = [u for u in updates if u.parent is step and not isinstance(u.item, Step)]
            timeline.apply(mine)
            self.query_one(Detail).refresh_if_showing([u.item for u in mine])
        self.query_one("#session-facts", Static).update(self._facts(step, run))

    def _facts(self, step: Step | None, run: Run) -> Any:
        if step is None:
            calls = [i for i in run.runner_items if isinstance(i, Call)]
            return facts(session="runner (plain code, no agent)", tool_calls=str(len(calls)))
        tokens = step.tokens
        return facts(session=step.session.get("session_id"), step=step.name, role=step.role,
                     model=f"{step.vendor} {step.model}", status=step.status,
                     took=fmt.duration(step.seconds), tool_calls=str(len(step.calls)),
                     tokens=f"in {fmt.count(tokens['input_tokens'])} · cached "
                            f"{fmt.count(tokens['cached_input_tokens'])} · out {fmt.count(tokens['output_tokens'])}",
                     cost=fmt.money(tokens["cost_usd"]), error=step.error)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.data is not None and self._shown_run is not None:
            self.query_one(Detail).show(event.node.data, self._shown_run)

    def action_toggle_follow(self) -> None:
        timeline = self.query_one(Timeline)
        timeline.follow = not timeline.follow
        self.notify("following newest" if timeline.follow else "follow off", timeout=2)
