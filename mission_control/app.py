"""Mission Control: watch pipeline runs live. Read-only; it never touches a run."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Tree

from mission_control.model import Run
from mission_control.store import RunStore
from mission_control.widgets import Detail, RunTable, Timeline

POLL_SECONDS = 0.5


class MissionControl(App):
    TITLE = "Mission Control"
    CSS_PATH = "app.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("e", "expand_all", "Expand all"),
        Binding("c", "collapse_all", "Collapse all"),
    ]

    def __init__(self, runs_dir: Path):
        super().__init__()
        self.store = RunStore(runs_dir)
        self.selected: Run | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield RunTable(id="runs")
            yield Timeline(id="timeline")
            yield Detail(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        for pane, title in (("#runs", "Runs"), ("#timeline", "Timeline"), ("#detail", "Detail")):
            self.query_one(pane).border_title = title
        self.sub_title = f"{self.store.root} · following"
        self.poll()
        self.set_interval(POLL_SECONDS, self.poll)
        self.query_one(RunTable).focus()

    def poll(self) -> None:
        changed = self.store.poll()
        table = self.query_one(RunTable)
        table.show(list(self.store.runs.values()))
        self._select(table.current_key)  # sorting can put a different run under the cursor
        for run, updates in changed:
            if run is self.selected:
                self.query_one(Timeline).apply(updates)
                self.query_one(Detail).refresh_if_showing([u.item for u in updates], run)

    # ------------------------------------------------------------ selection (messages up from the panes)

    def on_data_table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        # Read the cursor, not the event: a queued event can predate a re-sort.
        self._select(self.query_one(RunTable).current_key)

    def _select(self, key: str | None) -> None:
        run = self.store.runs.get(Path(key)) if key else None
        if run is None or run is self.selected:
            return
        self.selected = run
        self.query_one(Timeline).show(run)
        self.query_one(Detail).show(run, run)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.data is not None and self.selected is not None:
            self.query_one(Detail).show(event.node.data, self.selected)

    # ------------------------------------------------------------ actions

    def action_toggle_follow(self) -> None:
        timeline = self.query_one(Timeline)
        timeline.follow = not timeline.follow
        self.sub_title = f"{self.store.root}" + (" · following" if timeline.follow else "")

    def action_expand_all(self) -> None:
        self.query_one(Timeline).root.expand_all()

    def action_collapse_all(self) -> None:
        timeline = self.query_one(Timeline)
        for node in timeline.root.children:
            node.collapse_all()
