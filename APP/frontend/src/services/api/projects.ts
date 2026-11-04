import type {
  EarthBookmark,
  Project,
  ProjectActivity,
  ProjectCreate,
  ProjectEarthView,
  ProjectEarthViewCreate,
  ProjectInvestigationComparison,
  ProjectInvestigationComparisonCreate,
  ProjectInvestigationRef,
  EngineInvestigationComparison,
  ProjectNote,
  ProjectNoteCreate,
  ProjectNoteUpdate,
  ProjectMonitoringLink,
  ProjectSessionLink,
  ProjectUpdate,
  Session,
} from "@/shared/types";

import { apiFetch, apiFetchVoid } from "./client";
import { getSession, updateSessionEarthWorkspace } from "./sessions";

export function listProjects(signal?: AbortSignal): Promise<Project[]> {
  return apiFetch<Project[]>("/projects", { signal });
}

export function getProject(projectId: string, signal?: AbortSignal): Promise<Project> {
  return apiFetch<Project>(`/projects/${encodeURIComponent(projectId)}`, { signal });
}

export function createProject(body: ProjectCreate): Promise<Project> {
  return apiFetch<Project>("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateProject(
  projectId: string,
  body: ProjectUpdate,
): Promise<Project> {
  return apiFetch<Project>(`/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listProjectSessions(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectSessionLink[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectSessionLink[]>(
    `/projects/${encodeURIComponent(projectId)}/sessions?${query}`,
    { signal },
  );
}

export function listProjectInvestigations(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectInvestigationRef[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectInvestigationRef[]>(
    `/projects/${encodeURIComponent(projectId)}/investigations?${query}`,
    { signal },
  );
}

export function getProjectInvestigation(
  projectId: string,
  sessionId: string,
  investigationId: string,
  signal?: AbortSignal,
): Promise<ProjectInvestigationRef> {
  const query = new URLSearchParams({ session_id: sessionId });
  return apiFetch<ProjectInvestigationRef>(
    `/projects/${encodeURIComponent(projectId)}/investigations/${encodeURIComponent(investigationId)}?${query}`,
    { signal },
  );
}

export function listProjectInvestigationComparisons(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectInvestigationComparison[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectInvestigationComparison[]>(
    `/projects/${encodeURIComponent(projectId)}/comparisons?${query}`,
    { signal },
  );
}

export function getProjectInvestigationComparison(
  projectId: string,
  comparisonId: string,
  signal?: AbortSignal,
): Promise<ProjectInvestigationComparison> {
  return apiFetch<ProjectInvestigationComparison>(
    `/projects/${encodeURIComponent(projectId)}/comparisons/${encodeURIComponent(comparisonId)}`,
    { signal },
  );
}

export function getProjectInvestigationComparisonResult(
  projectId: string,
  comparisonId: string,
  signal?: AbortSignal,
): Promise<EngineInvestigationComparison> {
  return apiFetch<EngineInvestigationComparison>(
    `/projects/${encodeURIComponent(projectId)}/comparisons/${encodeURIComponent(comparisonId)}/engine-result`,
    { signal },
  );
}

export function createProjectInvestigationComparison(
  projectId: string,
  body: ProjectInvestigationComparisonCreate,
): Promise<ProjectInvestigationComparison> {
  return apiFetch<ProjectInvestigationComparison>(
    `/projects/${encodeURIComponent(projectId)}/comparisons`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteProjectInvestigationComparison(
  projectId: string,
  comparisonId: string,
): Promise<void> {
  return apiFetchVoid(
    `/projects/${encodeURIComponent(projectId)}/comparisons/${encodeURIComponent(comparisonId)}`,
    { method: "DELETE" },
  );
}

export async function listProjectWorkPage(
  projectId: string,
  signal: AbortSignal | undefined,
  limit: number,
  offset: number,
): Promise<{ sessions: ProjectSessionLink[]; investigations: ProjectInvestigationRef[] }> {
  const [sessions, investigations] = await Promise.all([
    listProjectSessions(projectId, signal, limit, offset),
    listProjectInvestigations(projectId, signal, limit, offset),
  ]);
  return { sessions, investigations };
}

export function listProjectActivity(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectActivity[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectActivity[]>(
    `/projects/${encodeURIComponent(projectId)}/activity?${query}`,
    { signal },
  );
}

export function listProjectNotes(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
  scope?: { investigation_id: string; investigation_session_id: string },
): Promise<ProjectNote[]> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    ...(scope ?? {}),
  });
  return apiFetch<ProjectNote[]>(
    `/projects/${encodeURIComponent(projectId)}/notes?${query}`,
    { signal },
  );
}

export function createProjectNote(
  projectId: string,
  body: ProjectNoteCreate,
): Promise<ProjectNote> {
  return apiFetch<ProjectNote>(`/projects/${encodeURIComponent(projectId)}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateProjectNote(
  projectId: string,
  noteId: string,
  body: ProjectNoteUpdate,
): Promise<ProjectNote> {
  return apiFetch<ProjectNote>(
    `/projects/${encodeURIComponent(projectId)}/notes/${encodeURIComponent(noteId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteProjectNote(projectId: string, noteId: string): Promise<void> {
  return apiFetchVoid(
    `/projects/${encodeURIComponent(projectId)}/notes/${encodeURIComponent(noteId)}`,
    { method: "DELETE" },
  );
}

export function listProjectViews(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
  scope?: { investigation_id: string; source_session_id: string },
): Promise<ProjectEarthView[]> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    ...(scope ?? {}),
  });
  return apiFetch<ProjectEarthView[]>(
    `/projects/${encodeURIComponent(projectId)}/views?${query}`,
    { signal },
  );
}

export function createProjectView(
  projectId: string,
  body: ProjectEarthViewCreate,
): Promise<ProjectEarthView> {
  return apiFetch<ProjectEarthView>(`/projects/${encodeURIComponent(projectId)}/views`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteProjectView(projectId: string, viewId: string): Promise<void> {
  return apiFetchVoid(
    `/projects/${encodeURIComponent(projectId)}/views/${encodeURIComponent(viewId)}`,
    { method: "DELETE" },
  );
}

export async function restoreProjectEarthView(
  view: ProjectEarthView,
): Promise<{ sessionId: string; bookmarkId: string }> {
  const session = await getSession(view.source_session_id);
  const existingBookmark = session.earth_workspace.bookmarks.find(
    (bookmark) =>
      bookmark.name === view.title &&
      JSON.stringify(bookmark.context) === JSON.stringify(view.context),
  );
  if (existingBookmark) {
    return { sessionId: session.id, bookmarkId: existingBookmark.id };
  }

  const timestamp = new Date().toISOString();
  const bookmark: EarthBookmark = {
    id: globalThis.crypto.randomUUID(),
    name: view.title,
    context: view.context,
    created_at: timestamp,
    updated_at: timestamp,
  };
  await updateSessionEarthWorkspace(session.id, {
    ...session.earth_workspace,
    camera_history: view.context.camera_history,
    captures: view.context.captures,
    bookmarks: [...session.earth_workspace.bookmarks, bookmark],
  });
  return { sessionId: session.id, bookmarkId: bookmark.id };
}

export function listProjectMonitoringLinks(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectMonitoringLink[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectMonitoringLink[]>(
    `/projects/${encodeURIComponent(projectId)}/monitoring-links?${query}`,
    { signal },
  );
}

export function linkProjectMonitoringSchedule(
  projectId: string,
  scheduleId: string,
): Promise<ProjectMonitoringLink> {
  return apiFetch<ProjectMonitoringLink>(
    `/projects/${encodeURIComponent(projectId)}/monitoring-links`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schedule_id: scheduleId }),
    },
  );
}

export function unlinkProjectMonitoringSchedule(
  projectId: string,
  scheduleId: string,
): Promise<void> {
  return apiFetchVoid(
    `/projects/${encodeURIComponent(projectId)}/monitoring-links/${encodeURIComponent(scheduleId)}`,
    { method: "DELETE" },
  );
}

export function createProjectSession(projectId: string): Promise<ProjectSessionLink> {
  return apiFetch<ProjectSessionLink>(`/projects/${encodeURIComponent(projectId)}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
}

export function linkProjectSession(
  projectId: string,
  sessionId: string,
): Promise<ProjectSessionLink> {
  return apiFetch<ProjectSessionLink>(`/projects/${encodeURIComponent(projectId)}/sessions/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export function listUnlinkedSessions(signal?: AbortSignal): Promise<Session[]> {
  return apiFetch<Session[]>("/projects/unlinked-sessions", { signal });
}
