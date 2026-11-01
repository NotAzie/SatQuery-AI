import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "@/services/api/client";
import { createSession, listSessions } from "@/services/api/sessions";
import type { Session } from "@/shared/types";
import { useSessionStore } from "@/state/sessionStore";

function messageFromError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Could not connect to the Platform API.";
}

export function SessionSidebar() {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const current = await listSessions(signal);
      setSessions(current);
      setError(null);
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(messageFromError(reason));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    listSessions(controller.signal)
      .then((current) => {
        if (!controller.signal.aborted) {
          setSessions(current);
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(messageFromError(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  async function handleCreate() {
    setCreating(true);
    setError(null);
    try {
      const session = await createSession();
      setSessions((current) => [session, ...current]);
      navigate(`/s/${encodeURIComponent(session.id)}`);
    } catch (reason) {
      setError(messageFromError(reason));
    } finally {
      setCreating(false);
    }
  }

  return (
    <section
      aria-label="Sessions"
      className="pointer-events-auto flex max-h-[min(72vh,48rem)] w-72 flex-col overflow-hidden rounded-2xl border border-white/10 bg-surface shadow-2xl shadow-black/40 backdrop-blur-xl"
    >
      <header className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-ink-dim">
            Workspace
          </p>
          <h1 className="mt-1 text-sm font-semibold text-ink">Earth Intelligence</h1>
        </div>
        <button
          type="button"
          onClick={() => void handleCreate()}
          disabled={creating}
          aria-label="Create session"
          className="rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-ink transition hover:border-accent/50 hover:bg-white/5 disabled:cursor-wait disabled:opacity-50"
        >
          {creating ? "Creating..." : "New"}
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <p className="px-2 pb-2 pt-1 text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
          Recent sessions
        </p>
        {loading && (
          <p className="px-2 py-3 text-xs text-ink-dim" role="status">
            Loading sessions...
          </p>
        )}
        {!loading && sessions.length === 0 && !error && (
          <p className="px-2 py-3 text-xs leading-5 text-ink-dim">
            No sessions yet. Create one to start a workspace.
          </p>
        )}
        <nav aria-label="Recent sessions" className="space-y-1">
          {sessions.map((session) => (
            <Link
              key={session.id}
              to={`/s/${encodeURIComponent(session.id)}`}
              aria-current={session.id === activeSessionId ? "page" : undefined}
              className={`block truncate rounded-xl px-3 py-2.5 text-sm transition ${
                session.id === activeSessionId
                  ? "bg-white/10 text-ink"
                  : "text-ink-dim hover:bg-white/5 hover:text-ink"
              }`}
            >
              {session.title || "Untitled session"}
            </Link>
          ))}
        </nav>
      </div>

      {error && (
        <div className="border-t border-rose-300/15 px-4 py-3 text-xs text-rose-200" role="alert">
          {error}
          <button
            type="button"
            className="ml-2 underline underline-offset-2"
            onClick={() => {
              setLoading(true);
              void refresh();
            }}
          >
            Retry
          </button>
        </div>
      )}
      <footer className="border-t border-white/10 px-4 py-2.5 text-[10px] text-ink-dim">
        SatQuery Engine provides analysis and evidence.
      </footer>
    </section>
  );
}
