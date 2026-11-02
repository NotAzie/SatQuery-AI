import type {
  EngineMission,
  EngineMissionCreate,
  EngineMonitoringComparison,
  EngineMonitoringNotification,
  EngineMonitoringTriggerHistory,
  EngineMonitoringRun,
  EngineMonitoringSchedule,
  EngineMonitoringScheduleCreate,
  EngineMonitoringScheduleUpdate,
} from "@/shared/types";

import { apiFetch } from "./client";

export function listMissions(signal?: AbortSignal): Promise<EngineMission[]> {
  return apiFetch("/monitoring/missions", { signal });
}

export function createMission(
  mission: EngineMissionCreate,
): Promise<EngineMission> {
  return apiFetch("/monitoring/missions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(mission),
  });
}

export function listMonitoringSchedules(
  signal?: AbortSignal,
): Promise<EngineMonitoringSchedule[]> {
  return apiFetch("/monitoring/schedules", { signal });
}

export function createMonitoringSchedule(
  schedule: EngineMonitoringScheduleCreate,
): Promise<EngineMonitoringSchedule> {
  return apiFetch("/monitoring/schedules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(schedule),
  });
}

export function reviseMonitoringSchedule(
  scheduleId: string,
  update: EngineMonitoringScheduleUpdate,
): Promise<EngineMonitoringSchedule> {
  return apiFetch(`/monitoring/schedules/${encodeURIComponent(scheduleId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
}

export function setMonitoringScheduleEnabled(
  scheduleId: string,
  enabled: boolean,
): Promise<EngineMonitoringSchedule> {
  return apiFetch(
    `/monitoring/schedules/${encodeURIComponent(scheduleId)}/${enabled ? "enable" : "disable"}`,
    { method: "POST" },
  );
}

export function listMonitoringRuns(
  scheduleId: string,
  signal?: AbortSignal,
): Promise<EngineMonitoringRun[]> {
  return apiFetch(
    `/monitoring/schedules/${encodeURIComponent(scheduleId)}/runs`,
    { signal },
  );
}

export function compareMonitoringSchedule(
  scheduleId: string,
  limit = 10,
  signal?: AbortSignal,
): Promise<EngineMonitoringComparison> {
  const query = new URLSearchParams({ limit: String(limit) });
  return apiFetch(
    `/monitoring/schedules/${encodeURIComponent(scheduleId)}/comparison?${query}`,
    { signal },
  );
}

export function listMonitoringNotifications(
  options: { scheduleId?: string; unreadOnly?: boolean; limit?: number } = {},
  signal?: AbortSignal,
): Promise<EngineMonitoringNotification[]> {
  const query = new URLSearchParams({
    unread_only: String(options.unreadOnly ?? false),
    limit: String(options.limit ?? 100),
  });
  if (options.scheduleId) query.set("schedule_id", options.scheduleId);
  return apiFetch(`/monitoring/notifications?${query}`, { signal });
}

export function acknowledgeMonitoringNotification(
  notificationId: string,
): Promise<EngineMonitoringNotification> {
  return apiFetch(
    `/monitoring/notifications/${encodeURIComponent(notificationId)}/acknowledge`,
    { method: "POST" },
  );
}

export function getMonitoringTriggers(
  scheduleId: string,
  limit = 100,
  cursor?: string,
  signal?: AbortSignal,
): Promise<EngineMonitoringTriggerHistory> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor) query.set("cursor", cursor);
  return apiFetch(
    `/monitoring/schedules/${encodeURIComponent(scheduleId)}/triggers?${query}`,
    { signal },
  );
}
