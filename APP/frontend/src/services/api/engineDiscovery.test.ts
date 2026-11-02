import { afterEach, describe, expect, it, vi } from "vitest";

import { apiUrl } from "./client";
import { getEngineDiscovery } from "./engineDiscovery";

describe("Engine discovery API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads Engine-authored dataset and image capability metadata", async () => {
    const discovery = {
      image_capabilities: [],
      datasets: [],
      earth_capabilities: {
        revision: "a".repeat(64),
        modalities: [],
        snapshot_sha256: "b".repeat(64),
        snapshot_schema_version: "1.0.0",
      },
      agent_tools: [],
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(discovery), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(getEngineDiscovery()).resolves.toEqual(discovery);
    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/intelligence/engine-discovery"),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });
});
