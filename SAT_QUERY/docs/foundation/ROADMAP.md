# Earth Intelligence Roadmap

> "SatQuery is an Earth Intelligence Operating System that autonomously observes, investigates, reasons about, and explains our planet using evidence from geospatial, environmental, and scientific data."

---

# Purpose

This roadmap defines the long-term evolution of SatQuery.

Unlike traditional software roadmaps, this document is not feature-oriented. It is capability-oriented.

Every phase represents a new level of Earth Intelligence.

The objective is not simply to build software—it is to build a trustworthy Earth Intelligence Operating System capable of understanding our planet through evidence, scientific reasoning, and transparent investigation.

This document serves as the master engineering roadmap for the entire project.

---

# Guiding Principles

Every future decision should reinforce these principles.

- Evidence before confidence.
- Reasoning before prediction.
- Scientific integrity before convenience.
- Transparency before appearance.
- Modularity over dependency.
- Reproducibility over demonstrations.
- Intelligence over automation.
- Understanding over information.

Every component should answer one question:

> "Does this improve SatQuery's ability to understand the Earth?"

If not, it likely does not belong in the core platform.

---

# The Evolution of SatQuery

SatQuery evolves through nine major capability layers.

Each layer builds upon the previous one.

None of these phases are isolated products.

Together they become one continuously evolving Earth Intelligence Operating System.

## Current implementation snapshot (2026-10-23)

The phase descriptions below define long-term capability goals. This snapshot
separates those goals from code that currently runs; detailed evidence and
limitations are in [implementation status](../IMPLEMENTATION_STATUS.md).

| Phase | Current repository state |
|---|---|
| 0 — Core Foundation | Local typed contracts, registries, configuration, connector lifecycle, bounded DAG execution, diagnostics, tests, CI, and optional single-host SQLite stores exist. Distributed execution, sandboxing, production security/deployment, and cross-subsystem transactions do not. |
| 1 — Earth Perception | Several configured real-source adapters, modality/capability selection, canonical observations, provenance, fusion, streaming, cache, and bounded raster operations exist. Plans retain integrity-checked snapshots of the safe public capability-selection metadata. Domain coverage, automatic asset processing, harmonization, reprojection, and uncertainty propagation remain limited. |
| 2 — Earth Understanding | Explicit source/caller-declared candidates can produce canonical Earth Objects with lineage, revisions, relationships, and memory/report integration. General segmentation, object detection, unconstrained entity resolution, and validated lifecycle inference are absent. |
| 3 — Investigation Engine | Deterministic planning/design, mission lifecycle, compiled execution DAG, local scheduler, cancellation, safe retry, checkpoint resume, reports, comparison, and monitoring-linked investigations exist. Plan and acquisition capability snapshots are retained in Earth Memory, reports, and reproducibility exports. Planning-language coverage, remote scheduling, and autonomous investigation adaptation remain bounded or absent. |
| 4 — Earth Reasoning Engine | Hypotheses, evidence coverage, sufficiency/preflight, rules/operators, cited knowledge records, uncertainty inventory, and governance scaffolds exist. No bundled method is certified for general scientific conclusions; general probabilistic, causal, and calibrated inference is not active. |
| 5 — Multi-Agent Intelligence | No multi-agent runtime, communication, delegation, agent policy, or collaboration UI is implemented. Existing task and plugin registries are not agents. |
| 6 — Earth Memory | Deterministic artifact and lineage search with in-memory and optional SQLite stores, capability snapshot artifacts, spatial-envelope/time filters, and cursor paging exists. It is local, non-semantic, same-CRS, and does not learn or provide planet-scale distributed retrieval. |
| 7 — Continuous Earth Observation | Mission-linked recurring queries, local scheduling/recovery, trigger policies, events, notifications, comparisons, and history integration exist. Operational triggers are not validated change detection; external notifications and distributed scheduling are absent. |
| 8 — Earth Intelligence Platform | Local FastAPI/OpenAPI, CLI, browser workspace, and grouped synchronous Python SDK cover local platform workflows. The workspace includes an interactive locator view for supported Earth Object geometries and GeoJSON export is available through API, CLI, and SDK. A full GIS/map workspace, authentication, organizations, cloud deployment, and production operations remain absent. |
| 9 — Earth Intelligence Ecosystem | Local extension/connector/method interfaces and registration exist. There is no public package ecosystem, marketplace, institutional governance network, or contribution/compatibility service. |

This snapshot is descriptive, not a completion score or release certification.
Historical reports under `archive/` and `satquery-ai/test_runs/` remain dated
records and should not override the current implementation documentation.

---

# Phase 0 — Core Foundation

## Goal

Build the engineering foundation upon which every future capability depends.

This phase focuses entirely on architecture, maintainability, extensibility, and developer experience.

Without this foundation, later intelligence layers become difficult to evolve.

---

## Objectives

Establish:

- modular architecture
- configuration system
- plugin/connector framework
- orchestration framework
- schema system
- model registry
- tool registry
- logging
- caching
- testing infrastructure
- documentation standards
- CI/CD pipeline
- project governance

---

## Deliverables

- Stable repository structure
- Core APIs
- Base abstractions
- Connector interface
- Tool interface
- Model interface
- Common schemas
- Documentation hierarchy
- Testing framework

---

# Phase 1 — Earth Perception

## Goal

Enable SatQuery to observe the planet.

The Earth produces information through many different sensing systems.

SatQuery must learn to access all of them.

---

## Scope

Satellite imagery

Weather

Climate

Hydrology

Elevation

Land cover

Population

Infrastructure

Transportation

Research repositories

Government datasets

Environmental sensors

Future observation systems

---

## Deliverables

Unified Connector System

Example connectors

- Sentinel
- Landsat
- MODIS
- Copernicus
- Google Earth Engine
- STAC
- ERA5
- CHIRPS
- OpenStreetMap
- NOAA
- NASA APIs

Each connector becomes another "sense" through which SatQuery observes Earth.

---

# Phase 2 — Earth Understanding

## Goal

Convert raw observations into structured Earth knowledge.

Raw pixels are not intelligence.

Understanding begins when observations become semantic information.

---

## Capabilities

Image understanding

Object detection

Segmentation

Land cover analysis

Scene understanding

Feature extraction

Caption generation

Metadata extraction

Spatial reasoning

Temporal alignment

Knowledge normalization

---

## Outputs

Instead of images:

Earth Objects

Water

Forest

Road

Building

Crop

River

Glacier

Burn Scar

Flood

Urban Area

Vegetation

Confidence

Relationships

### Current implementation boundary

The platform now has an evidence-backed Earth Object contract and deterministic
materialization/catalog layer, now fronted by a provider-neutral candidate
extraction pipeline. It reconciles stable identities across observations and
rejects conflicting type or method declarations rather than merging them.
Extraction batches retain source-observation and candidate digests and are
indexed in Earth Memory, including empty candidate batches so an unrecorded
extraction can be distinguished from one that emitted no candidates. The
versioned investigation DAG includes extraction and object materialization as
a typed, checkpointed task between acquisition and reasoning; its output lists
materialized object revision IDs and is replayable through the registered
task-output codec. Observation, extraction, object, and transition records are
captured together in versioned reproducibility bundles. The
same task can polygonize caller-selected classes from categorical raster
assets into connected component Earth Objects. Class mappings, connectivity,
AOI inclusion rule, size filters, output limits, native CRS, source-window
digests, and extraction software versions are retained. This is vectorization
of an already-encoded class mask, not classification or validated image
segmentation. The
OpenStreetMap adapter emits candidates for a bounded set of explicit tags,
NASA FIRMS emits source-identified thermal-anomaly records, and NOAA CO-OPS
emits provider-identified monitoring-station objects. These remain source
classifications, not validated ground truth. Independent adapters that declare
the same identity namespace, value, and canonical type can contribute evidence
to one object while retaining each method and declarer. Extraction metadata
preserves method identity, applicability context, limits, and an explicit
not-independently-validated status. Canonical property assertions retain
observation/evidence links, source measurements, uncertainty, and source
metadata. Explicit candidate source attributes are separately retained as
typed, unmapped values with observation, dataset, method, uncertainty status, and
provenance links; they do not become canonical properties without an explicit
validated mapping. Geometry and temporal validity are populated only when all supplied
source records agree exactly; otherwise they remain unknown and each original
record is retained in provenance. Relationships are explicit assertions with
evidence/observation references. Earth Objects are indexed in Earth Memory,
exposed in the API/CLI/workspace, and supplied to reasoning before it evaluates
the same investigation's observations. Validated image segmentation,
cross-source entity resolution without shared source identity, object-native
planning and reasoning operators, geometry aggregation, automatic lifecycle inference,
and scientific conclusions still require validated methods and suitable
reference evidence.

EarthQuery validates supplied GeoJSON structure and finite coordinates,
applying longitude/latitude bounds only when a geographic CRS is explicitly
declared. This does not establish topological validity, repair geometry,
aggregate geometries, or validate source observations; malformed source
geometries remain subject to explicit downstream handling.

The extraction implementation can be run through the shared scientific
validation executor using `EarthObjectExtractionBenchmarkRunner` and an
owner-supplied reference bundle. This hook validates exact output reproducibility
only; no scientific accuracy claim follows from a matching output.

These become the language of Earth.

---

# Phase 3 — Investigation Engine

## Goal

Transform natural language questions into scientific investigations.

Traditional AI answers questions.

SatQuery creates investigation plans.

---

## Responsibilities

Mission interpretation

Problem decomposition

Dataset selection

Tool selection

Workflow planning

Dependency resolution

Execution graph generation

Investigation orchestration

Evidence requirements

Confidence planning

### Current implementation boundary

The local execution path compiles a selected investigation candidate through a
versioned workflow compiler registry into one dependency graph containing
observation acquisition, evidence coverage assessment, and bounded scientific
evaluation. The scheduler runs ready tasks within a concurrency limit and
releases dependent work as soon as its inputs complete. Operators can request
cooperative cancellation through the API, CLI, or workspace. Assessment and
reasoning retain their dependencies and redacted inputs; they can proceed from
successful acquisition branches when another source fails. Partial outcomes
remain explicit in the investigation lifecycle. This graph does not imply that
a scientific conclusion was established: that remains contingent on applicable,
independently governed methods and sufficient evidence.

Execution checkpoints and append-only task events are available through a
replaceable journal, with a SQLite single-host adapter selected when a durable
storage path is configured. Checkpoints carry exact workflow fingerprints and
versioned output codecs. Explicit resumption reuses only successful compatible
checkpoints; a task with an uncertain prior attempt is replayed only when its
contract declares retry safety. Unsupported output types remain inspectable in
the current result but are explicitly marked as not checkpointed. SQLite event
records are immutable and hash chained. The API, SDK, workspace, and CLI expose
replayable live SSE over that journal. Distributed execution, cross-process
worker leases, and remote scheduling remain open capabilities.

---

## Example

User:

Why is this lake disappearing?

Investigation Engine produces

Mission

↓

Location Analysis

↓

Historical Imagery

↓

Rainfall Trends

↓

Groundwater

↓

Land Use Change

↓

Infrastructure

↓

Hydrology

↓

Evidence Collection

↓

Reasoning

↓

Report

---

# Phase 4 — Earth Reasoning Engine

## Goal

Combine evidence into trustworthy conclusions.

Reasoning is the core intelligence of SatQuery.

Models generate observations.

Reasoning generates understanding.

---

## Responsibilities

Evidence fusion

Cross-validation

Conflict resolution

Scientific inference

Confidence estimation

Uncertainty analysis

Hypothesis evaluation

Causal reasoning

Temporal reasoning

Spatial reasoning

Decision justification

---

## Principle

Every conclusion must be traceable to evidence.

---

# Phase 5 — Multi-Agent Intelligence

## Goal

Distribute scientific reasoning across specialized agents.

No single model should perform every task.

Instead, multiple domain agents collaborate.

---

## Initial Agents

Mission Agent

Planner Agent

Dataset Agent

Tool Agent

Execution Agent

Evidence Agent

Reasoning Agent

Verification Agent

Explanation Agent

Memory Agent

---

## Long-Term Vision

Future versions may include hundreds of specialized agents covering:

Agriculture

Climate

Floods

Wildfires

Urbanization

Oceanography

Ecology

Transportation

Disaster Management

Energy

Water Resources

Environmental Policy

Scientific Literature

And many more.

---

# Phase 6 — Earth Memory

## Goal

Enable SatQuery to remember the Earth.

Every investigation becomes knowledge.

Nothing valuable should be forgotten.

---

## Memory Includes

Investigations

Reports

Evidence

Images

Datasets

Seasonal trends

Historical observations

Reasoning chains

Confidence scores

Workflows

User missions

Environmental changes

Derived knowledge

---

## Long-Term Goal

Build a searchable planetary memory.

### Current implementation boundary

Earth Memory indexes immutable investigation artifacts, including safe
capability-selection snapshots, with deterministic literal search, explicit
source links, and optional SQLite durability. Its
spatiotemporal retrieval accepts explicit CRS-scoped bounding boxes and
timezone-aware intervals. Spatial filtering is inclusive envelope overlap in
the same CRS; it performs no reprojection or exact geometry predicate. SQLite
schema version 6 keeps derived extent indexes separate from immutable
source payloads and migrates prior index schemas transactionally. Unknown extents remain
unmatched for constrained searches. Semantic retrieval, exact geometry search,
planet-scale distributed indexing, and continuous change memory remain open
work.

Capability snapshots retain the public, source-neutral selection metadata
associated with a matrix revision and carry a separately verified content
digest. Raw dataset metadata, asset URIs, and connector source/provider payloads
are intentionally omitted; snapshots do not freeze or reproduce upstream data.

---

# Phase 7 — Continuous Earth Observation

## Goal

Observe Earth continuously instead of waiting for user questions.

SatQuery becomes proactive.

---

## Capabilities

Continuous monitoring

Current implementation: recurring mission-linked EarthQuery schedules can be
durably journaled when a platform storage path is configured, can be processed
by an opt-in local poller or explicit API/CLI tick, and execute as ordinary
versioned investigation workflows. Due investigations are claimed atomically
and dispatched with a configurable concurrency bound. Runs retain the exact
immutable schedule-definition revision that caused acquisition; scheduler
cursor advancement does not create configuration versions. A missed schedule
interval is coalesced and recorded; this scheduler does not itself infer change
or guarantee upstream acquisition availability. Workers renew durable leases;
expired or legacy unleased work is finalized as failed and is not automatically
replayed. Schedule/run events are journaled, indexed in Earth Memory, and exposed
alongside scheduler health. Schedule overlap policy can coalesce due work while
a prior run is active or allow overlapping investigations. Failures and partial
runs create durable local notifications with explicit acknowledgement state.
Schedule definitions can be revised with optimistic revision checks, and each
run remains linked to the definition revision that was current at claim time.
This provides local crash recovery without claiming exactly-once behavior for
external acquisitions; remote notification delivery remains adapter-dependent.

Change detection

Disaster detection

Anomaly detection

Environmental alerts

Trend discovery

Automatic investigations

Report generation

Event timelines

Monitoring missions

---

## Examples

Detect floods automatically.

Detect new roads.

Detect illegal mining.

Detect deforestation.

Detect shrinking reservoirs.

Detect wildfire scars.

Monitor glaciers.

Track crop health.

---

# Phase 8 — Earth Intelligence Platform

## Goal

Transform the intelligence engine into a complete platform.

---

## Components

Web Interface

REST API

Python SDK

CLI

Visualization

Interactive Maps

Mission Dashboard

Collaboration

Authentication

Organizations

Projects

Cloud deployment

Google Colab integration

Enterprise deployment

---

## Users

Researchers

Governments

Students

NGOs

Businesses

Environmental Agencies

Emergency Responders

Scientists

Policy Makers

---

# Phase 9 — Earth Intelligence Ecosystem

## Goal

Enable the world to extend SatQuery.

SatQuery should become an ecosystem rather than a standalone application.

---

## Community Contributions

New connectors

Reasoning modules

Analytical tools

Earth datasets

Scientific workflows

Domain agents

Visualization plugins

Research integrations

Benchmarks

Model adapters

---

## Long-Term Vision

Researchers contribute knowledge.

Governments contribute datasets.

Developers contribute tools.

Scientists contribute reasoning modules.

Organizations build specialized intelligence systems on top of SatQuery.

---

# Beyond the Roadmap

These phases are not the finish line.

They establish the core capabilities of an Earth Intelligence Operating System.

As technology evolves, new models, datasets, sensors, analytical methods, and reasoning systems will emerge.

SatQuery should never be constrained by today's tools.

Its architecture must be designed to continuously absorb future innovations while preserving scientific integrity and modularity.

The operating system should outlive any individual model, dataset, or technology.

---

# The Ultimate Vision

One day, anyone should be able to ask questions about the Earth as naturally as speaking to another person.

Students should understand how their cities have changed.

Scientists should investigate environmental change in minutes instead of weeks.

Governments should make evidence-based policy decisions.

Emergency responders should receive trustworthy situational intelligence during disasters.

Researchers should build upon a shared platform rather than repeatedly solving the same infrastructure problems.

SatQuery will not simply answer questions.

It will investigate.

It will reason.

It will explain.

It will remember.

It will continuously learn from the changing planet.

Our mission is not to build another AI application.

Our mission is to build the world's most trustworthy Earth Intelligence Operating System.
