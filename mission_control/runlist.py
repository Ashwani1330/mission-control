"""The run list beside every screen, like the chat list in an LLM app: running first, then
today, then earlier. Picking a run points every screen at it."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from mission_control import fmt
from mission_control.model import Run

GROUPS = ("Running", "Needs you", "Today", "Earlier")
AWAITING = "AWAITING_APPROVAL"
NAME_WIDTH = 27  # fits the list's width next to the status icon
ATTENTION = {"NEEDS_HUMAN_REVIEW", "STOP", "REVISE"}


def group_of(run: Run, today: datetime) -> str:
    if run.status in ("running", "paused"):
        return "Running"
    if run.status == "done" and run.verdict == AWAITING:
        return "Needs you"
    if run.started and run.started.astimezone().date() == today.date():
        return "Today"
    return "Earlier"


def status_of(run: Run) -> str:
    if run.status == "done" and run.verdict == AWAITING:
        return "awaiting"
    return "attention" if run.status == "done" and run.verdict in ATTENTION else run.status


def prompt(run: Run, today: datetime) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append_text(fmt.status_icon(status_of(run)))
    name = run.mission if len(run.mission) <= NAME_WIDTH else run.mission[: NAME_WIDTH - 1] + "…"
    text.append(f" {name}\n", style="bold")
    when = fmt.clock(run.started, "%H:%M" if group_of(run, today) != "Earlier" else "%b %d")
    meta = [run.workflow, when, fmt.money(run.cost_usd) if run.cost_usd else ""]  # the icon shows the result
    text.append("  " + " · ".join(m for m in meta if m), style="dim")
    return text


def ordered(runs: list[Run], today: datetime) -> list[tuple[str, list[Run]]]:
    newest = sorted(runs, key=lambda r: r.started.timestamp() if r.started else 0.0, reverse=True)
    return [(g, [r for r in newest if group_of(r, today) == g]) for g in GROUPS]


class RunList(OptionList):
    """Rebuilt only when runs appear or move between groups; otherwise prompts are patched in place."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._layout: list[str] = []

    def show(self, runs: list[Run], selected: Run | None) -> None:
        today = datetime.now().astimezone()
        groups = ordered(runs, today)
        layout = [f"#{g}" if not members else f"#{g}|" + "|".join(str(r.path) for r in members)
                  for g, members in groups]
        if layout != self._layout:
            keep = self._current() if self.has_focus else (str(selected.path) if selected else None)
            self._layout = layout
            self.clear_options()
            for group, members in groups:
                if not members:
                    continue
                self.add_option(Option(Text(group.upper(), style="bold dim"), disabled=True))
                self.add_options(Option(prompt(r, today), id=str(r.path)) for r in members)
            self._move_to(keep)
            return
        for _, members in groups:
            for run in members:
                self.replace_option_prompt(str(run.path), prompt(run, today))
        if not self.has_focus and selected is not None:
            self._move_to(str(selected.path))

    def _current(self) -> str | None:
        if self.highlighted is None:
            return None
        return self.get_option_at_index(self.highlighted).id

    def _move_to(self, option_id: str | None) -> None:
        if option_id is None:
            return
        try:
            self.highlighted = self.get_option_index(option_id)
        except Exception:  # noqa: BLE001, S110 — the run may have gone; leave the cursor where it is
            pass
