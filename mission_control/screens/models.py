"""Models: which model each role runs on, as declared by the runner and as actually used."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widgets import DataTable, Static

from mission_control import fmt
from mission_control.model import Run, Update
from mission_control.screens.base import View
from mission_control.widgets import Row, make_table, sync_table


def model_rows(run: Run) -> list[Row]:
    roles: dict[str, dict[str, Any]] = {role: {"spec": spec, "steps": []} for role, spec in run.models.items()}
    for step in run.steps.values():
        roles.setdefault(step.role or "?", {"spec": {}, "steps": []})["steps"].append(step)
    rows: list[Row] = []
    for role, info in roles.items():
        spec, steps = info["spec"], info["steps"]
        used = sorted({f"{s.vendor} {s.model}".strip() for s in steps} - {""})
        declared = f"{spec.get('vendor', '')} {spec.get('model', '')}".strip() if isinstance(spec, dict) else str(spec)
        totals = {k: sum(s.tokens[k] for s in steps) for k in ("input_tokens", "output_tokens", "cost_usd")}
        rows.append((role, [role, declared or "-", spec.get("effort", "-") if isinstance(spec, dict) else "-",
                            ", ".join(used) or "-", str(len(steps)), fmt.count(totals["input_tokens"]),
                            fmt.count(totals["output_tokens"]), fmt.money(totals["cost_usd"])]))
    return rows


class ModelsScreen(View):
    def body(self) -> ComposeResult:
        yield Static("Declared by the runner at start, and what each role's steps actually ran on.", id="models-note")
        yield make_table("role", "declared", "effort", "used", "steps", "in", "out", "cost", id="models")

    def redraw(self, run: Run, updates: list[Update]) -> None:
        sync_table(self.query_one("#models", DataTable), model_rows(run))
