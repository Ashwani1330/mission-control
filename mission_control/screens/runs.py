"""Runs: every run on disk, newest first. Enter makes one the selected run."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable

from mission_control import fmt
from mission_control.model import Run, Update
from mission_control.screens.base import View
from mission_control.widgets import Detail, Row, make_table, sync_table


def run_rows(runs: list[Run]) -> list[Row]:
    rows = []
    for run in sorted(runs, key=lambda r: r.started.timestamp() if r.started else 0.0, reverse=True):
        status = run.status
        if status == "done" and run.verdict not in (None, "PASS", "AWAITING_APPROVAL"):
            status = "attention"  # finished, but needs a human look
        rows.append((str(run.path), [fmt.status_icon(status), run.workflow, run.mission,
                                     fmt.clock(run.started, "%m-%d %H:%M"), fmt.duration(run.seconds),
                                     run.verdict or run.status, fmt.money(run.cost_usd)]))
    return rows


class RunsScreen(View):
    TITLES: ClassVar[dict[str, str]] = {"#runs": "Runs · enter selects", "#run-detail": "Run"}

    def body(self) -> ComposeResult:
        with Horizontal():
            yield make_table("", "workflow", "mission", "started", "took", "result", "cost", id="runs")
            yield Detail(id="run-detail")

    def redraw(self, run: Run, updates: list[Update]) -> None:
        sync_table(self.query_one("#runs", DataTable), run_rows(list(self.app.store.runs.values())))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        run = self.app.store.runs_by_key.get(event.row_key.value)
        if run is not None:
            self.query_one(Detail).show(run, run)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        run = self.app.store.runs_by_key.get(event.row_key.value)
        if run is not None:
            self.app.select_run(run)
