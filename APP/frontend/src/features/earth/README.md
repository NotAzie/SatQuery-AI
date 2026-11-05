# `src/features/earth`

**Purpose.** Engine capability discovery exposed through the SatQuery product workspace. God’s Eye
View owns the Earth workspace controls, including layer selection, navigation, scenes, drawing,
measurement, and other Earth interactions.

**Belongs here**
- Presenting Engine-authored registered dataset and image-analysis capability metadata
- Displaying the versioned Earth modality snapshot and registered Agent tool schemas

**Never here**
- Cesium imports or scene manipulation
- Scientific calculations outside the Engine

**Public interface.** `EngineDiscoveryPanel`, available from the command notch's workspace drawer.
Engine discovery uses the Platform's typed discovery endpoint. It displays consent visibility and
does not invoke tools. Dataset registrations do not guarantee data access or scientific suitability.
