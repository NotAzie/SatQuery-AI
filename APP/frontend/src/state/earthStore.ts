import { create } from "zustand";

import type { CameraState, EarthCaptureMetadata, EarthContext } from "@/shared/types";
import { useSessionStore } from "@/state/sessionStore";
import type { TimelineState } from "@/earth/timeline/types";
import type {
  EarthDrawing as EarthDrawingState,
  EarthSelection,
  MeasurementResult,
} from "@/earth/workspace/types";

interface EarthStoreState {
  camera: CameraState | null;
  timeline: TimelineState;
  selection: EarthSelection | null;
  drawings: EarthDrawingState[];
  captures: EarthCaptureMetadata[];
  measurement: MeasurementResult | null;
  splitView: boolean;
  syncCameras: boolean;
  setCamera: (camera: CameraState) => void;
  setTimeline: (timeline: TimelineState) => void;
  setSelection: (selection: EarthSelection | null) => void;
  setDrawings: (drawings: EarthDrawingState[]) => void;
  setCaptures: (captures: EarthCaptureMetadata[]) => void;
  setMeasurement: (measurement: MeasurementResult | null) => void;
  setSplitView: (enabled: boolean) => void;
  setSyncCameras: (enabled: boolean) => void;
}

/** Mirror of what the user is currently looking at, written by the Earth controller. */
export const useEarthStore = create<EarthStoreState>((set) => ({
  camera: null,
  timeline: { instant: null, range: null, playing: false, speed: 1 },
  selection: null,
  drawings: [],
  captures: [],
  measurement: null,
  splitView: false,
  syncCameras: false,
  setCamera: (camera) => set({ camera }),
  setTimeline: (timeline) => set({ timeline }),
  setSelection: (selection) => set({ selection }),
  setDrawings: (drawings) => set({ drawings }),
  setCaptures: (captures) => set({ captures }),
  setMeasurement: (measurement) => set({ measurement }),
  setSplitView: (splitView) => set({ splitView }),
  setSyncCameras: (syncCameras) => set({ syncCameras }),
}));

/** Snapshot of the local workspace context. It is not sent to the Engine until its API supports it. */
export function snapshotEarthContext(): EarthContext | null {
  const { camera, timeline, selection, drawings, captures } = useEarthStore.getState();
  const { cameraHistory, bookmarks } = useSessionStore.getState();
  const { splitView, syncCameras, measurement } = useEarthStore.getState();
  if (!camera) return null;
  return {
    camera,
    layers: [],
    time: timeline.range,
    instant: timeline.instant?.toISOString() ?? null,
    selection,
    drawings,
    captures,
    selected_evidence_ids: [],
    bookmarks: bookmarks.map(({ id, name, context: bookmarkContext }) => ({
      id,
      name,
      camera: bookmarkContext.camera,
      time: bookmarkContext.time,
      instant: bookmarkContext.instant,
    })),
    camera_history: cameraHistory,
    split_view: { enabled: splitView, sync_cameras: syncCameras },
    measurement,
  };
}
