"""Home: the clean view Mission Control opens on when nothing is running."""

from __future__ import annotations

from datetime import datetime

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Center, Middle
from textual.widgets import Static

from mission_control import fmt
from mission_control.model import Run, Update
from mission_control.screens.base import View

KEYS = (("n", "start a new mission"), ("r", "open a run from the list"), ("b", "hide / show the list"),
        ("t", "change the theme"), ("q", "quit"))


class HomeScreen(View):
    def body(self) -> ComposeResult:
        with Middle(), Center():
            yield Static(id="home")

    def refresh_view(self, updates: list[Update]) -> None:
        super().refresh_view(updates)
        self.query_one("#home", Static).update(self._welcome())

    def redraw(self, run: Run, updates: list[Update]) -> None:
        pass  # home shows the same thing whichever run is selected

    def _welcome(self) -> Table:
        runs = list(self.app.store.runs.values())
        today = datetime.now().astimezone().date()
        running = [r for r in runs if r.status in ("running", "paused")]
        spent_today = sum(r.cost_usd for r in runs if r.started and r.started.astimezone().date() == today)
        grid = Table.grid(padding=(0, 2))
        grid.add_column(justify="right", style=f"bold {fmt.ACCENT}")
        grid.add_column()
        grid.add_row("▲", Text("Mission Control", style="bold"))
        grid.add_row("", Text(str(self.app.store.root), style="dim"))
        grid.add_row("", "")
        grid.add_row("", Text(f"{len(runs)} runs · {len(running)} running · "
                              f"{fmt.money(spent_today) if spent_today else '$0'} spent today"))
        grid.add_row("", "")
        for key, what in KEYS:
            if key == "n" and self.app.config is None:
                what = "start a new mission (add a mission-control.toml first)"
            grid.add_row(key, what)
        return grid
