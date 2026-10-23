# SatQuery system architecture

This document describes the current repository architecture. Long-term goals
belong to the [roadmap](ROADMAP.md); current runtime limits are summarized in
[implementation status](../IMPLEMENTATION_STATUS.md).

## Application shape

SatQuery is a Python application with one FastAPI service, one served browser
workspace, and one `satquery` CLI. The application composition creates a
`PlatformRuntime` that owns modality/dataset/connector registries, the
investigation lifecycle, execution services, Earth Memory, governance, and
monitoring. CLI and API operations use the same platform services. The legacy
image question-answering capability remains reachable through compatibility
routes and task integration; it is not the primary Earth observation pipeline.

```text
CLI / FastAPI / browser workspace
              |
       application composition
              |
       PlatformRuntime
       /      |       \
 planning  perception  lifecycle & execution
              |              |
      capability/dataset  workflow DAG
      selection + source  /      |      \
      adapters           objects evidence diagnostics
                              \    |    /
                           reports, audit,
                       reproducibility, memory
```

The runtime is local and in-process. Optional SQLite adapters provide local
durability for selected platform records. They are not distributed services.

## Main boundaries

### Contracts and capability selection

Pydantic contracts in `satquery.platform.contracts` define EarthQuery,
observations, measurements, assets, provenance, quality, Earth Objects,
evidence, workflows, and investigation state. Modality, dataset, ontology,
and capability modules determine which configured implementations declare
support. The planner preserves unresolved information rather than guessing.

### Perception

Connector adapters acquire source data and normalize it to canonical
observations while retaining source metadata and provenance. Quality and
fusion report known properties/conflicts; missing uncertainty and availability
remain unknown. The capability matrix is based on declarations and observed
registry state, not a guarantee of provider availability.

Optional Rasterio/PyProj/Shapely functionality supports documented sampling,
zonal summary, and explicitly mapped categorical-component workflows. It does
not provide general remote-sensing classification, automatic resampling,
mosaicking, or validated uncertainty propagation.

### Understanding and investigation

Earth Objects are materialized from explicit extraction candidates. Current
paths include source-declared OSM features, FIRMS records, NOAA station data,
and caller-mapped categorical raster components. The extraction record links
object properties and relationships to source observations; this does not
establish ground truth or support general segmentation/entity resolution.

Natural-language planning is deterministic and bounded by supported ontology
terms and configured capabilities. Ready plans can be designed into an
investigation DAG. The local scheduler executes dependency-aware tasks with
bounded concurrency, cancellation, explicit retry safety, events, and
compatible checkpoint resume.

### Scientific intelligence and governance

Evidence assessment checks recorded coverage, not scientific sufficiency.
Reasoning emits deterministic diagnostics and registered findings. The
catalogued literature is not itself executable. No bundled scientific method
is certified for general conclusions; there is no general causal or calibrated
probabilistic engine. Governance records versioned method transitions and
benchmark results supplied to it; it does not create independent scientific
review.

### Memory, monitoring, and reproducibility

Earth Memory indexes immutable artifacts and explicit lineage using
deterministic filters. Optional SQLite search indexes support local querying.
Monitoring runs recurring EarthQueries and evaluates user-authored operational
thresholds; they are not a scientific event detector. Reproducibility exports
hash retained plans, observations, objects, reasoning, audit, and monitoring
artifacts where available. They cannot reconstruct upstream data that the
provider no longer serves unless that data was retained. They also retain the
content-verified public capability-selection snapshots used during planning
and acquisition; raw dataset metadata, asset URIs, and connector source/provider
payloads are excluded from those snapshots.

## Persistence and deployment

Without configured paths, application stores are in memory. SQLite can persist
selected lifecycle, memory, execution journal, audit, and monitoring records
on one host. Cache defaults are local/in-memory. No container, cloud, database
service, authentication, tenant isolation, secret management, backup/restore,
or deployment automation is currently supplied. See [local setup](../development/SETUP.md)
and [deployment status](../deployment/README.md).

## Package map

- `satquery/api.py`, `ui.py`, `__main__.py`: HTTP, browser, and CLI interfaces.
- `satquery/platform/`: canonical contracts and runtime capabilities.
- `connectors/`: source adapters and optional imagery fetcher.
- `configs/`: opt-in example connector declarations.
- `tests/`: repository-level tests, configured by `satquery-ai/pyproject.toml`.
- `docs/`: user, contributor, subsystem, and research documentation.

See the [component guide](../architecture/COMPONENTS.md) for module details.
