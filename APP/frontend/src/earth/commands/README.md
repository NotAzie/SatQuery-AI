# Earth command dispatcher

**Purpose.** Route typed server-issued `earth.command` events to the Cesium workspace controllers.

**Belongs here**
- Exhaustive routing by `EarthCommand.type`
- Presentation-only event dispatch and explicit unsupported-handler errors

**Never here**
- Constructing commands from prompts, chat text, tool results, or local heuristics
- Scientific calculations or interpretation of evidence payloads
- Direct Cesium manipulation (delegate through `EarthController` slices)

**Public interface.** `createEarthCommandDispatcher(handlers).dispatch(AgentEvent)`.
Handlers are registered by the Earth controller when each workspace capability is implemented.
