import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("cesium", () => {
  class Cartesian2 {
    constructor(
      readonly x: number,
      readonly y: number,
    ) {}
  }
  class Entity {
    readonly properties?: Record<string, unknown> & {
      propertyNames: string[];
    };
    constructor(
      readonly id: string,
      values?: Record<string, { getValue: () => unknown }>,
    ) {
      if (values) this.properties = { ...values, propertyNames: Object.keys(values) };
    }
  }
  class Color {
    static readonly CYAN = new Color();
    static readonly WHITE = new Color();
    withAlpha() {
      return this;
    }
  }
  class PolygonHierarchy {
    constructor(readonly positions: unknown) {}
  }
  class ScreenSpaceEventHandler {
    static latest: ScreenSpaceEventHandler;
    private readonly actions = new Map<number, (event: { position: Cartesian2 }) => void>();
    constructor() {
      ScreenSpaceEventHandler.latest = this;
    }
    setInputAction(action: (event: { position: Cartesian2 }) => void, type: number) {
      this.actions.set(type, action);
    }
    trigger(type: number, event: { position: Cartesian2 }) {
      this.actions.get(type)?.(event);
    }
    destroy() {}
  }
  return {
    Cartesian2,
    Cartesian3: {
      fromDegrees: (...coordinates: number[]) => coordinates,
      fromDegreesArray: (coordinates: number[]) => coordinates,
    },
    Cartographic: {
      fromCartesian: (value: { longitude: number; latitude: number }) => value,
      fromDegrees: (longitude: number, latitude: number) => ({ longitude, latitude }),
    },
    Color,
    Entity,
    Math: { toDegrees: (degrees: number) => degrees },
    PolygonHierarchy,
    ScreenSpaceEventHandler,
    ScreenSpaceEventType: { LEFT_CLICK: 1, RIGHT_CLICK: 2 },
  };
});

import {
  Cartesian2,
  Entity,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  type Viewer,
} from "cesium";

import { createEarthEventBus } from "../events";
import { createCesiumWorkspaceController } from "./CesiumWorkspaceController";

interface MockHandler {
  trigger(type: number, event: { position: Cartesian2 }): void;
}

function currentHandler(): MockHandler {
  const mocked = ScreenSpaceEventHandler as unknown as {
    latest: MockHandler;
  };
  return mocked.latest;
}

function createEntity(
  id: string,
  properties: Record<string, { getValue: () => unknown }>,
): Entity {
  const MockEntity = Entity as unknown as new (
    entityId: string,
    values: Record<string, { getValue: () => unknown }>,
  ) => Entity;
  return new MockEntity(id, properties);
}

function fakeViewer() {
  const createdEntities: unknown[] = [];
  const viewer = {
    scene: {
      canvas: {},
      globe: {
        ellipsoid: {},
        pick: (ray: { x: number; y: number }) => ({ longitude: ray.x, latitude: ray.y }),
        getHeight: () => 321,
      },
      pick: () => null,
    },
    camera: {
      getPickRay: (position: Cartesian2) => position,
      pickEllipsoid: () => undefined,
    },
    clock: { currentTime: new Date() },
    entities: {
      add: (entity: unknown) => createdEntities.push(entity),
      removeById: vi.fn((id: string) => {
        const index = createdEntities.findIndex(
          (entity) =>
            typeof entity === "object" &&
            entity !== null &&
            "id" in entity &&
            entity.id === id,
        );
        if (index >= 0) createdEntities.splice(index, 1);
      }),
    },
  };
  return { viewer: viewer as unknown as Viewer, createdEntities };
}

function click(x: number, y: number): { position: Cartesian2 } {
  return { position: new Cartesian2(x, y) };
}

describe("Cesium workspace controller", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("publishes entity selection and deselection changes as typed Earth events", () => {
    const { viewer } = fakeViewer();
    const events = createEarthEventBus();
    const received = vi.fn();
    events.subscribe(received);
    const selected = createEntity("feature-7", {
      class: { getValue: () => "water" },
      count: { getValue: () => 3 },
      ignored: { getValue: () => ({ internal: true }) },
    });
    viewer.scene.pick = () => ({ id: selected });
    const controller = createCesiumWorkspaceController(viewer, events);
    const pointer = currentHandler();

    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(12, 48));
    expect(received).toHaveBeenLastCalledWith({
      type: "earth.selection.changed",
      selection: {
        entity_id: "feature-7",
        position: { lng: 12, lat: 48 },
        properties: { class: "water", count: 3 },
      },
    });

    viewer.scene.pick = () => null;
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(12, 48));
    expect(received).toHaveBeenLastCalledWith({
      type: "earth.selection.changed",
      selection: null,
    });
    controller.destroy();
  });

  it("creates GeoJSON presentation drawings without invoking Engine behavior", () => {
    const { viewer, createdEntities } = fakeViewer();
    const secondary = fakeViewer();
    const events = createEarthEventBus();
    const changed = vi.fn();
    events.subscribe(changed);
    const controller = createCesiumWorkspaceController(viewer, events);
    const pointer = currentHandler();
    const secondaryController = createCesiumWorkspaceController(secondary.viewer, events);

    controller.startDrawing("point");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(4, 5));
    expect(changed).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: "earth.drawings.changed",
        drawings: [
          expect.objectContaining({
            kind: "point",
            geometry: { type: "Point", coordinates: [4, 5] },
          }),
        ],
      }),
    );
    expect(createdEntities).toHaveLength(1);

    controller.startDrawing("line");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(0, 0));
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(1, 1));
    pointer.trigger(ScreenSpaceEventType.RIGHT_CLICK, click(1, 1));
    expect(changed).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: "earth.drawings.changed",
        drawings: expect.arrayContaining([
          expect.objectContaining({
            kind: "line",
            geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] },
          }),
        ]),
      }),
    );

    controller.startDrawing("polygon");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(0, 0));
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(1, 0));
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(1, 1));
    pointer.trigger(ScreenSpaceEventType.RIGHT_CLICK, click(1, 1));

    controller.startDrawing("rectangle");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(-1, -1));
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(1, 1));

    controller.startDrawing("circle");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(5, 5));
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(5.1, 5));
    const latestDrawings = changed.mock.calls
      .filter(([event]) => event.type === "earth.drawings.changed")
      .at(-1)?.[0];
    expect(latestDrawings).toMatchObject({
      drawings: [
        { kind: "point" },
        { kind: "line" },
        { kind: "polygon" },
        { kind: "rectangle" },
        { kind: "circle" },
      ],
    });
    expect(createdEntities).toHaveLength(5);
    expect(secondary.createdEntities).toHaveLength(5);
    controller.destroy();
    secondaryController.destroy();
  });

  it("measures distance, coordinates, and available local elevation", () => {
    const { viewer } = fakeViewer();
    const events = createEarthEventBus();
    const received = vi.fn();
    events.subscribe(received);
    const controller = createCesiumWorkspaceController(viewer, events);
    const pointer = currentHandler();

    controller.startMeasurement("distance");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(0, 0));
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(1, 0));
    expect(received).toHaveBeenLastCalledWith(
      expect.objectContaining({ type: "earth.measurement.changed", measurement: expect.objectContaining({ kind: "distance", value: expect.any(Number) }) }),
    );

    controller.startMeasurement("coordinates");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(10, 20));
    expect(received).toHaveBeenLastCalledWith({
      type: "earth.measurement.changed",
      measurement: {
        kind: "coordinates",
        value: null,
        unit: "degrees",
        position: { lng: 10, lat: 20 },
      },
    });

    controller.startMeasurement("elevation");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(10, 20));
    expect(received).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: "earth.measurement.changed",
        measurement: expect.objectContaining({
          kind: "elevation",
          value: 321,
          unit: "m elevation",
        }),
      }),
    );

    controller.startMeasurement("area");
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(0, 0));
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(1, 0));
    pointer.trigger(ScreenSpaceEventType.LEFT_CLICK, click(1, 1));
    pointer.trigger(ScreenSpaceEventType.RIGHT_CLICK, click(1, 1));
    expect(received).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: "earth.measurement.changed",
        measurement: expect.objectContaining({ kind: "area", unit: "km2" }),
      }),
    );
    controller.destroy();
  });
});
