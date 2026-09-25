"""Start pipeline runs: read mission-control.toml, draft a mission, launch it detached. No Textual here.

The launched runner is its own process (own session), so it keeps running if Mission
Control exits; Mission Control finds its run through the trace like any other run."""

from __future__ import annotations

import json
import re
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONFIG_NAME = "mission-control.toml"
DRAFT_TIMEOUT = 600
STATE_DIR = ".mission-control"  # drafts and launch logs, next to the config


class LaunchError(Exception):
    pass


@dataclass(frozen=True)
class Workflow:
    name: str
    description: str
    run: list[str]
    draft: list[str] | None = None


@dataclass(frozen=True)
class Config:
    path: Path
    workflows: dict[str, Workflow]
    model_choices: list[str] = field(default_factory=list)  # "vendor/model"
    efforts: list[str] = field(default_factory=lambda: ["low", "medium", "high"])

    @property
    def root(self) -> Path:  # commands run here
        return self.path.parent

    @property
    def state(self) -> Path:
        return self.root / STATE_DIR


@dataclass
class Launch:
    workflow: str
    mission: dict[str, Any]
    process: subprocess.Popen
    log: Path
    started: float  # time.time()

    @property
    def slug(self) -> str:
        return slugify(self.mission.get("name", ""))


def find_config(runs_dir: Path, explicit: Path | None = None) -> Path | None:
    candidates = [explicit] if explicit else [Path.cwd() / CONFIG_NAME, runs_dir.parent / CONFIG_NAME]
    return next((p.resolve() for p in candidates if p and p.is_file()), None)


def load_config(path: Path) -> Config:
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LaunchError(f"cannot read {path}: {exc}") from exc
    workflows = {}
    for entry in raw.get("workflow", []):
        if not isinstance(entry.get("name"), str) or not _command(entry.get("run")):
            raise LaunchError(f"{path}: every [[workflow]] needs a name and a run command (a list of strings)")
        workflows[entry["name"]] = Workflow(entry["name"], str(entry.get("description", "")), list(entry["run"]),
                                            list(entry["draft"]) if _command(entry.get("draft")) else None)
    models = raw.get("models", {})
    return Config(path, workflows, [str(m) for m in models.get("choices", [])],
                  [str(e) for e in models.get("efforts", ["low", "medium", "high"])])


def _command(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(part, str) for part in value)


def fill(command: list[str], **values: Path) -> list[str]:
    return [part.format(**{k: str(v) for k, v in values.items()}) for part in command]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def draft(config: Config, workflow: str, request: str) -> dict[str, Any]:
    """Run the workflow's draft command on `request` (blocking) and return the mission it wrote."""
    flow = config.workflows[workflow]
    if flow.draft is None:
        raise LaunchError(f"workflow {workflow!r} has no draft command; write the mission JSON yourself")
    folder = config.state / "drafts"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    request_file, mission_file = folder / f"{workflow}-{stamp}.request.txt", folder / f"{workflow}-{stamp}.json"
    request_file.write_text(request)
    try:
        done = subprocess.run(fill(flow.draft, request=request_file, mission=mission_file), cwd=config.root,
                              capture_output=True, text=True, timeout=DRAFT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LaunchError(f"draft command failed: {exc}") from exc
    if done.returncode or not mission_file.exists():
        raise LaunchError((done.stderr or done.stdout).strip()[-600:] or f"draft exited {done.returncode}")
    return json.loads(mission_file.read_text())


def launch(config: Config, workflow: str, mission: dict[str, Any]) -> Launch:
    """Write the approved mission and start its runner in the background."""
    flow = config.workflows[workflow]
    folder = config.state / "launches"
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / f"{slugify(mission.get('name', workflow)) or workflow}-{_stamp()}"
    mission_file, log = base.with_suffix(".json"), base.with_suffix(".log")
    mission_file.write_text(json.dumps(mission, indent=2, ensure_ascii=False) + "\n")
    with log.open("w") as out:
        try:
            process = subprocess.Popen(fill(flow.run, mission=mission_file), cwd=config.root, stdout=out,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise LaunchError(f"could not start {flow.run[0]}: {exc}") from exc
    return Launch(workflow, mission, process, log, time.time())


def log_tail(path: Path, chars: int = 600) -> str:
    try:
        return path.read_text()[-chars:].strip()
    except OSError:
        return ""
