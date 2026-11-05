import type { Viewer } from "cesium";

import type { LayerState } from "@/shared/types";
import type { Unsubscribe } from "@/shared/utils";

interface GodsEyeLayerSummary {
  id: string;
  name: string;
  enabled: boolean;
}

interface GodsEyeDataManager {
  getAll(): GodsEyeLayerSummary[];
  setEnabled(
    layerId: string,
    enabled: boolean,
    options?: { origin?: string; signal?: AbortSignal | null },
  ): Promise<unknown>;
  subscribe(listener: (change: unknown) => void): Unsubscribe;
}

export interface GodsEyeRuntime {
  viewer: Viewer;
  dataManager: GodsEyeDataManager;
  openProviderSettings?: () => Promise<boolean>;
}

export interface EarthDataLayerController {
  getState(): LayerState[];
  setVisibility(layerId: string, visible: boolean, opacity?: number): Promise<void>;
  restore(layers: readonly LayerState[]): Promise<void>;
  onChange(listener: () => void): Unsubscribe;
}

declare global {
  interface Window {
    __godsEyeView?: GodsEyeRuntime;
  }
}

export function isGodsEyeRuntime(value: unknown): value is GodsEyeRuntime {
  if (typeof value !== "object" || value === null) return false;
  const runtime = value as Partial<GodsEyeRuntime>;
  const viewer = runtime.viewer as Viewer | undefined;
  const dataManager = runtime.dataManager;
  return (
    typeof viewer === "object" &&
    viewer !== null &&
    typeof viewer.scene === "object" &&
    typeof viewer.camera === "object" &&
    typeof dataManager?.getAll === "function" &&
    typeof dataManager.setEnabled === "function" &&
    typeof dataManager.subscribe === "function"
  );
}

export async function openGodsEyeProviderSettings(): Promise<boolean> {
  const openSettings = window.__godsEyeView?.openProviderSettings;
  if (!openSettings) return false;
  return openSettings();
}

export function createGodsEyeLayerController(
  dataManager: GodsEyeDataManager,
): EarthDataLayerController {
  const getRegisteredLayers = () => new Map(dataManager.getAll().map((layer) => [layer.id, layer]));

  const setVisibility = async (
    layerId: string,
    visible: boolean,
    opacity = 1,
  ): Promise<void> => {
    if (!getRegisteredLayers().has(layerId)) {
      throw new RangeError(`Earth data layer '${layerId}' is not registered`);
    }
    if (opacity !== 1) {
      throw new RangeError(`Earth data layer '${layerId}' does not support opacity`);
    }
    await dataManager.setEnabled(layerId, visible, { origin: "tool" });
  };

  return {
    getState() {
      return dataManager.getAll().map((layer) => ({
        layer_id: layer.id,
        opacity: 1,
        visible: layer.enabled,
      }));
    },
    setVisibility,
    async restore(layers) {
      const saved = new Map(layers.map((layer) => [layer.layer_id, layer]));
      if (saved.size !== layers.length) {
        throw new RangeError("Saved Earth context contains duplicate data layers");
      }
      const registered = getRegisteredLayers();
      for (const layer of saved.values()) {
        if (!registered.has(layer.layer_id)) {
          throw new RangeError(`Saved Earth data layer '${layer.layer_id}' is not available`);
        }
        if (layer.opacity !== 1) {
          throw new RangeError(`Saved Earth data layer '${layer.layer_id}' uses unsupported opacity`);
        }
      }
      for (const layer of registered.values()) {
        await setVisibility(layer.id, saved.get(layer.id)?.visible ?? false);
      }
    },
    onChange(listener) {
      return dataManager.subscribe(() => listener());
    },
  };
}
