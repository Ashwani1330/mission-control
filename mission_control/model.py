"""Fold trace events (docs/trace-format.md) into a run: steps, tool calls, events. No Textual here.

A run's timeline is a list of entries; a Step holds its own entries. Every
`Run.apply` returns an `Update` saying which item changed, so a view can patch
itself instead of rebuilding."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Older runs used "mission.*" for the run lifecycle and "<role>.started" for steps.
LIFECYCLE = {"run.started": "started", "run.completed": "completed", "run.failed": "failed", "run.stopped": "stopped",
             "mission.started": "started", "mission.completed": "completed", "mission.failed": "failed"}
STAMP = re.compile(r"-\d{8}T\d{6}Z$")
TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens")


@dataclass(eq=False)
class Event:
    """Anything shown as-is: messages, warnings, workflow-specific events."""
    name: str
    time: datetime | None
    fields: dict[str, Any]


@dataclass(eq=False)
class Call:
    call_id: str
    tool: str
    time: datetime | None
    input: Any = None
    step: str | None = None  # None: made by the runner's own code
    output: Any = None
    error: Any = None
    done: bool = False
    ended: datetime | None = None
    reported_seconds: float | None = None

    @property
    def seconds(self) -> float | None:
        if self.reported_seconds is not None:
            return self.reported_seconds
        return _elapsed(self.time, self.ended)

    @property
    def status(self) -> str:
        return "failed" if self.error else "done" if self.done else "running"


@dataclass(eq=False)
class Step:
    name: str
    time: datetime | None
    fields: dict[str, Any] = field(default_factory=dict)   # from step.started: role, vendor, model, ...
    usage: dict[str, Any] = field(default_factory=dict)    # from step.completed
    live: dict[str, float] = field(default_factory=dict)   # usage events seen while running
    session: dict[str, Any] = field(default_factory=dict)  # from the session event
    items: list[Call | Event] = field(default_factory=list)
    done: bool = False
    ended: datetime | None = None

    @property
    def role(self) -> str:
        return str(self.fields.get("role") or "")

    @property
    def vendor(self) -> str:
        return str(self.fields.get("vendor") or self.usage.get("vendor") or "")

    @property
    def model(self) -> str:
        return str(self.fields.get("model") or self.usage.get("model") or "")

    @property
    def error(self) -> Any:
        return self.usage.get("error")

    @property
    def status(self) -> str:
        return "failed" if self.error else "done" if self.done else "running"

    @property
    def seconds(self) -> float | None:
        return self.usage.get("seconds") or _elapsed(self.time, self.ended)

    @property
    def tokens(self) -> dict[str, float]:
        source = self.usage if self.done else self.live
        return {key: source.get(key) or 0 for key in (*TOKEN_KEYS, "cost_usd")}

    @property
    def calls(self) -> list[Call]:
        return [i for i in self.items if isinstance(i, Call)]


Item = Step | Call | Event


@dataclass(frozen=True)
class Update:
    item: Item
    parent: Step | None  # None: top level of the run
    new: bool


class Run:
    def __init__(self, path: Path):
        self.path = path
        self.workflow = path.parent.name
        self.mission = STAMP.sub("", path.name)
        self.entries: list[Item] = []
        self.steps: dict[str, Step] = {}
        self.calls: dict[tuple[str | None, str], Call] = {}  # in start order
        self.models: dict[str, Any] = {}  # role -> model spec, as the runner declared it
        self.started: datetime | None = None
        self.last: datetime | None = None
        self.lifecycle: str | None = None
        self.paused = False  # the runner is waiting at a checkpoint (run.paused … run.resumed)
        self.pid: int | None = None
        self.verdict: str | None = None
        self.error: str | None = None

    # ------------------------------------------------------------ folding

    def apply(self, event: dict[str, Any]) -> Update:
        name = str(event.get("event", "?"))
        time = _parse_time(event.get("time"))
        step_name = event.get("step")
        fields = {k: v for k, v in event.items() if k not in ("time", "event", "step")}
        self.started = self.started or time
        self.last = time or self.last

        prefix, _, suffix = name.rpartition(".")
        if step_name and suffix in ("started", "completed") and prefix not in ("step", "tool", "run"):
            name, fields = f"step.{suffix}", {"role": prefix, **fields}  # legacy "<role>.started"
        self._track_lifecycle(name, fields)
        if name in ("run.paused", "run.resumed"):
            self.paused = name == "run.paused"

        if name == "step.started":
            step = self._step(step_name, time)
            step.fields = fields
            return Update(step, None, new=True)
        if name == "step.completed":
            new = step_name not in self.steps
            step = self._step(step_name, time)
            step.usage, step.done, step.ended = fields, True, time
            return Update(step, None, new=new)
        parent = self._step(step_name, time) if step_name else None
        if parent is not None and name in ("usage", "session"):  # folded into the step, not shown as items
            if name == "session":
                parent.session = fields
            else:
                for key, value in fields.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        parent.live[key] = parent.live.get(key, 0) + value
            return Update(parent, None, new=False)
        if name in ("tool.started", "tool.completed"):
            return self._tool(name, time, fields, parent)
        item = Event(name, time, fields)
        self._add(item, parent)
        return Update(item, parent, new=True)

    def _track_lifecycle(self, name: str, fields: dict[str, Any]) -> None:
        state = LIFECYCLE.get(name)
        if state is None:
            return
        self.lifecycle = state
        self.paused = False
        if state == "started":
            self.pid = fields.get("pid")
            self.error = None
            self.models = fields.get("models") or self.models
        self.verdict = fields.get("verdict", self.verdict)
        self.error = fields.get("error", self.error)

    def _step(self, name: str, time: datetime | None) -> Step:
        if name not in self.steps:  # created by its first event, whatever that is
            self.steps[name] = Step(name, time)
            self.entries.append(self.steps[name])
        return self.steps[name]

    def _tool(self, name: str, time: datetime | None, fields: dict[str, Any], parent: Step | None) -> Update:
        call_id = str(fields.get("call_id") or f"#{len(self.calls)}")
        key = (parent.name if parent else None, call_id)
        call = self.calls.get(key)
        new = call is None
        if call is None:
            call = Call(call_id, str(fields.get("tool", "?")), time, fields.get("input"),
                        step=parent.name if parent else None)
            self.calls[key] = call
            self._add(call, parent)
        if name == "tool.completed":
            call.output, call.error, call.done, call.ended = fields.get("output"), fields.get("error"), True, time
            call.reported_seconds = fields.get("seconds")
            if call.input is None:
                call.input = fields.get("input")
        return Update(call, parent, new=new)

    def _add(self, item: Item, parent: Step | None) -> None:
        (parent.items if parent else self.entries).append(item)

    # ------------------------------------------------------------ summary

    @property
    def status(self) -> str:
        """running · paused · done · stopped · failed · crashed (started, but its process is gone) · unknown."""
        if self.lifecycle in ("completed", "failed", "stopped"):
            return {"completed": "done"}.get(self.lifecycle, self.lifecycle)
        if self.lifecycle == "started" and self.pid:
            if not _alive(self.pid):
                return "crashed"
            return "paused" if self.paused else "running"
        return "unknown"

    @property
    def seconds(self) -> float | None:
        end = datetime.now(self.started.tzinfo) if self.status == "running" and self.started else self.last
        return _elapsed(self.started, end)

    @property
    def tokens(self) -> dict[str, float]:
        totals = dict.fromkeys((*TOKEN_KEYS, "cost_usd"), 0.0)
        for step in self.steps.values():
            for key, value in step.tokens.items():
                totals[key] += value
        return totals

    @property
    def cost_usd(self) -> float:
        return self.tokens["cost_usd"]

    @property
    def runner_items(self) -> list[Call | Event]:
        """What the runner did itself, outside any agent step."""
        return [e for e in self.entries if not isinstance(e, Step)]

    @property
    def active_step(self) -> Step | None:
        """The step running now, else the last one."""
        steps = list(self.steps.values())
        running = [s for s in steps if not s.done]
        return running[-1] if running else steps[-1] if steps else None


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _elapsed(start: datetime | None, end: datetime | None) -> float | None:
    return (end - start).total_seconds() if start and end else None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
