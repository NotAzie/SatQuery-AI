# `earth_platform/plugins`

**Purpose.** The extension contract.

**Belongs here**
- `api.py`, the only module third-party plugins import
- `PluginHost` Protocol; no concrete host is wired into the application

**Never here**
- Core feature code (first-party features use the same registries directly)
- Plugin-specific logic
- Anything that lets a plugin bypass registries

**Depends on.** `agent`, `llm`, `earth`, `settings`, `shared`.

**Public interface.** `Plugin`, `PluginManifest`, `PluginContext.register_provider_factory/tool_source/earth_layer/ui_panel`, `PluginHost`.
