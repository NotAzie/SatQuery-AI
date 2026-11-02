import { beforeEach, describe, expect, it, vi } from "vitest";

const cesium = vi.hoisted(() => {
  const colorWithAlpha = vi.fn((alpha: number) => ({ alpha }));
  return {
    load: vi.fn(),
    colorWithAlpha,
    cyan: { alpha: 1, withAlpha: colorWithAlpha },
    yellow: { alpha: 1, withAlpha: colorWithAlpha },
  };
});

vi.mock("cesium", () => ({
  Color: {
    CYAN: cesium.cyan,
    YELLOW: cesium.yellow,
    fromCssColorString: vi.fn(),
  },
  ColorMaterialProperty: vi.fn(function (this: { color: unknown }, color: unknown) {
    this.color = color;
  }),
  GeoJsonDataSource: { load: cesium.load },
}));

import type { GeoJsonDataSource, Viewer } from "cesium";

import type { EngineEarthObjectGeoJSON } from "@/shared/types";

import { createCesiumOverlayController } from "./CesiumOverlayController";

function collection(): EngineEarthObjectGeoJSON {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: "object-1",
        geometry: { type: "Point", coordinates: [10, 20] },
        properties: {
          evidence_ids: ["evidence-1"],
          investigation_ids: ["investigation-1"],
          lifecycle: "active",
          object_id: "object-1",
          object_type: "site",
          revision: 1,
          source_observation_ids: ["observation-1"],
        },
      },
    ],
    "satquery:omitted_objects": [],
    "satquery:geometry_policy": "WGS 84 longitude/latitude only",
  };
}

function setup() {
  const source = { entities: { values: [] } } as unknown as GeoJsonDataSource;
  cesium.load.mockResolvedValue(source);
  const viewer = {
    clock: { currentTime: {} },
    dataSources: {
      add: vi.fn(async (value: GeoJsonDataSource) => value),
      remove: vi.fn(),
    },
    flyTo: vi.fn(async () => true),
    scene: { requestRender: vi.fn() },
  } as unknown as Viewer;
  return { source, viewer, overlays: createCesiumOverlayController(viewer) };
}

describe("Cesium investigation overlays", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("adds Engine GeoJSON to the viewer and removes it when cleared", async () => {
    const { source, viewer, overlays } = setup();
    const changed = vi.fn();
    overlays.onChange(changed);

    await overlays.showInvestigation("investigation-1", collection());
    expect(overlays.getState()).toMatchObject([
      {
        id: "investigation:investigation-1",
        investigation_id: "investigation-1",
        features: [{ id: "object-1" }],
      },
    ]);
    expect(changed).toHaveBeenLastCalledWith(overlays.getState());
    overlays.clear(["investigation:investigation-1"]);
    expect(overlays.getState()).toEqual([]);

    expect(cesium.load).toHaveBeenCalledWith(
      collection(),
      expect.objectContaining({ clampToGround: true }),
    );
    expect(viewer.dataSources.add).toHaveBeenCalledWith(source);
    expect(viewer.flyTo).toHaveBeenCalledWith(source);
    expect(viewer.dataSources.remove).toHaveBeenCalledWith(source, true);
  });

  it("does not add a GeoJSON source when it completes after clear", async () => {
    let resolveLoad!: (value: GeoJsonDataSource) => void;
    cesium.load.mockReturnValue(
      new Promise<GeoJsonDataSource>((resolve) => {
        resolveLoad = resolve;
      }),
    );
    const { source, viewer, overlays } = setup();
    const pending = overlays.showInvestigation("investigation-1", collection());

    overlays.clear();
    resolveLoad(source);
    await pending;

    expect(viewer.dataSources.add).not.toHaveBeenCalled();
  });

  it("removes all owned sources on destroy", async () => {
    const { source, viewer, overlays } = setup();
    await overlays.showInvestigation("investigation-1", collection());

    overlays.destroy();

    expect(viewer.dataSources.remove).toHaveBeenCalledWith(source, true);
  });
});
