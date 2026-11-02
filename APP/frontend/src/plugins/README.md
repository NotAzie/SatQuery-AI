# `src/plugins`

**Purpose.** Frontend plugin contracts and registration hosts.

**Belongs here**
- `PluginHostProvider` registries (panels, layer renderers), `PanelHost`, plugin types
- Runtime manifest retrieval and module loading are not implemented.

**Never here**
- Plugin-specific code

**Depends on.** `earth/layers`, `shared`.

**Public interface.** `FrontendPlugin.register(ctx)` contract, `PanelHost`, `usePluginHost`.
