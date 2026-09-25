"""Find runs on disk and read only what was appended to their trace since the last poll."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mission_control.model import Run, Update


class Tail:
    """Reads new complete JSON lines from an append-only file; keeps a trailing partial line for later."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.partial = b""

    def read(self) -> list[dict[str, Any]]:
        try:
            if self.path.stat().st_size <= self.offset:
                return []
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                data = stream.read()
        except FileNotFoundError:
            return []
        self.offset += len(data)
        *lines, self.partial = (self.partial + data).split(b"\n")
        events = []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events


class RunStore:
    """All runs under `root`, laid out as <root>/<workflow>/<run-id>/events.jsonl."""

    def __init__(self, root: Path):
        self.root = root
        self.runs: dict[Path, Run] = {}
        self._tails: dict[Path, Tail] = {}

    def poll(self) -> list[tuple[Run, list[Update]]]:
        changed = []
        for trace in self.root.glob("*/*/events.jsonl"):
            run_dir = trace.parent
            if run_dir not in self.runs:
                self.runs[run_dir] = Run(run_dir)
                self._tails[run_dir] = Tail(trace)
            run = self.runs[run_dir]
            updates = [run.apply(event) for event in self._tails[run_dir].read()]
            if updates:
                changed.append((run, updates))
        return changed
