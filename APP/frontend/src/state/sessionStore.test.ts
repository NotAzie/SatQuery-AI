import { afterEach, describe, expect, it, vi } from "vitest";

import type { CameraState, EarthContext } from "@/shared/types";

import { useSessionStore } from "./sessionStore";

const camera = (lng: number): CameraState => ({
  position: { lng, lat: 48 },
  height_m: 1_000_000,
  heading_deg: 0,
  pitch_deg: -90,
  roll_deg: 0,
  view_rect: null,
});

const context = (lng: number): EarthContext => ({
  camera: camera(lng),
  secondary_view: null,
  viewport: null,
  layers: [],
  time: null,
  instant: null,
  timeline_playback: { playing: false, speed: 1 },
  selection: null,
  drawings: [],
  captures: [],
  imagery: [],
  overlays: [],
  investigations: { known_ids: [], visible_ids: [] },
  selected_evidence_ids: [],
  bookmarks: [],
  camera_history: { past: [], present: null, future: [] },
  split_view: { enabled: false, sync_cameras: false },
  measurement: null,
});

function installStorage() {
  const data = new Map<string, string>();
  const storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> = {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value);
    },
    removeItem: (key) => {
      data.delete(key);
    },
  };
  vi.stubGlobal("localStorage", storage);
}

afterEach(() => {
  vi.unstubAllGlobals();
  useSessionStore.setState({
    activeSessionId: null,
    bookmarks: [],
    cameraHistory: { past: [], present: null, future: [] },
    captures: [],
  });
});

describe("Session Earth workspace persistence", () => {
  it("persists Earth capture metadata with its session", () => {
    installStorage();
    useSessionStore.getState().setActiveSession("session-a");
    const capture = {
      id: "capture-1",
      asset_id: "asset-1",
      captured_at: "2026-11-01T10:00:00Z",
      source: "viewport" as const,
      camera: camera(12),
      region: null,
      pixel_region: null,
      viewport_width_px: null,
      viewport_height_px: null,
    };
    expect(useSessionStore.getState().addCapture("session-a", capture)).toBe(true);
    useSessionStore.getState().setActiveSession("session-b");
    expect(useSessionStore.getState().captures).toEqual([]);
    useSessionStore.getState().setActiveSession("session-a");
    expect(useSessionStore.getState().captures).toEqual([capture]);
    expect(useSessionStore.getState().deleteCapture("session-a", capture.id)).toBe(true);
    expect(useSessionStore.getState().captures).toEqual([]);
  });

  it("ignores stale capture mutations for a session that is no longer active", () => {
    installStorage();
    useSessionStore.getState().setActiveSession("session-a");
    const captureA = {
      id: "capture-a",
      asset_id: "asset-a",
      captured_at: "2026-11-01T10:00:00Z",
      source: "viewport" as const,
      camera: camera(12),
      region: null,
      pixel_region: null,
      viewport_width_px: null,
      viewport_height_px: null,
    };
    useSessionStore.getState().addCapture("session-a", captureA);
    useSessionStore.getState().setActiveSession("session-b");
    const captureB = { ...captureA, id: "capture-b", asset_id: "asset-b" };
    useSessionStore.getState().addCapture("session-b", captureB);

    expect(useSessionStore.getState().addCapture("session-a", captureA)).toBe(false);
    expect(useSessionStore.getState().deleteCapture("session-a", captureB.id)).toBe(false);
    expect(useSessionStore.getState().captures).toEqual([captureB]);
  });

  it("records camera history, supports undo/redo, and restores it per session", () => {
    installStorage();
    const store = useSessionStore.getState();
    store.setActiveSession("session-a");
    store.recordCamera(camera(1));
    store.recordCamera(camera(2));

    expect(useSessionStore.getState().undoCamera()).toEqual(camera(1));
    expect(useSessionStore.getState().redoCamera()).toEqual(camera(2));

    useSessionStore.getState().setActiveSession("session-b");
    expect(useSessionStore.getState().cameraHistory.present).toBeNull();
    useSessionStore.getState().setActiveSession("session-a");
    expect(useSessionStore.getState().cameraHistory.present).toEqual(camera(2));
    expect(useSessionStore.getState().cameraHistory.past).toEqual([camera(1)]);
  });

  it("clears the redo branch after a new navigation and caps stored history", () => {
    installStorage();
    useSessionStore.getState().setActiveSession("session-a");
    useSessionStore.getState().recordCamera(camera(1));
    useSessionStore.getState().recordCamera(camera(2));
    useSessionStore.getState().undoCamera();
    useSessionStore.getState().recordCamera(camera(3));
    expect(useSessionStore.getState().cameraHistory.future).toEqual([]);

    for (let longitude = 4; longitude < 110; longitude += 1) {
      useSessionStore.getState().recordCamera(camera(longitude));
    }
    expect(useSessionStore.getState().cameraHistory.past).toHaveLength(100);
  });

  it("persists bookmark creation, rename, update, and deletion", () => {
    installStorage();
    useSessionStore.getState().setActiveSession("session-a");
    const bookmark = useSessionStore.getState().addBookmark("  saved view  ", context(1));
    expect(bookmark.name).toBe("saved view");

    useSessionStore.getState().renameBookmark(bookmark.id, "Renamed");
    useSessionStore.getState().updateBookmark(bookmark.id, context(2));
    useSessionStore.getState().setActiveSession("session-b");
    useSessionStore.getState().setActiveSession("session-a");
    expect(useSessionStore.getState().bookmarks[0]).toMatchObject({
      id: bookmark.id,
      name: "Renamed",
      context: context(2),
    });

    useSessionStore.getState().deleteBookmark(bookmark.id);
    expect(useSessionStore.getState().bookmarks).toEqual([]);
    expect(() => useSessionStore.getState().renameBookmark(bookmark.id, "Missing")).toThrow(
      "does not exist",
    );
  });

  it("rejects empty names instead of creating nameless bookmarks", () => {
    installStorage();
    useSessionStore.getState().setActiveSession("session-a");
    expect(() => useSessionStore.getState().addBookmark("  ", context(1))).toThrow(
      "cannot be empty",
    );
  });

  it("requires a Platform session before saving bookmarks", () => {
    installStorage();
    expect(() => useSessionStore.getState().addBookmark("Orphan", context(1))).toThrow(
      "opening a Platform session",
    );
  });
});
