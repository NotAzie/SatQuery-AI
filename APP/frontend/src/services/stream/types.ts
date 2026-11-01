import type { AgentEvent, ClientMessage, ControlMessage } from "@/shared/types";

export type StreamItem = AgentEvent | ControlMessage;

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed";

/**
 * Transport-neutral view of a session's live stream. One implementation per transport:
 *  - SSE: server -> client only (chat streaming); control actions go over HTTP POST.
 *  - WebSocket: bidirectional (cancel, camera/Earth context updates).
 * Both resume from `afterSeq`, so a dropped connection loses nothing.
 */
export interface StreamClient {
  connect(sessionId: string, options?: { afterSeq?: number }): void;
  close(): void;
  readonly state: ConnectionState;
  onItem(listener: (item: StreamItem) => void): () => void;
  onState(listener: (state: ConnectionState) => void): () => void;
  /** Rejects on transports that cannot send (SSE). */
  send(message: ClientMessage): Promise<void>;
}
