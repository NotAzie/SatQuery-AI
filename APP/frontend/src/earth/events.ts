import type { Unsubscribe } from "@/shared/utils";

import type {
  EarthDrawing,
  EarthSelection,
  MeasurementResult,
} from "./workspace/types";
import type { CameraState, EarthOverlay, EarthViewport } from "@/shared/types";
import type { TimelineState } from "./timeline/types";

export type EarthEvent =
  | { type: "earth.camera.changed"; camera: CameraState; viewId: EarthViewId }
  | { type: "earth.viewport.changed"; viewport: EarthViewport; viewId: EarthViewId }
  | { type: "earth.timeline.changed"; timeline: TimelineState; viewId: EarthViewId }
  | { type: "earth.overlays.changed"; overlays: EarthOverlay[]; viewId: EarthViewId }
  | { type: "earth.evidence.highlighted"; evidenceIds: string[]; viewId: EarthViewId }
  | { type: "earth.selection.changed"; selection: EarthSelection | null }
  | { type: "earth.drawings.changed"; drawings: EarthDrawing[] }
  | { type: "earth.measurement.changed"; measurement: MeasurementResult | null };

export type EarthViewId = "primary" | "secondary";

export interface EarthEventBus {
  subscribe(listener: (event: EarthEvent) => void): Unsubscribe;
  publish(event: EarthEvent): void;
}

export function createEarthEventBus() {
  const listeners = new Set<(event: EarthEvent) => void>();
  return {
    publish(event: EarthEvent) {
      listeners.forEach((listener) => listener(event));
    },
    subscribe(listener: (event: EarthEvent) => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
