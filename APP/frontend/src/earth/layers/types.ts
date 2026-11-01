import type { Viewer } from "cesium";

import type { LayerSpec } from "@/shared/types";
import type { Unsubscribe } from "@/shared/utils";

/** A materialised layer on the globe. */
export interface RenderedLayer {
  setVisible(visible: boolean): void;
  setOpacity(opacity: number): void;
  setTime?(instant: Date): void;
  dispose(): void;
}

/**
 * Knows how to render one `LayerSpec.kind` (imagery, geojson, 3dtiles, ...). Core ships the
 * standard kinds; plugins register renderers for new kinds. `id` is the kind it handles.
 */
export interface LayerRenderer {
  id: string;
  create(viewer: Viewer, spec: LayerSpec): Promise<RenderedLayer>;
}

export interface LayerController {
  sync(specs: readonly LayerSpec[]): Promise<void>;
  setVisibility(layerId: string, visible: boolean, opacity?: number): void;
  onChange(listener: () => void): Unsubscribe;
}
