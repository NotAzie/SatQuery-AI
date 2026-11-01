import { describe, expect, it } from "vitest";

import {
  circleGeometry,
  distanceMeters,
  polygonAreaSquareMeters,
  rectangleGeometry,
  validateDrawing,
} from "./geometry";

describe("Earth workspace geometry", () => {
  it("measures geodesic distance in meters", () => {
    expect(distanceMeters([0, 0], [1, 0])).toBeCloseTo(111_195, -1);
  });

  it("computes a positive spherical polygon area", () => {
    const square = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
      [0, 0],
    ] as const;
    expect(polygonAreaSquareMeters(square)).toBeGreaterThan(12_000_000_000);
    expect(polygonAreaSquareMeters(square)).toBeLessThan(13_000_000_000);
  });

  it("creates presentation geometry for circles and rectangles", () => {
    const circle = circleGeometry([0, 0], 1000);
    expect(circle.type).toBe("Polygon");
    if (circle.type === "Polygon") expect(circle.coordinates[0]).toHaveLength(65);

    expect(rectangleGeometry([2, 4], [-1, 3])).toEqual({
      type: "Polygon",
      coordinates: [[[-1, 3], [2, 3], [2, 4], [-1, 4], [-1, 3]]],
    });
  });

  it("rejects drawings whose shape and GeoJSON geometry do not agree", () => {
    expect(() =>
      validateDrawing({
        id: "shape-1",
        name: "broken point",
        kind: "point",
        geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] },
      }),
    ).toThrow("Point drawings require");
  });
});
