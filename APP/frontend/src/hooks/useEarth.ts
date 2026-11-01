import { useContext } from "react";

import { EarthRegistryContext, type EarthRegistry } from "@/earth/EarthProvider";

export function useEarthRegistry(): EarthRegistry {
  const registry = useContext(EarthRegistryContext);
  if (!registry) throw new Error("useEarthRegistry must be used inside <EarthProvider>");
  return registry;
}

/** The live globe controller, or null until the globe has mounted. */
export function useEarthController() {
  return useEarthRegistry().controller;
}
