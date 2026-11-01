# Documentation map

Start with [current implementation status](IMPLEMENTATION_STATUS.md) for a
truthful overview of what runs today and the principal limits. The
[implementation status](IMPLEMENTATION_STATUS.md) and API reference describe
working behavior; the foundation documents describe principles and long-term
direction.

## New contributors

1. [Project overview and local installation](../satquery-ai/README.md)
2. [Development setup and configuration](development/SETUP.md)
3. [Contribution process](development/CONTRIBUTING.md)
4. [Style guide](development/STYLE_GUIDE.md)
5. [Testing guide](testing/TESTING_GUIDE.md)
6. [Current system architecture](foundation/SYSTEM_ARCHITECTURE.md)
7. [Subsystem catalog](architecture/COMPONENTS.md)

## Platform and science

- [Earth Perception](architecture/Earth_Perception.md)
- [Earth Understanding and Objects](foundation/ROADMAP.md#phase-2--earth-understanding)
- [Investigation and execution flow](architecture/QUERY_PIPELINE.md)
- [Scientific intelligence and governance](architecture/SCIENTIFIC_INTELLIGENCE.md)
- [Earth Memory](architecture/EARTH_MEMORY.md)
- [Continuous observation](foundation/ROADMAP.md#phase-7--continuous-earth-observation)
- [Earth data sources](datasets/SUPPORTED_DATASETS.md)
- [STAC connector](datasets/STAC_CONNECTOR.md)
- [NASA POWER connector](datasets/NASA_POWER_CONNECTOR.md)
- [API and CLI](api/API_REFERENCE.md)

## Testing and operations

- [Testing guide](testing/TESTING_GUIDE.md)
- [Benchmark policy and current assets](testing/BENCHMARKS.md)
- [Local deployment boundary](deployment/README.md)
- [Agent-system status](architecture/AGENT_SYSTEM.md)
- [Model stack](architecture/MODEL_STACK.md)

## Research notes

- [Papers and cited scientific methods](research/PAPERS.md)
- [Research ideas](research/IDEAS.md)
- [External code references](research/GITHUB_REFERENCES.md)

## Document status

`docs/foundation/ROADMAP.md` is the long-term capability roadmap. It is not a
release checklist. Historical reports under `archive/` and dated test reports
are immutable records of the state at the time they were produced; they are
not current status statements. Where a current document and a dated archive
disagree, use [current implementation status](IMPLEMENTATION_STATUS.md) and
the current source tree.
