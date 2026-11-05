import type { EarthController } from "./controller";
import type { EarthEventBus } from "./events";
import { useEarthStore } from "@/state/earthStore";
import type { EarthContext } from "@/shared/types";
import type { EarthDrawing, GeoJSONGeometry } from "./workspace/types";

type Position = [number, number];

function isPosition(value: unknown): value is Position {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    value.every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate))
  );
}

function isPositionList(value: unknown, minimum: number): value is Position[] {
  return Array.isArray(value) && value.length >= minimum && value.every(isPosition);
}

function isPolygonCoordinates(value: unknown): value is Position[][] {
  return Array.isArray(value) && value.every((ring) => isPositionList(ring, 4));
}

function restoreDrawings(drawings: EarthContext["drawings"]): EarthDrawing[] {
  return drawings.map((drawing) => {
    const geometry = drawing.geometry;
    if (typeof geometry !== "object" || geometry === null || Array.isArray(geometry)) {
      throw new RangeError(`Saved drawing '${drawing.id}' has invalid geometry`);
    }
    const record = geometry;
    let restoredGeometry: GeoJSONGeometry;
    if (drawing.kind === "point" && record.type === "Point" && isPosition(record.coordinates)) {
      restoredGeometry = { type: "Point", coordinates: record.coordinates };
    } else if (
      drawing.kind === "line" &&
      record.type === "LineString" &&
      isPositionList(record.coordinates, 2)
    ) {
      restoredGeometry = { type: "LineString", coordinates: record.coordinates };
    } else if (
      ["polygon", "rectangle", "circle"].includes(drawing.kind) &&
      record.type === "Polygon" &&
      isPolygonCoordinates(record.coordinates)
    ) {
      restoredGeometry = {
        type: "Polygon",
        coordinates: record.coordinates,
      };
    } else {
      throw new RangeError(`Saved drawing '${drawing.id}' has unsupported geometry`);
    }
    return {
      id: drawing.id,
      name: drawing.name,
      kind: drawing.kind,
      geometry: restoredGeometry,
    };
  });
}

export async function restoreEarthContext(
  context: EarthContext,
  controller: EarthController,
  secondaryController: EarthController | null,
  events: EarthEventBus,
): Promise<void> {
  const earth = useEarthStore.getState();
  await controller.layers?.restore(context.layers);
  earth.setCamera(context.camera);
  earth.setViewport(context.viewport);
  earth.setLayers(context.layers);
  earth.setCaptures(context.captures);
  earth.setSelection(context.selection);
  earth.setSplitView(context.split_view.enabled && Boolean(secondaryController));
  earth.setSyncCameras(context.split_view.sync_cameras && Boolean(secondaryController));
  earth.setSecondaryCamera(secondaryController ? context.secondary_view?.camera ?? null : null);
  earth.setSecondaryViewport(secondaryController ? context.secondary_view?.viewport ?? null : null);
  earth.setSecondaryOverlays(secondaryController ? context.secondary_view?.overlays ?? [] : []);
  earth.setSecondarySelectedEvidenceIds(
    secondaryController ? context.secondary_view?.selected_evidence_ids ?? [] : [],
  );
  const measurement = context.measurement
    ? {
        kind: context.measurement.kind,
        value: context.measurement.value,
        unit: context.measurement.unit,
        position: context.measurement.position,
      }
    : null;
  earth.setMeasurement(measurement);

  controller.camera.restore(context.camera);
  controller.timeline.restore({
    instant: context.instant ? new Date(context.instant) : null,
    range: context.time,
    playing: context.timeline_playback.playing,
    speed: context.timeline_playback.speed,
  });
  controller.workspace.replaceDrawings(restoreDrawings(context.drawings));
  await controller.overlays.restore(context.overlays);
  controller.overlays.highlight(context.selected_evidence_ids);
  events.publish({ type: "earth.selection.changed", selection: context.selection });
  events.publish({
    type: "earth.measurement.changed",
    measurement,
  });

  if (!secondaryController) return;
  if (!context.secondary_view) {
    secondaryController.overlays.clear();
    secondaryController.overlays.highlight([]);
    return;
  }
  secondaryController.camera.restore(context.secondary_view.camera);
  await secondaryController.overlays.restore(context.secondary_view.overlays);
  secondaryController.overlays.highlight(context.secondary_view.selected_evidence_ids);
}
