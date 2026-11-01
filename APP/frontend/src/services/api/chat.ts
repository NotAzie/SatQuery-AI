import type { AgentEvent, AgentTurnRequest, EngineAgentSession } from "@/shared/types";

import { apiFetch, apiUrl, ApiError } from "./client";

export async function getAgentSession(sessionId: string, signal?: AbortSignal) {
  return apiFetch<EngineAgentSession>(`/chat/sessions/${encodeURIComponent(sessionId)}`, {
    signal,
  });
}

export async function* streamAgentTurn(
  sessionId: string,
  request: AgentTurnRequest,
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
