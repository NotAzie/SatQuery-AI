import { afterEach, describe, expect, it, vi } from "vitest";

import { apiUrl } from "./client";
import { getMonitoringTriggers } from "./monitoring";

describe("monitoring API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests a trigger-history page with its continuation cursor", async () => {
    const history = {
      schedule_id: "schedule-1",
      schedule_revision: 3,
      policies: [],
      events: [],
      next_cursor: null,
      has_more: false,
    };
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(history), {
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);

    await expect(getMonitoringTriggers("schedule/1", 25, "cursor value"))
      .resolves.toEqual(history);

    expect(fetch).toHaveBeenCalledWith(
      apiUrl(
        "/monitoring/schedules/schedule%2F1/triggers?limit=25&cursor=cursor+value",
      ),
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });
});
