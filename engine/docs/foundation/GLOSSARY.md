# SatQuery glossary

These terms describe current platform contracts and their boundaries. See the
[implementation status](../IMPLEMENTATION_STATUS.md) for a concise map.

**Capability matrix** — A deterministic view of registered modalities,
connectors, datasets, variables, and declared coverage/limits. A declaration
does not prove live provider availability.

**Connector** — A replaceable integration that discovers data and/or acquires
source records through a provider-neutral runtime contract.

**Dataset** — A named source collection or product represented by metadata,
coverage, variables, access, and provenance declarations. A catalog entry may
be incomplete or unavailable.

**Earth Memory** — An artifact index for investigation and scientific records.
It supports deterministic retrieval and optional local SQLite durability; it
does not learn, infer, or automatically validate science.

**Earth Object** — A canonical, versioned semantic entity explicitly
materialized from source candidates and evidence. Assertions retain their
support and provenance. Unknown properties remain absent. Materialization
does not itself detect an entity or prove a scientific claim.

**EarthQuery** — The structured query contract for spatial/temporal scope,
variables, datasets, and explicit processing requests.

**Evidence** — A traceable record associated with observations, measurements,
hypotheses, or method outputs. Evidence presence alone does not imply that an
assertion is true or sufficient.

**Investigation** — A mission-linked, versioned workflow record that plans and
executes tasks against an EarthQuery and preserves outputs and lifecycle.

**Mission** — A local record of a user's higher-level Earth objective, which
can contain investigations and monitoring schedules.

**Modality** — A sensing domain such as atmospheric, hydrological, visual, or
oceanic. It is independent of a particular connector or dataset.

**Observation** — A canonical record acquired from a source or produced by an
explicit processing step. It retains its source metadata, geometry, time,
measurements, quality, and provenance where supplied.

**Observation stack** — An exact-support grouping of compatible timestamped
measurements. It does not resample, convert units, interpolate, or imply a
trend.

**Provenance** — The recorded source, query, connector, method, processing, and
lineage information associated with an artifact.

**Scientific diagnostic** — A bounded descriptive output such as coverage,
agreement under a declared criterion, or exact-support arithmetic. It is not a
validated scientific conclusion unless an applicable, independently validated
method says so.

**Scientific method** — A versioned, cited, applicability-bounded procedure
with required inputs, assumptions, limitations, uncertainty semantics, and
validation evidence. Metadata alone does not certify it.

**Uncertainty** — Uncertainty explicitly supplied by a source or produced by a
method with a declared uncertainty model. Unknown uncertainty is not zero and
must not be replaced by confidence.
