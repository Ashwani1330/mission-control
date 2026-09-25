import json
import os

import pytest

T = "2026-09-25T10:00:{:02d}+00:00"


def ev(second, event, **fields):
    return {"time": T.format(second), "event": event, **fields}


def write(path, *events):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.writelines(json.dumps(e) + "\n" for e in events)


@pytest.fixture
def research_run(tmp_path):
    """A running research-style run: a Codex planner, runner yc CLI calls, a Claude observer mid-step."""
    trace = tmp_path / "research" / "yc-20260925T100000Z" / "events.jsonl"
    write(trace,
          ev(0, "run.started", trace_version=1, pid=os.getpid(), workflow="research",
             models={"planner": {"vendor": "codex", "model": "gpt", "effort": "high"},
                     "observer": {"vendor": "claude", "model": "opus", "effort": "high"}}),
          ev(1, "step.started", step="planner-r1", role="planner", vendor="codex", model="gpt"),
          ev(2, "session", step="planner-r1", session_id="abc"),
          ev(3, "message", step="planner-r1", kind="text", text="plan"),
          ev(4, "usage", step="planner-r1", input_tokens=100, cached_input_tokens=0, output_tokens=10),
          ev(5, "step.completed", step="planner-r1", input_tokens=100, output_tokens=10, seconds=4.0),
          ev(6, "tool.completed", call_id="s1", tool="yc search.companies", input={"query": "robots"}, seconds=1.5),
          ev(7, "tool.completed", call_id="s2", tool="yc search.companies", input={"query": "arms"}, seconds=0.5),
          ev(8, "step.started", step="observer-1", role="observer", vendor="claude", model="opus"),
          ev(9, "tool.started", step="observer-1", call_id="t1", tool="mcp__yc__search", input={"entity": "x"}))
    return trace


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Never read or write the real user's settings."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
