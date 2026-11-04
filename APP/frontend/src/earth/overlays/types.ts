import type { EarthCommand, EarthOverlay, EngineEarthObjectGeoJSON } from "@/shared/types";
import type { Unsubscribe } from "@/shared/utils";

type AddOverlayCommand = Extract<EarthCommand, { type: "add_overlay" }>;

/** Transient Engine geometry, distinct from persistent data layers. */
export interface OverlayController {
  getState(): EarthOverlay[];
  onChange(listener: (overlays: EarthOverlay[]) => void): Unsubscribe;
  onHighlightChange(listener: (evidenceIds: string[]) => void): Unsubscribe;
  restore(overlays: readonly EarthOverlay[]): Promise<void>;
  add(command: AddOverlayCommand): Promise<void>;
  showInvestigation(
    investigationId: string,
    collection: EngineEarthObjectGeoJSON,
  ): Promise<void>;
  highlight(evidenceIds: readonly string[]): void;
  clear(overlayIds?: readonly string[]): void;
  destroy(): void;
}
