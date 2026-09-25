"""The app on a generated runs folder: screens, navigation and live updates."""

from conftest import ev, write
from textual.widgets import DataTable

from mission_control.app import MissionControl
from mission_control.model import Call
from mission_control.screens.agents import RUNNER, SessionScreen
from mission_control.widgets import Detail, Timeline


def keys(table: DataTable) -> list[str]:
    return [row.value for row in table.rows]


async def test_overview_shows_newest_run(tmp_path, research_run):
    write(tmp_path / "coding" / "old-20260924T100000Z" / "events.jsonl",
          {"time": "2026-09-24T10:00:00+00:00", "event": "run.started"})
    app = MissionControl(tmp_path)
    async with app.run_test(size=(180, 45)) as pilot:
        await pilot.pause()
        assert app.selected.mission == "yc"
        assert keys(app.screen.query_one("#overview-agents")) == [RUNNER, "planner-r1", "observer-1"]
        assert keys(app.screen.query_one("#overview-plugins")) == ["yc"]

        await pilot.press("r")
        await pilot.pause()
        assert app.current_mode == "runs" and len(keys(app.screen.query_one("#runs"))) == 2


async def test_session_follows_new_events_live(tmp_path, research_run):
    app = MissionControl(tmp_path)
    async with app.run_test(size=(180, 45)) as pilot:
        await pilot.pause()
        app.open_session("observer-1")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SessionScreen)
        timeline = screen.query_one(Timeline)
        assert len(timeline.root.children) == 1

        write(research_run, ev(20, "tool.started", step="observer-1", call_id="t2", tool="WebFetch",
                               input={"url": "https://example.com"}),
              ev(21, "tool.started", step="planner-r1", call_id="x", tool="shell"))  # another step: not shown
        app.poll()
        await pilot.pause()
        assert len(timeline.root.children) == 2 and "WebFetch" in str(timeline.root.children[1].label)

        timeline.move_cursor(timeline.root.children[1])
        await pilot.pause()
        assert isinstance(screen.query_one(Detail).item, Call)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SessionScreen)


async def test_plugins_screen_lists_calls_of_the_chosen_plugin(tmp_path, research_run):
    app = MissionControl(tmp_path)
    async with app.run_test(size=(180, 45)) as pilot:
        await pilot.pause()
        app.open_plugin("yc")
        await pilot.pause()
        calls = app.screen.query_one("#plugin-calls")
        assert keys(calls) == ["|s1", "|s2", "observer-1|t1"]  # runner CLI calls and the agent's MCP call
        assert isinstance(app.screen.query_one(Detail).item, Call)


async def test_agents_filters_by_vendor(tmp_path, research_run):
    app = MissionControl(tmp_path)
    async with app.run_test(size=(180, 45)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        table = app.screen.query_one("#agents")
        assert keys(table) == [RUNNER, "planner-r1", "observer-1"]
        await pilot.press("v")  # first vendor in order: claude
        await pilot.pause()
        assert keys(table) == ["observer-1"]


async def test_full_view_opens_and_closes(tmp_path, research_run):
    from mission_control.widgets import FullText
    app = MissionControl(tmp_path)
    async with app.run_test(size=(180, 45)) as pilot:
        await pilot.pause()
        app.open_session("planner-r1")
        await pilot.pause()
        detail = app.screen.query_one(Detail)
        detail.show(app.selected.steps["planner-r1"].items[0], app.selected)
        detail.focus()
        await pilot.press("v")
        await pilot.pause()
        assert isinstance(app.screen, FullText)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SessionScreen)
