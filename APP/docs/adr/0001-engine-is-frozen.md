# ADR 0001: SatQuery Engine is frozen and accessed through one seam

**Status:** accepted

**Context.** The Engine (v1.0) is finished, tested and stable. The Platform needs its capabilities
without becoming entangled with its internals.

**Decision.** The Engine is a dependency like a database. Only `earth_platform.engine` may import
Engine SDK or transport code. It exposes a Platform-owned `EngineClient` Protocol and thin models;
adapters map Engine types to them. The Platform never recomputes or edits evidence; it holds
`EvidenceRef`s.

**Consequences.** Engine changes touch one adapter. Tests use a fake `EngineClient`. The Platform's
models may be thinner than the Engine's; richer data is fetched by id when needed. The first adapter
must be fitted to the Engine's real Agent Interface, which this scaffold deliberately does not guess.
