User Query

↓

Intent Detection

↓

Mission Creation

↓

Planning

↓

Dataset Discovery

↓

Evidence Collection

↓

Analysis

↓

Reasoning

↓

Verification

↓

Explanation

↓

Visualization

↓

Memory Update

## Investigation execution

Planned investigations compile their selected observation steps into an
execution DAG. The platform runtime appends explicit evidence-assessment and
scientific-reasoning stages when a stored plan and design identify an
executable candidate. The API delegates execution to this same runtime path;
it does not run scientific stages in route code.

Workflow compilation is versioned and registered. A compiler produces a
validated `ExecutionPlan`; registered task handlers remain separately
replaceable. The local scheduler releases downstream work as soon as its own
dependencies finish, within the configured concurrency bound, instead of
waiting for an entire DAG layer. Operators can request cancellation through
the API, CLI, or workspace. Async handlers are cancelled by the scheduler;
synchronous or long-running handlers can inspect the shared cancellation token
through `TaskContext`. Unstarted work is recorded as cancelled.

Assessment and reasoning stages declare their acquisition dependencies and may
consume successful branches when another acquisition fails. Cancelled branches
still stop downstream work. Each task result preserves its handler, declared
dependencies, description, and redacted parameters alongside the output, so the
execution endpoint and reproducibility artifacts retain the graph that ran.

Partial execution remains visible as a partial investigation lifecycle state.
Assessment and reasoning outputs remain evidence-scoped diagnostics. No
scientific conclusion is asserted unless an independently governed method
supports it.

The scheduler remains local and in-process, while a replaceable execution
journal can persist workflow fingerprints, immutable successful task
checkpoints, and append-only hash-chained events in SQLite. Output replay is allowed only
through an explicitly registered codec version. `investigation resume` and the
matching API route reuse compatible successful checkpoints after a process
restart. Tasks whose prior completion is uncertain require an explicit
`retry_safe` declaration before they can be replayed; unsupported output
contracts are reported as uncheckpointed rather than reconstructed heuristically.
The event API supports ordered polling. Live SSE, distributed workers, worker
leases, and remote scheduling remain future work.
