import { afterEach, describe, expect, it } from "vitest";

import { snapshotEarthContext, useEarthStore } from "./earthStore";
import { useSessionStore } from "./sessionStore";

afterEach(() => {
  useEarthStore.setState({
    camera: null,
    timeline: { instant: null, range: null, playing: false, speed: 1 },
    selection: null,
    drawings: [],
    captures: [],
    measurement: null,
    splitView: false,
    syncCameras: false,
  });
  useSessionStore.setState({
    bookmarks: [],
    cameraHistory: { past: [], present: null, future: [] },
  });
});

describe("Earth context snapshot", () => {
  it("reflects the current timeline range and instant", () => {
    const instant = new Date("2024-06-15T12:30:00.000Z");
    const range = {
      start: "2024-06-01T00:00:00.000Z",
      end: "2024-06-30T23:59:59.999Z",
    };

    useEarthStore.setState({
      camera: {
        position: { lng: 0, lat: 0 },
        height_m: 1_000_000,
        heading_deg: 0,
        pitch_deg: -90,
        roll_deg: 0,
        view_rect: null,
      },
      timeline: { instant, range, playing: false, speed: 1 },
    });

    expect(snapshotEarthContext()).toMatchObject({
      time: range,
      instant: instant.toISOString(),
    });
  });

  it("does not create an Earth context before camera state exists", () => {
    expect(snapshotEarthContext()).toBeNull();
  });

  it("shares serializable selection and drawings in the EarthContext snapshot", () => {
    const camera = {
      position: { lng: 1, lat: 2 },
      height_m: 1000,
      heading_deg: 0,
      pitch_deg: -90,
      roll_deg: 0,
      view_rect: null,
    };
    const selection = {
      entity_id: "entity-1",
      position: { lng: 1, lat: 2 },
      properties: { label: "picked" },
    };
    const drawings = [
      {
        id: "drawing-1",
        name: "Point 1",
        kind: "point" as const,
        geometry: { type: "Point" as const, coordinates: [1, 2] as [number, number] },
      },
    ];
    useEarthStore.setState({ camera, selection, drawings });

    expect(snapshotEarthContext()).toMatchObject({ selection, drawings });
  });

  it("includes captured image metadata in EarthContext", () => {
    const camera = {
      position: { lng: 1, lat: 2 },
      height_m: 1000,
      heading_deg: 0,
      pitch_deg: -90,
      roll_deg: 0,
      view_rect: null,
    };
    const capture = {
      id: "capture-1",
      asset_id: "image-1",
      captured_at: "2026-11-01T10:00:00Z",
      source: "viewport" as const,
      camera,
      region: null,
      pixel_region: null,
      viewport_width_px: null,
      viewport_height_px: null,
    };
    useEarthStore.setState({ camera, captures: [capture] });
    expect(snapshotEarthContext()?.captures).toEqual([capture]);
  });

  it("stores split-view and camera-sync preferences independently", () => {
    useEarthStore.getState().setSplitView(true);
    useEarthStore.getState().setSyncCameras(true);
    expect(useEarthStore.getState()).toMatchObject({ splitView: true, syncCameras: true });
  });

  it("includes bookmarks, camera history, split-view, and measurement in the canonical snapshot", () => {
    const camera = {
      position: { lng: 1, lat: 2 },
      height_m: 1000,
      heading_deg: 0,
      pitch_deg: -90,
      roll_deg: 0,
      view_rect: null,
    };
    const context = {
      camera,
      layers: [],
      time: null,
      instant: null,
      selection: null,
      drawings: [],
      captures: [],
      selected_evidence_ids: [],
      bookmarks: [],
      camera_history: { past: [], present: camera, future: [] },
      split_view: { enabled: true, sync_cameras: true },
      measurement: null,
    };
    useEarthStore.setState({
      camera,
      splitView: true,
      syncCameras: true,
    });
    useSessionStore.setState({
      cameraHistory: { past: [], present: camera, future: [] },
      bookmarks: [
        {
          id: "bookmark-1",
          name: "Field site",
          context,
          created_at: "2026-11-01T10:00:00Z",
          updated_at: "2026-11-01T10:00:00Z",
        },
      ],
    });

    expect(snapshotEarthContext()).toMatchObject({
      bookmarks: [
        {
          id: "bookmark-1",
          name: "Field site",
          camera,
          time: null,
          instant: null,
        },
      ],
      camera_history: { present: camera },
      split_view: { enabled: true, sync_cameras: true },
      measurement: null,
    });
  });
});
