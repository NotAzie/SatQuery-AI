# `earth_platform/sessions`

**Purpose.** Platform workspace metadata, investigation context, active tasks, and ordered event log.
Agent chat transcripts remain authoritative in the linked SatQuery Engine Agent session.

**Belongs here**
- Domain models and repository Protocols; the current SQLite implementation and future store adapters
- `Session.engine_agent_session_id` links a Platform session to its Engine-owned Agent transcript
- `Session.earth_workspace` persists Platform presentation context, camera history and bookmarks
- `EventLog`: ordered record enabling stream resume

**Never here**
- Interpreting events (the log stores opaque payloads)
- Orchestration or LLM calls
- Evidence payloads (store ids only; the Engine owns evidence)
- A second copy of Engine Agent messages in Platform conversation storage

**Depends on.** `shared`.

**Public interface.** `SessionStore` facade with `sessions`, `conversations`, `tasks`, `events` repositories; `SQLiteSessionStore` is the current single-process implementation.
