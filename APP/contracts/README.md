# `contracts`

**Purpose.** Generated wire contracts, the single source of truth shared by backend and frontend.

**Belongs here**
- `schema.json` JSON Schema exported from the pydantic models

**Never here**
- Hand edits: run `make contracts`

**Depends on.** Produced by `scripts/export_contracts.py`; consumed by `frontend` codegen.

**Public interface.** `schema.json`.
