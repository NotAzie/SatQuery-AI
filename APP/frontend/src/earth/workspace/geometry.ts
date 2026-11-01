import type { EarthDrawing, GeoJSONGeometry } from "./types";

const EARTH_RADIUS_M = 6_371_008.8;

export function distanceMeters(
  first: readonly [number, number],
  second: readonly [number, number],
): number {
  const radians = (degrees: number) => (degrees * Math.PI) / 180;
  const lat1 = radians(first[1]);
  const lat2 = radians(second[1]);
  const deltaLat = lat2 - lat1;
  const deltaLng = radians(second[0] - first[0]);
  const a =
    Math.sin(deltaLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function polygonAreaSquareMeters(
  ring: readonly (readonly [number, number])[],
): number {
  if (ring.length < 4) return 0;
  let total = 0;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const first = ring[index];
    const second = ring[index + 1];
    if (!first || !second) continue;
    const [lng1, lat1] = first;
    const [lng2, lat2] = second;
    total +=
      ((lng2 - lng1) * Math.PI) / 180 *
      (2 + Math.sin((lat1 * Math.PI) / 180) + Math.sin((lat2 * Math.PI) / 180));
  }
  return Math.abs((total * EARTH_RADIUS_M ** 2) / 2);
}

export function circleGeometry(
  center: readonly [number, number],
  radiusMeters: number,
  steps = 64,
): GeoJSONGeometry {
  if (!Number.isFinite(radiusMeters) || radiusMeters <= 0) {
    throw new RangeError("Circle radius must be positive and finite");
  }
  if (!Number.isInteger(steps) || steps < 8) {
    throw new RangeError("Circle geometry requires at least eight segments");
  }
  const [longitude, latitude] = center;
  const angularDistance = radiusMeters / EARTH_RADIUS_M;
  const lat1 = (latitude * Math.PI) / 180;
  const lon1 = (longitude * Math.PI) / 180;
  const ring: [number, number][] = [];
  for (let step = 0; step <= steps; step += 1) {
    const bearing = (2 * Math.PI * step) / steps;
    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(angularDistance) +
        Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing),
    );
    const lon2 =
      lon1 +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1),
        Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2),
      );
    ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return { type: "Polygon", coordinates: [ring] };
}

export function rectangleGeometry(
  first: readonly [number, number],
  second: readonly [number, number],
): GeoJSONGeometry {
  const west = Math.min(first[0], second[0]);
  const east = Math.max(first[0], second[0]);
  const south = Math.min(first[1], second[1]);
  const north = Math.max(first[1], second[1]);
  return {
    type: "Polygon",
    coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
  };
}

export function validateDrawing(drawing: EarthDrawing): void {
  if (
    drawing.kind === "point" &&
    drawing.geometry.type !== "Point"
  ) {
    throw new TypeError("Point drawings require a GeoJSON Point geometry");
  }
  if (
    drawing.kind === "line" &&
    (drawing.geometry.type !== "LineString" || drawing.geometry.coordinates.length < 2)
  ) {
    throw new TypeError("Line drawings require at least two coordinates");
  }
  if (drawing.kind === "polygon" || drawing.kind === "rectangle" || drawing.kind === "circle") {
    if (
      drawing.geometry.type !== "Polygon" ||
      !drawing.geometry.coordinates[0] ||
      drawing.geometry.coordinates[0].length < 4
    ) {
      throw new TypeError("Area drawings require a closed GeoJSON Polygon ring");
    }
  }
}
