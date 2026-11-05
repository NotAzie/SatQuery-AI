import { afterEach, describe, expect, it, vi } from "vitest";

import type { LayerState } from "@/shared/types";

import {
  createGodsEyeLayerController,
  isGodsEyeRuntime,
  openGodsEyeProviderSettings,
} from "./godsEyeRuntime";

afterEach(() => vi.unstubAllGlobals());

function dataManager() {
  const states = [
    { id: "flights", name: "Flights", enabled: true },
    { id: "earthquakes", name: "Earthquakes", enabled: false },
  ];
  return {
    getAll: vi.fn(() => states.map((state) => ({ ...state }))),
    setEnabled: vi.fn(async (id: string, enabled: boolean) => {
      const state = states.find((item) => item.id === id);
      if (!state) return;
      state.enabled = enabled;
    }),
    subscribe: vi.fn(() => () => {}),
  };
}

describe("God's Eye runtime integration", () => {
  it("accepts only a runtime with a live viewer and the required layer API", () => {
    expect(
      isGodsEyeRuntime({
        viewer: { scene: {}, camera: {} },
        dataManager: dataManager(),
      }),
    ).toBe(true);
    expect(isGodsEyeRuntime({ viewer: {}, dataManager: dataManager() })).toBe(false);
    expect(isGodsEyeRuntime(null)).toBe(false);
  });

  it("opens provider settings through the runtime action when available", async () => {
    const openProviderSettings = vi.fn(async () => true);
    vi.stubGlobal("window", { __godsEyeView: { openProviderSettings } });

    await expect(openGodsEyeProviderSettings()).resolves.toBe(true);
    expect(openProviderSettings).toHaveBeenCalledOnce();
  });

  it("reports provider settings unavailable when the runtime has no action", async () => {
    vi.stubGlobal("window", { __godsEyeView: undefined });

    await expect(openGodsEyeProviderSettings()).resolves.toBe(false);
  });

  it("mirrors registered layer state and routes visibility through the real lifecycle", async () => {
    const manager = dataManager();
    const controller = createGodsEyeLayerController(manager);

    expect(controller.getState()).toEqual([
      { layer_id: "flights", opacity: 1, visible: true },
      { layer_id: "earthquakes", opacity: 1, visible: false },
    ]);

    await controller.setVisibility("earthquakes", true);
    expect(manager.setEnabled).toHaveBeenCalledWith(
      "earthquakes",
      true,
      { origin: "tool" },
    );
    expect(controller.getState()[1]?.visible).toBe(true);
  });

  it("restores every registered layer and rejects unavailable or unsupported state", async () => {
    const manager = dataManager();
    const controller = createGodsEyeLayerController(manager);
    const saved: LayerState[] = [
      { layer_id: "flights", opacity: 1, visible: false },
    ];

    await controller.restore(saved);
    expect(manager.setEnabled).toHaveBeenNthCalledWith(
      1,
      "flights",
      false,
      { origin: "tool" },
    );
    expect(manager.setEnabled).toHaveBeenNthCalledWith(
      2,
      "earthquakes",
      false,
      { origin: "tool" },
    );

    await expect(
      controller.restore([{ layer_id: "unknown", opacity: 1, visible: true }]),
    ).rejects.toThrow("Saved Earth data layer 'unknown' is not available");
    await expect(
      controller.restore([{ layer_id: "flights", opacity: 0.5, visible: true }]),
    ).rejects.toThrow("uses unsupported opacity");
  });
});
