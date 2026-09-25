"""Mission Control: watch pipeline runs live. Read-only; it never touches a run.

Each screen answers one question (Textual "modes", one per key). The app owns
the data: it polls the traces and tells the visible screen what changed."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType

from mission_control.model import Run
from mission_control.screens.agents import AgentsScreen, SessionScreen
from mission_control.screens.base import View
from mission_control.screens.models import ModelsScreen
from mission_control.screens.overview import OverviewScreen
from mission_control.screens.plugins import PluginsScreen
from mission_control.screens.runs import RunsScreen
from mission_control.store import RunStore

POLL_SECONDS = 0.5


class MissionControl(App):
    TITLE = "Mission Control"
    CSS_PATH = "app.tcss"
    MODES: ClassVar[dict[str, type[View]]] = {
        "overview": OverviewScreen, "runs": RunsScreen, "agents": AgentsScreen,
        "plugins": PluginsScreen, "models": ModelsScreen,
    }
    DEFAULT_MODE = "overview"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("o", "switch_mode('overview')", "Overview"),
        Binding("r", "switch_mode('runs')", "Runs"),
        Binding("a", "switch_mode('agents')", "Agents"),
        Binding("p", "switch_mode('plugins')", "Plugins"),
        Binding("m", "switch_mode('models')", "Models"),
        Binding("escape", "back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, runs_dir: Path):
        super().__init__()
        self.store = RunStore(runs_dir)
        self.store.poll()
        self.selected: Run | None = self.store.newest()

    def on_mount(self) -> None:
        self.set_interval(POLL_SECONDS, self.poll)

    def poll(self) -> None:
        changed = {id(run): updates for run, updates in self.store.poll()}
        if self.selected is None:
            self.selected = self.store.newest()
        updates = changed.get(id(self.selected), []) if self.selected else []
        running = self.selected is not None and self.selected.status == "running"
        if isinstance(self.screen, View) and (changed or running):
            self.screen.refresh_view(updates)

    # ------------------------------------------------------------ navigation

    def select_run(self, run: Run) -> None:
        self.selected = run
        self.switch_mode("overview")
        if isinstance(self.screen, View):
            self.screen.refresh_view([])

    def open_session(self, key: str | None) -> None:
        if key is not None:
            self.push_screen(SessionScreen(key))

    def open_plugin(self, name: str | None) -> None:
        self.switch_mode("plugins")
        if isinstance(self.screen, PluginsScreen):
            self.screen.show_plugin(name)

    def action_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()
        elif self.current_mode != "overview":
            self.switch_mode("overview")
