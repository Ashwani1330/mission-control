# Trace format

**Version 1.** Every run folder holds one append-only `events.jsonl`: one JSON
object per line, in the order things happened. It is the contract between
pipelines (writers) and Mission Control (the reader). Any pipeline that writes
this format, in any language, shows up in Mission Control.

```
runs/<workflow>/<run-id>/
├── events.jsonl          ← the trace (this format)
├── <step>.prompt.txt     ← what the agent was asked
├── <step>.events.jsonl   ← the vendor's own stream, verbatim, for audit
├── <step>.stderr.log
└── <step>.json           ← the agent's structured result
```

## Lines

Every line has `time` (ISO 8601, UTC) and `event`. These event names have
meaning; any other name is shown as-is with its fields, which is how a
workflow adds its own events (`feature.decision`, `verdict`, …).

| event | fields | written by |
|---|---|---|
| `run.started` | `trace_version`, `pid`, `workflow`, `mission`, … | the runner |
| `run.completed` | `verdict`, … | the runner |
| `run.failed` | `error` | the runner |
| `run.stopped` | `reason` | the runner, when the operator stopped it |
| `run.paused` / `run.resumed` | `before` (the step it waits in front of) | the runner |
| `operator.note` | `step`, `notes` | the runner, when it hands operator notes to a step |
| `step.started` | `step`, `role`, `vendor`, `model`, `prompt_file` | the agent-call wrapper |
| `step.completed` | `step`, `seconds`, token counts, `cost_usd`, `tool_calls_by_name`, `error` | the agent-call wrapper |
| `tool.started` | `step`?, `call_id`, `tool`, `input` | the vendor's stream, or runner code |
| `tool.completed` | `step`?, `call_id`, `tool`, `output`, `error`, `seconds`? | the vendor's stream, or runner code |
| `message` | `step`, `kind` (`text` / `thinking`), `text` | the vendor's stream |
| `usage` | `step`, token counts, `cost_usd`? | the vendor's stream |
| `session` | `step`, `session_id`, … | the vendor's stream |
| `warning` / `error` | `step`, `text` | the vendor's stream |

- `step` ties an event to one agent call. Events without it belong to the
  run itself; a tool call without a step was made by runner code (e.g. the
  research runner's `yc` CLI searches).
- `tool.started` and `tool.completed` pair up by (`step`, `call_id`). A
  `tool.completed` with no start is fine; it may carry `seconds` itself.
- `run.started` carries the runner's `pid` so a viewer can tell a running
  run from a crashed one.

- `run.started` carries `trace_version`. Readers show unknown versions as
  best they can; bump the version only for changes readers must know about.
- Events older than version 1 (`mission.*` lifecycle, `<role>.started` steps)
  are still read.

## Control (Mission Control → runner)

Mission Control steers a running mission by writing `<run-dir>/control.json`
atomically:

```json
{"state": "running", "notes": [{"time": "2026-09-25T12:03:00+00:00", "text": "focus on pumps"}]}
```

`state` is `running`, `paused` or `stopped`. A runner that supports control reads the
file before each agent step: while paused it waits there (emitting `run.paused`, then
`run.resumed`); when stopped it ends cleanly (`run.stopped`); notes it has not yet
delivered go into the next step's prompt (`operator.note`). A runner that ignores the
file still works; it just cannot be steered.

## Writers

Any program that appends these lines works; see the README for a minimal Python writer.
A typical setup: the runner writes the run lifecycle and its own tool calls; a small
wrapper around each agent call writes `step.*`; and one adapter per agent CLI
translates that CLI's JSON stream (`codex exec --json`, `claude -p --output-format
stream-json`, …) into `tool.*`, `message`, `usage` and `session` events as lines arrive.
