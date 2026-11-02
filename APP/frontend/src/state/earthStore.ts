import { create } from "zustand";

import type {
  CameraState,
  EarthCaptureMetadata,
  EarthContext,
  EarthImageryRef,
  EarthOverlay,
  EarthViewport,
  LayerState,
} from "@/shared/types";
import { useSessionStore } from "@/state/sessionStore";
import type { TimelineState } from "@/earth/timeline/types";
import type {
  EarthDrawing as EarthDrawingState,
  EarthSelection,
  MeasurementResult,
} from "@/earth/workspace/types";

interface EarthStoreState {
  camera: CameraState | null;
  secondaryCamera: CameraState | null;
  viewport: EarthViewport | null;
  secondaryViewport: EarthViewport | null;
  layers: LayerState[];
  timeline: TimelineState;
  selection: EarthSelection | null;
  drawings: EarthDrawingState[];
  captures: EarthCaptureMetadata[];
  overlays: EarthOverlay[];
  selectedEvidenceIds: string[];
  secondaryOverlays: EarthOverlay[];
  secondarySelectedEvidenceIds: string[];
  measurement: MeasurementResult | null;
  splitView: boolean;
  syncCameras: boolean;
  setCamera: (camera: CameraState) => void;
  setSecondaryCamera: (camera: CameraState | null) => void;
  setViewport: (viewport: EarthViewport) => void;
  setSecondaryViewport: (viewport: EarthViewport | null) => void;
  setLayers: (layers: LayerState[]) => void;
  setTimeline: (timeline: TimelineState) => void;
  setSelection: (selection: EarthSelection | null) => void;
  setDrawings: (drawings: EarthDrawingState[]) => void;
  setCaptures: (captures: EarthCaptureMetadata[]) => void;
  setOverlays: (overlays: EarthOverlay[]) => void;
  setSelectedEvidenceIds: (evidenceIds: string[]) => void;
  setSecondaryOverlays: (overlays: EarthOverlay[]) => void;
  setSecondarySelectedEvidenceIds: (evidenceIds: string[]) => void;
  setMeasurement: (measurement: MeasurementResult | null) => void;
  setSplitView: (enabled: boolean) => void;
  setSyncCameras: (enabled: boolean) => void;
}

/** Mirror of what the user is currently looking at, written by the Earth controller. */
export const useEarthStore = create<EarthStoreState>((set) => ({
  camera: null,
  secondaryCamera: null,
  viewport: null,
  secondaryViewport: null,
  layers: [],
  timeline: { instant: null, range: null, playing: false, speed: 1 },
  selection: null,
  drawings: [],
  captures: [],
  overlays: [],
  selectedEvidenceIds: [],
  secondaryOverlays: [],
  secondarySelectedEvidenceIds: [],
  measurement: null,
  splitView: false,
  syncCameras: false,
  setCamera: (camera) => set({ camera }),
  setSecondaryCamera: (secondaryCamera) => set({ secondaryCamera }),
  setViewport: (viewport) => set({ viewport }),
  setSecondaryViewport: (secondaryViewport) => set({ secondaryViewport }),
  setLayers: (layers) => set({ layers }),
  setTimeline: (timeline) => set({ timeline }),
  setSelection: (selection) => set({ selection }),
  setDrawings: (drawings) => set({ drawings }),
  setCaptures: (captures) => set({ captures }),
  setOverlays: (overlays) => set({ overlays }),
  setSelectedEvidenceIds: (selectedEvidenceIds) => set({ selectedEvidenceIds }),
  setSecondaryOverlays: (secondaryOverlays) => set({ secondaryOverlays }),
  setSecondarySelectedEvidenceIds: (secondarySelectedEvidenceIds) =>
    set({ secondarySelectedEvidenceIds }),
  setMeasurement: (measurement) => set({ measurement }),
  setSplitView: (splitView) => set({ splitView }),
  setSyncCameras: (syncCameras) => set({ syncCameras }),
}));

/** Snapshot of serializable workspace state; rendered assets remain Platform-owned. */
export function snapshotEarthContext(): EarthContext | null {
  const {
    camera,
    secondaryCamera,
    viewport,
    secondaryViewport,
    layers,
    timeline,
    selection,
    drawings,
    captures,
    overlays,
    selectedEvidenceIds,
    secondaryOverlays,
    secondarySelectedEvidenceIds,
  } = useEarthStore.getState();
  const { cameraHistory, bookmarks } = useSessionStore.getState();
  const { splitView, syncCameras, measurement } = useEarthStore.getState();
  if (!camera) return null;
  const imagery: EarthImageryRef[] = captures.map((capture) => ({
    asset_id: capture.asset_id,
    source: "capture",
    attached: false,
    captured_at: capture.captured_at,
    region: capture.region,
    camera: capture.camera,
    mime_type: null,
    width: null,
    height: null,
  }));
  const visibleInvestigationIds = [
    ...new Set(
      [
        ...overlays.flatMap((overlay) =>
          overlay.investigation_id ? [overlay.investigation_id] : [],
        ),
        ...(splitView
          ? secondaryOverlays.flatMap((overlay) =>
              overlay.investigation_id ? [overlay.investigation_id] : [],
            )
          : []),
      ],
    ),
  ];
  return {
    camera,
    secondary_view:
      splitView && secondaryCamera
        ? {
            camera: secondaryCamera,
            viewport: secondaryViewport,
            layers: [],
            overlays: secondaryOverlays,
            selected_evidence_ids: secondarySelectedEvidenceIds,
          }
        : null,
    viewport,
    layers,
    time: timeline.range,
    instant: timeline.instant?.toISOString() ?? null,
    timeline_playback: { playing: timeline.playing, speed: timeline.speed },
    selection,
    drawings,
    captures,
    imagery,
    overlays,
    investigations: { known_ids: [], visible_ids: visibleInvestigationIds },
    selected_evidence_ids: selectedEvidenceIds,
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
