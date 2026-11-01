import type { Viewer } from "cesium";

import { createCameraController } from "./camera/CesiumCameraController";
import type { CameraController } from "./camera/types";
import { captureViewer, type CaptureController } from "./capture";
import {
  createEarthCommandDispatcher,
  type EarthCommandDispatcher,
} from "./commands/dispatcher";
import { createTimelineController } from "./timeline/CesiumTimelineController";
import type { TimelineController } from "./timeline/types";
import { createEarthEventBus, type EarthEventBus, type EarthViewId } from "./events";
import { createCesiumWorkspaceController } from "./workspace/CesiumWorkspaceController";
import type { EarthWorkspaceController } from "./workspace/types";

/**
 * The imperative facade over the globe. UI and the event reducer talk to this, never to Cesium.
 * Cesium-facing behavior is composed here; no caller receives a Viewer or Cesium object.
 */
export interface EarthController {
  camera: CameraController;
  commands: EarthCommandDispatcher;
  timeline: TimelineController;
  workspace: EarthWorkspaceController;
  events: EarthEventBus;
  capture: CaptureController;
  destroy(): void;
}

export function createEarthController(
  viewer: Viewer,
  events: EarthEventBus = createEarthEventBus(),
  viewId: EarthViewId = "primary",
): EarthController {
  const camera = createCameraController(viewer);
  const timeline = createTimelineController(viewer.clock);
  const workspace = createCesiumWorkspaceController(viewer, events);
  const stopCameraEvents = camera.onSettle((state) =>
    events.publish({ type: "earth.camera.changed", camera: state, viewId }),
  );
  const stopTimelineEvents = timeline.onChange((state) =>
    events.publish({ type: "earth.timeline.changed", timeline: state, viewId }),
  );
  return {
    camera,
    timeline,
    workspace,
    events,
    commands: createEarthCommandDispatcher({
      fly_to: (command) => camera.flyTo(command),
      set_time: (command) => {
        if (command.range) timeline.setRange(command.range);
        if (command.instant) timeline.setInstant(new Date(command.instant));
        if (command.playback_speed === null) timeline.pause();
        else if (command.playback_speed !== undefined) timeline.play(command.playback_speed);
      },
    }),
    capture: { captureEarth: () => captureViewer(viewer) },
    destroy() {
      stopCameraEvents();
      stopTimelineEvents();
      workspace.destroy();
    },
  };
}
