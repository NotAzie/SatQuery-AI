# Plugins

A plugin can contribute **LLM providers**, **tools**, **Earth layers** and **UI panels**.

## Backend half

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

## Frontend half

The manifest's `frontend_entry` is an ES module whose default export is a `FrontendPlugin`:

```ts
export default { register(ctx) { ctx.registerPanel({ id: "watch", title: "Watch", slot: "right", component: WatchPanel }) } }
```

The app loads advertised modules at runtime, so plugins ship without rebuilding the frontend. A new
layer `kind` also needs a frontend `LayerRenderer` registered here.

## Guarantees

- Contributions are tracked by owner and removed together on unload (`Registry.unregister_owner`).
- A plugin that fails to load is marked `failed`; startup continues.
- `api_version` is checked against `PLUGIN_API_VERSION`; incompatible plugins are not loaded.
- Plugins import only `earth_platform.plugins.api` (and the types it re-exports).

Plugin-specific settings live under `plugins.config.<plugin_id>` in configuration.

Not yet specified: permission model, sandboxing of tool execution, plugin signing.
