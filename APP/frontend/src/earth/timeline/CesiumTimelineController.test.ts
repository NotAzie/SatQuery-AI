import { Clock, ClockRange, JulianDate } from "cesium";
import { describe, expect, it, vi } from "vitest";

import { createTimelineController } from "./CesiumTimelineController";

describe("CesiumTimelineController", () => {
  it("sets a range, synchronizes the current instant, and publishes clock ticks", () => {
    const clock = new Clock();
    const controller = createTimelineController(clock);
    const listener = vi.fn();
    controller.onChange(listener);
    const range = {
      start: "2024-01-01T00:00:00.000Z",
      end: "2024-01-03T23:59:59.999Z",
    };

    controller.setRange(range);
    expect(controller.getState().range).toEqual(range);
    expect(controller.getState().instant?.toISOString()).toBe(range.start);
    expect(clock.shouldAnimate).toBe(false);
    expect(listener).toHaveBeenLastCalledWith(controller.getState());

    controller.setInstant(new Date("2024-01-02T12:00:00.000Z"));
    expect(controller.getState().instant?.toISOString()).toBe("2024-01-02T12:00:00.000Z");
    expect(controller.getState().range).toEqual(range);

    const tickInstant = JulianDate.fromDate(new Date("2024-01-03T00:00:00.000Z"));
    clock.currentTime = tickInstant;
    clock.onTick.raiseEvent(clock);
    expect(controller.getState().instant?.toISOString()).toBe("2024-01-03T00:00:00.000Z");
  });

  it("plays and pauses configured time ranges and rejects invalid operations", () => {
    const clock = new Clock();
    const controller = createTimelineController(clock);

    expect(() => controller.play(1)).toThrow("Set a timeline range before playback");
    controller.setRange({
      start: "2024-01-01T00:00:00Z",
      end: "2024-01-02T00:00:00Z",
    });
    controller.play(4);
    expect(controller.getState()).toMatchObject({ playing: true, speed: 4 });
    controller.pause();
    expect(controller.getState().playing).toBe(false);
    expect(() => controller.play(0)).toThrow("positive finite number");
    expect(() =>
      controller.setInstant(new Date("2024-01-03T00:00:00Z")),
    ).toThrow("within the selected range");
    expect(() =>
      controller.setRange({
        start: "2024-01-02T00:00:00Z",
        end: "2024-01-01T00:00:00Z",
      }),
    ).toThrow("start must not be after");
  });

  it("unsubscribes timeline listeners", () => {
    const controller = createTimelineController(new Clock());
    const listener = vi.fn();
    const unsubscribe = controller.onChange(listener);

    unsubscribe();
    controller.setInstant(new Date("2024-01-01T00:00:00Z"));
    expect(listener).not.toHaveBeenCalled();
  });

  it("removes its Cesium clock listener when destroyed", () => {
    const clock = new Clock();
    const controller = createTimelineController(clock);
    const listener = vi.fn();
    controller.onChange(listener);

    controller.destroy();
    clock.onTick.raiseEvent(clock);

    expect(listener).not.toHaveBeenCalled();
  });

  it("uses a clamped Cesium clock range until playback is requested", () => {
    const clock = new Clock();
    const controller = createTimelineController(clock);

    controller.setRange({
      start: "2024-01-01T00:00:00Z",
      end: "2024-01-02T00:00:00Z",
    });
    expect(clock.clockRange).toBe(ClockRange.CLAMPED);
    controller.play(1);
    expect(clock.clockRange).toBe(ClockRange.LOOP_STOP);
  });
});
