import { describe, expect, it, vi } from "vitest";

import type { EarthCommandIssued } from "@/shared/types";

import {
  createEarthCommandDispatcher,
  UnsupportedEarthCommandError,
} from "./dispatcher";

const event = (
  command: EarthCommandIssued["command"],
): EarthCommandIssued => ({
  id: "evt-1",
  schema_version: 1,
  session_id: "ses-1",
  conversation_id: "ses-1",
  run_id: "run-1",
  seq: 1,
  at: "2026-11-01T10:00:00Z",
  type: "earth.command",
  command,
});

describe("EarthCommandDispatcher", () => {
  it("routes a typed fly-to event to the camera controller", async () => {
    const flyTo = vi.fn();
    const dispatcher = createEarthCommandDispatcher({ fly_to: flyTo });
    const command: EarthCommandIssued["command"] = {
      type: "fly_to",
      target: { lng: 12, lat: 48 },
      height_m: 150_000,
      duration_s: 2,
    };

    await expect(dispatcher.dispatch(event(command))).resolves.toBe(true);
    expect(flyTo).toHaveBeenCalledOnce();
    expect(flyTo).toHaveBeenCalledWith(command);
  });

  it("routes layer visibility commands to the live layer controller", async () => {
    const setVisibility = vi.fn();
    const dispatcher = createEarthCommandDispatcher({
      set_layer_visibility: setVisibility,
    });
    const command: EarthCommandIssued["command"] = {
      type: "set_layer_visibility",
      layer_id: "flights",
      visible: true,
      opacity: null,
    };

    await expect(dispatcher.dispatch(event(command))).resolves.toBe(true);
    expect(setVisibility).toHaveBeenCalledOnce();
    expect(setVisibility).toHaveBeenCalledWith(command);
  });

  it("ignores non-command Agent events", async () => {
    const flyTo = vi.fn();
    const dispatcher = createEarthCommandDispatcher({ fly_to: flyTo });

    await expect(
      dispatcher.dispatch({
        id: "evt-2",
        schema_version: 1,
        session_id: "ses-1",
        conversation_id: "ses-1",
        run_id: "run-1",
        seq: 2,
        at: "2026-11-01T10:00:00Z",
        type: "run.completed",
        finish_reason: "stop",
      }),
    ).resolves.toBe(false);
    expect(flyTo).not.toHaveBeenCalled();
  });

  it("surfaces commands without a workspace handler instead of simulating them", async () => {
    const dispatcher = createEarthCommandDispatcher({});
    const command: EarthCommandIssued["command"] = {
      type: "highlight_evidence",
      evidence_ids: ["ev-1"],
    };

    await expect(dispatcher.dispatch(event(command))).rejects.toThrow(
      UnsupportedEarthCommandError,
    );
    await expect(dispatcher.dispatch(event(command))).rejects.toThrow(
      "Earth command 'highlight_evidence' has no registered workspace handler",
    );
  });

  it("propagates controller failures to the event consumer", async () => {
    const failure = new Error("camera controller failed");
    const dispatcher = createEarthCommandDispatcher({
      fly_to: () => {
        throw failure;
      },
    });

    await expect(
      dispatcher.dispatch(
        event({
          type: "fly_to",
          target: { lng: 12, lat: 48 },
          height_m: null,
          duration_s: 0,
        }),
      ),
    ).rejects.toBe(failure);
  });
});
