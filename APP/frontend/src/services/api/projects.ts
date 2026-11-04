import type {
  EarthBookmark,
  Project,
  ProjectActivity,
  ProjectCreate,
  ProjectEarthView,
  ProjectEarthViewCreate,
  ProjectInvestigationComparison,
  ProjectInvestigationComparisonCreate,
  ProjectInvestigationCollection,
  ProjectInvestigationCollectionCreate,
  ProjectInvestigationCollectionMemberUpdate,
  ProjectInvestigationCollectionUpdate,
  ProjectInvestigationRef,
  ProjectInvestigationRelationship,
  ProjectInvestigationRelationshipCreate,
  ProjectInvestigationTemplate,
  ProjectInvestigationTemplateCreate,
  ProjectInvestigationTemplateRun,
  ProjectInvestigationTemplateRunUpdate,
  ProjectInvestigationTemplateUpdate,
  EngineInvestigationComparison,
  ProjectNote,
  ProjectNoteCreate,
  ProjectNoteUpdate,
  ProjectMonitoringLink,
  ProjectSessionLink,
  ProjectSearchResponse,
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

export function searchProject(
  projectId: string,
  query: string,
  signal?: AbortSignal,
  limit = 20,
  offset = 0,
): Promise<ProjectSearchResponse> {
  const params = new URLSearchParams({
    query,
    limit: String(limit),
    offset: String(offset),
  });
  return apiFetch<ProjectSearchResponse>(
    `/projects/${encodeURIComponent(projectId)}/search?${params}`,
    { signal },
  );
}

export function listProjectInvestigationRelationships(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectInvestigationRelationship[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectInvestigationRelationship[]>(
    `/projects/${encodeURIComponent(projectId)}/investigation-relationships?${query}`,
    { signal },
  );
}

export function createProjectInvestigationRelationship(
  projectId: string,
  body: ProjectInvestigationRelationshipCreate,
): Promise<ProjectInvestigationRelationship> {
  return apiFetch<ProjectInvestigationRelationship>(
    `/projects/${encodeURIComponent(projectId)}/investigation-relationships`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteProjectInvestigationRelationship(
  projectId: string,
  relationshipId: string,
): Promise<void> {
  return apiFetchVoid(
    `/projects/${encodeURIComponent(projectId)}/investigation-relationships/${encodeURIComponent(relationshipId)}`,
    { method: "DELETE" },
  );
}

export function listProjectInvestigationCollections(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectInvestigationCollection[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectInvestigationCollection[]>(
    `/projects/${encodeURIComponent(projectId)}/investigation-collections?${query}`,
    { signal },
  );
}

export function createProjectInvestigationCollection(
  projectId: string,
  body: ProjectInvestigationCollectionCreate,
): Promise<ProjectInvestigationCollection> {
  return apiFetch<ProjectInvestigationCollection>(
    `/projects/${encodeURIComponent(projectId)}/investigation-collections`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function updateProjectInvestigationCollection(
  projectId: string,
  collectionId: string,
  body: ProjectInvestigationCollectionUpdate,
): Promise<ProjectInvestigationCollection> {
  return apiFetch<ProjectInvestigationCollection>(
    `/projects/${encodeURIComponent(projectId)}/investigation-collections/${encodeURIComponent(collectionId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function updateProjectInvestigationCollectionMembers(
  projectId: string,
  collectionId: string,
  body: ProjectInvestigationCollectionMemberUpdate,
): Promise<ProjectInvestigationCollection> {
  return apiFetch<ProjectInvestigationCollection>(
    `/projects/${encodeURIComponent(projectId)}/investigation-collections/${encodeURIComponent(collectionId)}/members`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteProjectInvestigationCollection(
  projectId: string,
  collectionId: string,
): Promise<void> {
  return apiFetchVoid(
    `/projects/${encodeURIComponent(projectId)}/investigation-collections/${encodeURIComponent(collectionId)}`,
    { method: "DELETE" },
  );
}

export function listProjectInvestigationTemplates(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectInvestigationTemplate[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectInvestigationTemplate[]>(
    `/projects/${encodeURIComponent(projectId)}/investigation-templates?${query}`,
    { signal },
  );
}

export function createProjectInvestigationTemplate(
  projectId: string,
  body: ProjectInvestigationTemplateCreate,
): Promise<ProjectInvestigationTemplate> {
  return apiFetch<ProjectInvestigationTemplate>(
    `/projects/${encodeURIComponent(projectId)}/investigation-templates`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function updateProjectInvestigationTemplate(
  projectId: string,
  templateId: string,
  body: ProjectInvestigationTemplateUpdate,
): Promise<ProjectInvestigationTemplate> {
  return apiFetch<ProjectInvestigationTemplate>(
    `/projects/${encodeURIComponent(projectId)}/investigation-templates/${encodeURIComponent(templateId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteProjectInvestigationTemplate(
  projectId: string,
  templateId: string,
): Promise<void> {
  return apiFetchVoid(
    `/projects/${encodeURIComponent(projectId)}/investigation-templates/${encodeURIComponent(templateId)}`,
    { method: "DELETE" },
  );
}

export function applyProjectInvestigationTemplate(
  projectId: string,
  templateId: string,
): Promise<ProjectInvestigationTemplateRun> {
  return apiFetch<ProjectInvestigationTemplateRun>(
    `/projects/${encodeURIComponent(projectId)}/investigation-templates/${encodeURIComponent(templateId)}/apply`,
    { method: "POST" },
  );
}

export function listProjectInvestigationTemplateRuns(
  projectId: string,
  signal?: AbortSignal,
  limit = 50,
  offset = 0,
): Promise<ProjectInvestigationTemplateRun[]> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return apiFetch<ProjectInvestigationTemplateRun[]>(
    `/projects/${encodeURIComponent(projectId)}/investigation-template-runs?${query}`,
    { signal },
  );
}

export function updateProjectInvestigationTemplateRun(
  projectId: string,
  runId: string,
  body: ProjectInvestigationTemplateRunUpdate,
): Promise<ProjectInvestigationTemplateRun> {
  return apiFetch<ProjectInvestigationTemplateRun>(
    `/projects/${encodeURIComponent(projectId)}/investigation-template-runs/${encodeURIComponent(runId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
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
  investigation?: ProjectInvestigationRef,
): Promise<ProjectActivity[]> {
  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    ...(investigation ?? {}),
  });
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
