# Dependency graph

## Backend layers (enforced)

An arrow means "may import". Modules on the same row never import each other. The rule lives in
`backend/pyproject.toml` (`[tool.importlinter]`) and runs as `make lint-imports` and in CI.

```mermaid
flowchart TD
  main --> lifecycle & api
  lifecycle --> container
  api --> container
  container --> plugins & streaming
  plugins --> agent
  streaming --> agent
  agent --> vision
  vision --> llm
  agent --> engine & earth & sessions & llm
  llm & engine & earth & sessions --> settings
  settings --> shared
```

| Layer (top to bottom) | Modules |
|---|---|
| 1 | `main` |
| 2 | `lifecycle`, `api` |
| 3 | `container` |
| 4 | `plugins`, `streaming` |
| 5 | `agent` |
| 6 | `vision` |
| 7 | `llm`, `engine`, `earth`, `sessions` |
| 8 | `settings` |
| 9 | `shared` |

## Frontend

```mermaid
flowchart TD
  app --> features & plugins & earth & state
  features --> components & hooks & services & state & plugins
  hooks --> earth & state
  plugins --> earth
  earth --> state
  services --> shared
  state --> shared
  components --> shared
  earth --> shared
```

`earth` is the only folder importing `cesium`. `features` never import each other.

## Cross-stack

```mermaid
flowchart LR
  models["backend pydantic models"] -->|scripts/export_contracts.py| schema["contracts/schema.json"]
  schema -->|npm run gen:contracts| ts["frontend/src/shared/generated"]
```
