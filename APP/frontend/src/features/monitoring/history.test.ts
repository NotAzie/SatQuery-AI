import { describe, expect, it } from "vitest";

import type { EngineMonitoringTriggerHistory } from "@/shared/types";
import { appendTriggerHistoryPage } from "./history";

function history(
  overrides: Partial<EngineMonitoringTriggerHistory> = {},
): EngineMonitoringTriggerHistory {
  return {
    schedule_id: "schedule-1",
    schedule_revision: 3,
    policies: [],
    events: [],
    next_cursor: null,
    has_more: false,
    ...overrides,
  };
}

describe("appendTriggerHistoryPage", () => {
  it("appends events in page order and advances the cursor", () => {
    const first = history({
      events: [
        {
          event_id: "event-1",
          event_type: "trigger_evaluated",
          schedule_id: "schedule-1",
          run_id: "run-1",
          occurred_at: "2026-11-02T10:00:00Z",
          payload: {},
        },
      ],
      next_cursor: "cursor-1",
      has_more: true,
    });
    const next = history({
      events: [
        {
          event_id: "event-2",
          event_type: "trigger_matched",
          schedule_id: "schedule-1",
          run_id: "run-2",
          occurred_at: "2026-11-02T11:00:00Z",
          payload: {},
        },
      ],
      next_cursor: null,
      has_more: false,
    });

    expect(appendTriggerHistoryPage(first, next)).toEqual({
      ...next,
      events: [...first.events, ...next.events],
    });
  });

  it("does not duplicate events returned on adjacent pages", () => {
    const event = {
      event_id: "event-1",
      event_type: "trigger_evaluated" as const,
      schedule_id: "schedule-1",
      run_id: null,
      occurred_at: "2026-11-02T10:00:00Z",
      payload: {},
    };

    expect(appendTriggerHistoryPage(
      history({ events: [event], has_more: true, next_cursor: "cursor-1" }),
      history({ events: [event, event], has_more: false }),
    )?.events).toEqual([event]);
  });

  it("rejects pages from another schedule revision", () => {
    expect(appendTriggerHistoryPage(
      history(),
      history({ schedule_revision: 4 }),
    )).toBeNull();
    expect(appendTriggerHistoryPage(
      history(),
      history({ schedule_id: "schedule-2" }),
    )).toBeNull();
  });
});
