import { createContext, useCallback, useMemo, useState, type ReactNode } from "react";

import type { EarthController } from "./controller";
import { createEarthEventBus, type EarthEventBus } from "./events";

export interface EarthRegistry {
  controller: EarthController | null;
  secondaryController: EarthController | null;
  events: EarthEventBus;
  attach: (controller: EarthController) => void;
  attachSecondary: (controller: EarthController) => void;
  detach: () => void;
  detachSecondary: () => void;
}

export const EarthRegistryContext = createContext<EarthRegistry | null>(null);

/** Holds the live controller so any component can reach the globe without prop drilling. */
export function EarthProvider({ children }: { children: ReactNode }) {
  const [controller, setController] = useState<EarthController | null>(null);
  const [secondaryController, setSecondaryController] = useState<EarthController | null>(null);
  const [events] = useState(createEarthEventBus);
  const attach = useCallback((next: EarthController) => setController(next), []);
  const attachSecondary = useCallback(
    (next: EarthController) => setSecondaryController(next),
    [],
  );
  const detach = useCallback(() => setController(null), []);
  const detachSecondary = useCallback(() => setSecondaryController(null), []);
  const value = useMemo(
    () => ({
      controller,
      secondaryController,
      events,
      attach,
      attachSecondary,
      detach,
      detachSecondary,
    }),
    [controller, secondaryController, events, attach, attachSecondary, detach, detachSecondary],
  );
  return <EarthRegistryContext.Provider value={value}>{children}</EarthRegistryContext.Provider>;
}
