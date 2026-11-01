# `src/features/chat`

**Purpose.** Conversation UI and the event reducer that turns `AgentEvent`s into messages and Earth commands.

**Belongs here**
- Components, feature-local hooks and state for this feature
- Present streamed Engine events and forward typed `earth.command` events to the Earth dispatcher

**Never here**
- Importing another feature
- Constructing Earth commands or interpreting scientific results

**Depends on.** `components`, `services`, `state`, `shared`, `earth` (controller API only).

**Public interface.** `AgentChat`.
