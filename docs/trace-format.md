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

## Writers

Any program that appends these lines works.
