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
    json.dump({"name": "Demo Mission", "goal": request.strip(),
               "models": {"worker": {"vendor": "codex", "model": "gpt", "effort": "high"}}}, open(out, "w"))
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
    (tmp_path / "runs").mkdir()
    (tmp_path / "mission-control.toml").write_text(textwrap.dedent(f"""
        [models]
        choices = ["codex/gpt", "claude/opus"]
        [[workflow]]
        name = "demo"
        draft = ["{sys.executable}", "draft.py", "{{request}}", "{{mission}}"]
        run = ["{sys.executable}", "run.py", "{{mission}}"]
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
        assert app.selected.mission == "demo-mission"
        assert app.selected.models["worker"] == {"vendor": "claude", "model": "opus", "effort": "high"}
        assert not isinstance(app.screen, NewMissionScreen)
