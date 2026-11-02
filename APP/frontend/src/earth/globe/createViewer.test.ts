import { vi, describe, expect, it } from "vitest";

const cesium = vi.hoisted(() => ({
  colorFromCssColorString: vi.fn((value: string) => value),
  ion: { defaultAccessToken: undefined as string | undefined },
  viewer: vi.fn(),
}));

vi.mock("cesium", () => ({
  Color: { fromCssColorString: cesium.colorFromCssColorString },
  Ion: cesium.ion,
  Viewer: cesium.viewer,
}));

import { createViewer } from "./createViewer";

describe("createViewer", () => {
  it("uses request-render mode for idle workspaces", () => {
    const viewerInstance = { scene: { globe: {} } };
    cesium.viewer.mockImplementation(function () {
      return viewerInstance;
    });

    const viewer = createViewer({} as HTMLElement);

    expect(viewer).toBe(viewerInstance);
    expect(cesium.viewer).toHaveBeenCalledWith(
      {},
      expect.objectContaining({ requestRenderMode: true }),
    );
  });
});
