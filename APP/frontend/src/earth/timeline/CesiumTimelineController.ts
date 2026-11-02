import { ClockRange, ClockStep, JulianDate, type Clock } from "cesium";

import type { TimeRange } from "@/shared/types";

import type { TimelineController, TimelineState } from "./types";

type TimelineClock = Pick<
  Clock,
  | "clockRange"
  | "clockStep"
  | "currentTime"
  | "multiplier"
  | "onTick"
  | "shouldAnimate"
  | "startTime"
  | "stopTime"
>;

function toDate(value: string): Date {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new RangeError("Timeline date must be valid");
  return date;
}

function toRange(start: Date, stop: Date): TimeRange {
  if (start.getTime() > stop.getTime()) {
    throw new RangeError("Timeline range start must not be after its end");
  }
  return { start: start.toISOString(), end: stop.toISOString() };
}

export function createTimelineController(clock: TimelineClock): TimelineController {
  const listeners = new Set<(state: TimelineState) => void>();
  let range: TimeRange | null = null;

  const state = (): TimelineState => ({
    instant: JulianDate.toDate(clock.currentTime),
    range,
    playing: clock.shouldAnimate,
    speed: clock.multiplier,
  });

  const publish = () => {
    const snapshot = state();
    listeners.forEach((listener) => listener(snapshot));
  };

  const removeTickListener = clock.onTick.addEventListener(() => publish());

  return {
    getState: state,

    setInstant(instant) {
      if (!Number.isFinite(instant.getTime())) {
        throw new RangeError("Timeline instant must be a valid date");
      }
      if (range) {
        const start = toDate(range.start).getTime();
        const end = toDate(range.end).getTime();
        if (instant.getTime() < start || instant.getTime() > end) {
          throw new RangeError("Timeline instant must be within the selected range");
        }
      }
      clock.currentTime = JulianDate.fromDate(instant);
      publish();
    },

    setRange(nextRange) {
      const start = toDate(nextRange.start);
      const stop = toDate(nextRange.end);
      range = toRange(start, stop);
      clock.startTime = JulianDate.fromDate(start);
      clock.stopTime = JulianDate.fromDate(stop);
      clock.currentTime = JulianDate.fromDate(start);
      clock.clockRange = ClockRange.CLAMPED;
      clock.clockStep = ClockStep.SYSTEM_CLOCK_MULTIPLIER;
      clock.shouldAnimate = false;
      publish();
    },

    play(speed) {
      if (!range) throw new Error("Set a timeline range before playback");
      if (!Number.isFinite(speed) || speed <= 0) {
        throw new RangeError("Timeline playback speed must be a positive finite number");
      }
      clock.multiplier = speed;
      clock.clockRange = ClockRange.LOOP_STOP;
      clock.clockStep = ClockStep.SYSTEM_CLOCK_MULTIPLIER;
      clock.shouldAnimate = true;
      publish();
    },

    pause() {
      clock.shouldAnimate = false;
      publish();
    },

    onChange(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    destroy() {
      removeTickListener();
      listeners.clear();
    },
  };
}
