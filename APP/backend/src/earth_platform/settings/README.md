# `earth_platform/settings`

**Purpose.** Typed, layered configuration.

**Belongs here**
- Pydantic sections (`models.py`), the root `Settings`, and the YAML+env `loader.py`

**Never here**
- Secrets as values (sections name an env var, e.g. `api_key_env`)
- Reading configuration from anywhere except through `Settings`
- Behaviour: it describes, others act

**Depends on.** `shared`.

**Public interface.** `Settings`, `load_settings(environment=, profiles=, config_dir=)`, `ProviderSettings`.
