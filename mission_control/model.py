"""Fold trace events (docs/trace-format.md) into a run's timeline. No Textual here.

A timeline is a list of entries; a Step holds its own entries. Every `Run.apply`
returns an `Update` saying which item changed, so a view can patch itself instead
of rebuilding."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Older runs used "mission.*" for the run lifecycle and "<role>.started" for steps.
LIFECYCLE = {"run.started": "started", "run.completed": "completed", "run.failed": "failed",
             "mission.started": "started", "mission.completed": "completed", "mission.failed": "failed"}
STAMP = re.compile(r"-\d{8}T\d{6}Z$")


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


@dataclass(eq=False)
class Step:
    name: str
    time: datetime | None
    fields: dict[str, Any] = field(default_factory=dict)  # from step.started: role, vendor, model, ...
    usage: dict[str, Any] = field(default_factory=dict)   # from step.completed
    items: list[Call | Event] = field(default_factory=list)
    done: bool = False
    ended: datetime | None = None

    @property
    def error(self) -> Any:
        return self.usage.get("error")

    @property
    def seconds(self) -> float | None:
        return self.usage.get("seconds") or _elapsed(self.time, self.ended)


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
        self.calls: dict[tuple[str | None, str], Call] = {}
        self.started: datetime | None = None
        self.last: datetime | None = None
        self.lifecycle: str | None = None
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
        if state == "started":
            self.pid = fields.get("pid")
            self.error = None
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
            call = self.calls[key] = Call(call_id, str(fields.get("tool", "?")), time, fields.get("input"))
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
        """running · done · failed · crashed (started, but its process is gone) · unknown."""
        if self.lifecycle == "completed":
            return "done"
        if self.lifecycle == "failed":
            return "failed"
        if self.lifecycle == "started" and self.pid:
            return "running" if _alive(self.pid) else "crashed"
        return "unknown"

    @property
    def cost_usd(self) -> float:
        return sum(s.usage.get("cost_usd") or 0 for s in self.steps.values())

    @property
    def seconds(self) -> float | None:
        end = datetime.now(self.started.tzinfo) if self.status == "running" and self.started else self.last
        return _elapsed(self.started, end)


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
