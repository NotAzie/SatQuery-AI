# Monitoring

The registered `MonitoringPanel` creates Engine-owned missions and recurring schedules, toggles
schedule state, and reads run history and recent-run comparisons. It submits a declared WGS 84
bounding box and optional requested variables; Engine owns schedule execution and the resulting
investigations. The panel lists and acknowledges the Engine's operational notifications for partial
and failed runs. Schedule creation can include Engine-evaluated descriptive-measurement triggers;
operators can edit or remove those policies through a revision-checked Engine update, and inspect
trigger activity returned by the Engine. The same schedule editor supports revision-checked changes
to its name, query variables, simple WGS 84 rectangle, interval, optional rolling-window duration,
priority, and overlap policy. A rolling window is anchored to each persisted run's start time and
cannot be combined with fixed EarthQuery times. Resolved bounds are shown in run history. Unedited
query dimensions and existing policies' follow-up queries are preserved.

The panel displays Engine-authored comparison text, its digest, and its limitations. The current
schedule contract supports Engine-resolved rolling temporal windows; it does not provide
Platform-side alert interpretation. Trigger activity is loaded in cursor-paged chunks from the
Engine, retaining event order and deduplicating overlapping events.
