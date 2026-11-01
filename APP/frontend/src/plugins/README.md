# `src/plugins`

**Purpose.** Frontend half of the plugin system.

**Belongs here**
- `PluginHostProvider` registries (panels, layer renderers), `PanelHost`, plugin types

**Never here**
- Plugin-specific code

**Depends on.** `earth/layers`, `shared`.

**Public interface.** `FrontendPlugin.register(ctx)`, `PanelHost`, `usePluginHost`.
