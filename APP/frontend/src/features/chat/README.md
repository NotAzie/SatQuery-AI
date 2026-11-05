# `src/features/chat`

**Purpose.** SatQuery's command notch, mounted in God's Eye's native command dock, conversation UI,
and event reducer that turns `AgentEvent`s into messages and Earth commands.

**Belongs here**
- Components, feature-local hooks and state for this feature
- Keep the compact command notch, expanded conversation, Engine progress, execution consent, and
  access to the actual God's Eye provider settings in one interaction surface
- Open the Platform workspace drawer for Projects/sessions, saved session views, monitoring, and
  read-only Engine capability discovery
- Present streamed Engine events and forward typed `earth.command` events to the Earth dispatcher
- Show ordered investigation journal activity without interpreting Engine results or evidence
- Open Engine-authored investigation reports referenced by the active Engine transcript
- Render persisted Engine attachment references through the owning Platform session's image API

**Never here**
- Importing another feature
- Constructing Earth commands or interpreting scientific results

**Depends on.** `components`, `services`, `state`, `shared`, `earth` (controller API only).

**Public interface.** `AgentChat`.
