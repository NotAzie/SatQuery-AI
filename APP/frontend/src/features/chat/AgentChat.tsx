import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useShallow } from "zustand/react/shallow";

import { ApiError } from "@/services/api/client";
import {
  cancelAgentTurn,
  getAgentSession,
  getInvestigationEarthObjects,
  getInvestigationEvents,
  getInvestigationReport,
  streamAgentTurn,
} from "@/services/api/chat";
import { openGodsEyeProviderSettings } from "@/earth/integration/godsEyeRuntime";
import { VisionAttachments } from "@/features/vision/VisionAttachments";
import { useWorkspaceDrawer } from "@/features/workspace/SatQueryWorkspaceDrawer";
import { useEarthController } from "@/hooks/useEarth";
import { imageContentUrl } from "@/services/api/vision";
import type { EngineInvestigationReport } from "@/shared/types";
import { snapshotEarthContext } from "@/state/earthStore";
import { useSessionStore } from "@/state/sessionStore";
import { useVisionStore } from "@/state/visionStore";
import { visibleAgentMessage } from "./messageContent";
import {
  formatInvestigationEventType,
  investigationActivityFromEvent,
  investigationActivityFromJournalEvent,
  type InvestigationActivityItem,
} from "./investigationActivity";

const MAX_INVESTIGATION_ACTIVITY_ITEMS = 100;

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  imageAssetIds?: string[];
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "The request failed unexpectedly.";
}

export function AgentChat() {
  const sessionId = useSessionStore((state) => state.activeSessionId);
  const earth = useEarthController();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesSessionId, setMessagesSessionId] = useState<string | null>(null);
  const [investigationActivity, setInvestigationActivity] = useState<
    InvestigationActivityItem[]
  >([]);
  const [activitySessionId, setActivitySessionId] = useState<string | null>(null);
  const [investigationRefs, setInvestigationRefs] = useState<{
    sessionId: string;
    ids: string[];
  } | null>(null);
  const [investigationHistory, setInvestigationHistory] = useState<{
    sessionId: string;
    investigationId: string;
    items: InvestigationActivityItem[];
    nextSequence: number;
    hasMore: boolean;
  } | null>(null);
  const [historyLoadingId, setHistoryLoadingId] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<{
    sessionId: string;
    investigationId: string;
    message: string;
  } | null>(null);
  const [selectedReport, setSelectedReport] = useState<{
    sessionId: string;
    investigationId: string;
    report: EngineInvestigationReport;
  } | null>(null);
  const [reportLoading, setReportLoading] = useState<{
    sessionId: string;
    investigationId: string;
  } | null>(null);
  const [reportError, setReportError] = useState<{
    sessionId: string;
    message: string;
  } | null>(null);
  const [overlayLoading, setOverlayLoading] = useState<{
    sessionId: string;
    investigationId: string;
  } | null>(null);
  const [overlayNotice, setOverlayNotice] = useState<{
    sessionId: string;
    message: string;
    error: boolean;
  } | null>(null);
  const [overlayCount, setOverlayCount] = useState<{
    sessionId: string;
    count: number;
  } | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [executionAuthorized, setExecutionAuthorized] = useState(false);
  const attachments = useVisionStore(
    useShallow((state) =>
      state.selectedAssets.filter((asset) => asset.session_id === sessionId),
    ),
  );
  const setVisionPanelOpen = useVisionStore((state) => state.setPanelOpen);
  const { openWorkspace } = useWorkspaceDrawer();
  const [notice, setNotice] = useState<{
    sessionId: string | null;
    status: string | null;
    error: string | null;
  }>({ sessionId: null, status: null, error: null });
  const visibleMessages = useMemo(
    () => (messagesSessionId === sessionId ? messages : []),
    [messages, messagesSessionId, sessionId],
  );
  const visibleActivity = activitySessionId === sessionId ? investigationActivity : [];
  const visibleInvestigationIds =
    investigationRefs?.sessionId === sessionId ? investigationRefs.ids : [];
  const visibleInvestigationHistory =
    investigationHistory?.sessionId === sessionId ? investigationHistory : null;
  const visibleHistoryError =
    historyError?.sessionId === sessionId ? historyError : null;
  const visibleReport = selectedReport?.sessionId === sessionId ? selectedReport : null;
  const visibleReportLoadingId =
    reportLoading?.sessionId === sessionId ? reportLoading.investigationId : null;
  const visibleOverlayLoadingId =
    overlayLoading?.sessionId === sessionId ? overlayLoading.investigationId : null;
  const visibleOverlayCount = overlayCount?.sessionId === sessionId ? overlayCount.count : 0;
  const status = notice.sessionId === sessionId ? notice.status : null;
  const error = notice.sessionId === sessionId ? notice.error : null;
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeTurn = useRef<AbortController | null>(null);
  const reportRequestId = useRef(0);
  const overlayRequestId = useRef(0);
  const historyRequestId = useRef(0);
  const loadedInvestigationOverlays = useRef(new Set<string>());
  const cancellationError = useRef<string | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    const loadedOverlaysForSession = loadedInvestigationOverlays.current;
    reportRequestId.current += 1;
    overlayRequestId.current += 1;
    historyRequestId.current += 1;
    const controller = new AbortController();
    void getAgentSession(sessionId, controller.signal)
      .then((session) => {
        if (controller.signal.aborted) return;
        setReportLoading(null);
        setOverlayLoading(null);
        setActivitySessionId(sessionId);
        setInvestigationActivity([]);
        setInvestigationRefs({ sessionId, ids: session.investigation_ids });
        setInvestigationHistory(null);
        setHistoryLoadingId(null);
        setHistoryError(null);
        setSelectedReport(null);
        setReportError(null);
        setOverlayNotice(null);
        setOverlayCount({ sessionId, count: 0 });
        setMessagesSessionId(sessionId);
        setMessages(
          session.messages
            .filter((message) => message.role === "user" || message.role === "assistant")
            .map((message, index) => ({
              id: `${message.turn_id ?? session.session_id}-${index}`,
              role: message.role,
              content: visibleAgentMessage(message.role, message.content),
              imageAssetIds: message.attachments.map((item) => item.asset_id),
            })),
        );
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setNotice({ sessionId, status: null, error: errorText(reason) });
        }
      });
    return () => {
      reportRequestId.current += 1;
      overlayRequestId.current += 1;
      historyRequestId.current += 1;
      controller.abort();
      activeTurn.current?.abort();
      earth?.overlays.clear(
        [...loadedOverlaysForSession].map(
          (investigationId) => `investigation:${investigationId}`,
        ),
      );
      loadedOverlaysForSession.clear();
    };
  }, [sessionId, earth]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [visibleMessages]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sessionId || busy || (!draft.trim() && attachments.length === 0)) return;
    setExpanded(true);
    const text = draft.trim() || "Describe the attached image(s).";
    const assetIds = attachments.map((asset) => asset.id);
    const visibleText = attachments.length
      ? `${text}\n\nImages: ${attachments.map((asset) => asset.filename ?? "image").join(", ")}`
      : text;
    const controller = new AbortController();
    activeTurn.current = controller;
    cancellationError.current = null;
    setDraft("");
    setBusy(true);
    setActivitySessionId(sessionId);
    setNotice({ sessionId, status: "Connecting to SatQuery Engine...", error: null });
    setMessagesSessionId(sessionId);
    setMessages((current) => [
      ...(messagesSessionId === sessionId ? current : []),
      {
        id: crypto.randomUUID(),
        role: "user",
        content: visibleText,
        imageAssetIds: assetIds,
      },
    ]);
    let completed = false;
    try {
      for await (const event of streamAgentTurn(
        sessionId,
        {
          message: text,
          execution_authorized: executionAuthorized,
          earth_context: snapshotEarthContext(),
          asset_ids: assetIds,
        },
        controller.signal,
      )) {
        if (event.type === "engine.event") {
          const activity = investigationActivityFromEvent(event);
          if (activity && useSessionStore.getState().activeSessionId === sessionId) {
            setInvestigationActivity((current) =>
              [...current, activity].slice(-MAX_INVESTIGATION_ACTIVITY_ITEMS),
            );
          }
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
            if (event.command.type === "show_investigation") {
              await showInvestigationOnEarth(
                event.command.investigation_id,
                event.command.evidence_ids,
              );
            } else {
              await earth.commands.dispatch(event);
            }
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
      if (completed && !controller.signal.aborted) {
        const transcript = await getAgentSession(sessionId, controller.signal);
        if (useSessionStore.getState().activeSessionId === sessionId) {
          setInvestigationRefs({ sessionId, ids: transcript.investigation_ids });
        }
      }
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setNotice({ sessionId, status: null, error: errorText(reason) });
      }
    } finally {
      if (activeTurn.current === controller) activeTurn.current = null;
      if (controller.signal.aborted) {
        const cancelError = cancellationError.current;
        cancellationError.current = null;
        setNotice(
          cancelError
            ? { sessionId, status: null, error: cancelError }
            : { sessionId, status: "Turn stopped.", error: null },
        );
      }
      setBusy(false);
    }
  }

  async function openProviderSettings() {
    try {
      const opened = await openGodsEyeProviderSettings();
      if (!opened) {
        setNotice({
          sessionId,
          status: null,
          error:
            "Provider settings are unavailable in this environment. Configure credentials through the deployment environment or Colab Secrets.",
        });
      }
    } catch (reason) {
      setNotice({
        sessionId,
        status: null,
        error:
          reason instanceof Error
            ? `Provider settings could not be opened: ${reason.message}`
            : "Provider settings could not be opened.",
      });
    }
  }

  async function stopTurn() {
    if (!sessionId || !activeTurn.current || canceling) return;
    const controller = activeTurn.current;
    setCanceling(true);
    setNotice({ sessionId, status: "Requesting Engine cancellation...", error: null });
    try {
      await cancelAgentTurn(sessionId);
    } catch (reason) {
      cancellationError.current =
        reason instanceof ApiError
          ? `Engine cancellation failed: ${reason.message}`
          : "Engine cancellation failed.";
    } finally {
      if (activeTurn.current === controller) {
        controller.abort();
      } else if (cancellationError.current) {
        setNotice({ sessionId, status: null, error: cancellationError.current });
        cancellationError.current = null;
      }
      setCanceling(false);
    }
  }

  async function showInvestigationReport(investigationId: string) {
    if (!sessionId) return;
    const requestId = ++reportRequestId.current;
    setReportLoading({ sessionId, investigationId });
    setReportError(null);
    try {
      const report = await getInvestigationReport(sessionId, investigationId);
      if (
        reportRequestId.current === requestId &&
        useSessionStore.getState().activeSessionId === sessionId
      ) {
        setSelectedReport({ sessionId, investigationId, report });
      }
    } catch (reason) {
      if (
        reportRequestId.current === requestId &&
        useSessionStore.getState().activeSessionId === sessionId
      ) {
        setReportError({
          sessionId,
          message:
            reason instanceof ApiError
              ? reason.message
              : "The investigation report could not be loaded.",
        });
      }
    } finally {
      if (reportRequestId.current === requestId) setReportLoading(null);
    }
  }

  async function loadInvestigationHistory(
    investigationId: string,
    append = false,
  ) {
    if (!sessionId) return;
    const requestId = ++historyRequestId.current;
    const previous =
      append &&
      investigationHistory?.sessionId === sessionId &&
      investigationHistory.investigationId === investigationId
        ? investigationHistory
        : null;
    setInvestigationHistory(
      previous ?? {
        sessionId,
        investigationId,
        items: [],
        nextSequence: 0,
        hasMore: false,
      },
    );
    setHistoryLoadingId(investigationId);
    setHistoryError(null);
    try {
      const page = await getInvestigationEvents(
        sessionId,
        investigationId,
        previous?.nextSequence ?? 0,
      );
      if (
        historyRequestId.current !== requestId ||
        useSessionStore.getState().activeSessionId !== sessionId
      ) {
        return;
      }
      const loaded = page.events.map(investigationActivityFromJournalEvent);
      setInvestigationHistory((current) => {
        const currentItems =
          current?.sessionId === sessionId &&
          current.investigationId === investigationId
            ? current.items
            : [];
        const existingIds = new Set(currentItems.map((item) => item.id));
        return {
          sessionId,
          investigationId,
          items: [...currentItems, ...loaded.filter((item) => !existingIds.has(item.id))],
          nextSequence: page.next_sequence,
          hasMore: page.has_more,
        };
      });
    } catch (reason) {
      if (
        historyRequestId.current === requestId &&
        useSessionStore.getState().activeSessionId === sessionId
      ) {
        setHistoryError({
          sessionId,
          investigationId,
          message:
            reason instanceof ApiError
              ? reason.message
              : "Investigation history could not be loaded.",
        });
      }
    } finally {
      if (historyRequestId.current === requestId) setHistoryLoadingId(null);
    }
  }

  async function showInvestigationOnEarth(
    investigationId: string,
    evidenceIds: readonly string[] = [],
  ) {
    if (!sessionId) return;
    if (!earth) {
      setOverlayNotice({
        sessionId,
        message: "The Earth workspace is not ready to display investigation geometry.",
        error: true,
      });
      return;
    }

    const requestId = ++overlayRequestId.current;
    setOverlayLoading({ sessionId, investigationId });
    setOverlayNotice(null);
    try {
      const collection = await getInvestigationEarthObjects(sessionId, investigationId);
      if (
        overlayRequestId.current !== requestId ||
        useSessionStore.getState().activeSessionId !== sessionId
      ) {
        return;
      }

      const overlayId = `investigation:${investigationId}`;
      loadedInvestigationOverlays.current.add(investigationId);
      await earth.overlays.showInvestigation(investigationId, collection);
      if (evidenceIds.length > 0) earth.overlays.highlight(evidenceIds);
      if (
        overlayRequestId.current !== requestId ||
        useSessionStore.getState().activeSessionId !== sessionId
      ) {
        earth.overlays.clear([overlayId]);
        loadedInvestigationOverlays.current.delete(investigationId);
        return;
      }

      const rendered = collection.features.length;
      const omitted = collection["satquery:omitted_objects"].length;
      if (rendered === 0) loadedInvestigationOverlays.current.delete(investigationId);
      setOverlayCount({
        sessionId,
        count: loadedInvestigationOverlays.current.size,
      });
      setOverlayNotice({
        sessionId,
        message:
          rendered === 0
            ? `No WGS 84 Earth Object geometry is available. The Engine omitted ${omitted} object(s) under its declared geometry policy.`
            : `Displayed ${rendered} Engine Earth Object(s). The Engine omitted ${omitted} object(s) under its declared geometry policy.`,
        error: false,
      });
    } catch (reason) {
      earth.overlays.clear([`investigation:${investigationId}`]);
      loadedInvestigationOverlays.current.delete(investigationId);
      if (useSessionStore.getState().activeSessionId === sessionId) {
        setOverlayCount({
          sessionId,
          count: loadedInvestigationOverlays.current.size,
        });
      }
      if (
        overlayRequestId.current === requestId &&
        useSessionStore.getState().activeSessionId === sessionId
      ) {
        setOverlayNotice({
          sessionId,
          message:
            reason instanceof ApiError
              ? reason.message
              : "The Engine Earth Object geometry could not be displayed.",
          error: true,
        });
      }
    } finally {
      if (overlayRequestId.current === requestId) setOverlayLoading(null);
    }
  }

  function clearInvestigationOverlays() {
    if (!sessionId || !earth) return;
    const investigationIds = new Set(loadedInvestigationOverlays.current);
    if (overlayLoading?.sessionId === sessionId) {
      investigationIds.add(overlayLoading.investigationId);
    }
    overlayRequestId.current += 1;
    earth.overlays.clear(
      [...investigationIds].map((investigationId) => `investigation:${investigationId}`),
    );
    loadedInvestigationOverlays.current.clear();
    setOverlayLoading(null);
    setOverlayCount({ sessionId, count: 0 });
    setOverlayNotice({ sessionId, message: "Investigation overlays cleared.", error: false });
  }

  return (
    <section
      aria-label="SatQuery command center"
      data-satquery-agent
      data-expanded={expanded}
      className={`pointer-events-auto flex max-h-[min(78vh,52rem)] flex-col overflow-hidden border border-white/10 bg-surface/95 shadow-2xl shadow-black/50 backdrop-blur-2xl transition-[width,height,border-radius] duration-200 ${
        expanded
          ? "absolute bottom-[calc(100%+0.75rem)] right-0 h-[min(68vh,44rem)] w-[min(46rem,calc(100vw_-_2rem))] rounded-3xl"
          : "relative w-full rounded-xl"
      }`}
    >
      <header className="flex items-center justify-between border-b border-white/10 px-5 py-3">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-ink-dim">
            Altas · Satellite Intelligence
          </p>
          <p className="mt-1 max-w-[min(28rem,60vw)] truncate text-xs text-ink-dim" role={error ? "alert" : status ? "status" : undefined}>
            {error ?? status ?? (expanded
              ? "Engine analysis, scientific execution, and evidence."
              : "Ask about the Earth or start an investigation.")}
          </p>
        </div>
        <div className="ml-3 flex shrink-0 items-center gap-2">
          <button
            type="button"
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink"
            onClick={openWorkspace}
            aria-label="Open SatQuery workspace"
          >
            Workspace
          </button>
          <button
            type="button"
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink"
            onClick={openProviderSettings}
            aria-label="Open provider settings"
          >
            Settings
          </button>
          <button
            type="button"
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse command center" : "Expand command center"}
          >
            {expanded ? "Collapse" : "Open"}
          </button>
          {busy && (
          <button
            type="button"
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
            onClick={() => void stopTurn()}
            disabled={canceling}
          >
            {canceling ? "Stopping..." : "Stop"}
          </button>
          )}
        </div>
      </header>

      {expanded && (
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
        <VisionAttachments />
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
            {sessionId && message.imageAssetIds && message.imageAssetIds.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {message.imageAssetIds.map((assetId) => (
                  <img
                    key={assetId}
                    src={imageContentUrl(sessionId, assetId, true)}
                    alt="Attached image"
                    className="max-h-40 max-w-48 rounded-lg object-contain"
                  />
                ))}
              </div>
            )}
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
        {visibleActivity.length > 0 && (
          <section
            aria-label="Investigation activity"
            className="rounded-xl border border-white/10 p-3"
          >
            <h2 className="text-xs font-medium text-ink">Investigation activity</h2>
            <ol aria-live="polite" className="mt-2 space-y-1">
              {visibleActivity.map((item) => (
                <li key={item.id} className="text-xs text-ink-dim">
                  <time dateTime={item.at}>{formatInvestigationEventType(item.eventType)}</time>
                </li>
              ))}
            </ol>
          </section>
        )}
        {visibleInvestigationIds.length > 0 && (
          <section
            aria-label="Investigation reports"
            className="rounded-xl border border-white/10 p-3"
          >
            <header className="flex items-center justify-between gap-2">
              <h2 className="text-xs font-medium text-ink">Engine investigation reports</h2>
              {(visibleOverlayCount > 0 || visibleOverlayLoadingId !== null) && (
                <button
                  type="button"
                  className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] text-ink-dim hover:text-ink"
                  onClick={clearInvestigationOverlays}
                >
                  Clear map
                </button>
              )}
            </header>
            <ul className="mt-2 flex flex-wrap gap-2">
              {visibleInvestigationIds.map((investigationId) => (
                <li key={investigationId}>
                  <button
                    type="button"
                    className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
                    onClick={() => void showInvestigationReport(investigationId)}
                    disabled={visibleReportLoadingId !== null}
                  >
                    {visibleReportLoadingId === investigationId
                      ? "Loading report..."
                      : `View ${investigationId}`}
                  </button>
                  <button
                    type="button"
                    className="ml-1 rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
                    onClick={() => void showInvestigationOnEarth(investigationId)}
                    disabled={visibleOverlayLoadingId !== null}
                  >
                    {visibleOverlayLoadingId === investigationId
                      ? "Loading map data..."
                      : "Show on Earth"}
                  </button>
                  <button
                    type="button"
                    className="ml-1 rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink disabled:opacity-50"
                    aria-expanded={
                      visibleInvestigationHistory?.investigationId === investigationId
                    }
                    onClick={() => {
                      if (
                        visibleInvestigationHistory?.investigationId === investigationId
                      ) {
                        setInvestigationHistory(null);
                        return;
                      }
                      void loadInvestigationHistory(investigationId);
                    }}
                    disabled={historyLoadingId !== null}
                  >
                    {historyLoadingId === investigationId
                      ? "Loading activity..."
                      : visibleInvestigationHistory?.investigationId === investigationId
                        ? "Hide activity"
                        : "Activity"}
                  </button>
                </li>
              ))}
            </ul>
            {visibleInvestigationHistory && (
              <section
                aria-label={`Investigation activity ${visibleInvestigationHistory.investigationId}`}
                className="mt-3 rounded-lg bg-black/20 p-3"
              >
                <h3 className="text-xs font-medium text-ink">Execution history</h3>
                <ol className="mt-2 space-y-1">
                  {visibleInvestigationHistory.items.map((item) => (
                    <li key={item.id} className="text-xs text-ink-dim">
                      <time dateTime={item.at}>
                        {formatInvestigationEventType(item.eventType)}
                      </time>
                    </li>
                  ))}
                </ol>
                {visibleInvestigationHistory.items.length === 0 &&
                  historyLoadingId !== visibleInvestigationHistory.investigationId && (
                    <p className="mt-2 text-xs text-ink-dim">
                      No execution events are available for this investigation yet.
                    </p>
                  )}
                {visibleInvestigationHistory.hasMore && (
                  <button
                    type="button"
                    className="mt-2 rounded-full border border-white/10 px-3 py-1.5 text-[10px] text-ink-dim hover:text-ink disabled:opacity-50"
                    onClick={() =>
                      void loadInvestigationHistory(
                        visibleInvestigationHistory.investigationId,
                        true,
                      )
                    }
                    disabled={historyLoadingId !== null}
                  >
                    {historyLoadingId === visibleInvestigationHistory.investigationId
                      ? "Loading..."
                      : "Load more"}
                  </button>
                )}
                {visibleHistoryError?.investigationId ===
                  visibleInvestigationHistory.investigationId && (
                  <p className="mt-2 text-xs text-rose-200" role="alert">
                    {visibleHistoryError.message}
                  </p>
                )}
              </section>
            )}
            {reportError?.sessionId === sessionId && (
              <p className="mt-2 text-xs text-rose-200" role="alert">
                {reportError.message}
              </p>
            )}
            {overlayNotice?.sessionId === sessionId && (
              <p
                className={`mt-2 text-xs ${overlayNotice.error ? "text-rose-200" : "text-ink-dim"}`}
                role={overlayNotice.error ? "alert" : "status"}
              >
                {overlayNotice.message}
              </p>
            )}
            {visibleReport && (
              <article className="mt-3 max-h-80 overflow-y-auto rounded-lg bg-black/20 p-3">
                <h3 className="text-xs font-medium text-ink">
                  Investigation report {visibleReport.report.report_id}
                </h3>
                <pre className="mt-2 whitespace-pre-wrap break-words font-sans text-xs leading-5 text-ink-dim">
                  {visibleReport.report.markdown}
                </pre>
              </article>
            )}
          </section>
        )}
      </div>
      )}

      <form
        className={`${expanded ? "border-t border-white/10" : ""} p-3`}
        onSubmit={(event) => void submit(event)}
      >
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
          rows={expanded ? 2 : 1}
          className="w-full resize-none bg-transparent px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-dim disabled:opacity-50"
        />
        <div className="flex items-center justify-between gap-3 px-2 pb-1">
          <button
            type="button"
            className="rounded-full border border-white/10 px-3 py-2 text-xs text-ink-dim hover:text-ink"
            onClick={() => {
              setVisionPanelOpen(true);
              setExpanded(true);
            }}
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
            {attachments.length ? "Send with images" : "Send"}
          </button>
        </div>
      </form>
    </section>
  );
}
