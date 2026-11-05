import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "@/services/api/client";
import {
  createProject,
  createProjectSession,
  listProjectSessions,
  listProjects,
  listUnlinkedSessions,
} from "@/services/api/projects";
import { createSession } from "@/services/api/sessions";
import type { Project, ProjectSessionLink, Session } from "@/shared/types";
import { useSessionStore } from "@/state/sessionStore";

type ProjectEntry = {
  project: Project;
  sessions: ProjectSessionLink[];
};

export function isProjectSubmissionDisabled(title: string, submitting: boolean): boolean {
  return submitting || !title.trim();
}

async function loadWorkspace(signal?: AbortSignal): Promise<{
  projects: ProjectEntry[];
  sessions: Session[];
}> {
  const [currentProjects, unlinkedSessions] = await Promise.all([
    listProjects(signal),
    listUnlinkedSessions(signal),
  ]);
  const projectEntries = await Promise.all(
    currentProjects.map(async (project) => ({
      project,
      sessions: await listProjectSessions(project.id, signal),
    })),
  );
  return { projects: projectEntries, sessions: unlinkedSessions };
}

function messageFromError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Could not connect to the Platform API.";
}

export function SessionSidebar({ embedded = false }: { embedded?: boolean }) {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [projectFormOpen, setProjectFormOpen] = useState(false);
  const [submittingProject, setSubmittingProject] = useState(false);
  const [projectTitle, setProjectTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const workspace = await loadWorkspace(signal);
      if (signal?.aborted) return;
      setProjects(workspace.projects);
      setSessions(workspace.sessions);
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
    loadWorkspace(controller.signal)
      .then((workspace) => {
        if (controller.signal.aborted) return;
        setProjects(workspace.projects);
        setSessions(workspace.sessions);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(messageFromError(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const handleProjectsUpdated = () => void refresh();
    window.addEventListener("satquery:projects-updated", handleProjectsUpdated);
    return () => window.removeEventListener("satquery:projects-updated", handleProjectsUpdated);
  }, [refresh]);

  async function handleCreateSession() {
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

  async function handleCreateProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = projectTitle.trim();
    if (!title) return;
    setSubmittingProject(true);
    setError(null);
    try {
      const project = await createProject({ title, description: null });
      setProjectTitle("");
      setProjectFormOpen(false);
      setProjects((current) => [{ project, sessions: [] }, ...current]);
      navigate(`/p/${encodeURIComponent(project.id)}`);
    } catch (reason) {
      setError(messageFromError(reason));
    } finally {
      setSubmittingProject(false);
    }
  }

  async function handleCreateProjectSession(projectId: string) {
    setCreating(true);
    setError(null);
    try {
      const link = await createProjectSession(projectId);
      setProjects((current) =>
        current.map((entry) =>
          entry.project.id === projectId
            ? { ...entry, sessions: [...entry.sessions, link] }
            : entry,
        ),
      );
      navigate(`/s/${encodeURIComponent(link.session_id)}`);
    } catch (reason) {
      setError(messageFromError(reason));
    } finally {
      setCreating(false);
    }
  }

  return (
    <section
      aria-label="Investigation workspace"
      className={
        embedded
          ? "flex min-h-0 w-full flex-col overflow-hidden text-ink"
          : "pointer-events-auto flex max-h-[min(72vh,48rem)] w-72 flex-col overflow-hidden rounded-2xl border border-white/10 bg-surface shadow-2xl shadow-black/40 backdrop-blur-xl"
      }
    >
      <header className="border-b border-white/10 px-4 py-3">
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-ink-dim">
          Investigation workspace
        </p>
        <h1 className="mt-1 text-sm font-semibold text-ink">Earth Intelligence</h1>
        <button
          type="button"
          onClick={() => void handleCreateSession()}
          disabled={creating}
          aria-label="Create standalone session"
          className="mt-3 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-ink transition hover:border-accent/50 hover:bg-white/5 disabled:cursor-wait disabled:opacity-50"
        >
          {creating ? "Creating..." : "New session"}
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <div className="flex items-center justify-between px-2 pb-2 pt-1">
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
            Projects
          </p>
          <button
            type="button"
            onClick={() => setProjectFormOpen((current) => !current)}
            className="text-xs text-accent hover:text-ink"
          >
            New project
          </button>
        </div>
        {projectFormOpen && (
          <form onSubmit={(event) => void handleCreateProject(event)} className="mb-2 flex gap-1">
            <input
              autoFocus
              aria-label="Project name"
              maxLength={160}
              value={projectTitle}
              onChange={(event) => setProjectTitle(event.target.value)}
              placeholder="Project name"
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-2 py-1.5 text-xs text-ink outline-none focus:border-accent/60"
            />
            <button
              type="submit"
              disabled={isProjectSubmissionDisabled(projectTitle, submittingProject)}
              className="rounded-lg border border-white/10 px-2 py-1.5 text-xs text-ink disabled:opacity-50"
            >
              {submittingProject ? "Adding..." : "Add"}
            </button>
          </form>
        )}
        {loading && (
          <p className="px-2 py-3 text-xs text-ink-dim" role="status">
            Loading workspace...
          </p>
        )}
        {!loading && projects.length === 0 && !error && (
          <p className="px-2 py-2 text-xs leading-5 text-ink-dim">
            Create a project to organize related investigations and sessions.
          </p>
        )}
        <nav aria-label="Projects" className="space-y-1">
          {projects.map(({ project, sessions: projectSessions }) => (
            <div key={project.id} className="rounded-xl">
              <div className="flex items-center gap-1">
                <Link
                  to={`/p/${encodeURIComponent(project.id)}`}
                  className="min-w-0 flex-1 truncate rounded-lg px-3 py-2 text-sm text-ink hover:bg-white/5"
                >
                  {project.title}
                  {project.archived ? " (archived)" : ""}
                </Link>
                {!project.archived && (
                  <button
                    type="button"
                    aria-label={`Create session in ${project.title}`}
                    disabled={creating}
                    onClick={() => void handleCreateProjectSession(project.id)}
                    className="rounded-md px-2 py-1 text-xs text-ink-dim hover:bg-white/10 hover:text-ink disabled:opacity-50"
                  >
                    +
                  </button>
                )}
              </div>
              <nav aria-label={`${project.title} sessions`} className="ml-3 space-y-0.5">
                {projectSessions.map(({ session }) => (
                  <Link
                    key={session.id}
                    to={`/s/${encodeURIComponent(session.id)}`}
                    aria-current={session.id === activeSessionId ? "page" : undefined}
                    className={`block truncate rounded-lg px-3 py-1.5 text-xs transition ${
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
          ))}
        </nav>

        <p className="px-2 pb-2 pt-4 text-[10px] font-medium uppercase tracking-[0.16em] text-ink-dim">
          Unlinked sessions
        </p>
        {!loading && sessions.length === 0 && !error && (
          <p className="px-2 py-2 text-xs text-ink-dim">No unlinked sessions.</p>
        )}
        <nav aria-label="Unlinked sessions" className="space-y-1">
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
