# Agent system status

SatQuery does not currently contain a multi-agent execution runtime. The
roadmap describes agent collaboration as a future capability; it must not be
read as an existing product feature.

## What exists today

The platform has a deterministic planner, investigation design and workflow
DAG, component registries, replaceable task handlers, scientific operator and
method registries, and an execution trace. A single `PlatformRuntime`
composes and runs the investigation. These are useful foundations for future
orchestration but are not agents: they do not independently set goals,
negotiate, delegate, critique one another, or exchange messages.

Model adapter contracts exist, and the legacy image question-answering path
can load Hugging Face models with optional dependencies. The scientific
reasoning path does not call a general-purpose model to generate scientific
conclusions.

## Not implemented

- Agent identity, role policy, or independent context/state.
- Inter-agent communication, delegation, consensus, or conflict arbitration.
- Agent scheduling, budgets, sandboxing, or trust isolation.
- Autonomous modification of plans based on model-generated scientific claims.
- Multi-agent evaluation or benchmark assets.

Any future agent runtime must operate on explicit platform contracts, retain
the same provenance/audit trail, and keep model-generated proposals separate
from validated evidence and conclusions. See the [roadmap](../foundation/ROADMAP.md#phase-5--multi-agent-intelligence).
