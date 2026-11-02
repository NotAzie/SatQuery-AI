import { afterEach, describe, expect, it, vi } from "vitest";

import { cancelAgentTurn, streamAgentTurn } from "./chat";
import { apiUrl } from "./client";

describe("chat API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests Engine cancellation through the session API", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);

    await cancelAgentTurn("platform/session");

    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/chat/sessions/platform%2Fsession/cancel"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("submits selected image asset references with the chat turn", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        'data: {"type":"engine.event"}\n\n',
        { headers: { "Content-Type": "text/event-stream" } },
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    const stream = streamAgentTurn(
      "session-1",
      {
        message: "Describe this image",
        asset_ids: ["asset-1"],
      },
      controller.signal,
    );

    await stream.next();

    expect(fetch).toHaveBeenCalledWith(
      apiUrl("/chat/sessions/session-1/turns"),
      expect.objectContaining({
        body: JSON.stringify({
          message: "Describe this image",
          asset_ids: ["asset-1"],
        }),
      }),
    );
  });
});
