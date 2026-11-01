import { afterEach, describe, expect, it } from "vitest";

import type { ImageAsset } from "@/shared/types";

import { useVisionStore } from "./visionStore";

afterEach(() => {
  useVisionStore.setState({ selectedAssets: [], panelOpen: false });
});

describe("Vision attachment state", () => {
  it("shares selected session-scoped assets with the chat and toggles the intake panel", () => {
    const asset: ImageAsset = {
      id: "image-1",
      session_id: "session-a",
      mime_type: "image/png",
      size_bytes: 12,
      width: 2,
      height: 2,
      sha256: "hash",
      origin: "upload",
      filename: "image.png",
      georef: null,
      created_at: "2026-11-01T10:00:00Z",
      source_metadata: {},
    };

    useVisionStore.getState().setSelectedAssets([asset]);
    useVisionStore.getState().setPanelOpen(true);
    expect(useVisionStore.getState()).toMatchObject({
      selectedAssets: [asset],
      panelOpen: true,
    });

    useVisionStore.getState().setPanelOpen(false);
    expect(useVisionStore.getState().panelOpen).toBe(false);
  });
});
