import { useEffect, useState } from "react";

// @ts-expect-error Vendored JavaScript startup module; the runtime is guarded below.
import { applicationReady } from "../../../../earth-view/src/main.js";
import { useEarthRegistry } from "@/hooks/useEarth";
import { useEarthStore } from "@/state/earthStore";
import { useSessionStore } from "@/state/sessionStore";

import { createEarthController } from "../controller";
import type { EarthEvent } from "../events";
import {
  createGodsEyeLayerController,
  isGodsEyeRuntime,
} from "../integration/godsEyeRuntime";

/** Connect SatQuery's typed workspace controllers to God's Eye's single live viewer. */
export function EarthStage() {
  const registry = useEarthRegistry();
  const { events, attach, detach } = registry;
  const [startupError, setStartupError] = useState<string | null>(null);
  const setCamera = useEarthStore((state) => state.setCamera);
  const setViewport = useEarthStore((state) => state.setViewport);
  const setLayers = useEarthStore((state) => state.setLayers);
  const setOverlays = useEarthStore((state) => state.setOverlays);
  const setSelectedEvidenceIds = useEarthStore((state) => state.setSelectedEvidenceIds);
  const setTimeline = useEarthStore((state) => state.setTimeline);
  const setSelection = useEarthStore((state) => state.setSelection);
  const setDrawings = useEarthStore((state) => state.setDrawings);
  const setMeasurement = useEarthStore((state) => state.setMeasurement);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const recordCamera = useSessionStore((state) => state.recordCamera);

  useEffect(() => {
    const unsubscribe = events.subscribe((event: EarthEvent) => {
      switch (event.type) {
        case "earth.camera.changed":
          setCamera(event.camera);
          recordCamera(event.camera);
          break;
        case "earth.layers.changed":
          setLayers(event.layers);
          break;
        case "earth.viewport.changed":
          setViewport(event.viewport);
          break;
        case "earth.timeline.changed":
          setTimeline(event.timeline);
          break;
        case "earth.overlays.changed":
          setOverlays(event.overlays);
          break;
        case "earth.evidence.highlighted":
          setSelectedEvidenceIds(event.evidenceIds);
          break;
        case "earth.selection.changed":
          setSelection(event.selection);
          break;
        case "earth.drawings.changed":
          setDrawings(event.drawings);
          break;
        case "earth.measurement.changed":
          setMeasurement(event.measurement);
          break;
      }
    });
    return unsubscribe;
  }, [
    events,
    recordCamera,
    setCamera,
    setDrawings,
    setLayers,
    setMeasurement,
    setOverlays,
    setSelectedEvidenceIds,
    setSelection,
    setTimeline,
    setViewport,
  ]);

  useEffect(() => {
    const savedCamera = useSessionStore.getState().cameraHistory.present;
    if (!activeSessionId || !registry.controller) return;
    if (savedCamera) {
      setCamera(savedCamera);
      registry.controller.camera.restore(savedCamera);
    } else {
      const currentCamera = registry.controller.camera.getState();
      setCamera(currentCamera);
      recordCamera(currentCamera);
    }
  }, [activeSessionId, registry.controller, recordCamera, setCamera]);

  useEffect(() => {
    let active = true;
    let attached = false;
    let cleanupRuntime = () => {};

    const attachRuntime = (value: unknown) => {
      if (!active || attached) return;
      if (!isGodsEyeRuntime(value)) {
        setStartupError("Earth View started without a compatible Cesium viewer or data-layer manager.");
        return;
      }
      const container = document.getElementById("cesiumContainer");
      if (!container) {
        setStartupError("Earth View did not create its Cesium container.");
        return;
      }

      const layers = createGodsEyeLayerController(value.dataManager);
      const controller = createEarthController(value.viewer, events, "primary", layers);
      const publishViewport = () => {
        const bounds = container.getBoundingClientRect();
        const width = Math.round(bounds.width);
        const height = Math.round(bounds.height);
        if (width <= 0 || height <= 0) return;
        events.publish({
          type: "earth.viewport.changed",
          viewport: {
            width_px: width,
            height_px: height,
            pixel_ratio: window.devicePixelRatio || 1,
          },
          viewId: "primary",
        });
      };
      const resizeObserver = new ResizeObserver(publishViewport);
      resizeObserver.observe(container);
      const syncLayers = () => {
        const state = layers.getState();
        setLayers(state);
        events.publish({
          type: "earth.layers.changed",
          layers: state,
          viewId: "primary",
        });
      };
      const unsubscribeLayers = layers.onChange(syncLayers);
      attached = true;
      attach(controller);
      setStartupError(null);
      setInitialEarthState(controller);
      syncLayers();
      publishViewport();
      cleanupRuntime = () => {
        resizeObserver.disconnect();
        unsubscribeLayers();
        detach();
        controller.destroy();
        attached = false;
      };
    };

    void applicationReady
      .then((runtime: unknown) => {
        attachRuntime(runtime);
      })
      .catch((error: unknown) => {
        if (active) {
          setStartupError(
            error instanceof Error ? error.message : "Earth View could not initialize.",
          );
        }
      });

    return () => {
      active = false;
      cleanupRuntime();
    };
  }, [attach, detach, events, setLayers]);

  if (!startupError) return null;
  return (
    <p
      className="pointer-events-auto fixed bottom-4 left-1/2 z-[100] max-w-[min(42rem,calc(100%-2rem))] -translate-x-1/2 rounded-xl border border-rose-300/30 bg-black/90 px-4 py-3 text-sm text-rose-100 shadow-xl"
      role="alert"
    >
      Earth environment failed to start: {startupError}
    </p>
  );
}

function setInitialEarthState(controller: ReturnType<typeof createEarthController>): void {
  const initialCamera = controller.camera.getState();
  const savedCamera = useSessionStore.getState().cameraHistory.present;
  if (savedCamera) {
    useEarthStore.getState().setCamera(savedCamera);
    controller.camera.restore(savedCamera);
  } else {
    useEarthStore.getState().setCamera(initialCamera);
    useSessionStore.getState().recordCamera(initialCamera);
  }
  useEarthStore.getState().setTimeline(controller.timeline.getState());
  controller.workspace.replaceDrawings(useEarthStore.getState().drawings);
}
