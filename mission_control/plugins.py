"""Group tool calls into plugins (yc, web, shell, …) by simple rules. No Textual here.

A rule names a plugin and lists tool-name patterns (shell-style wildcards). A
shell call is also matched by the program it runs, so an agent running `yc …`
in a shell counts as the yc plugin. The first matching rule wins; calls that
match nothing go to "other". To add a plugin, add one rule."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

from mission_control.model import Call

SHELL_TOOLS = ("shell", "Bash")


@dataclass(frozen=True)
class Rule:
    name: str
    tools: tuple[str, ...] = ()
    program: str | None = None  # a program name that, run from a shell tool, belongs to this plugin

    def matches(self, call: Call) -> bool:
        if any(fnmatch.fnmatchcase(call.tool, pattern) for pattern in self.tools):
            return True
        return bool(self.program and call.tool in SHELL_TOOLS and _runs(command_of(call), self.program))


RULES = (
    Rule("yc", tools=("mcp__yc__*", "yc *"), program="yc"),
    Rule("web", tools=("WebFetch", "WebSearch", "web_search", "mcp__*web*")),
    Rule("skill", tools=("Skill",)),
    Rule("files", tools=("Read", "Write", "Edit", "Glob", "Grep", "file_change")),
    Rule("shell", tools=SHELL_TOOLS),
    Rule("meta", tools=("ToolSearch", "StructuredOutput", "TodoWrite", "todo_list")),
)
OTHER = "other"


def plugin_of(call: Call) -> str:
    return next((rule.name for rule in RULES if rule.matches(call)), OTHER)


def command_of(call: Call) -> str:
    return str(call.input.get("command", "")) if isinstance(call.input, dict) else ""


def _runs(command: str, program: str) -> bool:
    return re.search(rf"(^|[\s;&|(\"']){re.escape(program)}\s", command) is not None


@dataclass
class PluginStats:
    name: str
    calls: list[Call] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for c in self.calls if c.error)

    @property
    def running(self) -> int:
        return sum(1 for c in self.calls if not c.done)

    @property
    def avg_seconds(self) -> float | None:
        times = [c.seconds for c in self.calls if c.seconds is not None]
        return sum(times) / len(times) if times else None

    @property
    def tools(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for call in self.calls:
            counts[call.tool] = counts.get(call.tool, 0) + 1
        return counts


def summarize(calls: list[Call]) -> list[PluginStats]:
    """Plugins in rule order (then "other"), only those that were used."""
    stats = {name: PluginStats(name) for name in (*(r.name for r in RULES), OTHER)}
    for call in calls:
        stats[plugin_of(call)].calls.append(call)
    return [s for s in stats.values() if s.calls]
