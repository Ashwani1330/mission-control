"""The TUI: folding events, tailing files, and the app on a fake runs folder."""

import json
import os

from mission_control.app import MissionControl
from mission_control.model import Call, Event, Run, Step
from mission_control.store import Tail
from mission_control.widgets import Detail, RunTable, Timeline

T = "2026-09-25T10:00:0{}+00:00"


def ev(second, event, **fields):
    return {"time": T.format(second), "event": event, **fields}


def write(path, *events):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.writelines(json.dumps(e) + "\n" for e in events)


def test_fold_nests_calls_under_steps_and_pairs_them(tmp_path):
    run = Run(tmp_path / "research" / "yc-20260925T100000Z")
    run.apply(ev(0, "run.started", pid=os.getpid()))
    run.apply(ev(1, "step.started", step="observer-1", role="observer", vendor="claude"))
    first = run.apply(ev(2, "tool.started", step="observer-1", call_id="t1", tool="mcp__yc__search", input={"q": 1}))
    second = run.apply(ev(4, "tool.completed", step="observer-1", call_id="t1", tool="mcp__yc__search", output="ok"))
    runner_call = run.apply(ev(5, "tool.completed", call_id="s1", tool="yc search.companies", seconds=1.5))
    run.apply(ev(6, "step.completed", step="observer-1", cost_usd=0.25, seconds=5.0))

    assert run.mission == "yc" and run.workflow == "research" and run.status == "running"
    step = run.steps["observer-1"]
    assert first.new and not second.new and first.item is second.item and first.parent is step
    call = step.items[0]
    assert isinstance(call, Call) and call.done and call.output == "ok" and call.seconds == 2.0
    assert runner_call.parent is None and runner_call.item.seconds == 1.5  # a runner-made call sits at top level
    assert step.done and run.cost_usd == 0.25

    run.apply(ev(7, "run.completed", verdict="PASS"))
    assert run.status == "done" and run.verdict == "PASS"


def test_fold_reads_legacy_events_and_unknown_ones(tmp_path):
    run = Run(tmp_path / "coding" / "x")
    run.apply(ev(0, "mission.started"))
    update = run.apply(ev(1, "planner.started", step="planner-r1"))
    assert isinstance(update.item, Step) and update.item.fields["role"] == "planner"
    other = run.apply(ev(2, "feature.decision", decision="PASS"))
    assert isinstance(other.item, Event) and other.parent is None
    assert run.status == "unknown"  # started, but no pid to check
    run.apply(ev(3, "run.started", pid=2**22 + 12345))
    assert run.status == "crashed"


def test_tail_keeps_partial_lines_for_later(tmp_path):
    path = tmp_path / "events.jsonl"
    tail = Tail(path)
    assert tail.read() == []
    path.write_text('{"a": 1}\n{"b"')
    assert tail.read() == [{"a": 1}]
    with path.open("a") as stream:
        stream.write(': 2}\nbroken\n')
    assert tail.read() == [{"b": 2}]
    assert tail.read() == []


async def test_app_shows_newest_run_and_follows_new_events(tmp_path):
    old = tmp_path / "coding" / "old-20260924T100000Z" / "events.jsonl"
    new = tmp_path / "research" / "new-20260925T100000Z" / "events.jsonl"
    write(old, {"time": "2026-09-24T10:00:00+00:00", "event": "run.started"})
    write(new, ev(0, "run.started", pid=os.getpid()), ev(1, "step.started", step="planner-r1"))

    app = MissionControl(tmp_path)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        assert app.query_one(RunTable).row_count == 2
        assert app.selected is app.store.runs[new.parent]
        timeline = app.query_one(Timeline)
        assert len(timeline.root.children) == 2

        write(new, ev(2, "tool.started", step="planner-r1", call_id="1", tool="shell", input={"command": "ls"}))
        app.poll()
        await pilot.pause()
        step_node = timeline.root.children[1]
        assert len(step_node.children) == 1 and "shell" in str(step_node.children[0].label)

        timeline.focus()
        timeline.select_node(step_node.children[0])
        timeline.move_cursor(step_node.children[0])
        await pilot.pause()
        assert isinstance(app.query_one(Detail).item, Call)
