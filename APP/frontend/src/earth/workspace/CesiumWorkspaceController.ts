import {
  Cartesian2,
  Cartesian3,
  Cartographic,
  Color,
  Entity,
  Math as CesiumMath,
  PolygonHierarchy,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  type Viewer,
} from "cesium";

import { distanceMeters, circleGeometry, rectangleGeometry, polygonAreaSquareMeters } from "./geometry";
import type {
  DrawingKind,
  EarthDrawing,
  EarthSelection,
  EarthWorkspaceController,
  GeoJSONGeometry,
  MeasurementKind,
  MeasurementResult,
} from "./types";
import type { EarthEvent, EarthEventBus } from "../events";

type Position = [number, number];
type Interaction =
  | { type: "drawing"; kind: DrawingKind; points: Position[] }
  | { type: "measurement"; kind: MeasurementKind; points: Position[] }
  | null;

function positionAt(viewer: Viewer, screenPosition: Cartesian2): Position | null {
  const ray = viewer.camera.getPickRay(screenPosition);
  const world = ray ? viewer.scene.globe.pick(ray, viewer.scene) : undefined;
  const position =
    world ?? viewer.camera.pickEllipsoid(screenPosition, viewer.scene.globe.ellipsoid);
  if (!position) return null;
  const cartographic = Cartographic.fromCartesian(position);
  return [CesiumMath.toDegrees(cartographic.longitude), CesiumMath.toDegrees(cartographic.latitude)];
}

function propertySnapshot(entity: Entity, viewer: Viewer): EarthSelection["properties"] {
  const result: EarthSelection["properties"] = {};
  const names = entity.properties?.propertyNames ?? [];
  for (const name of names) {
    const value: unknown = entity.properties?.[name]?.getValue(viewer.clock.currentTime);
    if (
      name === "evidence_ids" &&
      Array.isArray(value) &&
      value.every((item) => typeof item === "string")
    ) {
      result[name] = JSON.stringify(value);
      continue;
    }
    if (
      value === null ||
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      result[name] = value;
    }
  }
  return result;
}

function geometryPositions(geometry: GeoJSONGeometry): Position[] {
  if (geometry.type === "Point") return [geometry.coordinates];
  if (geometry.type === "LineString") return geometry.coordinates;
  return geometry.coordinates[0] ?? [];
}

function requiredPoint(points: Position[], index: number): Position {
  const point = points[index];
  if (!point) throw new RangeError(`Drawing requires point ${index + 1}`);
  return point;
}

function renderDrawing(viewer: Viewer, drawing: EarthDrawing): void {
  const positions = geometryPositions(drawing.geometry);
  const options = {
    id: `drawing:${drawing.id}`,
    name: drawing.name,
    properties: { earthDrawingId: drawing.id, earthDrawingKind: drawing.kind },
  };
  if (drawing.geometry.type === "Point") {
    viewer.entities.add({
      ...options,
      position: Cartesian3.fromDegrees(...drawing.geometry.coordinates),
      point: { pixelSize: 10, color: Color.CYAN, outlineColor: Color.WHITE, outlineWidth: 1 },
    });
  } else if (drawing.geometry.type === "LineString") {
    viewer.entities.add({
      ...options,
      polyline: {
        positions: Cartesian3.fromDegreesArray(positions.flat()),
        width: 3,
        material: Color.CYAN,
      },
    });
  } else {
    viewer.entities.add({
      ...options,
      polygon: {
        hierarchy: new PolygonHierarchy(Cartesian3.fromDegreesArray(positions.flat())),
        material: Color.CYAN.withAlpha(0.2),
        outline: true,
        outlineColor: Color.CYAN,
      },
    });
  }
}

function closedRing(points: Position[]): Position[] {
  return [...points, requiredPoint(points, 0)];
}

function drawingGeometry(kind: DrawingKind, points: Position[]): GeoJSONGeometry {
  if (kind === "point") return { type: "Point", coordinates: requiredPoint(points, 0) };
  if (kind === "line") return { type: "LineString", coordinates: points };
  if (kind === "rectangle") {
    return rectangleGeometry(requiredPoint(points, 0), requiredPoint(points, 1));
  }
  if (kind === "circle") {
    const center = requiredPoint(points, 0);
    return circleGeometry(center, distanceMeters(center, requiredPoint(points, 1)));
  }
  return { type: "Polygon", coordinates: [closedRing(points)] };
}

export function createCesiumWorkspaceController(
  viewer: Viewer,
  events: EarthEventBus,
): EarthWorkspaceController {
  let interaction: Interaction = null;
  let drawings: EarthDrawing[] = [];
  let handler: ScreenSpaceEventHandler | null = null;
  const renderedDrawingIds = new Set<string>();

  const publishSelection = (selection: EarthSelection | null) => {
    events.publish({ type: "earth.selection.changed", selection });
  };
  const publishDrawings = () => {
    const snapshot = drawings.map((drawing) => ({ ...drawing }));
    events.publish({ type: "earth.drawings.changed", drawings: snapshot });
  };
  const publishMeasurement = (measurement: MeasurementResult | null) => {
    events.publish({ type: "earth.measurement.changed", measurement });
  };

  function finishDrawing() {
    if (interaction?.type !== "drawing") return;
    const { kind, points } = interaction;
    const minPoints = kind === "point" ? 1 : kind === "line" || kind === "rectangle" || kind === "circle" ? 2 : 3;
    if (points.length < minPoints) {
      throw new RangeError(`A ${kind} requires at least ${minPoints} point${minPoints === 1 ? "" : "s"}`);
    }
    const drawing: EarthDrawing = {
      id: globalThis.crypto.randomUUID(),
      name: `${kind.charAt(0).toUpperCase()}${kind.slice(1)} ${drawings.length + 1}`,
      kind,
      geometry: drawingGeometry(kind, points),
    };
    drawings = [...drawings, drawing];
    renderDrawing(viewer, drawing);
    renderedDrawingIds.add(drawing.id);
    viewer.scene.requestRender();
    interaction = null;
    releaseHandler();
    publishDrawings();
  }

  function finishMeasurement(position: Position) {
    if (interaction?.type !== "measurement") return;
    const { kind, points } = interaction;
    if (kind === "coordinates") {
      publishMeasurement({ kind, value: null, unit: "degrees", position: { lng: position[0], lat: position[1] } });
      interaction = null;
      releaseHandler();
      return;
    }
    if (kind === "elevation") {
      const height = viewer.scene.globe.getHeight(
        Cartographic.fromDegrees(position[0], position[1]),
      );
      publishMeasurement({
        kind,
        value: height === undefined || !Number.isFinite(height) ? null : height,
        unit: "m elevation",
        position: { lng: position[0], lat: position[1] },
      });
      interaction = null;
      releaseHandler();
      return;
    }
    points.push(position);
    if (kind === "distance" && points.length >= 2) {
      const meters = distanceMeters(requiredPoint(points, 0), requiredPoint(points, 1));
      publishMeasurement({
        kind,
        value: meters >= 1000 ? meters / 1000 : meters,
        unit: meters >= 1000 ? "km" : "m",
        position: { lng: position[0], lat: position[1] },
      });
      interaction = null;
      releaseHandler();
      return;
    }
  }

  function releaseHandler() {
    handler?.destroy();
    handler = null;
  }

  function ensureHandler() {
    if (handler) return;
    handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction(({ position }: { position: Cartesian2 }) => {
      const coordinate = positionAt(viewer, position);
      if (!coordinate) return;
      if (interaction?.type === "drawing") {
        interaction.points.push(coordinate);
        if (interaction.kind === "point") finishDrawing();
        else if (
          (interaction.kind === "rectangle" || interaction.kind === "circle") &&
          interaction.points.length === 2
        ) {
          finishDrawing();
        }
        return;
      }
      if (interaction?.type === "measurement") finishMeasurement(coordinate);
    }, ScreenSpaceEventType.LEFT_CLICK);

    handler.setInputAction(() => {
      if (interaction?.type === "drawing") finishDrawing();
      else if (interaction?.type === "measurement" && interaction.kind === "area") {
        const points = interaction.points;
        if (points.length < 3) throw new RangeError("Area measurement requires at least three points");
        const area = polygonAreaSquareMeters(closedRing(points));
        const last = requiredPoint(points, points.length - 1);
        publishMeasurement({
          kind: "area",
          value: area >= 1_000_000 ? area / 1_000_000 : area,
          unit: area >= 1_000_000 ? "km2" : "m2",
          position: { lng: last[0], lat: last[1] },
        });
        interaction = null;
        releaseHandler();
      }
    }, ScreenSpaceEventType.RIGHT_CLICK);
  }

  function syncDrawings(nextDrawings: readonly EarthDrawing[]) {
    for (const id of renderedDrawingIds) viewer.entities.removeById(`drawing:${id}`);
    renderedDrawingIds.clear();
    drawings = [...nextDrawings];
    for (const drawing of drawings) {
      renderDrawing(viewer, drawing);
      renderedDrawingIds.add(drawing.id);
    }
    viewer.scene.requestRender();
  }

  const removeSelectionListener = viewer.selectedEntityChanged.addEventListener((entity) => {
    if (!entity) {
      publishSelection(null);
      return;
    }
    const position = entity.position?.getValue(viewer.clock.currentTime);
    const cartographic = position ? Cartographic.fromCartesian(position) : null;
    publishSelection({
      entity_id: String(entity.id),
      position: cartographic
        ? {
            lng: CesiumMath.toDegrees(cartographic.longitude),
            lat: CesiumMath.toDegrees(cartographic.latitude),
          }
        : null,
      properties: propertySnapshot(entity, viewer),
    });
  });

  const unsubscribe = events.subscribe((event: EarthEvent) => {
    if (
      event.type === "earth.drawings.changed" &&
      JSON.stringify(event.drawings) !== JSON.stringify(drawings)
    ) {
      syncDrawings(event.drawings);
    }
  });

  return {
    onSelectionChange(listener) {
      return events.subscribe((event) => {
        if (event.type === "earth.selection.changed") listener(event.selection);
      });
    },
    onDrawingChange(listener) {
      return events.subscribe((event) => {
        if (event.type === "earth.drawings.changed") listener(event.drawings);
      });
    },
    onMeasurement(listener) {
      return events.subscribe((event) => {
        if (event.type === "earth.measurement.changed") listener(event.measurement);
      });
    },
    startDrawing(kind) {
      interaction = { type: "drawing", kind, points: [] };
      ensureHandler();
      publishMeasurement(null);
    },
    finishDrawing,
    cancelInteraction() {
      interaction = null;
      releaseHandler();
      publishMeasurement(null);
    },
    replaceDrawings(nextDrawings) {
      syncDrawings(nextDrawings);
      publishDrawings();
    },
    startMeasurement(kind) {
      interaction = { type: "measurement", kind, points: [] };
      ensureHandler();
      publishMeasurement(null);
    },
    destroy() {
      releaseHandler();
      removeSelectionListener();
      unsubscribe();
      for (const id of renderedDrawingIds) viewer.entities.removeById(`drawing:${id}`);
      renderedDrawingIds.clear();
    },
  };
}
