import {
  Color,
  ColorMaterialProperty,
  GeoJsonDataSource,
  type Entity,
  type Viewer,
} from "cesium";

import type {
  EarthCommand,
  EarthOverlay,
  EngineEarthObjectGeoJSON,
} from "@/shared/types";
import type { Unsubscribe } from "@/shared/utils";

import type { OverlayController } from "./types";

type AddOverlayCommand = Extract<EarthCommand, { type: "add_overlay" }>;
interface OverlayPalette {
  fill: Color;
  marker: Color;
  stroke: Color;
}

const INVESTIGATION_OVERLAY_PREFIX = "investigation:";
const DEFAULT_PALETTE: OverlayPalette = {
  fill: Color.CYAN.withAlpha(0.25),
  marker: Color.CYAN,
  stroke: Color.CYAN,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object";
}

function cssColor(value: string | undefined, fallback: Color): Color {
  if (!value) return fallback;
  return Color.fromCssColorString(value) ?? fallback;
}

function evidenceMatches(
  entity: Entity,
  evidenceIds: ReadonlySet<string>,
  currentTime: Viewer["clock"]["currentTime"],
): boolean {
  if (!entity.properties) return false;
  const properties: unknown = entity.properties.getValue(currentTime);
  if (!isRecord(properties) || !Array.isArray(properties.evidence_ids)) return false;
  return properties.evidence_ids.some(
    (id: unknown) => typeof id === "string" && evidenceIds.has(id),
  );
}

export function createCesiumOverlayController(viewer: Viewer): OverlayController {
  const sources = new Map<string, GeoJsonDataSource>();
  const palettes = new Map<string, OverlayPalette>();
  const overlayContexts = new Map<string, EarthOverlay>();
  const generations = new Map<string, number>();
  const changeListeners = new Set<(overlays: EarthOverlay[]) => void>();
  const highlightListeners = new Set<(evidenceIds: string[]) => void>();
  let highlightedEvidenceIds = new Set<string>();
  let destroyed = false;

  function publishOverlays(): void {
    const state = [...overlayContexts.values()];
    changeListeners.forEach((listener) => listener(state));
  }

  function subscribe<T>(
    listeners: Set<(value: T) => void>,
    listener: (value: T) => void,
  ): Unsubscribe {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function applyHighlights(source: GeoJsonDataSource, palette: OverlayPalette): void {
    for (const entity of source.entities.values) {
      const highlighted = evidenceMatches(
        entity,
        highlightedEvidenceIds,
        viewer.clock.currentTime,
      );
      const stroke = highlighted ? Color.YELLOW : palette.stroke;
      if (entity.polygon) {
        const fill = highlighted
          ? Color.YELLOW.withAlpha(palette.fill.alpha)
          : palette.fill;
        entity.polygon.material = new ColorMaterialProperty(fill);
        entity.polygon.outlineColor = new ColorMaterialProperty(stroke).color;
      }
      if (entity.polyline) {
        entity.polyline.material = new ColorMaterialProperty(stroke);
      }
      if (entity.point) {
        const marker = highlighted ? Color.YELLOW : palette.marker;
        entity.point.color = new ColorMaterialProperty(marker).color;
      }
    }
  }

  async function replaceSource(
    id: string,
    collection: object,
    options: GeoJsonDataSource.LoadOptions,
    palette: OverlayPalette,
    context: EarthOverlay,
    flyToSource = true,
  ): Promise<void> {
    const generation = (generations.get(id) ?? 0) + 1;
    generations.set(id, generation);
    const source = await GeoJsonDataSource.load(collection, options);
    if (destroyed || generations.get(id) !== generation) return;

    await viewer.dataSources.add(source);
    if (destroyed || generations.get(id) !== generation) {
      viewer.dataSources.remove(source, true);
      return;
    }

    if (flyToSource) {
      const flewToSource = await viewer.flyTo(source);
      if (!flewToSource || destroyed || generations.get(id) !== generation) {
        viewer.dataSources.remove(source, true);
        if (destroyed || generations.get(id) !== generation) return;
        throw new Error("The Earth workspace could not navigate to the Engine geometry.");
      }
    }

    const previous = sources.get(id);
    if (previous) viewer.dataSources.remove(previous, true);
    sources.set(id, source);
    palettes.set(id, palette);
    overlayContexts.set(id, context);
    applyHighlights(source, palette);
    publishOverlays();
    viewer.scene.requestRender();
  }

  function clear(overlayIds?: readonly string[]): void {
    const ids = overlayIds
      ? [...overlayIds]
      : [...new Set([...generations.keys(), ...sources.keys()])];
    let overlaysChanged = false;
    for (const id of ids) {
      generations.set(id, (generations.get(id) ?? 0) + 1);
      const source = sources.get(id);
      if (source) viewer.dataSources.remove(source, true);
      sources.delete(id);
      palettes.delete(id);
      overlaysChanged = overlayContexts.delete(id) || overlaysChanged;
    }
    if (overlaysChanged) publishOverlays();
    if (sources.size === 0 && highlightedEvidenceIds.size > 0) {
      highlightedEvidenceIds.clear();
      highlightListeners.forEach((listener) => listener([]));
    }
    viewer.scene.requestRender();
  }

  function add(command: AddOverlayCommand): Promise<void> {
    const style = command.style;
    const feature = {
      type: "Feature",
      id: command.overlay_id,
      geometry: command.geometry,
      properties: {
        name: command.label ?? command.overlay_id,
        evidence_ids: command.evidence_id ? [command.evidence_id] : [],
      },
    };
    const context: EarthOverlay = {
      id: command.overlay_id,
      label: command.label ?? command.overlay_id,
      investigation_id: null,
      features: [
        {
          id: command.overlay_id,
          geometry: command.geometry,
          properties: {
            name: command.label ?? command.overlay_id,
            evidence_ids: command.evidence_id ? [command.evidence_id] : [],
          },
        },
      ],
      omitted_objects: [],
      geometry_policy: null,
    };
    const opacity =
      typeof style.opacity === "number" && style.opacity >= 0 && style.opacity <= 1
        ? style.opacity
        : 0.25;
    const stroke = cssColor(
      typeof style.stroke === "string" ? style.stroke : undefined,
      Color.CYAN,
    );
    const fill = cssColor(
      typeof style.fill === "string" ? style.fill : undefined,
      Color.CYAN,
    ).withAlpha(opacity);
    return replaceSource(
      command.overlay_id,
      { type: "FeatureCollection", features: [feature] },
      {
        clampToGround: style.clampToGround === true,
        fill,
        markerColor: stroke,
        stroke,
        strokeWidth:
          typeof style.strokeWidth === "number" && style.strokeWidth > 0
            ? style.strokeWidth
            : 3,
      },
      { fill, marker: stroke, stroke },
      context,
    );
  }

  return {
    getState() {
      return [...overlayContexts.values()];
    },
    onChange(listener) {
      return subscribe(changeListeners, listener);
    },
    onHighlightChange(listener) {
      return subscribe(highlightListeners, listener);
    },
    async restore(overlays) {
      clear();
      try {
        for (const overlay of overlays) {
          const features = overlay.features.map((feature) => ({
            type: "Feature",
            id: feature.id,
            geometry: feature.geometry,
            properties: { ...feature.properties },
          }));
          await replaceSource(
            overlay.id,
            { type: "FeatureCollection", features },
            {
              clampToGround: true,
              fill: DEFAULT_PALETTE.fill,
              markerColor: DEFAULT_PALETTE.marker,
              stroke: DEFAULT_PALETTE.stroke,
              strokeWidth: 3,
            },
            DEFAULT_PALETTE,
            overlay,
            false,
          );
        }
      } catch (error) {
        clear();
        throw error;
      }
    },
    add,
    async showInvestigation(
      investigationId: string,
      collection: EngineEarthObjectGeoJSON,
    ) {
      const id = `${INVESTIGATION_OVERLAY_PREFIX}${investigationId}`;
      if (collection.features.length === 0) {
        clear([id]);
        return;
      }
      await replaceSource(
        id,
        collection,
        {
          clampToGround: true,
          fill: DEFAULT_PALETTE.fill,
          markerColor: DEFAULT_PALETTE.marker,
          stroke: DEFAULT_PALETTE.stroke,
          strokeWidth: 3,
        },
        DEFAULT_PALETTE,
        {
          id,
          label: investigationId,
          investigation_id: investigationId,
          features: collection.features.map((feature) => ({
            id: feature.id,
            geometry: feature.geometry,
            properties: { ...feature.properties },
          })),
          omitted_objects: collection["satquery:omitted_objects"],
          geometry_policy: collection["satquery:geometry_policy"],
        },
      );
    },
    highlight(evidenceIds) {
      highlightedEvidenceIds = new Set(evidenceIds);
      const state = [...highlightedEvidenceIds];
      highlightListeners.forEach((listener) => listener(state));
      for (const [id, source] of sources) {
        const palette = palettes.get(id);
        if (palette) applyHighlights(source, palette);
      }
      viewer.scene.requestRender();
    },
    clear,
    destroy() {
      destroyed = true;
      clear();
      changeListeners.clear();
      highlightListeners.clear();
    },
  };
}
