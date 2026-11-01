# Architectural decision log

This concise log records decisions visible in the current architecture. It is
not a substitute for a dated proposal or change review. The implementation
status page records the current effects and limits.

## Accepted decisions

### Modality-first, provider-neutral perception

Earth sensing domains and canonical observations are separate from dataset and
connector identity. The capability matrix selects only implementations whose
declared scope matches a request. Provider metadata remains attached as source
provenance. A connector declaration is not a live availability check.

### One platform runtime with a retained image capability

Missions, investigations, Earth observations, execution, and monitoring use
the platform runtime exposed through the API, CLI, and browser workspace. The
original image-QA interface remains a compatible perception task rather than
a second Earth platform. It still has a distinct legacy model/tool pipeline.

### Earth Objects are evidence-backed assertions

Objects are explicitly materialized from candidates and observations. Stable
source identity can support reconciliation; object properties and
relationships retain their evidence links. The platform does not infer
classification, object lifecycle, or ground truth from unvalidated source
records.

### Deterministic diagnostics precede general inference

Coverage, exact-support comparison, hypothesis bookkeeping, and registered
rules are inspectable. Operational trigger thresholds are user-defined
predicates. No method is allowed to emit validated scientific findings merely
because its manifest says `validated`.

### Local durability is optional and explicit

In-memory stores are the default for a simple local run. Configured SQLite
stores persist selected Earth Memory, lifecycle, execution, audit, and
monitoring records on one host. SQLite files are not a distributed storage or
multi-tenant deployment design.

## Revisit when

- Independently validated scientific methods need real benchmark assets.
- Multiple users or organizations require authentication, authorization, and
  isolation.
- Distributed acquisition or worker execution is introduced.
- Asset downloads, retention, licensing, or cloud costs require product
  decisions.
