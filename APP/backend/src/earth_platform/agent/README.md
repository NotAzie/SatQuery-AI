# `earth_platform/agent`

**Purpose.** Platform session/event integration and the public run-event contract. SatQuery Engine
owns the reasoning-model/tool loop exposed by its Agent API; the Platform forwards it rather than
reimplementing it.

**Belongs here**
- `AgentRuntime`: links Platform sessions to Engine Agent sessions and publishes forwarded events
- `AgentEvent` union (the primary Platform wire contract)
- Existing generic agent/tool interfaces remain extension contracts and are not used for Engine turns

**Never here**
- Model/tool loops, planning, prompts, or deterministic computation (the Engine owns them)
- Provider-specific code (use `llm`)
- Transport concerns such as SSE or WebSocket framing

**Depends on.** `engine`, `sessions`, `shared`.

**Public interface.** `AgentRuntime.stream_turn`, `AgentEvent`, and the session/event bridge.
