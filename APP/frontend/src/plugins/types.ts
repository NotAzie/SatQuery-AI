import type { ComponentType } from "react";

import type { LayerRenderer } from "@/earth/layers/types";
import type { PanelContribution } from "@/shared/types";
import type { Unsubscribe } from "@/shared/utils";

export type PanelSlot = PanelContribution["slot"];

export interface PanelRegistration {
  id: string;
  title: string;
  slot: PanelSlot;
  order: number;
  component: ComponentType;
}

/** What a plugin may do on the frontend. The mirror of the backend's `PluginContext`. */
export interface FrontendPluginContext {
  pluginId: string;
  registerPanel(panel: Omit<PanelRegistration, "order"> & { order?: number }): Unsubscribe;
  registerLayerRenderer(renderer: LayerRenderer): Unsubscribe;
}

/**
 * Default export of a plugin's `frontend_entry` ES module (see backend `PluginManifest`).
 * Loaded at runtime from URLs the backend advertises, so plugins ship without rebuilding the app.
 */
export interface FrontendPlugin {
  register(ctx: FrontendPluginContext): void | Promise<void>;
}
