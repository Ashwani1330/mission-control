"""Mission Control: watch pipeline runs live. Read-only; it never touches a run.

Each screen answers one question (Textual "modes", one per key). The app owns
the data: it polls the traces and tells the visible screen what changed."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType

from mission_control import fmt, launch, settings, themes
from mission_control.model import Run
from mission_control.screens.agents import AgentsScreen, SessionScreen
from mission_control.screens.base import View
from mission_control.screens.models import ModelsScreen
from mission_control.screens.new_mission import NewMissionScreen
from mission_control.screens.overview import OverviewScreen
from mission_control.screens.plugins import PluginsScreen
from mission_control.screens.results import ResultsScreen
from mission_control.screens.runs import RunsScreen
from mission_control.store import RunStore

POLL_SECONDS = 0.5


class MissionControl(App):
    TITLE = "Mission Control"
    CSS_PATH = "app.tcss"
    MODES: ClassVar[dict[str, type[View]]] = {
        "overview": OverviewScreen, "runs": RunsScreen, "agents": AgentsScreen,
        "plugins": PluginsScreen, "models": ModelsScreen, "results": ResultsScreen,
    }
    DEFAULT_MODE = "overview"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("o", "switch_mode('overview')", "Overview"),
        Binding("r", "switch_mode('runs')", "Runs"),
        Binding("a", "switch_mode('agents')", "Agents"),
        Binding("p", "switch_mode('plugins')", "Plugins"),
        Binding("m", "switch_mode('models')", "Models"),
        Binding("f", "switch_mode('results')", "Files"),
        Binding("t", "next_theme", "Theme"),
        Binding("n", "new_mission", "New mission"),
        Binding("escape", "back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, runs_dir: Path, config_path: Path | None = None):
        super().__init__()
        self.config: launch.Config | None = None
        self.config_problem: str | None = None
        found = launch.find_config(runs_dir, config_path)
        if found is not None:
            try:
                self.config = launch.load_config(found)
            except launch.LaunchError as exc:
                self.config_problem = str(exc)
        self.launches: list[launch.Launch] = []
        self.store = RunStore(runs_dir)
        self.store.poll()
        self.selected: Run | None = self.store.newest()

    def on_mount(self) -> None:
        for theme in themes.THEMES:
            self.register_theme(theme)
        saved = settings.load().get("theme")
        self.theme = saved if saved in themes.BY_NAME else themes.DEFAULT
        self.set_interval(POLL_SECONDS, self.poll)

    def watch_theme(self, name: str) -> None:
        theme = themes.BY_NAME.get(name)
        if theme is not None:
            fmt.use_theme(theme.accent or fmt.ACCENT, theme.dark)
        if isinstance(self.screen, View):
            self.screen.refresh_view([])

    def action_next_theme(self) -> None:
        names = [t.name for t in themes.THEMES]
        self.theme = names[(names.index(self.theme) + 1) % len(names)] if self.theme in names else names[0]
        settings.save(theme=self.theme)
        self.notify(f"theme: {self.theme}", timeout=2)

    def poll(self) -> None:
        changed = {id(run): updates for run, updates in self.store.poll()}
        if self.selected is None:
            self.selected = self.store.newest()
        self._follow_launches()
        if not isinstance(self.screen, View):
            return
        if changed:
            self.screen.refresh_view(changed.get(id(self.selected), []) if self.selected else [])
        elif self.selected is not None and self.selected.status == "running":
            self.screen.tick()  # nothing new: only the clock moved

    # ------------------------------------------------------------ launching

    def action_new_mission(self) -> None:
        self.push_screen(NewMissionScreen(self.config, self.config_problem))

    def start_launch(self, workflow: str, mission: dict) -> None:
        if self.config is None:
            raise launch.LaunchError("no mission-control.toml loaded")
        self.launches.append(launch.launch(self.config, workflow, mission))
        self.notify(f"Launched {mission['name']}; waiting for its run to appear…", timeout=4)

    def _follow_launches(self) -> None:
        """Open a launched mission's run as soon as it appears; report runners that die first."""
        for pending in list(self.launches):
            run = next((r for r in self.store.runs.values()
                        if r.mission == pending.slug and r.started and r.started.timestamp() >= pending.started - 5),
                       None)
            if run is not None:
                self.launches.remove(pending)
                self.select_run(run)
                self.notify(f"{pending.mission['name']} is running", timeout=3)
            elif pending.process.poll() is not None:
                self.launches.remove(pending)
                self.notify(f"{pending.mission['name']} stopped before starting (exit {pending.process.returncode}):\n"
                            f"{launch.log_tail(pending.log, 400)}", severity="error", timeout=15)

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
