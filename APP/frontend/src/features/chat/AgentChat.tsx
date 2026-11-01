import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { ApiError } from "@/services/api/client";
import { getAgentSession, streamAgentTurn } from "@/services/api/chat";
import { prepareVisionAssets } from "@/services/api/vision";
import { snapshotEarthContext, useEarthStore } from "@/state/earthStore";
import { useSessionStore } from "@/state/sessionStore";
import { useVisionStore } from "@/state/visionStore";
import { useEarthController } from "@/hooks/useEarth";
import { visibleAgentMessage } from "./messageContent";

interface ChatMessage {
  id: string;
  role: string;
  content: string;
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "The Engine Agent stream failed.";
}

export function AgentChat() {
  const sessionId = useSessionStore((state) => state.activeSessionId);
  const earth = useEarthController();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesSessionId, setMessagesSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [executionAuthorized, setExecutionAuthorized] = useState(false);
  const attachments = useVisionStore((state) =>
    state.selectedAssets.filter((asset) => asset.session_id === sessionId),
  );
  const setVisionPanelOpen = useVisionStore((state) => state.setPanelOpen);
  const [notice, setNotice] = useState<{
    sessionId: string | null;
    status: string | null;
    error: string | null;
  }>({ sessionId: null, status: null, error: null });
  const visibleMessages = useMemo(
    () => (messagesSessionId === sessionId ? messages : []),
    [messages, messagesSessionId, sessionId],
  );
  const status = notice.sessionId === sessionId ? notice.status : null;
  const error = notice.sessionId === sessionId ? notice.error : null;
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeTurn = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    void getAgentSession(sessionId, controller.signal)
      .then((session) => {
        setMessagesSessionId(sessionId);
        setMessages(
          session.messages
            .filter((message) => message.role === "user" || message.role === "assistant")
            .map((message, index) => ({
              id: `${message.turn_id ?? session.session_id}-${index}`,
              role: message.role,
              content: visibleAgentMessage(message.role, message.content),
            })),
        );
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setNotice({ sessionId, status: null, error: errorText(reason) });
        }
      });
    return () => {
      controller.abort();
      activeTurn.current?.abort();
    };
  }, [sessionId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [visibleMessages]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionId || busy || (!draft.trim() && attachments.length === 0)) return;
    if (attachments.length > 0) {
      const [firstAttachment, ...remainingAttachments] = attachments;
      if (!firstAttachment) return;
      setBusy(true);
      setNotice({ sessionId, status: "Preparing image context...", error: null });
      try {
        await prepareVisionAssets(sessionId, {
          asset_ids: [firstAttachment.id, ...remainingAttachments.map((asset) => asset.id)],
          context: {
            assets: [],
            earth_captures: useEarthStore
              .getState()
              .captures.filter((capture) =>
                attachments.some((asset) => asset.id === capture.asset_id),
              ),
            georeference: null,
            metadata: {},
          },
        });
        setNotice({
          sessionId,
          status: null,
          error:
            "Image context is prepared, but SatQuery Engine's Agent API currently accepts text only. Nothing was sent; remove the images to send a text-only turn.",
        });
      } catch (reason) {
        setNotice({ sessionId, status: null, error: errorText(reason) });
      } finally {
        setBusy(false);
      }
      return;
    }
    if (!draft.trim()) return;
    const text = draft.trim();
    const controller = new AbortController();
    activeTurn.current = controller;
    setDraft("");
    setBusy(true);
    setNotice({ sessionId, status: "Connecting to SatQuery Engine...", error: null });
    setMessagesSessionId(sessionId);
    setMessages((current) => [
      ...(messagesSessionId === sessionId ? current : []),
      { id: crypto.randomUUID(), role: "user", content: text },
    ]);
    let completed = false;
    try {
      for await (const event of streamAgentTurn(
        sessionId,
        {
          message: text,
          execution_authorized: executionAuthorized,
          earth_context: snapshotEarthContext(),
          asset_ids: [],
          vision_context: {
            assets: [],
            earth_captures: [],
            georeference: null,
            metadata: {},
          },
        },
        controller.signal,
      )) {
        if (event.type === "engine.event") {
          switch (event.engine_kind) {
            case "turn.started":
              setNotice({ sessionId, status: "SatQuery Agent is reasoning...", error: null });
              break;
            case "assistant.delta":
              setMessages((current) => {
                const index = current.findIndex(
                  (message) => message.id === event.engine_turn_id && message.role === "assistant",
                );
                if (index < 0) {
                  return [
                    ...current,
                    {
                      id: event.engine_turn_id,
                      role: "assistant",
                      content: String(event.payload.text ?? ""),
                    },
                  ];
                }
                return current.map((message, messageIndex) =>
                  messageIndex === index
                    ? { ...message, content: message.content + String(event.payload.text ?? "") }
                    : message,
                );
              });
              setNotice({ sessionId, status: null, error: null });
              break;
            case "tool.started":
              setNotice({
                sessionId,
                status: `Running ${String(event.payload.tool_id ?? "Engine tool")}...`,
                error: null,
              });
              break;
            case "tool.completed":
              setNotice({ sessionId, status: "Engine tool completed.", error: null });
              break;
            case "tool.failed":
              setNotice({
                sessionId,
                status: `Engine tool failed: ${String(
                  event.payload.detail ?? event.payload.code ?? "see Engine event",
                )}`,
                error: null,
              });
              break;
            case "investigation.progress":
              setNotice({
                sessionId,
                status:
                  typeof event.payload.message === "string"
                    ? event.payload.message
                    : "Investigation in progress...",
                error: null,
              });
              break;
            case "turn.completed":
              completed = true;
              setNotice({ sessionId, status: null, error: null });
              break;
            case "turn.cancelled":
              completed = true;
              setNotice({ sessionId, status: "Turn cancelled.", error: null });
              break;
            case "agent.error":
              completed = true;
              setNotice({
                sessionId,
                status: null,
                error: String(event.payload.detail ?? event.payload.code ?? "Engine Agent error"),
              });
              break;
          }
        } else if (event.type === "run.failed") {
          completed = true;
          setNotice({ sessionId, status: null, error: event.message });
        } else if (event.type === "earth.command") {
          if (!earth) {
            setNotice({
              sessionId,
              status: null,
              error: "The Earth workspace is not ready to apply this command.",
            });
            continue;
          }
          try {
            await earth.commands.dispatch(event);
          } catch (reason) {
            setNotice({
              sessionId,
              status: null,
              error:
                reason instanceof Error
                  ? reason.message
                  : "The Earth workspace could not apply the Engine command.",
            });
          }
        }
      }
      if (!completed && !controller.signal.aborted) {
        setNotice({
          sessionId,
          status: null,
          error: "The Engine Agent stream ended before a final event arrived.",
        });
      }
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setNotice({ sessionId, status: null, error: errorText(reason) });
      }
    } finally {
      if (activeTurn.current === controller) activeTurn.current = null;
      if (controller.signal.aborted) setNotice({ sessionId, status: "Turn stopped.", error: null });
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="Conversation"
      className="pointer-events-auto absolute bottom-4 left-1/2 mx-auto flex h-[min(68vh,44rem)] w-[min(46rem,calc(100vw-2rem))] -translate-x-1/2 flex-col overflow-hidden rounded-3xl border border-white/10 bg-surface/90 shadow-2xl shadow-black/50 backdrop-blur-2xl"
    >
      <header className="flex items-center justify-between border-b border-white/10 px-5 py-3">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-ink-dim">
            SatQuery Agent
          </p>
          <p className="mt-1 text-xs text-ink-dim">
            The Engine owns analysis, tool execution, and evidence.
          </p>
        </div>
        {busy && (
          <button
            type="button"
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink"
            onClick={() => activeTurn.current?.abort()}
          >
            Stop
          </button>
        )}
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {!sessionId && (
          <p className="py-6 text-center text-sm text-ink-dim">
            Create or select a workspace session to start a conversation.
          </p>
        )}
        {sessionId && visibleMessages.length === 0 && (
          <p className="py-6 text-center text-sm text-ink-dim">
            Ask a question about the Earth. SatQuery Engine will provide scientific analysis.
          </p>
        )}
        {visibleMessages.map((message) => (
          <article
            key={message.id}
            className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-6 ${
              message.role === "user"
                ? "ml-auto bg-accent/20 text-ink"
                : "mr-auto bg-white/5 text-ink"
            }`}
          >
            {message.content}
          </article>
        ))}
        {status && (
          <p className="text-xs text-ink-dim" role="status">
            {status}
          </p>
        )}
        {error && (
          <p className="text-xs text-rose-200" role="alert">
            {error}
          </p>
        )}
      </div>

      <form className="border-t border-white/10 p-3" onSubmit={(event) => void submit(event)}>
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          disabled={!sessionId || busy}
          placeholder={sessionId ? "Message SatQuery Agent..." : "Select a session first"}
          aria-label="Message SatQuery Agent"
          rows={2}
          className="w-full resize-none bg-transparent px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-dim disabled:opacity-50"
        />
        <div className="flex items-center justify-between gap-3 px-2 pb-1">
          <button
            type="button"
            className="rounded-full border border-white/10 px-3 py-2 text-xs text-ink-dim hover:text-ink"
            onClick={() => setVisionPanelOpen(true)}
            disabled={!sessionId}
          >
            Images{attachments.length ? ` (${attachments.length})` : ""}
          </button>
          <label className="flex items-center gap-2 text-[10px] text-ink-dim">
            <input
              type="checkbox"
              checked={executionAuthorized}
              onChange={(event) => setExecutionAuthorized(event.target.checked)}
              disabled={busy}
            />
            Allow investigation execution
          </label>
          <button
            type="submit"
            disabled={!sessionId || (!draft.trim() && attachments.length === 0) || busy}
            className="rounded-full bg-accent px-4 py-2 text-xs font-medium text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {attachments.length ? "Prepare images" : "Send"}
          </button>
        </div>
      </form>
    </section>
  );
}
