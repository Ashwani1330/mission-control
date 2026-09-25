"""Drafting and launching missions from the New mission screen, with fake pipeline commands."""

import json
import sys
import textwrap

from textual.widgets import Select, TextArea

from mission_control.app import MissionControl
from mission_control.launch import find_config, load_config
from mission_control.screens.new_mission import NewMissionScreen

FAKE_DRAFT = textwrap.dedent("""
    import json, sys
    request, out = open(sys.argv[1]).read(), sys.argv[2]
    context = sys.argv[4] if len(sys.argv) > 4 else "none"
    json.dump({"name": "Demo Mission", "goal": request.strip(), "drafted_with": context,
               "models": {"worker": {"vendor": "codex", "model": "gpt", "effort": "high"}}}, open(out, "w"))
""")
FAKE_DESCRIBE = textwrap.dedent("""
    import json
    print(json.dumps({"selects": [{"field": "context", "label": "Context", "default": "acme",
        "options": [{"value": "acme", "label": "acme"}, {"value": "globex", "label": "globex"}]}],
        "choices": [{"field": "tools", "label": "Tools", "options": [
        {"value": "web", "label": "Web", "available": True, "note": ""},
        {"value": "yc", "label": "YC", "available": True, "note": ""},
        {"value": "lab", "label": "Lab", "available": False, "note": "not installed"}]}],
        "numbers": [{"path": ["budget", "max_tasks"], "label": "max tasks", "integer": True, "min": 1, "max": 8}],
        "models": {"worker": {"vendor": "codex", "model": "gpt", "effort": "high"}}}))
""")
FAKE_RUN = textwrap.dedent("""
    import json, os, sys, time
    from datetime import datetime, timezone
    mission = json.load(open(sys.argv[1]))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = os.path.join("runs", "demo", "demo-mission-" + stamp)
    os.makedirs(run)
    with open(os.path.join(run, "events.jsonl"), "w") as f:
        f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "event": "run.started",
                            "pid": os.getpid(), "models": mission["models"]}) + "\\n")
    time.sleep(3)
""")


def make_config(tmp_path):
    (tmp_path / "draft.py").write_text(FAKE_DRAFT)
    (tmp_path / "run.py").write_text(FAKE_RUN)
    (tmp_path / "describe.py").write_text(FAKE_DESCRIBE)
    (tmp_path / "runs").mkdir()
    (tmp_path / "mission-control.toml").write_text(textwrap.dedent(f"""
        [models]
        choices = ["codex/gpt", "claude/opus"]
        [[workflow]]
        name = "demo"
        draft = ["{sys.executable}", "draft.py", "{{request}}", "{{mission}}", "--context", "{{context}}"]
        run = ["{sys.executable}", "run.py", "{{mission}}"]
        describe = ["{sys.executable}", "describe.py"]
    """))
    return tmp_path / "runs"


def test_config_is_found_next_to_the_runs_folder(tmp_path):
    runs = make_config(tmp_path)
    config = load_config(find_config(runs))
    assert list(config.workflows) == ["demo"] and config.model_choices == ["codex/gpt", "claude/opus"]


async def test_draft_edit_models_and_launch(tmp_path):
    runs = make_config(tmp_path)
    app = MissionControl(runs)
    async with app.run_test(size=(180, 45)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, NewMissionScreen)
        screen.query_one("#nm-request", TextArea).text = "count the robots"
        await pilot.press("ctrl+g")
        for _ in range(50):
            await pilot.pause(0.1)
            if screen.query_one("#nm-mission", TextArea).text:
                break
        mission = json.loads(screen.query_one("#nm-mission", TextArea).text)
        assert mission["goal"] == "count the robots" and "models" not in mission

        screen.query_one("#model-worker", Select).value = "claude/opus"
        await pilot.press("ctrl+l")
        for _ in range(50):
            await pilot.pause(0.1)
            app.poll()
            if app.selected is not None and app.selected.mission == "demo-mission":
                break
        await pilot.pause(0.2)
        assert app.selected.mission == "demo-mission" and app.current_mode == "overview"
        assert app.selected.models["worker"] == {"vendor": "claude", "model": "opus", "effort": "high"}
        assert not isinstance(app.screen, NewMissionScreen)



async def wait_for(pilot, condition, tries=60):
    for _ in range(tries):
        await pilot.pause(0.1)
        if condition():
            return True
    return False


async def test_options_form_edits_the_mission(tmp_path):
    from textual.widgets import Checkbox, Input
    runs = make_config(tmp_path)
    app = MissionControl(runs)
    async with app.run_test(size=(180, 50)) as pilot:
        await pilot.press("n")
        screen = app.screen
        assert await wait_for(pilot, lambda: len(screen.query(Checkbox)) == 3)
        web, yc, lab = screen.query(Checkbox)
        assert lab.disabled and not web.disabled
        assert await wait_for(pilot, lambda: len(screen.query(".nm-model-row")) == 1)  # models before any draft
        assert all(w.region.height > 0 for w in screen.query(".nm-number-row"))

        yc.value = True  # chosen before any draft: must end up in the draft
        from textual.widgets import Select
        context = next(w for w in screen.query(Select) if w.id != "nm-workflow")
        context.value = "globex"
        await pilot.pause()
        screen.query_one("#nm-request", TextArea).text = "count the robots"
        await pilot.press("ctrl+g")
        assert await wait_for(pilot, lambda: screen.query_one("#nm-mission", TextArea).text)
        mission = json.loads(screen.query_one("#nm-mission", TextArea).text)
        assert mission["tools"] == ["yc"]
        assert mission["context"] == "globex" and mission["drafted_with"] == "globex"

        tasks = screen.query_one(Input)
        tasks.value = "5"
        await pilot.pause(0.2)
        assert json.loads(screen.query_one("#nm-mission", TextArea).text)["budget"]["max_tasks"] == 5
        tasks.value = "99"  # out of range: ignored
        await pilot.pause(0.2)
        assert json.loads(screen.query_one("#nm-mission", TextArea).text)["budget"]["max_tasks"] == 5


async def test_approve_continues_a_run_waiting_for_approval(tmp_path):
    from conftest import ev, write

    from mission_control.screens.dialogs import Confirm
    runs = make_config(tmp_path)
    (tmp_path / "approve.py").write_text(textwrap.dedent("""
        import json, os, sys, time
        from datetime import datetime, timezone
        with open(os.path.join(sys.argv[1], "events.jsonl"), "a") as f:
            f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "event": "run.started",
                                "pid": os.getpid(), "phase": "run"}) + "\\n")
        time.sleep(3)
    """))
    config = (tmp_path / "mission-control.toml").read_text()
    (tmp_path / "mission-control.toml").write_text(
        config.replace('name = "demo"', f'name = "demo"\napprove = ["{sys.executable}", "approve.py", "{{run_dir}}"]'))
    trace = runs / "demo" / "plan-20260925T100000Z" / "events.jsonl"
    write(trace, ev(0, "run.started", pid=1, phase="plan"),
          ev(5, "run.completed", phase="plan", verdict="AWAITING_APPROVAL"))

    app = MissionControl(runs)
    async with app.run_test(size=(180, 45)) as pilot:
        await pilot.press("r", "down", "down", "enter")  # the "Needs you" group, then the run
        await pilot.pause()
        assert app.selected is not None and app.selected.verdict == "AWAITING_APPROVAL"
        await pilot.press("A")
        await pilot.pause()
        assert isinstance(app.screen, Confirm)
        await pilot.press("y")
        assert await wait_for(pilot, lambda: (app.poll(), app.selected.status == "running")[1])
