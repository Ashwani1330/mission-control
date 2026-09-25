"""What every screen shares: the run header on top, the key bar at the bottom, and a redraw hook."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer

from mission_control.model import Run, Update
from mission_control.widgets import RunHeader

if TYPE_CHECKING:
    from mission_control.app import MissionControl


class View(Screen):
    """A screen over the app's selected run. The app calls `refresh_view` after every poll."""

    app: MissionControl
    TITLES: ClassVar[dict[str, str]] = {}  # selector -> pane title

    def compose(self) -> ComposeResult:
        yield RunHeader(id="header")
        yield from self.body()
        yield Footer()

    def body(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        for selector, title in self.TITLES.items():
            self.query_one(selector).border_title = title
        self.refresh_view([])

    def on_screen_resume(self) -> None:
        self.refresh_view([])

    def refresh_view(self, updates: list[Update]) -> None:
        run = self.app.selected
        self.query_one(RunHeader).show(run, self.app.store.root)
        if run is not None:
            self.redraw(run, updates)

    def tick(self) -> None:
        """Called each poll with no new events while the run is live: just keep the header's clock moving."""
        self.query_one(RunHeader).show(self.app.selected, self.app.store.root)

    def redraw(self, run: Run, updates: list[Update]) -> None:
        """Bring the body up to date. `updates` are this poll's changes to `run` (maybe none)."""
