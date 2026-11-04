import { describe, expect, it, vi } from "vitest";

import type { EarthController } from "./controller";
import { createEarthEventBus } from "./events";
import { restoreEarthContext } from "./restore";
import type { EarthContext } from "@/shared/types";
import { useEarthStore } from "@/state/earthStore";

function context(): EarthContext {
  const camera = {
    position: { lng: 12, lat: 34 },
    height_m: 1200,
    heading_deg: 15,
    pitch_deg: -45,
    roll_deg: 0,
    view_rect: null,
  };
  return {
    camera,
    viewport: null,
    layers: [],
    time: { start: "2024-01-01T00:00:00Z", end: "2024-01-03T00:00:00Z" },
    instant: "2024-01-02T00:00:00Z",
    timeline_playback: { playing: false, speed: 1 },
    selection: null,
    drawings: [],
    captures: [],
    imagery: [],
    overlays: [],
    secondary_view: null,
    investigations: { known_ids: [], visible_ids: [] },
    selected_evidence_ids: ["evidence-1"],
    bookmarks: [],
    camera_history: { past: [], present: camera, future: [] },
    split_view: { enabled: false, sync_cameras: false },
    measurement: null,
  };
}

describe("restoreEarthContext", () => {
  it("restores presentation state through controllers and publishes UI state", async () => {
    const saved = context();
    const controller = {
      camera: { restore: vi.fn() },
      timeline: { restore: vi.fn() },
      workspace: { replaceDrawings: vi.fn() },
      overlays: {
        restore: vi.fn().mockResolvedValue(undefined),
        highlight: vi.fn(),
        clear: vi.fn(),
      },
    } as unknown as EarthController;
    const events = createEarthEventBus();
    const received: unknown[] = [];
    events.subscribe((event) => received.push(event));

    await restoreEarthContext(saved, controller, null, events);

    expect(controller.camera.restore).toHaveBeenCalledWith(saved.camera);
    expect(controller.timeline.restore).toHaveBeenCalledWith({
      instant: new Date(saved.instant!),
      range: saved.time,
      playing: false,
      speed: 1,
    });
    expect(controller.workspace.replaceDrawings).toHaveBeenCalledWith([]);
    expect(controller.overlays.restore).toHaveBeenCalledWith([]);
    expect(controller.overlays.highlight).toHaveBeenCalledWith(["evidence-1"]);
    expect(useEarthStore.getState().camera).toEqual(saved.camera);
    expect(received).toContainEqual({ type: "earth.selection.changed", selection: null });
  });

  it("clears a stale secondary overlay when the saved view has no secondary pane", async () => {
    const saved = context();
    const primary = {
      camera: { restore: vi.fn() },
      timeline: { restore: vi.fn() },
      workspace: { replaceDrawings: vi.fn() },
      overlays: {
        restore: vi.fn().mockResolvedValue(undefined),
        highlight: vi.fn(),
        clear: vi.fn(),
      },
    } as unknown as EarthController;
    const secondary = {
      camera: { restore: vi.fn() },
      overlays: {
        restore: vi.fn().mockResolvedValue(undefined),
        highlight: vi.fn(),
        clear: vi.fn(),
      },
    } as unknown as EarthController;

    await restoreEarthContext(saved, primary, secondary, createEarthEventBus());

    expect(secondary.overlays.clear).toHaveBeenCalledOnce();
    expect(secondary.overlays.highlight).toHaveBeenCalledWith([]);
  });
});
