# ADR 0003: The Earth is the workspace

**Status:** accepted

**Context.** The product should feel like an immersive Earth, not a chat window with a map.

**Decision.** The globe is mounted once and persists across routes; panels float above it in named
slots. The backend drives it with typed `EarthCommand`s carried in the same event stream as chat. The
frontend reports `EarthContext` (camera, layers, time, selection) back with requests.

**Consequences.** Cesium is isolated behind `EarthController`. Routes do not remount the globe.
Questions can be grounded in what the user is looking at. Commands are presentation-only, so replaying
an event log reproduces the visual story.
