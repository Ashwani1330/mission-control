"""Live: one tile per agent (running ones first), each showing its newest messages and tool calls.
`tab` moves between tiles, `enter` opens a tile's session."""

from __future__ import annotations

from typing import ClassVar

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Grid
from textual.widgets import Static

from mission_control import fmt
from mission_control.model import LIFECYCLE, Call, Event, Run, Step, Update
from mission_control.screens.agents import RUNNER
from mission_control.screens.base import View
from mission_control.widgets import label

MAX_TILES = 6


class Tile(Static, can_focus=True):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "open", "Open session")]

    key: str | None = None

    def action_open(self) -> None:
        if self.key is not None:
            self.app.open_session(self.key)

    def on_click(self) -> None:
        self.action_open()


def pick(run: Run) -> list[Step]:
    """Up to MAX_TILES steps: every running one, then the most recent finished ones, in start order."""
    steps = list(run.steps.values())
    running = [s for s in steps if not s.done]
    finished = [s for s in steps if s.done][::-1][: max(0, MAX_TILES - len(running))]
    chosen = set(map(id, running[-MAX_TILES:] + finished))
    return [s for s in steps if id(s) in chosen]


def tile_title(step: Step | None, run: Run) -> Text:
    title = Text()
    if step is None:
        calls = [i for i in run.runner_items if isinstance(i, Call)]
        title.append("⚙ runner", style="bold")
        title.append(f"  code · {len(calls)} calls", style="dim")
        return title
    title.append_text(fmt.status_icon(step.status))
    title.append(f" {step.name}", style="bold")
    title.append(f"  {step.vendor} {step.model}", style="dim")
    title.append(f"  {fmt.duration(step.seconds)}" if step.done else "  running", style="dim")
    return title


def _one_line(text: Text) -> Text:
    text.no_wrap, text.overflow = True, "ellipsis"
    return text


class LiveScreen(View):
    def body(self) -> ComposeResult:
        with Grid(id="live"):
            for _ in range(MAX_TILES + 1):  # + the runner's own work
                yield Tile(classes="tile")

    def redraw(self, run: Run, updates: list[Update]) -> None:
        tiles = list(self.query(Tile))
        runner_items = ([i for i in run.runner_items if not (isinstance(i, Event) and i.name in LIFECYCLE)]
                        if any(isinstance(i, Call) for i in run.runner_items) else [])
        entries: list[tuple[str, Step | None, list]] = [(s.name, s, s.items) for s in pick(run)]
        if runner_items:
            entries.insert(0, (RUNNER, None, runner_items))
        grid = self.query_one("#live", Grid)
        grid.styles.grid_size_columns = 3 if len(entries) > 4 else 2 if len(entries) > 1 else 1
        for tile, entry in zip(tiles, entries + [None] * (len(tiles) - len(entries)), strict=True):
            tile.display = entry is not None
            if entry is None:
                continue
            key, step, items = entry
            tile.key = key
            tile.border_title = tile_title(step, run)
            lines = max(3, (tile.size.height or 14) - 1)
            shown = [_one_line(label(item)) for item in items[-lines:]]
            tile.update(Group(*shown) if shown else Text("waiting for the first event…", style="dim"))
