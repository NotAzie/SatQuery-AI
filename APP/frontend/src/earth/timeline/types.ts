import type { TimeRange } from "@/shared/types";
import type { Unsubscribe } from "@/shared/utils";

export interface TimelineState {
  instant: Date | null;
  range: TimeRange | null;
  playing: boolean;
  speed: number;
}

/** Time as a first-class axis: change detection and monitoring animate over it. */
export interface TimelineController {
  setInstant(instant: Date): void;
  setRange(range: TimeRange): void;
  restore(state: TimelineState): void;
  play(speed: number): void;
  pause(): void;
  getState(): TimelineState;
  onChange(listener: (state: TimelineState) => void): Unsubscribe;
  destroy(): void;
}
