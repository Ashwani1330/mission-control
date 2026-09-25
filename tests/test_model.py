"""Folding events into runs, tailing trace files, and grouping calls into plugins."""

import os

from conftest import ev

from mission_control.model import Call, Event, Run, Step
from mission_control.plugins import plugin_of, summarize
from mission_control.store import RunStore, Tail


def test_fold_nests_calls_pairs_them_and_totals_tokens(tmp_path, research_run):
    store = RunStore(tmp_path)
    store.poll()
    run = store.newest()
    assert run.mission == "yc" and run.workflow == "research" and run.status == "running"
    assert set(run.models) == {"planner", "observer"}

    planner = run.steps["planner-r1"]
    assert planner.session == {"session_id": "abc"}
    assert [type(i) for i in planner.items] == [Event]  # usage and session are folded, not listed
    assert planner.tokens["input_tokens"] == 100 and planner.done

    runner_calls = [i for i in run.runner_items if isinstance(i, Call)]
    assert [c.step for c in runner_calls] == [None, None] and runner_calls[0].seconds == 1.5

    observer = run.steps["observer-1"]
    assert run.active_step is observer and observer.calls[0].status == "running"
    update = run.apply(ev(12, "tool.completed", step="observer-1", call_id="t1", tool="mcp__yc__search", output="ok"))
    assert not update.new and update.parent is observer and observer.calls[0].seconds == 3.0

    run.apply(ev(13, "usage", step="observer-1", input_tokens=50, cost_usd=0.25))
    assert run.tokens["input_tokens"] == 150 and run.cost_usd == 0.25  # live usage of a running step counts

    run.apply(ev(14, "run.completed", verdict="PASS"))
    assert run.status == "done" and run.verdict == "PASS"


def test_fold_reads_legacy_events_and_unknown_ones(tmp_path):
    run = Run(tmp_path / "coding" / "x")
    run.apply(ev(0, "mission.started"))
    update = run.apply(ev(1, "planner.started", step="planner-r1"))
    assert isinstance(update.item, Step) and update.item.role == "planner"
    other = run.apply(ev(2, "feature.decision", decision="PASS"))
    assert isinstance(other.item, Event) and other.parent is None
    assert run.status == "unknown"  # started, but no pid to check
    run.apply(ev(3, "run.started", pid=os.getpid() + 2**22))
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


def call(tool, **tool_input):
    return Call("1", tool, None, tool_input)


def test_plugins_group_by_tool_and_by_program_run_in_a_shell():
    assert plugin_of(call("mcp__yc__search")) == "yc"
    assert plugin_of(call("yc search.companies")) == "yc"
    assert plugin_of(call("shell", command='/usr/bin/bash -lc "yc tools list --json"')) == "yc"
    assert plugin_of(call("shell", command="ls ycombinator")) == "shell"
    assert plugin_of(call("WebFetch")) == "web"
    assert plugin_of(call("Frobnicate")) == "other"

    failed = call("WebSearch")
    failed.error = "boom"
    stats = summarize([call("mcp__yc__search"), call("yc search.companies"), failed])
    assert [s.name for s in stats] == ["yc", "web"]
    assert stats[0].tools == {"mcp__yc__search": 1, "yc search.companies": 1} and stats[1].errors == 1
