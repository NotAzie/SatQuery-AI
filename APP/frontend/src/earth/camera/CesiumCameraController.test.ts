import { Cartesian3, Math as CesiumMath, type Viewer } from "cesium";
import { describe, expect, it, vi } from "vitest";

import type { CameraState } from "@/shared/types";

import { createCameraController } from "./CesiumCameraController";

describe("CesiumCameraController", () => {
  it("restores the camera position and all orientation axes without animation", () => {
    const setView = vi.fn();
    const viewer = {
      camera: { setView },
    } as unknown as Viewer;
    const controller = createCameraController(viewer);
    const state: CameraState = {
      position: { lng: 18.4, lat: -32.1 },
      height_m: 847_000,
      heading_deg: 93,
      pitch_deg: -41,
      roll_deg: 7,
      view_rect: null,
    };

    controller.restore(state);

    expect(setView).toHaveBeenCalledWith({
      destination: Cartesian3.fromDegrees(18.4, -32.1, 847_000),
      orientation: {
        heading: CesiumMath.toRadians(93),
        pitch: CesiumMath.toRadians(-41),
        roll: CesiumMath.toRadians(7),
      },
    });
  });
});
