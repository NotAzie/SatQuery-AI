# `earth_platform/streaming`

**Purpose.** Real-time delivery of events to clients.

**Belongs here**
- `EventBus` (fan-out + replay), the SQLite-backed event-log integration, and the SSE encoder/route
- WebSocket transport and shared multi-process bus backends are future extensions

**Never here**
- Defining events (they belong to `agent`)
- Persistence logic (uses `sessions.EventLog`)
- Business decisions about what to emit

**Depends on.** `agent` (events), `earth`, `shared`.

**Public interface.** `EventBus.publish/subscribe`, `InMemoryEventBus`, `SSEEventEncoder`, `ClientMessage`, `ControlMessage`, `EventEncoder`. Live fan-out currently targets one backend process.
