"""Per-user settings (the chosen theme), kept in $XDG_CONFIG_HOME/mission-control/settings.json.
Losing them is harmless, so every read and write fails soft."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "mission-control" / "settings.json"


def load() -> dict[str, Any]:
    try:
        value = json.loads(path().read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save(**changes: Any) -> None:
    try:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({**load(), **changes}, indent=2))
    except OSError:
        pass
