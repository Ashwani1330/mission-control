"""Small text formatters shared by every screen."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from rich.text import Text

BRIEF = 70
STATUS = {"running": ("●", "yellow"), "done": ("✓", "green"), "failed": ("✗", "red"),
          "crashed": ("✗", "red"), "attention": ("!", "magenta"), "unknown": ("?", "dim")}


def status_icon(status: str) -> Text:
    icon, style = STATUS.get(status, STATUS["unknown"])
    return Text(icon, style=style)


def status_text(status: str, label: str | None = None) -> Text:
    icon, style = STATUS.get(status, STATUS["unknown"])
    return Text(f"{icon} {label or status}", style=style)


def clock(time: datetime | None, fmt: str = "%H:%M:%S") -> str:
    return time.astimezone().strftime(fmt) if time else "--:--:--"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s" if minutes < 60 else f"{minutes // 60}h{minutes % 60:02d}m"


def count(value: float | None) -> str:
    if not value:
        return "-"
    for unit, size in (("M", 1_000_000), ("K", 1_000)):
        if value >= size:
            return f"{value / size:.1f}{unit}"
    return str(int(value))


def money(value: float | None) -> str:
    return f"${value:.2f}" if value else "-"


def brief(value: Any, limit: int = BRIEF) -> str:
    if isinstance(value, dict) and len(value) == 1:
        value = next(iter(value.values()))
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
