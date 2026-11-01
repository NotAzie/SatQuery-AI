# SatQuery design principles

These principles constrain implementation. See
[current implementation status](../IMPLEMENTATION_STATUS.md) for what is
currently available; this page does not claim every principle is fully
realized.

1. **Evidence before conclusions.** Preserve observations and their lineage;
   do not make conclusions from language output alone.
2. **Unknown remains unknown.** Missing uncertainty, quality, licensing,
   coverage, resolution, and access metadata must not be fabricated.
3. **Source facts remain source facts.** Keep provider terminology and payloads
   available alongside canonical mappings; do not imply a source declaration
   is independent validation.
4. **Provider neutrality.** Select implementations through declared
   capability and query compatibility, not provider identity embedded in
   scientific logic.
5. **Reproducibility.** Version plans, workflows, methods, processing choices,
   and artifacts; retain exact inputs and explicit missing records.
6. **Determinism where appropriate.** Use stable ordering and identities for
   planning, registries, diagnostics, and replay. Label nondeterministic
   external acquisition and model output explicitly.
7. **Modular composition.** Contracts define boundaries; adapters implement
   them. Do not add unused registries or parallel storage paths without an
   implemented consumer.
8. **Graceful partial execution.** Keep independent successful evidence when
   another source fails, while making partial coverage and failed tasks
   visible.
9. **Scientific scope is explicit.** Separate operational triggers,
   descriptive comparisons, evidence coverage, and validated inference.
10. **Security at extension boundaries.** Treat connector manifests,
    plugins, model checkpoints, and provider responses as untrusted data or
    trusted executable code only where explicitly configured; manifests do
    not sandbox code.

When principles conflict, preserve scientific integrity and traceability over
convenience or presentation.
