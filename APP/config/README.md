# `config`

**Purpose.** Declarative, layered configuration (no secrets).

**Belongs here**
- `base.yaml` defaults
- `providers/*.yaml` every known LLM endpoint, disabled
- `environments/{development,production,test}.yaml`
- `profiles/*.yaml` composable overlays: `local-models`, `hosted-apis`

**Never here**
- API keys or tokens (use environment variables named by `*_env`)
- Per-developer overrides (use `.env`)

**Depends on.** Read by `earth_platform.settings`.

**Public interface.** Load order: base, providers, environment, profiles, then `EARTH_*` environment variables.
