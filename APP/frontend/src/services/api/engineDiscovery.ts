import type { EngineDiscoveryResponse } from "@/shared/types";

import { apiFetch } from "./client";

export function getEngineDiscovery(
  signal?: AbortSignal,
): Promise<EngineDiscoveryResponse> {
  return apiFetch("/intelligence/engine-discovery", { signal });
}
