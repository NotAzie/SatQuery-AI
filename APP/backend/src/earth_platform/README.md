# `earth_platform`

**Purpose.** The backend application: one Python package, layered so dependencies only point downward (enforced by import-linter).

**Belongs here**
- `main.py` app factory, `lifecycle.py` startup/shutdown, `container.py` composition root, `logging.py`

**Never here**
- Domain logic (belongs in a module below)
- Engine/vendor SDK imports outside their adapter module
- Module-level singletons or import-time side effects

**Depends on.** Everything below it; it is the top of the dependency graph.

**Public interface.** `create_app(settings=None) -> FastAPI`, `Container`, `build_container(settings)`.
