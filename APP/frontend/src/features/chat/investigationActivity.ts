import type { AgentEvent, EngineInvestigationEvent } from "@/shared/types";

export interface InvestigationActivityItem {
  id: string;
  eventType: string;
  at: string;
}

export function investigationActivityFromEvent(
  event: AgentEvent,
): InvestigationActivityItem | null {
  if (event.type !== "engine.event" || event.engine_kind !== "investigation.progress") {
    return null;
  }
  const eventType = event.payload.event_type;
  if (typeof eventType !== "string" || eventType.trim().length === 0) return null;

  return {
    id: `${event.engine_turn_id}:${event.engine_sequence}`,
    eventType,
    at: event.engine_timestamp,
  };
}

export function investigationActivityFromJournalEvent(
  event: EngineInvestigationEvent,
): InvestigationActivityItem {
  return {
    id: `${event.plan_id}:${event.sequence}`,
    eventType: event.event_type,
    at: event.timestamp,
  };
}

export function formatInvestigationEventType(eventType: string): string {
  return eventType
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
