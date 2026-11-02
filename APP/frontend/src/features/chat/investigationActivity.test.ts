import { describe, expect, it } from "vitest";

import type { AgentEvent } from "@/shared/types";

type EngineEvent = Extract<AgentEvent, { type: "engine.event" }>;

import {
  formatInvestigationEventType,
  investigationActivityFromEvent,
} from "./investigationActivity";

function progressEvent(payload: Record<string, unknown>): EngineEvent {
  return {
    type: "engine.event",
    id: "event-1",
    session_id: "session-1",
    conversation_id: "session-1",
    run_id: "run-1",
    seq: 4,
    schema_version: 1,
    at: "2026-11-02T10:00:00Z",
    engine_session_id: "engine-session-1",
    engine_kind: "investigation.progress",
    engine_turn_id: "turn-1",
    engine_sequence: 8,
    engine_timestamp: "2026-11-02T10:00:01Z",
    payload,
  };
}

describe("investigation activity", () => {
  it("extracts only the ordered journal event type from investigation progress", () => {
    expect(
      investigationActivityFromEvent(
        progressEvent({
          sequence: 2,
          plan_id: "plan-1",
          event_type: "task.completed",
          payload: { task_id: "task-1", output: { private_detail: "not rendered" } },
        }),
      ),
    ).toEqual({
      id: "turn-1:8",
      eventType: "task.completed",
      at: "2026-11-02T10:00:01Z",
    });
  });

  it("ignores malformed and unrelated events", () => {
    expect(investigationActivityFromEvent(progressEvent({ payload: {} }))).toBeNull();
    const unrelated: EngineEvent = {
      ...progressEvent({ event_type: "task.completed" }),
      engine_kind: "tool.completed",
    };
    expect(investigationActivityFromEvent(unrelated)).toBeNull();
  });

  it("formats journal event names for display", () => {
    expect(formatInvestigationEventType("task.completed")).toBe("Task Completed");
  });
});
