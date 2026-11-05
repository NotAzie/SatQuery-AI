import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import { useEarthController } from "@/hooks/useEarth";
import { snapshotEarthContext, useEarthStore } from "@/state/earthStore";
import { useSessionStore } from "@/state/sessionStore";
import { EngineDiscoveryPanel } from "@/features/earth/EngineDiscoveryPanel";
import { MonitoringPanel } from "@/features/monitoring/MonitoringPanel";
import { SessionSidebar } from "@/features/sessions/SessionSidebar";

export interface WorkspaceDrawerState {
  open: boolean;
  openWorkspace: () => void;
  closeWorkspace: () => void;
}

const WorkspaceDrawerContext = createContext<WorkspaceDrawerState | null>(null);

export function WorkspaceDrawerProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const openWorkspace = useCallback(() => setOpen(true), []);
  const closeWorkspace = useCallback(() => setOpen(false), []);
  const value = { open, openWorkspace, closeWorkspace };

  return (
    <WorkspaceDrawerContext.Provider value={value}>{children}</WorkspaceDrawerContext.Provider>
  );
}

export function useWorkspaceDrawer(): WorkspaceDrawerState {
  const state = useContext(WorkspaceDrawerContext);
  if (!state) throw new Error("WorkspaceDrawerStateProvider is missing.");
  return state;
}

type WorkspaceSection = "projects" | "saved-views" | "monitoring" | "engine";

const sections: { id: WorkspaceSection; label: string }[] = [
  { id: "projects", label: "Projects" },
  { id: "saved-views", label: "Saved views" },
  { id: "monitoring", label: "Monitoring" },
  { id: "engine", label: "Engine" },
];

export function SatQueryWorkspaceDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [section, setSection] = useState<WorkspaceSection>("projects");

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div
      className="pointer-events-auto fixed inset-0 z-[200] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="satquery-workspace-title"
        className="flex max-h-[min(84vh,52rem)] w-[min(34rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-white/10 bg-surface text-ink shadow-2xl shadow-black/60"
      >
        <header className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
              SatQuery
            </p>
            <h2 id="satquery-workspace-title" className="mt-1 text-sm font-semibold">
              Workspace
            </h2>
          </div>
          <button
            type="button"
            autoFocus
            aria-label="Close workspace"
            onClick={onClose}
            className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-ink-dim hover:text-ink"
          >
            Close
          </button>
        </header>
        <nav
          aria-label="Workspace sections"
          className="flex gap-1 overflow-x-auto border-b border-white/10 p-2"
        >
          {sections.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={section === item.id}
              onClick={() => setSection(item.id)}
              className={`shrink-0 rounded-lg px-3 py-2 text-xs ${
                section === item.id
                  ? "bg-white/10 text-ink"
                  : "text-ink-dim hover:bg-white/5 hover:text-ink"
              }`}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="min-h-0 overflow-y-auto p-4">
          {section === "projects" && <SessionSidebar embedded />}
          {section === "saved-views" && <SavedEarthViews />}
          {section === "monitoring" && <MonitoringPanel embedded />}
          {section === "engine" && <EngineDiscoveryPanel embedded />}
        </div>
      </section>
    </div>
  );
}

function SavedEarthViews() {
  const bookmarks = useSessionStore((state) => state.bookmarks);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const persistenceError = useSessionStore((state) => state.persistenceError);
  const addBookmark = useSessionStore((state) => state.addBookmark);
  const renameBookmark = useSessionStore((state) => state.renameBookmark);
  const updateBookmark = useSessionStore((state) => state.updateBookmark);
  const deleteBookmark = useSessionStore((state) => state.deleteBookmark);
  const earth = useEarthController();
  const camera = useEarthStore((state) => state.camera);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const context = snapshotEarthContext();
    if (!context) {
      setError("The Earth camera is not ready yet.");
      return;
    }
    try {
      addBookmark(name, context);
      setName("");
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save this view.");
    }
  }

  return (
    <section aria-label="Saved Earth views" className="space-y-3">
      <div>
        <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
          Session views
        </p>
        <p className="mt-1 text-xs text-ink-dim">
          Save a camera and EarthContext snapshot to this SatQuery session.
        </p>
      </div>
      <form onSubmit={save} className="flex gap-2">
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          aria-label="Saved view name"
          placeholder="Name this view"
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs"
        />
        <button
          type="submit"
          disabled={!activeSessionId || !camera || !name.trim()}
          className="rounded-lg border border-white/10 px-3 py-2 text-xs disabled:opacity-40"
        >
          Save
        </button>
      </form>
      {bookmarks.length ? (
        <ul className="space-y-2">
          {bookmarks.map((bookmark) => (
            <li key={bookmark.id} className="rounded-xl border border-white/10 p-3">
              <p className="truncate text-xs font-medium">{bookmark.name}</p>
              <p className="mt-1 text-[10px] text-ink-dim">
                {bookmark.context.camera.position.lat.toFixed(3)},{" "}
                {bookmark.context.camera.position.lng.toFixed(3)}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="rounded-md border border-white/10 px-2 py-1 text-[10px]"
                  onClick={() => earth?.camera.restore(bookmark.context.camera)}
                >
                  Fly to
                </button>
                <button
                  type="button"
                  className="rounded-md border border-white/10 px-2 py-1 text-[10px]"
                  onClick={() => {
                    const nextName = window.prompt("Rename saved view", bookmark.name);
                    try {
                      if (nextName === null) return;
                      renameBookmark(bookmark.id, nextName);
                      setError(null);
                    } catch (reason) {
                      setError(reason instanceof Error ? reason.message : "Could not rename view.");
                    }
                  }}
                >
                  Rename
                </button>
                <button
                  type="button"
                  className="rounded-md border border-white/10 px-2 py-1 text-[10px]"
                  onClick={() => {
                    const context = snapshotEarthContext();
                    if (!context) return;
                    try {
                      updateBookmark(bookmark.id, context);
                      setError(null);
                    } catch (reason) {
                      setError(reason instanceof Error ? reason.message : "Could not update view.");
                    }
                  }}
                >
                  Update
                </button>
                <button
                  type="button"
                  className="rounded-md border border-rose-300/20 px-2 py-1 text-[10px] text-rose-200"
                  onClick={() => {
                    try {
                      deleteBookmark(bookmark.id);
                      setError(null);
                    } catch (reason) {
                      setError(reason instanceof Error ? reason.message : "Could not delete view.");
                    }
                  }}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-ink-dim">No saved views in this session.</p>
      )}
      {(error || persistenceError) && (
        <p role="alert" className="text-xs text-rose-200">
          {error ?? persistenceError}
        </p>
      )}
    </section>
  );
}
