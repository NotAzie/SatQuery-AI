import type { EngineMonitoringTriggerHistory } from "@/shared/types";

export function appendTriggerHistoryPage(
  current: EngineMonitoringTriggerHistory,
  next: EngineMonitoringTriggerHistory,
): EngineMonitoringTriggerHistory | null {
  if (
    current.schedule_id !== next.schedule_id ||
    current.schedule_revision !== next.schedule_revision
  ) {
    return null;
  }

  const eventIds = new Set(current.events.map((event) => event.event_id));
  return {
    ...next,
    events: [
      ...current.events,
      ...next.events.filter((event) => {
        if (eventIds.has(event.event_id)) return false;
        eventIds.add(event.event_id);
        return true;
      }),
    ],
  };
}
