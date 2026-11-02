import { describe, expect, it } from "vitest";

import type {
  EngineEarthQuery,
  EngineMonitoringSchedule,
  EngineMonitoringTriggerPolicy,
} from "@/shared/types";
import {
  buildMonitoringScheduleUpdate,
  buildTriggerPolicies,
  canEditMonitoringBounds,
  monitoringScheduleDraft,
  parseWgs84Bounds,
  parseTriggerOperator,
  triggerPolicyDraft,
} from "./form";

describe("parseWgs84Bounds", () => {
  it("parses ordered WGS 84 bounds", () => {
    expect(parseWgs84Bounds("-123, 36, -121, 38")).toEqual([-123, 36, -121, 38]);
  });

  it.each([
    "",
    ",0,1,1",
    "0,0,1",
    "-181,0,1,1",
    "0,-91,1,1",
    "0,1,1,0",
    "0,0,0,1",
    "west,0,1,1",
    "0,0,Infinity,1",
  ])("rejects invalid bounds: %s", (value) => {
    expect(parseWgs84Bounds(value)).toBeNull();
  });
});

describe("monitoring trigger policy edits", () => {
  const query: EngineEarthQuery = {
    bbox: [-123, 36, -121, 38],
    point: null,
    geometry: null,
    temporal_start: null,
    temporal_end: null,
    crs: "OGC:CRS84",
    spatial_resolution: null,
    resolution_unit: null,
    requested_dataset_ids: [],
    requested_variables: ["shoreline"],
    requested_modalities: [],
    required_capabilities: [],
    region: null,
    filters: {},
    asset_preferences: [],
    asset_sampling: null,
    raster_analysis: null,
    raster_pixel_selection: null,
    raster_weighting: null,
    raster_semantics: {},
    raster_component_extraction: [],
  };
  const existing: EngineMonitoringTriggerPolicy = {
    policy_id: "policy-1",
    name: "Original",
    canonical_variable: "shoreline_change",
    unit: "m/year",
    operator: "gte",
    threshold: 2,
    follow_up_query: query,
    cooldown_seconds: 60,
    max_attempts: 2,
    retry_safe: true,
  };
  const schedule: EngineMonitoringSchedule = {
    schedule_id: "schedule-1",
    mission_id: "mission-1",
    name: "Original schedule",
    earth_query: query,
    interval_seconds: 86400,
    rolling_window_seconds: 3600,
    priority: 0,
    overlap_policy: "skip_while_running",
    trigger_policies: [existing],
    enabled: true,
    next_run_at: "2026-11-02T10:00:00Z",
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    revision: 4,
  };

  it("revises policy fields while preserving Engine-owned follow-up settings", () => {
    const policies = buildTriggerPolicies(
      [{
        ...triggerPolicyDraft(existing),
        name: "Updated",
        threshold: "3.5",
      }],
      [existing],
      query,
    );

    expect(policies).toEqual([{
      ...existing,
      name: "Updated",
      threshold: 3.5,
    }]);
  });

  it("creates new policies with the schedule query and conservative defaults", () => {
    const policies = buildTriggerPolicies(
      [{
        policy_id: "policy-2",
        name: "New",
        canonical_variable: "shoreline_change",
        unit: "m/year",
        operator: "abs_gte",
        threshold: "0",
      }],
      [],
      query,
    );

    expect(policies).toEqual([{
      policy_id: "policy-2",
      name: "New",
      canonical_variable: "shoreline_change",
      unit: "m/year",
      operator: "abs_gte",
      threshold: 0,
      follow_up_query: query,
      cooldown_seconds: 0,
      max_attempts: 1,
      retry_safe: false,
    }]);
  });

  it("only accepts Engine-supported trigger operators", () => {
    expect(parseTriggerOperator("abs_gt")).toBe("abs_gt");
    expect(parseTriggerOperator("unknown")).toBeNull();
  });

  it("allows removing every existing policy", () => {
    expect(buildTriggerPolicies([], [existing], query)).toEqual([]);
  });

  it("builds a revision patch for edited schedule fields and preserves query scope", () => {
    const draft = {
      ...monitoringScheduleDraft(schedule),
      name: "Updated schedule",
      bbox: "-122, 35, -120, 37",
      variables: "wind, shoreline",
      intervalHours: "12",
      rollingWindowHours: "2",
      priority: "5",
      overlapPolicy: "allow" as const,
    };
    const policies = [{
      ...triggerPolicyDraft(existing),
      threshold: "3",
    }];

    expect(buildMonitoringScheduleUpdate(schedule, draft, policies)).toEqual({
      expected_revision: 4,
      name: "Updated schedule",
      earth_query: {
        ...query,
        bbox: [-122, 35, -120, 37],
        requested_variables: ["wind", "shoreline"],
      },
      interval_seconds: 43200,
      rolling_window_seconds: 7200,
      priority: 5,
      overlap_policy: "allow",
      trigger_policies: [{ ...existing, threshold: 3 }],
    });
  });

  it("rejects no-op, invalid, and unsupported spatial edits", () => {
    const initial = monitoringScheduleDraft(schedule);
    expect(buildMonitoringScheduleUpdate(schedule, initial, [triggerPolicyDraft(existing)]))
      .toBeNull();
    expect(buildMonitoringScheduleUpdate(
      schedule,
      { ...initial, bbox: "0,0,0,1" },
      [triggerPolicyDraft(existing)],
    )).toBeNull();
    expect(buildMonitoringScheduleUpdate(
      schedule,
      { ...initial, intervalHours: "0" },
      [triggerPolicyDraft(existing)],
    )).toBeNull();
    const pointSchedule = {
      ...schedule,
      earth_query: { ...query, bbox: null, point: [-122, 37] as [number, number] },
    };
    expect(canEditMonitoringBounds(pointSchedule)).toBe(false);
    expect(buildMonitoringScheduleUpdate(
      pointSchedule,
      { ...monitoringScheduleDraft(pointSchedule), bbox: "-123,36,-121,38" },
      [triggerPolicyDraft(existing)],
    )).toBeNull();
  });

  it.each([
    { name: "", threshold: "1" },
    { name: "Policy", threshold: "" },
    { name: "Policy", threshold: "-1", operator: "abs_gte" as const },
    { name: "Policy", threshold: "NaN" },
  ])("rejects incomplete or invalid policy edits: %o", (draft) => {
    expect(buildTriggerPolicies(
      [{
        ...triggerPolicyDraft(existing),
        ...draft,
      }],
      [existing],
      query,
    )).toBeNull();
  });

  it("allows removing a rolling window and rejects invalid durations", () => {
    const initial = monitoringScheduleDraft(schedule);
    expect(
      buildMonitoringScheduleUpdate(
        schedule,
        { ...initial, rollingWindowHours: "" },
        [triggerPolicyDraft(existing)],
      ),
    ).toEqual({
      expected_revision: 4,
      rolling_window_seconds: null,
    });
    expect(
      buildMonitoringScheduleUpdate(
        schedule,
        { ...initial, rollingWindowHours: "-1" },
        [triggerPolicyDraft(existing)],
      ),
    ).toBeNull();
  });
});
