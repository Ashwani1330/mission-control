"""What every screen shares: the run header on top, the run list on the left, the key bar at the
bottom, and a redraw hook."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, OptionList

from mission_control.model import Run, Update
from mission_control.runlist import RunList
from mission_control.widgets import RunHeader

if TYPE_CHECKING:
    from mission_control.app import MissionControl


class View(Screen):
    """A screen over the app's selected run. The app calls `refresh_view` after every poll."""

    app: MissionControl
    TITLES: ClassVar[dict[str, str]] = {}  # selector -> pane title

    def compose(self) -> ComposeResult:
        yield RunHeader(id="header")
        with Horizontal(id="frame"):
            yield RunList(id="run-list")
            with Vertical(id="main"):
                yield from self.body()
        yield Footer()

    def body(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        for widget in self.query(RunList):
            widget.border_title = "Runs · r"
        for selector, title in self.TITLES.items():
            for widget in self.query(selector):  # tolerate a screen torn down while mounting
                widget.border_title = title
        self.refresh_view([])

    def on_screen_resume(self) -> None:
        self.refresh_view([])

    def refresh_view(self, updates: list[Update]) -> None:
        if not self.is_mounted:
            return
        run = self.app.selected
        self.query_one(RunHeader).show(run, self.app.store.root)
        runs = self.query_one(RunList)
        runs.display = self.app.show_run_list
        runs.show(list(self.app.store.runs.values()), run)
        if run is not None:
            self.redraw(run, updates)

    def tick(self) -> None:
        """Called each poll with no new events while the run is live: just keep the header's clock moving."""
        if self.is_mounted:
            self.query_one(RunHeader).show(self.app.selected, self.app.store.root)

    def redraw(self, run: Run, updates: list[Update]) -> None:
        """Bring the body up to date. `updates` are this poll's changes to `run` (maybe none)."""

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if isinstance(event.option_list, RunList) and event.option.id:
            run = self.app.store.runs_by_key.get(event.option.id)
            if run is not None:
                self.app.select_run(run)
