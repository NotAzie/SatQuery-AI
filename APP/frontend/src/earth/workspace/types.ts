import type { CameraState, EarthContext, LngLat } from "@/shared/types";
import type { Unsubscribe } from "@/shared/utils";

export type DrawingKind = "point" | "line" | "polygon" | "rectangle" | "circle";
export type MeasurementKind = "distance" | "area" | "coordinates" | "elevation";
export type GeoJSONGeometry =
  | { type: "Point"; coordinates: [number, number] }
  | { type: "LineString"; coordinates: [number, number][] }
  | { type: "Polygon"; coordinates: [number, number][][] };

export interface EarthSelection {
  entity_id: string;
  position: LngLat | null;
  properties: Record<string, string | number | boolean | null>;
}

export interface EarthDrawing {
  id: string;
  name: string;
  kind: DrawingKind;
  geometry: GeoJSONGeometry;
}

export interface MeasurementResult {
  kind: MeasurementKind;
  value: number | null;
  unit: "m" | "km" | "m2" | "km2" | "degrees" | "m elevation";
  position: LngLat;
}

export interface EarthWorkspaceController {
  onSelectionChange(listener: (selection: EarthSelection | null) => void): Unsubscribe;
  onDrawingChange(listener: (drawings: EarthDrawing[]) => void): Unsubscribe;
  onMeasurement(listener: (measurement: MeasurementResult | null) => void): Unsubscribe;
  startDrawing(kind: DrawingKind): void;
  finishDrawing(): void;
  cancelInteraction(): void;
  replaceDrawings(drawings: readonly EarthDrawing[]): void;
  startMeasurement(kind: MeasurementKind): void;
  destroy(): void;
}

export interface CameraHistory {
  past: CameraState[];
  present: CameraState | null;
  future: CameraState[];
}

export interface EarthBookmark {
  id: string;
  name: string;
  context: EarthContext;
  created_at: string;
  updated_at: string;
}
