"""Steer a running mission by writing <run-dir>/control.json, which the runner reads before each step.

    {"state": "running" | "paused" | "stopped", "notes": [{"time": "...", "text": "..."}]}

Writes are atomic (temp file, then rename), so a runner never reads half a file."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read(run_dir: Path) -> dict[str, Any]:
    try:
        value = json.loads((run_dir / "control.json").read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def write(run_dir: Path, state: str | None = None, note: str | None = None) -> dict[str, Any]:
    control = {"state": "running", "notes": [], **read(run_dir)}
    if state is not None:
        control["state"] = state
    if note:
        control["notes"] = [*control.get("notes", []), {"time": datetime.now(UTC).isoformat(), "text": note}]
    target = run_dir / "control.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(control, indent=2, ensure_ascii=False))
    os.replace(temp, target)
    return control
