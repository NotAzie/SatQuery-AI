import { create } from "zustand";

import type {
  CameraState,
  EarthCaptureMetadata,
  EarthContext,
  EarthWorkspaceState,
} from "@/shared/types";
import type { CameraHistory, EarthBookmark } from "@/earth/workspace/types";

interface SessionStoreState {
  activeSessionId: string | null;
  bookmarks: EarthBookmark[];
  cameraHistory: CameraHistory;
  captures: EarthCaptureMetadata[];
  persistenceError: string | null;
  setActiveSession: (id: string | null) => void;
  hydrateWorkspace: (workspace: EarthWorkspaceState) => void;
  snapshotWorkspace: () => EarthWorkspaceState;
  setPersistenceError: (message: string | null) => void;
  recordCamera: (camera: CameraState) => void;
  undoCamera: () => CameraState | null;
  redoCamera: () => CameraState | null;
  addBookmark: (name: string, context: EarthContext) => EarthBookmark;
  renameBookmark: (id: string, name: string) => void;
  updateBookmark: (id: string, context: EarthContext) => void;
  deleteBookmark: (id: string) => void;
  addCapture: (sessionId: string, capture: EarthCaptureMetadata) => boolean;
  deleteCapture: (sessionId: string, id: string) => boolean;
}

interface PersistedWorkspace {
  bookmarks: EarthBookmark[];
  camera_history: CameraHistory;
  captures: EarthCaptureMetadata[];
}

const EMPTY_WORKSPACE: PersistedWorkspace = {
  bookmarks: [],
  camera_history: { past: [], present: null, future: [] },
  captures: [],
};

function storageKey(sessionId: string): string {
  return `satquery:earth-workspace:${encodeURIComponent(sessionId)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCamera(value: unknown): value is CameraState {
  if (!isRecord(value) || !isRecord(value.position)) return false;
  const rect = value.view_rect;
  return (
    typeof value.position.lng === "number" &&
    typeof value.position.lat === "number" &&
    typeof value.height_m === "number" &&
    typeof value.heading_deg === "number" &&
    typeof value.pitch_deg === "number" &&
    typeof value.roll_deg === "number" &&
    (rect === null ||
      (isRecord(rect) &&
        typeof rect.west === "number" &&
        typeof rect.south === "number" &&
        typeof rect.east === "number" &&
        typeof rect.north === "number"))
  );
}

function isCapture(value: unknown): value is EarthCaptureMetadata {
  if (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.asset_id === "string" &&
    typeof value.captured_at === "string" &&
    (value.source === "viewport" || value.source === "region") &&
    isCamera(value.camera) &&
    (value.region === null || isRecord(value.region))
  ) {
    const crop = value.pixel_region;
    const viewportWidth = value.viewport_width_px;
    const viewportHeight = value.viewport_height_px;
    const hasViewportWidth = typeof viewportWidth === "number";
    const hasViewportHeight = typeof viewportHeight === "number";
    const hasCrop = crop !== undefined && crop !== null;
    const validCrop =
      crop === undefined ||
      crop === null ||
      (isRecord(crop) &&
        Number.isInteger(crop.left) &&
        Number.isInteger(crop.top) &&
        Number.isInteger(crop.width) &&
        Number.isInteger(crop.height) &&
        Number(crop.left) >= 0 &&
        Number(crop.top) >= 0 &&
        Number(crop.width) > 0 &&
        Number(crop.height) > 0);
    return (
      validCrop &&
      (!hasCrop || hasViewportWidth) &&
      hasViewportWidth === hasViewportHeight &&
      (!hasViewportWidth ||
        (typeof viewportWidth === "number" &&
          typeof viewportHeight === "number" &&
          viewportWidth > 0 &&
          viewportHeight > 0 &&
          (crop === undefined ||
            crop === null ||
            (isRecord(crop) &&
              Number(crop.left) + Number(crop.width) <= viewportWidth &&
              Number(crop.top) + Number(crop.height) <= viewportHeight))))
    );
  }
  return false;
}

function isPosition(value: unknown): value is { lng: number; lat: number } {
  return (
    isRecord(value) &&
    typeof value.lng === "number" &&
    typeof value.lat === "number"
  );
}

function isCoordinate(value: unknown): value is [number, number] {
  return Array.isArray(value) && value.length === 2 && value.every((part) => typeof part === "number");
}

function isEarthDrawing(value: unknown): boolean {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    !["point", "line", "polygon", "rectangle", "circle"].includes(String(value.kind)) ||
    !isRecord(value.geometry)
  ) {
    return false;
  }
  const kind = value.kind;
  const { type, coordinates } = value.geometry;
  if (kind === "point" && type === "Point") return isCoordinate(coordinates);
  if (kind === "line" && type === "LineString") {
    return Array.isArray(coordinates) && coordinates.length >= 2 && coordinates.every(isCoordinate);
  }
  if (
    (kind === "polygon" || kind === "rectangle" || kind === "circle") &&
    type === "Polygon"
  ) {
    return (
      Array.isArray(coordinates) &&
      coordinates.length > 0 &&
      coordinates.every(
        (ring) => Array.isArray(ring) && ring.length >= 4 && ring.every(isCoordinate),
      )
    );
  }
  return false;
}

function isEarthContext(value: unknown): value is EarthContext {
  if (!isRecord(value) || !isCamera(value.camera)) return false;
  const captures = value.captures;
  if (captures !== undefined && (!Array.isArray(captures) || !captures.every(isCapture))) {
    return false;
  }
  if (
    !Array.isArray(value.layers) ||
    !value.layers.every(
      (layer) =>
        isRecord(layer) &&
        typeof layer.layer_id === "string" &&
        typeof layer.visible === "boolean" &&
        typeof layer.opacity === "number",
    ) ||
    !Array.isArray(value.drawings) ||
    !value.drawings.every(isEarthDrawing) ||
    !Array.isArray(value.selected_evidence_ids) ||
    !value.selected_evidence_ids.every((id) => typeof id === "string")
  ) {
    return false;
  }
  if (value.time !== null && (!isRecord(value.time) || typeof value.time.start !== "string" || typeof value.time.end !== "string")) {
    return false;
  }
  if (value.instant !== null && typeof value.instant !== "string") return false;
  if (
    value.selection !== null &&
    (!isRecord(value.selection) ||
      typeof value.selection.entity_id !== "string" ||
      (value.selection.position !== null && !isPosition(value.selection.position)) ||
      !isRecord(value.selection.properties) ||
      !Object.values(value.selection.properties).every(
        (property) =>
          property === null ||
          typeof property === "string" ||
          typeof property === "number" ||
          typeof property === "boolean",
      ))
  ) {
    return false;
  }
  return true;
}

function isBookmark(value: unknown): value is EarthBookmark {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    isEarthContext(value.context) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

function isCameraHistory(value: unknown): value is CameraHistory {
  return (
    isRecord(value) &&
    Array.isArray(value.past) &&
    value.past.every(isCamera) &&
    (value.present === null || isCamera(value.present)) &&
    Array.isArray(value.future) &&
    value.future.every(isCamera)
  );
}

function parseWorkspace(value: unknown): PersistedWorkspace {
  if (
    !isRecord(value) ||
    !Array.isArray(value.bookmarks) ||
    !value.bookmarks.every(isBookmark) ||
    !isCameraHistory(value.camera_history)
  ) {
    throw new TypeError("Saved Earth workspace data is invalid");
  }
  const captures = value.captures ?? [];
  if (!Array.isArray(captures) || !captures.every(isCapture)) {
    throw new TypeError("Saved Earth capture data is invalid");
  }
  return {
    bookmarks: value.bookmarks,
    camera_history: value.camera_history,
    captures,
  };
}

function loadWorkspace(sessionId: string | null): PersistedWorkspace {
  if (!sessionId || typeof localStorage === "undefined") return EMPTY_WORKSPACE;
  const raw = localStorage.getItem(storageKey(sessionId));
  if (!raw) return EMPTY_WORKSPACE;
  const parsed: unknown = JSON.parse(raw);
  return parseWorkspace(parsed);
}

function persistWorkspace(sessionId: string | null, workspace: PersistedWorkspace): void {
  if (!sessionId || typeof localStorage === "undefined") return;
  localStorage.setItem(storageKey(sessionId), JSON.stringify(workspace));
}

function sameCamera(first: CameraState, second: CameraState): boolean {
  return (
    first.position.lng === second.position.lng &&
    first.position.lat === second.position.lat &&
    first.height_m === second.height_m &&
    first.heading_deg === second.heading_deg &&
    first.pitch_deg === second.pitch_deg &&
    first.roll_deg === second.roll_deg
  );
}

function save(
  get: () => SessionStoreState,
  set: (partial: Partial<SessionStoreState>) => void,
  update: (workspace: PersistedWorkspace) => PersistedWorkspace,
): PersistedWorkspace {
  const state = get();
  const workspace = update({
    bookmarks: state.bookmarks,
    camera_history: state.cameraHistory,
    captures: state.captures,
  });
  persistWorkspace(state.activeSessionId, workspace);
  set({
    bookmarks: workspace.bookmarks,
    cameraHistory: workspace.camera_history,
    captures: workspace.captures,
  });
  return workspace;
}

export const useSessionStore = create<SessionStoreState>((set, get) => ({
  activeSessionId: null,
  bookmarks: EMPTY_WORKSPACE.bookmarks,
  cameraHistory: { ...EMPTY_WORKSPACE.camera_history },
  captures: EMPTY_WORKSPACE.captures,
  persistenceError: null,
  setActiveSession: (id) => {
    let workspace: PersistedWorkspace;
    try {
      workspace = loadWorkspace(id);
    } catch (reason) {
      set({
        activeSessionId: id,
        bookmarks: [],
        cameraHistory: { ...EMPTY_WORKSPACE.camera_history },
        captures: [],
        persistenceError:
          reason instanceof Error ? reason.message : "Could not read saved Earth workspace.",
      });
      return;
    }
    set({
      activeSessionId: id,
      bookmarks: workspace.bookmarks,
      cameraHistory: workspace.camera_history,
      captures: workspace.captures,
      persistenceError: null,
    });
  },
  hydrateWorkspace: (workspace) => {
    const saved = parseWorkspace(workspace);
    persistWorkspace(get().activeSessionId, saved);
    set({
      bookmarks: saved.bookmarks,
      cameraHistory: saved.camera_history,
      captures: saved.captures,
      persistenceError: null,
    });
  },
  snapshotWorkspace: () => ({
    bookmarks: get().bookmarks,
    camera_history: get().cameraHistory,
    captures: get().captures,
  }),
  setPersistenceError: (message) => set({ persistenceError: message }),
  recordCamera: (camera) => {
    save(get, set, (workspace) => {
      const { past, present, future } = workspace.camera_history;
      if (present && sameCamera(present, camera)) return workspace;
      const cameraHistory: CameraHistory = present
        ? { past: [...past, present].slice(-100), present: camera, future: [] }
        : { past, present: camera, future };
      return { ...workspace, camera_history: cameraHistory };
    });
  },
  undoCamera: () => {
    let restored: CameraState | null = null;
    save(get, set, (workspace) => {
      const { past, present, future } = workspace.camera_history;
      if (!present || past.length === 0) return workspace;
      const target = past[past.length - 1];
      if (!target) return workspace;
      restored = target;
      return {
        ...workspace,
        camera_history: {
          past: past.slice(0, -1),
          present: target,
          future: [present, ...future],
        },
      };
    });
    return restored;
  },
  redoCamera: () => {
    let restored: CameraState | null = null;
    save(get, set, (workspace) => {
      const { past, present, future } = workspace.camera_history;
      if (!present || future.length === 0) return workspace;
      const target = future[0];
      if (!target) return workspace;
      restored = target;
      return {
        ...workspace,
        camera_history: {
          past: [...past, present],
          present: target,
          future: future.slice(1),
        },
      };
    });
    return restored;
  },
  addBookmark: (name, context) => {
    if (!get().activeSessionId) {
      throw new Error("Save a bookmark only after opening a Platform session");
    }
    const trimmed = name.trim();
    if (!trimmed) throw new RangeError("Bookmark name cannot be empty");
    const now = new Date().toISOString();
    const bookmark: EarthBookmark = {
      id: globalThis.crypto.randomUUID(),
      name: trimmed,
      context,
      created_at: now,
      updated_at: now,
    };
    save(get, set, (workspace) => ({
      ...workspace,
      bookmarks: [...workspace.bookmarks, bookmark],
    }));
    return bookmark;
  },
  renameBookmark: (id, name) => {
    const trimmed = name.trim();
    if (!trimmed) throw new RangeError("Bookmark name cannot be empty");
    save(get, set, (workspace) => {
      const bookmarks = workspace.bookmarks.map((bookmark) =>
        bookmark.id === id
          ? { ...bookmark, name: trimmed, updated_at: new Date().toISOString() }
          : bookmark,
      );
      if (bookmarks.every((bookmark) => bookmark.id !== id)) {
        throw new RangeError(`Bookmark '${id}' does not exist`);
      }
      return { ...workspace, bookmarks };
    });
  },
  updateBookmark: (id, context) => {
    save(get, set, (workspace) => {
      const bookmarks = workspace.bookmarks.map((bookmark) =>
        bookmark.id === id
          ? { ...bookmark, context, updated_at: new Date().toISOString() }
          : bookmark,
      );
      if (bookmarks.every((bookmark) => bookmark.id !== id)) {
        throw new RangeError(`Bookmark '${id}' does not exist`);
      }
      return { ...workspace, bookmarks };
    });
  },
  deleteBookmark: (id) => {
    save(get, set, (workspace) => {
      if (!workspace.bookmarks.some((bookmark) => bookmark.id === id)) {
        throw new RangeError(`Bookmark '${id}' does not exist`);
      }
      return {
        ...workspace,
        bookmarks: workspace.bookmarks.filter((bookmark) => bookmark.id !== id),
      };
    });
  },
  addCapture: (sessionId, capture) => {
    if (get().activeSessionId !== sessionId) return false;
    save(get, set, (workspace) => ({
      ...workspace,
      captures: [...workspace.captures, capture],
    }));
    return true;
  },
  deleteCapture: (sessionId, id) => {
    if (get().activeSessionId !== sessionId) return false;
    save(get, set, (workspace) => {
      if (!workspace.captures.some((capture) => capture.id === id)) {
        throw new RangeError(`Earth capture '${id}' does not exist`);
      }
      return {
        ...workspace,
        captures: workspace.captures.filter((capture) => capture.id !== id),
      };
    });
    return true;
  },
}));
