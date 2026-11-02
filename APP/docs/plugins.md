# Plugin extension contracts

## Current status

Plugin runtime loading is not wired into the Platform. The backend defines the
`PluginManifest`, `Plugin`, `PluginContext`, and `PluginHost` contracts, but there is no concrete
host that discovers or loads plugins and the application lifecycle does not invoke one. The
frontend provides registries and `PanelHost`, but it does not fetch plugin manifests or dynamically
import frontend modules. These types and registries are extension points, not proof that plugins
are currently loaded.

## Intended backend contract

The following is an illustrative future interface, not an active loading path.

A Python distribution exposes an entry point in group `earth_platform.plugins` resolving to an object
implementing `Plugin` (`earth_platform.plugins.api`):

```python
class MiningWatch:
    manifest = PluginManifest(id="acme.mining-watch", name="Mining Watch", version="0.1.0",
                              provides=["tool_source", "earth_layer", "ui_panel"],
                              frontend_entry="/plugins/acme.mining-watch/index.js")
    async def register(self, ctx: PluginContext) -> None:
        ctx.register_tool_source(...)
        ctx.register_earth_layer(LayerSpec(...))
        ctx.register_ui_panel(PanelContribution(id="watch", title="Watch", slot="right", component="WatchPanel"))
    async def shutdown(self) -> None: ...
```

## Intended frontend contract

If a trusted plugin loader is implemented, a manifest's `frontend_entry` could identify an ES module
whose default export implements `FrontendPlugin`:

```ts
export default { register(ctx) { ctx.registerPanel({ id: "watch", title: "Watch", slot: "right", component: WatchPanel }) } }
```

The intended loader would import advertised modules at runtime. No backend manifest endpoint or
frontend module loader currently connects this contract. A new layer `kind` would also need a
frontend `LayerRenderer` registered by that future loader.

## Requirements before runtime loading

- Define which administrators may install and configure plugins.
- Define the trust boundary for Python code, which otherwise runs with the backend process's
  authority; the current interface does not provide sandboxing or a permission model.
- Define how frontend modules are served, authenticated, and constrained by browser security policy.
- Implement and test registration ownership, API-version checks, failure isolation, unload, and
  shutdown before claiming those lifecycle guarantees.

Plugin-specific settings live under `plugins.config.<plugin_id>` in configuration.
