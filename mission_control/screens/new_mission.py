"""New mission: describe the work, let an agent draft the mission, review it, pick models, launch."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Label, Select, Static, TextArea

from mission_control import fmt
from mission_control.launch import Config, LaunchError, describe, draft
from mission_control.screens.mission_form import MissionForm

if TYPE_CHECKING:
    from mission_control.app import MissionControl

HELP = """Add a mission-control.toml next to your runs folder (or pass --config) listing the
workflows Mission Control may start:

[models]
choices = ["codex/gpt-5.6-sol", "claude/claude-opus-5-5"]

[[workflow]]
name = "research"
draft = ["python3", "-m", "workflows.research.runner", "--draft", "{request}", "--out", "{mission}"]
run = ["python3", "-m", "workflows.research.runner", "{mission}"]"""


class NewMissionScreen(Screen):
    app: MissionControl
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+g", "draft", "Draft", priority=True),
        Binding("ctrl+l", "launch", "Launch", priority=True),
        Binding("escape", "app.pop_screen", "Back", priority=True),
    ]

    def __init__(self, config: Config | None, problem: str | None = None):
        super().__init__()
        self.config = config
        self.problem = problem
        self._drafting_since: float | None = None
        self._options: dict[str, dict[str, Any]] = {}  # workflow -> described options
        self._form_for: str | None = None  # the workflow the form was built for

    def compose(self) -> ComposeResult:
        title = Text()
        title.append("▲ New mission", style=f"bold {fmt.ACCENT}")
        title.append("   describe the work · pick options · draft · review · launch", style="dim")
        yield Static(title, id="nm-title")
        if self.config is None or not self.config.workflows:
            yield Static(self.problem or HELP, id="nm-help", classes="panel")
            yield Footer(compact=True)
            return
        workflows = [(w.name, w.name) for w in self.config.workflows.values()]
        with Horizontal(id="nm-body"):
            with Vertical(id="nm-left"):
                with Vertical(id="nm-workflow-panel", classes="panel"):
                    yield Select(workflows, value=workflows[0][1], allow_blank=False, compact=True, id="nm-workflow")
                    yield Static(id="nm-workflow-about")
                yield TextArea(id="nm-request", soft_wrap=True, compact=True, classes="panel",
                               placeholder="Describe the mission in plain words: the goal, what the result "
                                           "should contain, anything to avoid.")
                yield MissionForm(id="nm-options", classes="panel")
            with Vertical(id="nm-right"):
                yield TextArea(id="nm-mission", soft_wrap=True, show_line_numbers=True, compact=True, classes="panel",
                               placeholder="The drafted mission appears here (ctrl+g). Edit anything before launching.")
                yield VerticalScroll(id="nm-models", classes="panel")
        with Horizontal(id="nm-actions"):
            yield Static(id="nm-status")
            yield Button("Draft  ctrl+g", id="nm-draft", compact=True, classes="action")
            yield Button("Launch  ctrl+l", id="nm-launch", compact=True, classes="action go", disabled=True)
        yield Footer(compact=True)

    def on_mount(self) -> None:
        if self.config is not None and self.config.workflows:
            titles = {"#nm-workflow-panel": "1 · Workflow", "#nm-request": "2 · Request", "#nm-options": "3 · Options",
                      "#nm-mission": "4 · Mission", "#nm-models": "5 · Models"}
            for selector, text in titles.items():
                self.query_one(selector).border_title = text
            self.query_one("#nm-mission").border_subtitle = "JSON · the form edits it for you"
            self.query_one("#nm-models").border_subtitle = "model · effort per role"
            self._about(self.query_one("#nm-workflow", Select).value)
            self.query_one("#nm-request", TextArea).focus()
            self.set_interval(1, self._tick)
            self._describe(self.query_one("#nm-workflow", Select).value)

    # ------------------------------------------------------------ options form

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "nm-workflow":
            self._about(event.value)
            self._describe(event.value)

    def _about(self, workflow: str) -> None:
        about = self.config.workflows[workflow].description if self.config else ""
        self.query_one("#nm-workflow-about", Static).update(Text(about, style="dim"))

    @work(thread=True, exclusive=True, group="describe")
    def _describe(self, workflow: str) -> None:
        if workflow not in self._options:
            try:
                self._options[workflow] = describe(self.config, workflow)
            except LaunchError as exc:
                self.app.call_from_thread(self._status, str(exc), "red")
                self._options[workflow] = {"selects": [], "choices": [], "numbers": []}
        self.app.call_from_thread(self._show_options, workflow)

    def _show_options(self, workflow: str) -> None:
        if workflow == self._form_for:
            return
        self._form_for = workflow
        form = self.query_one(MissionForm)
        form.build(self._options[workflow])
        self._show_models(self._options[workflow].get("models", {}))  # offered before any draft
        mission = self._mission()
        if mission is not None:
            self.call_after_refresh(form.load, mission)

    def on_mission_form_changed(self, event: MissionForm.Changed) -> None:
        mission = self._mission()
        if mission is None:
            return  # no draft yet: the choice is remembered and applied to the draft
        self.query_one(MissionForm).apply(mission, {event.key})
        self._set_mission(mission)

    def _mission(self) -> dict[str, Any] | None:
        text = self.query_one("#nm-mission", TextArea).text.strip()
        try:
            value = json.loads(text) if text else None
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def _set_mission(self, mission: dict[str, Any]) -> None:
        self.query_one("#nm-mission", TextArea).load_text(json.dumps(mission, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------ draft

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nm-draft":
            self.action_draft()
        elif event.button.id == "nm-launch":
            self.action_launch()

    def action_draft(self) -> None:
        if self.config is None or self._drafting_since is not None:
            return
        request = self.query_one("#nm-request", TextArea).text.strip()
        if not request:
            self._status("Describe the mission first.", "yellow")
            return
        self._drafting_since = time.monotonic()
        self.query_one("#nm-draft", Button).disabled = True
        context = self.query_one(MissionForm).value(("context",))
        self._draft(self.query_one("#nm-workflow", Select).value, request, context)

    @work(thread=True, exclusive=True, group="draft")
    def _draft(self, workflow: str, request: str, context: str | None) -> None:
        try:
            mission = draft(self.config, workflow, request, context)
        except (LaunchError, ValueError) as exc:
            self.app.call_from_thread(self._draft_failed, str(exc))
        else:
            self.app.call_from_thread(self._drafted, mission)

    def _tick(self) -> None:
        if self._drafting_since is not None:
            self._status(f"Drafting… {time.monotonic() - self._drafting_since:.0f}s", "yellow")

    def _draft_failed(self, error: str) -> None:
        self._drafting_since = None
        self.query_one("#nm-draft", Button).disabled = False
        self._status(f"Draft failed: {error}", "red")

    def _drafted(self, mission: dict[str, Any]) -> None:
        seconds = time.monotonic() - (self._drafting_since or time.monotonic())
        self._drafting_since = None
        self.query_one("#nm-draft", Button).disabled = False
        models = mission.pop("models", {}) or {}
        form = self.query_one(MissionForm)
        form.apply(mission, form.touched | form.select_keys)  # what you chose before drafting wins
        self._set_mission(mission)
        form.load(mission)
        if not self.query(".nm-model-row"):  # keep models the user already picked
            self._show_models(models)
        self.query_one("#nm-launch", Button).disabled = False
        self._status(f"Drafted in {seconds:.0f}s. Review it, pick models, then launch.", "green")

    def _show_models(self, models: dict[str, dict[str, str]]) -> None:
        box = self.query_one("#nm-models", VerticalScroll)
        box.remove_children()
        choices = list(self.config.model_choices) if self.config else []
        for role, spec in models.items():
            current = f"{spec.get('vendor')}/{spec.get('model')}"
            options = [(c, c) for c in dict.fromkeys([current, *choices])]
            efforts = [(e, e) for e in dict.fromkeys([spec.get("effort", "high"), *self.config.efforts])]
            box.mount(Horizontal(
                Label(role, classes="nm-role"),
                Select(options, value=current, allow_blank=False, compact=True, id=f"model-{role}",
                       classes="nm-model"),
                Select(efforts, value=spec.get("effort", "high"), allow_blank=False, compact=True,
                       id=f"effort-{role}", classes="nm-effort"),
                classes="nm-model-row", name=role))

    # ------------------------------------------------------------ launch

    def action_launch(self) -> None:
        if self.config is None or self.query_one("#nm-launch", Button).disabled:
            return
        try:
            mission = json.loads(self.query_one("#nm-mission", TextArea).text)
        except json.JSONDecodeError as exc:
            self._status(f"The mission is not valid JSON: {exc}", "red")
            return
        if not isinstance(mission, dict) or not mission.get("name"):
            self._status("The mission needs a name.", "red")
            return
        models = {}
        for row in self.query(".nm-model-row"):
            role = str(row.name)
            vendor, _, model = str(row.query_one(".nm-model", Select).value).partition("/")
            models[role] = {"vendor": vendor, "model": model, "effort": str(row.query_one(".nm-effort", Select).value)}
        if models:
            mission["models"] = models
        workflow = self.query_one("#nm-workflow", Select).value
        try:
            self.app.start_launch(workflow, mission)
        except LaunchError as exc:
            self._status(str(exc), "red")
            return
        self.app.pop_screen()

    def _status(self, text: str, style: str) -> None:
        self.query_one("#nm-status", Static).update(Text(text, style=style))
