import { Cartesian3, Math as CesiumMath, Rectangle, type Viewer } from "cesium";

import type { CameraState } from "@/shared/types";

import type { CameraController } from "./types";

const DEFAULT_FLY_HEIGHT_M = 1_000_000;

export function createCameraController(viewer: Viewer): CameraController {
  const { camera } = viewer;

  const getState = (): CameraState => {
    const c = camera.positionCartographic;
    const rect = camera.computeViewRectangle();
    return {
      position: { lng: CesiumMath.toDegrees(c.longitude), lat: CesiumMath.toDegrees(c.latitude) },
      height_m: c.height,
      heading_deg: CesiumMath.toDegrees(camera.heading),
      pitch_deg: CesiumMath.toDegrees(camera.pitch),
      roll_deg: CesiumMath.toDegrees(camera.roll),
      view_rect: rect
        ? {
            west: CesiumMath.toDegrees(rect.west),
            south: CesiumMath.toDegrees(rect.south),
            east: CesiumMath.toDegrees(rect.east),
            north: CesiumMath.toDegrees(rect.north),
          }
        : null,
    };
  };

  return {
    getState,

    flyTo({ target, height_m, duration_s }) {
      return new Promise<void>((resolve) => {
        const destination =
          "west" in target
            ? Rectangle.fromDegrees(target.west, target.south, target.east, target.north)
            : Cartesian3.fromDegrees(target.lng, target.lat, height_m ?? DEFAULT_FLY_HEIGHT_M);
        camera.flyTo({
          destination,
          duration: duration_s,
          complete: resolve,
          cancel: resolve,
        });
      });
    },

    restore(state) {
      camera.setView({
        destination: Cartesian3.fromDegrees(
          state.position.lng,
          state.position.lat,
          state.height_m,
        ),
        orientation: {
          heading: CesiumMath.toRadians(state.heading_deg),
          pitch: CesiumMath.toRadians(state.pitch_deg),
          roll: CesiumMath.toRadians(state.roll_deg),
        },
      });
    },

    onSettle(listener) {
      const remove = camera.moveEnd.addEventListener(() => listener(getState()));
      return () => {
        remove();
      };
    },
  };
}
