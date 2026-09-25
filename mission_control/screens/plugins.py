"""Plugins: tool calls grouped by plugin (yc, web, shell, …), each call's full input and output."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable

from mission_control import fmt
from mission_control.model import Call, Run, Update
from mission_control.plugins import PluginStats, summarize
from mission_control.screens.base import View
from mission_control.widgets import Detail, Row, cursor_key, make_table, sync_table


def plugin_rows(stats: list[PluginStats]) -> list[Row]:
    return [(s.name, [s.name, str(len(s.calls)), str(s.errors) if s.errors else "-",
                      str(s.running) if s.running else "-", fmt.duration(s.avg_seconds)]) for s in stats]


def call_key(call: Call) -> str:
    return f"{call.step or ''}|{call.call_id}"


class PluginsScreen(View):
    TITLES: ClassVar[dict[str, str]] = {"#plugins": "Plugins", "#plugin-tools": "Tools",
                                        "#plugin-calls": "Calls", "#plugin-detail": "Detail · v full view"}

    def __init__(self) -> None:
        super().__init__()
        self.plugin: str | None = None  # the plugin whose calls are listed
        self._calls: dict[str, Call] = {}

    def body(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="plugin-side"):
                yield make_table("plugin", "calls", "errors", "running", "avg", id="plugins")
                yield make_table("tool", "calls", id="plugin-tools")
            yield make_table("", "time", "by", "tool", "input", "took", id="plugin-calls")
            yield Detail(id="plugin-detail")

    def show_plugin(self, name: str | None) -> None:
        self.plugin = name
        if self.is_mounted:
            self.refresh_view([])

    def redraw(self, run: Run, updates: list[Update]) -> None:
        stats = summarize(list(run.calls.values()))
        by_name = {s.name: s for s in stats}
        plugins = self.query_one("#plugins", DataTable)
        sync_table(plugins, plugin_rows(stats))
        if self.plugin not in by_name:
            self.plugin = cursor_key(plugins)
        elif cursor_key(plugins) != self.plugin:
            plugins.move_cursor(row=list(by_name).index(self.plugin), animate=False)
        chosen = by_name.get(self.plugin)
        calls = chosen.calls if chosen else []
        self._calls = {call_key(c): c for c in calls}
        sync_table(self.query_one("#plugin-tools", DataTable),
                   [(tool, [tool, str(n)]) for tool, n in sorted((chosen.tools if chosen else {}).items(),
                                                                  key=lambda kv: -kv[1])])
        self.query_one("#plugin-calls").border_title = f"{self.plugin or ''} calls  {len(calls)}"
        sync_table(self.query_one("#plugin-calls", DataTable),
                   [(call_key(c), [fmt.status_icon(c.status), fmt.clock(c.time), c.step or "runner", c.tool,
                                   fmt.brief(c.input, 48), fmt.duration(c.seconds)]) for c in calls])
        detail = self.query_one(Detail)
        detail.refresh_if_showing([u.item for u in updates])
        if detail.item is None and calls:
            detail.show(calls[0], run)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        run = self.app.selected
        if run is None:
            return
        if event.data_table.id == "plugins" and event.row_key.value != self.plugin:
            self.plugin = event.row_key.value
            self.refresh_view([])
        elif event.data_table.id == "plugin-calls" and event.row_key.value in self._calls:
            self.query_one(Detail).show(self._calls[event.row_key.value], run)
