import { useEffect, useRef } from "react";

import { useEarthRegistry } from "@/hooks/useEarth";
import { useEarthStore } from "@/state/earthStore";
import { useSessionStore } from "@/state/sessionStore";

import { createEarthController } from "../controller";
import type { EarthController } from "../controller";
import type { EarthEvent, EarthViewId } from "../events";
import { createViewer } from "./createViewer";

/** Persistent primary and optional secondary globe, with one shared presentation event stream. */
export function EarthStage() {
  const registry = useEarthRegistry();
  const splitView = useEarthStore((state) => state.splitView);
  const syncCameras = useEarthStore((state) => state.syncCameras);
  const setCamera = useEarthStore((state) => state.setCamera);
  const setTimeline = useEarthStore((state) => state.setTimeline);
  const setSelection = useEarthStore((state) => state.setSelection);
  const setDrawings = useEarthStore((state) => state.setDrawings);
  const setMeasurement = useEarthStore((state) => state.setMeasurement);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const recordCamera = useSessionStore((state) => state.recordCamera);

  useEffect(() => {
    if (splitView && syncCameras && registry.controller && registry.secondaryController) {
      registry.secondaryController.camera.restore(registry.controller.camera.getState());
    }
    const unsubscribe = registry.events.subscribe((event: EarthEvent) => {
      switch (event.type) {
        case "earth.camera.changed":
          if (event.viewId === "primary") {
            setCamera(event.camera);
            recordCamera(event.camera);
          }
          if (syncCameras && splitView) {
            synchronizeCamera(event.viewId, event.camera, registry.controller, registry.secondaryController);
          }
          break;
        case "earth.timeline.changed":
          if (event.viewId === "primary") {
            setTimeline(event.timeline);
            if (splitView) synchronizeTimeline(event.timeline, registry.secondaryController);
          }
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
    registry.events,
    registry.controller,
    registry.secondaryController,
    splitView,
    syncCameras,
    recordCamera,
    setCamera,
    setTimeline,
    setSelection,
    setDrawings,
    setMeasurement,
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

  return (
    <div className="absolute inset-0 flex">
      <EarthViewport viewId="primary" events={registry.events} />
      {splitView && (
        <EarthViewport viewId="secondary" events={registry.events} />
      )}
    </div>
  );
}

function EarthViewport({ viewId, events }: { viewId: EarthViewId; events: EarthController["events"] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { attach, attachSecondary, detach, detachSecondary } = useEarthRegistry();

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const viewer = createViewer(container);
    const controller = createEarthController(viewer, events, viewId);
    if (viewId === "primary") {
      attach(controller);
      setInitialEarthState(controller);
    } else {
      attachSecondary(controller);
      const current = useEarthStore.getState();
      controller.workspace.replaceDrawings(current.drawings);
      if (current.timeline.range) {
        controller.timeline.setRange(current.timeline.range);
        if (current.timeline.instant) controller.timeline.setInstant(current.timeline.instant);
      }
      if (current.timeline.playing) controller.timeline.play(current.timeline.speed);
    }

    return () => {
      if (viewId === "primary") detach();
      else detachSecondary();
      controller.destroy();
      viewer.destroy();
    };
  }, [viewId, events, attach, attachSecondary, detach, detachSecondary]);

  return (
    <div
      ref={containerRef}
      className={`relative h-full ${viewId === "secondary" ? "min-w-0 flex-1 border-l border-white/10" : "min-w-0 flex-1"}`}
      aria-label={viewId === "primary" ? "Primary Earth view" : "Secondary Earth view"}
    />
  );
}

function setInitialEarthState(controller: EarthController): void {
  const initialCamera = controller.camera.getState();
  const savedCamera = useSessionStore.getState().cameraHistory.present;
  if (savedCamera) {
    useEarthStore.getState().setCamera(savedCamera);
    controller.camera.restore(savedCamera);
  }
  else {
    useEarthStore.getState().setCamera(initialCamera);
    useSessionStore.getState().recordCamera(initialCamera);
  }
  useEarthStore.getState().setTimeline(controller.timeline.getState());
  controller.workspace.replaceDrawings(useEarthStore.getState().drawings);
}

function synchronizeCamera(
  source: EarthViewId,
  camera: Parameters<EarthController["camera"]["restore"]>[0],
  primary: EarthController | null,
  secondary: EarthController | null,
): void {
  const target = source === "primary" ? secondary : primary;
  if (!target || sameCamera(target.camera.getState(), camera)) return;
  target.camera.restore(camera);
}

function sameCamera(
  first: Parameters<EarthController["camera"]["restore"]>[0],
  second: Parameters<EarthController["camera"]["restore"]>[0],
): boolean {
  return (
    Math.abs(first.position.lng - second.position.lng) < 0.00001 &&
    Math.abs(first.position.lat - second.position.lat) < 0.00001 &&
    Math.abs(first.height_m - second.height_m) < 0.1 &&
    Math.abs(first.heading_deg - second.heading_deg) < 0.001 &&
    Math.abs(first.pitch_deg - second.pitch_deg) < 0.001 &&
    Math.abs(first.roll_deg - second.roll_deg) < 0.001
  );
}

function synchronizeTimeline(
  timeline: ReturnType<EarthController["timeline"]["getState"]>,
  secondary: EarthController | null,
): void {
  if (!secondary) return;
  const current = secondary.timeline.getState();
  if (JSON.stringify(current.range) !== JSON.stringify(timeline.range)) {
    if (timeline.range) secondary.timeline.setRange(timeline.range);
  }
  if (
    timeline.instant &&
    current.instant?.getTime() !== timeline.instant.getTime()
  ) {
    secondary.timeline.setInstant(timeline.instant);
  }
  if (timeline.playing && !current.playing) secondary.timeline.play(timeline.speed);
  else if (!timeline.playing && current.playing) secondary.timeline.pause();
}
