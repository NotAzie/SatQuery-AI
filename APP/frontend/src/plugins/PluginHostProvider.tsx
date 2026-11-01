import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { LayerRenderer } from "@/earth/layers/types";
import { Registry } from "@/shared/registry";

import type { PanelRegistration } from "./types";

export interface PluginHost {
  panels: Registry<PanelRegistration>;
  layerRenderers: Registry<LayerRenderer>;
}

const PluginHostContext = createContext<PluginHost | null>(null);

export function PluginHostProvider({ children }: { children: ReactNode }) {
  const host = useMemo<PluginHost>(
    () => ({
      panels: new Registry<PanelRegistration>("panel"),
      layerRenderers: new Registry<LayerRenderer>("layer renderer"),
    }),
    [],
  );
  return <PluginHostContext.Provider value={host}>{children}</PluginHostContext.Provider>;
}

export function usePluginHost(): PluginHost {
  const host = useContext(PluginHostContext);
  if (!host) throw new Error("usePluginHost must be used inside <PluginHostProvider>");
  return host;
}
