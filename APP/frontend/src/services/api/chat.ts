import type {
  AgentEvent,
  AgentTurnRequest,
  EngineEarthObjectGeoJSON,
  EngineAgentSession,
  EngineHypothesisCreateRequest,
  EngineHypothesisLifecycleResponse,
  EngineHypothesisMutationResponse,
  EngineHypothesisTransitionRequest,
  EngineInvestigationEventPage,
  EngineObservation,
  EngineInvestigationReport,
  EngineInvestigationReasoningResponse,
  EngineInvestigationReproducibilityBundle,
} from "@/shared/types";

import { apiFetch, apiFetchVoid, apiUrl, ApiError } from "./client";

type AgentTurnSubmission = Omit<AgentTurnRequest, "asset_ids"> & {
  asset_ids?: string[];
};

export async function getAgentSession(sessionId: string, signal?: AbortSignal) {
  return apiFetch<EngineAgentSession>(`/chat/sessions/${encodeURIComponent(sessionId)}`, {
    signal,
  });
}

export async function getInvestigationReport(
  sessionId: string,
  investigationId: string,
  signal?: AbortSignal,
) {
  return apiFetch<EngineInvestigationReport>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/report`,
    { signal },
  );
}

export async function getInvestigationReasoning(
  sessionId: string,
  investigationId: string,
  signal?: AbortSignal,
) {
  return apiFetch<EngineInvestigationReasoningResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/reasoning`,
    { signal },
  );
}

export async function getInvestigationReproducibility(
  sessionId: string,
  investigationId: string,
  signal?: AbortSignal,
) {
  return apiFetch<EngineInvestigationReproducibilityBundle>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/reproducibility`,
    { signal },
  );
}

export async function getInvestigationObservations(
  sessionId: string,
  investigationId: string,
  signal?: AbortSignal,
) {
  return apiFetch<EngineObservation[]>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/observations`,
    { signal },
  );
}

export async function getInvestigationEarthObjects(
  sessionId: string,
  investigationId: string,
  signal?: AbortSignal,
) {
  return apiFetch<EngineEarthObjectGeoJSON>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/earth-objects`,
    { signal },
  );
}

export async function getInvestigationEvents(
  sessionId: string,
  investigationId: string,
  afterSequence = 0,
  limit = 100,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    after_sequence: String(afterSequence),
    limit: String(limit),
  });
  return apiFetch<EngineInvestigationEventPage>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/events?${query}`,
    { signal },
  );
}

export async function getInvestigationHypotheses(
  sessionId: string,
  investigationId: string,
  signal?: AbortSignal,
) {
  return apiFetch<EngineHypothesisLifecycleResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/hypotheses`,
    { signal },
  );
}

export async function addInvestigationHypothesis(
  sessionId: string,
  investigationId: string,
  body: EngineHypothesisCreateRequest,
) {
  return apiFetch<EngineHypothesisMutationResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/hypotheses`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function transitionInvestigationHypothesis(
  sessionId: string,
  investigationId: string,
  hypothesisId: string,
  body: EngineHypothesisTransitionRequest,
) {
  return apiFetch<EngineHypothesisMutationResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/investigations/${encodeURIComponent(investigationId)}/hypotheses/${encodeURIComponent(hypothesisId)}/transitions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export async function cancelAgentTurn(sessionId: string): Promise<void> {
  await apiFetchVoid(`/chat/sessions/${encodeURIComponent(sessionId)}/cancel`, {
    method: "POST",
  });
}

export async function* streamAgentTurn(
  sessionId: string,
  request: AgentTurnSubmission,
  signal: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const response = await fetch(apiUrl(`/chat/sessions/${encodeURIComponent(sessionId)}/turns`), {
    method: "POST",
    headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> };
    } | null;
    throw new ApiError(
      response.status,
      body?.error?.code ?? "http_error",
      body?.error?.message ?? response.statusText,
      body?.error?.details,
    );
  }
  if (!response.body) throw new Error("The chat response did not include a stream.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      while (true) {
        const separator = /\r?\n\r?\n/.exec(buffer);
        if (!separator || separator.index === undefined) break;
        const frame = buffer.slice(0, separator.index);
        buffer = buffer.slice(separator.index + separator[0].length);
        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).replace(/^ /, ""))
          .join("\n");
        if (data) yield JSON.parse(data) as AgentEvent;
      }
      if (done) break;
    }
    if (buffer.trim()) {
      const data = buffer
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data) yield JSON.parse(data) as AgentEvent;
    }
  } finally {
    reader.releaseLock();
  }
}
