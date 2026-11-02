import type {
  EngineEarthQuery,
  EngineMonitoringSchedule,
  EngineMonitoringScheduleUpdate,
  EngineMonitoringTriggerPolicy,
} from "@/shared/types";

export type Wgs84Bounds = [west: number, south: number, east: number, north: number];

export interface TriggerPolicyDraft {
  policy_id: string;
  name: string;
  canonical_variable: string;
  unit: string;
  operator: EngineMonitoringTriggerPolicy["operator"];
  threshold: string;
}

export interface MonitoringScheduleDraft {
  name: string;
  bbox: string;
  variables: string;
  intervalHours: string;
  rollingWindowHours: string;
  priority: string;
  overlapPolicy: EngineMonitoringSchedule["overlap_policy"];
}

export function canEditMonitoringBounds(schedule: EngineMonitoringSchedule): boolean {
  const query = schedule.earth_query;
  return (
    query.bbox !== null &&
    query.bbox.length === 4 &&
    query.geometry === null &&
    query.point === null &&
    query.region === null
  );
}

export function monitoringScheduleDraft(
  schedule: EngineMonitoringSchedule,
): MonitoringScheduleDraft {
  return {
    name: schedule.name,
    bbox: canEditMonitoringBounds(schedule) ? schedule.earth_query.bbox?.join(", ") ?? "" : "",
    variables: schedule.earth_query.requested_variables.join(", "),
    intervalHours: String(schedule.interval_seconds / 3600),
    rollingWindowHours:
      schedule.rolling_window_seconds === null
        ? ""
        : String(schedule.rolling_window_seconds / 3600),
    priority: String(schedule.priority),
    overlapPolicy: schedule.overlap_policy,
  };
}

export function parseWgs84Bounds(value: string): Wgs84Bounds | null {
  const parts = value.split(",").map((part) => part.trim());
  if (parts.length !== 4 || parts.some((part) => part.length === 0)) return null;
  const coordinates = parts.map(Number);
  if (!coordinates.every(Number.isFinite)) return null;
  const [west, south, east, north] = coordinates;
  if (
    west === undefined ||
    south === undefined ||
    east === undefined ||
    north === undefined ||
    west < -180 ||
    west > 180 ||
    east < -180 ||
    east > 180 ||
    south < -90 ||
    south > 90 ||
    north < -90 ||
    north > 90 ||
    west >= east ||
    south >= north
  ) {
    return null;
  }
  return [west, south, east, north];
}

export function parseTriggerThreshold(
  value: string,
  operator: EngineMonitoringTriggerPolicy["operator"],
): number | null {
  if (!value.trim()) return null;
  const threshold = Number(value);
  if (!Number.isFinite(threshold)) return null;
  if (operator.startsWith("abs_") && threshold < 0) return null;
  return threshold;
}

export function parseTriggerOperator(
  value: string,
): EngineMonitoringTriggerPolicy["operator"] | null {
  switch (value) {
    case "gt":
    case "gte":
    case "lt":
    case "lte":
    case "abs_gt":
    case "abs_gte":
      return value;
    default:
      return null;
  }
}

export function triggerPolicyDraft(
  policy: EngineMonitoringTriggerPolicy,
): TriggerPolicyDraft {
  return {
    policy_id: policy.policy_id,
    name: policy.name,
    canonical_variable: policy.canonical_variable,
    unit: policy.unit,
    operator: policy.operator,
    threshold: String(policy.threshold),
  };
}

export function buildTriggerPolicies(
  drafts: readonly TriggerPolicyDraft[],
  existing: readonly EngineMonitoringTriggerPolicy[],
  followUpQuery: EngineEarthQuery,
): EngineMonitoringTriggerPolicy[] | null {
  const policyIds = new Set<string>();
  const policies: EngineMonitoringTriggerPolicy[] = [];

  for (const draft of drafts) {
    const threshold = parseTriggerThreshold(draft.threshold, draft.operator);
    if (
      !draft.policy_id.trim() ||
      policyIds.has(draft.policy_id) ||
      !draft.name.trim() ||
      !draft.canonical_variable.trim() ||
      !draft.unit.trim() ||
      threshold === null
    ) {
      return null;
    }

    policyIds.add(draft.policy_id);
    const previous = existing.find((policy) => policy.policy_id === draft.policy_id);
    policies.push({
      ...(previous ?? {
        policy_id: draft.policy_id,
        follow_up_query: followUpQuery,
        cooldown_seconds: 0,
        max_attempts: 1,
        retry_safe: false,
      }),
      name: draft.name.trim(),
      canonical_variable: draft.canonical_variable.trim(),
      unit: draft.unit.trim(),
      operator: draft.operator,
      threshold,
    });
  }

  return policies;
}

export function parseRollingWindowHours(value: string): number | null | undefined {
  if (!value.trim()) return null;
  const hours = Number(value);
  const seconds = Math.round(hours * 3600);
  return Number.isFinite(hours) && hours > 0 && seconds > 0 ? seconds : undefined;
}

export function buildMonitoringScheduleUpdate(
  schedule: EngineMonitoringSchedule,
  draft: MonitoringScheduleDraft,
  policyDrafts: readonly TriggerPolicyDraft[],
): EngineMonitoringScheduleUpdate | null {
  const update: EngineMonitoringScheduleUpdate = {
    expected_revision: schedule.revision,
  };
  const name = draft.name.trim();
  if (!name) return null;
  if (name !== schedule.name) update.name = name;

  const initialDraft = monitoringScheduleDraft(schedule);
  if (draft.bbox !== initialDraft.bbox) {
    if (!canEditMonitoringBounds(schedule)) return null;
    const bbox = parseWgs84Bounds(draft.bbox);
    if (!bbox) return null;
    update.earth_query = { ...schedule.earth_query, bbox };
  }

  const variables = draft.variables
    .split(",")
    .map((variable) => variable.trim())
    .filter(Boolean);
  if (
    JSON.stringify(variables) !==
    JSON.stringify(schedule.earth_query.requested_variables)
  ) {
    update.earth_query = {
      ...(update.earth_query ?? schedule.earth_query),
      requested_variables: variables,
    };
  }

  const hours = Number(draft.intervalHours);
  const intervalSeconds = Math.round(hours * 3600);
  if (!Number.isFinite(hours) || hours <= 0 || intervalSeconds < 1) return null;
  if (intervalSeconds !== schedule.interval_seconds) {
    update.interval_seconds = intervalSeconds;
  }

  const rollingWindowSeconds = parseRollingWindowHours(draft.rollingWindowHours);
  if (rollingWindowSeconds === undefined) return null;
  if (rollingWindowSeconds !== schedule.rolling_window_seconds) {
    update.rolling_window_seconds = rollingWindowSeconds;
  }

  const priority = Number(draft.priority);
  if (!Number.isInteger(priority) || priority < 0 || priority > 100) return null;
  if (priority !== schedule.priority) update.priority = priority;

  if (draft.overlapPolicy !== schedule.overlap_policy) {
    update.overlap_policy = draft.overlapPolicy;
  }

  const policies = buildTriggerPolicies(
    policyDrafts,
    schedule.trigger_policies,
    update.earth_query ?? schedule.earth_query,
  );
  if (policies === null) return null;
  if (JSON.stringify(policies) !== JSON.stringify(schedule.trigger_policies)) {
    update.trigger_policies = policies;
  }

  return Object.keys(update).length > 1 ? update : null;
}
