import { describe, expect, it, vi } from "vitest";

import { createEarthEventBus } from "./events";

describe("EarthEventBus", () => {
  it("publishes typed selection changes and supports unsubscribe", () => {
    const events = createEarthEventBus();
    const listener = vi.fn();
    const unsubscribe = events.subscribe(listener);
    const selection = {
      entity_id: "entity-1",
      position: { lng: 8, lat: 47 },
      properties: { source: "user", quality: 4, valid: true },
    };

    events.publish({ type: "earth.selection.changed", selection });
    expect(listener).toHaveBeenLastCalledWith({
      type: "earth.selection.changed",
      selection,
    });
    unsubscribe();
    events.publish({ type: "earth.selection.changed", selection: null });
    expect(listener).toHaveBeenCalledOnce();
  });
});
