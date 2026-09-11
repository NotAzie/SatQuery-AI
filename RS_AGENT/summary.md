# SatQuery AI Architecture

SatQuery AI keeps the useful question-to-capability workflow while owning its
runtime structure and vocabulary.

## Runtime flow

```text
Question + image path
        |
        v
SatQueryEngine.understand()
        |
        v
Task catalog -> capability catalog
        |
        v
GuidanceStore -> selected capability adapter -> result
```

## Canonical package

- `satquery_ai/orchestration/engine.py`: query lifecycle and routing decisions.
- `satquery_ai/orchestration/prompts.py`: SatQuery question-understanding prompt.
- `satquery_ai/task_catalog.py`: task vocabulary and strict label normalization.
- `satquery_ai/tools/catalog.py`: task-to-capability routes.
- `satquery_ai/tools/placeholders.py`: current capability adapters.
- `satquery_ai/guidance/store.py`: local guidance lookup and lazy custom-index fallback.
- `satquery_ai/configuration.py`: application configuration and path resolution.
- `satquery_ai/knowledge.py`: optional knowledge-engine boundary.

## Current runtime boundary

The understanding, guidance, routing, and response orchestration are functional.
The default image capabilities are intentionally placeholders. They receive the
image path through the tool interface and return fixed text; they do not run image
models or alter image files yet.

The `rs_agent/` package is retained only as a compatibility namespace for older
imports. The public ownership boundary is `satquery_ai`.
