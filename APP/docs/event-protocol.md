# Event protocol

Defined in `earth_platform/agent/events.py` (`AgentEvent`) and `streaming/messages.py`; mirrored in
TypeScript from `contracts/schema.json`. Every event carries `id`, `schema_version`, `session_id`,
`conversation_id`, `run_id`, `seq` (per session, assigned on publish) and `at`.

| `type` | Meaning | Key fields |
|---|---|---|
| `run.started` | a run began | `model` |
| `message.delta` / `reasoning.delta` | streamed text | `message_id`, `text` |
| `message.completed` | full assistant message | `message` |
| `tool.requested` / `tool.started` | model asked for / system began a tool | `invocation_id`, `tool`, `arguments` |
| `tool.progress` | progress update | `fraction`, `message` |
| `tool.completed` | tool finished | `ok`, `error`, `evidence[]` |
| `investigation.updated` | Engine investigation status | `investigation_id`, `status`, `fraction` |
| `earth.command` | make the globe react | `command` (`EarthCommand`) |
| `usage` | token accounting | `usage` |
| `run.completed` / `run.failed` | terminal | `finish_reason` / `code`, `message` |
| `engine.event` | Engine Agent event forwarded without reinterpretation | Engine session/turn id, kind, sequence, timestamp, `payload` |

Rules: add event types and fields freely; renaming or removing is breaking and bumps
`EVENT_SCHEMA_VERSION`. The server always serialises every field (no `exclude_defaults`).

## Transports

| | SSE | WebSocket |
|---|---|---|
| Direction | server → client | both |
| Use | chat streaming; simple, proxy-friendly | live Earth context up, cancel, multiplexed control |
| Resume | `Last-Event-ID` = `seq` | `Subscribe{after_seq}` |
| Control | HTTP POST | `Cancel`, `UpdateEarthContext`, `Ping` frames |

The chat POST route forwards `engine.event` records from the Engine Agent SSE stream and persists
them before writing to its response. The separate session SSE route uses
`EventBus.subscribe(session_id, after_seq)`, replays from the SQLite-backed event log, then receives
events published in the same process. Its event IDs map to per-session sequence numbers and drive
`Last-Event-ID` reconnects. A shared multi-process broker and the WebSocket route are not
implemented. Control frames (`hello`, `pong`, `stream.error`) are contracts only and are not
persisted.

`earth.command` is a Platform event contract consumed by the frontend dispatcher. The current
Engine Agent event allowlist does not emit it, and the Platform does not infer or synthesize one
from assistant text or tool results. The Engine-to-Platform mapping remains an explicit integration
gap.

## Earth commands

`fly_to`, `set_time`, `set_layer_visibility`, `add_overlay`, `clear_overlays`, `highlight_evidence`,
`show_investigation`. Presentation directives only: they reference evidence by id and carry no computed
results.
