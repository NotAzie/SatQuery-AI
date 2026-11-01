import type { EarthCommand } from "@/shared/types";

type AddOverlayCommand = Extract<EarthCommand, { type: "add_overlay" }>;

/** Transient, command-driven graphics (regions, detections, labels), distinct from layers. */
export interface OverlayController {
  add(command: AddOverlayCommand): void;
  highlight(evidenceIds: readonly string[]): void;
  clear(overlayIds?: readonly string[]): void;
}
