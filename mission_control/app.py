"""Mission Control: watch pipeline runs live. Read-only; it never touches a run.

Each screen answers one question (Textual "modes", one per key). The app owns
the data: it polls the traces and tells the visible screen what changed."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType

from mission_control import control, fmt, launch, settings, themes
from mission_control.model import Run
from mission_control.runlist import RunList
from mission_control.screens.agents import AgentsScreen, SessionScreen
from mission_control.screens.base import View
from mission_control.screens.dialogs import AskText, Confirm, KeysScreen
from mission_control.screens.home import HomeScreen
from mission_control.screens.live import LiveScreen
from mission_control.screens.models import ModelsScreen
from mission_control.screens.new_mission import NewMissionScreen
from mission_control.screens.overview import OverviewScreen
from mission_control.screens.plugins import PluginsScreen
from mission_control.screens.results import ResultsScreen
from mission_control.store import RunStore

POLL_SECONDS = 0.5


class MissionControl(App):
    TITLE = "Mission Control"
    CSS_PATH = "app.tcss"
    MODES: ClassVar[dict[str, type[View]]] = {
        "home": HomeScreen, "overview": OverviewScreen, "agents": AgentsScreen,
        "plugins": PluginsScreen, "models": ModelsScreen, "results": ResultsScreen, "live": LiveScreen,
    }
    DEFAULT_MODE = "home"  # on_mount moves to the overview when a run is live at start
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "new_mission", "New"),
        Binding("o", "open('overview')", "Overview"),
        Binding("l", "open('live')", "Live"),
        Binding("a", "open('agents')", "Agents"),
        Binding("p", "open('plugins')", "Plugins"),
        Binding("f", "open('results')", "Files"),
        Binding("m", "open('models')", "Models", show=False),
        Binding("r", "focus_runs", "Runs", show=False),
        Binding("b", "toggle_run_list", "Hide list", show=False),
        Binding("t", "next_theme", "Theme", show=False),
        Binding("P", "pause", "Pause"),  # P, X, M only show while the selected run is live (check_action)
        Binding("X", "stop", "Stop"),
        Binding("M", "note", "Note"),
        Binding("question_mark", "help", "Keys"),
        Binding("escape", "back", "Back", show=False),
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
        # Open on a live run if there is one; otherwise on a clean home screen.
        live = [r for r in self.store.runs.values() if r.status in ("running", "paused")]
        self.selected: Run | None = max(live, key=lambda r: r.started.timestamp() if r.started else 0.0,
                                        default=None)
        self.show_run_list = True

    def on_mount(self) -> None:
        for theme in themes.THEMES:
            self.register_theme(theme)
        saved = settings.load().get("theme")
        self.theme = saved if saved in themes.BY_NAME else themes.DEFAULT
        if self.selected is not None:
            self.switch_mode("overview")
        self.set_interval(POLL_SECONDS, self.poll)

    def watch_theme(self, name: str) -> None:
        theme = themes.BY_NAME.get(name)
        if theme is not None:
            fmt.use_theme(theme.accent or fmt.ACCENT, theme.secondary or fmt.SECONDARY, theme.dark)
        if isinstance(self.screen, View):
            self.screen.refresh_view([])

    def action_next_theme(self) -> None:
        names = [t.name for t in themes.THEMES]
        self.theme = names[(names.index(self.theme) + 1) % len(names)] if self.theme in names else names[0]
        settings.save(theme=self.theme)
        self.notify(f"theme: {self.theme}", timeout=2)

    def poll(self) -> None:
        changed = {id(run): updates for run, updates in self.store.poll()}
        self._follow_launches()
        if not isinstance(self.screen, View):
            return
        if changed:
            self.refresh_bindings()
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

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Hide the steering keys unless the selected run is live."""
        if action in ("pause", "stop", "note"):
            return self.selected is not None and self.selected.status in ("running", "paused")
        return True

    def action_help(self) -> None:
        self.push_screen(KeysScreen())

    # ------------------------------------------------------------ steering (see control.py)

    def _live_run(self) -> Run | None:
        run = self.selected
        if run is None or run.status not in ("running", "paused"):
            self.notify("The selected run is not running.", severity="warning", timeout=3)
            return None
        return run

    def action_pause(self) -> None:
        run = self._live_run()
        if run is None:
            return
        paused = control.read(run.path).get("state") == "paused"
        control.write(run.path, state="running" if paused else "paused")
        self.notify("Resuming." if paused else "Pause requested: the run waits before its next step.", timeout=4)

    def action_stop(self) -> None:
        run = self._live_run()
        if run is None:
            return

        def stop(confirmed: bool | None) -> None:
            if confirmed:
                control.write(run.path, state="stopped")
                self.notify("Stop requested: the run ends before its next step.", timeout=4)
        self.push_screen(Confirm(f"Stop {run.mission}? The current step finishes first."), stop)

    def action_note(self) -> None:
        run = self._live_run()
        if run is None:
            return

        def send(text: str | None) -> None:
            if text:
                control.write(run.path, note=text)
                self.notify("Note queued for the next agent step.", timeout=3)
        self.push_screen(AskText("Note for the next agent step", "e.g. focus on medical devices"), send)

    # ------------------------------------------------------------ navigation

    def select_run(self, run: Run) -> None:
        """Point every screen at `run`; from home (or a pushed screen), go to its overview."""
        self.selected = run
        self.refresh_bindings()  # the steering keys depend on the selected run
        if self.current_mode == "home" or not isinstance(self.screen, View):
            self.switch_mode("overview")  # the screen redraws itself when it mounts or resumes
        elif isinstance(self.screen, View):
            self.screen.refresh_view([])

    def action_open(self, mode: str) -> None:
        if self.selected is None:
            self.notify("Pick a run from the list first (r), or start one (n).", timeout=3)
            self.action_focus_runs()
            return
        self.switch_mode(mode)

    def action_focus_runs(self) -> None:
        self.show_run_list = True
        if isinstance(self.screen, View):
            self.screen.refresh_view([])
            self.screen.query_one(RunList).focus()

    def action_toggle_run_list(self) -> None:
        self.show_run_list = not self.show_run_list
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
        elif self.current_mode not in ("overview", "home"):
            self.switch_mode("overview")
        elif self.current_mode == "overview":
            self.switch_mode("home")
