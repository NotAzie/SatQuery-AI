import type { EarthWorkspaceState, Session } from "@/shared/types";

import { apiFetch } from "./client";

export function listSessions(signal?: AbortSignal): Promise<Session[]> {
  return apiFetch<Session[]>("/sessions", { signal });
}

export function createSession(title?: string): Promise<Session> {
  return apiFetch<Session>("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function getSession(sessionId: string, signal?: AbortSignal): Promise<Session> {
  return apiFetch<Session>(`/sessions/${encodeURIComponent(sessionId)}`, { signal });
}

export function updateSessionEarthWorkspace(
  sessionId: string,
  earthWorkspace: EarthWorkspaceState,
  signal?: AbortSignal,
): Promise<Session> {
  return apiFetch<Session>(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ earth_workspace: earthWorkspace }),
  });
}
